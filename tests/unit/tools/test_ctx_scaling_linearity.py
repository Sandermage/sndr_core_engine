# SPDX-License-Identifier: Apache-2.0
"""TDD for the context-scaling linearity check in genesis_bench_suite.py.

Operator ask (2026-07-04): the bench suite must verify that decode speed
degrades *linearly* (bounded, smooth) as the prompt/context volume grows —
and flag the two real failure shapes we have seen in the wild:

  * CLIFF — a single tier where TPS collapses (the Cliff-2b class:
    club-3090 #149/#182 — fine at 16K, ~4x slower past the streaming-GDN
    threshold), i.e. one successive-tier drop far beyond the linear trend;
  * DEGRADED — no single cliff, but the endpoint TPS has eroded to a small
    fraction of the small-context TPS (gradual super-linear decay).

The analysis is a pure function over (prompt_tokens, decode_tps) points so
it is unit-testable without a GPU; the live sweep section feeds it real
measurements. Same design as ``evaluate_accept_rate_floor`` (PN380 floor).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def bench_module():
    """Load the bench module via spec_from_file_location since it lives
    outside the package tree (canonical home: sndr/extras/tools/)."""
    repo_root = Path(__file__).resolve().parents[3]
    bench_path = repo_root / "sndr" / "extras" / "tools" / "genesis_bench_suite.py"
    assert bench_path.is_file(), f"bench suite not found at {bench_path}"
    spec = importlib.util.spec_from_file_location("gbs_ctx_scaling", bench_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestHelperContract:
    def test_helper_exists(self, bench_module):
        assert callable(bench_module.analyze_ctx_scaling)

    def test_default_thresholds_exist(self, bench_module):
        assert 0 < bench_module.CTX_SCALING_MAX_STEP_DROP < 1
        assert 0 < bench_module.CTX_SCALING_ENDPOINT_FLOOR < 1


class TestInsufficient:
    def test_fewer_than_three_points(self, bench_module):
        out = bench_module.analyze_ctx_scaling([(1024, 230.0), (8192, 210.0)])
        assert out["classification"] == "INSUFFICIENT"

    def test_empty(self, bench_module):
        out = bench_module.analyze_ctx_scaling([])
        assert out["classification"] == "INSUFFICIENT"


class TestHealthyShapes:
    def test_linear_decay_ok(self, bench_module):
        # Clean linear decay 230 -> 170 over 1K..32K: the healthy shape.
        pts = [(1024, 230.0), (4096, 222.0), (8192, 214.0),
               (16384, 198.0), (32768, 170.0)]
        out = bench_module.analyze_ctx_scaling(pts)
        assert out["classification"] in ("LINEAR_OK", "FLAT_OK")
        # endpoint_ratio is reported rounded to 4 decimals (suite style)
        assert out["endpoint_ratio"] == pytest.approx(170.0 / 230.0, abs=5e-5)

    def test_flat_is_ok_even_with_noise(self, bench_module):
        # Near-flat with noise: linear r2 is meaningless at tiny variance —
        # must NOT false-alarm.
        pts = [(1024, 200.0), (4096, 205.0), (8192, 198.0),
               (16384, 203.0), (32768, 199.0)]
        out = bench_module.analyze_ctx_scaling(pts)
        assert out["classification"] == "FLAT_OK"

    def test_unsorted_input_is_sorted_internally(self, bench_module):
        pts = [(32768, 170.0), (1024, 230.0), (8192, 214.0),
               (4096, 222.0), (16384, 198.0)]
        out = bench_module.analyze_ctx_scaling(pts)
        assert out["classification"] in ("LINEAR_OK", "FLAT_OK")

    def test_live_agentic_shape_passes(self, bench_module):
        # The real 2026-07-04 35B agentic series (prompt_tok, decode_tps):
        # noisy but bounded 218 -> 151 across 1K..39K — must pass.
        pts = [(960, 218.0), (14209, 214.8), (17695, 217.9), (21461, 168.9),
               (25507, 164.8), (29830, 151.4), (34436, 165.9), (39317, 208.7)]
        out = bench_module.analyze_ctx_scaling(pts)
        assert out["classification"] in ("LINEAR_OK", "FLAT_OK")


class TestFailureShapes:
    def test_cliff_detected_at_the_right_tier(self, bench_module):
        # Cliff-2b shape: healthy to 16K, collapse at 32K (200 -> 55).
        pts = [(1024, 230.0), (4096, 225.0), (8192, 215.0),
               (16384, 200.0), (32768, 55.0)]
        out = bench_module.analyze_ctx_scaling(pts)
        assert out["classification"] == "CLIFF"
        cliff_steps = [s for s in out["steps"] if s["is_cliff"]]
        assert len(cliff_steps) == 1
        assert cliff_steps[0]["to_ctx"] == 32768

    def test_gradual_superlinear_collapse_is_degraded(self, bench_module):
        # No single step exceeds the cliff threshold, but the endpoint has
        # eroded to ~30% of the small-context speed.
        pts = [(1024, 230.0), (4096, 175.0), (8192, 133.0),
               (16384, 100.0), (32768, 72.0)]
        out = bench_module.analyze_ctx_scaling(pts)
        assert out["classification"] == "DEGRADED"
        assert out["endpoint_ratio"] < bench_module.CTX_SCALING_ENDPOINT_FLOOR

    def test_cliff_takes_precedence_over_degraded(self, bench_module):
        # Both signatures present -> CLIFF (the more actionable verdict).
        pts = [(1024, 230.0), (4096, 220.0), (8192, 210.0),
               (16384, 80.0), (32768, 60.0)]
        out = bench_module.analyze_ctx_scaling(pts)
        assert out["classification"] == "CLIFF"


class TestReportShape:
    def test_output_carries_fit_and_steps(self, bench_module):
        pts = [(1024, 230.0), (8192, 214.0), (32768, 170.0)]
        out = bench_module.analyze_ctx_scaling(pts)
        assert out["n_points"] == 3
        assert "slope_per_1k_tokens" in out["linear"]
        assert "r2" in out["linear"]
        assert len(out["steps"]) == 2
        for s in out["steps"]:
            assert {"from_ctx", "to_ctx", "drop_pct", "is_cliff"} <= set(s)

    def test_thresholds_overridable(self, bench_module):
        pts = [(1024, 230.0), (8192, 214.0), (32768, 170.0)]
        strict = bench_module.analyze_ctx_scaling(
            pts, endpoint_floor_ratio=0.95)
        assert strict["classification"] == "DEGRADED"
