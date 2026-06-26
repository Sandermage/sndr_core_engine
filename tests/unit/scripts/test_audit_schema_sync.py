# SPDX-License-Identifier: Apache-2.0
"""Tests for `scripts/audit_schema_sync.py` — schema mirror parity gate.

Contract:

  1. Live canonical + mirror schemas are byte-identical (regression
     anchor — catches divergence at CI before it ships).
  2. main() exits 0 when both files exist and match.
  3. main() exits 1 when canonical is missing.
  4. main() exits 1 when mirror is missing.
  5. main() exits 1 when both exist but byte-differ.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "audit_schema_sync.py"


def _import_script():
    name = "_audit_schema_sync_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestLive:
    def test_canonical_exists(self):
        mod = _import_script()
        assert mod.CANONICAL.exists(), (
            f"canonical schema missing: {mod.CANONICAL}"
        )

    def test_mirror_exists(self):
        mod = _import_script()
        assert mod.MIRROR.exists(), (
            f"root mirror missing: {mod.MIRROR}"
        )

    def test_live_repo_schemas_match(self):
        """Regression anchor — if this fails, the two schemas have
        drifted and the operator forgot to mirror after editing."""
        mod = _import_script()
        assert mod.CANONICAL.read_bytes() == mod.MIRROR.read_bytes(), (
            f"schemas differ: canonical {len(mod.CANONICAL.read_bytes())} "
            f"bytes vs mirror {len(mod.MIRROR.read_bytes())} bytes — "
            f"run `cp {mod.CANONICAL} {mod.MIRROR}`."
        )

    def test_main_exits_zero(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0


class TestMissingFiles:
    def test_missing_canonical_returns_1(self, tmp_path, monkeypatch):
        mod = _import_script()
        # Monkeypatch REPO_ROOT alongside paths so the script's
        # `.relative_to(REPO_ROOT)` formatting in error messages works
        # against the tmp tree.
        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(mod, "CANONICAL", tmp_path / "missing.json")
        monkeypatch.setattr(mod, "MIRROR", tmp_path / "present.json")
        (tmp_path / "present.json").write_bytes(b"{}\n")
        rc = mod.main()
        assert rc == 1

    def test_missing_mirror_returns_1(self, tmp_path, monkeypatch):
        mod = _import_script()
        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(mod, "CANONICAL", tmp_path / "canon.json")
        monkeypatch.setattr(mod, "MIRROR", tmp_path / "missing.json")
        (tmp_path / "canon.json").write_bytes(b"{}\n")
        rc = mod.main()
        assert rc == 1


class TestDriftDetection:
    def test_byte_diff_returns_1(self, tmp_path, monkeypatch):
        mod = _import_script()
        canonical = tmp_path / "canonical.json"
        mirror = tmp_path / "mirror.json"
        canonical.write_bytes(b'{"a": 1}\n')
        mirror.write_bytes(b'{"a": 2}\n')  # differs
        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(mod, "CANONICAL", canonical)
        monkeypatch.setattr(mod, "MIRROR", mirror)
        rc = mod.main()
        assert rc == 1

    def test_identical_returns_0(self, tmp_path, monkeypatch):
        mod = _import_script()
        canonical = tmp_path / "canonical.json"
        mirror = tmp_path / "mirror.json"
        payload = b'{"sample": "schema"}\n'
        canonical.write_bytes(payload)
        mirror.write_bytes(payload)
        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(mod, "CANONICAL", canonical)
        monkeypatch.setattr(mod, "MIRROR", mirror)
        rc = mod.main()
        assert rc == 0
