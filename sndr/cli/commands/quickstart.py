# SPDX-License-Identifier: Apache-2.0
"""CLI command: ``sndr quickstart`` — the zero-decision front door.

The single command a newcomer runs after ``git clone``: it detects the rig +
OS, resolves a FITTING preset through a progressive ladder, shows the per-card
VRAM projection (with a hard FAIL gate BEFORE any container starts), and hands
the actual bring-up to the EXISTING ``sndr up`` seams. It never reimplements an
engine or a server — it is a thin, opinionated wrapper that removes decisions.

Additive by construction: the expert path (``sndr launch <preset>``,
``sndr up <preset>``, explicit pins) is untouched. ``quickstart`` only adds a
simpler surface on top.

Flow (every interactive step has a non-interactive escape — PICKER-2):

  1. Detect OS + rig (``RigProbe`` / ``--fake-gpus`` / ``--rig``).
  2. REMOTE PIVOT (GAP 3): no local GPU + ``SNDR_OPENAI_BASE_URL`` set -> client
     mode (delegate to the daemon-only ``sndr up --no-engine`` path). No GPU and
     no remote -> the actionable ``sndr remote setup`` hint (never a bare "no
     preset fits").
  3. Preset LADDER (PICKER-3 / DEFAULT-3): explicit arg > pinned default
     (validated) > top-fit. Exactly one fit -> auto; many + TTY -> one-key
     confirm of the top fit; non-TTY / ``--no-input`` -> top fit, never stdin.
  4. VRAM PROJECTION (VRAM-1): print the per-card budget for the chosen preset;
     a FAIL verdict refuses BEFORE boot unless ``--force``.
  5. BOOT: delegate to the existing ``sndr up`` flow (weights -> engine -> ready
     -> daemon -> GUI).
  6. Post-boot (DEFAULT-1): after a green boot, offer to pin the preset as the
     default (opt-IN, only when interactive).

Examples::

    sndr quickstart                       # detect rig -> pick + boot -> GUI
    sndr quickstart prod-qwen3.6-35b-balanced
    sndr quickstart --no-input            # CI / scripted, never prompts
    sndr quickstart --fake-gpus "RTX A5000:24564:8.6;RTX A5000:24564:8.6" --dry-run
"""
from __future__ import annotations

import argparse
import platform
import sys
from typing import Any

from sndr.cli import user_prefs
from sndr.cli._messages import Emitter

_DEFAULT_GUI_PORT = 8765
_REMOTE_ENV = "SNDR_OPENAI_BASE_URL"


class QuickstartCommand:
    name = "quickstart"
    help = "Zero-config bring-up: detect your rig, pick + boot a fitting preset, open the GUI."

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "preset", nargs="?", default=None,
            help="Preset to boot. Omit to auto-pick (pinned default, else the "
                 "top-ranked fitting preset for the detected rig).",
        )
        parser.add_argument(
            "--no-input", action="store_true",
            help="Headless: never prompt on stdin (auto-pick, skip the "
                 "make-default offer).",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Boot even when the VRAM projection says the preset will not "
                 "fit (override the FAIL gate).",
        )
        parser.add_argument(
            "--gui-port", type=int, default=_DEFAULT_GUI_PORT, metavar="PORT",
            help=f"Port for the product-API + GUI daemon (default: {_DEFAULT_GUI_PORT}).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Resolve + project + plan without starting anything.",
        )
        parser.add_argument(
            "--rig", default=None, metavar="HARDWARE_ID",
            help="Resolve the fit against a builtin hardware def (offline).",
        )
        parser.add_argument(
            "--fake-gpus", default=None, metavar="SPEC",
            help="Resolve the fit against a synthetic rig "
                 "'name:vram_mib:cc;...' (offline).",
        )

    # ── dispatch ─────────────────────────────────────────────────────────────

    def execute(self, args: argparse.Namespace) -> int:  # noqa: PLR0911 — linear front-door ladder: one early-return per stage (remote/ladder/projection/dry-run/boot)
        em = Emitter()  # advisory output → stderr (stdout stays scriptable)
        no_input = bool(getattr(args, "no_input", False))
        gui_port = int(getattr(args, "gui_port", _DEFAULT_GUI_PORT))

        os_name = platform.system() or "unknown"
        rig = _detect_rig(args)

        em.blank()
        em.line(f"  sndr quickstart — OS {os_name}, "
                f"{rig.gpu_count} GPU(s) detected ({rig.source})")

        # ── 2) remote pivot (no local GPU) ───────────────────────────────────
        remote_url = _remote_env_url()
        if rig.gpu_count == 0:
            if remote_url:
                em.line(f"  no local GPU — client mode against {remote_url}")
                em.line("  bringing up the daemon + GUI pointed at the remote …")
                ns = _up_namespace(preset=None, gui_port=gui_port, no_engine=True)
                return _boot(ns)
            em.err("no local GPU detected and no remote engine configured.")
            em.hint("point this machine at a rig:  sndr remote setup http://<rig>:8102/v1")
            em.hint("or see docs/REMOTE_ENGINE.md for client-mode setup")
            return 2

        # ── 3) preset ladder ─────────────────────────────────────────────────
        try:
            chosen, why = _resolve_preset(args, rig, em, no_input=no_input)
        except _NoFitError as exc:
            em.err(str(exc))
            em.hint("pick one interactively:  sndr")
            em.hint("or see docs/SINGLE_CARD.md for single-card options")
            return 2
        em.line(f"  preset: {chosen}   ({why})")

        # ── 4) VRAM projection + hard FAIL gate ──────────────────────────────
        projection = _project_vram(chosen, rig)
        if projection is not None:
            _print_projection(em, chosen, rig, projection)
            if getattr(projection, "verdict", None) == "FAIL" and not args.force:
                em.err(f"projection says {chosen} will not fit on your rig — "
                       "refusing to boot.")
                em.hint("override with --force, or pick a lighter preset: sndr")
                return 2

        # ── dry-run: report the plan, start nothing ──────────────────────────
        if args.dry_run:
            url = f"http://127.0.0.1:{gui_port}"
            em.line("  (dry-run) plan:")
            em.line(f"    1. sndr up {chosen}   (weights → engine → ready)")
            em.line(f"    2. start product-API + GUI   ({url})")
            print(f"sndr quickstart plan: {chosen} gui={url}")
            return 0

        # ── 5) boot via the existing `sndr up` flow ──────────────────────────
        ns = _up_namespace(preset=chosen, gui_port=gui_port, no_engine=False)
        rc = _boot(ns)
        if rc != 0:
            return rc

        # ── 6) post-boot: offer to pin the default (opt-in, interactive only) ─
        if not no_input:
            _maybe_offer_set_default(chosen, no_input=no_input)
        return 0


