#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Audit gate — PN59 streaming-GDN driver carries the v7.72.5 Level 2
markers that close Cliff 2b on chunked-prefill paths (club-3090 #22).

Why this exists
---------------
External users (noonghunna/club-3090 issue #182) reported that pinning
Genesis at v7.72.2 (commit `7b9fd319`) **silently reverts** the Cliff 2b
fix: PN59's eligibility check rejects chunked-prefill in v7.72.2, so it
no-ops onto the vanilla `(B, NT, H, V, K)` materialization, which OOMs
the single-card 24 GB path at >50K single-prompt context.

The fix landed at v7.72.5 (`fbecee3`) as four "Level 2" components:
  Level 2A: `_slice_chunk_metadata_for_window` — per-window slicing
  Level 2A: GENESIS_PN59_STRICT_NO_METADATA env (default flipped 1→0)
  Level 2C: `GdnScratchPool.is_production_eligible` gate
  Level 2C+D: `GdnScratchPool.acquire_o_output` scratch reuse

A future regression (someone rebases off v7.72.2, accidentally drops
the Level 2 work, etc.) would silently re-open Cliff 2b. This gate
fails loud at CI time instead of waiting for a 24 GB rig to OOM in
production.

Invariant
---------
File `vllm/sndr_core/kernels/streaming_gdn_driver.py` must contain ALL
four sentinel strings. Any missing marker → exit 1 (strict) with the
list of which Level 2 component went missing.

Usage
-----
  python3 scripts/audit_pn59_cliff2b_markers.py           # human report
  python3 scripts/audit_pn59_cliff2b_markers.py --strict  # CI gate (exit 1)
  python3 scripts/audit_pn59_cliff2b_markers.py --json    # machine-readable

No torch / pyyaml imports — runs in CI on bare Python.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

# Each marker = (label, sentinel-string, level). The sentinel must appear
# verbatim in streaming_gdn_driver.py. Strings deliberately chosen as
# stable identifiers (function names + qualified calls) rather than
# comment text, so refactors of the surrounding prose don't break the gate.
_LEVEL_2_MARKERS: tuple[tuple[str, str, str], ...] = (
    ("Level 2A — chunk-metadata window slicer",
     "def _slice_chunk_metadata_for_window(", "2A"),
    ("Level 2A — STRICT_NO_METADATA env (default flipped 1→0)",
     "GENESIS_PN59_STRICT_NO_METADATA", "2A"),
    ("Level 2C — scratch-pool production-eligibility gate",
     "GdnScratchPool.is_production_eligible(", "2C"),
    ("Level 2C+D — scratch-pool acquire_o_output reuse",
     "GdnScratchPool.acquire_o_output(", "2C+D"),
)

_TARGET_REL = Path("vllm/sndr_core/kernels/streaming_gdn_driver.py")


@dataclass(slots=True)
class MarkerStatus:
    label: str
    level: str
    sentinel: str
    present: bool


def _audit(text: str) -> list[MarkerStatus]:
    return [
        MarkerStatus(label, level, sentinel, sentinel in text)
        for (label, sentinel, level) in _LEVEL_2_MARKERS
    ]


def _format_report(status: list[MarkerStatus], target: Path) -> str:
    lines = [
        f"audit_pn59_cliff2b_markers: {target}",
        "",
    ]
    missing = [s for s in status if not s.present]
    for s in status:
        mark = "✓" if s.present else "✗"
        lines.append(f"  {mark}  Level {s.level:5}  {s.label}")
    lines.append("")
    if missing:
        lines.append(
            f"  ✗ {len(missing)}/{len(status)} Level 2 marker(s) missing — "
            f"PN59 may have been rolled back below v7.72.5. Cliff 2b is "
            f"open. (club-3090 #182 root class)"
        )
    else:
        lines.append(
            f"  ✓ All {len(status)} Level 2 markers present — "
            f"Genesis ≥ v7.72.5 equivalent (club-3090 #22 fix engaged)."
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on any missing marker (CI gate mode)")
    ap.add_argument("--json", action="store_true",
                    help="emit JSON instead of human-readable")
    ap.add_argument("--root", type=Path,
                    default=Path(__file__).resolve().parents[1],
                    help="repo root (auto-detected)")
    args = ap.parse_args(argv)

    target = args.root / _TARGET_REL
    if not target.is_file():
        sys.stderr.write(
            f"ERROR: target {target} does not exist. PN59 driver missing "
            f"entirely — far worse than markers missing.\n"
        )
        return 2

    text = target.read_text(encoding="utf-8")
    status = _audit(text)
    missing_count = sum(1 for s in status if not s.present)

    if args.json:
        print(json.dumps({
            "target": str(target.relative_to(args.root)),
            "total": len(status),
            "missing": missing_count,
            "markers": [
                {"level": s.level, "label": s.label,
                 "sentinel": s.sentinel, "present": s.present}
                for s in status
            ],
            "pass": missing_count == 0,
        }, indent=2))
    else:
        print(_format_report(status, target.relative_to(args.root)))

    if args.strict and missing_count > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
