# SPDX-License-Identifier: Apache-2.0
"""T4 (UNIFIED_CONFIG plan 2026-05-09) — release pipeline gate tests.

Verifies the .github/workflows/release.yml file is well-formed and
includes the SBOM generation step + the strict-tests step. This is a
static-shape check — we don't execute the workflow itself in CI here.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _release_yaml() -> str:
    p = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "release.yml"
    assert p.exists(), f"release workflow not found at {p}"
    return p.read_text()


def test_release_workflow_exists():
    body = _release_yaml()
    assert "name: Genesis release" in body


def test_release_workflow_triggers_on_version_tags():
    body = _release_yaml()
    assert "tags:" in body
    assert "'v*'" in body or '"v*"' in body or "v*" in body


def test_release_workflow_runs_sbom_step():
    body = _release_yaml()
    assert "scripts/generate_sbom.py" in body
    assert "--out sbom/genesis-sbom" in body


def test_release_workflow_runs_strict_tests():
    body = _release_yaml()
    assert "SNDR_ALLOW_LEGACY_LICENSE_KEYS" in body
    # Strict mode: legacy gate empty (or unset)
    assert 'SNDR_ALLOW_LEGACY_LICENSE_KEYS: ""' in body
    assert "pytest" in body


def test_release_workflow_uploads_artifacts():
    body = _release_yaml()
    assert "actions/upload-artifact" in body
    assert "softprops/action-gh-release" in body
    assert "dist/*" in body
    assert "sbom/*" in body


def test_release_workflow_validates_json():
    body = _release_yaml()
    # JSON validity check on SBOM files
    assert "json.load" in body or "Verify SBOM" in body


def test_release_workflow_can_be_parsed_as_yaml():
    """The file must parse as valid YAML (no indentation regressions)."""
    yaml = pytest.importorskip("yaml")
    p = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "release.yml"
    parsed = yaml.safe_load(p.read_text())
    assert parsed["name"] == "Genesis release"
    assert "build_and_sbom" in parsed["jobs"]
    steps = parsed["jobs"]["build_and_sbom"]["steps"]
    step_names = [s.get("name", "") for s in steps]
    assert any("SBOM" in n for n in step_names), f"no SBOM step in {step_names}"
    assert any("Strict" in n or "strict" in n.lower() for n in step_names), \
        f"no strict-tests step in {step_names}"
