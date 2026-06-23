"""TASK 1 — per-PATCH upstream-merge tri-state recorded IN the manifest.

The operator's explicit ask: stop silently dropping upstream-merged anchors into
the rej set. Aggregate a patch's sub-patches into not_merged / fully_merged /
partially_merged, record it in to_engine_manifest's per-patch entry, validate it
in the engine schema, and (for partial) record which sub-anchors are merged so
the apply/operator knows which parts to skip.

Synthetic targets + pristine — no vLLM on the host needed.
"""
from sndr.engines.vllm.anchor_discovery import AnchorTarget
from sndr.engines.vllm.anchor_manifest_gen import (
    MERGE_FULLY_MERGED,
    MERGE_NOT_MERGED,
    MERGE_PARTIALLY_MERGED,
    aggregate_merge_status,
    build_pin_manifest,
    to_engine_manifest,
)
from sndr.engines.vllm.wiring.anchor_manifest import validate_manifest_schema


def _patch_entry(manifest, rel, pid):
    return manifest["files"][rel]["patches"][pid]


# ─── aggregate_merge_status unit (the tri-state core) ──────────────────


def test_aggregate_none_merged_is_not_merged():
    assert aggregate_merge_status(3, set()) == MERGE_NOT_MERGED


def test_aggregate_all_merged_is_fully_merged():
    assert aggregate_merge_status(2, {"a", "b"}) == MERGE_FULLY_MERGED


def test_aggregate_some_merged_is_partial():
    assert aggregate_merge_status(3, {"a"}) == MERGE_PARTIALLY_MERGED


def test_aggregate_zero_subs_is_not_merged():
    # defensive: no applicable subs -> not_merged (never fully on an empty set)
    assert aggregate_merge_status(0, set()) == MERGE_NOT_MERGED


# ─── not_merged: ordinary patch, all anchors live ──────────────────────


def test_not_merged_records_status_and_keeps_anchors():
    targets = [
        AnchorTarget("PNM", "s1", "f.py", "ANCHOR_1", "R1", True),
        AnchorTarget("PNM", "s2", "f.py", "ANCHOR_2", "R2", True),
    ]
    pristine = {"f.py": "x ANCHOR_1 y ANCHOR_2 z"}
    res = build_pin_manifest(lambda rel: pristine.get(rel), targets)
    assert res.merge["PNM"]["merge_status"] == MERGE_NOT_MERGED
    m = to_engine_manifest(res, lambda rel: pristine.get(rel),
                           vllm_pin="0.23.1", genesis_pin="v12")
    pe = _patch_entry(m, "f.py", "PNM")
    assert pe["merge_status"] == MERGE_NOT_MERGED
    assert set(pe["anchors"]) == {"s1", "s2"}      # both anchors still spliced
    assert "merged_subs" not in pe                  # only on partial
    assert validate_manifest_schema(m) == []


# ─── fully_merged: ALL subs upstreamed -> visible, zero anchors left ────


def test_fully_merged_recorded_even_with_no_anchors():
    targets = [
        AnchorTarget("PFM", "s1", "f.py", "A1", "R1", True,
                     upstream_merged_markers=("def native_fix_one",)),
        AnchorTarget("PFM", "s2", "f.py", "A2", "R2", True,
                     upstream_merged_markers=("def native_fix_two",)),
    ]
    # BOTH merge markers present in the pristine source -> fully upstreamed
    pristine = {"f.py": "A1 A2 def native_fix_one def native_fix_two"}
    res = build_pin_manifest(lambda rel: pristine.get(rel), targets)
    assert not res.ok                                # nothing left to splice
    assert res.merge["PFM"]["merge_status"] == MERGE_FULLY_MERGED

    m = to_engine_manifest(res, lambda rel: pristine.get(rel),
                           vllm_pin="0.23.1", genesis_pin="v12")
    # The patch is VISIBLE (not silently dropped) so a pin-switch SEES it.
    pe = _patch_entry(m, "f.py", "PFM")
    assert pe["merge_status"] == MERGE_FULLY_MERGED
    assert pe["anchors"] == {}                       # zero anchors, still recorded
    assert "merged_subs" not in pe                   # only on partial
    assert validate_manifest_schema(m) == []


# ─── partially_merged: SOME subs upstreamed -> remaining anchors kept ───


