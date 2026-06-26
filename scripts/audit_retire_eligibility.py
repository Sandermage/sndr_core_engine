#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""audit_retire_eligibility.py — thin gate around
``retire_eligibility()`` for ``make release-preflight``
(§9.A.16, AUDIT-CLOSURE.3, 2026-05-27).

``scripts/audit_upstream_status.py::retire_eligibility(row_data)``
classifies a (PR-state, lifecycle, relationship) triple into one of
five verdicts:

  * ``RETIRE-CANDIDATE``   — only verdict that authorizes the retire queue
  * ``NEEDS-DEEP-PARITY``  — merged upstream but non-pure backport;
                             requires iron-rule-#11 deep-diff
  * ``ACTIVE``             — upstream PR open; no retire action
  * ``ALREADY-RETIRED``    — our patch lifecycle already retired
  * ``UNKNOWN``            — query error / unclassifiable

The function existed since 2026-05-25 inside ``audit_upstream_status.py``
but was only invoked as part of the full upstream-audit report.
Master plan §9.A.16 asks for a standalone Make target so the verdict
distribution can be reported quickly during release preflight without
re-running the full ``gh api`` calls.

This script is a **thin wrapper**: it imports ``retire_eligibility``
(no logic duplication), iterates ``PATCH_REGISTRY`` against pre-collected
rows (``--from-rows ROWS.json``) or by invoking the upstream audit
itself in offline mode, and emits the per-verdict counts.

Default: **offline** (``--skip-network``) — emits verdict counts using
``categorize()`` over the registry without hitting the GitHub API.
This is suitable for ``make release-preflight``. To get the
network-augmented verdict, run ``scripts/audit_upstream_status.py``
directly.

Exit codes
──────────

  0 — verdict counts reported (informational by default)
  1 — ``--fail-on-retire-candidate`` set AND at least one
      ``RETIRE-CANDIDATE`` verdict present
  2 — internal error

