"""FINDING #6 — patcher-level upstream-drift markers must classify as merged.

Root cause: two independent upstream-merge marker mechanisms exist —
``TextPatch.upstream_merged_markers`` (SUB-patch level) and
``TextPatcher.upstream_drift_markers`` (whole-PATCHER level). The manifest
pipeline carried ONLY the sub-patch field, so the 169/174 patches that declare
their marker at PATCHER level (PN387, G4_26, the PN12/PN25/PN30 family) fell
through to STATUS_ANCHOR_DRIFT once upstream merged the fix — underreporting
``upstream_merged`` and polluting the genuine-drift re-anchor backlog.

The fix carries ``patcher_drift_markers`` into ``AnchorTarget`` and checks it in
``build_pin_manifest`` against the PRISTINE source. A patcher-level marker fires
identically for every sub of the patch (same src), so every sub routes to
STATUS_UPSTREAM_MERGED and the patch aggregates to FULLY_MERGED (never partial)
— matching Layer-3 whole-patch semantics.

Synthetic pristine + targets — no vLLM on the host needed.
"""
from sndr.engines.vllm.anchor_discovery import AnchorTarget
from sndr.engines.vllm.anchor_manifest_gen import (
    MERGE_FULLY_MERGED,
    MERGE_NOT_MERGED,
    MERGE_PARTIALLY_MERGED,
    STATUS_ANCHOR_DRIFT,
    STATUS_UPSTREAM_MERGED,
    build_pin_manifest,
    to_engine_manifest,
)
from sndr.engines.vllm.wiring.anchor_manifest import validate_manifest_schema


def _rej_status(res, key):
    for e in res.rej:
        if e["key"] == key:
            return e["status"]
    return None


# ─── the classifier contract: patcher-level marker -> upstream_merged ──────


def test_patcher_level_marker_classifies_upstream_merged():
    # single-sub patch; pristine has the patcher-level marker but the anchor is
    # GONE (upstream merged the fix). Must classify upstream_merged (NOT
    # anchor_drift), aggregate FULLY_MERGED, and NOT enter the ok set.
    targets = [
        AnchorTarget("PPL", "s1", "f.py", "OUR_ANCHOR", "R1", True,
                     patcher_drift_markers=("def native_guard",)),
    ]
    pristine = {"f.py": "x def native_guard y"}  # marker present, anchor absent
    res = build_pin_manifest(pristine.get, targets)
    assert "PPL::s1" not in res.ok
    assert _rej_status(res, "PPL::s1") == STATUS_UPSTREAM_MERGED
    assert _rej_status(res, "PPL::s1") != STATUS_ANCHOR_DRIFT
    assert res.merge["PPL"]["merge_status"] == MERGE_FULLY_MERGED


def test_patcher_level_marker_all_subs_fully_merged():
    # multi-sub patch; the single patcher-level marker present -> ALL subs are
    # upstream_merged -> FULLY_MERGED (never partial — a patcher-level marker
    # fires for the whole patch, so it can't be a partial merge).
    targets = [
        AnchorTarget("PML", "s1", "f.py", "A1", "R1", True,
                     patcher_drift_markers=("MERGED_MARKER",)),
        AnchorTarget("PML", "s2", "f.py", "A2", "R2", True,
                     patcher_drift_markers=("MERGED_MARKER",)),
    ]
    pristine = {"f.py": "A1 A2 MERGED_MARKER"}  # marker present; anchors also here
    res = build_pin_manifest(pristine.get, targets)
    assert not res.ok  # patcher-level merge wins over the still-present anchors
    assert _rej_status(res, "PML::s1") == STATUS_UPSTREAM_MERGED
    assert _rej_status(res, "PML::s2") == STATUS_UPSTREAM_MERGED
    assert res.merge["PML"]["merge_status"] == MERGE_FULLY_MERGED
    assert "merged_subs" not in res.merge["PML"]  # fully, not partial


