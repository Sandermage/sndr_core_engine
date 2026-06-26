#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""CONFIG-UX.5.1 — generated catalog freshness + redaction audit.

Two orthogonal checks the audit enforces:

  (a) **Determinism / drift**: regeneration must produce byte-identical
      drift-stripped output across two consecutive runs. If timestamps
      or git-commit churn are stripped and the result still differs,
      the generator has a non-deterministic field somewhere — HALT.

  (b) **Redaction**: emitted catalog must NOT contain any of the
      banned path forms (`sndr_private/`, `/Users/`, `/home/`,
      `/tmp/`, `/var/`). This is the operator-locked public visibility
      rule. Any leak fails the audit unconditionally.

Severity model (operator-locked at .5.1 release-target tier):
  - default mode: informational. exit 0 always (warnings only).
  - --strict: exit 1 if any finding (drift or redaction leak).

This audit is registered in `make_evidence.py` as **informational**
(non-gating) at .5.1 ship. Promotion to gating after 1-2 successful
release cycles per operator §10.4.

Exit codes:
  0 — clean (default mode OR --strict with no findings)
  1 — findings present (--strict only)
  2 — usage / IO error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# Path patterns that MUST NOT appear in generated catalog output.
# Operator-locked rule: catalog is a public derived artifact.
_REDACTION_VIOLATIONS = (
    "sndr_private/",
    "/Users/",
    "/home/",
    "/tmp/",
    "/var/",
)


@dataclass
class Finding:
    severity: str                     # info | warning | error
    rule: str
    message: str

    def as_dict(self) -> dict:
        return {
            "severity": self.severity,
            "rule": self.rule,
            "message": self.message,
        }


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def add(self, severity: str, rule: str, message: str) -> None:
        self.findings.append(Finding(severity, rule, message))

    def has_errors(self) -> bool:
        return any(f.severity == "error" for f in self.findings)

    def has_warnings(self) -> bool:
        return any(f.severity == "warning" for f in self.findings)

    def count_by_severity(self) -> dict[str, int]:
        out = {"info": 0, "warning": 0, "error": 0}
        for f in self.findings:
            out[f.severity] = out.get(f.severity, 0) + 1
        return out


def _generate_and_serialise_for_drift() -> tuple[str, list[dict]]:
    """Invoke generator, return (drift-stripped JSON, full rows)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_gencatalog_audit",
        REPO_ROOT / "scripts" / "generate_config_catalog.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_gencatalog_audit"] = mod
    spec.loader.exec_module(mod)
    rows = mod.build_catalog()
    return mod.serialise_for_drift(rows), rows


def _audit_redaction(rows: list[dict], report: Report) -> None:
    """Walk the full catalog payload and flag any string containing
    a banned path prefix. Operator-locked invariant."""
    payload = json.dumps(rows, default=str)
    for pattern in _REDACTION_VIOLATIONS:
        if pattern in payload:
            # Find the actual string(s) that leaked for actionable error
            leaks = _find_leaked_strings(rows, pattern)
            report.add(
                "error", "redaction_leak",
                f"banned path prefix {pattern!r} appears in generated catalog "
                f"({len(leaks)} occurrence(s)); first 3: {leaks[:3]}",
            )


def _find_leaked_strings(obj: Any, pattern: str, _acc=None) -> list[str]:
    """Recursively gather all string leaves containing `pattern`."""
    if _acc is None:
        _acc = []
    if isinstance(obj, str):
        if pattern in obj:
            _acc.append(obj[:120])
    elif isinstance(obj, dict):
        for v in obj.values():
            _find_leaked_strings(v, pattern, _acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _find_leaked_strings(v, pattern, _acc)
    return _acc


def _audit_drift(report: Report) -> None:
    """Two-run determinism check."""
    s1, _ = _generate_and_serialise_for_drift()
    s2, _ = _generate_and_serialise_for_drift()
    if s1 != s2:
        # Compute minimal diff hint
        lines1 = s1.splitlines()
        lines2 = s2.splitlines()
        diff_lines = []
        for i, (a, b) in enumerate(zip(lines1, lines2)):
            if a != b:
                diff_lines.append(f"  L{i}: {a!r} vs {b!r}")
            if len(diff_lines) >= 3:
                break
        report.add(
            "error", "non_deterministic",
            "generator output drifted between two consecutive runs "
            "(timestamps + git-commit fields stripped); first diffs:\n"
            + "\n".join(diff_lines) if diff_lines else
            "generator output drifted; no line-level diff isolated",
        )


def run_audit() -> Report:
    """Full audit: drift + redaction."""
    report = Report()
    s1, rows = _generate_and_serialise_for_drift()
    # Determinism: do a second pass for comparison
    s2, _ = _generate_and_serialise_for_drift()
    if s1 != s2:
        report.add(
            "error", "non_deterministic",
            "generator output drifted between two consecutive runs",
        )
    # Redaction: scan the first-pass rows
    _audit_redaction(rows, report)
    return report


def _print_table(report: Report, row_count: int) -> None:
    counts = report.count_by_severity()
    print("audit-generated-config-catalog: catalog freshness + redaction")
    print("─" * 70)
    print(f"  scanned: {row_count} rows")
    print(
        f"  findings: {counts.get('error', 0)} error, "
        f"{counts.get('warning', 0)} warning, "
        f"{counts.get('info', 0)} info"
    )
    print()
    if not report.findings:
        print("  ✓ generated catalog clean: deterministic + redacted")
        return
    for f in report.findings:
        marker = {"error": "✗", "warning": "⚠", "info": "•"}[f.severity]
        print(f"  {marker} [{f.rule}] {f.message}")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0] if __doc__ else "",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--json", action="store_true",
        help="machine-readable JSON output",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="exit 1 on any finding (CI release gate). Default mode "
             "exits 0 (informational at CONFIG-UX.5.1 ship).",
    )
    args = parser.parse_args()

    try:
        report = run_audit()
    except Exception as e:
        print(f"audit-generated-config-catalog: internal error: {e}", file=sys.stderr)
        return 2

    # Quick row count for display
    try:
        _, rows = _generate_and_serialise_for_drift()
        row_count = len(rows)
    except Exception:
        row_count = 0

    if args.json:
        payload = {
            "row_count": row_count,
            "counts": report.count_by_severity(),
            "findings": [f.as_dict() for f in report.findings],
            "has_errors": report.has_errors(),
            "has_warnings": report.has_warnings(),
            "strict": args.strict,
        }
        print(json.dumps(payload, indent=2))
    else:
        _print_table(report, row_count)

    # Severity-aware exit:
    #   - errors (drift / redaction leak) ALWAYS fail (any mode)
    #   - warnings fail only under --strict
    # CONFIG-UX.5.1 release-target is informational, but the operator
    # rule "redaction leak HALT" requires errors to fire unconditionally.
    if report.has_errors():
        return 1
    if args.strict and report.has_warnings():
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
