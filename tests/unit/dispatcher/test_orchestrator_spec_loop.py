# SPDX-License-Identifier: Apache-2.0
"""TDD for `_run_via_specs` (PR38 Day 6-8).

Spec-driven apply loop activated by `SNDR_APPLY_VIA_SPECS=1`. Iterates
`dispatcher.iter_patch_specs()` and calls `module.apply()` directly on
each spec's `apply_module`. Replaces the hand-written
`_per_patch_dispatch.apply_patch_X` parking lot.
"""
from __future__ import annotations

import pytest


def _orch():
    from vllm.sndr_core.apply import orchestrator
    return orchestrator


# ─── Spec-loop function exists + is wired ─────────────────────────────────


class TestSpecLoopWiring:
    def test_run_via_specs_function_exists(self):
        o = _orch()
        assert callable(o._run_via_specs), (
            "_run_via_specs must exist on orchestrator"
        )

    def test_run_via_specs_uses_iter_patch_specs(self):
        """The spec-loop must drive its iteration from
        `dispatcher.iter_patch_specs()` — not from `_state.PATCH_REGISTRY`
        (the legacy registration list)."""
        import inspect
        o = _orch()
        src = inspect.getsource(o._run_via_specs)
        assert "iter_patch_specs" in src


# ─── End-to-end dry-run via spec loop ─────────────────────────────────────


class TestSpecLoopDryRun:
    def test_spec_loop_runs_clean_in_dry_run(self, monkeypatch):
        """With `SNDR_APPLY_VIA_SPECS=1` and dry-run mode:

        P0-2 (audit 2026-05-08): the dispatcher decision (`should_apply`)
        is consulted BEFORE importing the wiring module. Disabled patches
        — env-flag off, tier ineligible, hardware mismatch, conflicts —
        record as 'skipped' without touching their potentially
        torch-heavy apply_module. This makes dry-run a real torch-less
        diagnostic path.

        New contract (replaces the pre-P0-2 'every apply_module → applied'
        expectation):
          - default_on patches with apply_module → 'applied' (dry-run ready)
          - default_off patches → 'skipped' (env flag not set)
          - patches without apply_module → 'skipped' (informational entry)
          - failures → only structurally broken wiring (rare)

        Acceptable result on a torch-equipped host: a small bucket of
        applied (~20 default_on), a large bucket of skipped (the
        intentionally opt-in patches), and zero failures.
        """
        monkeypatch.setenv("SNDR_APPLY_VIA_SPECS", "1")
        o = _orch()
        stats = o.run(verbose=False, apply=False)
        applied = [r for r in stats.results if r.status == "applied"]
        skipped = [r for r in stats.results if r.status == "skipped"]
        failed = [r for r in stats.results if r.status == "failed"]
        # default_on bucket should be non-empty.
        assert len(applied) >= 5, (
            f"dry-run produced suspiciously few applied: {len(applied)}"
        )
        # The bulk of registry is opt-in → skipped is the larger bucket.
        assert len(skipped) >= len(applied), (
            f"applied={len(applied)} skipped={len(skipped)} — "
            "post-P0-2 contract expects skipped to dominate (most "
            "patches are opt-in)"
        )
        # Failures during dry-run import are P0-2's other guarantee:
        # missing torch on host → skipped, not failed. Real wiring
        # bugs surface as failed.
        assert len(failed) == 0, (
            f"spec-loop dry-run produced failures: "
            f"{[(r.name, r.reason) for r in failed[:5]]}"
        )

    def test_spec_loop_default_off(self, monkeypatch):
        """Without env flag, the legacy loop runs (not the spec loop).
        Verify by checking that `_run_via_specs` is NOT called when
        `SNDR_APPLY_VIA_SPECS` is absent."""
        monkeypatch.delenv("SNDR_APPLY_VIA_SPECS", raising=False)
        o = _orch()
        called = {"spec": 0}
        original = o._run_via_specs

        def spy(stats):
            called["spec"] += 1
            return original(stats)

        monkeypatch.setattr(o, "_run_via_specs", spy)
        o.run(verbose=False, apply=False)
        assert called["spec"] == 0, (
            "spec loop should not run when SNDR_APPLY_VIA_SPECS is unset"
        )

    @pytest.mark.parametrize("env_value", ["1", "true", "yes", "on", "TRUE"])
    def test_spec_loop_engages_on_truthy_env(self, monkeypatch, env_value):
        """All canonical truthy values activate the spec loop."""
        monkeypatch.setenv("SNDR_APPLY_VIA_SPECS", env_value)
        o = _orch()
        called = {"spec": 0}
        original = o._run_via_specs

        def spy(stats):
            called["spec"] += 1
            return original(stats)

        monkeypatch.setattr(o, "_run_via_specs", spy)
        o.run(verbose=False, apply=False)
        assert called["spec"] == 1


# ─── Spec-loop result shape ───────────────────────────────────────────────


class TestSpecLoopResultShape:
    def test_each_result_is_patchresult(self, monkeypatch):
        from vllm.sndr_core.apply._state import PatchResult
        monkeypatch.setenv("SNDR_APPLY_VIA_SPECS", "1")
        o = _orch()
        stats = o.run(verbose=False, apply=False)
        for r in stats.results:
            assert isinstance(r, PatchResult)
            assert r.status in ("applied", "skipped", "failed")

    def test_result_name_includes_patch_id(self, monkeypatch):
        """Display name must start with the patch_id so logs are
        grep-able by ID — same contract as the legacy loop."""
        monkeypatch.setenv("SNDR_APPLY_VIA_SPECS", "1")
        o = _orch()
        stats = o.run(verbose=False, apply=False)
        # Find PN82's entry — recently added, has apply_module
        pn82_results = [r for r in stats.results if "PN82" in r.name]
        assert pn82_results, "PN82 must appear in spec-loop results"
