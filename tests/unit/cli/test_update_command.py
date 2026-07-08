# SPDX-License-Identifier: Apache-2.0
"""`sndr update` — the one-command "keep my install current + healthy" front door.

Contract:

  * Registered on the curated dispatcher as `update`.
  * DEFAULT (check) mode is read-only: it reports the installed version, the
    engine pin, and whether the local repo is behind upstream — it MUST NOT
    mutate anything and MUST NOT pull a new engine image (vLLM pin policy).
  * `--apply` runs the product update (git fast-forward + editable reinstall)
    via an injectable runner, then points at the integrity re-check.
  * The status text always states that engine-pin changes are operator-gated,
    so a user never mistakes `sndr update` for an engine upgrade.
"""
from __future__ import annotations

import argparse

import pytest

pytest.importorskip("pydantic")

from sndr.cli.commands import COMMAND_REGISTRY  # noqa: E402
from sndr.cli.commands import update as update_mod  # noqa: E402


@pytest.fixture(autouse=True)
def _populate_registry():
    """COMMAND_REGISTRY is filled by build_subparsers at parser-build time."""
    from sndr.cli.main import build_parser

    build_parser()


def test_update_command_registered():
    assert "update" in COMMAND_REGISTRY
    cmd = COMMAND_REGISTRY["update"]
    assert cmd.name == "update"
    assert cmd.help


def test_home_dir_respects_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SNDR_HOME", str(tmp_path))
    assert update_mod._home_dir() == tmp_path


def test_home_dir_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("SNDR_HOME", raising=False)
    # Falls back to ~/.sndr — the install.sh default.
    assert update_mod._home_dir().name == ".sndr"


def test_render_status_shows_version_and_pin():
    out = update_mod.render_status(
        version="12.1.0", pin="0.23.1rc1.dev748", behind=0, home="/x", applied=False
    )
    assert "12.1.0" in out
    assert "0.23.1rc1.dev748" in out
    assert "up to date" in out.lower() or "up-to-date" in out.lower()


def test_render_status_reports_behind_count():
    out = update_mod.render_status(
        version="12.1.0", pin="p", behind=3, home="/x", applied=False
    )
    assert "3" in out
    assert "behind" in out.lower()


def test_render_status_states_pin_policy():
    """The output must make clear the engine pin is NOT auto-upgraded."""
    out = update_mod.render_status(
        version="12.1.0", pin="p", behind=0, home="/x", applied=False
    )
    low = out.lower()
    assert "pin" in low
    assert "operator" in low or "not " in low or "gated" in low


def test_behind_count_parses_git_output():
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        # `git rev-list --count HEAD..@{u}` → number of upstream-ahead commits
        class R:
            returncode = 0
            stdout = "4\n"
        return R()

    n = update_mod._behind_count("/repo", runner=fake_run)
    assert n == 4
    # It must have fetched then counted — never pulled/merged in check mode.
    joined = " ".join(" ".join(c) for c in calls)
    assert "rev-list" in joined
    assert "pull" not in joined
    assert "merge" not in joined


def test_behind_count_unknown_on_error():
    def fake_run(cmd, **kw):
        class R:
            returncode = 128
            stdout = ""
        return R()

    assert update_mod._behind_count("/repo", runner=fake_run) is None


def test_execute_check_mode_does_not_mutate(monkeypatch, tmp_path):
    """Default execute() must never call the mutating runner."""
    monkeypatch.setenv("SNDR_HOME", str(tmp_path))
    mutations = []
    monkeypatch.setattr(
        update_mod, "_apply_update",
        lambda *a, **k: mutations.append(a) or 0,
    )
    # No fetch → deterministic offline.
    args = argparse.Namespace(apply=False, yes=False, json=False, no_fetch=True)
    rc = COMMAND_REGISTRY["update"].execute(args)
    assert rc == 0
    assert mutations == [], "check mode must not apply an update"


def test_execute_apply_invokes_update(monkeypatch, tmp_path):
    monkeypatch.setenv("SNDR_HOME", str(tmp_path))
    applied = []
    monkeypatch.setattr(
        update_mod, "_apply_update",
        lambda *a, **k: applied.append(True) or 0,
    )
    args = argparse.Namespace(apply=True, yes=True, json=False, no_fetch=True)
    rc = COMMAND_REGISTRY["update"].execute(args)
    assert rc == 0
    assert applied == [True]


def test_apply_update_runs_pull_then_reinstall():
    cmds = []

    def fake_run(cmd, **kw):
        cmds.append(cmd)
        class R:
            returncode = 0
            stdout = ""
        return R()

    rc = update_mod._apply_update("/repo", runner=fake_run)
    assert rc == 0
    joined = [" ".join(c) for c in cmds]
    # Must fast-forward pull the product repo AND reinstall the package.
    assert any("pull" in c and "--ff-only" in c for c in joined), joined
    assert any("pip" in c and "install" in c for c in joined), joined
    # Policy: never pulls a docker/engine image.
    assert not any("docker" in c and "pull" in c for c in joined)
