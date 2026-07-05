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
        capture_output=True, text=True, cwd=REPO_ROOT, check=False,
    )
    assert proc.returncode == 0
    assert "Stale vllm_version_range audit" in proc.stdout


def test_audit_json_mode_structured():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True, text=True, cwd=REPO_ROOT, check=False,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert "pin" in data
    assert "total_stale_ranges" in data
    assert "critical_count" in data
    assert "warn_count" in data
    assert "rows" in data


def test_no_new_critical_beyond_baseline():
    """v11.3.0 BUG #14: CRITICAL = default_on=True silently skipping
    OR opt-in patch enabled-in-builtin-YAML silently no-oping. The
    19 known entries are pinned in
    `_BASELINE_CRITICAL_STALE` and surface as INFO in audit output.

    Any CRITICAL outside that baseline is a NEW regression: either
    a recently-added patch has a stale upper bound, or a YAML newly
    enables a patch whose range hasn't been bumped. Force review.
    """
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True, text=True, cwd=REPO_ROOT, check=False,
    )
    data = json.loads(proc.stdout)
    # Import baseline directly so this test breaks atomically with
    # any baseline change in the audit script.
    import sys as _sys
    if str(REPO_ROOT) not in _sys.path:
        _sys.path.insert(0, str(REPO_ROOT))
    from scripts.audit_stale_vllm_version_ranges import (
        _BASELINE_CRITICAL_STALE,
    )
    critical_pids = {
        r["patch_id"] for r in data["rows"] if r["severity"] == "CRITICAL"
    }
    new = sorted(critical_pids - _BASELINE_CRITICAL_STALE)
    assert not new, (
        f"{len(new)} NEW CRITICAL stale-range entries beyond v11.3.0 "
        f"baseline:\n" + "\n".join(f"  - {p}" for p in new) +
        "\n\nFix the range in registry.py OR add to baseline "
        "_BASELINE_CRITICAL_STALE in scripts/audit_stale_vllm_version_ranges.py"
    )


def test_strict_mode_respects_baseline():
    """`--strict` should exit 0 when all CRITICAL entries are in the
    v11.3.0 baseline (known queued work, not a regression). Exits 1
    only on NEW critical entries beyond baseline.
    """
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--strict"],
        capture_output=True, text=True, cwd=REPO_ROOT, check=False,
    )
    # Currently 19 CRITICAL all in baseline → --strict should pass
    assert proc.returncode == 0, (
        f"--strict failed at v11.3.0 baseline (expected 0). "
        f"Stderr:\n{proc.stderr}"
    )


def test_pin_override_works():
    """`--pin VERSION` lets the audit run against an arbitrary pin —
    useful for "what if we bumped to X" experiments."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--pin", "0.99.0", "--json"],
        capture_output=True, text=True, cwd=REPO_ROOT, check=False,
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
        capture_output=True, text=True, cwd=REPO_ROOT, check=False,
    )
    data = json.loads(proc.stdout)
    warn = data["warn_count"]
    # Bound: 0 (all cleaned up) to 50 (lots of drift accumulated)
    assert 0 <= warn <= 50, (
        f"WARN count {warn} outside expected 0-50 range. Either many "
        f"ranges were just fixed (GOOD — lower the bound) or many "
        f"patches were added with stale ranges (BAD — investigate)."
    )


def test_resolve_current_pin_prefers_pins_yaml_ssot():
    """The 'current pin' MUST come from the pins.yaml SSOT, not from
    whatever vllm happens to be installed in the venv. CI installs an
    older vllm (dev714) than our declared current pin (dev748); trusting
    the package made PN523-526 (lower bound >=dev748) falsely flag as
    range-excludes-current CRITICAL on CI while passing locally
    (regression 2026-07-05)."""
    import importlib.util
    import sys
    import types
    spec = importlib.util.spec_from_file_location("_stale_audit", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from sndr import pins
    # Reproduce the CI condition: an OLDER vllm installed in the venv.
    fake = types.ModuleType("vllm")
    fake.__version__ = "0.23.1rc1.dev714+g09663abde"
    saved = sys.modules.get("vllm")
    sys.modules["vllm"] = fake
    try:
        assert mod._resolve_current_pin(None) == pins.current()
    finally:
        if saved is not None:
            sys.modules["vllm"] = saved
        else:
            sys.modules.pop("vllm", None)


def test_default_pin_matches_current_ssot():
    """DEFAULT_PIN is the last-ditch fallback (reached only if the pins.yaml
    read AND the sndr package AND guards all fail). It must not lag the SSOT:
    a stale literal here silently evaluates version ranges against an old pin.
    bump_pin.py auto-maintains it; this test is the backstop that goes RED on
    any bump that forgets it (2026-07-05 integrity audit; the literal was the
    dev714 rollback pin, one bump behind current)."""
    import importlib.util

    from sndr import pins
    spec = importlib.util.spec_from_file_location("_stale_audit_dp", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert pins.current() == mod.DEFAULT_PIN, (
        f"DEFAULT_PIN ({mod.DEFAULT_PIN}) must track pins.yaml current "
        f"({pins.current()}); run scripts/bump_pin.py so it auto-updates"
    )


def test_resolve_pin_survives_sndr_package_import_failure():
    """CI robustness: even when `from sndr import pins` and the guards module
    fail to import (lean CI env, optional-dep ImportError), the resolver MUST
    still return the pins.yaml SSOT via the direct file read — never the stale
    static default. Regression 2026-07-05: DEFAULT_PIN=dev714 leaked through
    on CI and mis-flagged forward-dated patches (PN523-526)."""
    import importlib.util
    import sys

    import yaml
    spec = importlib.util.spec_from_file_location("_stale_audit2", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Poison the package imports the resolver would otherwise use.
    saved = {k: sys.modules.get(k) for k in ("sndr", "sndr.pins")}
    sys.modules["sndr"] = None  # -> `from sndr import pins` raises
    try:
        # guards path also unusable now; only the direct pins.yaml read remains
        resolved = mod._resolve_current_pin(None)
    finally:
        for k, v in saved.items():
            if v is not None:
                sys.modules[k] = v
            else:
                sys.modules.pop(k, None)
    expected = yaml.safe_load((REPO_ROOT / "sndr" / "pins.yaml").read_text())["current"]
    assert resolved == expected