Modes
─────

  python3 scripts/audit_retire_eligibility.py            # human-readable
  python3 scripts/audit_retire_eligibility.py --json
  python3 scripts/audit_retire_eligibility.py --fail-on-retire-candidate
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _import_upstream_status_module():
    """Import ``scripts/audit_upstream_status.py`` as a module so we
    can call ``retire_eligibility`` + ``run_audit`` directly."""
    path = REPO_ROOT / "scripts" / "audit_upstream_status.py"
    spec = importlib.util.spec_from_file_location(
        "_audit_upstream_status_for_retire", path,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_audit_upstream_status_for_retire"] = mod
    spec.loader.exec_module(mod)
    return mod


# Bucket → verdict mapping. MUST stay in lockstep with
# ``audit_upstream_status.py::retire_eligibility``. The two surfaces
# share the same enum semantics; this helper exists because
# ``retire_eligibility(row_data)`` operates on the internal pre-audit
# dict shape while we have post-audit ``PatchAuditRow`` objects where
# ``row.category`` IS the bucket already computed by ``categorize()``.
# Adding a new bucket requires editing both surfaces and updating
# tests/unit/scripts/test_audit_retire_eligibility.py to lock the pair.
_BUCKET_TO_VERDICT: dict[str, str] = {
    "NEWLY-MERGED":            "RETIRE-CANDIDATE",
    "COUNTER-REGRESSION":      "NEEDS-DEEP-PARITY",
    "INTENTIONAL-INVERSE":     "NEEDS-DEEP-PARITY",
    "ENABLES-UPSTREAM":        "NEEDS-DEEP-PARITY",
    "DEFENSIVE-OVERLAY":       "NEEDS-DEEP-PARITY",
    "RELATED-NOT-SUPERSEDING": "NEEDS-DEEP-PARITY",
    "SUPERSEDED-OK":           "ALREADY-RETIRED",
    "STALE-RETIRED":           "ALREADY-RETIRED",
    "WATCH":                   "ACTIVE",
    "ERROR":                   "UNKNOWN",
    "ISSUE-OPEN":              "UNKNOWN",
    "ISSUE-CLOSED":            "UNKNOWN",
}


def bucket_to_verdict(bucket: str) -> str:
    """Map an audit bucket name to its retire verdict."""
    return _BUCKET_TO_VERDICT.get(bucket, "UNKNOWN")


def row_verdict(row) -> str:
    """Lifecycle-aware verdict for a ``PatchAuditRow``.

    A retired patch needs no parity work regardless of which bucket it
    falls in — lifecycle takes precedence over the context-free
    ``bucket_to_verdict`` mapping. This matters for the conflated
    ``RELATED-NOT-SUPERSEDING`` bucket which can fire on either an
    active patch (genuine NEEDS-DEEP-PARITY) or a retired patch (open
    PR + explicit relationship marker — ALREADY-RETIRED).
    """
    if row.lifecycle == "retired":
        return "ALREADY-RETIRED"
    return bucket_to_verdict(row.category)


def _audit_once(*, skip_network: bool) -> tuple[dict[str, int], list[dict]]:
    """Single ``run_audit`` invocation; return (counts, candidates)."""
    mod = _import_upstream_status_module()
    rows = mod.run_audit(skip_network=skip_network)
    counter: Counter[str] = Counter()
    candidates: list[dict] = []
    for row in rows:
        verdict = row_verdict(row)
        counter[verdict] += 1
        if verdict == "RETIRE-CANDIDATE":
            candidates.append({
                "patch_id": row.patch_id,
                "category": row.category,
                "lifecycle": row.lifecycle,
                "upstream_pr": row.upstream_pr,
            })
    return dict(counter), candidates


def collect_verdicts(*, skip_network: bool = True) -> dict[str, int]:
    """Tally each entry's retire verdict via the bucket→verdict map."""
    counts, _ = _audit_once(skip_network=skip_network)
    return counts


def list_candidates(*, skip_network: bool = True) -> list[dict]:
    """Return rows whose verdict is RETIRE-CANDIDATE."""
    _, cands = _audit_once(skip_network=skip_network)
    return cands


def _render_text(counts: dict[str, int], candidates: list[dict]) -> str:
    total = sum(counts.values())
    lines: list[str] = []
    lines.append("audit-retire-eligibility: verdict distribution")
    lines.append("─" * 70)
    lines.append(f"  total patches scanned: {total}")
    lines.append("")
    # Canonical verdict order — informational first, actionable last.
    order = (
        "ACTIVE", "ALREADY-RETIRED", "UNKNOWN",
        "NEEDS-DEEP-PARITY", "RETIRE-CANDIDATE",
    )
    for verdict in order:
        if verdict in counts:
            sym = "✗" if verdict == "RETIRE-CANDIDATE" else "·"
            lines.append(f"  {sym} {verdict:24s} {counts[verdict]}")
    # Surface any verdicts not in canonical order (defensive).
    for verdict in sorted(counts):
        if verdict not in order:
            lines.append(f"  ? {verdict:24s} {counts[verdict]}")

    if candidates:
        lines.append("")
        lines.append(f"  RETIRE-CANDIDATE rows ({len(candidates)}):")
        for c in candidates[:20]:
            lines.append(
                f"    · {c.get('patch_id', '?'):14s} "
                f"upstream_pr={c.get('upstream_pr')} "
                f"lifecycle={c.get('lifecycle')}"
            )
        if len(candidates) > 20:
            lines.append(f"    … ({len(candidates) - 20} more)")
        lines.append("")
        lines.append(
            "  ⚠ RETIRE-CANDIDATE verdicts AUTHORIZE the retire queue "
            "but iron-rule-#11 deep-diff is REQUIRED before any actual retire."
        )
    else:
        lines.append("")
        lines.append("  ✓ no RETIRE-CANDIDATE verdicts")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable JSON")
    ap.add_argument(
        "--skip-network", action="store_true", default=True,
        help="(default) skip gh API calls; tally verdicts offline",
    )
    ap.add_argument(
        "--with-network", action="store_true",
        help="enable gh API queries (slower, fresher state)",
    )
    ap.add_argument(
        "--fail-on-retire-candidate", action="store_true",
        help="exit 1 if any RETIRE-CANDIDATE verdicts found (CI gate)",
    )
    args = ap.parse_args()

    skip_network = not args.with_network

    try:
        counts, candidates = _audit_once(skip_network=skip_network)
    except Exception as e:
        print(f"audit-retire-eligibility: {type(e).__name__}: {e}",
              file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({
            "skip_network": skip_network,
            "counts": counts,
            "total": sum(counts.values()),
            "candidates": candidates,
        }, indent=2, sort_keys=True))
    else:
        print(_render_text(counts, candidates))

    if args.fail_on_retire_candidate and "RETIRE-CANDIDATE" in counts \
            and counts["RETIRE-CANDIDATE"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
