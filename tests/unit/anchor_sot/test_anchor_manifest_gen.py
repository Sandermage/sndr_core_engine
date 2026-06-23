"""Phase 2 — true-drift classifier (R2) tests. Synthetic, local, no vLLM needed."""
from sndr.engines.vllm.anchor_discovery import AnchorTarget
from sndr.engines.vllm.anchor_manifest_gen import (
    classify_anchor,
    build_pin_manifest,
    apply_via_meta,
    verify_roundtrip,
    to_engine_manifest,
    STATUS_OK,
    STATUS_ANCHOR_DRIFT,
    STATUS_AMBIGUOUS,
    STATUS_RETIRED,
)


def test_to_engine_manifest_passes_engine_validator():
    from sndr.engines.vllm.wiring.anchor_manifest import validate_manifest_schema

    targets = [
        AnchorTarget("PA", "s1", "fileA.py", "ANCHOR_A", "REPL_A", True),
        AnchorTarget("PB", "s1", "fileA.py", "ANCHOR_B", "REPL_B", True),
    ]
    pristine = {"fileA.py": "x ANCHOR_A y ANCHOR_B z"}
    res = build_pin_manifest(lambda rel: pristine.get(rel), targets)
    m = to_engine_manifest(
        res, lambda rel: pristine.get(rel), vllm_pin="0.23.1", genesis_pin="v12"
    )
    errors = validate_manifest_schema(m)
    assert errors == [], errors
    assert "fileA.py" in m["files"]
    assert set(m["files"]["fileA.py"]["patches"]) == {"PA", "PB"}
    assert "s1" in m["files"]["fileA.py"]["patches"]["PA"]["anchors"]


def test_R3_roundtrip_byte_identical_single_line():
    src = "a\ndef f():\n    return OLD_ANCHOR\nb\n"
    assert verify_roundtrip(src, "    return OLD_ANCHOR", "    return NEW_VALUE")


def test_R3_roundtrip_byte_identical_multiline():
    src = "x\n    if (\n        self.cond):\n        do()\ny\n"
    assert verify_roundtrip(
        src, "    if (\n        self.cond):", "    if (self.cond):  # patched"
    )


def test_R3_roundtrip_unicode_replacement():
    # replacement with non-ASCII (anchor stays ASCII so offset is byte-stable)
    src = "head\n    ANCHOR_HERE\ntail\n"
    assert verify_roundtrip(src, "    ANCHOR_HERE", "    PATCHED_x")


def test_apply_via_meta_matches_inline():
    src = "p\n    target_line()\nq\n"
    status, meta = classify_anchor(src, "    target_line()", "    new_line()")
    assert status == STATUS_OK
    assert apply_via_meta(src, meta, "    new_line()") == src.replace(
        "    target_line()", "    new_line()", 1
    )


def test_classify_ok_computes_meta():
    src = "def foo():\n    return ORIGINAL_X\n\ndef bar():\n    return OTHER_Y\n"
    status, meta = classify_anchor(src, "    return ORIGINAL_X", "    return PATCHED")
    assert status == STATUS_OK
    assert meta["byte_offset"] >= 0 and meta["anchor_md5"]
    assert meta["replacement_md5"]  # replacement passed -> md5 present


def test_R2_drift_is_real_not_assumed():
    src = "def foo():\n    return ORIGINAL_X\n"
    mutated = src.replace("ORIGINAL_X", "REFACTORED_Z")  # upstream refactor
    status, meta = classify_anchor(mutated, "    return ORIGINAL_X")
    assert status == STATUS_ANCHOR_DRIFT and meta is None


def test_R2_no_false_positive_on_unaffected_anchor():
    src = "def foo():\n    return ORIGINAL_X\n\ndef bar():\n    return OTHER_Y\n"
    mutated = src.replace("ORIGINAL_X", "REFACTORED_Z")
    # the OTHER anchor in the same mutated file is untouched -> still ok
    status, _ = classify_anchor(mutated, "    return OTHER_Y")
    assert status == STATUS_OK


def test_ambiguous_when_anchor_not_unique():
    src = "X\nDUP\nY\nDUP\nZ\n"
    status, meta = classify_anchor(src, "DUP")
    assert status == STATUS_AMBIGUOUS and meta is None


def test_R2_build_pin_manifest_isolates_drift():
    targets = [
        AnchorTarget("PA", "s1", "fileA.py", "ANCHOR_A", "REPL_A", True),
        AnchorTarget("PB", "s1", "fileB.py", "ANCHOR_B", "REPL_B", True),
    ]
    pristine = {"fileA.py": "x ANCHOR_A y", "fileB.py": "p ANCHOR_B q"}
    r = build_pin_manifest(lambda rel: pristine.get(rel), targets)
    assert set(r.ok) == {"PA::s1", "PB::s1"} and not r.rej

    # drift fileA only -> EXACTLY PA drifts, PB still ok (R2 isolation)
    drifted = dict(pristine, **{"fileA.py": "x REFACTORED y"})
    r2 = build_pin_manifest(lambda rel: drifted.get(rel), targets)
    assert "PB::s1" in r2.ok and "PA::s1" not in r2.ok
    assert any(
        e["key"] == "PA::s1" and e["status"] == STATUS_ANCHOR_DRIFT
        for e in r2.rej
    )


