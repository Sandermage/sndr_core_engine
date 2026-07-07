# SPDX-License-Identifier: Apache-2.0
"""UX GROUP-CLI — ``sndr quickstart`` (the zero-decision front door).

``quickstart`` detects the rig + OS, resolves a fitting preset via the
progressive ladder (explicit > pinned default > top-fit), prints the per-card
VRAM projection with a hard FAIL gate, and delegates the actual bring-up to the
EXISTING ``sndr up`` seams — it never reimplements an engine or a server.

Every side-effectful step is mocked; these tests assert only wiring + policy:

  * registration on the canonical surface;
  * ``--fake-gpus … --no-input --dry-run`` resolves a fitting preset and never
    reads stdin (PICKER-2 non-interactive escape);
  * a non-fitting rig -> FAIL projection -> exit 2 unless ``--force`` (VRAM-1);
  * empty rig + ``SNDR_OPENAI_BASE_URL`` -> pivots to no-engine client mode
    (GAP 3), with NO engine launch;
  * empty rig + NO remote -> exit 2 with the actionable remote-setup hint
    (never a bare "no preset fits");
  * a pinned default is chosen over the top-fit, and the post-boot "make
    default?" offer only fires when not ``--no-input`` (DEFAULT-1).
"""
from __future__ import annotations

import argparse
import io
from contextlib import redirect_stderr, redirect_stdout

import pytest

pytest.importorskip("pydantic")

import sndr.cli.commands.quickstart as qs  # noqa: E402
from sndr.cli.commands.quickstart import QuickstartCommand  # noqa: E402
from sndr.model_configs.preflight_fit import DetectedGpu, Rig  # noqa: E402

TWO_A5000 = "RTX A5000:24564:8.6;RTX A5000:24564:8.6"


def _ns(**kw):
    base = {
        "preset": None,
        "no_input": False,
        "force": False,
        "gui_port": 8765,
        "dry_run": False,
        "rig": None,
        "fake_gpus": None,
        "output": "text",
    }
    base.update(kw)
    return argparse.Namespace(**base)


def _empty_rig() -> Rig:
    return Rig(gpus=[], source="nvidia-smi")


def _a5000_rig() -> Rig:
    g = [DetectedGpu(index=i, name="RTX A5000", vram_mib=24564, compute_cap=(8, 6)) for i in range(2)]
    return Rig(gpus=g, source="fake")


def _run(cmd, ns):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cmd.execute(ns)
    return rc, out.getvalue() + err.getvalue()


# ── 1. registration ──────────────────────────────────────────────────────────


def test_quickstart_registered():
    from sndr.cli.commands import COMMAND_REGISTRY
    from sndr.cli.main import build_parser

    build_parser()
    assert "quickstart" in COMMAND_REGISTRY


# ── 2. non-interactive dry-run resolves a fitting preset, never reads stdin ───


def test_dry_run_no_input_resolves_and_never_reads_stdin(monkeypatch):
    def _boom(*a, **k):  # any stdin read is a bug in the non-interactive path
        raise AssertionError("quickstart read stdin in --no-input mode")

    monkeypatch.setattr("builtins.input", _boom)
    booted: list = []
    monkeypatch.setattr(qs, "_boot", lambda ns: booted.append(ns) or 0)

    rc, text = _run(QuickstartCommand(), _ns(fake_gpus=TWO_A5000, no_input=True, dry_run=True))
    assert rc == 0
    assert booted == []  # dry-run starts nothing
    # A concrete fitting preset name is surfaced.
    assert "prod-qwen3.6-35b" in text


# ── 3. non-fitting rig -> FAIL projection -> exit 2 unless --force ────────────


