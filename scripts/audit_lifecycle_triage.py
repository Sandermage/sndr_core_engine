#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Lifecycle-triage visibility report for PATCH_REGISTRY.

The registry carries a large `experimental` cohort, and the metadata layer
(`dispatcher.registry_metadata.derive_metadata`) computes a `production_default`
for every patch from `(implementation_status, test_status)`. Patches whose impl
is usable but that have NO discoverable test (and no audited override) land at
`review_required` — held back from production-eligibility by design until they
earn a test or an evidence-backed override.

That governance is sound but INVISIBLE: nothing surfaces the review_required
backlog, so "graduate experimental -> stable" has no actionable worklist. This
script prints one. It is READ-ONLY and never fails the build (visibility, not a
gate) — graduation is a per-patch evidence decision, not something to automate.

Usage:
    python3 scripts/audit_lifecycle_triage.py            # full report
    python3 scripts/audit_lifecycle_triage.py --list     # + full review_required list
    make audit-lifecycle-triage

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter


def _load():
    from sndr.dispatcher import PATCH_REGISTRY
    from sndr.dispatcher.registry_metadata import derive_metadata
    return PATCH_REGISTRY, derive_metadata


def build_report() -> dict:
    registry, derive_metadata = _load()
    lifecycle = Counter()
    test_status = Counter()
    production_default = Counter()
    review_required: list[tuple[str, str]] = []  # (patch_id, lifecycle)
    for pid, meta in registry.items():
        lc = meta.get("lifecycle") or "unset"
        lifecycle[lc] += 1
        try:
            derived = derive_metadata(pid, meta)
        except Exception:  # noqa: S112 — a metadata-derivation failure for one
            # patch must not blank the whole report; count it and continue.
            test_status["derive_error"] += 1
            continue
        test_status[derived.get("test_status")] += 1
        pd = derived.get("production_default")
        production_default[pd] += 1
        if pd == "review_required":
            review_required.append((pid, lc))
    return {
        "total": len(registry),
        "lifecycle": dict(lifecycle),
        "test_status": dict(test_status),
        "production_default": dict(production_default),
        "review_required": review_required,
    }


def _fmt_counter(title: str, counts: dict) -> list[str]:
    lines = [f"  {title}:"]
    for key, n in sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        lines.append(f"      {str(key):<16} {n:>4d}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lifecycle-triage visibility report")
    parser.add_argument(
        "--list", action="store_true",
        help="print the full review_required patch list (not just the count)",
    )
    args = parser.parse_args(argv)

    r = build_report()
    out = ["=== lifecycle-triage (read-only visibility) ===",
           f"  total registry patches: {r['total']}", ""]
    out += _fmt_counter("lifecycle", r["lifecycle"])
    out.append("")
    out += _fmt_counter("derived test_status", r["test_status"])
    out.append("")
    out += _fmt_counter("derived production_default", r["production_default"])
    out.append("")

    rr = r["review_required"]
    out.append(
        f"  review_required backlog: {len(rr)} patch(es) — usable impl but no "
        "discoverable test / audited override."
    )
    out.append(
        "  To graduate one: add a per-patch test (drives test_status off 'none') "
        "or an EXPLICIT_OVERRIDES entry pointing at a real evidence artefact."
    )
    if args.list:
        out.append("  review_required patches:")
        for pid, lc in sorted(rr):
            out.append(f"      {pid:<22} (lifecycle={lc})")
    else:
        out.append("  (run with --list to see the full worklist)")

    out.append("")
    out.append("  This report never fails — graduation is an evidence decision.")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
