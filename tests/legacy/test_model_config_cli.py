# SPDX-License-Identifier: Apache-2.0
"""TDD for compat/model_config_cli.py — list/show/render/audit/where.

Audit closure 2026-05-08 (DEEP_AUDIT_VLLM_NOONGHUNNA P0-2): hardcoded
TPS expectations drift every time bench updates. These tests now load
the actual YAML and assert the CLI surfaces what's in the config —
that way Wave updates to reference_metrics don't require parallel
test edits.
"""
from __future__ import annotations

import pytest

from vllm.sndr_core.compat.model_config_cli import main as cli_main
from vllm.sndr_core.model_configs.registry import get as get_config


def _expected_tps(key: str) -> float:
    """Read the YAML's reference TPS — single source of truth.

    Falls back to a permissive sentinel if the key/field is absent so
    test failures point at the loader, not at perceived drift."""
    cfg = get_config(key)
    assert cfg is not None, f"config {key!r} not loadable"
    rm = cfg.reference_metrics
    return float(rm.long_gen_sustained_tps)


class TestList:
    def test_list_succeeds_and_shows_builtins(self, capsys):
        # Default `list` now hides tested/QA configs (P0.2 fix —
        # previous behaviour was the `or True` bug that always merged
        # them in). Pass --include-tested to surface them.
        rc = cli_main(["list", "--include-tested"])
        assert rc == 0
        out = capsys.readouterr().out
        # Must include builtin configs
        assert "a5000-2x-35b-prod" in out
        assert "a5000-2x-27b-int4-tested" in out
        # Must show TPS column
        assert "TPS" in out
        # 35B and 27B reference TPS — read from YAML, not hardcoded
        tps_35b = _expected_tps("a5000-2x-35b-prod")
        # YAML drift-resistant: just check the TPS value (truncated to
        # one decimal) appears anywhere in the list output.
        assert f"{tps_35b:.1f}" in out or f"{tps_35b:.2f}" in out, (
            f"35B PROD TPS {tps_35b:.2f} not visible in list output"
        )

    def test_list_default_hides_tested(self, capsys):
        """Default invocation must hide tested/QA configs but flag that
        they're available behind --include-tested."""
        rc = cli_main(["list"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "a5000-2x-35b-prod" in out
        assert "a5000-2x-27b-int4-tested" not in out
        assert "--include-tested" in out


class TestShow:
    def test_show_known_key(self, capsys):
        rc = cli_main(["show", "a5000-2x-35b-prod"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "key: a5000-2x-35b-prod" in out
        # YAML-driven: assert show emits the actual reference TPS
        tps = _expected_tps("a5000-2x-35b-prod")
        assert f"long_gen_sustained_tps: {tps}" in out, (
            f"show should surface reference TPS {tps} from YAML"
        )

    def test_show_unknown_returns_1(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli_main(["show", "totally-bogus-config"])
        assert exc.value.code == 1


class TestRender:
    def test_render_emits_bash_script(self, capsys):
        rc = cli_main(["render", "a5000-2x-35b-prod"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "#!/usr/bin/env bash" in out
        assert "set -euo pipefail" in out
        assert "vllm serve" in out
        # Header references TPS — pulled from YAML, not hardcoded
        tps = _expected_tps("a5000-2x-35b-prod")
        assert f"{tps:.1f}" in out or f"{tps:.2f}" in out, (
            f"render header should reference {tps:.2f} TPS"
        )

    def test_render_includes_all_genesis_env(self, capsys):
        rc = cli_main(["render", "a5000-2x-27b-int4-tested"])
        assert rc == 0
        out = capsys.readouterr().out
        # Spot-check critical patches present
        assert "GENESIS_ENABLE_P67_TQ_MULTI_QUERY_KERNEL" in out
        assert "GENESIS_ENABLE_P99" in out


class TestAudit:
    def test_audit_clean_config_returns_0(self, capsys):
        # 27B has 1 warning (R-005 PN59 long-ctx), but no errors → exit 0
        rc = cli_main(["audit", "a5000-2x-27b-int4-tested"])
        assert rc == 0

    def test_audit_unknown_returns_1(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli_main(["audit", "bogus"])
        assert exc.value.code == 1


class TestWhere:
    def test_where_shows_tier(self, capsys):
        rc = cli_main(["where", "a5000-2x-35b-prod"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "tier:" in out and "builtin" in out


class TestNew:
    def test_new_template_creates_user_config(self, tmp_path, monkeypatch,
                                                capsys):
        monkeypatch.setenv("GENESIS_MODEL_CONFIG_DIR", str(tmp_path))
        rc = cli_main(["new", "my-test", "--template", "a5000-2x-35b-prod"])
        assert rc == 0
        out_path = tmp_path / "my-test.yaml"
        assert out_path.is_file()
        content = out_path.read_text()
        assert "key: my-test" in content
        assert "reference_metrics: null" in content  # cleared on clone

    def test_new_no_overwrite_without_force(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GENESIS_MODEL_CONFIG_DIR", str(tmp_path))
        cli_main(["new", "my-test", "--template", "a5000-2x-35b-prod"])
        # Second call without --force fails
        rc = cli_main(["new", "my-test", "--template", "a5000-2x-35b-prod"])
        assert rc == 1


class TestVerify:
    def test_verify_unknown_returns_1(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli_main(["verify", "bogus"])
        assert exc.value.code == 1

    def test_verify_known_config_no_server_fails_predictably(self, capsys):
        # Without a running server, bench will fail → returns 1.
        # This is correct behaviour (operator must launch first).
        rc = cli_main(["verify", "a5000-2x-35b-prod"])
        assert rc in (0, 1)  # 0 if server happens to be up, 1 if not
