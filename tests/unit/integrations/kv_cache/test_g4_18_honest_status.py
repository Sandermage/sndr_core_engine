# SPDX-License-Identifier: Apache-2.0
"""Integrity lock for G4_18 — per-layer KV page-size override MUST NOT
report a false ``"applied"`` when its wrapper is inert.

Background (Class-3 silent-no-op)
---------------------------------
G4_18 wraps ``ModelConfig.get_num_kv_heads`` and only overrides the
KV-head count when it receives a ``layer_idx`` kwarg. On vLLM >= 0.22
(dev491) the upstream signature is ``get_num_kv_heads(self,
parallel_config)`` — there is NO ``layer_idx`` parameter and no caller
passes one, so the per-layer branch can never fire. The wrapper always
falls through to the original, yet ``apply()`` returned ``"applied"``.
The registry CAVEAT already documents this; these tests make the runtime
status itself honest.

Contract pinned here:
  * when the upstream signature lacks ``layer_idx``, ``apply()`` returns
    ``"skipped"`` (never ``"applied"``) with a reason naming the dropped
    kwarg;
  * when the upstream signature DOES expose ``layer_idx`` (older pin),
    ``apply()`` installs and returns ``"applied"`` — the override is
    live there, so the honest status is still ``"applied"``.

All vLLM modules are faked in ``sys.modules`` — no torch/CUDA required.
"""
from __future__ import annotations

import importlib
import sys
import types

import pytest

MODULE_PATH = "sndr.engines.vllm.patches.kv_cache.g4_18_per_layer_kv_page_size"
_ENV = "GENESIS_ENABLE_G4_18_GEMMA4_PER_LAYER_KV_PAGE_SIZE"


@pytest.fixture
def g4_18():
    sys.modules.pop(MODULE_PATH, None)
    mod = importlib.import_module(MODULE_PATH)
    yield mod
    sys.modules.pop(MODULE_PATH, None)


def _clear_fake_vllm() -> None:
    for n in list(sys.modules):
        if n == "vllm" or n.startswith("vllm."):
            sys.modules.pop(n, None)


def _install_fake_modelconfig(monkeypatch, *, with_layer_idx: bool) -> type:
    """Fake ``vllm.config.ModelConfig`` whose ``get_num_kv_heads``
    signature does/doesn't expose ``layer_idx``."""
    _clear_fake_vllm()
    pkg_vllm = types.ModuleType("vllm")
    mod_config = types.ModuleType("vllm.config")

    if with_layer_idx:
        class ModelConfig:
            def get_num_kv_heads(self, parallel_config=None, layer_idx=None):
                return 2
    else:
        class ModelConfig:
            def get_num_kv_heads(self, parallel_config=None):
                return 2

    mod_config.ModelConfig = ModelConfig
    pkg_vllm.config = mod_config
    monkeypatch.setitem(sys.modules, "vllm", pkg_vllm)
    monkeypatch.setitem(sys.modules, "vllm.config", mod_config)
    return ModelConfig


# ─────────────────────────────────────────────────────────────────────


def test_apply_skips_when_env_disabled(g4_18, monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)
    status, reason = g4_18.apply()
    assert status == "skipped"
    assert "disabled" in reason.lower()


def test_apply_skips_when_upstream_dropped_layer_idx(g4_18, monkeypatch):
    """The integrity lock: on a pin whose get_num_kv_heads has no
    layer_idx, the override is inert — apply() must NOT report 'applied'."""
    monkeypatch.setenv(_ENV, "1")
    _install_fake_modelconfig(monkeypatch, with_layer_idx=False)

    status, reason = g4_18.apply()
    assert status != "applied", (
        "G4_18 must not claim 'applied' when the layer_idx kwarg is gone"
    )
    assert status == "skipped"
    assert "layer_idx" in reason.lower()


def test_inert_wrapper_not_installed_on_dropped_kwarg(g4_18, monkeypatch):
    """When inert, the original method must be left untouched (no wrap)."""
    monkeypatch.setenv(_ENV, "1")
    cls = _install_fake_modelconfig(monkeypatch, with_layer_idx=False)
    before = cls.get_num_kv_heads
    g4_18.apply()
    assert cls.get_num_kv_heads is before, (
        "inert override must not monkeypatch get_num_kv_heads"
    )
    assert not getattr(cls.get_num_kv_heads, "_genesis_g4_18_wrapped", False)


def test_apply_installs_when_layer_idx_present(g4_18, monkeypatch):
    """On a pin that still exposes layer_idx, the override is live —
    'applied' is the honest status there."""
    monkeypatch.setenv(_ENV, "1")
    cls = _install_fake_modelconfig(monkeypatch, with_layer_idx=True)
    status, reason = g4_18.apply()
    assert status == "applied"
    assert getattr(cls.get_num_kv_heads, "_genesis_g4_18_wrapped", False)
