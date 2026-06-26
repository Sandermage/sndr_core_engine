# SPDX-License-Identifier: Apache-2.0
"""Unit tests for G4_07 — FP8_BLOCK double-scale fix GEMM binding.

2026-06-13 repoint (dev491 pin bump, preflight RUNTIME_BINDING triage):
the vllm FP8 kernel-selection refactor REMOVED the high-level
``apply_fp8_block_linear`` wrapper this patch was originally written
against. The bare ``from ...fp8_utils import apply_fp8_block_linear``
import resolves on NEITHER the current PROD pin
(0.22.1rc1.dev259+g303916e93) NOR the candidate
(0.22.1rc1.dev491+g1033ffac2) — pin_preflight flagged it
BINDING_SYMBOL_MISSING.

The fix uses the PN351/PN32/P18B DUAL-ANCHOR convention: import the
fp8_utils MODULE (resolves on BOTH pins so the static preflight passes)
and resolve the GEMM symbol at runtime, probing the dev491 canonical
``w8a8_triton_block_scaled_mm`` first, then the dev259 legacy
``apply_fp8_block_linear`` fallback, failing LOUD if neither exists.

These tests pin the new contract:
  * dev491 anchor symbol resolves when present (and wins over legacy);
  * dev259 legacy anchor symbol resolves as fallback on a pre-refactor
    pin that still exposes the wrapper;
  * NEITHER symbol → RuntimeError (fail-loud), never a silent
    double-scaled forward;
  * the patch source no longer carries the dead bare import;
  * (optional) the dev491-anchor symbol is verifiably present in the
    pristine dev491 tree AND the dev259 tree when those scratch trees
    exist on disk.

All vllm modules are faked in ``sys.modules`` — no torch/CUDA needed for
the resolver unit tests.
"""
from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest

MODULE_PATH = (
    "sndr.engines.vllm.patches.model_compat.gemma4."
    "g4_07_gemma4_fp8_block_double_scale_fix"
)

# The two ephemeral pristine pin trees the pin-bump fix-loop extracts.
_DEV259_TREE = Path("/private/tmp/candidate_pin_current/vllm")
_DEV491_TREE = Path("/tmp/candidate_pin_new/vllm")
_FP8_UTILS_REL = (
    "model_executor/layers/quantization/utils/fp8_utils.py"
)
_DEV491_SYMBOL = "w8a8_triton_block_scaled_mm"
_DEV259_LEGACY_SYMBOL = "apply_fp8_block_linear"


# ─── Fixtures / fakes ─────────────────────────────────────────────────


@pytest.fixture
def g4_07():
    """Fresh module per test (module-level _APPLIED state)."""
    sys.modules.pop(MODULE_PATH, None)
    mod = importlib.import_module(MODULE_PATH)
    yield mod
    sys.modules.pop(MODULE_PATH, None)


def _clear_fake_vllm() -> None:
    for n in list(sys.modules):
        if n == "vllm" or n.startswith("vllm."):
            sys.modules.pop(n, None)


def _install_fake_fp8_utils(monkeypatch, **symbols) -> types.ModuleType:
    """Build a minimal fake ``vllm...fp8_utils`` module exposing ``symbols``.

    Parent packages are stubbed so ``importlib.import_module`` of the full
    dotted path succeeds. Pass NO symbols to simulate a pin where neither
    GEMM candidate exists.
    """
    _clear_fake_vllm()
    full = "vllm.model_executor.layers.quantization.utils.fp8_utils"
    parents = [
        "vllm",
        "vllm.model_executor",
        "vllm.model_executor.layers",
        "vllm.model_executor.layers.quantization",
        "vllm.model_executor.layers.quantization.utils",
    ]
    for p in parents:
        monkeypatch.setitem(sys.modules, p, types.ModuleType(p))
    mod = types.ModuleType(full)
    for k, v in symbols.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, full, mod)
    return mod


# ─── Source-level regression pin ──────────────────────────────────────


def test_source_has_no_dead_bare_import(g4_07):
    """The removed wrapper must not appear as a real ``import`` statement.

    pin_preflight statically AST-extracts ``from vllm...import NAME`` and
    flags BINDING_SYMBOL_MISSING. The legacy name may appear only inside
    the runtime candidate tuple / explanatory comments, never as an actual
    importable binding. We re-run the project's own AST extractor and
    assert no extracted (module, attr) binding names the dead symbol.
    """
    import sys as _sys

    # This test file lives at <repo>/tests/unit/integrations/gemma4/ →
    # repo root is parents[4]; pin_preflight lives under <repo>/tools.
    repo_root = Path(__file__).resolve().parents[4]
    tools_dir = repo_root / "tools"
    _sys.path.insert(0, str(tools_dir))
    try:
        import pin_preflight as pf
    finally:
        _sys.path.remove(str(tools_dir))

    source = Path(g4_07.__file__).read_text(encoding="utf-8")
    extracted_attrs = {
        b["attr"] for b in pf.extract_bindings(source) if b["attr"]
    }
    assert _DEV259_LEGACY_SYMBOL not in extracted_attrs, (
        "the dead apply_fp8_block_linear binding is still a real import "
        "statement (pin_preflight would flag BINDING_SYMBOL_MISSING)"
    )
    # The dev491 module-level binding (fp8_utils.per_token_group_quant_fp8)
    # IS expected — it resolves on both pins.
    assert "per_token_group_quant_fp8" in extracted_attrs


