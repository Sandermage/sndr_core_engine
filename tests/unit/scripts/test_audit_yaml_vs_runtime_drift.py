# SPDX-License-Identifier: Apache-2.0
"""Tests for ``scripts/audit_yaml_vs_runtime_drift.py`` —
TOOLING-HARDENING.2 L.8 (2026-05-26).

Strategy:

  * Pure-function audit core (``audit(yaml_keys, live_keys)``) is
    exercised directly with synthetic dicts — no docker, no subprocess.
  * Parser helpers (``parse_yaml_genesis_keys``, ``parse_live_env``)
    get unit coverage with crafted YAML and docker-inspect-style inputs.
  * End-to-end CLI is tested via the ``--from-env-file`` hook, which
    bypasses docker so the live-corpus tests never depend on a running
    container.

The shell sibling at ``tools/audit_yaml_vs_runtime.sh`` stays the
canonical bash entry point; this Python port matches its semantics
byte-for-byte (drift classifications + exit codes 0/1/2).
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "audit_yaml_vs_runtime_drift.py"


def _import_audit_module():
    spec = importlib.util.spec_from_file_location(
        "audit_yaml_vs_runtime_drift", SCRIPT_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["audit_yaml_vs_runtime_drift"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def audit_mod():
    return _import_audit_module()


class TestParseYamlGenesisKeys:
    """``parse_yaml_genesis_keys`` extracts indented GENESIS_* lines."""

    def test_single_key_with_quoted_value(self, audit_mod):
        text = "genesis_env:\n  GENESIS_ENABLE_P67: '1'\n"
        keys = audit_mod.parse_yaml_genesis_keys(text)
        assert keys == {"GENESIS_ENABLE_P67": "1"}

    def test_multi_keys_with_mixed_quoting(self, audit_mod):
        text = (
            "genesis_env:\n"
            "  GENESIS_ENABLE_P67: '1'\n"
            "  GENESIS_ENABLE_P82: \"0\"\n"
            "  GENESIS_BUFFER_MODE: shared\n"
        )
        keys = audit_mod.parse_yaml_genesis_keys(text)
        assert keys == {
            "GENESIS_ENABLE_P67": "1",
            "GENESIS_ENABLE_P82": "0",
            "GENESIS_BUFFER_MODE": "shared",
        }

    def test_inline_comment_stripped(self, audit_mod):
        text = "  GENESIS_ENABLE_PN90: '1'    # vllm#40269 backport\n"
        keys = audit_mod.parse_yaml_genesis_keys(text)
        assert keys == {"GENESIS_ENABLE_PN90": "1"}

    def test_top_level_keys_ignored(self, audit_mod):
        """Sibling shell ``grep -E "^\\s+GENESIS_"`` requires leading
        whitespace — top-level keys are out of scope."""
        text = "GENESIS_AT_ROOT: '1'\n  GENESIS_INDENTED: '1'\n"
        keys = audit_mod.parse_yaml_genesis_keys(text)
        assert "GENESIS_AT_ROOT" not in keys
        assert keys == {"GENESIS_INDENTED": "1"}

    def test_non_genesis_keys_ignored(self, audit_mod):
        text = "  VLLM_LOGGING_LEVEL: WARNING\n  GENESIS_REAL: '1'\n"
        keys = audit_mod.parse_yaml_genesis_keys(text)
        assert keys == {"GENESIS_REAL": "1"}


class TestParseLiveEnv:
    """``parse_live_env`` parses docker-inspect KEY=VALUE output."""

    def test_single_line(self, audit_mod):
        text = "GENESIS_ENABLE_P67=1\n"
        assert audit_mod.parse_live_env(text) == {"GENESIS_ENABLE_P67": "1"}

    def test_filters_non_genesis(self, audit_mod):
        text = (
            "PATH=/usr/bin\n"
            "GENESIS_BUFFER_MODE=shared\n"
            "VLLM_LOGGING_LEVEL=WARNING\n"
            "GENESIS_ENABLE_P67=1\n"
        )
        out = audit_mod.parse_live_env(text)
        assert out == {
            "GENESIS_BUFFER_MODE": "shared",
            "GENESIS_ENABLE_P67": "1",
        }

    def test_empty_input(self, audit_mod):
        assert audit_mod.parse_live_env("") == {}


class TestAuditCore:
    """Pure-function audit classifier."""

    def test_clean_state_zero_findings(self, audit_mod):
        yaml_keys = {"GENESIS_ENABLE_P67": "1", "GENESIS_BUFFER_MODE": "shared"}
        live_keys = {"GENESIS_ENABLE_P67": "1", "GENESIS_BUFFER_MODE": "shared"}
        findings, exit_code = audit_mod.audit(yaml_keys, live_keys)
        assert findings == []
        assert exit_code == 0

    def test_yaml_enables_but_live_missing_is_drift(self, audit_mod):
        yaml_keys = {"GENESIS_ENABLE_PN90": "1"}
        live_keys = {}
        findings, exit_code = audit_mod.audit(yaml_keys, live_keys)
        assert exit_code == 1
        assert len(findings) == 1
        assert findings[0].key == "GENESIS_ENABLE_PN90"
        assert findings[0].classification == "drift"

    def test_yaml_explicit_zero_is_ok_disable(self, audit_mod):
        """YAML sets KEY: '0', live env doesn't have it → not drift."""
        yaml_keys = {"GENESIS_ENABLE_P82": "0"}
        live_keys = {}
        findings, exit_code = audit_mod.audit(yaml_keys, live_keys)
        assert exit_code == 0
        assert len(findings) == 1
        assert findings[0].classification == "ok_disable"

    def test_live_has_extra_is_drift(self, audit_mod):
        yaml_keys = {}
        live_keys = {"GENESIS_ENABLE_P67": "1"}
        findings, exit_code = audit_mod.audit(yaml_keys, live_keys)
        assert exit_code == 1
        assert findings[0].classification == "extra"

    def test_live_pn95_prefix_is_intentional(self, audit_mod):
        """PN95 experiment additions are not drift."""
        yaml_keys = {}
        live_keys = {
            "GENESIS_PN95_TIER_BUDGET": "8192",
            "GENESIS_ENABLE_PN95_EXTRAS": "1",
        }
        findings, exit_code = audit_mod.audit(yaml_keys, live_keys)
        assert exit_code == 0
        assert all(f.classification == "intentional_pn95" for f in findings)
        assert len(findings) == 2

    def test_mixed_scenario(self, audit_mod):
        """All four classifications fire correctly in one call."""
        yaml_keys = {
            "GENESIS_ENABLE_P67": "1",      # matches live → no finding
            "GENESIS_ENABLE_PN90": "1",     # not in live → drift
            "GENESIS_ENABLE_P82": "0",      # not in live, explicit 0 → ok_disable
        }
        live_keys = {
            "GENESIS_ENABLE_P67": "1",
            "GENESIS_PN95_RUNTIME": "1",    # PN95 prefix → intentional
            "GENESIS_EXTRA_FLAG": "1",      # not in YAML → extra
        }
        findings, exit_code = audit_mod.audit(yaml_keys, live_keys)
        assert exit_code == 1  # because of drift + extra

        by_class = {f.classification: f.key for f in findings}
        assert by_class.get("drift") == "GENESIS_ENABLE_PN90"
        assert by_class.get("ok_disable") == "GENESIS_ENABLE_P82"
        assert by_class.get("intentional_pn95") == "GENESIS_PN95_RUNTIME"
        assert by_class.get("extra") == "GENESIS_EXTRA_FLAG"

    def test_findings_sorted_deterministically(self, audit_mod):
        """Output ordering must be stable so diff-style tooling works."""
        yaml_keys = {
            "GENESIS_ENABLE_PZ": "1",
            "GENESIS_ENABLE_PA": "1",
        }
        live_keys = {}
        findings, _ = audit_mod.audit(yaml_keys, live_keys)
        # Sorted alphabetically within the YAML-only section.
        assert [f.key for f in findings] == [
            "GENESIS_ENABLE_PA", "GENESIS_ENABLE_PZ",
        ]


