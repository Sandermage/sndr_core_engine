"""Truth-claim provenance gate — unit tests (TDD red-first).

Closes the deterministic parts of audit-2026-07-04 findings #3 (a release tag
existed with no CHANGELOG heading), #11 (evidence cited from volatile /tmp), and
adds an informational ratchet for #2/#9/#23/#45 (bench numbers cited without a
(pin, date) label).

The three checks:
  A (GATING)        release tag <-> CHANGELOG heading
  B (INFORMATIONAL) bench rows carry a (pin, date) label
  C (GATING)        evidence cited from a durable path, not /tmp

Each check is extracted as a PURE function so it is unit-testable without
mutating the repo.
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "audit_claim_provenance.py"

acp = pytest.importorskip("scripts.audit_claim_provenance")


# ─── existence + real-tree integration ─────────────────────────────────────


def test_script_exists():
    assert SCRIPT.is_file(), SCRIPT


def test_runs_and_exits_zero_on_current_tree():
    # the real repo must PASS: A heading present ([v12.1.0]); C clean (0 /tmp
    # evidence refs); B informational (never blocks).
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--strict"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), check=False,
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"


def test_json_mode_structured():
    import json
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), check=False,
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    for key in (
        "version", "is_release_shaped", "changelog_heading_found",
        "unlabeled_bench_rows", "unlabeled_baseline_count",
        "new_unlabeled_beyond_baseline", "tmp_evidence_refs",
        "gating_failures", "informational_warnings",
    ):
        assert key in data, f"missing key {key}: {list(data)}"


# ─── Check A: release tag <-> CHANGELOG heading (pure fn) ───────────────────


def test_is_release_shaped():
    assert acp.is_release_shaped("12.1.0") is True
    assert acp.is_release_shaped("12.2.0.dev1") is False
    assert acp.is_release_shaped("12.2.0rc1") is False
    assert acp.is_release_shaped("0.23.1a2") is False
    assert acp.is_release_shaped("12.1.0b3") is False


def test_changelog_has_heading_accepts_both_bracket_forms():
    text = "## [v12.1.0] — dev748 pin (2026-07-04)\nbody\n"
    assert acp.changelog_has_heading("12.1.0", text) is True
    text2 = "## [12.1.0] — release (2026-07-04)\n"
    assert acp.changelog_has_heading("12.1.0", text2) is True


def test_changelog_has_heading_false_when_absent():
    text = "## [v12.0.0] — old\n## [Unreleased]\n"
    assert acp.changelog_has_heading("99.9.9", text) is False


def test_check_a_prerelease_is_not_a_gating_failure():
    # a dev/rc version legitimately has no cut heading -> A informational/skipped
    res = acp.check_a("12.2.0.dev1", changelog_text="## [v12.1.0]\n")
    assert res["gating_failure"] is False
    assert res["is_release_shaped"] is False


def test_check_a_release_without_heading_is_gating_failure():
    res = acp.check_a("13.0.0", changelog_text="## [v12.1.0]\nno 13 here\n")
    assert res["is_release_shaped"] is True
    assert res["changelog_heading_found"] is False
    assert res["gating_failure"] is True


def test_check_a_release_with_heading_passes():
    res = acp.check_a("12.1.0", changelog_text="## [v12.1.0] — x (2026-07-04)\n")
    assert res["gating_failure"] is False
    assert res["changelog_heading_found"] is True


# ─── Check B: bench-row (pin, date) label (pure fn) ─────────────────────────


def test_row_is_labeled_inline_pin_and_date():
    row = "| Model X | dev748 | 242 t/s | 2026-07-04 |"
    assert acp.row_is_labeled(row, context="") is True


def test_row_is_labeled_false_when_bare():
    row = "| Model X | 242 t/s | fast |"
    assert acp.row_is_labeled(row, context="") is False


def test_row_is_labeled_inherits_from_caption_context():
    # pin in the row column, date in the section caption above the table
    row = "| Model X | dev748 | 242 t/s |"
    ctx = "## Fleet sweep (promotion gate 2026-07-04)\n"
    assert acp.row_is_labeled(row, context=ctx) is True


def test_row_is_labeled_needs_both_pin_and_date():
    # date present but no pin token anywhere -> unlabeled
    row = "| Model X | 242 t/s | 2026-07-04 |"
    assert acp.row_is_labeled(row, context="") is False


def test_is_bench_row_matches_metric_tokens():
    assert acp.is_bench_row("| m | 242 t/s |")
    assert acp.is_bench_row("| m | 3.9 ms | 242 TPS |")
    assert acp.is_bench_row("| m | accept-rate 0.65 |")
    assert not acp.is_bench_row("| Metric | What it captures | Why |")
    assert not acp.is_bench_row("plain prose line")


# ─── Check C: evidence path durability (pure fn) ────────────────────────────


def test_is_tmp_evidence_ref_flags_tmp_reference_metrics():
    assert acp.is_tmp_evidence_ref(
        "reference_metrics_ref", "/tmp/bench_x.json") is True
    assert acp.is_tmp_evidence_ref(
        "reference_metrics_ref", "/private/tmp/bench_x.json") is True


def test_is_tmp_evidence_ref_ok_for_durable_path():
    assert acp.is_tmp_evidence_ref(
        "reference_metrics_ref", "evidence/baselines/35b.json") is False
    assert acp.is_tmp_evidence_ref(
        "reference_metrics_ref", "releases/v12.1.0/bench.json") is False


def test_is_tmp_evidence_ref_ignores_non_evidence_field():
    # a non-evidence structured key pointing at /tmp is NOT this finding's class
    assert acp.is_tmp_evidence_ref("some_scratch_dir", "/tmp/x.json") is False


# ─── strict exit reflects only gating checks ───────────────────────────────


def test_strict_exit_only_reflects_gating(tmp_path):
    # a gating failure (release version, no heading) -> the aggregation marks it
    findings = acp.aggregate_gating_failures(
        check_a_res={"gating_failure": True, "reason": "no heading for 13.0.0"},
        tmp_evidence_refs=[],
    )
    assert findings, "check A gating failure must surface"

    # informational-only (unlabeled bench rows beyond baseline) must NOT be in
    # the gating-failure aggregation
    findings2 = acp.aggregate_gating_failures(
        check_a_res={"gating_failure": False},
        tmp_evidence_refs=[],
    )
    assert findings2 == []


def test_tmp_evidence_ref_is_gating():
    findings = acp.aggregate_gating_failures(
        check_a_res={"gating_failure": False},
        tmp_evidence_refs=[{"file": "m.yaml", "field": "reference_metrics_ref",
                            "value": "/tmp/x.json"}],
    )
    assert findings, "a /tmp evidence ref must be a gating failure"