def test_candidate_order_is_dev491_first(g4_07):
    """Dual-anchor probe order: dev491 canonical first, dev259 legacy last."""
    cands = g4_07._FP8_BLOCK_GEMM_CANDIDATES
    assert cands[0] == _DEV491_SYMBOL
    assert cands[-1] == _DEV259_LEGACY_SYMBOL


# ─── Dual-anchor resolver behavior ────────────────────────────────────


def test_dev491_symbol_resolves_and_wins(g4_07, monkeypatch):
    """When BOTH symbols exist (the dev259+dev491 reality), dev491 wins."""
    _install_fake_fp8_utils(
        monkeypatch,
        w8a8_triton_block_scaled_mm=lambda *a, **k: "DEV491",
        apply_fp8_block_linear=lambda *a, **k: "DEV259",
    )
    name, fn = g4_07._resolve_fp8_block_gemm()
    assert name == _DEV491_SYMBOL
    assert fn() == "DEV491"


def test_dev259_legacy_symbol_resolves_as_fallback(g4_07, monkeypatch):
    """Pre-refactor pin exposing ONLY the legacy wrapper still binds."""
    _install_fake_fp8_utils(
        monkeypatch,
        apply_fp8_block_linear=lambda *a, **k: "DEV259",
    )
    name, fn = g4_07._resolve_fp8_block_gemm()
    assert name == _DEV259_LEGACY_SYMBOL
    assert fn() == "DEV259"


def test_neither_symbol_fails_loud(g4_07, monkeypatch):
    """No bindable GEMM symbol → RuntimeError, never a silent forward.

    G4_07 is a correctness guard: a missing GEMM symbol must abort, not
    fall through to an un-anchored (potentially double-scaled) path.
    """
    _install_fake_fp8_utils(monkeypatch)  # empty module — no candidates
    with pytest.raises(RuntimeError, match=r"\[Genesis G4_07\]"):
        g4_07._resolve_fp8_block_gemm()


def test_module_import_failure_fails_loud(g4_07, monkeypatch):
    """fp8_utils module entirely absent → RuntimeError (fail-loud)."""
    _clear_fake_vllm()
    # Ensure the real vllm install (if any) cannot satisfy the import.
    monkeypatch.setitem(
        sys.modules,
        "vllm.model_executor.layers.quantization.utils.fp8_utils",
        None,  # import_module raises ImportError for a None entry
    )
    with pytest.raises(RuntimeError, match=r"cannot import"):
        g4_07._resolve_fp8_block_gemm()


# ─── apply() registration entrypoint ──────────────────────────────────


def test_disabled_env_skips(g4_07, monkeypatch):
    monkeypatch.delenv(g4_07._ENV_ENABLE, raising=False)
    status, reason = g4_07.apply()
    assert status == "skipped"
    assert g4_07._ENV_ENABLE in reason


# ─── Pristine-tree anchor verification (opt-in; skips if trees absent) ─


def _symbol_present_in_tree(tree: Path, symbol: str) -> bool:
    f = tree / _FP8_UTILS_REL
    if not f.is_file():
        return False
    return f"def {symbol}" in f.read_text(encoding="utf-8")


@pytest.mark.skipif(
    not (_DEV491_TREE / _FP8_UTILS_REL).is_file(),
    reason="pristine dev491 tree not extracted on this host",
)
def test_dev491_anchor_present_in_pristine_dev491_tree():
    """dev491 anchor symbol must exist exactly once in the dev491 fp8_utils."""
    f = _DEV491_TREE / _FP8_UTILS_REL
    text = f.read_text(encoding="utf-8")
    assert text.count(f"def {_DEV491_SYMBOL}(") == 1
    # The dead legacy wrapper must NOT be re-anchored against on dev491.
    assert f"def {_DEV259_LEGACY_SYMBOL}(" not in text


@pytest.mark.skipif(
    not (_DEV259_TREE / _FP8_UTILS_REL).is_file(),
    reason="pristine dev259 tree not extracted on this host",
)
def test_dev491_anchor_also_present_in_dev259_tree():
    """The dev491 canonical symbol is also present on the current PROD pin,
    so the SAME re-anchored binding keeps working on dev259 (required: the
    PROD 35B stays on dev259 until dev491 is validated)."""
    assert _symbol_present_in_tree(_DEV259_TREE, _DEV491_SYMBOL)
