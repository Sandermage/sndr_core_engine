#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Pin-transition runtime-contract verifier.

Catches BEHAVIORAL drift that the anchor-drift preflight cannot see: a
config/launcher references an upstream component by NAME (e.g.
``--tool-call-parser qwen3_xml``), and that name silently resolves to a
DIFFERENT implementation class across a pin bump — so a feature that worked on
the validated pin stops working on the new one even though every Genesis patch
still applies cleanly.

The dev259 -> dev491 streaming-tool-call regression is the canonical case
(2026-06-14): upstream #45171 deleted ``qwen3xml_tool_parser.py`` and remapped
``qwen3_xml`` -> ``Qwen3CoderToolParser``. ``pin_preflight`` (which checks
whether each patch's text anchors still match) found nothing — no Genesis patch
anchors on the tool-parser registry. This verifier would have caught it: it
resolves each config-referenced parser name to its ``module.Class`` on the
candidate pin and diffs against a baseline manifest recorded on the validated
pin.

It also surfaces the launcher<->YAML config drift (Class-1): if the launcher
runs ``--tool-call-parser qwen3_xml`` while the model YAML declares
``qwen3_coder``, both names are checked and any divergence in what they resolve
to is reported.

Usage (resolution runs INSIDE the pin's container, where vLLM is importable):

  # On the VALIDATED pin — record the baseline contract:
  docker run --rm --entrypoint python3 \\
    -v $PWD:/work vllm/vllm-openai:<validated> \\
    /work/tools/pin_runtime_contract.py --emit > runtime_contract.<validated>.json

  # On the CANDIDATE pin — check for drift vs the baseline:
  docker run --rm --entrypoint python3 \\
    -v $PWD:/work vllm/vllm-openai:<candidate> \\
    /work/tools/pin_runtime_contract.py --check /work/runtime_contract.<validated>.json
  #   exit 0 = no identity drift; exit 3 = drift found (printed)

The pure diff logic (`diff_contracts`) is import-safe and unit-tested without a
GPU/vLLM — only `--emit`/`--check` need the in-pin environment.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

# Components our PROD stack references by NAME and that are resolved by an
# upstream registry (so they can silently remap across pins). Derived from the
# model YAMLs (capabilities.tool_call_parser / reasoning_parser) PLUS the names
# the live launchers actually pass (qwen3_xml is launcher-only — exactly the one
# that remapped). Extend this list as new config-referenced components appear.
DEFAULT_COMPONENTS: dict[str, list[str]] = {
    "tool_call_parser": ["qwen3_xml", "qwen3_coder", "gemma4", "hermes"],
    "reasoning_parser": ["qwen3"],
}

UNRESOLVED = "<unresolved>"


def _class_path(cls: object) -> str:
    """Stable ``module.QualName`` identity string for a resolved class."""
    mod = getattr(cls, "__module__", "?")
    qn = getattr(cls, "__qualname__", getattr(cls, "__name__", repr(cls)))
    return f"{mod}.{qn}"


def _resolve_tool_parser(name: str) -> str:
    """Resolve a ``--tool-call-parser`` NAME to its class identity on this pin.

    Tries the public manager APIs first, then the lazy/registry dict, across
    the several shapes these have had (pre/post #45171). Returns UNRESOLVED
    rather than raising so one missing name never masks the others.
    """
    try:
        from vllm.tool_parsers import ToolParserManager  # type: ignore
    except Exception:
        try:
            from vllm.entrypoints.openai.tool_parsers import (  # type: ignore
                ToolParserManager,
            )
        except Exception as e:  # pragma: no cover - env specific
            return f"{UNRESOLVED} (no ToolParserManager: {type(e).__name__})"

    # 1) public getter that returns the class (forces lazy import).
    for api in ("get_tool_parser", "get_parser"):
        fn = getattr(ToolParserManager, api, None)
        if callable(fn):
            try:
                cls = fn(name)
                if cls is not None:
                    return _class_path(cls)
            except Exception:
                pass

    # 2) registry dict ``name -> class`` or ``name -> (module, class_name)``.
    for attr in ("tool_parsers", "_tool_parsers", "tool_parsers_registry"):
        reg = getattr(ToolParserManager, attr, None)
        if isinstance(reg, dict) and name in reg:
            val = reg[name]
            if isinstance(val, tuple) and len(val) >= 2:
                # lazy spec (module_path, class_name) — report verbatim.
                return f"{val[-2]}.{val[-1]}"
            return _class_path(val)
    return f"{UNRESOLVED} ({name} not registered)"


def _resolve_reasoning_parser(name: str) -> str:
    """Resolve a ``--reasoning-parser`` NAME to its class identity on this pin."""
    mgr = None
    for path in (
        "vllm.reasoning",
        "vllm.reasoning_parsers",
        "vllm.entrypoints.openai.reasoning_parsers",
    ):
        try:
            mod = __import__(path, fromlist=["ReasoningParserManager"])
            mgr = getattr(mod, "ReasoningParserManager", None)
            if mgr is not None:
                break
        except Exception:
            continue
    if mgr is None:
        return f"{UNRESOLVED} (no ReasoningParserManager)"
    for api in ("get_reasoning_parser", "get_parser"):
        fn = getattr(mgr, api, None)
        if callable(fn):
            try:
                cls = fn(name)
                if cls is not None:
                    return _class_path(cls)
            except Exception:
                pass
    for attr in ("reasoning_parsers", "_reasoning_parsers"):
        reg = getattr(mgr, attr, None)
        if isinstance(reg, dict) and name in reg:
            val = reg[name]
            if isinstance(val, tuple) and len(val) >= 2:
                return f"{val[-2]}.{val[-1]}"
            return _class_path(val)
    return f"{UNRESOLVED} ({name} not registered)"


def _pin_version() -> str:
    try:
        import vllm  # type: ignore

        return getattr(vllm, "__version__", "unknown")
    except Exception:
        return "unknown"


def emit_contract(
    components: Optional[dict[str, list[str]]] = None,
) -> dict:
    """Resolve every config-referenced component NAME -> class identity on the
    current (in-pin) environment. The returned manifest is the runtime
    contract to record on a validated pin and diff against on a candidate.
    """
    components = components or DEFAULT_COMPONENTS
    resolvers = {
        "tool_call_parser": _resolve_tool_parser,
        "reasoning_parser": _resolve_reasoning_parser,
    }
    out: dict[str, dict[str, str]] = {}
    for category, names in components.items():
        resolve = resolvers.get(category)
        if resolve is None:
            continue
        out[category] = {name: resolve(name) for name in names}
    return {"pin": _pin_version(), "components": out}


def diff_contracts(baseline: dict, candidate: dict) -> list[dict]:
    """Pure diff: report every NAME whose resolved class identity CHANGED.

    A change means: the name resolved to one class on the validated pin and to a
    different class on the candidate pin — i.e. a config that relied on the old
    behavior now silently gets a different implementation. Names newly
    unresolved (deleted) are reported too. Names that stayed identical, and
    names only present on one side, are noted but not flagged as drift unless the
    identity changed.
    """
    drifts: list[dict] = []
    b_comp = baseline.get("components", {})
    c_comp = candidate.get("components", {})
    for category in sorted(set(b_comp) | set(c_comp)):
        b_names = b_comp.get(category, {})
        c_names = c_comp.get(category, {})
        for name in sorted(set(b_names) | set(c_names)):
            b_cls = b_names.get(name)
            c_cls = c_names.get(name)
            if b_cls is None or c_cls is None:
                # present only on one side — informational, not a drift.
                continue
            if b_cls != c_cls:
                drifts.append(
                    {
                        "category": category,
                        "name": name,
                        "baseline": b_cls,
                        "candidate": c_cls,
                        "kind": (
                            "deleted"
                            if c_cls.startswith(UNRESOLVED)
                            else "remapped"
                        ),
                    }
                )
    return drifts


def _format_drifts(drifts: list[dict], baseline_pin: str, candidate_pin: str) -> str:
    if not drifts:
        return (
            "  ✓ runtime contract CLEAN — every config-referenced component "
            f"resolves identically\n    baseline={baseline_pin} candidate="
            f"{candidate_pin}"
        )
    lines = [
        f"  ⚠ RUNTIME-CONTRACT DRIFT ({len(drifts)}) — config names resolve to "
        "DIFFERENT implementations across the pin bump:",
        f"    baseline={baseline_pin}  candidate={candidate_pin}",
    ]
    for d in drifts:
        lines.append(
            f"      - [{d['category']}] {d['name']} ({d['kind']}):\n"
            f"          was:  {d['baseline']}\n"
            f"          now:  {d['candidate']}"
        )
    lines.append(
        "    A config/launcher relying on the old behavior will silently mis-"
        "function. Adapt the affected patch/config before promoting this pin."
    )
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--emit", action="store_true", help="resolve + print manifest JSON")
    g.add_argument("--check", metavar="BASELINE.json", help="diff candidate vs baseline")
    args = p.parse_args(argv)

    if args.emit:
        print(json.dumps(emit_contract(), indent=2))
        return 0

    with open(args.check) as f:
        baseline = json.load(f)
    candidate = emit_contract()
    drifts = diff_contracts(baseline, candidate)
    print(_format_drifts(drifts, baseline.get("pin", "?"), candidate.get("pin", "?")))
    return 3 if drifts else 0


if __name__ == "__main__":
    sys.exit(main())
