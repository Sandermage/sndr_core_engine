# SPDX-License-Identifier: Apache-2.0
"""TDD for PN62 — text-only ViT scratch skip on qwen3_vl.

Wave 6 (2026-05-09): real hook now flips
``MultiModalConfig.skip_mm_profiling`` to True before profile_run, so
vllm's native encoder-skip short-circuit fires. These tests exercise
the detection logic, the flag flip, and the wrapper integration.
"""
from __future__ import annotations

import pytest

from vllm.sndr_core.integrations.multimodal.pn62_text_only_vit_skip import (
    _is_text_only_mode,
    _flip_skip_flag,
    _wrap_profile_run,
)


# ─── helpers ────────────────────────────────────────────────────────────


class _FakeMMConfig:
    def __init__(self, limit_per_prompt=None, skip=False):
        self.limit_per_prompt = limit_per_prompt
        self.skip_mm_profiling = skip


class _FakeModelConfig:
    def __init__(self, lmo=False, mm_config=None, limit_mm_per_prompt=None):
        self.language_model_only = lmo
        self.multimodal_config = mm_config
        if limit_mm_per_prompt is not None:
            self.limit_mm_per_prompt = limit_mm_per_prompt


class _FakeRunner:
    def __init__(self, lmo=False, mm_limits=None, mm_config=True, has_skip_flag=True):
        if mm_config:
            mmc = _FakeMMConfig(limit_per_prompt=mm_limits, skip=False)
            if not has_skip_flag:
                # simulate older vllm pin — no skip_mm_profiling field
                del mmc.skip_mm_profiling
        else:
            mmc = None
        self.model_config = _FakeModelConfig(lmo=lmo, mm_config=mmc)


# ─── _is_text_only_mode ────────────────────────────────────────────────


class TestTextOnlyModeDetection:
    def test_no_lmo_returns_false(self):
        r = _FakeRunner(lmo=False)
        assert _is_text_only_mode(r) is False

    def test_lmo_with_zero_limits_returns_true(self):
        r = _FakeRunner(lmo=True, mm_limits={"image": 0, "video": 0})
        assert _is_text_only_mode(r) is True

    def test_lmo_with_no_limits_returns_true(self):
        """Empty mm_limits dict + lmo → considered text-only."""
        r = _FakeRunner(lmo=True, mm_limits={})
        assert _is_text_only_mode(r) is True

    def test_lmo_with_nonzero_limits_returns_false(self):
        r = _FakeRunner(lmo=True, mm_limits={"image": 1})
        assert _is_text_only_mode(r) is False

    def test_lmo_no_mm_config_returns_true(self):
        """lmo=True with no multimodal_config at all → text-only."""
        r = _FakeRunner(lmo=True, mm_config=False)
        assert _is_text_only_mode(r) is True

    def test_no_config_returns_false(self):
        r = type("R", (), {})()
        assert _is_text_only_mode(r) is False

    def test_lookup_via_vllm_config_fallback(self):
        """When runner has no `model_config` attr, look through vllm_config."""
        r = type("R", (), {})()
        r.vllm_config = type("VC", (), {})()
        r.vllm_config.model_config = _FakeModelConfig(
            lmo=True, mm_config=_FakeMMConfig(limit_per_prompt={})
        )
        assert _is_text_only_mode(r) is True


# ─── _flip_skip_flag ────────────────────────────────────────────────────


