#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""propose_reanchors — deterministic re-anchor proposer for pin bumps.

The recurring pain: every vLLM pin bump breaks a handful of Genesis text-patches
because `TextPatch.anchor` is an EXACT substring — upstream renames a line,
inserts a method, or reflows a call and the anchor no longer matches (drift).
Re-deriving each anchor by hand is slow archaeology.

This tool turns that into review-and-apply. For a drifted anchor and the NEW
pristine source, `propose_anchor` locates the anchor's *surviving landmark* lines
(the ones still present in the new source) and proposes the corrected anchor —
the exact pristine region that spans them, carrying whatever upstream changed in
between — with a uniqueness guarantee and a confidence.

It is ANALYSIS ONLY. It never touches the apply engine, so it cannot mis-apply a
patch; a human reviews each proposal before writing it. That is the safety
property: safer + simpler pin bumps without adding risk to the runtime apply
path.

    python3 tools/propose_reanchors.py <pristine-vllm-tree> [--patch PN367 ...] [--json]

Without --patch it proposes for every drifted text-patch the drift checker
(tools/check_upstream_drift.py) reports against <pristine-vllm-tree>.
"""
from __future__ import annotations

import argparse
import json
import sys


def propose_anchor(old_anchor: str, pristine: str) -> dict:
    """Propose a corrected anchor for ``old_anchor`` against ``pristine``.

    Returns a dict with ``status`` in {unchanged, reanchor, manual}:
      * unchanged — the anchor still matches; nothing to do.
      * reanchor  — a unique corrected anchor was derived (``new_anchor``).
      * manual    — the anchored code is gone / too ambiguous to re-derive safely.
    plus ``confidence`` (high|medium|low) and, for reanchor, the surviving
    landmark lines used.
    """
    if old_anchor and old_anchor in pristine:
        return {"status": "unchanged", "confidence": "high", "new_anchor": old_anchor}

    anchor_lines = [ln for ln in old_anchor.splitlines() if ln.strip()]
    if not anchor_lines:
        return {"status": "manual", "confidence": "low", "reason": "empty anchor"}

    pristine_lines = pristine.splitlines(keepends=True)
    pristine_cmp = [pl.rstrip() for pl in pristine_lines]

    def positions(line: str) -> list[int]:
        target = line.rstrip()
        return [i for i, pl in enumerate(pristine_cmp) if pl == target]

    surviving = [(ln, positions(ln)) for ln in anchor_lines]
    surviving = [(ln, pos) for ln, pos in surviving if pos]
    if not surviving:
        return {
            "status": "manual", "confidence": "low",
            "reason": "no anchor line survives in the new source — code was removed/rewritten",
        }

    first_line, first_pos = surviving[0]
    last_line, last_pos = surviving[-1]
    start = first_pos[0]
    end_candidates = [p for p in last_pos if p >= start]
    if not end_candidates:
        return {"status": "manual", "confidence": "low", "reason": "landmarks out of order"}
    end = end_candidates[0]

    new_anchor = "".join(pristine_lines[start:end + 1])
    unique = pristine.count(new_anchor) == 1
    ambiguous_first = len(first_pos) > 1
    ambiguous_last = len(last_pos) > 1

    if not unique or (ambiguous_first and ambiguous_last):
        return {
            "status": "manual", "confidence": "low", "new_anchor": new_anchor,
            "reason": "proposed region is not unique / landmarks are ambiguous — verify by hand",
        }

    return {
        "status": "reanchor",
        "confidence": "high" if not (ambiguous_first or ambiguous_last) else "medium",
        "new_anchor": new_anchor,
        "surviving_landmarks": [first_line.strip(), last_line.strip()],
        "drifted_lines": [
            ln.strip() for ln in anchor_lines if not positions(ln)
        ],
    }


# ── CLI: propose against a single pristine FILE ──────────────────────────────
# Uniqueness is only meaningful within the file the anchor lives in, so the CLI
# is file-scoped: give it the drifted target file (from the drift checker's
# report) and the anchor text (a file, or stdin), and it proposes the fix.

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pristine_file", help="the drifted target file in the NEW pristine tree")
    ap.add_argument(
        "--anchor-file",
        help="file holding the current anchor text (default: read from stdin)",
    )
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    import pathlib

    anchor = (
        pathlib.Path(args.anchor_file).read_text(encoding="utf-8")
        if args.anchor_file
        else sys.stdin.read()
    )
    pristine = pathlib.Path(args.pristine_file).read_text(encoding="utf-8")
    p = propose_anchor(anchor, pristine)

    if args.json:
        print(json.dumps(p, indent=2))
    else:
        print(f"status: {p['status']}  confidence: {p['confidence']}")
        if p.get("reason"):
            print(f"reason: {p['reason']}")
        if p.get("drifted_lines"):
            print("drifted lines:")
            for ln in p["drifted_lines"]:
                print(f"  - {ln}")
        if p.get("new_anchor"):
            print("proposed anchor:\n" + p["new_anchor"])
    # exit 0 for reanchor/unchanged, 2 for manual (needs a human)
    return 2 if p["status"] == "manual" else 0


if __name__ == "__main__":
    sys.exit(main())
