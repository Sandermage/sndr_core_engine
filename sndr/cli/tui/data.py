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
