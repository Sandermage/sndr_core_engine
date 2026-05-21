# SPDX-License-Identifier: Apache-2.0
"""CPU-only unit tests for PN275 — DFlash drafter VllmConfig max_cgs
alignment (dev371 compat).

These tests exercise the wrapper closure built by `_build_wrapper`
against synthetic stand-ins for `vllm.config.utils.replace` and the
VllmConfig dataclass. No torch / CUDA / pydantic dependency required.

Covered behavior:

  * `should_apply()` is False without the env, True when env truthy.
  * The wrapper only intervenes when the source's class name is
    'VllmConfig'.
  * When caller supplies `compilation_config` in kwargs, wrapper
    defers to the original verbatim.
  * When source's compilation_config has consistent sizes/max,
    wrapper delegates without modifying kwargs.
  * When source has desynchronized max/sizes, wrapper builds an
    aligned compilation_config and injects it into kwargs.
  * Marker `_genesis_dflash_align_wrapped` prevents double-wrap on
    a second apply() call.
  * `is_applied()` / `revert()` round-trip on a fake module.
  * Registry entry shape matches the documented invariants.
"""
from __future__ import annotations

import os
import types
import unittest.mock as mock

import pytest


# ─── Module import (no torch dep) ───────────────────────────────────────


def _import_patch():
    """Import the patch module fresh. Test isolation: each call returns
    the module's current state (env-gated behavior changes with the
    surrounding monkeypatch)."""
    from vllm.sndr_core.integrations.spec_decode import (
        pn275_dflash_max_cgs_align as p,
    )
    return p


# ─── should_apply ───────────────────────────────────────────────────────


class TestShouldApply:
    def test_no_env_returns_false(self, monkeypatch):
        monkeypatch.delenv(
            "GENESIS_ENABLE_PN275_DFLASH_MAX_CGS_ALIGN", raising=False
        )
        assert _import_patch().should_apply() is False

    @pytest.mark.parametrize("v", ["1", "true", "yes", "on", "True", "YES"])
    def test_truthy_env_returns_true(self, monkeypatch, v):
        monkeypatch.setenv(
            "GENESIS_ENABLE_PN275_DFLASH_MAX_CGS_ALIGN", v
        )
        assert _import_patch().should_apply() is True

    @pytest.mark.parametrize("v", ["0", "", "false", "off", "no", "False"])
    def test_falsy_env_returns_false(self, monkeypatch, v):
        monkeypatch.setenv(
            "GENESIS_ENABLE_PN275_DFLASH_MAX_CGS_ALIGN", v
        )
        assert _import_patch().should_apply() is False


# ─── Wrapper closure behavior ───────────────────────────────────────────


class _FakeVllmConfig:
    """Stand-in. `type(x).__name__ == 'VllmConfig'` because of the
    class rename below at the bottom of the module."""

    def __init__(self, compilation_config):
        self.compilation_config = compilation_config


# Rename the class so it matches the wrapper's string-match check.
_FakeVllmConfig.__name__ = "VllmConfig"


class _FakeCompilationConfig:
    def __init__(self, max_cudagraph_capture_size, cudagraph_capture_sizes):
        self.max_cudagraph_capture_size = max_cudagraph_capture_size
        self.cudagraph_capture_sizes = cudagraph_capture_sizes


class _NonVllmConfig:
    def __init__(self):
        self.compilation_config = None


