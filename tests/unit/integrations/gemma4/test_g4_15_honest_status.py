# SPDX-License-Identifier: Apache-2.0
"""Integrity lock for G4_15 — fused QKV-RMSNorm route MUST NOT report
a false ``"applied"``.

Background (Class-3 silent-no-op)
---------------------------------
The G4_15 integration wrapper imports ``g4_qkv_rmsnorm`` but never
calls it: both ``_g4_15_wrapped_forward`` and ``_g4_15_fused_forward``
unconditionally ``return original(...)``. The fused kernel does not
engage on any vLLM pin (the deep-cut anchor patch G4_15b is still a
roadmap item). Before this fix, ``_install_gemma4_attention_subclass``
returned ``True`` regardless, so ``apply()`` returned ``"applied"`` and
claimed "+5-10% TPS" — a false status the project's no-false-applied
discipline forbids.

These tests pin the honest contract:
  * the fusion does NOT actually wire (helper reports not-installed);
  * ``apply()`` returns ``"skipped"`` (never ``"applied"``) with a
    reason that names the not-wired kernel and disclaims any TPS delta;
  * the dead empty-tuple guard is gone;
  * the no-op forward wrappers genuinely delegate to the original.

All vLLM modules are faked in ``sys.modules`` — no torch/CUDA required.
"""
from __future__ import annotations

import importlib
import inspect
import sys
import types

import pytest

MODULE_PATH = (
    "sndr.engines.vllm.patches.model_compat.gemma4."
    "g4_15_gemma4_fused_rmsnorm_route"
)
_ENV = "GENESIS_ENABLE_G4_15_GEMMA4_FUSED_RMSNORM"


@pytest.fixture
def g4_15():
    """Fresh module per test (module-level _APPLIED state)."""
    sys.modules.pop(MODULE_PATH, None)
    mod = importlib.import_module(MODULE_PATH)
    yield mod
    sys.modules.pop(MODULE_PATH, None)


def _clear_fake_vllm() -> None:
    for n in list(sys.modules):
        if n == "vllm" or n.startswith("vllm."):
            sys.modules.pop(n, None)


def _install_fake_gemma4(monkeypatch, *, with_norm_attrs: bool) -> None:
    """Build a minimal fake ``vllm.model_executor.models.gemma4`` exposing
    a ``Gemma4Attention`` class whose ``forward`` we can wrap."""
    _clear_fake_vllm()

    pkg_vllm = types.ModuleType("vllm")
    pkg_me = types.ModuleType("vllm.model_executor")
    pkg_models = types.ModuleType("vllm.model_executor.models")
    mod_gemma4 = types.ModuleType("vllm.model_executor.models.gemma4")

    class Gemma4Attention:
        def forward(self, hidden_states, *args, **kwargs):  # noqa: D401
            return ("ORIGINAL", hidden_states)

    if with_norm_attrs:
        # Class advertises q/k/v norm attrs (still no real fusion happens).
        Gemma4Attention.qkv_proj = object()
        Gemma4Attention.q_norm = object()
        Gemma4Attention.k_norm = object()
        Gemma4Attention.v_norm = object()
        Gemma4Attention.num_heads = 8
        Gemma4Attention.num_kv_heads = 2
        Gemma4Attention.head_dim = 128

    mod_gemma4.Gemma4Attention = Gemma4Attention
    pkg_models.gemma4 = mod_gemma4

    for name, mod in (
        ("vllm", pkg_vllm),
        ("vllm.model_executor", pkg_me),
        ("vllm.model_executor.models", pkg_models),
        ("vllm.model_executor.models.gemma4", mod_gemma4),
    ):
        monkeypatch.setitem(sys.modules, name, mod)


def _install_fake_triton_kernel(monkeypatch, g4_15) -> None:
    """Stub the fused-kernel module so the apply() import-guards pass and
    flow can reach the install path (where the false-applied bug lived)."""
    kmod = types.ModuleType(
        "sndr.engines.vllm.patches.model_compat.gemma4.kernels."
        "g4_fused_rmsnorm_triton"
    )
    kmod._TRITON_AVAILABLE = True

    def _g4_qkv_rmsnorm(*args, **kwargs):  # pragma: no cover - never called
        raise AssertionError("kernel must not be invoked on a no-op pin")

    kmod.g4_qkv_rmsnorm = _g4_qkv_rmsnorm
    monkeypatch.setitem(
        sys.modules,
        "sndr.engines.vllm.patches.model_compat.gemma4.kernels."
        "g4_fused_rmsnorm_triton",
        kmod,
    )


# ─────────────────────────────────────────────────────────────────────


def test_apply_skips_when_env_disabled(g4_15, monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)
    status, reason = g4_15.apply()
    assert status == "skipped"
    assert "disabled" in reason.lower()


def test_install_subclass_reports_not_wired(g4_15, monkeypatch):
    """The fusion does not actually engage — the install helper must
    report that (return False), not a false True."""
    _install_fake_gemma4(monkeypatch, with_norm_attrs=True)
    _install_fake_triton_kernel(monkeypatch, g4_15)
    from vllm.model_executor.models import gemma4 as g4mod

    ok = g4_15._install_gemma4_attention_subclass(g4mod.Gemma4Attention)
    assert ok is False, (
        "fused kernel is never called; install helper must NOT claim success"
    )


def test_apply_never_reports_applied_when_kernel_not_wired(g4_15, monkeypatch):
    """The integrity lock: with env on + triton present + gemma4 present,
    apply() still must NOT return 'applied' (the kernel is not wired)."""
    monkeypatch.setenv(_ENV, "1")
    _install_fake_gemma4(monkeypatch, with_norm_attrs=True)
    _install_fake_triton_kernel(monkeypatch, g4_15)

    status, reason = g4_15.apply()
    assert status != "applied", (
        "G4_15 must not claim 'applied' while the fused kernel never fires"
    )
    assert status == "skipped"
    low = reason.lower()
    assert "not wired" in low or "no-op" in low
    # Must NOT promise a TPS win it does not deliver. The honest disclaimer
    # ("no TPS delta") is fine; a positive promise like "+5-10% TPS" is not.
    assert "+5-10" not in reason
    assert "expected +" not in low


def test_apply_reason_text_carries_no_tps_promise(g4_15, monkeypatch):
    monkeypatch.setenv(_ENV, "1")
    _install_fake_gemma4(monkeypatch, with_norm_attrs=False)
    _install_fake_triton_kernel(monkeypatch, g4_15)
    status, reason = g4_15.apply()
    assert status == "skipped"
    assert "%" not in reason or "tps" not in reason.lower()


def test_dead_empty_tuple_guard_removed():
    """The dead ``if not all(... for attr in ()):`` guard over an empty
    tuple must be gone (it was always-False, pure dead code)."""
    src = inspect.getsource(importlib.import_module(MODULE_PATH))
    assert "for attr in ()" not in src


def test_wrapped_forward_delegates_to_original(g4_15, monkeypatch):
    """The no-op wrapper genuinely forwards to the original (it does not
    silently drop the call)."""
    _install_fake_gemma4(monkeypatch, with_norm_attrs=True)
    _install_fake_triton_kernel(monkeypatch, g4_15)
    from vllm.model_executor.models import gemma4 as g4mod

    original = g4mod.Gemma4Attention.forward
    wrapper = g4_15._make_attn_forward_wrapper(original)
    inst = g4mod.Gemma4Attention()
    assert wrapper(inst, "HS") == ("ORIGINAL", "HS")
    assert getattr(wrapper, "_genesis_g4_15_wrapped", False) is True
