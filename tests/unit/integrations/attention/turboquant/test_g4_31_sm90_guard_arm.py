# SPDX-License-Identifier: Apache-2.0
"""G4_31 v2 — sub-SM90 fp8 KV auto-override suppress arm (vllm#45038).

Torch-less unit tests for the second suppress arm added to the
G4_31 ``Attention.__init__`` wrap: when ``cache_config.cache_dtype ==
"auto"`` AND ``quant_config.kv_cache_scheme`` is present AND the device
is sub-SM90 (Ampere SM 8.6 in PROD), the checkpoint-driven fp8
auto-override must be suppressed (it would IMA-crash on FlashInfer-less
fp8 attention paths under MTP bursts — upstream issue #44879).

The wrap factory ``_make_wrapped_init(original)`` is exercised against
fake originals; device capability is injected via the module-level
``_SM90_OVERRIDE`` seam so no torch / vllm import is required.
"""
from __future__ import annotations

import importlib
import logging
from types import SimpleNamespace

import pytest


MODULE = (
    "sndr.engines.vllm.patches.attention.turboquant.g4_31_preserve_tq_dtype"
)


@pytest.fixture()
def mod():
    m = importlib.import_module(MODULE)
    original_override = m._SM90_OVERRIDE
    yield m
    m._SM90_OVERRIDE = original_override


def _configs(cache_dtype, scheme):
    cache_config = SimpleNamespace(cache_dtype=cache_dtype)
    quant_config = SimpleNamespace(kv_cache_scheme=scheme)
    return cache_config, quant_config


def _recording_original(mutate_cache_dtype_to=None):
    """Fake Attention.__init__ recording the scheme it observes."""
    seen = {}

    def original(self, *args, **kwargs):
        qc = kwargs.get("quant_config")
        cc = kwargs.get("cache_config")
        seen["scheme"] = getattr(qc, "kv_cache_scheme", "MISSING")
        if mutate_cache_dtype_to is not None and cc is not None:
            cc.cache_dtype = mutate_cache_dtype_to
        return None

    return original, seen


class TestSm90Predicate:
    def test_suppress_fires_on_auto_scheme_sub_sm90(self, mod):
        mod._SM90_OVERRIDE = False  # sub-SM90 (our A5000 SM 8.6)
        assert mod._should_suppress_fp8_auto("auto", {"num_bits": 8}) is True

    def test_no_suppress_on_sm90_plus(self, mod):
        mod._SM90_OVERRIDE = True
        assert mod._should_suppress_fp8_auto("auto", {"num_bits": 8}) is False

    def test_no_suppress_without_scheme(self, mod):
        mod._SM90_OVERRIDE = False
        assert mod._should_suppress_fp8_auto("auto", None) is False

    def test_no_suppress_on_explicit_dtype(self, mod):
        mod._SM90_OVERRIDE = False
        # Explicit operator choice (e.g. fp8_e5m2 via G4_80 profile, or
        # bf16) must win without G4_31 interference — upstream already
        # honors non-auto dtypes on this pin.
        assert mod._should_suppress_fp8_auto("fp8_e5m2", {"a": 1}) is False
        assert mod._should_suppress_fp8_auto("bfloat16", {"a": 1}) is False

    def test_turboquant_arm_predicate_unchanged(self, mod):
        # Original G4_31 arm: turboquant_* + scheme present (capability
        # is irrelevant for the TQ arm).
        mod._SM90_OVERRIDE = True
        assert mod._should_suppress_turboquant(
            "turboquant_4bit_nc", {"a": 1}
        ) is True
        assert mod._should_suppress_turboquant("auto", {"a": 1}) is False
        assert mod._should_suppress_turboquant(
            "turboquant_4bit_nc", None
        ) is False


class TestWrappedInitFp8AutoArm:
    def test_scheme_hidden_from_original_and_restored(self, mod):
        mod._SM90_OVERRIDE = False
        scheme = {"num_bits": 8, "type": "float"}
        cache_config, quant_config = _configs("auto", scheme)
        original, seen = _recording_original()
        wrapped = mod._make_wrapped_init(original)
        wrapped(object(), cache_config=cache_config, quant_config=quant_config)
        # The auto-override path keys on kv_cache_scheme — hiding it for
        # the duration of __init__ suppresses both the local "fp8"
        # rebind and the global cache_config mutation.
        assert seen["scheme"] is None
        assert quant_config.kv_cache_scheme is scheme  # restored
        assert cache_config.cache_dtype == "auto"  # never mutated to fp8

    def test_no_suppress_on_sm90(self, mod):
        mod._SM90_OVERRIDE = True
        scheme = {"num_bits": 8}
        cache_config, quant_config = _configs("auto", scheme)
        original, seen = _recording_original()
        wrapped = mod._make_wrapped_init(original)
        wrapped(object(), cache_config=cache_config, quant_config=quant_config)
        assert seen["scheme"] is scheme  # untouched — upstream behavior

    def test_turboquant_arm_still_works(self, mod):
        # Regression: the original G4_31 arm must keep functioning.
        mod._SM90_OVERRIDE = True  # capability must not gate the TQ arm
        scheme = {"num_bits": 8}
        cache_config, quant_config = _configs("turboquant_4bit_nc", scheme)
        original, seen = _recording_original()
        wrapped = mod._make_wrapped_init(original)
        wrapped(object(), cache_config=cache_config, quant_config=quant_config)
        assert seen["scheme"] is None
        assert quant_config.kv_cache_scheme is scheme

    def test_scheme_restored_when_original_raises(self, mod):
        mod._SM90_OVERRIDE = False
        scheme = {"num_bits": 8}
        cache_config, quant_config = _configs("auto", scheme)

        def boom(self, *args, **kwargs):
            raise RuntimeError("init failed")

        wrapped = mod._make_wrapped_init(boom)
        with pytest.raises(RuntimeError):
            wrapped(
                object(), cache_config=cache_config, quant_config=quant_config
            )
        assert quant_config.kv_cache_scheme is scheme

    def test_arm_fire_logged(self, mod, caplog):
        mod._SM90_OVERRIDE = False
        cache_config, quant_config = _configs("auto", {"num_bits": 8})
        original, _ = _recording_original()
        wrapped = mod._make_wrapped_init(original)
        with caplog.at_level(logging.WARNING, logger=mod.log.name):
            wrapped(
                object(), cache_config=cache_config, quant_config=quant_config
            )
        assert any("G4_31" in r.message and "fp8" in r.message
                   for r in caplog.records)

    def test_late_mutation_invariant_logged(self, mod, caplog):
        # If some OTHER path inside __init__ still mutates
        # cache_config.cache_dtype while the arm fired, the invariant
        # log must flag it (silent late mutation is the #44879 class).
        mod._SM90_OVERRIDE = False
        cache_config, quant_config = _configs("auto", {"num_bits": 8})
        original, _ = _recording_original(mutate_cache_dtype_to="fp8")
        wrapped = mod._make_wrapped_init(original)
        with caplog.at_level(logging.WARNING, logger=mod.log.name):
            wrapped(
                object(), cache_config=cache_config, quant_config=quant_config
            )
        assert any("INVARIANT" in r.message for r in caplog.records)

    def test_no_configs_passthrough(self, mod):
        mod._SM90_OVERRIDE = False
        original, seen = _recording_original()
        wrapped = mod._make_wrapped_init(original)
        wrapped(object())  # no cache_config / quant_config kwargs
        assert seen["scheme"] == "MISSING"
