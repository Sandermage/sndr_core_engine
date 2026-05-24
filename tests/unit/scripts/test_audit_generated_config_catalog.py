# SPDX-License-Identifier: Apache-2.0
"""CONFIG-UX.5.1 — tests for `scripts/audit_generated_config_catalog.py`."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "audit_generated_config_catalog.py"


def _import_audit():
    spec = importlib.util.spec_from_file_location("audit_generated_config_catalog", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["audit_generated_config_catalog"] = mod
    spec.loader.exec_module(mod)
    return mod


def _run_cli(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
    )


# ─── Live corpus ────────────────────────────────────────────────────────────


class TestLiveCorpus:
    def test_default_mode_exits_zero(self):
        result = _run_cli()
        assert result.returncode == 0

    def test_strict_mode_exits_zero_on_clean(self):
        """Post .5.1 ship the generator is deterministic + redaction-clean,
        so --strict exits 0."""
        result = _run_cli("--strict")
        assert result.returncode == 0

    def test_no_findings_on_clean_corpus(self):
        mod = _import_audit()
        report = mod.run_audit()
        assert report.findings == [], (
            f"clean corpus expected; got findings: "
            + "\n".join(f"[{f.rule}] {f.message}" for f in report.findings)
        )


# ─── Redaction enforcement ─────────────────────────────────────────────────


class TestRedactionDetection:
    def test_audit_flags_synthetic_redaction_leak(self, monkeypatch):
        """Inject a synthetic `sndr_private/` string into the catalog
        rows and confirm the audit catches it."""
        mod = _import_audit()

        def fake_gen():
            rows = [{
                "row_type": "preset",
                "id": "fake-leak",
                "card_evidence_refs": [
                    {"path": "sndr_private/runs/leak.md", "type": "bench"},
                ],
            }]
            return mod._generate_and_serialise_for_drift.__wrapped__ if hasattr(mod._generate_and_serialise_for_drift, '__wrapped__') else None
        # Direct invocation of internal helper
        report = mod.Report()
        # Use _audit_redaction directly with a synthetic row
        rows = [{
            "id": "fake-leak",
            "card_evidence_refs": [{"path": "sndr_private/runs/leak.md"}],
        }]
        mod._audit_redaction(rows, report)
        assert report.has_errors()
        assert any(
            f.rule == "redaction_leak" and "sndr_private/" in f.message
            for f in report.findings
        )

    @pytest.mark.parametrize("banned", ["/Users/sander/", "/home/user/", "/tmp/data/", "/var/log/"])
    def test_audit_flags_local_path_leak(self, banned):
        mod = _import_audit()
        report = mod.Report()
        rows = [{"id": "fake", "path_field": f"{banned}file.json"}]
        mod._audit_redaction(rows, report)
        assert report.has_errors(), f"audit should flag {banned!r}"

    def test_audit_passes_public_paths(self):
        mod = _import_audit()
        report = mod.Report()
        rows = [{
            "id": "fake",
            "path_field": "tests/integration/baselines/27b_v11_wave9.json",
            "external_ref": "external://docs.example/x",
        }]
        mod._audit_redaction(rows, report)
        assert not report.has_errors()


# ─── JSON output ────────────────────────────────────────────────────────────


class TestJSONOutput:
    def test_json_shape(self):
        result = _run_cli("--json")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        for key in ("row_count", "counts", "findings", "has_errors",
                    "has_warnings", "strict"):
            assert key in data

    def test_json_finding_shape(self):
        result = _run_cli("--json")
        data = json.loads(result.stdout)
        for f in data["findings"]:
            assert set(f.keys()) >= {"severity", "rule", "message"}
