# SPDX-License-Identifier: Apache-2.0
"""TDD for GENESIS_PN59_O_MAX_T cap on GdnScratchPool.acquire_o_output.

Phase A of MEMORY_DEEP_PLAN architectural pass (Sander 2026-05-07):
the o_output buffer was previously the largest unbounded grower in the
Genesis stack — T_binned = next_pow2(max_model_len) at long ctx could
quietly take up to ~768 MiB persistent on 1×24GB single-card configs.

The cap is opt-in (env var; default 0 = unlimited preserves prior
behavior). When set, requests whose binned-T exceeds the cap raise
RuntimeError; the caller's existing try/except in
streaming_gdn_driver._streaming_path then falls back to
`torch.empty_like(v)` for that one request — pool stays bounded for
typical (short) requests, long-ctx requests pay one transient alloc.
"""
from __future__ import annotations

import pytest
import torch

from sndr.engines.vllm.kernels_legacy import gdn_scratch_pool as m
from sndr.engines.vllm.kernels_legacy.gdn_scratch_pool import GdnScratchPool


@pytest.fixture(autouse=True)
def _reset_cache_and_registry(monkeypatch):
    """Clear env cache + O_REGISTRY between tests so env changes take effect."""
    monkeypatch.delenv(m._ENV_O_MAX_T, raising=False)
    m._reset_o_max_t_cache()
    GdnScratchPool._O_REGISTRY.clear()
    yield
    m._reset_o_max_t_cache()
    GdnScratchPool._O_REGISTRY.clear()


def _device():
    """Test on CPU (no GPU required) — pool logic is platform-agnostic."""
    return torch.device("cpu")


# ─── Default: unlimited (zero-risk pre-2026-05-07 behavior) ───────────


class TestDefaultUnlimited:
    def test_unset_env_returns_zero(self):
        assert m._get_o_max_t() == 0

    def test_invalid_env_returns_zero(self, monkeypatch):
        monkeypatch.setenv(m._ENV_O_MAX_T, "abc-not-int")
        m._reset_o_max_t_cache()
        assert m._get_o_max_t() == 0

    def test_negative_env_clamped_to_zero(self, monkeypatch):
        monkeypatch.setenv(m._ENV_O_MAX_T, "-100")
        m._reset_o_max_t_cache()
        assert m._get_o_max_t() == 0

    def test_large_T_succeeds_when_unlimited(self):
        # T=131072 → T_binned=131072 — no cap, succeeds
        buf = GdnScratchPool.acquire_o_output(
            B=1, T=131072, H=24, V=128,
            dtype=torch.float16, device=_device(),
        )
        assert buf.shape == (1, 131072, 24, 128)


# ─── Cap enforcement ──────────────────────────────────────────────────


class TestCapEnforcement:
    def test_cap_set_reads_int(self, monkeypatch):
        monkeypatch.setenv(m._ENV_O_MAX_T, "65536")
        m._reset_o_max_t_cache()
        assert m._get_o_max_t() == 65536

    def test_cap_with_whitespace_parsed(self, monkeypatch):
        monkeypatch.setenv(m._ENV_O_MAX_T, "  65536  ")
        m._reset_o_max_t_cache()
        assert m._get_o_max_t() == 65536

    def test_T_under_cap_succeeds(self, monkeypatch):
        monkeypatch.setenv(m._ENV_O_MAX_T, "65536")
        m._reset_o_max_t_cache()
        # T=4096 → T_binned=4096 → under cap → succeeds
        buf = GdnScratchPool.acquire_o_output(
            B=1, T=4096, H=24, V=128,
            dtype=torch.float16, device=_device(),
        )
        assert buf.shape == (1, 4096, 24, 128)

    def test_T_at_cap_succeeds(self, monkeypatch):
        monkeypatch.setenv(m._ENV_O_MAX_T, "65536")
        m._reset_o_max_t_cache()
        # T=65536 → T_binned=65536 → equals cap (NOT > cap) → succeeds
        buf = GdnScratchPool.acquire_o_output(
            B=1, T=65536, H=24, V=128,
            dtype=torch.float16, device=_device(),
        )
        assert buf.shape == (1, 65536, 24, 128)

    def test_T_over_cap_raises(self, monkeypatch):
        monkeypatch.setenv(m._ENV_O_MAX_T, "65536")
        m._reset_o_max_t_cache()
        # T=131072 → T_binned=131072 → exceeds cap → raises
        with pytest.raises(RuntimeError, match="GENESIS_PN59_O_MAX_T=65536"):
            GdnScratchPool.acquire_o_output(
                B=1, T=131072, H=24, V=128,
                dtype=torch.float16, device=_device(),
            )

    def test_T_just_over_cap_raises(self, monkeypatch):
        monkeypatch.setenv(m._ENV_O_MAX_T, "8192")
        m._reset_o_max_t_cache()
        # T=8193 → T_binned=16384 (next_pow2) > cap=8192 → raises
        with pytest.raises(RuntimeError, match="exceeds"):
            GdnScratchPool.acquire_o_output(
                B=1, T=8193, H=24, V=128,
                dtype=torch.float16, device=_device(),
            )

    def test_pool_not_polluted_on_raise(self, monkeypatch):
        """When cap-bypass raises, NO entry should be added to _O_REGISTRY.

        This is the load-bearing guarantee: the cap stops persistent
        accumulation, so a poisoned shape from one over-cap request
        doesn't outlive the request.
        """
        monkeypatch.setenv(m._ENV_O_MAX_T, "8192")
        m._reset_o_max_t_cache()
        with pytest.raises(RuntimeError):
            GdnScratchPool.acquire_o_output(
                B=1, T=131072, H=24, V=128,
                dtype=torch.float16, device=_device(),
            )
        assert len(GdnScratchPool._O_REGISTRY) == 0


# ─── Composition with existing pool semantics ────────────────────────


class TestComposition:
    def test_cap_does_not_affect_repeat_acquire(self, monkeypatch):
        """A safe-shape acquire under cap caches; second call returns view."""
        monkeypatch.setenv(m._ENV_O_MAX_T, "65536")
        m._reset_o_max_t_cache()
        buf1 = GdnScratchPool.acquire_o_output(
            B=1, T=4096, H=24, V=128,
            dtype=torch.float16, device=_device(),
        )
        buf2 = GdnScratchPool.acquire_o_output(
            B=1, T=4096, H=24, V=128,
            dtype=torch.float16, device=_device(),
        )
        # Same underlying storage — pool reuse works
        assert buf1.data_ptr() == buf2.data_ptr()
        assert len(GdnScratchPool._O_REGISTRY) == 1

    def test_T_binning_min_512_unchanged(self, monkeypatch):
        """Cap doesn't break the min-512 floor for very short prompts."""
        monkeypatch.setenv(m._ENV_O_MAX_T, "65536")
        m._reset_o_max_t_cache()
        # T=4 → T_binned should still bin up to 512 (existing behavior)
        buf = GdnScratchPool.acquire_o_output(
            B=1, T=4, H=24, V=128,
            dtype=torch.float16, device=_device(),
        )
        assert buf.shape == (1, 4, 24, 128)
        # Internal storage padded to 512
        cached = next(iter(GdnScratchPool._O_REGISTRY.values()))
        assert cached.shape[1] == 512
