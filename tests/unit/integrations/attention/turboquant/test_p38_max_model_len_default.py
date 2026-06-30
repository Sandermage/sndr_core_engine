# SPDX-License-Identifier: Apache-2.0
"""M1 regression: the TQ continuation dequant pool's default ceiling must track
the engine's real max_model_len, not a hardcoded 262144 (which left an
oversized allocate-once K/V buffer standing — ~512 MiB/rank — on any model run
below 262144). GENESIS_TQ_MAX_MODEL_LEN still overrides; 262144 is the
config-unavailable fallback only.
"""
from __future__ import annotations

import sys
import types

import sndr.engines.vllm.patches.attention.turboquant.p38_tq_continuation_memory as p38


def test_default_falls_back_to_262144_without_running_config(monkeypatch):
    # No vllm config importable here → historical fallback preserved.
    monkeypatch.delitem(sys.modules, "vllm.config", raising=False)
    assert p38._p38_default_max_model_len() == 262144


def test_default_uses_engine_max_model_len_when_config_present(monkeypatch):
    """Inject a fake vllm.config exposing get_current_vllm_config → the default
    becomes the engine's max_model_len (131072 here, not 262144)."""
    fake = types.ModuleType("vllm.config")

    class _MC:
        max_model_len = 131072

    class _Cfg:
        model_config = _MC()

    fake.get_current_vllm_config = lambda: _Cfg()
    monkeypatch.setitem(sys.modules, "vllm.config", fake)
    # ensure a parent 'vllm' package object exists for the submodule import
    if "vllm" not in sys.modules:
        monkeypatch.setitem(sys.modules, "vllm", types.ModuleType("vllm"))
    assert p38._p38_default_max_model_len() == 131072