class TestFlipFlag:
    def test_flip_succeeds_when_unset(self):
        r = _FakeRunner(lmo=True, mm_limits={})
        flipped, reason = _flip_skip_flag(r)
        assert flipped is True
        assert r.model_config.multimodal_config.skip_mm_profiling is True
        assert "False→True" in reason

    def test_already_true_idempotent(self):
        r = _FakeRunner(lmo=True, mm_limits={})
        r.model_config.multimodal_config.skip_mm_profiling = True
        flipped, reason = _flip_skip_flag(r)
        assert flipped is False
        assert "already True" in reason

    def test_no_mm_config_returns_false(self):
        r = _FakeRunner(lmo=True, mm_config=False)
        flipped, reason = _flip_skip_flag(r)
        assert flipped is False
        assert "not mm-capable" in reason

    def test_no_skip_flag_field_returns_false(self):
        """Older vllm pin with no skip_mm_profiling field — abstain."""
        r = _FakeRunner(lmo=True, mm_limits={}, has_skip_flag=False)
        flipped, reason = _flip_skip_flag(r)
        assert flipped is False
        assert "absent on this vllm pin" in reason

    def test_no_model_config_returns_false(self):
        r = type("R", (), {})()
        flipped, reason = _flip_skip_flag(r)
        assert flipped is False
        assert "no model_config" in reason


# ─── _wrap_profile_run ──────────────────────────────────────────────────


class TestProfileRunWrapper:
    def test_text_only_flips_flag_before_call(self):
        """When text-only, wrapper flips skip flag BEFORE original runs."""
        captured = {}

        def fake_profile_run(self, *args, **kwargs):
            captured["skip_during_call"] = (
                self.model_config.multimodal_config.skip_mm_profiling
            )

        runner = _FakeRunner(lmo=True, mm_limits={"image": 0})
        wrapped = _wrap_profile_run(fake_profile_run)
        wrapped(runner)
        # By the time original runs, skip flag must already be True
        assert captured["skip_during_call"] is True

    def test_non_text_only_does_not_flip_flag(self):
        captured = {}

        def fake_profile_run(self, *args, **kwargs):
            captured["skip_during_call"] = (
                self.model_config.multimodal_config.skip_mm_profiling
            )

        runner = _FakeRunner(lmo=False)
        wrapped = _wrap_profile_run(fake_profile_run)
        wrapped(runner)
        # Text-only NOT detected → flag stays False
        assert captured["skip_during_call"] is False

    def test_no_mm_config_text_only_marker_set(self):
        """text-only without mm_config — sets fallback runner marker."""
        called = {"yes": False}

        def fake_profile_run(self, *args, **kwargs):
            called["yes"] = True

        runner = _FakeRunner(lmo=True, mm_config=False)
        wrapped = _wrap_profile_run(fake_profile_run)
        wrapped(runner)
        assert called["yes"] is True
        assert getattr(runner, "_pn62_skip_vit_scratch", False) is True

    def test_propagates_inner_exception(self):
        def fake_profile_run(self, *args, **kwargs):
            raise RuntimeError("inner failure")

        runner = _FakeRunner(lmo=True, mm_limits={})
        wrapped = _wrap_profile_run(fake_profile_run)
        with pytest.raises(RuntimeError, match="inner failure"):
            wrapped(runner)
        # Skip flag was flipped — caller can inspect it
        assert runner.model_config.multimodal_config.skip_mm_profiling is True

    def test_idempotency_marker_attached(self):
        wrapped = _wrap_profile_run(lambda self: None)
        assert getattr(wrapped, "__pn62_wrapped__", False) is True

    def test_wrapped_records_original(self):
        original = lambda self: "ok"
        wrapped = _wrap_profile_run(original)
        assert wrapped.__wrapped__ is original


# ─── apply() integration ────────────────────────────────────────────────


class TestApplyFunction:
    def test_apply_skipped_when_env_disabled(self, monkeypatch):
        from vllm.sndr_core.integrations.multimodal import pn62_text_only_vit_skip as p
        monkeypatch.delenv("GENESIS_ENABLE_PN62", raising=False)
        status, reason = p.apply()
        assert status == "skipped"

    def test_apply_skipped_when_runner_module_absent(self, monkeypatch):
        from vllm.sndr_core.integrations.multimodal import pn62_text_only_vit_skip as p
        monkeypatch.setenv("GENESIS_ENABLE_PN62", "1")
        import sys
        monkeypatch.setitem(
            sys.modules, "vllm.v1.worker.gpu_model_runner", None
        )
        status, reason = p.apply()
        assert status == "skipped"
        assert "not importable" in reason or "GPUModelRunner" in reason
