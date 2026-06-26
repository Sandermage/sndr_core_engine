# SPDX-License-Identifier: Apache-2.0
"""Unit test for the Phase 6 P3.4 dispatcher migration readiness audit."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "audit_dispatcher_migration_readiness.py"


def test_script_exists_and_is_executable():
    assert SCRIPT.is_file()


def test_audit_runs_and_exits_zero():
    """Default mode (no flags) prints the human report + returns 0."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert proc.returncode == 0
    assert "Dispatcher migration readiness audit" in proc.stdout
    assert "Total PATCH_REGISTRY entries" in proc.stdout


def test_audit_json_mode_returns_structured_output():
    """--json flag emits a parseable JSON payload."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert "buckets" in data
    assert "summary" in data
    assert "total_entries" in data["summary"]
    assert "real_gaps" in data["summary"]
    assert "migration_safe" in data["summary"]


def test_audit_reports_real_gaps_zero():
    """The live registry has no real gaps — migration is ready.

    If this test fails, it means a new patch was added without an
    apply_module OR without a lifecycle override. Update the registry
    or the audit categorization rules.
    """
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    data = json.loads(proc.stdout)
    real_gaps = data["summary"]["real_gaps"]
    gap_list = data["buckets"]["REAL_GAPS"]
    assert real_gaps == 0, (
        f"unexpected real gaps in PATCH_REGISTRY: {gap_list}. "
        f"Either add an apply_module or a lifecycle override."
    )
    assert data["summary"]["migration_safe"] is True


def test_audit_strict_mode_returns_zero_when_safe():
    """--strict + 0 real gaps = exit 0."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--strict"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert proc.returncode == 0


def test_audit_summary_percentages_consistent():
    """The percentages reported sum to ~100%."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    data = json.loads(proc.stdout)
    total = (
        data["summary"]["spec_ready_pct"]
        + data["summary"]["intentionally_unmapped_pct"]
        + data["summary"]["real_gaps_pct"]
    )
    # Rounding tolerance — three pcts each rounded to 0.1
    assert abs(total - 100.0) < 0.3, (
        f"percentages don't sum to ~100: {total}"
    )
