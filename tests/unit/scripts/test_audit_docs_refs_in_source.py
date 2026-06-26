# SPDX-License-Identifier: Apache-2.0
"""Tests for ``scripts/audit_docs_refs_in_source.py`` — Phase 10.5
D-extension (2026-06-01) source-code docs/ reference integrity gate."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "audit_docs_refs_in_source.py"


def _import_script():
    name = "_audit_docs_refs_in_source_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ─── Regex boundary check ───────────────────────────────────────────────────


class TestDocRefRegex:
    def test_matches_plain_docs_md_ref(self):
        mod = _import_script()
        matches = mod._DOC_REF_RE.findall("See docs/PATCHES.md for details.")
        assert matches == ["docs/PATCHES.md"]

    def test_matches_nested_path(self):
        mod = _import_script()
        text = "Per docs/reference/V756_INVESTIGATION_20260427.md the issue is..."
        matches = mod._DOC_REF_RE.findall(text)
        assert matches == ["docs/reference/V756_INVESTIGATION_20260427.md"]

    def test_internal_docs_skipped_by_regex_already(self):
        # `docs/_internal/...` is automatically skipped by the regex —
        # the `[A-Za-z]` class after `docs/` requires a letter, so the
        # leading underscore in `_internal` filters it out at the regex
        # layer. The audit()-level `startswith("docs/_internal/")` check
        # is therefore defensive belt-and-braces (regex change wouldn't
        # accidentally start letting them through).
        mod = _import_script()
        text = "See docs/_internal/AUDIT_PLAN.md for the private plan."
        matches = mod._DOC_REF_RE.findall(text)
        assert matches == [], (
            f"Internal docs path should be filtered at the regex layer, "
            f"got {matches!r}"
        )

    def test_does_not_match_internal_docs_in_compound_path(self):
        # `Genesis_internal_docs/FOO.md` should NOT match as `docs/FOO.md`
        # because the regex requires a token boundary before `docs/`.
        mod = _import_script()
        text = "See Genesis_internal_docs/BRAINSTORM.md for the design notes."
        matches = mod._DOC_REF_RE.findall(text)
        assert matches == [], (
            f"Compound path `Genesis_internal_docs/...` must NOT match, "
            f"got: {matches}"
        )

    def test_matches_after_open_paren(self):
        mod = _import_script()
        text = 'references=["docs/COOKBOOK.md#ngram-vs-mtp"],'
        matches = mod._DOC_REF_RE.findall(text)
        assert matches == ["docs/COOKBOOK.md"]


# ─── External-repo marker check ────────────────────────────────────────────


class TestExternalRepoMarker:
    def test_noonghunna_org_prefix(self):
        mod = _import_script()
        assert mod._is_external_repo_ref(
            "docs/CONTAINER_RUNTIMES.md",
            "Per noonghunna/club-3090 docs/CONTAINER_RUNTIMES.md the recommended...",
        ) is True

    def test_noonghunna_prose_form_no_slash(self):
        mod = _import_script()
        # Same marker matches even when the operator drops the slash:
        # "noonghunna club-3090 docs/..." (prose form).
        assert mod._is_external_repo_ref(
            "docs/CONTAINER_RUNTIMES.md",
            "Community feedback (noonghunna club-3090 docs/CONTAINER_RUNTIMES.md):",
        ) is True

    def test_own_doc_not_external(self):
        mod = _import_script()
        # A bare ref with no external-repo marker IS our docs/ tree.
        assert mod._is_external_repo_ref(
            "docs/MISSING.md",
            "Operator pointer: see docs/MISSING.md for the missing recipe.",
        ) is False


# ─── Live tree — regression anchor ─────────────────────────────────────────


class TestLiveCorpus:
    def test_no_broken_refs_on_committed_tree(self):
        mod = _import_script()
        report = mod.audit()
        assert report["broken"] == [], (
            "Found broken docs/ refs in vllm/sndr_core (refs to .md files "
            "not in git ls-files AND not in the documented aspirational "
            "allow-list):\n"
            + "\n".join(
                f"  {r['path']}:{r['line']}: {r['ref']}"
                for r in report["broken"]
            )
        )

    def test_cli_default_exits_zero(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=15,
        )
        # Default mode is warn-only on aspirational; exits 0 unless
        # a brand-new broken ref appears.
        assert result.returncode == 0, result.stdout + result.stderr

    def test_cli_strict_surfaces_aspirational(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--strict"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=15,
        )
        # The aspirational list is non-empty as of Phase 10.5; --strict
        # promotes those warnings to errors.
        assert result.returncode == 1, result.stdout + result.stderr

    def test_cli_json_shape(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--json"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        for key in ("broken", "aspirational", "external", "counts", "passed"):
            assert key in payload
        assert payload["counts"]["broken"] == 0
        assert payload["passed"] is True


# ─── Synthetic broken ref ──────────────────────────────────────────────────


class TestSyntheticBroken:
    def test_synthetic_broken_ref_surfaces(self, tmp_path, monkeypatch):
        mod = _import_script()
        fake = tmp_path / "vllm_sndr_core" / "fake_module.py"
        fake.parent.mkdir(parents=True)
        fake.write_text(
            '"""See docs/TOTALLY_FAKE_FILE_XYZ_2026.md for context."""\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(mod, "SCAN_ROOT", tmp_path / "vllm_sndr_core")
        # tracked tree doesn't contain the synthetic ref.
        report = mod.audit()
        broken_refs = {r["ref"] for r in report["broken"]}
        assert "docs/TOTALLY_FAKE_FILE_XYZ_2026.md" in broken_refs, (
            f"Synthetic broken ref didn't fire; report: {report!r}"
        )
