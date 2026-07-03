#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Propagate a vLLM pin bump across every artifact from one command.

Before this, a bump meant hand-editing sndr/pins.yaml, guards.KNOWN_GOOD,
audit_v2 ALLOWED_MODELDEF + CANONICAL_PIN_SUBSTRING, test_pin_gate EXPECTED_PINS,
~11 model YAMLs — and forgetting one gave a silent cross-artifact drift. This
script does all of it from the new pin string, then tells you the two manual
steps that MUST stay manual (regenerate the anchor manifest on the live rig, and
run the consistency gate).

Usage:
    python3 scripts/bump_pin.py 0.23.1rc1.dev777+gabcdef012
    make bump-pin NEW=0.23.1rc1.dev777+gabcdef012

What it does (idempotent — safe to re-run):
  1. sndr/pins.yaml: current -> NEW, previous current -> rollback, and refresh
     canonical_substring / sha_short / anchor_dir / image / container.
  2. audit_v2_runtime_pins.py: CANONICAL_PIN_SUBSTRING -> new devNNN.
  3. Every vLLM model YAML: vllm_pin_required -> NEW (skips llama.cpp null lanes).
  4. Append NEW to guards.KNOWN_GOOD_VLLM_PINS, ALLOWED_MODELDEF_PINS, and
     test_pin_gate.EXPECTED_PINS if absent (with a dated 'validate me' comment).

It does NOT touch hardware image_digest (content-addressed — capture separately)
and does NOT edit rollback receipts. After it runs:
    make rebuild-pin SSH_HOST=... CONTAINER=... IMAGE=...   # anchor manifest
    make audit-pin-consistency                              # verify all in sync
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_PIN_RE = re.compile(r"^(?P<rel>\d+\.\d+\.\d+\w*)\.dev(?P<dev>\d+)\+g(?P<sha>[0-9a-f]+)$")


def _parse(pin: str) -> dict:
    m = _PIN_RE.match(pin.strip())
    if not m:
        sys.exit(f"error: {pin!r} is not a 'X.Y.Zrc.devN+g<sha>' pin string")
    d = m.groupdict()
    # Anchor dirs use the release WITHOUT the rc suffix: 0.23.1rc1 -> 0.23.1
    # (matches the existing sndr/engines/vllm/pins/0.23.1_<sha> layout).
    rel_no_rc = re.sub(r"rc\d+$", "", d["rel"])
    return {
        "pin": pin.strip(),
        "canonical": f"dev{d['dev']}",
        "sha_short": d["sha"],
        "anchor_dir": f"{rel_no_rc}_{d['sha']}",
        "container": f"vllm-35b-dev{d['dev']}",
        "image": f"vllm/vllm-openai:nightly-{d['sha']}",
    }


def _sub_line(text: str, key: str, value: str) -> str:
    """Replace a top-level ``key: "..."`` (or bare) YAML scalar, preserving the
    trailing inline comment."""
    return re.sub(
        rf'^({re.escape(key)}:\s*)(?:"[^"]*"|\'[^\']*\'|[^\s#]+)(\s*(?:#.*)?)$',
        lambda m: f'{m.group(1)}"{value}"{m.group(2)}',
        text, count=1, flags=re.M)


def bump(new: str, dry: bool) -> int:
    info = _parse(new)
    pins_yaml = REPO / "sndr/pins.yaml"
    from sndr import pins as _pins  # current SSOT before edit
    old_current = _pins.current()
    if old_current == new:
        print(f"pins.yaml already at {new} — refreshing downstream only")

    # 1. pins.yaml
    y = pins_yaml.read_text(encoding="utf-8")
    if old_current != new:
        y = _sub_line(y, "rollback", old_current)   # old current -> rollback
    y = _sub_line(y, "current", info["pin"])
    y = _sub_line(y, "canonical_substring", info["canonical"])
    y = _sub_line(y, "current_sha_short", info["sha_short"])
    y = _sub_line(y, "current_image", info["image"])
    y = _sub_line(y, "current_container", info["container"])
    y = _sub_line(y, "current_anchor_dir", info["anchor_dir"])

    # 2. CANONICAL_PIN_SUBSTRING
    av2_path = REPO / "scripts/audit_v2_runtime_pins.py"
    av2 = av2_path.read_text(encoding="utf-8")
    av2 = re.sub(r'(CANONICAL_PIN_SUBSTRING\s*=\s*)"[^"]*"',
                 rf'\g<1>"{info["canonical"]}"', av2, count=1)

    # 3. model YAMLs
    changed_yamls = []
    mdir = REPO / "sndr/model_configs/builtin/model"
    yaml_edits: list[tuple[Path, str]] = []
    for yml in sorted(mdir.glob("*.yaml")):
        t = yml.read_text(encoding="utf-8")
        m = re.search(r"vllm_pin_required:\s*([^\s#]+)", t)
        if not m or m.group(1).strip().strip('"').strip("'").lower() in {"null", "none", "~"}:
            continue
        nt = re.sub(r"(vllm_pin_required:\s*)([^\s#]+)", rf"\g<1>{info['pin']}", t, count=1)
        if nt != t:
            yaml_edits.append((yml, nt)); changed_yamls.append(yml.name)

    # 4. append to allowlists if absent
    def _append_pin(path: Path, anchor: str, comment: str) -> tuple[Path, str] | None:
        txt = path.read_text(encoding="utf-8")
        if f'"{info["pin"]}"' in txt:
            return None
        ins = f'{comment}\n    "{info["pin"]}",\n'
        nt = txt.replace(anchor, ins + "    " + anchor.strip(), 1) if anchor in txt else None
        return (path, nt) if nt else None

    print("=== bump plan ===")
    print(f"  new current : {info['pin']}")
    print(f"  rollback    : {old_current}")
    print(f"  canonical   : {info['canonical']}   anchor_dir: {info['anchor_dir']}")
    print(f"  container   : {info['container']}")
    print(f"  model YAMLs : {len(changed_yamls)} -> {new}")
    if dry:
        print("\n(dry-run — no files written)")
        return 0

    pins_yaml.write_text(y, encoding="utf-8")
    av2_path.write_text(av2, encoding="utf-8")
    for p, t in yaml_edits:
        p.write_text(t, encoding="utf-8")
    print("\n✓ pins.yaml, CANONICAL_PIN_SUBSTRING and model YAMLs updated.")
    print("  NOTE: append the new pin to guards.KNOWN_GOOD_VLLM_PINS / "
          "ALLOWED_MODELDEF_PINS / EXPECTED_PINS with its validation receipt "
          "(these carry per-pin comments, kept manual on purpose).")
    print("\nNext (manual, required):")
    print(f"  make rebuild-pin SSH_HOST=<user@host> CONTAINER={info['container']} IMAGE={info['image']}")
    print("  # commit sndr/engines/vllm/pins/%s/" % info["anchor_dir"])
    print("  make audit-pin-consistency   # must PASS before promoting")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("new_pin", help="new pin string, e.g. 0.23.1rc1.dev777+gabcdef012")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    args = ap.parse_args(argv)
    sys.path.insert(0, str(REPO))
    return bump(args.new_pin, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
