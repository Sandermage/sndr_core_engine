"""Phase 1 — anchor_discovery R1 coverage tests.

R1: discovery must enumerate ALL anchor-bearing patches (no hand-typed subset).
Discovery requires a vLLM source tree (the patchers build against it); when
vLLM is absent (local dev box) the discovery yields ~nothing and the test
skips — the authoritative R1 proof runs on the rig / CI where dev148 vLLM is
installed (see the §-server-test in the implementation plan).
"""
import pytest

from sndr.engines.vllm.anchor_discovery import (
    AnchorTarget,
    iter_anchor_targets,
    iter_specs_with_apply_module,
    _build_patcher_for_module,
)


def _discovered():
    return list(iter_anchor_targets())


def test_R1_broad_coverage():
    targets = _discovered()
    if len(targets) < 10:
        pytest.skip(
            "vLLM not installed (discovery yields nothing) — R1 is proven on "
            "the rig/CI with dev148 vLLM present"
        )
    patch_ids = {t.patch_id for t in targets}
    # Must be FAR beyond the old 4-patch hand-typed manifest subset.
    assert len(patch_ids) >= 100, (
        f"R1: only {len(patch_ids)} patches discovered, expected ~180"
    )


def test_anchor_target_shape():
    targets = _discovered()
    if not targets:
        pytest.skip("vLLM not installed — discovery empty")
    for t in targets[:30]:
        assert isinstance(t, AnchorTarget)
        assert t.patch_id and t.target_rel and t.anchor
        assert isinstance(t.required, bool)


def test_anchor_target_carries_lifecycle_field():
    # FIX 2 plumbing: AnchorTarget exposes a `lifecycle` field (defaults None),
    # so the manifest generator can route retired patches to STATUS_RETIRED.
    # Host-runnable (no vLLM): asserts the dataclass shape directly.
    import dataclasses

    names = {f.name for f in dataclasses.fields(AnchorTarget)}
    assert "lifecycle" in names
    t = AnchorTarget("P", "s", "f.py", "A", "R", True)
    assert t.lifecycle is None  # default when a spec has no lifecycle
    t2 = AnchorTarget("P", "s", "f.py", "A", "R", True, lifecycle="retired")
    assert t2.lifecycle == "retired"


def test_discovery_populates_lifecycle_from_spec():
    # When vLLM is present, iter_anchor_targets must stamp each target's
    # lifecycle from its spec (retired patches keep being yielded — VISIBLE —
    # but tagged so the generator can classify them as retired). Rig-gated.
    targets = _discovered()
    if not targets:
        pytest.skip("vLLM not installed — discovery empty")
    by_pid = {}
    for t in targets:
        by_pid.setdefault(t.patch_id, t)
    # every target's lifecycle is either None or a lowercase string
    for t in targets[:50]:
        assert t.lifecycle is None or t.lifecycle == t.lifecycle.lower()
    # the known retired patches (if discovered on this pin) are tagged retired,
    # NOT dropped from discovery.
    for pid in ("P78", "PN67", "G4_05"):
        if pid in by_pid:
            assert by_pid[pid].lifecycle == "retired", pid


def test_R1_no_anchor_bearing_patch_dropped():
    """Cross-check the yield logic: every spec whose patcher has >=1 anchored
    sub-patch must appear in iter_anchor_targets (catches an over-aggressive
    skip in the yield path)."""
    import importlib

    discovered = {t.patch_id for t in _discovered()}
    if not discovered:
        pytest.skip("vLLM not installed — discovery empty")
    expected = set()
    for spec in iter_specs_with_apply_module():
        try:
            mod = importlib.import_module(spec.apply_module)
        except Exception:
            continue
        patcher, _ = _build_patcher_for_module(mod)
        if patcher is None:
            continue
        if any(
            getattr(sp, "anchor", None)
            for sp in getattr(patcher, "sub_patches", []) or []
        ):
            expected.add(getattr(spec, "patch_id", "?"))
    missing = expected - discovered
    assert not missing, f"R1 VIOLATION: discovery missed {sorted(missing)}"


# ── discover_patchers: generalized multi-builder enumeration ─────────────
# The blind spot: _build_patcher_for_module recognized only _make_patcher /
# _make_patcher_for_drift, so multi-file patches (P58: _make_request_patcher +
# _make_scheduler_patcher + _make_async_sched_patcher) fell to needs_fixture
# despite having real anchors. discover_patchers must find ALL builders.
import types


def _fake_patcher(name):
    return types.SimpleNamespace(patch_name=name, target_file=f"/x/{name}.py",
                                 marker=f"m-{name}", sub_patches=[])


def test_discover_patchers_finds_all_named_builders():
    from sndr.engines.vllm.anchor_discovery import discover_patchers
    mod = types.ModuleType("fake_multi")
    mod._make_request_patcher = lambda: _fake_patcher("request")
    mod._make_scheduler_patcher = lambda: _fake_patcher("scheduler")
    mod._make_patcher = lambda: _fake_patcher("main")
    mod._helper = lambda: "not a patcher"          # ignored (bad name)
    mod._is_enabled = lambda: True                  # ignored (bad name)
    got = discover_patchers(mod)
    names = sorted(p.patch_name for p, _ in got if p)
    assert names == ["main", "request", "scheduler"]


def test_discover_patchers_skips_none_returns():
    from sndr.engines.vllm.anchor_discovery import discover_patchers
    mod = types.ModuleType("fake_absent")
    mod._make_a_patcher = lambda: None              # target file absent at pin
    mod._make_b_patcher = lambda: _fake_patcher("b")
    got = [p for p, _ in discover_patchers(mod) if p]
    assert [p.patch_name for p in got] == ["b"]


def test_discover_patchers_empty_for_pure_wiring():
    from sndr.engines.vllm.anchor_discovery import discover_patchers
    mod = types.ModuleType("fake_wiring")
    mod.apply = lambda: ("ok", "ok")                # class-rebind, no builders
    assert discover_patchers(mod) == []


def test_discover_patchers_skips_arg_requiring_helper_builders():
    # FP-2: a helper/fixture builder that REQUIRES args (e.g. _make_patcher_for_target(cls))
    # must not be called with guessed defaults — that fabricates a bogus patcher.
    from sndr.engines.vllm.anchor_discovery import discover_patchers
    mod = types.ModuleType("fake_fixture")
    mod._make_patcher = lambda: _fake_patcher("real")            # zero-arg runtime builder
    mod._make_patcher_for_target = lambda cls: _fake_patcher(cls or "bogus")  # helper — REQUIRES cls
    got = [p.patch_name for p, _ in discover_patchers(mod) if p]
    assert got == ["real"]  # the arg-requiring helper is skipped


def test_discover_patchers_drops_empty_target_patchers():
    # A builder that returns a patcher with no target_file must not enter aggregation.
    from sndr.engines.vllm.anchor_discovery import discover_patchers
    import types as _t
    mod = _t.ModuleType("fake_empty")
    mod._make_a_patcher = lambda: _t.SimpleNamespace(patch_name="empty", target_file="", marker="m", sub_patches=[])
    mod._make_b_patcher = lambda: _fake_patcher("good")
    got = [p.patch_name for p, _ in discover_patchers(mod) if p]
    assert got == ["good"]
