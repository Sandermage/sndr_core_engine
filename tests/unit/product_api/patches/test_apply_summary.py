# SPDX-License-Identifier: Apache-2.0
"""Tests for ``product_api.patches.apply_summary`` — engine patch self-test."""
from __future__ import annotations

from sndr.product_api.legacy.patches import apply_summary


class TestApplySummary:
    def test_shape_no_raise(self):
        d = apply_summary.apply_summary()
        assert isinstance(d, dict)
        for key in ("summary", "checks", "container"):
            assert key in d
        assert isinstance(d["checks"], list)
        assert isinstance(d["summary"], dict)

    def test_parses_self_test(self, monkeypatch):
        import sndr.product_api.legacy.container_ops as co

        monkeypatch.setattr(apply_summary, "_running_engine_name", lambda: "vllm-x")

        class _Res:
            exit_code = 0
            stdout = '{"summary": {"passed": 6, "failed": 0, "warned": 2, "total": 8}, "checks": [{"name": "P67", "status": "pass", "message": ""}]}'

        class _Ctl:
            def __init__(self, **_kw):
                pass

            def exec(self, name, argv, *, timeout=30.0):
                assert name == "vllm-x" and "self-test" in argv
                return _Res()

        monkeypatch.setattr(co, "SocketContainerControl", _Ctl)
        d = apply_summary.apply_summary()
        assert d["summary"]["passed"] == 6 and d["summary"]["total"] == 8
        assert d["checks"][0]["name"] == "P67"
        assert d["container"] == "vllm-x"

    def test_fail_safe_on_nonzero_rc(self, monkeypatch):
        import sndr.product_api.legacy.container_ops as co

        monkeypatch.setattr(apply_summary, "_running_engine_name", lambda: "vllm-x")

        class _Res:
            exit_code = 3
            stdout = ""

        class _Ctl:
            def __init__(self, **_kw):
                pass

            def exec(self, name, argv, *, timeout=30.0):
                return _Res()

        monkeypatch.setattr(co, "SocketContainerControl", _Ctl)
        d = apply_summary.apply_summary()
        assert d["error"] == "self_test_rc_3" and d["summary"] == {}
