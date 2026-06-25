# SPDX-License-Identifier: Apache-2.0
"""Tests for ``product_api.patches.bump_preflight_status`` — daemon-side pin-bump
preflight (newly-retired / retire-broken / perf-dropped between two pin manifests)."""
from __future__ import annotations

from sndr.product_api.legacy.patches import bump_preflight_status as bp


class TestBumpPreflightStatus:
    def test_shape_against_real_manifests(self):
        d = bp.bump_preflight_status()
        assert isinstance(d, dict)
        for key in ("old_pin", "new_pin", "newly_retired", "high_count",
                    "high_unmitigated", "high_mitigated", "perf_landmines", "gate_pass"):
            assert key in d
        assert isinstance(d["newly_retired"], list)
        assert isinstance(d["gate_pass"], bool)

    def test_gate_passes_when_high_is_mitigated(self):
        # The dev301 -> dev424 bump's only HIGH edge (PN353A->PN399) has a
        # native-form fallback -> mitigated -> the gate must PASS (no false-fail).
        d = bp.bump_preflight_status()
        if d.get("error"):
            return  # manifests absent in this env -> nothing to assert
        assert d["high_unmitigated"] == []
        assert d["gate_pass"] is True

    def test_fail_safe_no_pins_dir(self, monkeypatch):
        from sndr.product_api.legacy.patches import anchor_status
        monkeypatch.setattr(anchor_status, "_pins_dir", lambda: None)
        d = bp.bump_preflight_status()
        assert d["error"] == "no_pins_dir"
        assert d["gate_pass"] is True

    def test_dev_num_ordering(self):
        assert bp._dev_num("0.23.1rc1.dev424+g3f5a1e173") == 424
        assert bp._dev_num("0.23.1rc1.dev301+g04c2a8dea") == 301
        assert bp._dev_num("nope") == -1
