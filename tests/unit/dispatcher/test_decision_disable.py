# SPDX-License-Identifier: Apache-2.0
"""TDD for SNDR_DISABLE_X / GENESIS_DISABLE_X opt-out wiring in
`dispatcher.decision.should_apply()`.

Audit 2026-05-14: `env.is_disabled` had existed for a while but was
never consulted by `should_apply()`. That meant `default_on=True`
patches could not be opted-out via env — operators had to edit
`registry.py` to A/B-test a patch's contribution. Community
benchmark workflows ("disable patch X, re-bench, compare") were
blocked by that gap.

The fix:
  - `should_apply()` consults `is_disabled(bare_flag)` after the
    ENABLE check.
  - DISABLE wins over ENABLE when both are set (intent-clear
    opt-out semantics).
  - WARN log is emitted on the conflict so the contradiction is
    visible.

These tests freeze that contract.
"""
from __future__ import annotations

import os
from unittest import mock

import pytest


# Use P108 as the canonical default_on=True patch for these tests.
# We pick P108 because it is the patch whose absence of a DISABLE
# knob produced the original audit finding (Wave 8 → dev338 bench).
# If P108 is ever retired, swap to any other default_on=True patch.
TEST_PATCH_ID = "P108"
TEST_BARE_FLAG = "P108"


def _should_apply():
    """Lazy import so test collection doesn't pull torch."""
    from vllm.sndr_core.dispatcher.decision import should_apply
    return should_apply


class TestDisableEnvKnob:
    """`should_apply()` honours SNDR_DISABLE_X / GENESIS_DISABLE_X."""

    def test_clean_default_on_applies(self):
        """Baseline: with no env knobs set, a default_on=True patch applies."""
        # Strip both ENABLE and DISABLE knobs to make sure we're seeing
        # the default behaviour.
        env = {k: v for k, v in os.environ.items()
               if TEST_BARE_FLAG not in k.replace("ENABLE_", "").replace("DISABLE_", "")}
        with mock.patch.dict(os.environ, env, clear=True):
            should_apply = _should_apply()
            ok, reason = should_apply(TEST_PATCH_ID)
            # default_on=True + clean env → apply
            assert ok, f"clean env should apply default_on patch, got skip: {reason}"

    def test_genesis_disable_skips(self):
        """`GENESIS_DISABLE_P108=1` skips even though default_on=True."""
        env = {**os.environ, f"GENESIS_DISABLE_{TEST_BARE_FLAG}": "1"}
        # Make sure no ENABLE knob masks the DISABLE one for this test.
        env.pop(f"GENESIS_ENABLE_{TEST_BARE_FLAG}", None)
        env.pop(f"SNDR_ENABLE_{TEST_BARE_FLAG}", None)
        with mock.patch.dict(os.environ, env, clear=True):
            should_apply = _should_apply()
            ok, reason = should_apply(TEST_PATCH_ID)
            assert not ok, "DISABLE should skip"
            assert "explicitly disabled" in reason.lower()
            assert TEST_BARE_FLAG in reason

    def test_sndr_disable_skips(self):
        """SNDR_DISABLE_<X>=1 takes precedence the same way as the legacy alias."""
        env = {**os.environ, f"SNDR_DISABLE_{TEST_BARE_FLAG}": "1"}
        env.pop(f"GENESIS_ENABLE_{TEST_BARE_FLAG}", None)
        env.pop(f"SNDR_ENABLE_{TEST_BARE_FLAG}", None)
        with mock.patch.dict(os.environ, env, clear=True):
            should_apply = _should_apply()
            ok, reason = should_apply(TEST_PATCH_ID)
            assert not ok, "SNDR_DISABLE should skip"
            assert "explicitly disabled" in reason.lower()

    def test_disable_wins_over_enable(self):
        """If both ENABLE=1 AND DISABLE=1 are set, DISABLE wins.

        Intent-clear opt-out — kill-switch beats opt-in when in conflict.
        """
        env = {
            **os.environ,
            f"GENESIS_ENABLE_{TEST_BARE_FLAG}": "1",
            f"GENESIS_DISABLE_{TEST_BARE_FLAG}": "1",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            should_apply = _should_apply()
            ok, reason = should_apply(TEST_PATCH_ID)
            assert not ok, "DISABLE must beat ENABLE when both set"
            assert "explicitly disabled" in reason.lower()

    def test_disable_falsy_does_not_disable(self):
        """`GENESIS_DISABLE_X=0` is treated as 'no opt-out' (not as 'disable')."""
        env = {**os.environ, f"GENESIS_DISABLE_{TEST_BARE_FLAG}": "0"}
        env.pop(f"GENESIS_ENABLE_{TEST_BARE_FLAG}", None)
        env.pop(f"SNDR_ENABLE_{TEST_BARE_FLAG}", None)
        with mock.patch.dict(os.environ, env, clear=True):
            should_apply = _should_apply()
            ok, _reason = should_apply(TEST_PATCH_ID)
            # default_on=True patch with DISABLE=0 should still apply.
            assert ok, "DISABLE=0 should NOT disable; it means 'no opt-out'"


# ─── Reason text contract ─────────────────────────────────────────────────


class TestDisableReasonText:
    """Operator-facing reason string must point at the env var that
    triggered the skip, so the diagnostic is actionable from one
    `sndr doctor` line."""

    def test_reason_names_both_prefixes(self):
        env = {**os.environ, f"GENESIS_DISABLE_{TEST_BARE_FLAG}": "1"}
        env.pop(f"GENESIS_ENABLE_{TEST_BARE_FLAG}", None)
        env.pop(f"SNDR_ENABLE_{TEST_BARE_FLAG}", None)
        with mock.patch.dict(os.environ, env, clear=True):
            should_apply = _should_apply()
            _ok, reason = should_apply(TEST_PATCH_ID)
            assert f"SNDR_DISABLE_{TEST_BARE_FLAG}" in reason
            assert f"GENESIS_DISABLE_{TEST_BARE_FLAG}" in reason
            assert "re-engage" in reason or "engage" in reason
