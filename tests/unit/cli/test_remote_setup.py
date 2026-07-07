# SPDX-License-Identifier: Apache-2.0
"""UX GROUP-CLI (GAP 1) — ``sndr remote setup`` client onboarding.

Configures THIS machine to drive a remote rig engine (Mac/Windows client mode).
It validates the URL form (GUARD-1 loud typed refusal on a bad URL), probes
reachability best-effort, persists the last-used remote, and prints the three
canonical exports with a "shell env wins" note.
"""
from __future__ import annotations

import argparse
import io
from contextlib import redirect_stderr, redirect_stdout

import pytest

pytest.importorskip("pydantic")

import sndr.cli.commands.remote as remote_mod  # noqa: E402
from sndr.cli import user_prefs  # noqa: E402
from sndr.cli.commands.remote import RemoteSetupCommand  # noqa: E402


def _ns(**kw):
    base = {
        "remote_cmd": "setup", "url": None, "key": "genesis-local",
        "dsn": None, "write_env": False, "output": "text",
    }
    base.update(kw)
    return argparse.Namespace(**base)


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("SNDR_HOME", str(tmp_path))
    # Keep the probe offline/deterministic.
    monkeypatch.setattr(
        remote_mod, "_probe_remote",
        lambda host, port, key: {"reachable": False, "error": "offline in test"},
    )
    return tmp_path


def _run(ns):
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(out):
        rc = RemoteSetupCommand().execute(ns)
    return rc, out.getvalue()


def test_setup_prints_three_exports_and_persists(monkeypatch):
    rc, text = _run(_ns(url="http://192.168.1.10:8102/v1", key="genesis-local"))
    assert rc == 0
    assert "SNDR_OPENAI_BASE_URL" in text
    assert "SNDR_ENGINE_API_KEY" in text
    assert "GENESIS_MEMORY_DSN" in text
    # persisted for next time
    r = user_prefs.get_last_remote()
    assert r is not None
    assert r["url"] == "http://192.168.1.10:8102/v1"
    assert r["key"] == "genesis-local"


def test_bad_url_form_is_a_typed_refusal():
    rc, text = _run(_ns(url="not-a-real-url"))
    assert rc == 64  # EX_USAGE — loud typed refusal
    assert "url" in text.lower()


def test_write_env_writes_dotenv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc, _ = _run(_ns(url="http://192.168.1.10:8102/v1", write_env=True))
    assert rc == 0
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "SNDR_OPENAI_BASE_URL=http://192.168.1.10:8102/v1" in env
