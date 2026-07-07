# SPDX-License-Identifier: Apache-2.0
"""UX GROUP-CLI (GAP 2) — ``sndr chat`` honors the remote-engine env.

When a Mac/Windows client is pointed at a remote rig via
``SNDR_OPENAI_BASE_URL`` (+ ``SNDR_ENGINE_API_KEY``), a bare ``sndr chat`` must
probe THAT engine — parsing host/port from the base URL and passing the key —
instead of the localhost:8000 default. Explicit ``--host`` / ``--port`` /
preset STILL win; the local default path is unchanged when no remote env is set.
"""
from __future__ import annotations

import argparse
import io
from contextlib import redirect_stderr, redirect_stdout

import pytest

pytest.importorskip("pydantic")

from sndr.cli.commands.chat import ChatCommand  # noqa: E402


def _ns(**kw):
    base = {"preset": None, "port": None, "host": "127.0.0.1", "api_key": None, "output": "text"}
    base.update(kw)
    return argparse.Namespace(**base)


def _patch_status(monkeypatch):
    """Capture the engine_status call kwargs; report unreachable so the command
    returns before opening a REPL."""
    calls: list = []

    def fake_status(host=None, *, port=None, timeout=3.0, api_key=None):
        calls.append({"host": host, "port": port, "api_key": api_key})
        return {"reachable": False, "error": "stub"}

    from sndr.product_api.legacy import engine_client

    monkeypatch.setattr(engine_client, "engine_status", fake_status)
    return calls


def _run(ns):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return ChatCommand().execute(ns)


def test_remote_env_probes_remote_host_with_key(monkeypatch):
    calls = _patch_status(monkeypatch)
    monkeypatch.setenv("SNDR_OPENAI_BASE_URL", "http://192.168.1.10:8102/v1")
    monkeypatch.setenv("SNDR_ENGINE_API_KEY", "genesis-local")

    _run(_ns())
    assert calls, "engine_status must be probed"
    assert calls[0]["host"] == "192.168.1.10"
    assert calls[0]["port"] == 8102
    assert calls[0]["api_key"] == "genesis-local"


def test_explicit_host_still_overrides_remote_env(monkeypatch):
    calls = _patch_status(monkeypatch)
    monkeypatch.setenv("SNDR_OPENAI_BASE_URL", "http://192.168.1.10:8102/v1")
    monkeypatch.setenv("SNDR_ENGINE_API_KEY", "genesis-local")

    _run(_ns(host="10.0.0.5", port=9001))
    assert calls[0]["host"] == "10.0.0.5"
    assert calls[0]["port"] == 9001


def test_api_key_flag_threads_through(monkeypatch):
    calls = _patch_status(monkeypatch)
    monkeypatch.setenv("SNDR_OPENAI_BASE_URL", "http://192.168.1.10:8102/v1")
    monkeypatch.delenv("SNDR_ENGINE_API_KEY", raising=False)

    _run(_ns(api_key="flag-key"))
    assert calls[0]["api_key"] == "flag-key"


def test_local_default_path_unchanged_without_remote(monkeypatch):
    calls = _patch_status(monkeypatch)
    monkeypatch.delenv("SNDR_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("SNDR_ENGINE_API_KEY", raising=False)

    _run(_ns())
    assert calls[0]["host"] == "127.0.0.1"
    assert calls[0]["port"] == 8000
