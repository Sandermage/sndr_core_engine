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

def test_resolve_dynamic_when_module_has_getattr_only(tmp_path):
    # __getattr__ means a hard symbol_missing would be a false POSITIVE, but a
    # flat "ok" would be a false NEGATIVE (FN-1: masks a removed class). The
    # honest answer is the soft "symbol_dynamic" — can't confirm nor refute.
    root = _tree(tmp_path, {"vllm/envs.py": "def __getattr__(name):\n    return None\n"})
    assert resolve_binding(root, "vllm.envs", "VLLM_ANY_FLAG") == "symbol_dynamic"


def test_resolve_ok_for_symbol_declared_under_type_checking(tmp_path):
    root = _tree(tmp_path, {
        "vllm/platforms/__init__.py":
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    current_platform: object\n",
    })
    assert resolve_binding(root, "vllm.platforms", "current_platform") == "ok"


def test_hard_module_missing_vs_soft_symbol_review(tmp_path):
    root = _tree(tmp_path, {"vllm/present.py": "class A:\n    pass\n"})
    # module the patch imports FROM is gone -> hard drift (always breaks apply)
    hard = check_module_bindings("def f():\n    from vllm.gone.mod import X\n", root)
    assert hard["status"] == "symbol_drift"
    # module present but the symbol isn't statically found -> soft review
    # (could be a real rename, a Genesis-created symbol, or a dynamic attr)
    soft = check_module_bindings("def f():\n    from vllm.present import Missing\n", root)
    assert soft["status"] == "binding_review"
    assert any("Missing" in d for d in soft["unresolved"])


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


# ── FN-1: __getattr__ must NOT mask a genuinely-removed symbol (false-negative) ──

def test_getattr_module_does_not_false_green_a_removed_symbol(tmp_path):
    # vllm/envs.py-style module: has __getattr__ but the specific symbol is NOT
    # statically defined. The OLD code returned "ok" (dynamic) — masking exactly
    # the 'upstream removed the class' case the tool exists to catch. Must be a
    # SOFT review, not a confident ok.
    root = _tree(tmp_path, {"vllm/platforms/__init__.py": "def __getattr__(n):\n    return None\n"})
    src = "def f():\n    from vllm.platforms import GoneClass\n"
    res = check_module_bindings(src, root)
    assert res["status"] == "binding_review"   # NOT "ok"
    assert any("GoneClass" in u for u in res["unresolved"])


def test_getattr_module_still_ok_for_statically_declared_symbol(tmp_path):
    # A symbol declared under TYPE_CHECKING resolves statically → stays ok even
    # though the module also has __getattr__ (envs.py real shape).
    root = _tree(tmp_path, {
        "vllm/envs.py":
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    VLLM_X: bool\ndef __getattr__(n):\n    return None\n",
    })
    res = check_module_bindings("def f():\n    from vllm.envs import VLLM_X\n", root)
    assert res["status"] == "ok"


# ── FP-6: AST coverage — tuple-unpack / star / deep nesting (false-positive) ──

def test_symbol_via_tuple_unpack_resolves(tmp_path):
    root = _tree(tmp_path, {"vllm/config.py": "A, B = 1, 2\n"})
    assert resolve_binding(root, "vllm.config", "B") == "ok"


def test_symbol_via_star_reexport_is_not_flagged_missing(tmp_path):
    # `from x import *` can re-export the symbol — must not hard-claim missing.
    root = _tree(tmp_path, {
        "vllm/pkg/__init__.py": "from vllm.pkg.impl import *\n",
        "vllm/pkg/impl.py": "class Thing:\n    pass\n",
    })
    # Thing may be re-exported via the star — resolver must not say symbol_missing
    assert resolve_binding(root, "vllm.pkg", "Thing") != "symbol_missing"
