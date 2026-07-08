# SPDX-License-Identifier: Apache-2.0
"""CLI command: ``sndr switch`` — change which model is running, in one step.

The rig runs one heavy model at a time (both GPUs are occupied at TP=2). Moving
from one preset to another is a stop-then-start dance; ``sndr switch`` makes it
a single stateless verb, the way club-3090's ``switch.sh <variant>`` does:

    sndr switch                     # list the presets you can switch to
    sndr switch prod-gemma4-31b-tq-default   # stop current, boot this one
    sndr switch prod-... --set-default        # ...and remember it as the default

It is a thin composition over the existing ``sndr down`` and ``sndr up`` — no
new orchestration logic, so it inherits their weight checks, readiness wait, and
GUI-daemon handling. The target preset is validated BEFORE anything is stopped,
so a typo can never leave the rig with nothing running.
"""
from __future__ import annotations

import argparse  # noqa: TC003 — runtime Namespace typing on the public execute() seam
import sys

_DEFAULT_GUI_PORT = 8765


def _known_presets() -> set[str]:
    """The set of switchable preset slugs (V2 registry). Empty on failure so
    the caller degrades to a plain 'unknown preset' message."""
    try:
        from sndr.model_configs.registry_v2 import list_presets

        return set(list_presets())
    except Exception:  # pragma: no cover - defensive
        return set()


def _current_default() -> str | None:
    try:
        from sndr.cli import user_prefs

        return user_prefs.get_default_preset()
    except Exception:  # pragma: no cover - defensive
        return None


def _set_default(preset: str) -> None:
    from sndr.cli import user_prefs

    user_prefs.set_default_preset(preset)


def _down(preset: str | None, *, gui_port: int, dry_run: bool) -> int:
    """Stop the current stack via the canonical DownCommand."""
    from sndr.cli.commands.up import DownCommand

    ns = argparse.Namespace(preset=preset, gui_port=gui_port, dry_run=dry_run)
    return DownCommand().execute(ns)


def _up(
    preset: str,
    *,
    gui_port: int,
    dry_run: bool,
    no_input: bool,
    timeout: int,
) -> int:
    """Boot ``preset`` via the canonical UpCommand."""
    from sndr.cli.commands.up import UpCommand

    ns = argparse.Namespace(
        preset=preset,
        port=None,
        gui_port=gui_port,
        no_engine=False,
        dry_run=dry_run,
        no_input=no_input,
        timeout=timeout,
        rig=None,
        fake_gpus=None,
    )
    return UpCommand().execute(ns)


def render_list(presets, current: str | None) -> str:
    lines = ["Switchable presets (* = current default):", ""]
    for p in sorted(presets):
        mark = " *" if p == current else "  "
        lines.append(f"{mark} {p}")
    lines.append("")
    lines.append("Switch with:  sndr switch <preset>   (add --set-default to pin it)")
    lines.append("Full cards:   sndr preset list")
    return "\n".join(lines)


class SwitchCommand:
    name = "switch"
    help = (
        "Switch the running model in one step: stop the current stack and boot "
        "another preset (bare `switch` lists them)."
    )

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "preset",
            nargs="?",
            default=None,
            help="Preset to switch to. Omit (or `--list`) to list switchable presets.",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            help="List the presets you can switch to and exit.",
        )
        parser.add_argument(
            "--set-default",
            action="store_true",
            help="Also pin this preset as the default (so `sndr up` boots it).",
        )
        parser.add_argument(
            "--gui-port",
            type=int,
            default=_DEFAULT_GUI_PORT,
            metavar="PORT",
            help=f"Product-API + GUI daemon port (default: {_DEFAULT_GUI_PORT}).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report the down/up plan without stopping or starting anything.",
        )
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Headless: never prompt on stdin.",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=300,
            metavar="SECONDS",
            help="Seconds to wait for the new engine to become ready.",
        )

    def execute(self, args: argparse.Namespace) -> int:
        preset = getattr(args, "preset", None)

        # Bare `switch` or `--list`: show the menu, change nothing.
        if getattr(args, "list", False) or preset is None:
            print(render_list(_known_presets(), _current_default()))
            return 0

        # Validate the target BEFORE stopping anything — a typo must never
        # leave the rig with nothing running.
        known = _known_presets()
        if known and preset not in known:
            from difflib import get_close_matches

            near = get_close_matches(preset, sorted(known), n=1)
            hint = f" Did you mean `{near[0]}`?" if near else ""
            sys.stderr.write(
                f"switch: unknown preset `{preset}`.{hint} "
                "Run `sndr switch --list` to see the options.\n"
            )
            return 2

        gui_port = int(getattr(args, "gui_port", _DEFAULT_GUI_PORT))
        dry_run = bool(getattr(args, "dry_run", False))
        no_input = bool(getattr(args, "no_input", False))
        timeout = int(getattr(args, "timeout", 300))

        # Pin BEFORE switching so a later bare `sndr up` boots the same preset.
        if getattr(args, "set_default", False):
            try:
                _set_default(preset)
            except Exception as exc:  # noqa: BLE001 — surface, don't crash
                sys.stderr.write(f"switch: could not pin default: {exc}\n")
                return 2

        down_rc = _down(preset, gui_port=gui_port, dry_run=dry_run)
        if down_rc != 0:
            sys.stderr.write(
                "switch: could not stop the current stack; not starting the new "
                "preset. Resolve the issue and retry.\n"
            )
            return down_rc
        return _up(
            preset,
            gui_port=gui_port,
            dry_run=dry_run,
            no_input=no_input,
            timeout=timeout,
        )