class TestWrapperBehavior:
    def _make_recorder(self):
        """Return (recorder, fake_replace). fake_replace mimics
        upstream `utils.replace` enough to be a wrap target — it
        records the call (instance, kwargs) and returns a sentinel."""
        recorded = []

        def fake_replace(instance, /, **kwargs):
            recorded.append({
                "instance": instance,
                "kwargs": dict(kwargs),
            })
            # When called with a CompilationConfig to align, return a
            # new CompilationConfig with the override applied. This
            # mimics `cls(**dataclass_dict)` shape for the recursive
            # alignment call inside the wrapper.
            if isinstance(instance, _FakeCompilationConfig):
                merged_max = kwargs.get(
                    "max_cudagraph_capture_size",
                    instance.max_cudagraph_capture_size,
                )
                return _FakeCompilationConfig(
                    merged_max, instance.cudagraph_capture_sizes,
                )
            return "ORIG_RESULT"
        return recorded, fake_replace

    def test_non_vllm_config_passes_through_untouched(self):
        recorded, fake_replace = self._make_recorder()
        wrapper = _import_patch()._build_wrapper(fake_replace)

        non_vllm = _NonVllmConfig()
        result = wrapper(non_vllm, attention_config="ATTN")
        assert result == "ORIG_RESULT"
        # Exactly one call to original; kwargs untouched
        assert len(recorded) == 1
        assert recorded[0]["instance"] is non_vllm
        assert recorded[0]["kwargs"] == {"attention_config": "ATTN"}

    def test_caller_supplied_compilation_config_kwarg_is_respected(self):
        recorded, fake_replace = self._make_recorder()
        wrapper = _import_patch()._build_wrapper(fake_replace)

        cc = _FakeCompilationConfig(
            max_cudagraph_capture_size=8,
            cudagraph_capture_sizes=[1, 2, 4, 6],
        )
        vc = _FakeVllmConfig(cc)
        operator_supplied_cc = _FakeCompilationConfig(99, [1])
        wrapper(vc, compilation_config=operator_supplied_cc)
        # Wrapper must NOT replace the operator's explicit kwarg
        assert len(recorded) == 1
        assert recorded[0]["kwargs"]["compilation_config"] is (
            operator_supplied_cc
        )

    def test_consistent_max_and_sizes_pass_through(self):
        recorded, fake_replace = self._make_recorder()
        wrapper = _import_patch()._build_wrapper(fake_replace)

        cc = _FakeCompilationConfig(
            max_cudagraph_capture_size=8,
            cudagraph_capture_sizes=[1, 2, 4, 8],
        )
        vc = _FakeVllmConfig(cc)
        wrapper(vc, attention_config="ATTN")
        # Original called exactly once; no compilation_config inject
        assert len(recorded) == 1
        assert "compilation_config" not in recorded[0]["kwargs"]

    def test_empty_sizes_passes_through(self):
        recorded, fake_replace = self._make_recorder()
        wrapper = _import_patch()._build_wrapper(fake_replace)

        cc = _FakeCompilationConfig(
            max_cudagraph_capture_size=8,
            cudagraph_capture_sizes=[],   # empty
        )
        vc = _FakeVllmConfig(cc)
        wrapper(vc, attention_config="ATTN")
        assert len(recorded) == 1
        assert "compilation_config" not in recorded[0]["kwargs"]

    def test_max_none_passes_through(self):
        recorded, fake_replace = self._make_recorder()
        wrapper = _import_patch()._build_wrapper(fake_replace)

        cc = _FakeCompilationConfig(
            max_cudagraph_capture_size=None,
            cudagraph_capture_sizes=[1, 2, 4, 6],
        )
        vc = _FakeVllmConfig(cc)
        wrapper(vc, attention_config="ATTN")
        assert len(recorded) == 1
        assert "compilation_config" not in recorded[0]["kwargs"]

    def test_desync_triggers_alignment_inject(self):
        """The canonical defect case: max=8 vs sizes=[..., 6]. Wrapper
        must inject an aligned compilation_config (max=6) into kwargs
        before delegating."""
        recorded, fake_replace = self._make_recorder()
        wrapper = _import_patch()._build_wrapper(fake_replace)

        cc = _FakeCompilationConfig(
            max_cudagraph_capture_size=8,
            cudagraph_capture_sizes=[1, 2, 4, 6],
        )
        vc = _FakeVllmConfig(cc)
        wrapper(vc, attention_config="ATTN")
        # Two calls: one for the inner align (CompilationConfig rebuild),
        # one for the outer VllmConfig replace
        assert len(recorded) == 2
        # First call rebuilds CompilationConfig with max=6
        assert recorded[0]["instance"] is cc
        assert recorded[0]["kwargs"] == {"max_cudagraph_capture_size": 6}
        # Second call sees the aligned compilation_config injected
        outer_kwargs = recorded[1]["kwargs"]
        assert "compilation_config" in outer_kwargs
        aligned_cc = outer_kwargs["compilation_config"]
        assert aligned_cc.max_cudagraph_capture_size == 6
        # And the operator's attention_config kwarg is preserved
        assert outer_kwargs["attention_config"] == "ATTN"

    def test_alignment_failure_falls_through_to_original(self):
        """If the inner alignment call raises, the wrapper must NOT
        propagate — fall through to the original outer call so pydantic
        can surface the real error."""
        recorded = []

        def fake_replace(instance, /, **kwargs):
            if isinstance(instance, _FakeCompilationConfig):
                raise RuntimeError("simulated alignment failure")
            recorded.append({"instance": instance, "kwargs": dict(kwargs)})
            return "ORIG_RESULT"

        wrapper = _import_patch()._build_wrapper(fake_replace)
        cc = _FakeCompilationConfig(
            max_cudagraph_capture_size=8,
            cudagraph_capture_sizes=[1, 2, 4, 6],
        )
        vc = _FakeVllmConfig(cc)
        result = wrapper(vc, attention_config="ATTN")
        assert result == "ORIG_RESULT"
        # Outer call was made; compilation_config NOT injected
        assert len(recorded) == 1
        assert "compilation_config" not in recorded[0]["kwargs"]


