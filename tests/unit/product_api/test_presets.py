# SPDX-License-Identifier: Apache-2.0
"""Tests for preset catalog Product API used by GUI/web callers."""
from __future__ import annotations

import sys
from dataclasses import asdict, is_dataclass

import pytest

from sndr.product_api.legacy import presets
from sndr.product_api.legacy.presets import (
    PresetListResult,
    PresetRecommendResult,
    PresetRecord,
    UnknownWorkloadError,
)


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    # Count only the builtin catalog — no operator-local presets from a shared
    # $SNDR_HOME — so counts are deterministic regardless of test order.
    monkeypatch.setenv("SNDR_HOME", str(tmp_path))


def test_list_presets_returns_catalog_records():
    result = presets.list_presets()

    # chat-K3 promotion session (2026-06-01): +2 preset aliases
    # (prod-gemma4-31b-tq-mtp-chat-k3 + prod-gemma4-26b-mtp-chat-k3
    # promoted from profile-only to operator-facing presets) → 21 → 23.
    # Gemma-31B kv-auto profile (2026-06-19, ea33b8e0): +1 preset → 24.
    # Canonical-config reorg (2026-06): 24 → 14. Archived 11 test/
    # experimental presets to presets/_archive/ (one canonical ⭐ + at most
    # one functional sibling per served model) and added the new
    # prod-diffusiongemma-tp2 preset (24 - 11 + 1 = 14).
    assert isinstance(result, PresetListResult)
    assert result.total == 14
    assert result.matched == 14
    assert result.load_errors == ()
    assert all(isinstance(row, PresetRecord) for row in result.presets)

    # Every builtin preset now carries a card (bench-and-update annotated the
    # last unannotated ones); the catalog has no unannotated presets.
    assert all(row.has_card for row in result.presets)


def test_list_presets_filters_status_and_family():
    by_status = presets.list_presets(status="production_candidate")
    by_family = presets.list_presets(family="qwen3_6_35b_a3b_fp8")

    # chat-K3 promotion (2026-06-01): the two new presets ship as
    # production_candidate, lifting the production_candidate-filter
    # count by 2 (14 → 16). Gemma-31B kv-auto (2026-06-19) +1 → 17.
    # Canonical-config reorg (2026-06): archived presets dropped the
    # production_candidate count to 8 (the kept canonical+sibling prod
    # presets: 35b balanced+multiconc, 27b k8v4+multiconc, 26b default+
    # multiconc, 31b kvauto-chat+tq-default; the new diffusiongemma preset
    # ships as experimental, not production_candidate). The 35B family
    # filter is unchanged at 2 (both 35B presets kept).
    assert by_status.matched == 8
    assert by_family.matched == 2
    assert {row.id for row in by_family.presets} == {
        "prod-qwen3.6-35b-balanced",
        "prod-qwen3.6-35b-multiconc",
    }


def test_get_preset_and_drill_field_are_json_safe():
    record = presets.get_preset("prod-qwen3.6-35b-balanced")

    assert isinstance(record, PresetRecord)
    assert record.has_card is True
    assert record.card["status"] == "production_candidate"
    assert presets.drill_field(asdict(record), "card.routing_family") == (
        "qwen3_6_35b_a3b_fp8"
    )
    assert "35b_v11_wave9.json" in presets.drill_field(
        asdict(record),
        "card.evidence_refs.0.path",
    )


def test_drill_field_reports_invalid_paths():
    record = asdict(presets.get_preset("prod-qwen3.6-35b-balanced"))

    with pytest.raises(KeyError, match="nonexistent"):
        presets.drill_field(record, "card.nonexistent")
    with pytest.raises(KeyError, match="out of range"):
        presets.drill_field(record, "card.evidence_refs.999.path")


def test_explain_preset_returns_composed_runtime_summary():
    result = presets.explain_preset("prod-qwen3.6-35b-multiconc")

    assert is_dataclass(result)
    payload = asdict(result)
    assert payload["id"] == "prod-qwen3.6-35b-multiconc"
    assert payload["card"]["status"] == "production_candidate"
    assert payload["composed"]["max_num_seqs"] == 8
    assert "enabled_patches_count" in payload["composed"]


