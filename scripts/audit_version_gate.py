#!/usr/bin/env python3
"""Advisory audit: version-ranged patches whose apply_module lacks a version pre-check.

The "version-gate-bypass" class (canonical example PN347): a patch with a
``vllm_version_range`` whose wiring ``apply()`` runs its anchor search and logs a
``required_anchor_missing`` warning even when the running pin is OUT of range —
instead of pre-checking the range and skipping silently. The dispatcher does apply
the gate centrally, so this is BENIGN (the patch still SKIPs, never corrupts), but it
produces misleading per-boot warnings that read like errors.

This lint flags candidates for adding an early version-range guard to the wiring.
It is ADVISORY (exit 0) — not every flagged patch needs the guard, and for some
(e.g. default-on patches) a naive ``should_apply`` guard is unsafe because it also
enforces opt-in (see the PN347 dispatch-gate rejection, journal 2026-06-16).

Usage: python3 scripts/audit_version_gate.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from sndr.dispatcher.registry import PATCH_REGISTRY

REPO = Path(__file__).resolve().parent.parent

# Markers that indicate the wiring is version/pin aware (any one is enough).
VERSION_MARKERS = (
    "vllm_version_range",
    "version_in_range",
    "_pin_in_range",
    "ENFORCE_VERSION",
    "GENESIS_ENFORCE_VERSION",
    "get_current_vllm_config",
    "__version__",
    "vllm.version",
    "pin_gate",
    "version_check",
)


def _has_version_range(entry: dict) -> bool:
    if entry.get("vllm_version_range"):
        return True
    applies = entry.get("applies_to")
    return isinstance(applies, dict) and bool(applies.get("vllm_version_range"))


def main() -> int:
    flagged: list[tuple[str, str]] = []
    checked = 0
    for pid, entry in PATCH_REGISTRY.items():
        if not _has_version_range(entry):
            continue
        module = entry.get("apply_module")
        if not module:
            continue
        path = REPO / (module.replace(".", "/") + ".py")
        if not path.exists():
            continue
        src = path.read_text(errors="ignore")
        # Only the anchor-searching wirings can emit the misleading
        # 'required_anchor_missing' / drift warning at boot when out of range.
        does_anchor_search = any(
            a in src for a in ("required_anchor_missing", "TextPatch", "anchor=", "_anchor", "drift")
        )
        if not does_anchor_search:
            continue
        checked += 1
        if not any(m in src for m in VERSION_MARKERS):
            flagged.append((pid, module.split(".")[-1]))

    print(
        f"version-gate audit: {checked} version-ranged + anchor-searching patch(es); "
        f"{len(flagged)} rely on the CENTRAL dispatcher gate (no per-wiring version pre-check)."
    )
    print(
        "FINDING (advisory, non-blocking): version-gating is CENTRALIZED in the dispatcher "
        "(_check_version_gate, GENESIS_ENFORCE_VERSION_RANGE). By design almost every "
        "anchor-searching patch relies on it rather than self-checking — so a high count "
        "here is EXPECTED, not a defect. The 'required_anchor_missing' boot lines for a "
        "version-gated-out patch (e.g. PN347 on dev491) are BENIGN: the dispatcher SKIPs the "
        "patch (never corrupts); the wiring just logs the missing anchor before the skip. The "
        "naive 'add should_apply to the wiring' fix is UNSAFE for default-on patches (flips "
        "them to opt-in — see journal 2026-06-16 PN347). Use --list to see the patch ids."
    )
    if "--list" in sys.argv:
        for pid, mod in sorted(flagged):
            print(f"  - {pid:<10} {mod}")
    return 0  # advisory: never fail CI


if __name__ == "__main__":
    sys.exit(main())
