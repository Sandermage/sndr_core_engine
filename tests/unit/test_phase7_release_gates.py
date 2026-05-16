# SPDX-License-Identifier: Apache-2.0
"""Phase 7 acceptance — release gates + docs deliverables.

Contract:

  1. `make audit-configs` (audit_configs.py) — every V2 preset alias
     composes cleanly.
  2. `make audit-artifacts` (audit_artifacts.py) — artefact storage
     policy passes (evidence ledger present, rollback playbook present,
     bench results not tracked).
  3. `make audit-public-docs` (audit_public_docs.py) — script runs and
     reports issues structurally (we do NOT assert zero violations here;
     pre-existing cleanup is a separate task).
  4. Docs deliverables present and structurally valid.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _import_script(name: str):
    """Load a `scripts/*.py` file as an isolated module."""
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_test_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─── audit_configs.py ─────────────────────────────────────────────────


class TestAuditConfigs:
    def test_all_11_aliases_compose(self):
        """Every committed V2 preset alias must compose cleanly."""
        mod = _import_script("audit_configs")
        aliases = mod._alias_ids()
        # Phase 3 shipped 11 aliases.
        assert len(aliases) == 11
        failures = []
        for alias in aliases:
            ok, summary = mod._verify_alias(alias)
            if not ok:
                failures.append((alias, summary))
        assert not failures, (
            f"audit-configs found {len(failures)} broken preset(s): {failures}"
        )

    def test_script_exit_code_zero_on_green_tree(self):
        """The whole script returns 0 when everything composes."""
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "audit_configs.py"),
             "--json"],
            cwd=REPO_ROOT,
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout
        payload = json.loads(result.stdout)
        assert payload["total"] == 11
        assert payload["failures"] == 0


# ─── audit_artifacts.py ───────────────────────────────────────────────


class TestAuditArtifacts:
    def test_evidence_ledger_present(self):
        mod = _import_script("audit_artifacts")
        issues = mod.check_evidence_ledger_present()
        assert issues == []

    def test_rollback_playbook_present(self):
        mod = _import_script("audit_artifacts")
        issues = mod.check_rollback_playbook_present()
        assert issues == []

    def test_patch_proof_layout_clean(self):
        """A-2: if evidence/patch_proof/ exists, it contains only *.json
        and _waivers/. Phase 7 ships no proof artefacts yet — the dir
        may not exist, which is fine."""
        mod = _import_script("audit_artifacts")
        issues = mod.check_patch_proof_layout()
        # Empty dir = pass; dir absent = pass; either way zero issues.
        assert issues == []

    def test_no_bench_results_in_git(self):
        """A-5: bench results live at ~/.sndr/bench-results/, never tracked."""
        mod = _import_script("audit_artifacts")
        # Use git ls-files via the script's helper.
        files = mod._git_tracked_files()
        issues = mod.check_no_bench_results_tracked(files)
        assert issues == []

    def test_script_passes_on_current_tree(self):
        """The default (non --public-release) invocation should be green."""
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "audit_artifacts.py"),
             "--json"],
            cwd=REPO_ROOT,
            capture_output=True, text=True,
        )
        payload = json.loads(result.stdout)
        # default mode has 4 checks active (A-3 skipped without --public-release)
        # and all 4 pass on a clean tree.
        assert payload["total_failures"] == 0, payload


# ─── audit_public_docs.py ─────────────────────────────────────────────


class TestAuditPublicDocs:
    """The gate IS the deliverable; we don't enforce zero pre-existing
    violations here. We assert that:
      • the script imports + runs without exception,
      • it scans public docs (under docs/ excluding _internal/upstream/reference),
      • each rule function returns a list (structural contract)."""

    def test_module_imports(self):
        mod = _import_script("audit_public_docs")
        for name in ("check_d1_no_internal_links", "check_d2_no_private_ips",
                     "check_d3_no_operator_paths",
                     "check_d4_no_server_container_names",
                     "check_d5_no_retired_verbs",
                     "check_d6_no_unresolved_todos"):
            assert hasattr(mod, name)
            assert callable(getattr(mod, name))

    def test_public_doc_classifier(self):
        mod = _import_script("audit_public_docs")
        # Internal doc → not public.
        assert mod._is_public_doc(
            Path("docs/_internal/X.md"),
        ) is False
        # Public doc → yes.
        assert mod._is_public_doc(Path("docs/PATCHES.md")) is True
        # Upstream archive → not public.
        assert mod._is_public_doc(Path("docs/upstream/SOMETHING.md")) is False

    def test_script_runs_without_crash(self):
        """Even with violations, the script must exit cleanly (rc=0 or 1)."""
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "audit_public_docs.py"),
             "--json"],
            cwd=REPO_ROOT,
            capture_output=True, text=True,
        )
        # rc=0 (clean) or rc=1 (violations); rc=2 = internal error (bad).
        assert result.returncode in (0, 1)
        payload = json.loads(result.stdout)
        assert "checks" in payload
        assert "total_failures" in payload
        assert "public_docs_scanned" in payload
        # Sanity: at least README.md + a few docs/ files exist on this repo.
        assert payload["public_docs_scanned"] >= 5


# ─── Docs deliverables ────────────────────────────────────────────────


class TestDocsDeliverables:
    """Phase 7 deliverable list (roadmap §5 Phase 7)."""

    @pytest.mark.parametrize("path", [
        "docs/CONFIG_SYSTEM_V2.md",
        "docs/COMMUNITY_PATCHES.md",
        "docs/INSTALL.md",
        "docs/ROLLBACK_PLAYBOOK.md",
    ])
    def test_doc_present(self, path):
        assert (REPO_ROOT / path).is_file(), f"missing Phase 7 doc: {path}"

    def test_config_system_v2_has_key_sections(self):
        text = (REPO_ROOT / "docs" / "CONFIG_SYSTEM_V2.md").read_text(
            encoding="utf-8",
        )
        # Key sections operators look up.
        for section in (
            "The four layers",
            "Discovery CLI",
            "Composition rules",
            "Layer ownership rules",
            "Adding a new preset",
            "Profile delta semantics",
            "Sizing override",
            "V1 ↔ V2 bridge",
        ):
            assert section in text, f"CONFIG_SYSTEM_V2.md missing section: {section}"

    def test_rollback_playbook_has_named_procedures(self):
        """Phase 2.3 contract — playbook has R-001..R-008 named procedures."""
        text = (REPO_ROOT / "docs" / "ROLLBACK_PLAYBOOK.md").read_text(
            encoding="utf-8",
        )
        # Spot-check half of the procedures.
        for rid in ("R-001", "R-003", "R-006", "R-008"):
            assert rid in text, f"ROLLBACK_PLAYBOOK.md missing {rid}"
        # Each procedure section has the four mandated headers.
        for header in ("Trigger:", "Revert command", "Smoke command",
                       "Evidence"):
            assert header in text, (
                f"ROLLBACK_PLAYBOOK.md missing required header: {header}"
            )

    def test_community_patches_doc_references_validator_rules(self):
        """COMMUNITY_PATCHES.md must list the 7 release-tier rules."""
        text = (REPO_ROOT / "docs" / "COMMUNITY_PATCHES.md").read_text(
            encoding="utf-8",
        )
        for rule in ("R-1", "R-2", "R-3", "R-4", "R-5", "R-6", "R-7"):
            assert rule in text, f"COMMUNITY_PATCHES.md missing rule {rule}"


# ─── Makefile targets ─────────────────────────────────────────────────


class TestMakefileTargets:
    """Every Phase 7 gate has a Makefile target so CI can invoke it."""

    @pytest.mark.parametrize("target", [
        "audit-configs",
        "audit-public-docs",
        "audit-artifacts",
        "audit-artifacts-release",
        "audit-community",
        "audit-security",
        "audit-security-release",
        "audit-dirty-state-dev",
        "audit-dirty-state-audit",
        "audit-dirty-state-release",
        "audit-docs-stale",
    ])
    def test_target_declared(self, target):
        mk = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        # Target appears as its own rule (start of a line + colon).
        assert f"\n{target}:" in mk, (
            f"Makefile missing rule for `{target}` — Phase 7 gate not wired"
        )
