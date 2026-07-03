#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Stranded-patch detector — flag text-patches whose target file(s) vanished.

Root-cause gate for the P12 class of silent failure. When upstream RENAMES or
MOVES a file a Genesis text-patch targets (e.g. dev714 split
``mamba/gdn_linear_attn.py`` into ``mamba/gdn/{qwen,olmo,kimi}_gdn_linear_attn``
and moved ``reasoning/qwen3_reasoning_parser.py`` into the ``parser/engine``
adapter), ``resolve_vllm_file()`` returns None, the patch's ``apply()`` returns
a benign INFO-level "skipped: file not found", and the fix silently stops
applying. The anchor-drift watcher CANNOT catch this: a file that is gone has no
anchor entry to drift, so a wholly-relocated target is invisible to it.

This gate closes that hole. For every patch module it statically collects the
paths passed to ``resolve_vllm_file(...)`` — both string literals and
module-level ``_TARGET*``-style string constants — and checks them against an
installed vLLM tree (``--vllm-root``). A module is **fully stranded** iff it has
at least one resolvable target AND every one of them is missing (so a patch that
also targets a path that DOES exist — e.g. the GDN patches that fall back to the
new ``mamba/gdn/`` split — is correctly NOT flagged). Partially-stranded modules
(some targets present, some gone) are reported separately as a softer signal.

A missing target is EXPECTED — not a finding — when the patch is documented as
not-for-this-pin. Two excuse mechanisms are honored automatically (preferred
over the ``KNOWN_STRANDED`` allowlist):
  * ``lifecycle == "retired"`` — the patch is intentionally dead.
  * an ``applies_to.vllm_version_range`` that EXCLUDES the current pin — the
    patch's target legitimately does not exist on a pin it never claims to
    support (this is how the 2026-06-19 audit disposed of the P12/P27/P61b/
    PN374 family after upstream #45413 deleted the old qwen3 reasoning/tool
    parsers). Only a patch whose range INCLUDES the current pin, whose target
    is nonetheless gone, is a genuine silent strand.

Whatever slips through those goes in ``KNOWN_STRANDED`` as a last resort.

Usage:
    python3 scripts/audit_patch_targets_exist.py --vllm-root /path/to/site-packages/vllm
    # operator, at pin bump, against the live container's install:
    #   docker cp scripts/audit_patch_targets_exist.py <ctr>:/tmp/ && \
    #   docker exec <ctr> python3 /tmp/audit_patch_targets_exist.py \
    #       --vllm-root /usr/local/lib/python3.12/dist-packages/vllm --patches-root <mounted repo>/sndr/engines/vllm/patches

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# Modules known to be stranded on the current pin and tracked for re-target /
# retirement — each MUST cite where the disposition is recorded. Keeps the gate
# green for reviewed cases while a genuinely-new strand fails loudly. Prefer a
# version-range cap (excused automatically) or lifecycle=retired over this
# allowlist; it is the last resort for a strand that is genuinely mid-triage.
KNOWN_STRANDED: dict[str, str] = {}


def _module_targets(tree: ast.AST) -> list[str]:
    """Collect the string paths passed to resolve_vllm_file(...) in a module.

    Handles two forms:
      resolve_vllm_file("literal/path.py")
      _TARGET = "literal/path.py"; resolve_vllm_file(_TARGET)
    Non-static args (f-strings, computed paths) are skipped — they cannot be
    checked statically, and a module with ANY unresolved arg is treated as
    "has an unknowable target" so it is never mis-flagged as fully stranded.
    """
    const_names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    const_names[tgt.id] = node.value.value

    targets: list[str] = []
    has_dynamic = False
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "resolve_vllm_file"):
            continue
        if not node.args:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            targets.append(arg.value)
        elif isinstance(arg, ast.Name) and arg.id in const_names:
            targets.append(const_names[arg.id])
        else:
            has_dynamic = True
    # Encode "has a dynamic target" as a sentinel so the caller never declares a
    # module fully stranded when part of its targeting is statically opaque.
    if has_dynamic:
        targets.append("<dynamic>")
    return targets


def _pin_out_of_range(pin: str, vrange) -> bool:
    """True iff ``pin`` falls OUTSIDE the ``(">=x", "<y")`` version range — i.e.
    the patch is documented as not-for-this-pin, so a missing target is
    intentional, not a surprise strand. Unparseable ⇒ False (don't excuse).
    """
    import re  # noqa: PLC0415

    from packaging.version import InvalidVersion  # noqa: PLC0415
    from packaging.version import parse as _v  # noqa: PLC0415
    if not vrange:
        return False
    try:
        pv = _v(pin)
    except InvalidVersion:
        return False
    ops = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b,
           ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
           "==": lambda a, b: a == b, "!=": lambda a, b: a != b}
    for constraint in vrange:
        mobj = re.match(r"\s*(<=|>=|==|!=|<|>)\s*(.+)", str(constraint))
        if not mobj:
            continue
        op, ver = mobj.group(1), mobj.group(2).strip()
        try:
            if not ops[op](pv, _v(ver)):
                return True  # pin violates a bound ⇒ out of range
        except InvalidVersion:
            continue
    return False


