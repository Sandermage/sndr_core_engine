# SPDX-License-Identifier: Apache-2.0
"""Unit tests for PN96B's Gemma 4 architecture gate.

Binary search 2026-05-15 identified PN96B as the patch that corrupts
Gemma 4 ``max_model_len`` at config-merge time. The fix adds an early
return in ``apply()`` when ``is_gemma4_arch(get_current_vllm_config())``
is true, with an override env flag ``GENESIS_PN96B_FORCE_GEMMA4=1``.
"""
from __future__ import annotations

import os
import sys
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _reset_pn96b_state():
    """Reset module-level state so each test starts clean."""
    from sndr.engines.vllm.patches.moe import (
        pn96b_marlin_persistent_workspace as mod,
    )
    mod._APPLY_INSTALLED = False
    mod._ORIGINAL_MARLIN_APPLY = None
    mod._ORIGINAL_FUSED_MARLIN_MOE = None
    yield
    mod._APPLY_INSTALLED = False
    mod._ORIGINAL_MARLIN_APPLY = None
    mod._ORIGINAL_FUSED_MARLIN_MOE = None


def _install_fake_vllm_config(cfg_obj):
    """Inject a fake ``vllm.config`` module exposing
    ``get_current_vllm_config()`` returning ``cfg_obj``. Returns a
    teardown callable."""
    fake = ModuleType("vllm.config")
    fake.get_current_vllm_config = lambda: cfg_obj
    prev = sys.modules.get("vllm.config")
    sys.modules["vllm.config"] = fake
    # Also expose attribute on existing vllm module if present
    vllm_mod = sys.modules.get("vllm")
    prev_attr = getattr(vllm_mod, "config", None) if vllm_mod else None
    if vllm_mod is not None:
        vllm_mod.config = fake

    def _restore():
        if prev is None:
            sys.modules.pop("vllm.config", None)
        else:
            sys.modules["vllm.config"] = prev
        if vllm_mod is not None:
            if prev_attr is None:
                if hasattr(vllm_mod, "config"):
                    delattr(vllm_mod, "config")
            else:
                vllm_mod.config = prev_attr
    return _restore


def _make_gemma4_vllm_config():
    """Build a minimal config-shaped object that is_gemma4_arch accepts."""
    hf_config = SimpleNamespace(
        architectures=["Gemma4ForConditionalGeneration"],
        model_type="gemma4",
    )
    model_config = SimpleNamespace(hf_config=hf_config)
    return SimpleNamespace(model_config=model_config)


def _make_qwen_vllm_config():
    """Build a minimal non-Gemma config (Qwen3.5 MoE shape)."""
    hf_config = SimpleNamespace(
        architectures=["Qwen3MoeForCausalLM"],
        model_type="qwen3_moe",
    )
    model_config = SimpleNamespace(hf_config=hf_config)
    return SimpleNamespace(model_config=model_config)


def test_pn96b_skips_on_gemma4_arch(monkeypatch):
    """When vllm_config carries a Gemma 4 architecture, apply() must skip."""
    from sndr.engines.vllm.patches.moe import (
        pn96b_marlin_persistent_workspace as mod,
    )
    monkeypatch.delenv("GENESIS_PN96B_FORCE_GEMMA4", raising=False)
    monkeypatch.delenv("GENESIS_DISABLE_PN96", raising=False)
    monkeypatch.delenv("GENESIS_DISABLE_PN96B", raising=False)

    teardown = _install_fake_vllm_config(_make_gemma4_vllm_config())
    try:
        status, reason = mod.apply()
    finally:
        teardown()

    assert status == "skipped"
    assert "Gemma 4" in reason
    assert "GENESIS_PN96B_FORCE_GEMMA4" in reason
    assert mod._APPLY_INSTALLED is False


def test_pn96b_force_gemma4_bypasses_gate(monkeypatch):
    """GENESIS_PN96B_FORCE_GEMMA4=1 must allow apply() to proceed past
    the gemma4 gate (subsequent gates may still skip — but NOT the
    gemma4 one)."""
    from sndr.engines.vllm.patches.moe import (
        pn96b_marlin_persistent_workspace as mod,
    )
    monkeypatch.setenv("GENESIS_PN96B_FORCE_GEMMA4", "1")
    monkeypatch.delenv("GENESIS_DISABLE_PN96", raising=False)
    monkeypatch.delenv("GENESIS_DISABLE_PN96B", raising=False)

    teardown = _install_fake_vllm_config(_make_gemma4_vllm_config())
    try:
        status, reason = mod.apply()
    finally:
        teardown()

    # Status is either "applied" (if Marlin moe importable + cuda+) or
    # "skipped" for a NON-gemma4 reason (platform/import). Either is fine —
    # the assertion is that the skip reason is NOT the gemma4 one.
    if status == "skipped":
        assert "Gemma 4" not in reason, (
            f"FORCE flag failed to bypass gemma4 gate: {reason}"
        )


def test_pn96b_non_gemma4_arch_proceeds(monkeypatch):
    """Non-Gemma4 model (e.g. Qwen3) must NOT be gated by the gemma4 check."""
    from sndr.engines.vllm.patches.moe import (
        pn96b_marlin_persistent_workspace as mod,
    )
    monkeypatch.delenv("GENESIS_PN96B_FORCE_GEMMA4", raising=False)
    monkeypatch.delenv("GENESIS_DISABLE_PN96", raising=False)
    monkeypatch.delenv("GENESIS_DISABLE_PN96B", raising=False)

    teardown = _install_fake_vllm_config(_make_qwen_vllm_config())
    try:
        status, reason = mod.apply()
    finally:
        teardown()

    if status == "skipped":
        assert "Gemma 4" not in reason, (
            f"non-gemma4 model wrongly hit gemma4 gate: {reason}"
        )


def test_pn96b_missing_vllm_config_proceeds(monkeypatch):
    """get_current_vllm_config() returning None must not trip the gate
    (fail-open: skip the gemma4 check, let platform gate decide)."""
    from sndr.engines.vllm.patches.moe import (
        pn96b_marlin_persistent_workspace as mod,
    )
    monkeypatch.delenv("GENESIS_PN96B_FORCE_GEMMA4", raising=False)
    monkeypatch.delenv("GENESIS_DISABLE_PN96", raising=False)
    monkeypatch.delenv("GENESIS_DISABLE_PN96B", raising=False)

    teardown = _install_fake_vllm_config(None)
    try:
        status, reason = mod.apply()
    finally:
        teardown()

    if status == "skipped":
        assert "Gemma 4" not in reason


def test_pn96b_disable_wins_over_gemma4_gate(monkeypatch):
    """GENESIS_DISABLE_PN96B=1 short-circuits BEFORE the gemma4 probe;
    skip reason mentions explicit disable, not gemma4."""
    from sndr.engines.vllm.patches.moe import (
        pn96b_marlin_persistent_workspace as mod,
    )
    monkeypatch.setenv("GENESIS_DISABLE_PN96B", "1")

    teardown = _install_fake_vllm_config(_make_gemma4_vllm_config())
    try:
        status, reason = mod.apply()
    finally:
        teardown()

    assert status == "skipped"
    assert "explicit disable" in reason
    assert "Gemma 4" not in reason
