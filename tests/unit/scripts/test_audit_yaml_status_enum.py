# SPDX-License-Identifier: Apache-2.0
"""Tests for ``scripts/audit_yaml_status_enum.py``.

Status-enum invariant (club-3090 convention port — see
``sndr_private/planning/audits/CLUB3090_CROSS_REFERENCE_2026-05-29_RU.md``):
every builtin model YAML must declare ``# Status: <one-of-enum>`` in
its first 40 lines. For non-✅ statuses, a ``# Caveats:`` line ≥10
chars is also required.

Coverage:
    1. Pure ``_audit_one()`` against crafted YAML snippets covering each
       violation code + the happy path.
    2. Tracked-tree smoke confirms all 10 builtin model YAMLs pass strict
       mode after the 2026-05-29 club-3090 wave.
    3. JSON shape (machine-readable mode) regression check.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "audit_yaml_status_enum.py"


def _import_audit_module():
    spec = importlib.util.spec_from_file_location(
        "audit_yaml_status_enum", SCRIPT_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["audit_yaml_status_enum"] = mod
    assert spec.loader is not None  # nosec
    spec.loader.exec_module(mod)
    return mod


# ───────────────────────── pure-function coverage ──────────────────────


def test_happy_path_production_no_caveats(tmp_path: Path) -> None:
    mod = _import_audit_module()
    text = (
        "# SPDX-License-Identifier: Apache-2.0\n"
        "# Status: ✅ Production\n"
        "# Genesis V2 model definition — fixture model.\n"
        "schema_version: 2\n"
    )
    fake = tmp_path / "fixture.yaml"
    fake.write_text(text, encoding="utf-8")
    assert mod._audit_one(fake) == []


def test_missing_status_violation(tmp_path: Path) -> None:
    mod = _import_audit_module()
    text = (
        "# SPDX-License-Identifier: Apache-2.0\n"
        "# Genesis V2 model definition — header forgot Status.\n"
        "schema_version: 2\n"
    )
    fake = tmp_path / "fixture.yaml"
    fake.write_text(text, encoding="utf-8")
    vios = mod._audit_one(fake)
    assert len(vios) == 1
    assert vios[0].code == "missing_status"


def test_invalid_status_enum(tmp_path: Path) -> None:
    mod = _import_audit_module()
    text = (
        "# SPDX-License-Identifier: Apache-2.0\n"
        "# Status: ☢️ Radioactive\n"  # not in enum
        "schema_version: 2\n"
    )
    fake = tmp_path / "fixture.yaml"
    fake.write_text(text, encoding="utf-8")
    vios = mod._audit_one(fake)
    assert len(vios) == 1
    assert vios[0].code == "invalid_status"


def test_warning_status_missing_caveats(tmp_path: Path) -> None:
    mod = _import_audit_module()
    text = (
        "# SPDX-License-Identifier: Apache-2.0\n"
        "# Status: ⚠️ Production w/ caveats\n"
        "# Genesis V2 model definition — forgot Caveats.\n"
        "schema_version: 2\n"
    )
    fake = tmp_path / "fixture.yaml"
    fake.write_text(text, encoding="utf-8")
    vios = mod._audit_one(fake)
    assert any(v.code == "missing_caveats" for v in vios)


def test_warning_status_caveats_too_short(tmp_path: Path) -> None:
    mod = _import_audit_module()
    text = (
        "# SPDX-License-Identifier: Apache-2.0\n"
        "# Status: 🧪 Experimental\n"
        "# Caveats: TBD\n"  # 3 chars < 10
        "schema_version: 2\n"
    )
    fake = tmp_path / "fixture.yaml"
    fake.write_text(text, encoding="utf-8")
    vios = mod._audit_one(fake)
    assert any(v.code == "caveats_too_short" for v in vios)


def test_experimental_with_proper_caveats_passes(tmp_path: Path) -> None:
    mod = _import_audit_module()
    text = (
        "# SPDX-License-Identifier: Apache-2.0\n"
        "# Status: 🧪 Experimental\n"
        "# Caveats: pending server-validation on rig (bench n=25 + soak PASS).\n"
        "schema_version: 2\n"
    )
    fake = tmp_path / "fixture.yaml"
    fake.write_text(text, encoding="utf-8")
    assert mod._audit_one(fake) == []


def test_plain_variant_emoji_accepted(tmp_path: Path) -> None:
    """⚠ (U+26A0) and ⚠️ (with VS-16) should both pass — terminals render identically."""
    mod = _import_audit_module()
    text = (
        "# SPDX-License-Identifier: Apache-2.0\n"
        "# Status: ⚠ Production w/ caveats\n"   # plain, no VS-16
        "# Caveats: storage-constrained on 24 GB single-card path.\n"
        "schema_version: 2\n"
    )
    fake = tmp_path / "fixture.yaml"
    fake.write_text(text, encoding="utf-8")
    assert mod._audit_one(fake) == []


# ───────────────────────── tracked-tree smoke ─────────────────────────


def test_tracked_tree_passes_strict() -> None:
    """All 10 builtin model YAMLs satisfy the gate as of 2026-05-29
    club-3090 wave (commit b8f1f136)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--strict"],
        cwd=REPO_ROOT,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"audit_yaml_status_enum --strict failed:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_json_shape() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--json"],
        cwd=REPO_ROOT,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert {"total_yamls", "violations", "pass"} <= data.keys()
    assert isinstance(data["total_yamls"], int)
    assert isinstance(data["violations"], list)
    assert isinstance(data["pass"], bool)
    # current tracked state: PASS
    assert data["pass"] is True
    assert data["total_yamls"] >= 10
