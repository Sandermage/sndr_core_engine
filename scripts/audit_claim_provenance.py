#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Truth-claim provenance gate.

Closes the deterministic parts of audit-2026-07-04's root-cause cluster #2
("no gate ties a release tag to a CHANGELOG heading; no gate ties bench rows to
their JSON fingerprints; the release proof base sits in volatile /tmp"):

  A (GATING)        release tag <-> CHANGELOG heading (finding #3)
  B (INFORMATIONAL) bench-number rows carry a (pin, date) label (#2/#9/#23/#45)
  C (GATING)        evidence cited from a durable path, not /tmp (#11)

Design: scripts/audit_claim_provenance.py (see the truth-gate spec). Each check
is a PURE function so it is unit-testable without mutating the repo. --strict's
exit code reflects ONLY the gating checks (A + C); Check B prints WARN but never
moves the exit code — mirroring audit_stale_vllm_version_ranges (0 on WARN, 1
only on CRITICAL).

Exit codes: 0 ok · 1 a gating check failed (with --strict) · 2 usage.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
Status: v12.1.0+ gate (audit-2026-07-04 cluster #2 closure).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


# ─────────────────────────── Check A pure fns ──────────────────────────────

# PEP440 pre-release / dev markers: a release-shaped version carries none.
# Anchored to a following digit so a hex git-hash never false-matches.
_PRERELEASE = re.compile(r"(\.dev|\.post|\.pre|a|b|rc|alpha|beta)\d", re.IGNORECASE)


def is_release_shaped(version: str) -> bool:
    """True iff ``version`` is a cut release tag (no .dev/rc/a/b/post suffix).

    Mirrors test_version_consistency's no-dev-suffix logic: a pre-release/dev
    build legitimately has no CHANGELOG heading yet, so Check A only gates on
    release-shaped versions.
    """
    v = str(version).strip()
    if not re.match(r"^\d+\.\d+", v):
        return False
    return _PRERELEASE.search(v) is None


def changelog_has_heading(version: str, changelog_text: str) -> bool:
    """True iff CHANGELOG has an H2 heading whose bracket token is the version.

    Accepts both ``## [v12.1.0]`` and ``## [12.1.0]`` (the two forms the tree
    uses). Pure string match -> fully deterministic.
    """
    pat = re.compile(r"(?m)^##\s+\[v?" + re.escape(str(version).strip()) + r"\]")
    return pat.search(changelog_text) is not None


def check_a(version: str, changelog_text: str) -> dict:
    """Check A: a release-shaped version MUST have a CHANGELOG heading.

    Pre-release/dev versions are informational (no heading expected yet).
    Returns a dict with the decision + a human reason.
    """
    release_shaped = is_release_shaped(version)
    heading = changelog_has_heading(version, changelog_text)
    if not release_shaped:
        return {
            "is_release_shaped": False,
            "changelog_heading_found": heading,
            "gating_failure": False,
            "reason": f"version {version!r} is pre-release/dev — Check A "
                      f"informational (no cut heading expected)",
        }
    if not heading:
        return {
            "is_release_shaped": True,
            "changelog_heading_found": False,
            "gating_failure": True,
            "reason": f"release version {version!r} has NO CHANGELOG heading "
                      f"(expected `## [v{version}]` or `## [{version}]`)",
        }
    return {
        "is_release_shaped": True,
        "changelog_heading_found": True,
        "gating_failure": False,
        "reason": f"release version {version!r} has a CHANGELOG heading",
    }


# ─────────────────────────── Check B pure fns ──────────────────────────────

# A bench DATA row quotes an actual numeric MEASUREMENT next to a throughput /
# latency / acceptance unit — not merely the metric token (which also appears in
# table HEADERS as a column name, in flag descriptions, and in prose). Requiring
# the number+unit is what separates a bench claim ("242.5 t/s") from a column
# label ("| wall_TPS |") or a config-doc line ("... accept-rate falls below").
_BENCH_MEASUREMENT = re.compile(
    r"\d[\d.,]*\s*(?:t/s|tok/s|TPS)\b"          # throughput
    r"|\d[\d.,]*\s*ms\b"                         # latency
    r"|accept[-\s]?rate\D{0,3}(?:0?\.\d+|\d+/\d+)",  # acceptance rate value
    re.IGNORECASE,
)
# pin tokens: dev\d+ (dev748, and legacy dev9/dev93), v0.<minor>[.<patch>], a
# Wave/vX.Y tag, or a full rc/dev pin string. Kept permissive because Check B is
# informational — the goal is to recognise a genuine (pin) label, not to be a
# strict pin validator (that is audit_pin_consistency's job).
_PIN_TOKEN = re.compile(r"dev\d+|v0\.\d+(?:\.\d+)?|v\d+\.\d+|0\.\d+\.\d+rc\d")
_DATE_TOKEN = re.compile(r"20\d\d-\d\d-\d\d")


def is_bench_row(line: str) -> bool:
    """True iff ``line`` is a Markdown table row quoting a bench MEASUREMENT
    (a number next to a throughput/latency/acceptance unit)."""
    stripped = line.lstrip()
    if not stripped.startswith("|"):
        return False
    return _BENCH_MEASUREMENT.search(line) is not None


def row_is_labeled(row: str, context: str = "") -> bool:
    """True iff a bench row supplies BOTH a pin token AND a date — inline OR via
    table-caption inheritance (the section heading / paragraph above the table,
    or the header row, carries the (pin, date))."""
    hay = row + "\n" + (context or "")
    return bool(_PIN_TOKEN.search(hay) and _DATE_TOKEN.search(hay))


def _row_signature(doc_name: str, row: str) -> str:
    """Stable identity for a bench row (line-number-independent): the doc name +
    a hash of the row's collapsed whitespace. Used to baseline the current
    unlabeled set so the class cannot silently grow."""
    norm = re.sub(r"\s+", " ", row.strip())
    h = hashlib.md5(norm.encode("utf-8")).hexdigest()[:12]
    return f"{doc_name}:{h}"


def find_unlabeled_bench_rows(doc_name: str, text: str) -> list[dict]:
    """Enumerate unlabeled bench rows in one doc.

    Context for label inheritance is a rolling buffer of the last few non-table
    lines (headings + caption paragraphs). Table rows do NOT enter the buffer,
    so a long data table never evicts the caption that carries its (pin, date)
    — the fix for a labeled table whose caption sits many rows above the flagged
    line (e.g. the README dev714 reference table).
    """
    from collections import deque

    lines = text.splitlines()
    recent_nontable: deque[str] = deque(maxlen=6)
    last_heading = ""
    out: list[dict] = []
    for i, line in enumerate(lines):
        is_table = line.lstrip().startswith("|")
        if not is_table:
            if line.lstrip().startswith("#"):
                # The section heading is kept separately (never evicted): it
                # commonly carries the (pin, date) label the whole section's
                # tables inherit, even when a long intro paragraph precedes the
                # table and pushes it out of the rolling caption buffer.
                last_heading = line
            if line.strip():
                recent_nontable.append(line)
            continue
        # separator rows (| --- | :-: |) are not data
        if re.fullmatch(r"\s*\|[\s:\-|]+\|\s*", line):
            continue
        if not is_bench_row(line):
            continue
        context = last_heading + "\n" + "\n".join(recent_nontable)
        if row_is_labeled(line, context):
            continue
        out.append({
            "doc": doc_name,
            "line": i + 1,
            "signature": _row_signature(doc_name, line),
            "row": line.strip()[:120],
        })
    return out


# ─────────────────────────── Check C pure fns ──────────────────────────────

# Structured evidence-field keys whose VALUE is a machine-readable proof handle.
# A committed number whose source resolves under /tmp is the finding-#11 class
# (one reboot erases the proof).
_EVIDENCE_FIELDS = frozenset({
    "reference_metrics_ref", "reference_metrics", "metrics_ref",
    "evidence_ref", "bench_ref", "proof_ref", "receipt_ref",
    "proof", "receipt",
})


def _is_evidence_field(field: str) -> bool:
    f = field.strip().lower()
    if f in _EVIDENCE_FIELDS:
        return True
    if f.endswith(("_metrics_ref", "_evidence", "evidence_ref")):
        return True
    return f.endswith("_ref") and any(
        k in f for k in ("metric", "bench", "proof", "evidence", "receipt")
    )


def is_tmp_evidence_ref(field: str, value: str) -> bool:
    """True iff a structured EVIDENCE field points at a volatile /tmp path.

    Scoped to evidence-fields (structured keys), so an ephemeral /tmp scratch
    path inside a playbook how-to command is NOT flagged (it is not an evidence
    citation) — the finding-#11 allowlist.
    """
    if not _is_evidence_field(field):
        return False
    v = str(value).strip().strip("'\"")
    return v.startswith(("/tmp/", "/private/tmp/"))


_YAML_KV = re.compile(r"^\s*([A-Za-z0-9_]+)\s*:\s*(.+?)\s*$")


def find_tmp_evidence_refs(files: list[Path]) -> list[dict]:
    """Scan committed structured (YAML) files for evidence fields under /tmp."""
    out: list[dict] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.splitlines()):
            m = _YAML_KV.match(line)
            if not m:
                continue
            field, value = m.group(1), m.group(2)
            if is_tmp_evidence_ref(field, value):
                out.append({
                    "file": str(f.relative_to(REPO_ROOT)),
                    "line": i + 1,
                    "field": field,
                    "value": value,
                })
    return out


# ─────────────────────────── aggregation ───────────────────────────────────


def aggregate_gating_failures(
    check_a_res: dict,
    tmp_evidence_refs: list[dict],
) -> list[str]:
    """Assemble the GATING failure list (Check A + Check C only). Check B
    (unlabeled bench rows) is INFORMATIONAL and never appears here."""
    failures: list[str] = []
    if check_a_res.get("gating_failure"):
        failures.append(
            "CHECK A: " + check_a_res.get("reason", "release tag has no "
                                          "CHANGELOG heading")
        )
    for ref in tmp_evidence_refs:
        failures.append(
            f"CHECK C: {ref['file']}:{ref.get('line', '?')} evidence field "
            f"`{ref['field']}` cites a volatile /tmp path ({ref['value']})"
        )
    return failures


# ─────────────────────────── repo scanning ─────────────────────────────────


def _read_version() -> str:
    text = (REPO_ROOT / "sndr" / "version.py").read_text(encoding="utf-8")
    m = re.search(r'__version__[^=]*=\s*["\']([^"\']+)["\']', text)
    return m.group(1) if m else "0.0.0"


def _read_changelog() -> str:
    p = REPO_ROOT / "CHANGELOG.md"
    return p.read_text(encoding="utf-8") if p.is_file() else ""


# Check B docs (public bench-number carriers).
_BENCH_DOCS = (
    "docs/BENCHMARKS.md", "README.md", "docs/COMPARISONS.md",
    "docs/CONFIGURATION.md", "docs/ARCHITECTURE.md",
)

# Check C structured surfaces (V2 model YAMLs, pins, config catalogs).
_EVIDENCE_GLOBS = (
    "sndr/model_configs/builtin/**/*.yaml",
    "sndr/pins.yaml",
    "configs/**/*.yaml",
)


def _bench_docs() -> list[Path]:
    return [REPO_ROOT / d for d in _BENCH_DOCS if (REPO_ROOT / d).is_file()]


def _evidence_files() -> list[Path]:
    files: list[Path] = []
    for g in _EVIDENCE_GLOBS:
        files.extend(sorted(REPO_ROOT.glob(g)))
    return [f for f in files if f.is_file()]


# Baseline of the CURRENT unlabeled bench rows (regression ratchet). A NEW
# unlabeled row beyond this set surfaces as a distinct WARN even while Check B
# stays non-blocking, so the ~40 legacy-row class cannot silently grow. Promote
# Check B to gating after a docs-wave labels these (the audit-config-catalog
# "informational now, gating after 1-2 cycles" precedent).
# Verified empty 2026-07-05: with caption/heading label-inheritance, every
# committed bench row already carries a (pin, date). Any NEW unlabeled row
# therefore surfaces immediately in new_unlabeled_beyond_baseline. If a
# deliberately-unlabeled legacy row is ever added, pin its signature here with a
# one-line reason rather than reddening the informational WARN.
_BASELINE_UNLABELED: frozenset[str] = frozenset()


def run_audit() -> dict:
    version = _read_version()
    check_a_res = check_a(version, _read_changelog())

    unlabeled: list[dict] = []
    for doc in _bench_docs():
        unlabeled.extend(
            find_unlabeled_bench_rows(
                str(doc.relative_to(REPO_ROOT)),
                doc.read_text(encoding="utf-8"),
            )
        )
    new_beyond_baseline = [
        r for r in unlabeled if r["signature"] not in _BASELINE_UNLABELED
    ]

    tmp_refs = find_tmp_evidence_refs(_evidence_files())
    gating_failures = aggregate_gating_failures(check_a_res, tmp_refs)

    informational: list[str] = []
    if new_beyond_baseline:
        informational.append(
            f"{len(new_beyond_baseline)} NEW unlabeled bench row(s) beyond the "
            f"baseline — add a (pin, date) label (inline or table caption)"
        )

    return {
        "version": version,
        "is_release_shaped": check_a_res["is_release_shaped"],
        "changelog_heading_found": check_a_res["changelog_heading_found"],
        "check_a_reason": check_a_res["reason"],
        "unlabeled_bench_rows": unlabeled,
        "unlabeled_baseline_count": len(_BASELINE_UNLABELED),
        "new_unlabeled_beyond_baseline": new_beyond_baseline,
        "tmp_evidence_refs": tmp_refs,
        "gating_failures": gating_failures,
        "informational_warnings": informational,
    }


def _print_human(res: dict) -> None:
    print("Truth-claim provenance gate")
    print("=" * 52)
    print(f"  version: {res['version']}  "
          f"(release-shaped={res['is_release_shaped']})")
    print(f"  CHECK A  changelog heading: "
          f"{'FOUND' if res['changelog_heading_found'] else 'absent'} "
          f"-> {res['check_a_reason']}")
    print(f"  CHECK C  /tmp evidence refs: {len(res['tmp_evidence_refs'])}")
    for ref in res["tmp_evidence_refs"]:
        print(f"    - {ref['file']}:{ref['line']} {ref['field']} = {ref['value']}")
    print(f"  CHECK B  unlabeled bench rows: {len(res['unlabeled_bench_rows'])} "
          f"(baseline {res['unlabeled_baseline_count']}, "
          f"new {len(res['new_unlabeled_beyond_baseline'])})  [informational]")
    for r in res["new_unlabeled_beyond_baseline"]:
        print(f"    ! NEW {r['doc']}:{r['line']}  {r['row']}")
    if res["gating_failures"]:
        print("\n  GATING FAILURES:")
        for f in res["gating_failures"]:
            print(f"    ✗ {f}")
    else:
        print("\n  gating checks (A + C): PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true",
                        help="emit machine-readable JSON")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 if any GATING check (A or C) fails")
    parser.add_argument("--emit-md", metavar="PATH",
                        help="also write a short Markdown summary to PATH")
    args = parser.parse_args()

    res = run_audit()

    if args.json:
        print(json.dumps(res, indent=2, sort_keys=True))
    else:
        _print_human(res)

    if args.emit_md:
        Path(args.emit_md).write_text(
            f"# Truth-claim provenance\n\n"
            f"- version: `{res['version']}` "
            f"(release-shaped: {res['is_release_shaped']})\n"
            f"- CHANGELOG heading: {res['changelog_heading_found']}\n"
            f"- /tmp evidence refs: {len(res['tmp_evidence_refs'])}\n"
            f"- unlabeled bench rows: {len(res['unlabeled_bench_rows'])} "
            f"({len(res['new_unlabeled_beyond_baseline'])} new)\n",
            encoding="utf-8",
        )

    if args.strict and res["gating_failures"]:
        print(f"\n⚠ --strict failed: {len(res['gating_failures'])} gating "
              f"failure(s) above.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
