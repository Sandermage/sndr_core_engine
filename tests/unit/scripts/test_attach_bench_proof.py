# SPDX-License-Identifier: Apache-2.0
"""Tests for `scripts/attach_bench_proof.py` — bench attachment helper.

Contract:

  1. _extract_metric finds value at top-level OR inside {value/mean/median} envelope.
  2. _collect_bench_metrics flattens via subsections (decode_bench, aggregate,
     summary, stats) and applies _BENCH_METRIC_FIELDS map.
  3. _compute_deltas yields *_delta_pct keys when both sides have the metric;
     division-by-zero guarded.
  4. _proof_artefacts_for returns sorted glob of `{patch_id}__*.json`.
  5. main exits 1 on missing bench file, unparseable JSON, or unresolvable preset.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "attach_bench_proof.py"


def _import_script():
    name = "_attach_bench_proof_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ─── _extract_metric ──────────────────────────────────────────────────


class TestExtractMetric:
    def test_top_level_number(self):
        mod = _import_script()
        result = mod._extract_metric({"wall_TPS": 211.35}, ("wall_TPS",))
        assert result == 211.35

    def test_envelope_with_mean(self):
        mod = _import_script()
        result = mod._extract_metric(
            {"wall_TPS": {"mean": 130.7, "stdev": 4.3}},
            ("wall_TPS",),
        )
        assert result == 130.7

    def test_envelope_with_value(self):
        mod = _import_script()
        result = mod._extract_metric(
            {"ttft_ms": {"value": 90.0, "unit": "ms"}},
            ("ttft_ms",),
        )
        assert result == 90.0

    def test_envelope_with_median(self):
        mod = _import_script()
        result = mod._extract_metric(
            {"decode_TPOT_ms": {"median": 4.5}},
            ("decode_TPOT_ms",),
        )
        assert result == 4.5

    def test_first_candidate_wins(self):
        """Candidate keys are tried in order — first match returned."""
        mod = _import_script()
        result = mod._extract_metric(
            {"alt": 50.0, "wall_TPS": 211.0},
            ("wall_TPS", "alt"),
        )
        assert result == 211.0

    def test_missing_returns_none(self):
        mod = _import_script()
        result = mod._extract_metric({"unrelated": 1}, ("wall_TPS",))
        assert result is None

    def test_int_coerced_to_float(self):
        mod = _import_script()
        result = mod._extract_metric({"wall_TPS": 211}, ("wall_TPS",))
        assert isinstance(result, float)


# ─── _collect_bench_metrics ───────────────────────────────────────────


class TestCollectBenchMetrics:
    def test_top_level_metrics(self):
        mod = _import_script()
        bench = {
            "wall_TPS": 211.35,
            "decode_TPOT_ms": 4.5,
            "ttft_ms": 90.0,
            "cv_pct": 5.5,
        }
        result = mod._collect_bench_metrics(bench)
        assert result["median_tps"] == 211.35
        assert result["decode_tpot_ms"] == 4.5
        assert result["ttft_ms"] == 90.0
        assert result["cv_pct"] == 5.5

    def test_nested_subsection_resolves(self):
        mod = _import_script()
        bench = {
            "decode_bench": {
                "wall_TPS": {"mean": 215.0},
                "ttft_ms": 100.0,
            }
        }
        result = mod._collect_bench_metrics(bench)
        assert result.get("median_tps") == 215.0
        assert result.get("ttft_ms") == 100.0

    def test_top_level_wins_over_subsection(self):
        """Top-level key resolved first; subsection only fills gaps."""
        mod = _import_script()
        bench = {
            "wall_TPS": 211.35,
            "decode_bench": {"wall_TPS": 999.0},
        }
        result = mod._collect_bench_metrics(bench)
        assert result["median_tps"] == 211.35

    def test_empty_bench_yields_empty(self):
        mod = _import_script()
        assert mod._collect_bench_metrics({}) == {}


# ─── _compute_deltas ──────────────────────────────────────────────────


class TestComputeDeltas:
    def test_positive_delta(self):
        mod = _import_script()
        deltas = mod._compute_deltas(
            current={"median_tps": 220.0},
            baseline={"median_tps": 200.0},
        )
        assert deltas["median_tps_delta_pct"] == pytest.approx(10.0)

    def test_negative_delta(self):
        mod = _import_script()
        deltas = mod._compute_deltas(
            current={"decode_tpot_ms": 5.0},
            baseline={"decode_tpot_ms": 4.0},
        )
        assert deltas["decode_tpot_delta_pct"] == pytest.approx(25.0)

    def test_zero_baseline_skipped(self):
        """Division by zero guard — skip the metric instead of raising."""
        mod = _import_script()
        deltas = mod._compute_deltas(
            current={"median_tps": 100.0},
            baseline={"median_tps": 0},
        )
        assert "median_tps_delta_pct" not in deltas

    def test_missing_current_skipped(self):
        mod = _import_script()
        deltas = mod._compute_deltas(
            current={},
            baseline={"median_tps": 200.0},
        )
        assert deltas == {}

    def test_missing_baseline_skipped(self):
        mod = _import_script()
        deltas = mod._compute_deltas(
            current={"median_tps": 200.0},
            baseline={},
        )
        assert deltas == {}

    def test_only_known_delta_metrics_emitted(self):
        """cv_pct + tool_call_score have NO delta-pct counterparts."""
        mod = _import_script()
        deltas = mod._compute_deltas(
            current={"cv_pct": 5.5, "tool_call_score": 7.0},
            baseline={"cv_pct": 4.0, "tool_call_score": 6.0},
        )
        assert deltas == {}


# ─── _proof_artefacts_for ─────────────────────────────────────────────


class TestProofArtefactsFor:
    def test_missing_dir_returns_empty(self, tmp_path):
        mod = _import_script()
        assert mod._proof_artefacts_for("PN204", tmp_path / "nope") == []

    def test_matches_glob(self, tmp_path):
        mod = _import_script()
        d = tmp_path / "proof"
        d.mkdir()
        (d / "PN204__staticonly.json").write_text("{}")
        (d / "PN204__dev371.json").write_text("{}")
        (d / "PN17__staticonly.json").write_text("{}")  # different patch
        results = mod._proof_artefacts_for("PN204", d)
        assert len(results) == 2
        for r in results:
            assert r.name.startswith("PN204__")

    def test_results_sorted(self, tmp_path):
        mod = _import_script()
        d = tmp_path / "proof"
        d.mkdir()
        (d / "PN1__zzz.json").write_text("{}")
        (d / "PN1__aaa.json").write_text("{}")
        (d / "PN1__mmm.json").write_text("{}")
        results = mod._proof_artefacts_for("PN1", d)
        names = [r.name for r in results]
        assert names == sorted(names)


# ─── main exit codes ──────────────────────────────────────────────────


class TestMainExitCodes:
    def test_missing_bench_file_returns_1(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH),
             "--bench", str(tmp_path / "nonexistent.json"),
             "--preset", "any"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 1
        assert "not found" in result.stderr

    def test_unparseable_bench_returns_1(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json")
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH),
             "--bench", str(bad),
             "--preset", "any"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 1
        assert "failed to parse" in result.stderr
