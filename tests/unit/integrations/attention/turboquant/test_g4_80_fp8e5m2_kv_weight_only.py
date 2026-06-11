# SPDX-License-Identifier: Apache-2.0
"""G4_80 — allow fp8_e5m2 KV cache for weight-only checkpoints (vllm#45040).

Torch-less unit tests. The patch wraps the module-level
``_init_kv_cache_quant`` in ``vllm/model_executor/layers/attention/
attention.py`` so that the pristine reject gate

    if layer.kv_cache_dtype == "fp8_e5m2":
        raise ValueError("fp8_e5m2 kv-cache is not supported with fp8
                          checkpoints.")

stops firing for weight-only quantized checkpoints (compressed-tensors
AWQ/GPTQ/INT4/INT8 that declare NO ``kv_cache_scheme`` — they carry no
fp8 KV scales). Genuine fp8-KV checkpoints stay rejected, mirroring the
upstream PR's ``_checkpoint_has_fp8_kv_scales`` predicate.

Tests exercise the pure helpers against fakes (no vllm import):
predicate, gate-signature drift guard, wrapper dtype-mask mechanics,
and module rebind/revert (including the mla_attention by-value import).
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest


MODULE = (
    "sndr.engines.vllm.patches.attention.turboquant."
    "g4_80_fp8e5m2_kv_weight_only"
)

GATE_MESSAGE = "fp8_e5m2 kv-cache is not supported with fp8 checkpoints."


@pytest.fixture()
def mod():
    return importlib.import_module(MODULE)


class _FakeKVCacheMethod:
    """Stand-in for CompressedTensorsKVCacheMethod."""

    def __init__(self, kv_cache_scheme):
        self.quant_config = SimpleNamespace(kv_cache_scheme=kv_cache_scheme)


class _OtherMethod:
    """Non compressed-tensors quant method (e.g. fp8 checkpoint)."""


def _fake_quant_config(quant_method):
    return SimpleNamespace(
        get_quant_method=lambda layer, prefix: quant_method,
        kv_cache_scheme=getattr(
            getattr(quant_method, "quant_config", None),
            "kv_cache_scheme",
            None,
        ),
    )


def _pristine_like_original():
    """Byte-equivalent reject-gate body of the pristine helper
    (pin 0.22.1rc1.dev259+g303916e93 attention.py:158-174, reduced)."""

    def _init_kv_cache_quant(layer, quant_config, prefix):
        quant_method = (
            quant_config.get_quant_method(layer, prefix=prefix)
            if quant_config
            else None
        )
        if quant_method is not None and not callable(quant_method):
            if layer.kv_cache_dtype == "fp8_e5m2":
                raise ValueError(
                    "fp8_e5m2 kv-cache is not supported with fp8 checkpoints."
                )
            layer.quant_method = quant_method

    return _init_kv_cache_quant


class TestCheckpointHasFp8KvScales:
    def test_weight_only_no_scheme_false(self, mod):
        method = _FakeKVCacheMethod(kv_cache_scheme=None)
        assert mod._checkpoint_has_fp8_kv_scales(
            method, kv_cache_method_cls=_FakeKVCacheMethod
        ) is False

    def test_declared_scheme_true(self, mod):
        method = _FakeKVCacheMethod(
            kv_cache_scheme={"num_bits": 8, "type": "float"}
        )
        assert mod._checkpoint_has_fp8_kv_scales(
            method, kv_cache_method_cls=_FakeKVCacheMethod
        ) is True

    def test_non_compressed_tensors_method_true(self, mod):
        # Conservative: anything that is not the compressed-tensors KV
        # method keeps the upstream rejection (fp8 checkpoints).
        assert mod._checkpoint_has_fp8_kv_scales(
            _OtherMethod(), kv_cache_method_cls=_FakeKVCacheMethod
        ) is True

    def test_unresolvable_class_true(self, mod):
        # kv_cache_method_cls=None → either vllm is not importable (cls
        # None → conservative True) or it is and the fake is not an
        # instance of the real CT class (→ True). Deterministic both ways.
        assert mod._checkpoint_has_fp8_kv_scales(
            _FakeKVCacheMethod(None), kv_cache_method_cls=None
        ) is True


class TestGateSignatureDriftGuard:
    def test_present_on_pristine_like_source(self, mod):
        assert mod._gate_signature_present(_pristine_like_original()) is True

    def test_absent_after_upstream_merge_shape(self, mod):
        def merged_like(layer, quant_config, prefix):
            # Post-#45040 upstream shape: predicate-qualified gate.
            if layer.kv_cache_dtype == "fp8_e5m2" and bool(quant_config):
                raise ValueError("different message")

        assert mod._gate_signature_present(merged_like) is False

    def test_unsourceable_function_false(self, mod):
        assert mod._gate_signature_present(len) is False


class TestWrapper:
    def test_weight_only_fp8e5m2_passes_gate(self, mod, monkeypatch):
        monkeypatch.delenv(mod._ENV_FORCE_ALLOW, raising=False)
        original = _pristine_like_original()
        wrapper = mod._make_wrapped_init_kv_cache_quant(
            original, kv_cache_method_cls=_FakeKVCacheMethod
        )
        method = _FakeKVCacheMethod(kv_cache_scheme=None)
        layer = SimpleNamespace(kv_cache_dtype="fp8_e5m2")
        wrapper(layer, _fake_quant_config(method), "layers.0.attn")
        # Gate bypassed AND dtype restored for downstream consumers
        # (kv_cache spec, backend validation read layer.kv_cache_dtype).
        assert layer.kv_cache_dtype == "fp8_e5m2"
        assert layer.quant_method is method

    def test_fp8_scales_checkpoint_still_rejected(self, mod, monkeypatch):
        monkeypatch.delenv(mod._ENV_FORCE_ALLOW, raising=False)
        original = _pristine_like_original()
        wrapper = mod._make_wrapped_init_kv_cache_quant(
            original, kv_cache_method_cls=_FakeKVCacheMethod
        )
        method = _FakeKVCacheMethod(kv_cache_scheme={"num_bits": 8})
        layer = SimpleNamespace(kv_cache_dtype="fp8_e5m2")
        with pytest.raises(ValueError, match="fp8_e5m2 kv-cache"):
            wrapper(layer, _fake_quant_config(method), "layers.0.attn")
        assert layer.kv_cache_dtype == "fp8_e5m2"

    def test_force_allow_env_overrides_scheme_reject(self, mod, monkeypatch):
        monkeypatch.setenv(mod._ENV_FORCE_ALLOW, "1")
        original = _pristine_like_original()
        wrapper = mod._make_wrapped_init_kv_cache_quant(
            original, kv_cache_method_cls=_FakeKVCacheMethod
        )
        method = _FakeKVCacheMethod(kv_cache_scheme={"num_bits": 8})
        layer = SimpleNamespace(kv_cache_dtype="fp8_e5m2")
        wrapper(layer, _fake_quant_config(method), "layers.0.attn")
        assert layer.kv_cache_dtype == "fp8_e5m2"
        assert layer.quant_method is method

    def test_non_fp8e5m2_dtype_untouched(self, mod, monkeypatch):
        monkeypatch.delenv(mod._ENV_FORCE_ALLOW, raising=False)
        calls = {}

        def original(layer, quant_config, prefix):
            calls["dtype_seen"] = layer.kv_cache_dtype

        wrapper = mod._make_wrapped_init_kv_cache_quant(
            original, kv_cache_method_cls=_FakeKVCacheMethod
        )
        layer = SimpleNamespace(kv_cache_dtype="auto")
        wrapper(layer, _fake_quant_config(_FakeKVCacheMethod(None)), "p")
        assert calls["dtype_seen"] == "auto"

    def test_none_quant_config_passthrough(self, mod):
        def original(layer, quant_config, prefix):
            layer.touched = True

        wrapper = mod._make_wrapped_init_kv_cache_quant(
            original, kv_cache_method_cls=_FakeKVCacheMethod
        )
        layer = SimpleNamespace(kv_cache_dtype="fp8_e5m2")
        wrapper(layer, None, "p")
        assert layer.touched is True

    def test_dtype_restored_when_original_raises(self, mod, monkeypatch):
        monkeypatch.delenv(mod._ENV_FORCE_ALLOW, raising=False)

        def boom(layer, quant_config, prefix):
            raise RuntimeError("create_weights failed")

        wrapper = mod._make_wrapped_init_kv_cache_quant(
            boom, kv_cache_method_cls=_FakeKVCacheMethod
        )
        layer = SimpleNamespace(kv_cache_dtype="fp8_e5m2")
        with pytest.raises(RuntimeError):
            wrapper(layer, _fake_quant_config(_FakeKVCacheMethod(None)), "p")
        assert layer.kv_cache_dtype == "fp8_e5m2"


class TestInstallRevert:
    def _fake_modules(self):
        original = _pristine_like_original()
        attention_mod = SimpleNamespace(_init_kv_cache_quant=original)
        # mla_attention.py imports the symbol BY VALUE at module level
        # (pristine mla_attention.py:219) — rebind must cover it too.
        mla_mod = SimpleNamespace(_init_kv_cache_quant=original)
        return attention_mod, mla_mod

    def test_install_rebinds_both_modules(self, mod):
        attention_mod, mla_mod = self._fake_modules()
        changed = mod.install_fp8e5m2_weight_only_gate(
            attention_mod, mla_mod, kv_cache_method_cls=_FakeKVCacheMethod
        )
        assert changed is True
        assert getattr(
            attention_mod._init_kv_cache_quant, "_genesis_g4_80_wrapped", False
        )
        assert getattr(
            mla_mod._init_kv_cache_quant, "_genesis_g4_80_wrapped", False
        )

    def test_install_idempotent(self, mod):
        attention_mod, mla_mod = self._fake_modules()
        assert mod.install_fp8e5m2_weight_only_gate(
            attention_mod, mla_mod, kv_cache_method_cls=_FakeKVCacheMethod
        ) is True
        assert mod.install_fp8e5m2_weight_only_gate(
            attention_mod, mla_mod, kv_cache_method_cls=_FakeKVCacheMethod
        ) is False
        # No double-wrap: unwrapping once must land on the original.
        inner = attention_mod._init_kv_cache_quant.__wrapped__
        assert not getattr(inner, "_genesis_g4_80_wrapped", False)

    def test_revert_restores_originals(self, mod):
        attention_mod, mla_mod = self._fake_modules()
        original = attention_mod._init_kv_cache_quant
        mod.install_fp8e5m2_weight_only_gate(
            attention_mod, mla_mod, kv_cache_method_cls=_FakeKVCacheMethod
        )
        assert mod.revert_fp8e5m2_weight_only_gate(attention_mod, mla_mod)
        assert attention_mod._init_kv_cache_quant is original
        assert mla_mod._init_kv_cache_quant is original

    def test_install_refuses_on_gate_drift(self, mod):
        # Drift guard: when the pristine gate signature is gone
        # (e.g. #45040 merged at a future pin), install must refuse —
        # re-audit instead of stacking a stale wrapper.
        def merged_like(layer, quant_config, prefix):
            return None

        attention_mod = SimpleNamespace(_init_kv_cache_quant=merged_like)
        changed = mod.install_fp8e5m2_weight_only_gate(
            attention_mod, None, kv_cache_method_cls=_FakeKVCacheMethod
        )
        assert changed is False
        assert attention_mod._init_kv_cache_quant is merged_like


class TestQueryQuantArm:
    """Arm 2 (query-quant neutralizer) — kills the SECOND pristine gate.

    On the pin, ``Attention.__init__`` creates ``self.query_quant`` for
    ANY fp8* kv_cache_dtype whenever ``impl.supports_quant_query_input``
    (TritonAttentionImpl: unconditionally True on CUDA,
    triton_attn.py:502); the FIRST forward then hits
    ``assert self.kv_cache_dtype in {"fp8", "fp8_e4m3", "nvfp4"}``
    (attention.py:467) → AssertionError for "fp8_e5m2" during the boot
    memory-profiling dummy run. The arm nulls ``query_quant`` post-init
    for fp8_e5m2 layers; impl forwards handle unquantized queries
    natively (triton_attn.py:607-614 only sets q_descale when
    query.dtype is the fp8 dtype).
    """

    def _fake_attention_cls(self):
        class FakeAttention:
            def __init__(self, *args, **kwargs):
                self.init_args = (args, kwargs)
                self.kv_cache_dtype = kwargs.pop("_dtype", "auto")
                self.query_quant = kwargs.pop("_qq", None)

        return FakeAttention

    def test_e5m2_query_quant_neutralized(self, mod):
        cls = self._fake_attention_cls()
        assert mod.install_query_quant_guard(cls) is True
        sentinel = object()
        inst = cls(1, 2, _dtype="fp8_e5m2", _qq=sentinel, prefix="layers.0")
        assert inst.query_quant is None

    def test_init_args_passed_through(self, mod):
        cls = self._fake_attention_cls()
        mod.install_query_quant_guard(cls)
        inst = cls(7, scale=0.5, _dtype="fp8_e5m2", _qq=object())
        args, kwargs = inst.init_args
        assert args == (7,)
        assert kwargs["scale"] == 0.5

    def test_fp8_query_quant_preserved(self, mod):
        # "fp8" passes the forward assert — the optimization must stay.
        cls = self._fake_attention_cls()
        mod.install_query_quant_guard(cls)
        sentinel = object()
        inst = cls(_dtype="fp8", _qq=sentinel)
        assert inst.query_quant is sentinel

    def test_fp8_e4m3_query_quant_preserved(self, mod):
        cls = self._fake_attention_cls()
        mod.install_query_quant_guard(cls)
        sentinel = object()
        inst = cls(_dtype="fp8_e4m3", _qq=sentinel)
        assert inst.query_quant is sentinel

    def test_e5m2_without_query_quant_noop(self, mod):
        # Backend with supports_quant_query_input False (or non-CUDA):
        # query_quant is already None — arm must be a silent no-op.
        cls = self._fake_attention_cls()
        mod.install_query_quant_guard(cls)
        inst = cls(_dtype="fp8_e5m2", _qq=None)
        assert inst.query_quant is None

    def test_auto_dtype_untouched(self, mod):
        cls = self._fake_attention_cls()
        mod.install_query_quant_guard(cls)
        sentinel = object()
        inst = cls(_dtype="auto", _qq=sentinel)
        assert inst.query_quant is sentinel

    def test_install_idempotent_no_double_wrap(self, mod):
        cls = self._fake_attention_cls()
        assert mod.install_query_quant_guard(cls) is True
        assert mod.install_query_quant_guard(cls) is False
        inner = cls.__init__.__wrapped__
        assert not getattr(inner, "_genesis_g4_80_qq_wrapped", False)

    def test_revert_restores_original(self, mod):
        cls = self._fake_attention_cls()
        original = cls.__init__
        mod.install_query_quant_guard(cls)
        assert mod.revert_query_quant_guard(cls) is True
        assert cls.__init__ is original

    def test_revert_without_install_false(self, mod):
        cls = self._fake_attention_cls()
        assert mod.revert_query_quant_guard(cls) is False


class TestModuleContract:
    def test_env_flag_name(self, mod):
        assert mod._ENV_ENABLE == "GENESIS_ENABLE_G4_80_FP8E5M2_KV"

    def test_marker_exists(self, mod):
        assert "G4_80" in mod.GENESIS_G4_80_MARKER

    def test_apply_callable(self, mod):
        assert callable(mod.apply)

    def test_apply_skips_when_env_unset(self, mod, monkeypatch):
        monkeypatch.delenv(mod._ENV_ENABLE, raising=False)
        status, reason = mod.apply()
        assert status == "skipped"
        assert reason