def test_version_gated_split_not_drift():
    # vrange excludes the pin -> version_gated even with an absent anchor (true cause)
    t = AnchorTarget(
        "PG", "s1", "f.py", "MISSING_ANCHOR", "R", True,
        vllm_version_range=(">=0.20.0", "<0.23.0"),
    )
    src = {"f.py": "no anchor here"}
    r = build_pin_manifest(
        lambda rel: src.get(rel), [t], pin="0.23.1rc1.dev148+gb4c80ec0f"
    )
    assert not r.ok and r.rej[0]["status"] == "version_gated"
    # without pin info it falls back to anchor_drift (can't know it's gated)
    r2 = build_pin_manifest(lambda rel: src.get(rel), [t])
    assert r2.rej[0]["status"] == "anchor_drift"


def test_upstream_merged_marker_on_target_excludes():
    # a per-target upstream_merged_marker present in source -> upstream_merged
    t = AnchorTarget(
        "PUM", "s1", "f.py", "ANCH", "R", True,
        upstream_merged_markers=("def native_fix",),
    )
    src = {"f.py": "ANCH present and def native_fix here"}
    r = build_pin_manifest(lambda rel: src.get(rel), [t])
    assert not r.ok and r.rej[0]["status"] == "upstream_merged"


def test_upstream_merged_excluded():
    targets = [AnchorTarget("PM", "s1", "f.py", "ANCH", "R", True)]
    src = {"f.py": "ANCH present"}
    r = build_pin_manifest(
        lambda rel: src.get(rel),
        targets,
        is_upstream_merged=lambda t, content: True,  # caller says merged
    )
    assert not r.ok
    assert r.rej and r.rej[0]["status"] == "upstream_merged"


def test_retired_drifted_anchor_is_retired_not_drift():
    # FIX 2: a retired patch whose anchor is GONE classifies as `retired`, not
    # anchor_drift — it must never enter the re-anchor backlog. A non-retired
    # patch with the same gone anchor still classifies anchor_drift.
    targets = [
        AnchorTarget("PRET", "s1", "f.py", "GONE_ANCHOR", "R", True,
                     lifecycle="retired"),
        AnchorTarget("PLIVE", "s1", "f.py", "GONE_TOO", "R", True),
    ]
    src = {"f.py": "neither present"}
    r = build_pin_manifest(lambda rel: src.get(rel), targets)
    by_key = {e["key"]: e["status"] for e in r.rej}
    assert by_key["PRET::s1"] == STATUS_RETIRED
    assert by_key["PLIVE::s1"] == STATUS_ANCHOR_DRIFT
    assert not r.ok
    # genuine drift (the re-anchor backlog) excludes the retired patch
    drift_keys = {e["key"] for e in r.rej if e["status"] == STATUS_ANCHOR_DRIFT}
    assert drift_keys == {"PLIVE::s1"}


def test_retired_matching_anchor_still_retired_never_ok():
    # Even when the anchor STILL matches, a retired patch never lands in `ok`
    # (never spliced) — routed to `retired` regardless of anchor presence.
    targets = [
        AnchorTarget("PRET", "s1", "f.py", "STILL_HERE", "R", True,
                     lifecycle="retired"),
    ]
    src = {"f.py": "x STILL_HERE y"}
    r = build_pin_manifest(lambda rel: src.get(rel), targets)
    assert not r.ok
    assert r.rej and r.rej[0]["status"] == STATUS_RETIRED


def test_retired_not_counted_in_merge_aggregation():
    # A retired patch is out of the active set: it must not feed the per-patch
    # merge tri-state (no spurious not_merged entry for a retired patch).
    targets = [
        AnchorTarget("PRET", "s1", "f.py", "STILL_HERE", "R", True,
                     lifecycle="retired"),
        AnchorTarget("PLIVE", "s1", "f.py", "LIVE_ANCH", "R", True),
    ]
    src = {"f.py": "x STILL_HERE LIVE_ANCH y"}
    r = build_pin_manifest(lambda rel: src.get(rel), targets)
    assert "PRET" not in r.merge          # retired excluded from merge roll-up
    assert r.merge["PLIVE"]["merge_status"] == "not_merged"


def test_retired_case_insensitive():
    # lifecycle string is matched case-insensitively ("Retired" / "RETIRED").
    for lc in ("Retired", "RETIRED", "retired"):
        t = AnchorTarget("PR", "s1", "f.py", "GONE", "R", True, lifecycle=lc)
        r = build_pin_manifest(lambda rel: {"f.py": "x"}.get(rel), [t])
        assert r.rej[0]["status"] == STATUS_RETIRED, lc