# ── resolution ───────────────────────────────────────────────────────────────


class _NoFitError(Exception):
    """No preset fits the rig and none was named."""


def _lone_user_first(fitting: list[str]) -> list[str]:
    """If the top auto-pick is a peak-throughput ``-multiconc`` preset, promote
    its SAME-MODEL single-stream sibling to the front instead.

    The fit ranking sorts by measured metric desc, which floats ``-multiconc``
    (max_num_seqs=8, ~100% per-card VRAM) above its balanced sibling. A
    zero-decision newcomer gets no benefit from multiconc but takes its OOM
    risk, so for the auto-default we prefer the same model's single-stream
    variant when it also fits. Surgical by design: only swaps a multiconc leader
    for its own sibling — the model choice and cross-model order are untouched,
    and nothing is dropped (if only the multiconc variant fits, it stays). The
    interactive full menu (different code path) is unaffected.
    """
    if not fitting:
        return fitting
    top = fitting[0]
    if "multiconc" not in top.lower():
        return fitting
    stem = top.lower().replace("-multiconc", "")
    for pid in fitting[1:]:
        low = pid.lower()
        if low.startswith(stem) and "multiconc" not in low:
            return [pid] + [x for x in fitting if x != pid]
    return fitting


def _resolve_preset(
    args: argparse.Namespace, rig, em: Emitter, *, no_input: bool,
) -> tuple[str, str]:
    """Resolve (preset_id, reason) via the ladder: explicit > pinned > top-fit.

    Raises :class:`_NoFitError` when nothing fits and no preset was named.
    """
    if args.preset:
        return str(args.preset), "explicit"

    pinned = user_prefs.get_default_preset()
    if pinned:
        return pinned, "your pinned default"

    fitting = _lone_user_first(_fitting_presets(rig))
    if not fitting:
        raise _NoFitError("no preset fits this rig")
    if len(fitting) == 1:
        em.line(f"  using the only fitting preset: {fitting[0]}")
        return fitting[0], "only fit"

    top = fitting[0]
    # Many fit — confirm the top pick when interactive; otherwise take it.
    if not no_input and _is_tty():
        gpu_label = _rig_label(rig)
        if _prompt(em, f"Launch {top} for your {gpu_label}? [Y/n]", default=True):
            return top, "confirmed top fit"
        raise _NoFitError("declined the top fit")
    return top, "top fit"


def _fitting_presets(rig) -> list[str]:
    """The rig-fitting presets, best-first (the same ranking the wizard shows)."""
    from sndr.cli.wizard.launch_wizard import build_catalog
    from sndr.model_configs.registry_v2 import (
        list_presets,
        load_alias,
        load_preset_def,
    )

    catalog = build_catalog(
        rig, preset_ids=list_presets(),
        card_loader=load_preset_def, cfg_loader=load_alias,
    )
    return [c.preset_id for c in catalog.menu(show_all=False)]


def _rig_label(rig) -> str:
    if not getattr(rig, "gpus", None):
        return "rig"
    name = rig.gpus[0].name
    return f"{rig.gpu_count}x {name}" if rig.gpu_count > 1 else name


# ── VRAM projection ──────────────────────────────────────────────────────────


