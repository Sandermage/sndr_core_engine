# SPDX-License-Identifier: Apache-2.0
"""Tests for ``scripts/audit_pn59_cliff2b_markers.py``.

Cliff 2b regression guard (club-3090 #22 / #182 — see
``sndr_private/planning/audits/CLUB3090_CROSS_REFERENCE_2026-05-29_RU.md``).
The audit prevents accidental Genesis rollback below v7.72.5 from
silently reverting PN59's chunked-prefill engagement.

Coverage:
    1. ``_audit()`` against crafted text — all-present, all-missing,
       partial-missing fixtures.
    2. Tracked-tree smoke confirms the live PN59 driver carries all four
       Level 2 markers (verified 2026-05-29 grep).
    3. JSON shape regression.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "audit_pn59_cliff2b_markers.py"


def _import_audit_module():
    spec = importlib.util.spec_from_file_location(
        "audit_pn59_cliff2b_markers", SCRIPT_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["audit_pn59_cliff2b_markers"] = mod
    assert spec.loader is not None  # nosec
    spec.loader.exec_module(mod)
    return mod


# ───────────────────────── pure-function coverage ──────────────────────


def test_all_markers_present() -> None:
    mod = _import_audit_module()
    text = (
        "def _slice_chunk_metadata_for_window(args):\n"
        "    pass\n"
        "GENESIS_PN59_STRICT_NO_METADATA = 0\n"
        "if GdnScratchPool.is_production_eligible():\n"
        "    o = GdnScratchPool.acquire_o_output(...)\n"
    )
    status = mod._audit(text)
    assert all(s.present for s in status)
    assert len(status) == 4


def test_all_markers_missing() -> None:
    mod = _import_audit_module()
    text = "# unrelated v7.72.2-style driver code\nimport sys\n"
    status = mod._audit(text)
    assert all(not s.present for s in status)
    assert len(status) == 4


def test_partial_markers_missing() -> None:
    """v7.72.3-style hypothetical state — Level 2A landed, 2C/D not yet."""
    mod = _import_audit_module()
    text = (
        "def _slice_chunk_metadata_for_window(args):\n"
        "    pass\n"
        "GENESIS_PN59_STRICT_NO_METADATA = 0\n"
        # No GdnScratchPool calls → Level 2C and 2C+D missing
    )
    status = mod._audit(text)
    present = [s for s in status if s.present]
    missing = [s for s in status if not s.present]
    assert len(present) == 2
    assert len(missing) == 2
    assert all(s.level == "2A" for s in present)
    assert all(s.level in ("2C", "2C+D") for s in missing)


# ───────────────────────── tracked-tree smoke ─────────────────────────


def test_tracked_tree_passes_strict() -> None:
    """Live PN59 driver in tracked tree carries all 4 Level 2 markers
    as of 2026-05-29 (verified manually + automated)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--strict"],
        cwd=REPO_ROOT,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"audit_pn59_cliff2b_markers --strict failed — PN59 may have been "
        f"rolled back below v7.72.5; Cliff 2b would re-open:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_json_shape() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--json"],
        cwd=REPO_ROOT,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert {"target", "total", "missing", "markers", "pass"} <= data.keys()
    assert data["total"] == 4
    assert data["missing"] == 0
    assert data["pass"] is True
    assert len(data["markers"]) == 4
    for m in data["markers"]:
        assert {"level", "label", "sentinel", "present"} <= m.keys()
        assert m["present"] is True


def test_missing_target_returns_2(tmp_path: Path) -> None:
    """If the driver file disappears, exit code 2 (not 1) so CI surfaces
    a distinct failure mode."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--root", str(tmp_path)],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 2