def test_non_fitting_rig_fails_projection(monkeypatch):
    tiny = Rig(gpus=[DetectedGpu(index=0, name="TinyGPU", vram_mib=2048, compute_cap=(8, 6))], source="fake")
    monkeypatch.setattr(qs, "_detect_rig", lambda args: tiny)
    monkeypatch.setattr(qs, "_boot", lambda ns: 0)

    # Explicit heavy preset on a 2 GiB card -> byte-level projection FAILs.
    rc, text = _run(QuickstartCommand(), _ns(preset="prod-qwen3.6-35b-balanced", no_input=True))
    assert rc == 2
    assert "force" in text.lower()


def test_non_fitting_rig_force_overrides(monkeypatch):
    tiny = Rig(gpus=[DetectedGpu(index=0, name="TinyGPU", vram_mib=2048, compute_cap=(8, 6))], source="fake")
    monkeypatch.setattr(qs, "_detect_rig", lambda args: tiny)
    booted: list = []
    monkeypatch.setattr(qs, "_boot", lambda ns: booted.append(ns) or 0)

    rc, _ = _run(QuickstartCommand(), _ns(preset="prod-qwen3.6-35b-balanced", no_input=True, force=True))
    assert rc == 0
    assert len(booted) == 1  # --force pushes past the FAIL gate


# ── 4. remote pivot: empty rig + SNDR_OPENAI_BASE_URL -> client mode ──────────


def test_empty_rig_with_remote_pivots_to_no_engine(monkeypatch):
    monkeypatch.setattr(qs, "_detect_rig", lambda args: _empty_rig())
    monkeypatch.setenv("SNDR_OPENAI_BASE_URL", "http://192.168.1.10:8102/v1")
    booted: list = []
    monkeypatch.setattr(qs, "_boot", lambda ns: booted.append(ns) or 0)

    rc, text = _run(QuickstartCommand(), _ns(no_input=True))
    assert rc == 0
    assert len(booted) == 1
    assert booted[0].no_engine is True  # daemon-only, no engine launch
    assert "192.168.1.10:8102" in text


def test_empty_rig_no_remote_gives_setup_hint(monkeypatch):
    monkeypatch.setattr(qs, "_detect_rig", lambda args: _empty_rig())
    monkeypatch.delenv("SNDR_OPENAI_BASE_URL", raising=False)
    booted: list = []
    monkeypatch.setattr(qs, "_boot", lambda ns: booted.append(ns) or 0)

    rc, text = _run(QuickstartCommand(), _ns(no_input=True))
    assert rc == 2
    assert booted == []
    assert "remote setup" in text.lower()
    assert "no preset fits" not in text.lower()  # not the bare error


# ── 5. pinned default beats top-fit; post-boot offer gated by --no-input ──────


def test_pinned_default_beats_top_fit(monkeypatch):
    monkeypatch.setattr(qs, "_detect_rig", lambda args: _a5000_rig())
    # Pin a fitting preset that is NOT the top-fit.
    monkeypatch.setattr(qs.user_prefs, "get_default_preset", lambda model_key=None: "prod-qwen3.6-35b-balanced")
    booted: list = []
    monkeypatch.setattr(qs, "_boot", lambda ns: booted.append(ns) or 0)
    offered: list = []
    monkeypatch.setattr(qs, "_maybe_offer_set_default", lambda pid, **k: offered.append(pid))

    rc, _ = _run(QuickstartCommand(), _ns(no_input=True))
    assert rc == 0
    assert booted[0].preset == "prod-qwen3.6-35b-balanced"
    # --no-input suppresses the interactive "make default?" offer.
    assert offered == []


def test_post_boot_offer_fires_when_interactive(monkeypatch):
    monkeypatch.setattr(qs, "_detect_rig", lambda args: _a5000_rig())
    monkeypatch.setattr(qs.user_prefs, "get_default_preset", lambda model_key=None: None)
    monkeypatch.setattr(qs, "_boot", lambda ns: 0)
    offered: list = []
    monkeypatch.setattr(qs, "_maybe_offer_set_default", lambda pid, **k: offered.append(pid))

    rc, _ = _run(QuickstartCommand(), _ns(no_input=False))
    assert rc == 0
    assert len(offered) == 1  # interactive => the offer seam is invoked
