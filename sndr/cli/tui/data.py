# SPDX-License-Identifier: Apache-2.0
"""Read-only data facade for the ``sndr tui`` cockpit.

The Textual app owns NO business logic. Every live value it shows comes through
this thin facade, which simply calls the SAME seams the CLI already uses:

  * the fit-ranked preset catalog → :func:`launch_wizard.build_catalog` (the
    exact rows ``sndr`` / ``sndr run`` rank), against a rig resolved the same way
    ``sndr launch`` resolves it (``--fake-gpus`` > ``--rig`` > live detect);
  * the live engine status + KPIs → ``engine_client.engine_status`` /
    ``engine_metrics`` (the same probes ``sndr run`` / ``sndr up`` poll).

Keeping it here (a) makes the app a provable view-over-the-CLI, not a parallel
implementation, and (b) gives the tests one small surface to fake instead of
mocking Textual's data flow. Every call is defensive — a down engine or a
GPU-less box yields a structured payload, never a crash (Phase 1 is read-only).
"""
from __future__ import annotations

from typing import Any, Optional


def resolve_rig(rig: Optional[str] = None, fake_gpus: Optional[str] = None):
    """Resolve the rig to plan the catalog against, mirroring ``sndr launch``.

    Precedence: ``--fake-gpus`` (synthetic) > ``--rig`` (named builtin) > live
    ``RigProbe().detect()``. A GPU-less detect returns a 0-GPU rig (the catalog
    then shows nothing fitting + a "pass --fake-gpus to plan" hint) rather than
    failing — the TUI must open on any box.
    """
    from sndr.model_configs.preflight_fit import (
        RigProbe,
        rig_from_fake_spec,
        rig_from_hardware_def,
    )

    if fake_gpus:
        return rig_from_fake_spec(fake_gpus)
    if rig:
        from sndr.model_configs.registry_v2 import load_hardware

        return rig_from_hardware_def(load_hardware(rig), source=f"rig:{rig}")
    return RigProbe().detect()


def load_catalog(rig: Optional[str] = None, fake_gpus: Optional[str] = None):
    """The evaluated, fit-ranked preset catalog for the resolved rig.

    Returns the wizard's :class:`Catalog` (``.rig`` + sorted ``.candidates`` with
    a fit verdict, status and measured-metric label per row). Reuses
    ``build_catalog`` verbatim — no new projection.
    """
    from sndr.cli.wizard.launch_wizard import build_catalog
    from sndr.model_configs.registry_v2 import (
        list_presets,
        load_alias,
        load_preset_def,
    )

    rig_obj = resolve_rig(rig, fake_gpus)
    return build_catalog(
        rig_obj,
        preset_ids=list_presets(),
        card_loader=load_preset_def,
        cfg_loader=load_alias,
    )


def engine_snapshot(host: Optional[str] = None, port: Optional[int] = None) -> dict[str, Any]:
    """Live engine status + KPIs, both defensive.

    ``{"status": <engine_status>, "metrics": <engine_metrics>}``. An unreachable
    engine or a probe error yields a structured ``reachable: False`` payload so
    the cockpit can render a calm "no engine — run `sndr run`" state.
    """
    from sndr.product_api.legacy.engine_client import engine_metrics, engine_status

    try:
        status = engine_status(host, port=port)
    except Exception as exc:  # pragma: no cover — defensive
        status = {"reachable": False, "error": str(exc)}
    try:
        metrics = engine_metrics(host, port=port)
    except Exception as exc:  # pragma: no cover — defensive
        metrics = {"reachable": False, "error": str(exc), "kpis": {}}
    return {"status": status, "metrics": metrics}


def serve(preset_id: str, *, port: Optional[int] = None) -> dict[str, Any]:
    """Launch a preset's engine, the SAME pipeline ``sndr run`` uses — minus the
    blocking wait/chat (the cockpit's 3s engine refresh shows it come up).

    Two steps, both reused verbatim from :mod:`sndr.cli.commands.run`:
    ``_pull_if_missing`` (a no-op when the weights are already present) then
    ``_launch_detached`` (``docker run -d`` via a child ``sndr launch``, so it
    returns once the container is up). Returns a structured
    ``{"ok", "preset_id", "rc", "error"}`` — never raises, so the worker that
    calls it can paint a calm log line on any failure.
    """
    from sndr.cli.commands.run import _launch_detached, _pull_if_missing

    try:
        rc = _pull_if_missing(preset_id, dry_run=False)
        if rc not in (0, None):
            return {"ok": False, "preset_id": preset_id, "rc": rc,
                    "error": f"weights not ready (pull rc={rc})"}
        rc = _launch_detached(preset_id, port=port, dry_run=False)
        if rc not in (0, None):
            return {"ok": False, "preset_id": preset_id, "rc": rc,
                    "error": f"launch failed (rc={rc})"}
        return {"ok": True, "preset_id": preset_id, "rc": 0, "error": None}
    except Exception as exc:  # pragma: no cover — defensive; the worker logs it
        return {"ok": False, "preset_id": preset_id, "rc": 1, "error": str(exc)}


