# SPDX-License-Identifier: Apache-2.0
"""Unit test for the stale vllm_version_range audit script.

Regression guard for CLAUDE.md Class 5 known-bug surface:

  - CRITICAL count MUST be 0 — no default_on=True patch may silently
    skip on the current pin due to stale version range upper bound
  - WARN count tracked but not pinned (allowed to drift with pin bumps)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "audit_stale_vllm_version_ranges.py"


def test_script_exists():
    assert SCRIPT.is_file()


def test_audit_runs_and_exits_zero():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert proc.returncode == 0
    assert "Stale vllm_version_range audit" in proc.stdout


def test_audit_json_mode_structured():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert "pin" in data
    assert "total_stale_ranges" in data
    assert "critical_count" in data
    assert "warn_count" in data
    assert "rows" in data


def test_no_critical_default_on_silent_skip():
    """CRITICAL pin: no default_on=True patch may silently skip on the
    current pin due to a stale `vllm_version_range` upper bound.

    If this fails, a default_on patch was added with a version range
    that excludes the current pin. Operators would silently lose the
    patch in production. Fix the range immediately."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    data = json.loads(proc.stdout)
    critical = data["critical_count"]
    if critical > 0:
        critical_rows = [
            r for r in data["rows"] if r["severity"] == "CRITICAL"
        ]
        raise AssertionError(
            f"{critical} default_on=True patch(es) silently skip on current "
            f"pin {data['pin']!r}:\n" + "\n".join(
                f"  - {r['patch_id']}: range={r['vllm_version_range']}"
                for r in critical_rows
            ) + "\n\nFix the vllm_version_range to include the current pin."
        )


def test_strict_mode_passes_when_no_critical():
    """`--strict` should exit 0 when critical_count is 0."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--strict", "--json"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    data = json.loads(proc.stdout)
    critical = data["critical_count"]
    if critical == 0:
        assert proc.returncode == 0, (
            "--strict returned non-zero despite critical_count=0"
        )
    else:
        assert proc.returncode == 1, (
            "--strict must return 1 when critical_count > 0"
        )


def test_pin_override_works():
    """`--pin VERSION` lets the audit run against an arbitrary pin —
    useful for "what if we bumped to X" experiments."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--pin", "0.99.0", "--json"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["pin"] == "0.99.0"
    # On a high pin, many ranges will look stale
    assert data["total_stale_ranges"] >= 1


def test_warn_count_within_documented_range():
    """WARN count baseline check — tracks doc-drift across pin bumps.

    At v11.3.0 baseline: ~25 WARN entries (patches with `<0.21.0`
    upper bound but actually working on 0.21.x via operator opt-in).

    Bound the count loosely so natural drift (patches retiring,
    bumping ranges) doesn't break CI."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    data = json.loads(proc.stdout)
    warn = data["warn_count"]
    # Bound: 0 (all cleaned up) to 50 (lots of drift accumulated)
    assert 0 <= warn <= 50, (
        f"WARN count {warn} outside expected 0-50 range. Either many "
        f"ranges were just fixed (GOOD — lower the bound) or many "
        f"patches were added with stale ranges (BAD — investigate)."
    )