def _excused_module_stems(current_pin: str | None) -> dict[str, str]:
    """Map module stem (apply_module basename) → why it is excused from the
    strand check: lifecycle=retired (intentionally dead), or a
    vllm_version_range that excludes the current pin (documented not-for-this-
    pin). Best-effort: no registry ⇒ only KNOWN_STRANDED applies.
    """
    try:
        from sndr.dispatcher import PATCH_REGISTRY  # noqa: PLC0415
    except Exception:
        return {}
    out: dict[str, str] = {}
    for meta in PATCH_REGISTRY.values():
        if not isinstance(meta, dict):
            continue
        mod = meta.get("apply_module")
        if not (isinstance(mod, str) and mod):
            continue
        stem = mod.rsplit(".", 1)[-1]
        if meta.get("lifecycle") == "retired":
            out[stem] = "retired"
            continue
        vrange = (meta.get("applies_to") or {}).get("vllm_version_range")
        if current_pin and _pin_out_of_range(current_pin, vrange):
            out[stem] = f"version-capped out of {current_pin}"
    return out


def scan(patches_root: Path, vllm_root: Path, current_pin: str | None = None) -> dict:
    fully: list[tuple[str, list[str]]] = []
    partial: list[tuple[str, list[str], list[str]]] = []
    reg_excused = _excused_module_stems(current_pin)
    excused = set(KNOWN_STRANDED) | set(reg_excused)
    scanned = 0
    for py in sorted(patches_root.rglob("*.py")):
        if "__pycache__" in py.parts or py.name == "__init__.py":
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        targets = _module_targets(tree)
        static = [t for t in targets if t != "<dynamic>"]
        if not static:
            continue
        scanned += 1
        has_dynamic = "<dynamic>" in targets
        present = [t for t in static if (vllm_root / t).is_file()]
        missing = [t for t in static if not (vllm_root / t).is_file()]
        if not missing:
            continue
        stem = py.stem
        if not present and not has_dynamic:
            # Every static target gone AND no dynamic escape hatch -> fully inert.
            # A retired patch (or an allowlisted one) is EXPECTED inert; only an
            # active patch that silently stopped applying is a finding.
            if stem not in excused:
                fully.append((stem, missing))
        else:
            partial.append((stem, missing, present))
    return {"scanned": scanned, "fully": fully, "partial": partial,
            "reg_excused": len(reg_excused)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect text-patches whose target file(s) vanished on the pin")
    here = Path(__file__).resolve().parents[1]
    parser.add_argument("--patches-root", default=str(here / "sndr/engines/vllm/patches"))
    parser.add_argument("--vllm-root", required=True,
                        help="path to the installed vllm package to check targets against")
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero if any NEW fully-stranded module is found")
    parser.add_argument("--pin", default=None,
                        help="current vLLM pin (default: sndr.pins.current()); used "
                             "to excuse patches version-capped out of this pin")
    args = parser.parse_args(argv)

    vllm_root = Path(args.vllm_root)
    if not vllm_root.is_dir():
        print(f"✗ --vllm-root {vllm_root} is not a directory", file=sys.stderr)
        return 2

    current_pin = args.pin
    if current_pin is None:
        try:
            from sndr import pins
            current_pin = pins.current()
        except Exception:
            current_pin = None

    r = scan(Path(args.patches_root), vllm_root, current_pin)
    print("=== patch-target existence audit ===")
    print(f"  vllm root: {vllm_root}")
    print(f"  current pin: {current_pin or '(unknown — version excuse disabled)'}")
    print(f"  patch modules with static targets: {r['scanned']}")
    print(f"  excused: {len(KNOWN_STRANDED)} allowlisted + "
          f"{r.get('reg_excused', 0)} retired/version-capped")
    print()

    if r["fully"]:
        print(f"✗ FULLY STRANDED ({len(r['fully'])}) — every target missing, patch is INERT "
              "(silent 'file not found' skip; the drift watcher cannot see this):")
        for stem, missing in r["fully"]:
            print(f"    {stem}")
            for m in missing:
                print(f"        missing: {m}")
    else:
        print("✓ no NEW fully-stranded patches (all targets resolve, or are allowlisted)")

    if r["partial"]:
        print()
        print(f"⚠ partially stranded ({len(r['partial'])}) — SOME targets moved; the sub-patches "
              "on the missing files are inert while siblings still apply. Review:")
        for stem, missing, present in r["partial"]:
            print(f"    {stem}: {len(missing)} missing / {len(present)} present")
            for m in missing:
                print(f"        missing: {m}")

    if args.strict and r["fully"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