def stop(preset_id: str, *, dry_run: bool = False) -> dict[str, Any]:
    """Stop a preset's engine container — reuses ``up._stop_engine`` (the same
    ``docker stop`` verb ``sndr down`` shells out to). Idempotent: a no-match
    returns ``stopped=False`` but still ``ok=True`` (pressing k twice is safe).
    Never raises.
    """
    from sndr.cli.commands.up import _stop_engine

    try:
        stopped = bool(_stop_engine(preset_id, dry_run=dry_run))
        return {"ok": True, "preset_id": preset_id, "stopped": stopped, "error": None}
    except Exception as exc:  # pragma: no cover — defensive
        return {"ok": False, "preset_id": preset_id, "stopped": False, "error": str(exc)}


def run_doctor() -> int:
    """Run the SAME ``doctor`` diagnostic the CLI promotes — through the
    ``sndr.compat.cli`` bridge the ``DoctorCommand`` pass-through targets — so the
    cockpit's ``d`` key and ``sndr doctor`` cannot drift. The app calls this under
    ``App.suspend()`` (it prints to the real terminal). Returns the doctor rc.
    """
    from sndr.compat import cli as _compat_cli

    return _compat_cli.main(["doctor"])


def run_chat(preset_id: Optional[str] = None, *, host: str = "127.0.0.1",
             port: Optional[int] = None) -> int:
    """Open the SAME thin REPL ``sndr chat`` uses — the native ``ChatCommand``
    (which probes the engine then drops into :func:`chat_repl.chat_loop`, the
    chat path the GUI shares). The app calls this under ``App.suspend()`` so the
    REPL owns the real terminal, then restores the cockpit on exit. Returns the
    chat rc (1 = no engine reachable, with a friendly pointer).
    """
    import argparse

    from sndr.cli.commands.chat import ChatCommand

    ns = argparse.Namespace(preset=preset_id, host=host, port=port)
    return ChatCommand().execute(ns)


def _settings_path():
    """The TUI settings file under SNDR_HOME (same state dir the daemon uses)."""
    import os
    from pathlib import Path

    home = os.environ.get("SNDR_HOME") or os.path.join(Path.home(), ".sndr")
    base = Path(home) / "state"
    base.mkdir(parents=True, exist_ok=True)
    return base / "tui_settings.json"


def load_settings() -> dict[str, str]:
    """Current Model Dir + HF token for the Settings modal to pre-fill.

    Precedence: a saved ``tui_settings.json`` wins; otherwise the live env
    (``SNDR_MODELS_DIR`` / ``HF_TOKEN``) — what the engine actually uses today —
    so the modal opens showing the real state, not blanks.
    """
    import json
    import os

    saved: dict[str, Any] = {}
    try:
        saved = json.loads(_settings_path().read_text(encoding="utf-8"))
    except Exception:  # pragma: no cover — no/garbled state file is fine
        saved = {}
    return {
        "model_dir": saved.get("model_dir") or os.environ.get("SNDR_MODELS_DIR", ""),
        "hf_token": saved.get("hf_token") or os.environ.get("HF_TOKEN", ""),
    }


def save_settings(*, model_dir: str = "", hf_token: str = "") -> dict[str, Any]:
    """Persist + apply Model Dir / HF token.

    Applies to the LIVE process env (``SNDR_MODELS_DIR`` / ``HF_TOKEN``) so this
    session's serve/pull — and the child ``sndr launch`` that inherits the env —
    use them immediately, and writes them under SNDR_HOME so the next launch
    loads them. A blank field is a no-op for that key (editing the dir never
    wipes a configured token). Never raises.
    """
    import json
    import os

    try:
        current = load_settings()
        model_dir = (model_dir or "").strip() or current["model_dir"]
        hf_token = (hf_token or "").strip() or current["hf_token"]
        if model_dir:
            os.environ["SNDR_MODELS_DIR"] = model_dir
        if hf_token:
            os.environ["HF_TOKEN"] = hf_token
        _settings_path().write_text(
            json.dumps({"model_dir": model_dir, "hf_token": hf_token},
                       indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return {"ok": True, "model_dir": model_dir, "error": None}
    except Exception as exc:  # pragma: no cover — defensive
        return {"ok": False, "model_dir": model_dir, "error": str(exc)}


def apply_saved_settings() -> None:
    """Apply persisted Model Dir / HF token to the process env at startup, so the
    cockpit's serve/pull use the operator's saved config without re-typing."""
    import os

    s = load_settings()
    if s.get("model_dir"):
        os.environ["SNDR_MODELS_DIR"] = s["model_dir"]
    if s.get("hf_token"):
        os.environ["HF_TOKEN"] = s["hf_token"]


def rig_summary(rig) -> str:
    """One-line rig description for the header (matches the wizard's wording)."""
    gpus = getattr(rig, "gpu_count", 0) or 0
    vram = getattr(rig, "min_vram_gb", None)
    cap = getattr(rig, "min_compute_cap", None)
    parts = [f"{gpus} GPU(s)"]
    if vram:
        parts.append(f"{vram} GB/GPU")
    if cap:
        parts.append(f"sm_{cap[0]}.{cap[1]}")
    src = getattr(rig, "source", "rig")
    return f"{src} ({', '.join(parts)})"


__all__ = ["resolve_rig", "load_catalog", "engine_snapshot", "rig_summary"]