class TestCli:
    """End-to-end through the ``--from-env-file`` hook (no docker)."""

    def _write_yaml(self, tmp_path: Path, content: str) -> Path:
        y = tmp_path / "config.yaml"
        y.write_text(content, encoding="utf-8")
        return y

    def _write_env(self, tmp_path: Path, content: str) -> Path:
        e = tmp_path / "live_env.txt"
        e.write_text(content, encoding="utf-8")
        return e

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )

    def test_clean_state_exit_zero(self, tmp_path):
        yaml_path = self._write_yaml(tmp_path,
            "genesis_env:\n  GENESIS_ENABLE_P67: '1'\n")
        env_path = self._write_env(tmp_path,
            "PATH=/usr/bin\nGENESIS_ENABLE_P67=1\n")
        result = self._run(
            str(yaml_path), "fake-container",
            "--from-env-file", str(env_path),
        )
        assert result.returncode == 0, (
            f"clean state should exit 0, got rc={result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert "No real drift detected" in result.stdout

    def test_drift_exit_one(self, tmp_path):
        yaml_path = self._write_yaml(tmp_path,
            "genesis_env:\n  GENESIS_ENABLE_PN90: '1'\n")
        env_path = self._write_env(tmp_path, "PATH=/usr/bin\n")
        result = self._run(
            str(yaml_path), "fake-container",
            "--from-env-file", str(env_path),
        )
        assert result.returncode == 2, (
            "empty GENESIS_* live env triggers the unobtainable path "
            f"(exit 2), got rc={result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    def test_drift_with_one_live_key_exit_one(self, tmp_path):
        """A real drift case where live env has at least one GENESIS_* key
        (so we pass the non-empty live-env guard) but a YAML key is missing."""
        yaml_path = self._write_yaml(tmp_path,
            "genesis_env:\n"
            "  GENESIS_ENABLE_PN90: '1'\n"
            "  GENESIS_ENABLE_P67: '1'\n")
        env_path = self._write_env(tmp_path,
            "GENESIS_ENABLE_P67=1\n")
        result = self._run(
            str(yaml_path), "fake-container",
            "--from-env-file", str(env_path),
        )
        assert result.returncode == 1, (
            f"missing-PN90 case should exit 1, got rc={result.returncode}\n"
            f"stdout:\n{result.stdout}"
        )
        assert "DRIFT" in result.stdout
        assert "GENESIS_ENABLE_PN90" in result.stdout

    def test_yaml_not_found_exit_two(self, tmp_path):
        result = self._run(
            str(tmp_path / "nonexistent.yaml"), "fake-container",
            "--from-env-file", str(tmp_path / "missing-env.txt"),
        )
        assert result.returncode == 2

    def test_env_file_not_found_exit_two(self, tmp_path):
        yaml_path = self._write_yaml(tmp_path,
            "genesis_env:\n  GENESIS_ENABLE_P67: '1'\n")
        result = self._run(
            str(yaml_path), "fake-container",
            "--from-env-file", str(tmp_path / "missing-env.txt"),
        )
        assert result.returncode == 2

    def test_json_output_shape(self, tmp_path):
        yaml_path = self._write_yaml(tmp_path,
            "genesis_env:\n"
            "  GENESIS_ENABLE_PN90: '1'\n"
            "  GENESIS_ENABLE_P67: '1'\n")
        env_path = self._write_env(tmp_path,
            "GENESIS_ENABLE_P67=1\nGENESIS_PN95_EXTRA=1\n")
        result = self._run(
            str(yaml_path), "fake-container",
            "--from-env-file", str(env_path), "--json",
        )
        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert data["yaml_count"] == 2
        assert data["live_count"] == 2
        assert data["real_drift"] is True
        classifications = {f["classification"] for f in data["findings"]}
        assert "drift" in classifications
        assert "intentional_pn95" in classifications

    def test_pn95_intentional_silent_in_text_output(self, tmp_path):
        """PN95 extras must not be reported as drift."""
        yaml_path = self._write_yaml(tmp_path,
            "genesis_env:\n  GENESIS_ENABLE_P67: '1'\n")
        env_path = self._write_env(tmp_path,
            "GENESIS_ENABLE_P67=1\nGENESIS_PN95_TIER_BUDGET=8192\n")
        result = self._run(
            str(yaml_path), "fake-container",
            "--from-env-file", str(env_path),
        )
        assert result.returncode == 0, (
            f"PN95 prefix should not trigger drift, got rc={result.returncode}\n"
            f"stdout:\n{result.stdout}"
        )
        assert "INTENTIONAL" in result.stdout
        assert "No real drift detected" in result.stdout

    def test_help_works(self):
        result = self._run("--help")
        assert result.returncode == 0
        assert "audit_yaml_vs_runtime_drift" in result.stdout
        assert "--from-env-file" in result.stdout
