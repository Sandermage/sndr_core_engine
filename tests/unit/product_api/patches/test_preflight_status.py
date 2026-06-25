# SPDX-License-Identifier: Apache-2.0
"""Tests for ``product_api.patches.preflight_status`` — runtime preflight checks
against the running engine."""
from __future__ import annotations

from sndr.product_api.legacy.patches import preflight_status


class TestPreflightStatus:
    def test_shape_no_raise(self):
        # Off-engine (no docker / no running engine) it must still return the
        # contract shape, never raise.
        d = preflight_status.preflight_status()
        assert isinstance(d, dict)
        for key in ("checks", "counts", "container", "model_dir"):
            assert key in d
        assert isinstance(d["checks"], list)
        assert isinstance(d["counts"], dict)

    def test_fail_safe_on_check_error(self, monkeypatch):
        monkeypatch.setattr(
            preflight_status, "_running_engine_target",
            lambda: ("vllm-x", "/models/X"),
        )
        import sndr.compat.preflight_checks as pf

        monkeypatch.setattr(
            pf, "run_all_preflight_checks",
            lambda **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        d = preflight_status.preflight_status()
        assert d["error"] == "RuntimeError"
        assert d["checks"] == []

    def test_counts_aggregation(self, monkeypatch):
        import dataclasses

        @dataclasses.dataclass
        class _CR:
            name: str
            severity: str
            message: str = ""
            remediation: str = ""

        monkeypatch.setattr(
            preflight_status, "_running_engine_target",
            lambda: ("vllm-x", "/models/X"),
        )
        import sndr.compat.preflight_checks as pf
        monkeypatch.setattr(
            pf, "run_all_preflight_checks",
            lambda **k: [_CR("a", "OK"), _CR("b", "WARN"), _CR("c", "WARN")],
        )
        d = preflight_status.preflight_status()
        assert d["counts"] == {"OK": 1, "WARN": 2}
        assert len(d["checks"]) == 3
        assert d["container"] == "vllm-x"
