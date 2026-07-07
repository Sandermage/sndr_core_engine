# SPDX-License-Identifier: Apache-2.0
"""UX GROUP-CLI — additive ``sndr up`` branches (remote pivot + pinned default).

These assert ONLY the new additive behavior; the existing ``up`` seams and
return codes are exercised by ``test_up_open_down.py`` and stay untouched:

  * empty rig + ``SNDR_OPENAI_BASE_URL`` -> auto no-engine daemon path (instead
    of the return-2 "no preset fits"); no remote -> still return 2;
  * a pinned default preset is consulted BEFORE the top-fit when no preset arg
    is given;
  * the post-boot ``_maybe_offer_set_default`` seam is guarded by ``--no-input``.
"""
from __future__ import annotations

import argparse
import io
from contextlib import redirect_stderr, redirect_stdout

import pytest

pytest.importorskip("pydantic")

import sndr.cli.commands.up as up_mod  # noqa: E402
from sndr.cli.commands.up import UpCommand  # noqa: E402

TWO_A5000 = "RTX A5000:24564:8.6;RTX A5000:24564:8.6"


def _up_ns(**kw):
    base = {
        "preset": None, "rig": None, "fake_gpus": None, "port": None, "gui_port": 8765,
        "dry_run": False, "no_input": False, "no_engine": False, "timeout": 300,
        "output": "text",
    }
    base.update(kw)
    return argparse.Namespace(**base)


def _patch_pipeline(monkeypatch, *, events, engine_ok=True, daemon_ok=True):
    def fake_ensure_weights(preset_id, *, dry_run=False):
        events.append(("ensure_weights", preset_id))
        return 0

    def fake_launch_engine(preset_id, *, port=None, dry_run=False):
        events.append(("launch_engine", preset_id, port))
        return 0

    def fake_wait_engine(host, port, *, timeout, on_progress=None):
        events.append(("wait_engine", host, port))
        return {"reachable": engine_ok, "models": ["m"], "error": None}

    def fake_start_daemon(host, port):
        events.append(("start_daemon", host, port))
        return object()

    def fake_wait_daemon(host, port, *, timeout):
        events.append(("wait_daemon", host, port))
        return daemon_ok

    monkeypatch.setattr(up_mod, "_ensure_weights", fake_ensure_weights)
    monkeypatch.setattr(up_mod, "_launch_engine_detached", fake_launch_engine)
    monkeypatch.setattr(up_mod, "_wait_engine_ready", fake_wait_engine)
    monkeypatch.setattr(up_mod, "_start_daemon", fake_start_daemon)
    monkeypatch.setattr(up_mod, "_wait_daemon_ready", fake_wait_daemon)


def _run(ns):
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(out):
        rc = UpCommand().execute(ns)
    return rc, out.getvalue()


# ── remote pivot ─────────────────────────────────────────────────────────────


def test_empty_rig_with_remote_pivots_to_no_engine(monkeypatch):
    events: list = []
    _patch_pipeline(monkeypatch, events=events)
    monkeypatch.setenv("SNDR_OPENAI_BASE_URL", "http://192.168.1.10:8102/v1")
    # fake_gpus="" -> an empty rig -> nothing fits -> would normally return 2.
    rc, _ = _run(_up_ns(fake_gpus="", no_input=True))
    kinds = [e[0] for e in events]
    assert rc == 0
    assert "launch_engine" not in kinds  # no engine in client mode
    assert "start_daemon" in kinds       # daemon still comes up


def test_empty_rig_no_remote_still_returns_2(monkeypatch):
    events: list = []
    _patch_pipeline(monkeypatch, events=events)
    monkeypatch.delenv("SNDR_OPENAI_BASE_URL", raising=False)
    rc, _ = _run(_up_ns(fake_gpus="", no_input=True))
    assert rc == 2
    assert events == []


# ── pinned default consulted before top-fit ──────────────────────────────────


def test_pinned_default_consulted_before_top_fit(monkeypatch):
    events: list = []
    _patch_pipeline(monkeypatch, events=events)
    monkeypatch.setattr(
        up_mod.user_prefs, "get_default_preset",
        lambda model_key=None: "prod-qwen3.6-35b-balanced",
    )
    rc, _ = _run(_up_ns(fake_gpus=TWO_A5000, no_input=True))
    assert rc == 0
    launched = [e for e in events if e[0] == "launch_engine"]
    assert launched
    assert launched[0][1] == "prod-qwen3.6-35b-balanced"


# ── post-boot offer gated by --no-input ──────────────────────────────────────


def test_offer_not_called_with_no_input(monkeypatch):
    events: list = []
    _patch_pipeline(monkeypatch, events=events)
    offered: list = []
    monkeypatch.setattr(up_mod, "_maybe_offer_set_default", offered.append)
    _run(_up_ns(fake_gpus=TWO_A5000, no_input=True))
    assert offered == []


def test_offer_called_without_no_input(monkeypatch):
    events: list = []
    _patch_pipeline(monkeypatch, events=events)
    offered: list = []
    monkeypatch.setattr(up_mod, "_maybe_offer_set_default", offered.append)
    _run(_up_ns(fake_gpus=TWO_A5000, no_input=False))
    assert len(offered) == 1
