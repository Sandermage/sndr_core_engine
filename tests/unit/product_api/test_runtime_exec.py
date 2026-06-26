# SPDX-License-Identifier: Apache-2.0
"""Tests for the gated service-action executor.

Uses only harmless local commands; never touches real containers or the
network. Real server verification is done manually (see the handoff log).
"""
from __future__ import annotations

import pytest

from sndr.product_api.legacy import runtime_exec as rx


def test_apply_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SNDR_ENABLE_APPLY", raising=False)
    assert rx.apply_enabled() is False
    monkeypatch.setenv("SNDR_ENABLE_APPLY", "1")
    assert rx.apply_enabled() is True
    monkeypatch.setenv("SNDR_ENABLE_APPLY", "0")
    assert rx.apply_enabled() is False


def test_exec_command_strips_follow():
    # Follow flags would block forever during execution; they must be stripped.
    assert "-f" not in rx.exec_safe_command("docker logs -f --tail 200 c").split()
    assert rx.exec_safe_command("docker ps --filter name=c") == "docker ps --filter name=c"
    assert "-f" not in rx.exec_safe_command("docker compose -p x logs -f --tail=200")


def test_wrap_ssh_vs_local():
    local = rx.wrap_command("docker ps", transport="local", ssh_target="")
    assert local == "docker ps"
    ssh = rx.wrap_command("docker ps", transport="ssh", ssh_target="user@host")
    assert ssh.startswith("ssh ") and "user@host" in ssh and "docker ps" in ssh
    # legit user@host has no metacharacters -> quoting is a no-op (stays bare)
    assert ssh == "ssh user@host 'docker ps'"


def test_wrap_command_neutralizes_ssh_target_injection():
    """ssh_target can come from the client request body and run_steps uses
    shell=True, so a malicious target must NOT be able to inject a command."""
    import shlex

    evil = "x; touch /tmp/pwned #"
    wrapped = rx.wrap_command("docker ps", transport="ssh", ssh_target=evil)
    # The whole malicious string must collapse to ONE argv token (a bogus
    # hostname), not separate shell words — i.e. no break-out.
    tokens = shlex.split(wrapped)
    assert tokens[0] == "ssh"
    assert tokens[1] == evil            # single token, metacharacters inert
    assert ";" not in wrapped.replace(shlex.quote(evil), "")   # ';' only inside the quoted token


def test_node_launchers_use_membership_check_not_bool():
    """bool('0') is True in Python; the daemon launchers must use a membership
    check so SNDR_ENABLE_APPLY=0 comes up apply-OFF (no silent gate inversion)."""
    from sndr.product_api.legacy import deployment, node_setup

    launcher = node_setup._DAEMON_LAUNCHER.decode()
    assert "bool(os.environ.get('SNDR_ENABLE_APPLY'))" not in launcher
    assert "in ('1','true','yes','on')" in launcher
    # the deployment template string lives inside a function; assert via module source
    import inspect
    dep_src = inspect.getsource(deployment)
    assert "bool(os.environ.get('SNDR_ENABLE_APPLY'))" not in dep_src


def test_run_steps_executes_local_safe_command():
    results = rx.run_steps(
        [("Status", "true"), ("Echo", "echo sndr-ok")],
        transport="local",
        ssh_target="",
        timeout=10,
    )
    assert all(r.exit_code == 0 for r in results)
    assert any("sndr-ok" in r.stdout for r in results)
    assert all(r.status == "ok" for r in results)


def test_run_steps_marks_failure():
    results = rx.run_steps([("Fail", "false")], transport="local", ssh_target="", timeout=10)
    assert results[0].exit_code != 0
    assert results[0].status == "failed"


def test_execute_blocked_when_disabled(monkeypatch):
    monkeypatch.delenv("SNDR_ENABLE_APPLY", raising=False)
    with pytest.raises(rx.ApplyDisabledError):
        rx.execute_service_action(preset_id="prod-qwen3.6-35b-balanced", action="status")


def test_mutating_requires_confirm(monkeypatch):
    monkeypatch.setenv("SNDR_ENABLE_APPLY", "1")
    with pytest.raises(rx.ConfirmationRequiredError):
        rx.execute_service_action(preset_id="prod-qwen3.6-35b-balanced", action="restart", confirm=False)