def test_partially_merged_keeps_remaining_anchors_and_lists_merged_subs():
    targets = [
        AnchorTarget("PPM", "s_merged", "f.py", "A_MERGED", "R1", True,
                     upstream_merged_markers=("def native_fix",)),
        AnchorTarget("PPM", "s_live", "f.py", "A_LIVE", "R2", True),
    ]
    # only the first sub's marker fires; A_LIVE is still ours to apply
    pristine = {"f.py": "A_MERGED A_LIVE def native_fix"}
    res = build_pin_manifest(lambda rel: pristine.get(rel), targets)
    assert res.merge["PPM"]["merge_status"] == MERGE_PARTIALLY_MERGED
    assert res.merge["PPM"]["merged_subs"] == ["s_merged"]
    # the non-merged sub is still classified ok (kept for the manifest)
    assert "PPM::s_live" in res.ok
    assert "PPM::s_merged" not in res.ok

    m = to_engine_manifest(res, lambda rel: pristine.get(rel),
                           vllm_pin="0.23.1", genesis_pin="v12")
    pe = _patch_entry(m, "f.py", "PPM")
    assert pe["merge_status"] == MERGE_PARTIALLY_MERGED
    assert pe["merged_subs"] == ["s_merged"]         # operator skips this one
    assert set(pe["anchors"]) == {"s_live"}          # still splices the rest
    assert validate_manifest_schema(m) == []


def test_partial_via_caller_is_upstream_merged_hook():
    # the caller-supplied hook can flag merges too (joins target markers)
    targets = [
        AnchorTarget("PH", "s1", "f.py", "A1", "R1", True),
        AnchorTarget("PH", "s2", "f.py", "A2", "R2", True),
    ]
    pristine = {"f.py": "A1 A2"}
    res = build_pin_manifest(
        lambda rel: pristine.get(rel), targets,
        is_upstream_merged=lambda t, content: t.sub == "s1",
    )
    assert res.merge["PH"]["merge_status"] == MERGE_PARTIALLY_MERGED
    assert res.merge["PH"]["merged_subs"] == ["s1"]


# ─── schema validation: pass + fail ────────────────────────────────────


def test_schema_rejects_invalid_merge_status_value():
    m = {
        "manifest_version": 1,
        "generated_at": "2026-01-01T00:00:00Z",
        "pins": {"vllm": "x", "genesis": "y"},
        "files": {
            "f.py": {
                "md5_pristine": "0" * 32,
                "size_bytes": 10,
                "patches": {
                    "PBAD": {"merge_status": "bananas", "anchors": {}},
                },
            }
        },
    }
    errors = validate_manifest_schema(m)
    assert any("merge_status" in e and "bananas" in e for e in errors), errors


def test_schema_requires_merged_subs_only_for_partial():
    # merged_subs present but status is not partial -> error
    m = {
        "manifest_version": 1,
        "generated_at": "2026-01-01T00:00:00Z",
        "pins": {"vllm": "x", "genesis": "y"},
        "files": {
            "f.py": {
                "md5_pristine": "0" * 32,
                "size_bytes": 10,
                "patches": {
                    "P": {"merge_status": "not_merged",
                          "merged_subs": ["s1"], "anchors": {}},
                },
            }
        },
    }
    errors = validate_manifest_schema(m)
    assert any("merged_subs" in e for e in errors), errors


def test_schema_requires_nonempty_merged_subs_for_partial():
    m = {
        "manifest_version": 1,
        "generated_at": "2026-01-01T00:00:00Z",
        "pins": {"vllm": "x", "genesis": "y"},
        "files": {
            "f.py": {
                "md5_pristine": "0" * 32,
                "size_bytes": 10,
                "patches": {
                    "P": {"merge_status": "partially_merged",
                          "merged_subs": [], "anchors": {}},
                },
            }
        },
    }
    errors = validate_manifest_schema(m)
    assert any("merged_subs" in e for e in errors), errors


def test_schema_tolerates_absent_merge_status_backcompat():
    # pin manifests built before TASK 1 have no merge_status -> still valid
    # (must not regress the apply fast-path on the live committed pin).
    m = {
        "manifest_version": 1,
        "generated_at": "2026-01-01T00:00:00Z",
        "pins": {"vllm": "x", "genesis": "y"},
        "files": {
            "f.py": {
                "md5_pristine": "0" * 32,
                "size_bytes": 10,
                "patches": {
                    "P": {"anchors": {}},  # no merge_status key at all
                },
            }
        },
    }
    assert validate_manifest_schema(m) == []
