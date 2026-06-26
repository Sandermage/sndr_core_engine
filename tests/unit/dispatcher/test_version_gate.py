# SPDX-License-Identifier: Apache-2.0
"""The version-only gate (deep-audit #1).

`_check_applies_to` checks `vllm_version_range` only in its Path B, AFTER an
early-return that fires whenever the model profile is unresolved — which is
always true at plugin-register apply time. So the version range was never
enforced. `_check_version_gate` restores enforcement with no dependency on
the model profile, behind GENESIS_ENFORCE_VERSION_RANGE=1 (default OFF).

These tests inject a known engine version so the real version comparison runs
without a live vLLM install.
"""
from __future__ import annotations

import pytest

from sndr.dispatcher import decision as D
from sndr.compat import version_check as vc


DEV259 = "0.22.1rc1.dev259+g303916e93"


@pytest.fixture
def engine_is_dev259(monkeypatch):
    """Make the toolchain detector report the dev259 pin (>= 0.22.0)."""
    prof = vc.VersionProfile(
        vllm=DEV259, vllm_commit="303916e93", torch=None, triton=None,
        cuda_runtime=None, nvidia_driver=None, python=None,
        compute_capabilities=[], errors=[],
    )
    monkeypatch.setattr(vc, "detect_versions", lambda refresh=False: prof)
    return prof


def _meta(version_range=None):
    m = {"title": "t", "tier": "community", "family": "x"}
    if version_range is not None:
        m["applies_to"] = {"vllm_version_range": version_range}
    return m


class TestCheckVersionGate:
    def test_off_by_default_returns_none(self, engine_is_dev259, monkeypatch):
        monkeypatch.delenv("GENESIS_ENFORCE_VERSION_RANGE", raising=False)
        # PN125's range excludes dev259, but the gate is OFF -> no skip.
        meta = _meta((">=0.20.0", "<0.22.0"))
        assert D._check_version_gate("PN125", meta) is None

    def test_on_and_range_excludes_pin_skips(self, engine_is_dev259, monkeypatch):
        monkeypatch.setenv("GENESIS_ENFORCE_VERSION_RANGE", "1")
        meta = _meta((">=0.20.0", "<0.22.0"))  # dev259 is 0.22.1 -> excluded
        result = D._check_version_gate("PN125", meta)
        assert result is not None
        applied, reason = result
        assert applied is False
        assert "VERSION-GATE" in reason

    def test_on_and_range_includes_pin_passes(self, engine_is_dev259, monkeypatch):
        monkeypatch.setenv("GENESIS_ENFORCE_VERSION_RANGE", "1")
        meta = _meta((">=0.20.0", "<0.23.0"))  # dev259 included
        assert D._check_version_gate("X", meta) is None

    def test_on_but_no_version_constraint_returns_none(self, engine_is_dev259, monkeypatch):
        monkeypatch.setenv("GENESIS_ENFORCE_VERSION_RANGE", "1")
        assert D._check_version_gate("X", _meta(None)) is None

    def test_probe_failure_does_not_block(self, monkeypatch):
        monkeypatch.setenv("GENESIS_ENFORCE_VERSION_RANGE", "1")

        def _boom(*a, **k):
            raise RuntimeError("no toolchain")

        monkeypatch.setattr(vc, "check_version_constraints", _boom)
        assert D._check_version_gate("X", _meta((">=0.20.0", "<0.22.0"))) is None


class TestShouldApplyIntegration:
    """The gate must be REACHABLE from should_apply even though the model
    profile is unresolved — the exact bug it fixes."""

    def test_enforced_version_mismatch_skips_even_when_env_enabled(
        self, engine_is_dev259, monkeypatch
    ):
        # PN125 is a real registry patch; env-enable it, enforce versions.
        monkeypatch.setenv("GENESIS_ENABLE_PN125_HYBRID_FULL_AND_PIECEWISE", "1")
        monkeypatch.setenv("GENESIS_ENFORCE_VERSION_RANGE", "1")
        monkeypatch.delenv("GENESIS_LEGACY_DEFAULT_ON", raising=False)
        decision, reason = D.should_apply("PN125")
        assert decision is False
        assert "VERSION-GATE" in reason

    def test_default_off_env_enabled_patch_still_applies(
        self, engine_is_dev259, monkeypatch
    ):
        # Same patch, same pin, but enforcement OFF -> env-override wins
        # (proves the gate ships as a no-op by default).
        monkeypatch.setenv("GENESIS_ENABLE_PN125_HYBRID_FULL_AND_PIECEWISE", "1")
        monkeypatch.delenv("GENESIS_ENFORCE_VERSION_RANGE", raising=False)
        monkeypatch.delenv("GENESIS_LEGACY_DEFAULT_ON", raising=False)
        decision, _ = D.should_apply("PN125")
        assert decision is True