def test_patcher_level_marker_absent_stays_active():
    # marker ABSENT, anchor present -> ok / not_merged (no over-fire).
    targets = [
        AnchorTarget("PAC", "s1", "f.py", "LIVE_ANCHOR", "R1", True,
                     patcher_drift_markers=("def native_guard",)),
    ]
    pristine = {"f.py": "x LIVE_ANCHOR y"}  # marker NOT present, anchor present
    res = build_pin_manifest(pristine.get, targets)
    assert "PAC::s1" in res.ok
    assert res.merge["PAC"]["merge_status"] == MERGE_NOT_MERGED


def test_self_banner_marker_not_fired_against_pristine():
    # self-collision safety: a Genesis self-banner marker (e.g. "[Genesis PN387")
    # is ABSENT from pristine (never-patched) source, so it must not false-fire.
    targets = [
        AnchorTarget("PSB", "s1", "f.py", "LIVE_ANCHOR", "R1", True,
                     patcher_drift_markers=("[Genesis PN387",)),
    ]
    pristine = {"f.py": "clean upstream code LIVE_ANCHOR here"}
    res = build_pin_manifest(pristine.get, targets)
    assert "PSB::s1" in res.ok  # not falsely merged
    assert res.merge["PSB"]["merge_status"] == MERGE_NOT_MERGED


def test_patcher_and_sub_markers_combine_to_partial():
    # a per-SUB marker on one sub, NO patcher marker -> partial (guards the
    # existing per-sub path still works alongside the new patcher-level one).
    targets = [
        AnchorTarget("PCM", "s_merged", "f.py", "A_MERGED", "R1", True,
                     upstream_merged_markers=("def native_fix",)),
        AnchorTarget("PCM", "s_live", "f.py", "A_LIVE", "R2", True),
    ]
    pristine = {"f.py": "A_MERGED A_LIVE def native_fix"}
    res = build_pin_manifest(pristine.get, targets)
    assert res.merge["PCM"]["merge_status"] == MERGE_PARTIALLY_MERGED
    assert res.merge["PCM"]["merged_subs"] == ["s_merged"]
    assert "PCM::s_live" in res.ok


def test_patcher_level_fully_merged_visible_in_engine_manifest():
    # to_engine_manifest round-trip: a patcher-level fully_merged patch is
    # VISIBLE with empty anchors + merge_status fully_merged + schema valid.
    targets = [
        AnchorTarget("PVM", "s1", "f.py", "GONE_ANCHOR", "R1", True,
                     patcher_drift_markers=("def native_guard",)),
    ]
    pristine = {"f.py": "def native_guard only"}
    res = build_pin_manifest(pristine.get, targets)
    m = to_engine_manifest(res, pristine.get,
                           vllm_pin="0.23.1", genesis_pin="v12")
    pe = m["files"]["f.py"]["patches"]["PVM"]
    assert pe["merge_status"] == MERGE_FULLY_MERGED
    assert pe["anchors"] == {}
    assert "merged_subs" not in pe
    assert validate_manifest_schema(m) == []


# ─── JSON boundary: build_manifest._mk must reconstruct the new field ──────


def test_mk_reconstructs_patcher_drift_markers_from_json():
    # discover -> dataclasses.asdict -> JSON -> _mk must preserve
    # patcher_drift_markers as a tuple (else the field silently drops at the
    # serialize/reconstruct boundary — the silent-no-op class).
    import dataclasses

    from scripts.anchor_sot.build_manifest import _mk

    t = AnchorTarget("PJB", "s1", "f.py", "A", "R", True,
                     patcher_drift_markers=("MARK_A", "MARK_B"))
    d = dataclasses.asdict(t)
    round_tripped = _mk(d)
    assert round_tripped.patcher_drift_markers == ("MARK_A", "MARK_B")
    assert isinstance(round_tripped.patcher_drift_markers, tuple)


def test_mk_defaults_patcher_drift_markers_when_absent():
    # back-compat: an old targets.json lacking the key -> default ().
    from scripts.anchor_sot.build_manifest import _mk

    d = {"patch_id": "POLD", "sub": "s", "target_rel": "f.py",
         "anchor": "A", "replacement": "R", "required": True}
    round_tripped = _mk(d)
    assert round_tripped.patcher_drift_markers == ()