def _project_vram(preset_id: str, rig) -> Any | None:
    """Project the preset's per-card VRAM against the rig (reuse the byte-level
    KV projector). Returns a ``Projection`` or None when the model declares no
    byte-level shape (the gate then simply skips)."""
    from sndr.cli.commands.kv_calc import _precise_vram_gib
    from sndr.model_configs import kv_projector as kp
    from sndr.model_configs.registry_v2 import load_alias, load_model, load_preset_def

    try:
        cfg = load_alias(preset_id)
        preset_def = load_preset_def(preset_id)
        model_def = load_model(preset_def.model)
    except Exception:  # noqa: BLE001 — an unresolvable preset skips the gate
        return None

    shape = getattr(model_def.capabilities, "shape", None)
    if shape is None or getattr(shape, "num_attention_layers", None) is None:
        return None

    vram_gib = _precise_vram_gib(rig)
    if vram_gib is None:
        return None
    try:
        return kp.project(
            cfg,
            kp.ProjectorRig(vram_gib_per_card=vram_gib, gpu_count=1, name=rig.source),
            shape=shape,
            preset_id=preset_id,
        )
    except ValueError:
        return None


def _print_projection(em: Emitter, preset_id: str, rig, p) -> None:
    budget = getattr(p, "budget_gib", 0.0) or 0.0
    total = getattr(p, "total_gib", 0.0) or 0.0
    pct = (100.0 * total / budget) if budget else 0.0
    em.line(f"  VRAM projection — {preset_id} on {_rig_label(rig)} (per card):")
    em.line(f"    weights (÷TP)   {getattr(p, 'weights_gib', 0.0):.2f} GiB")
    em.line(f"    KV pool         {getattr(p, 'kv_pool_actual_gib', 0.0):.2f} GiB")
    em.line(f"    peak total      {total:.2f} / {budget:.2f} GiB budget "
            f"({pct:.0f}%)  → {getattr(p, 'verdict', '?')}")


# ── interactive helpers ──────────────────────────────────────────────────────


def _is_tty() -> bool:
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except Exception:  # noqa: BLE001 — a detached stream is simply not a TTY
        return False


def _prompt(em: Emitter, question: str, *, default: bool, tty_required: bool = True) -> bool:
    """A minimal yes/no prompt that returns ``default`` on EOF / non-TTY instead
    of hanging (PICKER-2 graceful EOF). ``default`` is the value chosen when the
    operator just hits Enter (or when non-interactive)."""
    if tty_required and not _is_tty():
        return default
    try:
        answer = input(f"  {question} ").strip().lower()
    except EOFError:
        em.line("    (no interactive input — using the default; "
                "pass --no-input to silence)")
        return default
    if not answer:
        return default
    return answer in ("y", "yes")


def _maybe_offer_set_default(preset_id: str, *, no_input: bool = False) -> None:
    """After a green boot, offer to pin ``preset_id`` as the default (DEFAULT-1,
    opt-IN, N-default). No-op when non-interactive, ``--no-input``, or already
    pinned to this preset."""
    if no_input or not _is_tty():
        return
    if user_prefs.get_default_preset() == preset_id:
        return
    em = Emitter()
    if _prompt(em, f"Make {preset_id} your default? [y/N]", default=False):
        try:
            user_prefs.set_default_preset(preset_id)
            em.ok(f"default set — future `sndr quickstart` will boot {preset_id}")
        except ValueError:
            pass


# ── rig detection + boot seams (mocked in tests) ─────────────────────────────


def _detect_rig(args: argparse.Namespace):
    """Detect the rig: ``--fake-gpus`` > ``--rig`` > live ``nvidia-smi`` probe."""
    from sndr.model_configs.preflight_fit import (
        RigProbe,
        rig_from_fake_spec,
        rig_from_hardware_def,
    )

    fake = getattr(args, "fake_gpus", None)
    rig_id = getattr(args, "rig", None)
    if fake is not None:
        return rig_from_fake_spec(fake)
    if rig_id is not None:
        from sndr.model_configs.registry_v2 import load_hardware

        return rig_from_hardware_def(load_hardware(rig_id), source=f"rig:{rig_id}")
    return RigProbe().detect()


def _remote_env_url() -> str | None:
    import os

    url = os.environ.get(_REMOTE_ENV, "").strip()
    return url or None


def _up_namespace(*, preset: str | None, gui_port: int, no_engine: bool) -> argparse.Namespace:
    """Build the ``sndr up`` argument namespace. ``no_input=True`` so ``up`` never
    prompts (the wizard owns all prompting)."""
    return argparse.Namespace(
        preset=preset,
        port=None,
        gui_port=gui_port,
        no_engine=no_engine,
        dry_run=False,
        no_input=True,
        timeout=300,
        rig=None,
        fake_gpus=None,
        output="text",
    )


def _boot(ns: argparse.Namespace) -> int:
    """Delegate the actual bring-up to the EXISTING ``sndr up`` flow."""
    from sndr.cli.commands.up import UpCommand

    return UpCommand().execute(ns)


__all__ = ["QuickstartCommand"]
