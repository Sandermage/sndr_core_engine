# SPDX-License-Identifier: Apache-2.0
"""Tests for `scripts/audit_lifecycle_docstring_sync.py`.

Contract:

  1. `_extract_module_docstring` returns the top-of-file module
     docstring.
  2. `_extract_source` reads the raw file contents.
  3. `_has_retire_marker` matches RETIRED / TOMBSTONED / DEPRECATED /
     DEAD-CODE case-sensitively.
  4. `_patch_id_from_filename` normalizes lower-case prefixes to upper
     (`pn132_*.py` → `PN132`).
  5. `inspect_file` flags drift in BOTH directions:
        a. docstring marker + registry lifecycle != retired
        b. registry lifecycle == retired + docstring silent
  6. Coordinator filenames (`_per_patch_dispatch.py`, `__init__.py`,
     etc.) are exempt from both directions.
  7. Files under `_retired/` are filtered out by `iter_integration_files`.
  8. `--strict` exit code is 0 when no drift, 1 when drift exists.
  9. Repository's current state: 0 drift entries (caller-visible
     contract — adding a new patch with mismatched docstring + registry
     lifecycle must break the audit).
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "audit_lifecycle_docstring_sync.py"


def _import_script():
    name = "_audit_lifecycle_docstring_sync_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ────────────────────────────────────────────────────────────────────
# Pure helpers
# ────────────────────────────────────────────────────────────────────


def test_has_retire_marker_finds_uppercase_tokens():
    mod = _import_script()
    assert mod._has_retire_marker("This is RETIRED 2026-05-29.")
    assert mod._has_retire_marker("TOMBSTONED — see registry.")
    assert mod._has_retire_marker("DEPRECATED for upstream merge.")
    assert mod._has_retire_marker("DEAD-CODE: do not use.")


def test_has_retire_marker_is_case_sensitive_against_prose():
    mod = _import_script()
    # English word "retired" (lowercase) in prose should NOT match.
    assert not mod._has_retire_marker(
        "The retired kernel is no longer compiled."
    )
    # Mixed case "Retired" also doesn't match (only ALL-CAPS marker).
    assert not mod._has_retire_marker("Retired by upstream.")


def test_has_retire_marker_empty():
    mod = _import_script()
    assert not mod._has_retire_marker("")


def test_extract_module_docstring_finds_first_block():
    mod = _import_script()
    src = '"""Top-level docstring.\n\nSecond paragraph.\n"""\n\nimport os\n'
    ds = mod._extract_module_docstring(src)
    assert "Top-level docstring." in ds
    assert "Second paragraph." in ds


def test_extract_module_docstring_returns_empty_on_syntax_error():
    mod = _import_script()
    assert mod._extract_module_docstring("def broken(:") == ""


def test_extract_module_docstring_returns_empty_when_absent():
    mod = _import_script()
    assert mod._extract_module_docstring("import os\n") == ""


def test_patch_id_from_filename_normalizes_pn():
    mod = _import_script()
    p = Path("/tmp/pn132_triton_fix.py")
    assert mod._patch_id_from_filename(p) == "PN132"


def test_patch_id_from_filename_normalizes_p_only():
    mod = _import_script()
    p = Path("/tmp/p67_multi_query.py")
    assert mod._patch_id_from_filename(p) == "P67"


def test_patch_id_from_filename_unmatched_returns_empty():
    mod = _import_script()
    p = Path("/tmp/random_helper.py")
    assert mod._patch_id_from_filename(p) == ""


# ────────────────────────────────────────────────────────────────────
# inspect_file behavior with mocked registry
# ────────────────────────────────────────────────────────────────────


def test_inspect_file_coordinator_files_are_exempt(monkeypatch, tmp_path):
    mod = _import_script()
    for name in ("__init__.py", "_per_patch_dispatch.py"):
        path = tmp_path / name
        path.write_text(
            '"""RETIRED — should be ignored because coordinator name."""\n'
        )
        result = mod.inspect_file(path)
        assert result.patch_id == "<coordinator>"
        assert not result.drift


def test_inspect_file_flags_docstring_marker_but_registry_active(
    monkeypatch, tmp_path,
):
    mod = _import_script()
    monkeypatch.setattr(
        mod, "_registry_lifecycle",
        lambda pid: "experimental" if pid == "PN999" else "?missing",
    )
    f = tmp_path / "pn999_demo.py"
    f.write_text(
        '"""PN999 — demo patch.\n\nRETIRED 2026-05-31 by upstream merge.\n"""\n'
    )
    result = mod.inspect_file(f)
    assert result.patch_id == "PN999"
    assert result.has_retire_marker is True
    assert result.registry_lifecycle == "experimental"
    assert len(result.drift) == 1
    assert "marks RETIRED" in result.drift[0]


def test_inspect_file_flags_registry_retired_but_docstring_silent(
    monkeypatch, tmp_path,
):
    mod = _import_script()
    monkeypatch.setattr(
        mod, "_registry_lifecycle",
        lambda pid: "retired" if pid == "PN998" else "?missing",
    )
    f = tmp_path / "pn998_demo.py"
    f.write_text('"""PN998 — still says it is active."""\n')
    result = mod.inspect_file(f)
    assert result.patch_id == "PN998"
    assert result.has_retire_marker is False
    assert result.registry_lifecycle == "retired"
    assert len(result.drift) == 1
    assert "does not mention RETIRED" in result.drift[0]


def test_inspect_file_clean_when_both_in_sync(monkeypatch, tmp_path):
    mod = _import_script()
    monkeypatch.setattr(
        mod, "_registry_lifecycle",
        lambda pid: "retired" if pid == "PN997" else "?missing",
    )
    f = tmp_path / "pn997_demo.py"
    f.write_text(
        '"""PN997 — demo.\n\nRETIRED 2026-05-31 — see registry.\n"""\n'
    )
    result = mod.inspect_file(f)
    assert result.patch_id == "PN997"
    assert result.has_retire_marker is True
    assert result.registry_lifecycle == "retired"
    assert not result.drift


def test_inspect_file_clean_when_active_and_silent(monkeypatch, tmp_path):
    mod = _import_script()
    monkeypatch.setattr(
        mod, "_registry_lifecycle",
        lambda pid: "stable" if pid == "PN996" else "?missing",
    )
    f = tmp_path / "pn996_demo.py"
    f.write_text('"""PN996 — active stable patch."""\n')
    result = mod.inspect_file(f)
    assert result.patch_id == "PN996"
    assert result.has_retire_marker is False
    assert result.registry_lifecycle == "stable"
    assert not result.drift


# ────────────────────────────────────────────────────────────────────
# iter_integration_files filtering
# ────────────────────────────────────────────────────────────────────


def test_iter_integration_files_excludes_retired_subtree():
    mod = _import_script()
    paths = mod.iter_integration_files()
    assert all("_retired" not in p.parts for p in paths)


def test_iter_integration_files_excludes_pycache():
    mod = _import_script()
    paths = mod.iter_integration_files()
    assert all("__pycache__" not in p.parts for p in paths)


def test_iter_integration_files_includes_active_patches():
    mod = _import_script()
    paths = mod.iter_integration_files()
    # PN132 lives in compile_safety/ and is RETIRED — but still on disk
    # outside _retired/, so it should be scanned.
    assert any("pn132" in p.name.lower() for p in paths)


# ────────────────────────────────────────────────────────────────────
# End-to-end: script invocation against the real repo
# ────────────────────────────────────────────────────────────────────


def test_audit_strict_passes_on_current_repo():
    """The repo at the time of this commit must pass `--strict`.

    If a future change introduces drift, this test fires and CI rejects
    the PR. Add a `IGNORE_PATCH_IDS` entry to the audit script with an
    operator rationale, or fix the underlying drift.
    """
    res = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--strict"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert res.returncode == 0, (
        f"audit-lifecycle-docstring-sync failed:\n"
        f"stdout:\n{res.stdout}\nstderr:\n{res.stderr}"
    )
    assert "drift entries: 0" in res.stdout


def test_audit_non_strict_always_exits_zero(monkeypatch, tmp_path):
    """Without --strict, the audit reports but never blocks (exit 0)."""
    res = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert res.returncode == 0


def test_audit_strict_exits_1_when_drift_introduced(tmp_path, monkeypatch):
    """Verify the exit-code contract by inspecting the helper directly."""
    mod = _import_script()
    monkeypatch.setattr(
        mod, "_registry_lifecycle", lambda pid: "experimental",
    )
    drift_file = tmp_path / "pn999_drift_demo.py"
    drift_file.write_text('"""PN999.\n\nRETIRED 2026-06-01 fake.\n"""\n')
    monkeypatch.setattr(
        mod, "iter_integration_files", lambda: [drift_file],
    )
    results = mod.audit()
    assert results
    assert any(r.drift for r in results)
