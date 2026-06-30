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
    from sndr.apply import orchestrator
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
        """With `SNDR_APPLY_VIA_SPECS=1` and dry-run mode, the
        orchestrator must classify every registry entry into exactly
        one of {applied, skipped, failed} without raising — and must
        report zero failures (no wiring imports broken).

        Phase 5.3.A (2026-05-22): refreshed from the pre-2026-05-17
        auto-apply expectation. Under the strict-opt-in policy
        (decision.py:305-360), with a clean test env (no per-patch
        `GENESIS_ENABLE_<X>=1` flags set), every `default_on=True`
        patch routes to 'skipped' rather than 'applied'. The previous
        assertion `applied >= 5` therefore no longer holds — it
        encoded the auto-apply semantics now reserved for the
        `GENESIS_LEGACY_DEFAULT_ON=1` escape hatch.

        Structural contract (what matters regardless of policy era):
          - applied + skipped + failed == total (every entry classified)
          - failed == 0 (no broken wiring imports / structural bugs)
          - applied ⊆ entries that satisfied dispatcher decision

        The 'no failures' guarantee is the load-bearing one: a torch-
        less laptop run must not crash inside any apply_module. That
        was the P0-2 audit's original promise and survives the policy
        flip.
        """
        monkeypatch.setenv("SNDR_APPLY_VIA_SPECS", "1")
        # Ensure clean strict-opt-in env — no LEGACY_DEFAULT_ON
        # rescue, no per-patch ENABLE flags leaking from the parent
        # shell. The test verifies the modern policy's classification
        # invariants.
        monkeypatch.delenv("GENESIS_LEGACY_DEFAULT_ON", raising=False)
        monkeypatch.delenv("SNDR_LEGACY_DEFAULT_ON", raising=False)

        o = _orch()
        stats = o.run(verbose=False, apply=False)
        applied = [r for r in stats.results if r.status == "applied"]
        skipped = [r for r in stats.results if r.status == "skipped"]
        failed = [r for r in stats.results if r.status == "failed"]
        total_classified = len(applied) + len(skipped) + len(failed)

        # Every entry must land in exactly one bucket — no unclassified
        # / leaked statuses.
        assert total_classified == len(stats.results), (
            f"classification gap: applied={len(applied)} + "
            f"skipped={len(skipped)} + failed={len(failed)} != "
            f"total={len(stats.results)}"
        )
        # No broken wiring imports — the load-bearing P0-2 guarantee.
        assert len(failed) == 0, (
            f"spec-loop dry-run produced failures: "
            f"{[(r.name, r.reason) for r in failed[:5]]}"
        )
        # Under strict-opt-in clean env, the bulk of entries route to
        # 'skipped' (informational metadata-only entries + default_off
        # opt-ins + default_on awaiting explicit ENABLE).
        assert len(skipped) > 0, (
            "dry-run classified nothing as skipped; either the "
            "registry is empty or the orchestrator misclassified — "
            "investigate stats.results"
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
        from sndr.apply._state import PatchResult
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
        # Find PN116's entry — active experimental backport with apply_module
        # (PN82 retired 2026-05-28 K.1.R pin bump audit — vllm#41873 merged
        # upstream at 39d5fa96 within window dev371→626fa9bb).
        pn116_results = [r for r in stats.results if "PN116" in r.name]
        assert pn116_results, "PN116 must appear in spec-loop results"


# ─── Shared per-spec helper (extracted 2026-06-14) ────────────────────────


class TestApplySpecModuleHelper:
    """`_apply_spec_module` centralizes the gate→import→apply→classify
    sequence so `_run_via_specs` (full spec boot) and
    `_run_spec_only_supplement` (legacy-boot bridge) behave identically."""

    def test_helper_exists(self):
        o = _orch()
        assert callable(o._apply_spec_module)

    def test_run_via_specs_delegates_to_helper(self):
        import inspect
        o = _orch()
        src = inspect.getsource(o._run_via_specs)
        assert "_apply_spec_module" in src, (
            "_run_via_specs must drive each spec through the shared helper"
        )


# ─── Spec-only supplement (legacy-boot bridge, 2026-06-14) ────────────────


class TestSpecOnlySupplement:
    """Under the DEFAULT boot mode (SNDR_APPLY_VIA_SPECS unset) the legacy
    loop only applies @register_patch-hooked patches. 59 patches declare an
    apply_module but no legacy hook (KNOWN_SPEC_ONLY). Before the supplement
    they were unreachable at boot even when an operator set
    GENESIS_ENABLE_<X>=1 — the exact failure that made the dev491 PN392
    streaming fix appear inert in live smoke. The supplement applies the
    ENABLED ones without dropping the bundled default_on legacy patches
    (P1/P2, P17/P18, P32/P33) that have no apply_module.

    PN392 is the canonical probe: spec-only, apply_module imports torch-less
    (so dry-run yields a deterministic 'applied: dry-run ready'), env flag
    GENESIS_ENABLE_PN392_QWEN3CODER_STREAMING_COALESCE.

    NOTE: PN392 was lifecycle-retired (upstream streaming coalesce merged). The
    GAP4 lifecycle gate (decision._check_lifecycle_gate) now hard-skips retired
    patches on every apply path, so the two tests that assert PN392 *applies*
    set GENESIS_ALLOW_RETIRED=1 — they exercise the supplement WIRING on the
    known torch-less probe, not lifecycle policy (that is covered by
    test_decision_lifecycle_gate.py). The disabled/absent and spec-boot tests
    need no escape hatch: a should_apply=False patch is silently dropped by the
    supplement and emits a skip-row in the spec loop.
    """

    PN392_FLAG = "GENESIS_ENABLE_PN392_QWEN3CODER_STREAMING_COALESCE"

    def test_supplement_function_exists(self):
        o = _orch()
        assert callable(o._run_spec_only_supplement)

    def test_run_wires_supplement_in_legacy_path(self):
        import inspect
        o = _orch()
        src = inspect.getsource(o.run)
        assert "_run_spec_only_supplement" in src, (
            "run() must call the spec-only supplement after the legacy loop"
        )

    def test_enabled_spec_only_patch_applies_under_legacy_boot(
        self, monkeypatch
    ):
        """The load-bearing assertion: legacy boot + env flag → PN392
        appears as applied. Before the supplement it was absent."""
        monkeypatch.delenv("SNDR_APPLY_VIA_SPECS", raising=False)
        monkeypatch.setenv(self.PN392_FLAG, "1")
        monkeypatch.setenv("GENESIS_ALLOW_RETIRED", "1")  # PN392 is retired; test the wiring
        o = _orch()
        stats = o.run(verbose=False, apply=False)
        pn392 = [r for r in stats.results if r.name.startswith("PN392")]
        assert pn392, (
            "PN392 absent from legacy-boot stats — the supplement did not "
            "reach it (regression: spec-only patches inert at boot again)"
        )
        assert pn392[0].status == "applied", (
            f"PN392 enabled but not applied: "
            f"{pn392[0].status} / {pn392[0].reason}"
        )

    def test_disabled_spec_only_patch_absent_under_legacy_boot(
        self, monkeypatch
    ):
        """No flag → PN392 must NOT appear. Disabled spec-only patches are
        skipped silently (no stats row) so the default boot's apply summary
        is byte-identical to pre-supplement behavior."""
        monkeypatch.delenv("SNDR_APPLY_VIA_SPECS", raising=False)
        monkeypatch.delenv(self.PN392_FLAG, raising=False)
        o = _orch()
        stats = o.run(verbose=False, apply=False)
        pn392 = [r for r in stats.results if r.name.startswith("PN392")]
        assert not pn392, (
            f"PN392 must be silently skipped when disabled, but it produced "
            f"rows: {[(r.status, r.reason) for r in pn392]}"
        )

    def test_supplement_does_not_double_apply(self, monkeypatch):
        """The supplement excludes legacy-hooked patch ids, so an enabled
        spec-only patch appears exactly once (never via both paths)."""
        monkeypatch.delenv("SNDR_APPLY_VIA_SPECS", raising=False)
        monkeypatch.setenv(self.PN392_FLAG, "1")
        monkeypatch.setenv("GENESIS_ALLOW_RETIRED", "1")  # PN392 is retired; test the wiring
        o = _orch()
        stats = o.run(verbose=False, apply=False)
        pn392 = [r for r in stats.results if r.name.startswith("PN392")]
        assert len(pn392) == 1, (
            f"PN392 applied {len(pn392)} times (expected exactly 1) — "
            "double-apply guard failed"
        )

    def test_supplement_noop_does_not_break_spec_boot_mode(
        self, monkeypatch
    ):
        """Sanity: in spec-boot mode the legacy path (and its supplement)
        are skipped entirely, so PN392 still routes through _run_via_specs.
        Guards against the supplement leaking into the spec-driven path."""
        monkeypatch.setenv("SNDR_APPLY_VIA_SPECS", "1")
        monkeypatch.setenv(self.PN392_FLAG, "1")
        o = _orch()
        stats = o.run(verbose=False, apply=False)
        pn392 = [r for r in stats.results if r.name.startswith("PN392")]
        # Exactly one PN392 row from the spec loop — not duplicated by a
        # stray supplement call.
        assert len(pn392) == 1, (
            f"PN392 appears {len(pn392)} times under spec-boot (expected 1)"
        )
