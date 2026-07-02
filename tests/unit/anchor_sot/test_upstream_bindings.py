# SPDX-License-Identifier: Apache-2.0
"""TDD for the upstream-binding drift resolver.

Half the registry (157/305 patches at dev672) is class-rebind / monkeypatch
wiring with no text anchor — the drift checker used to punt on all of them
(`needs_fixture`, "covered by runtime self-test"), so a symbol they bind could
vanish upstream and only surface at boot. But 71 of those modules IMPORT the
upstream symbols they rebind (e.g. `from vllm.model_executor.models import
gemma4`), often inside a function — statically extractable and resolvable
against the pristine tree. This module turns that into a real static check.
"""
from __future__ import annotations

from pathlib import Path

from sndr.engines.vllm.upstream_bindings import (
    check_module_bindings,
    extract_vllm_imports,
    resolve_binding,
)


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    """Materialize a fake pristine tree: {"vllm/a/b.py": "class C: ..."}."""
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tmp_path


# ── extract_vllm_imports ─────────────────────────────────────────────────

def test_extract_finds_function_nested_from_import():
    src = '''
def apply():
    from vllm.model_executor.models import gemma4 as g4
    return g4
'''
    binds = extract_vllm_imports(src)
    assert ("vllm.model_executor.models", "gemma4") in [(b.module, b.symbol) for b in binds]


def test_extract_finds_top_level_and_symbol_imports():
    src = "from vllm.v1.request import Request\nimport vllm.config\n"
    pairs = {(b.module, b.symbol) for b in extract_vllm_imports(src)}
    assert ("vllm.v1.request", "Request") in pairs
    assert ("vllm.config", None) in pairs


def test_extract_ignores_non_vllm_and_sndr_imports():
    src = "import os\nfrom sndr.kernel import TextPatcher\nfrom vllm import envs\n"
    mods = {b.module for b in extract_vllm_imports(src)}
    assert "os" not in mods and "sndr.kernel" not in mods
    assert "vllm" in mods  # `from vllm import envs` → module vllm, symbol envs


def test_extract_dedupes_and_survives_syntax_error():
    assert extract_vllm_imports("def (((broken") == []


# ── resolve_binding (against a fake tree) ────────────────────────────────

def test_resolve_ok_when_module_and_symbol_present(tmp_path):
    root = _tree(tmp_path, {"vllm/model_executor/models/gemma4.py": "class Gemma4Model:\n    pass\n"})
    assert resolve_binding(root, "vllm.model_executor.models.gemma4", "Gemma4Model") == "ok"


def test_resolve_module_missing(tmp_path):
    root = _tree(tmp_path, {"vllm/config.py": "x = 1\n"})
    assert resolve_binding(root, "vllm.model_executor.models.gemma4", "Gemma4Model") == "module_missing"


def test_resolve_symbol_missing_when_file_present(tmp_path):
    root = _tree(tmp_path, {"vllm/model_executor/models/gemma4.py": "class SomethingElse:\n    pass\n"})
    assert resolve_binding(root, "vllm.model_executor.models.gemma4", "Gemma4Model") == "symbol_missing"


def test_resolve_symbol_none_only_checks_module(tmp_path):
    root = _tree(tmp_path, {"vllm/config.py": "y = 2\n"})
    assert resolve_binding(root, "vllm.config", None) == "ok"


def test_resolve_package_init(tmp_path):
    root = _tree(tmp_path, {"vllm/model_executor/models/__init__.py": "gemma4 = None\n"})
    # importing the subpackage `models` and symbol `gemma4` defined in __init__
    assert resolve_binding(root, "vllm.model_executor.models", "gemma4") == "ok"


# ── check_module_bindings aggregate ──────────────────────────────────────

def test_check_flags_symbol_drift_when_any_binding_unresolved(tmp_path):
    root = _tree(tmp_path, {
        "vllm/v1/request.py": "class Request:\n    pass\n",
        "vllm/model_executor/models/gemma4.py": "class Gemma4Model:\n    pass\n",
    })
    src = (
        "def a():\n"
        "    from vllm.v1.request import Request\n"          # ok
        "def b():\n"
        "    from vllm.model_executor.models.gemma4 import GoneClass\n"  # drift
    )
    res = check_module_bindings(src, root)
    assert res["status"] == "symbol_drift"
    assert any("GoneClass" in d for d in res["unresolved"])


def test_check_ok_when_all_bindings_resolve(tmp_path):
    root = _tree(tmp_path, {"vllm/v1/request.py": "class Request:\n    pass\n"})
    src = "def a():\n    from vllm.v1.request import Request\n"
    res = check_module_bindings(src, root)
    assert res["status"] == "ok"
    assert res["checked"] >= 1


def test_check_needs_fixture_when_no_vllm_bindings(tmp_path):
    # A patch that binds nothing statically (fully reflective) is honestly
    # uncheckable here — must NOT be a false ok.
    res = check_module_bindings("import os\nx = 1\n", tmp_path)
    assert res["status"] == "no_static_bindings"