# ─── B3: explain full story — projected fit + measured bench ──────────────────

def test_explain_preset_has_projected_fit_and_measured_bench_keys():
    """The one-slug full story: config + card + projected-fit + measured-bench."""
    payload = asdict(presets.explain_preset("prod-qwen3.6-35b-balanced"))
    assert "projected_fit" in payload
    assert "measured_bench" in payload


def test_explain_preset_projected_fit_from_explicit_vram():
    """An explicit vram_gib (the GUI live-free / --card path) drives a byte-level
    PASS/TIGHT/FAIL verdict against that VRAM basis."""
    result = presets.explain_preset("prod-qwen3.6-35b-balanced", vram_gib=24.0)
    pf = result.projected_fit
    assert pf is not None
    assert pf["verdict"] in ("PASS", "TIGHT", "FAIL")
    assert pf["vram_gib_per_card"] == 24.0
    # 35B at 24 GiB/card is not a comfortable PASS — verifies the projector is
    # actually computing (not a stub).
    assert pf["verdict"] in ("TIGHT", "FAIL")


def test_explain_preset_lower_vram_is_tighter_or_worse():
    """A smaller card never yields a BETTER verdict than a larger one — the
    projected fit is monotone in VRAM (sanity that live-VRAM threading is real)."""
    rank = {"PASS": 0, "TIGHT": 1, "FAIL": 2}
    big = presets.explain_preset(
        "prod-qwen3.6-35b-balanced", vram_gib=80.0).projected_fit
    small = presets.explain_preset(
        "prod-qwen3.6-35b-balanced", vram_gib=16.0).projected_fit
    assert big is not None and small is not None
    assert rank[small["verdict"]] >= rank[big["verdict"]]


def test_measured_bench_summary_flags_placeholder():
    """A primary_metric value of 0.0 is a PENDING placeholder, not a measured
    result — flagged so the operator does not read 0 TPS as real."""
    class _PM:
        kind = "agg_TPS"
        value = 0.0
        source = "external://pending/x"
        measured_at = "2026-06-19"

    class _Card:
        primary_metric = _PM()
        evidence_refs = ()

    mb = presets.measured_bench_summary(_Card())
    assert mb is not None
    assert mb["pending"] is True


def test_projected_fit_summary_none_without_shape_or_rig():
    """A model with no byte-level shape yields None (explain still works, the
    piece is just absent) — never crashes."""
    class _Caps:
        shape = None

    class _Model:
        capabilities = _Caps()

    class _PD:
        model = "no-shape-model"
        hardware = "nope"

    # No shape -> None regardless of vram.
    assert presets.projected_fit_summary(
        "x", _PD(), cfg=None, vram_gib=24.0) is None


def test_recommend_presets_honors_allow_deny_and_ranking():
    result = presets.recommend_presets(
        workload="free_chat",
        hardware="a5000-2x-24gbvram-16cpu-128gbram",
        concurrency=8,
        top=5,
    )

    assert isinstance(result, PresetRecommendResult)
    ids = [row.id for row in result.results]
    assert "prod-qwen3.6-35b-multiconc" in ids
    assert "prod-gemma4-26b-mtp-k4" not in ids
    assert "prod-gemma4-26b-multiconc" not in ids
    assert [row.rank for row in result.results] == list(
        range(1, len(result.results) + 1)
    )
    assert result.total_candidates >= result.total_matches


def test_recommend_presets_rejects_unknown_workload():
    with pytest.raises(UnknownWorkloadError):
        presets.recommend_presets(workload="freechat")


def test_recommend_presets_accepts_custom_workload_with_no_matches():
    result = presets.recommend_presets(workload="custom:my-special-task")

    assert result.results == ()
    assert result.total_matches == 0


def test_presets_product_api_does_not_import_torch():
    if "torch" in sys.modules:
        pytest.skip("torch already imported by another test/runtime")

    presets.list_presets(status="production_candidate")
    presets.recommend_presets(workload="structured_json.short", top=2)

    assert "torch" not in sys.modules