# ─── apply() / is_applied() / revert() against a fake module ───────────


class TestApplyAgainstFakeModule:
    """Exercise apply() / is_applied() / revert() by monkeypatching
    `importlib.import_module` to return a synthetic stand-in for
    `vllm.config.utils`. CPU-only — does not require vllm install."""

    def _make_fake_utils(self, replace_fn):
        m = types.ModuleType("vllm.config.utils")
        m.replace = replace_fn
        return m

    def test_apply_skips_when_env_unset(self, monkeypatch):
        monkeypatch.delenv(
            "GENESIS_ENABLE_PN275_DFLASH_MAX_CGS_ALIGN", raising=False,
        )
        p = _import_patch()
        status, reason = p.apply()
        assert status == "skipped"
        assert "GENESIS_ENABLE_PN275_DFLASH_MAX_CGS_ALIGN" in reason

    def test_apply_wraps_and_marks(self, monkeypatch):
        monkeypatch.setenv(
            "GENESIS_ENABLE_PN275_DFLASH_MAX_CGS_ALIGN", "1",
        )
        p = _import_patch()

        def original(instance, /, **kw):
            return "OK"
        fake_mod = self._make_fake_utils(original)

        with mock.patch(
            "importlib.import_module", return_value=fake_mod,
        ):
            status, reason = p.apply()
        assert status == "applied"
        # The marker MUST be present on the new fake_mod.replace
        assert getattr(fake_mod.replace, p._WRAPPED_ATTR, False) is True
        # Original is stashed for revert
        assert getattr(fake_mod.replace, p._ORIGINAL_ATTR) is original

    def test_apply_idempotent(self, monkeypatch):
        monkeypatch.setenv(
            "GENESIS_ENABLE_PN275_DFLASH_MAX_CGS_ALIGN", "1",
        )
        p = _import_patch()

        def original(instance, /, **kw):
            return "OK"
        fake_mod = self._make_fake_utils(original)

        with mock.patch(
            "importlib.import_module", return_value=fake_mod,
        ):
            p.apply()
            first_wrap = fake_mod.replace
            status, reason = p.apply()
            second_wrap = fake_mod.replace
        # Second apply must NOT double-wrap
        assert status == "applied"
        assert "idempotent" in reason
        assert first_wrap is second_wrap

    def test_revert_restores_original(self, monkeypatch):
        monkeypatch.setenv(
            "GENESIS_ENABLE_PN275_DFLASH_MAX_CGS_ALIGN", "1",
        )
        p = _import_patch()

        def original(instance, /, **kw):
            return "OK"
        fake_mod = self._make_fake_utils(original)

        with mock.patch(
            "importlib.import_module", return_value=fake_mod,
        ):
            p.apply()
            assert fake_mod.replace is not original
            ok = p.revert()
        assert ok is True
        assert fake_mod.replace is original


# ─── Registry contract ─────────────────────────────────────────────────


class TestRegistryEntry:
    def test_pn275_registered(self):
        from vllm.sndr_core.dispatcher import PATCH_REGISTRY
        assert "PN275" in PATCH_REGISTRY

    def test_pn275_metadata_shape(self):
        from vllm.sndr_core.dispatcher import PATCH_REGISTRY
        meta = PATCH_REGISTRY["PN275"]
        assert meta["env_flag"] == "GENESIS_ENABLE_PN275_DFLASH_MAX_CGS_ALIGN"
        assert meta["default_on"] is False
        assert meta["family"] == "spec_decode"
        assert meta["lifecycle"] == "experimental"
        assert meta["implementation_status"] == "experimental"
        assert meta["apply_module"] == (
            "vllm.sndr_core.integrations.spec_decode."
            "pn275_dflash_max_cgs_align"
        )
        # dev371-only — pin gate documents the dev338-incompatible
        # cross-validator that this patch addresses
        assert meta.get("vllm_version_range") == ">=0.20.2rc1.dev371"

    def test_pn275_dispatcher_hook(self):
        """The @register_patch hook must exist in the apply layer so
        sndr patches apply / boot dispatch can reach the patch."""
        from vllm.sndr_core.apply import apply_all
        assert hasattr(
            apply_all, "apply_patch_pn275_dflash_max_cgs_align"
        )
