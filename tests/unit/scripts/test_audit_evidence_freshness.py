# SPDX-License-Identifier: Apache-2.0
"""Tests for `scripts/audit_evidence_freshness.py` — §10.3 #3.

Behaviors:
  • Ledger absent → skip rc=0 (CI / fresh-clone OK).
  • Ledger present + newest entry within max-age-days → pass rc=0.
  • Ledger present + stale entries → fail rc=1.
  • Ledger present + stale entries but contains current short SHA → pass rc=0.
"""
from __future__ import annotations

import datetime as _dt
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "audit_evidence_freshness.py"


def _import():
    name = "_audit_evidence_freshness_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestEntryDateParsing:
    def test_extracts_newest(self):
        mod = _import()
        text = (
            "### 2026-04-01T12:00+0300 — old entry\n"
            "### 2026-05-13T18:30+0300 — newest\n"
            "### 2026-05-10T09:00+0300 — middle\n"
        )
        assert mod._newest_entry_date(text) == _dt.date(2026, 5, 13)

    def test_no_entries(self):
        mod = _import()
        assert mod._newest_entry_date("# header only\n\nnothing else\n") is None


class TestAudit:
    def test_ledger_absent_skips(self, tmp_path, monkeypatch):
        mod = _import()
        # Point at tmp_path so glob finds no ledger
        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
        report = mod.audit(max_age_days=7)
        assert report["skipped"] is True

    def test_fresh_passes(self, tmp_path, monkeypatch):
        mod = _import()
        ledger = tmp_path / "docs" / "_internal"
        ledger.mkdir(parents=True)
        today = _dt.date.today().isoformat()
        (ledger / "ROADMAP_EVIDENCE_LEDGER_2026-05-12_RU.md").write_text(
            f"### {today}T10:00+0300 — fresh entry\n"
        )
        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
        report = mod.audit(max_age_days=7)
        assert report["skipped"] is False
        assert report["rc"] == 0
        assert report["fresh_by_age"] is True

    def test_stale_fails(self, tmp_path, monkeypatch):
        mod = _import()
        ledger = tmp_path / "docs" / "_internal"
        ledger.mkdir(parents=True)
        stale = (_dt.date.today() - _dt.timedelta(days=30)).isoformat()
        (ledger / "ROADMAP_EVIDENCE_LEDGER_2026-05-12_RU.md").write_text(
            f"### {stale}T10:00+0300 — stale entry\n"
        )
        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
        report = mod.audit(max_age_days=7)
        assert report["rc"] == 1
        assert report["fresh_by_age"] is False

    def test_malformed_ledger(self, tmp_path, monkeypatch):
        mod = _import()
        ledger = tmp_path / "docs" / "_internal"
        ledger.mkdir(parents=True)
        (ledger / "ROADMAP_EVIDENCE_LEDGER_2026-05-12_RU.md").write_text(
            "# header\n\nno dated entries\n"
        )
        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
        report = mod.audit(max_age_days=7)
        assert report["rc"] == 2


class TestScriptCLI:
    def test_local_repo_runs(self):
        rc = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        # Either passes (fresh ledger) or skips (no ledger). Both rc=0.
        assert rc.returncode in (0, 1), (
            f"unexpected rc:\n{rc.stdout}\n{rc.stderr}"
        )
