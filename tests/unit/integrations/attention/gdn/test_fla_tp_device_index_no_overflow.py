# SPDX-License-Identifier: Apache-2.0
"""Tests for FLA TP device-index overflow guard — T2.2 / vllm#40265.

Synthetic shapes that mirror real GDN/FLA TP boundaries:

  - tp_size=8 × num_heads=64 × head_dim=128 × seq_len=320K
    → flat magnitude ~21.5G — well past int32 (≈2.1G).
  - tp_size=2 × num_heads=8 × head_dim=128 × seq_len=32K
    → ~67M, comfortable inside int32.

Tests exercise the API surface and verify behavior at the int32
boundary, the soft-warning threshold (85%), and the int64 hard-fail.
"""
from __future__ import annotations

import pytest

from vllm.sndr_core.kernels.fla_tp_device_index_guard import (
    IndexOverflowReport,
    check_index_overflow,
    index_space_bytes,
    raise_if_int64_overflow,
    warn_if_int32_overflow_imminent,
)


_INT32_MAX = (1 << 31) - 1


class TestIndexSpaceBytes:
    def test_simple_product(self):
        out = index_space_bytes(
            tp_size=2, num_heads=8, head_dim=128, seq_len=4096,
        )
        assert out == 2 * 8 * 128 * 4096

    def test_dtype_bytes_multiplies(self):
        a = index_space_bytes(
            tp_size=2, num_heads=8, head_dim=128, seq_len=4096,
            dtype_bytes=1,
        )
        b = index_space_bytes(
            tp_size=2, num_heads=8, head_dim=128, seq_len=4096,
            dtype_bytes=2,
        )
        assert b == a * 2

    def test_rejects_zero(self):
        with pytest.raises(ValueError):
            index_space_bytes(
                tp_size=0, num_heads=8, head_dim=128, seq_len=4096,
            )

    def test_rejects_negative(self):
        with pytest.raises(ValueError):
            index_space_bytes(
                tp_size=2, num_heads=-1, head_dim=128, seq_len=4096,
            )

    def test_rejects_non_int(self):
        with pytest.raises(TypeError):
            index_space_bytes(
                tp_size=2.5, num_heads=8, head_dim=128, seq_len=4096,  # type: ignore[arg-type]
            )


class TestCheckIndexOverflow:
    def test_safe_shape_fits_int32(self):
        # Modest single-rig shape: tp=2, h=8, d=128, seq=32K → 67 M
        r = check_index_overflow(
            tp_size=2, num_heads=8, head_dim=128, seq_len=32768,
        )
        assert r.fits_int32 is True
        assert r.fits_int64 is True
        assert r.margin_int32_pct < 50

    def test_long_context_at_tp8_overflows_int32(self):
        # Audit §16.7 boundary: tp=8 × h=64 × d=128 × seq=320K = 21.5 G
        r = check_index_overflow(
            tp_size=8, num_heads=64, head_dim=128, seq_len=320 * 1024,
        )
        assert r.fits_int32 is False
        assert r.fits_int64 is True
        assert r.margin_int32_pct > 100

    def test_returns_structured_report(self):
        r = check_index_overflow(
            tp_size=2, num_heads=8, head_dim=128, seq_len=4096,
        )
        assert isinstance(r, IndexOverflowReport)
        assert r.magnitude == 2 * 8 * 128 * 4096
        assert r.margin_int64_pct < 1.0  # tiny share of int64

    def test_at_int32_boundary(self):
        # Construct shape RIGHT at int32_max: 2^31 / 1 element per slot
        r = check_index_overflow(
            tp_size=1, num_heads=1, head_dim=1, seq_len=_INT32_MAX,
        )
        assert r.fits_int32 is True
        # +1 should overflow
        r2 = check_index_overflow(
            tp_size=1, num_heads=1, head_dim=2, seq_len=_INT32_MAX,
        )
        assert r2.fits_int32 is False


class TestRaiseIfInt64Overflow:
    def test_typical_shapes_dont_raise(self):
        raise_if_int64_overflow(
            tp_size=8, num_heads=64, head_dim=128,
            seq_len=320 * 1024,
        )
        # No exception → pass

    def test_extreme_shape_raises(self):
        # Synthesize a shape that overflows int64. int64_max ≈ 9.2e18.
        # Need product to exceed this.
        with pytest.raises(OverflowError):
            raise_if_int64_overflow(
                tp_size=10**6, num_heads=10**6, head_dim=10**6,
                seq_len=10**6,
            )


class TestWarnIfInt32OverflowImminent:
    def test_safe_shape_no_warn(self):
        warn, msg = warn_if_int32_overflow_imminent(
            tp_size=2, num_heads=8, head_dim=128, seq_len=4096,
        )
        assert warn is False
        assert msg == ""

    def test_imminent_overflow_warns(self):
        # Shape close to int32 limit: 90% utilization
        # int32_max ≈ 2.147G; need ~1.93G product.
        # 2 × 4 × 128 × 1.9M = 1.945G → ~90.6%
        warn, msg = warn_if_int32_overflow_imminent(
            tp_size=2, num_heads=4, head_dim=128, seq_len=1_900_000,
        )
        assert warn is True
        assert "int64" in msg

    def test_custom_threshold(self):
        # Same shape, threshold lowered to 50% — should warn
        warn, _ = warn_if_int32_overflow_imminent(
            tp_size=2, num_heads=4, head_dim=128, seq_len=1_900_000,
            threshold_pct=50.0,
        )
        assert warn is True
        # And raised to 99% — should NOT warn at 90% utilization
        warn, _ = warn_if_int32_overflow_imminent(
            tp_size=2, num_heads=4, head_dim=128, seq_len=1_900_000,
            threshold_pct=99.0,
        )
        assert warn is False

    def test_overflow_already_warns(self):
        warn, msg = warn_if_int32_overflow_imminent(
            tp_size=8, num_heads=64, head_dim=128,
            seq_len=320 * 1024,
        )
        assert warn is True
        assert "int32" in msg or "int64" in msg


class TestModuleExports:
    def test_public_api(self):
        from vllm.sndr_core.kernels import fla_tp_device_index_guard as g
        for name in ("IndexOverflowReport", "index_space_bytes",
                     "check_index_overflow", "raise_if_int64_overflow",
                     "warn_if_int32_overflow_imminent"):
            assert hasattr(g, name)
