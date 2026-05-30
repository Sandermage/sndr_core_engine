# SPDX-License-Identifier: Apache-2.0
"""Tests for `scripts/audit_no_new_v1.py` — Phase 9 V1 freeze gate.

Contract:

  1. FROZEN_V1_BASELINE is a frozenset (immutable, can't be mutated
     accidentally).
  2. _current_v1_files scans only top-level builtin/*.yaml (not subdirs).
  3. Live repo currently matches the frozen baseline (regression anchor).
  4. main() exits 0 on clean, 1 on drift (added or removed file).
  5. --json mode emits structured payload with frozen_baseline/current/
     added/removed/passed.
  6. Subdirectory yamls (model/, hardware/, profile/, presets/) are
     ignored — those are V2 layered and not subject to V1 freeze.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "audit_no_new_v1.py"


def _import_script():
    name = "_audit_no_new_v1_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ─── Baseline immutability ─────────────────────────────────────────────


class TestBaseline:
    def test_baseline_is_frozenset(self):
        mod = _import_script()
        assert isinstance(mod.FROZEN_V1_BASELINE, frozenset)

    def test_baseline_non_empty(self):
        mod = _import_script()
        assert len(mod.FROZEN_V1_BASELINE) > 0

    def test_baseline_yaml_filenames(self):
        mod = _import_script()
        for name in mod.FROZEN_V1_BASELINE:
            assert name.endswith(".yaml"), f"{name} not a YAML file"
            assert "/" not in name, (
                f"{name} contains path separator — baseline tracks bare filenames"
            )


# ─── Live regression anchor ────────────────────────────────────────────


class TestLiveRepo:
    def test_current_files_match_baseline(self):
        """Live repo state matches the frozen baseline. Anchor — fails
        if someone adds a top-level V1 yaml without updating the
        frozenset."""
        mod = _import_script()
        current = mod._current_v1_files()
        added = current - mod.FROZEN_V1_BASELINE
        removed = mod.FROZEN_V1_BASELINE - current
        assert not added, (
            f"NEW top-level V1 yaml(s) not in baseline: {sorted(added)}"
        )
        assert not removed, (
            f"baseline V1 yaml(s) MISSING from tree: {sorted(removed)}"
        )

    def test_main_exits_zero_on_clean(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0


# ─── Subdir isolation ──────────────────────────────────────────────────


class TestSubdirIsolation:
    def test_subdirs_ignored(self, tmp_path, monkeypatch):
        """Subdir yamls (model/, hardware/ etc) must NOT count as V1."""
        mod = _import_script()
        # Build fake builtin tree
        builtin = tmp_path / "builtin"
        (builtin).mkdir()
        (builtin / "single.yaml").write_text("# top-level V1\n")
        (builtin / "model").mkdir()
        (builtin / "model" / "subdir.yaml").write_text("# V2 model\n")
        (builtin / "hardware").mkdir()
        (builtin / "hardware" / "rig.yaml").write_text("# V2 hw\n")

        monkeypatch.setattr(mod, "BUILTIN_DIR", builtin)
        current = mod._current_v1_files()
        assert current == {"single.yaml"}


# ─── Drift detection ────────────────────────────────────────────────────


class TestDriftDetection:
    def test_added_file_triggers_exit_1(self, tmp_path, monkeypatch):
        mod = _import_script()
        builtin = tmp_path / "builtin"
        builtin.mkdir()
        # Recreate the baseline files
        for name in mod.FROZEN_V1_BASELINE:
            (builtin / name).write_text("# placeholder\n")
        # Add an unauthorized file
        (builtin / "rogue-extra.yaml").write_text("# not in baseline\n")

        monkeypatch.setattr(mod, "BUILTIN_DIR", builtin)
        monkeypatch.setattr(sys, "argv", ["audit_no_new_v1.py"])
        rc = mod.main()
        assert rc == 1

    def test_removed_file_triggers_exit_1(self, tmp_path, monkeypatch):
        mod = _import_script()
        builtin = tmp_path / "builtin"
        builtin.mkdir()
        # Recreate baseline MINUS one entry
        first = next(iter(sorted(mod.FROZEN_V1_BASELINE)))
        for name in mod.FROZEN_V1_BASELINE:
            if name == first:
                continue
            (builtin / name).write_text("# placeholder\n")

        monkeypatch.setattr(mod, "BUILTIN_DIR", builtin)
        monkeypatch.setattr(sys, "argv", ["audit_no_new_v1.py"])
        rc = mod.main()
        assert rc == 1


# ─── JSON output shape ──────────────────────────────────────────────────


class TestJsonOutput:
    def test_json_shape_clean(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--json"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert "frozen_baseline" in payload
        assert "current" in payload
        assert "added" in payload
        assert "removed" in payload
        assert "passed" in payload
        assert payload["passed"] is True
        assert payload["added"] == []
        assert payload["removed"] == []
