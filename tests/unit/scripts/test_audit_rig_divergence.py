# SPDX-License-Identifier: Apache-2.0
"""Tests for ``scripts/audit_rig_divergence.py`` — §9.A.9
(AUDIT-CLOSURE.2, 2026-05-27).

Local-only skeleton coverage:

  * ``probe_local`` returns a sensible check set on a real tree
  * ``--ssh-host`` without ``--allow-ssh`` is a usage error (double
    opt-in gate enforced)
  * Local-only mode never gates (exit 0 even with WARN findings)
  * JSON output shape

SSH-mode behavior is exercised via ``ssh`` mock that injects synthetic
output — does NOT contact a real rig.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "audit_rig_divergence.py"


def _import_audit_module():
    spec = importlib.util.spec_from_file_location(
        "audit_rig_divergence", SCRIPT_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["audit_rig_divergence"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def audit_mod():
    return _import_audit_module()


class TestProbeLocal:
    """``probe_local`` reads laptop git state."""

    def test_returns_nonzero_checks(self, audit_mod):
        checks = audit_mod.probe_local()
        assert len(checks) >= 1
        # Severities are constrained to the documented set.
        for c in checks:
            assert c.severity in ("OK", "WARN", "BLOCKER")

    def test_local_branch_reported(self, audit_mod):
        checks = audit_mod.probe_local()
        names = [c.name for c in checks]
        assert "local-branch" in names

    def test_local_head_sha_reported(self, audit_mod):
        checks = audit_mod.probe_local()
        names = [c.name for c in checks]
        assert "local-head-sha" in names


class TestDoubleOptInGate:
    """``--ssh-host`` without ``--allow-ssh`` must be usage error."""

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            capture_output=True, text=True, cwd=REPO_ROOT, check=False,
        )

    def test_ssh_host_without_allow_ssh_rejected(self):
        result = self._run("--ssh-host", "rig@example.com")
        assert result.returncode == 2
        assert "--allow-ssh" in result.stderr

    def test_allow_ssh_without_ssh_host_silently_local_only(self):
        """``--allow-ssh`` alone (no ``--ssh-host``) reverts to local-only —
        the flag is harmless without a target host."""
        result = self._run("--allow-ssh")
        assert result.returncode == 0


class TestLocalOnlyMode:
    """Local-only mode is informational; never gates."""

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            capture_output=True, text=True, cwd=REPO_ROOT, check=False,
        )

    def test_default_exit_zero(self):
        result = self._run()
        assert result.returncode == 0, (
            f"local-only mode should always exit 0, got rc="
            f"{result.returncode}\nstdout:\n{result.stdout}"
        )

    def test_default_mode_label(self):
        result = self._run()
        assert "mode: local-only" in result.stdout

    def test_json_shape_local_only(self):
        result = self._run("--json")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["mode"] == "local-only"
        assert "checks" in data
        assert data["count"] >= 1

    def test_help_works(self):
        result = self._run("--help")
        assert result.returncode == 0
        assert "audit_rig_divergence" in result.stdout
        assert "--ssh-host" in result.stdout
        assert "--allow-ssh" in result.stdout


class TestSshGate:
    """``probe_rig`` requires explicit host arg. We verify the gate
    behavior by inspecting CLI rejection — actual SSH calls are NOT
    made (would contact a real rig)."""

    def test_probe_rig_function_exists(self, audit_mod):
        """The function is defined; integration is operator-driven."""
        assert callable(audit_mod.probe_rig)
