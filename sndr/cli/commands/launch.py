# SPDX-License-Identifier: Apache-2.0
"""CLI command: ``sndr launch`` — flag-based launch **and** interactive wizard.

Two surfaces over one execution path:

  - ``sndr launch <preset> [--port N] [--dry-run]`` — the scriptable flag path.
    Resolves the preset and hands straight to the existing launcher
    (``sndr.cli.legacy.launch.run_launch``) — the same renderer + patcher + exec
    used today via the ``genesis`` entry point. The modern ``sndr`` entry point
    had **no** ``launch`` command before this; this closes that gap so the
    canonical CLI can launch without falling back to ``genesis``.

  - ``sndr launch`` (no preset, TTY) — an **interactive wizard**. This is the
    real gap versus club-3090's ``c3/launch.sh``: their bash menu lists compose
    files and lets you pick a number; ours detects/chooses the rig, lists only
    the presets that *fit* it (with the preset card's Status + measured TPS +
    the ``sndr preflight`` fit verdict inline, plus a "show all" toggle), runs
    the preflight fit-check on the choice, and — when a multi-GPU preset can't
    run on a single card — offers the card's ``fallback_preset`` escape hatch
    and routes to ``docs/SINGLE_CARD.md`` instead of dead-ending. The chosen
    preset resolves to a plain ``sndr launch <preset>`` call, so the wizard is a
    front-end onto the very same flag path, never a parallel launcher.

The wizard's decision logic is the I/O-free core in
:mod:`sndr.cli.wizard.launch_wizard` (unit-tested without a TTY). This module is
the terminal orchestration: numbered menus, prompts, rig selection, hand-off.

Scriptability: ``--dry-run`` makes the wizard non-interactive — it prints the
resolved ``sndr launch <preset>`` command to stdout (and the fit report to
stderr) instead of running it, so CI / external orchestrators can drive the
wizard. ``--no-input`` auto-picks the top-ranked fitting preset (the wizard's
"recommended" default) without prompting.

Examples::

    sndr launch                              # interactive wizard (TTY)
    sndr launch --dry-run                     # wizard, print resolved command
    sndr launch --no-input --dry-run          # auto-pick top fit, print command
    sndr launch --rig single-3090-24gbvram --dry-run --no-input
    sndr launch --fake-gpus "RTX 3090:24576:8.6" --dry-run --no-input
    sndr launch prod-qwen3.6-35b-balanced     # flag path → real launch
    sndr launch prod-qwen3.6-35b-balanced --dry-run   # flag path → render script
"""
from __future__ import annotations

import argparse
import sys

# ── glyphs for the per-row verdict (match sndr/cli/commands/preflight.py) ────
_GLYPH = {"pass": "✓", "fail": "✗", "warn": "!", "skip": "·", "fit": "✓", "nofit": "✗"}


class LaunchCommand:
    name = "launch"
    help = "Launch a preset — interactive rig→preset→fit wizard, or by name."

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "preset",
            nargs="?",
            default=None,
            help="Preset alias to launch (e.g. prod-qwen3.6-35b-balanced). "
                 "Omit on a TTY to open the interactive wizard.",
        )
        parser.add_argument(
            "--port", type=int, default=None,
            help="Override the preset's port.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Do not launch. Flag path: render the launch script. Wizard: "
                 "print the resolved `sndr launch <preset>` command (stdout).",
        )
        parser.add_argument(
            "--no-input", action="store_true",
            help="Wizard without prompts: auto-pick the top-ranked fitting "
                 "preset for the rig. Implies the wizard path when no preset is "
                 "given. Useful for CI / non-TTY drivers.",
        )
        parser.add_argument(
            "--all", action="store_true", dest="show_all",
            help="Wizard: list non-fitting presets too (default: fitting only).",
        )
        parser.add_argument(
            "--rig", default=None, metavar="HARDWARE_ID",
            help="Wizard: project against a builtin hardware definition "
                 "instead of the live rig (offline, no nvidia-smi).",
        )
        parser.add_argument(
            "--fake-gpus", default=None, metavar="SPEC",
            help="Wizard: project against a synthetic rig. Spec "
                 "'name:vram_mib:cc;...' e.g. 'RTX 3090:24576:8.6'. Offline.",
        )

    # ── dispatch ─────────────────────────────────────────────────────────────

    def execute(self, args: argparse.Namespace) -> int:
        # Explicit preset → flag path (delegate to the existing launcher).
        if args.preset is not None:
            return self._run_flag_path(args)

        # No preset: the wizard. Non-interactive (no TTY, no --no-input, no
        # --dry-run) is an error — there's nothing to pick against silently.
        interactive_ok = sys.stdin.isatty()
        if not (interactive_ok or args.no_input or args.dry_run):
            sys.stderr.write(
                "sndr launch: no preset given and stdin is not a TTY.\n"
                "  Pass a preset (`sndr launch <preset>`), or run the wizard "
                "with --no-input / --dry-run for headless use.\n"
            )
            return 2
        return self._run_wizard(args)

    # ── flag path: hand to the existing launcher ─────────────────────────────

    def _run_flag_path(self, args: argparse.Namespace) -> int:
        from sndr.cli.legacy.launch import run_launch

        opts = argparse.Namespace(
            config_key=args.preset,
            port=args.port,
            dry_run=args.dry_run,
            non_interactive=True,
            skip_apply=False,
            strict_image="auto",
            preflight_only=False,
            skip_autodetect=False,
            pull=False,
            check_deps=False,
            policy=None,
            extra_env=None,
        )
        return run_launch(opts)

    # ── the wizard ───────────────────────────────────────────────────────────

    def _run_wizard(self, args: argparse.Namespace) -> int:
        from sndr.cli.wizard.launch_wizard import (
            build_catalog,
            emit_launch_command,
            escape_hatch_for,
        )
        from sndr.model_configs.preflight_fit import (
            RigProbe,
            rig_from_fake_spec,
            rig_from_hardware_def,
        )
        from sndr.model_configs.registry_v2 import (
            list_presets,
            load_alias,
            load_hardware,
            load_preset_def,
        )

        # Advisory output goes to stderr so a piped stdout stays clean for the
        # resolved command on the --dry-run path (`... --dry-run | sh`).
        def out(msg: str = "") -> None:
            print(msg, file=sys.stderr)

        # ── resolve the rig (fake > rig > live nvidia-smi, optionally chosen) ─
        if args.fake_gpus is not None:
            rig = rig_from_fake_spec(args.fake_gpus)
        elif args.rig is not None:
            try:
                rig = rig_from_hardware_def(load_hardware(args.rig), source=f"rig:{args.rig}")
            except Exception as exc:
                out(f"sndr launch: could not load --rig {args.rig!r}: {exc}")
                return 2
        else:
            rig = RigProbe().detect()
            if rig.gpu_count == 0 and not (args.no_input or args.dry_run):
                rig = self._choose_rig_interactively(out, load_hardware) or rig

        out("")
        out("  sndr launch — interactive wizard")
        out(f"  rig: {rig.source} ({rig.gpu_count} GPU(s)"
            + (f", {rig.min_vram_gb} GB/GPU" if rig.min_vram_gb else "")
            + (f", sm_{rig.min_compute_cap[0]}.{rig.min_compute_cap[1]}"
               if rig.min_compute_cap else "")
            + ")")

        # ── evaluate the corpus against the rig ──────────────────────────────
        catalog = build_catalog(
            rig,
            preset_ids=list_presets(),
            card_loader=load_preset_def,
            cfg_loader=load_alias,
        )
        show_all = bool(args.show_all)
        rows = catalog.menu(show_all=show_all)
        if not rows and not show_all:
            # Nothing fits — auto-fall back to the full list so the operator
            # can still see (and escape-hatch out of) the non-fitting presets.
            out("  no preset fits this rig — showing all presets "
                "(single-card users: docs/SINGLE_CARD.md)")
            show_all = True
            rows = catalog.menu(show_all=True)
        if not rows:
            out("  no presets available.")
            return 2

        # ── render the menu ──────────────────────────────────────────────────
        self._render_menu(out, rows, show_all=show_all)

        # ── pick a preset ────────────────────────────────────────────────────
        # --no-input is the only auto-pick trigger. Under --dry-run alone we
        # still prompt (reading stdin — TTY or pipe), so scripts/tests can drive
        # the choice; an empty/closed stdin falls back to the top-ranked row.
        if args.no_input:
            chosen = rows[0]  # top-ranked (fitting + production + best metric)
            out(f"  auto-picked: {chosen.preset_id} (top-ranked fit)")
        else:
            chosen = self._prompt_choice(out, rows)
            if chosen is None:
                out("  aborted.")
                return 130

        # ── run the fit-check on the choice; offer escape hatch on fail ──────
        self._print_fit(out, chosen)
        hatch = escape_hatch_for(chosen, rig)
        if hatch.triggered:
            rc, chosen = self._handle_escape_hatch(out, hatch, chosen, catalog, args)
            if rc is not None:
                return rc

        # ── confirm + emit / run ─────────────────────────────────────────────
        argv = emit_launch_command(chosen.preset_id, port=args.port)
        command = " ".join(argv)

        if args.dry_run:
            # Scriptable: the resolved command is the ONLY thing on stdout.
            print(command)
            out(f"  (dry-run) resolved command: {command}")
            return 0

        if sys.stdin.isatty() and not args.no_input:
            if not self._confirm(out, f"Launch `{command}`?"):
                out("  aborted — not launched.")
                out(f"  to launch later: {command}")
                return 0

        out(f"  launching: {command}")
        delegate = argparse.Namespace(
            preset=chosen.preset_id, port=args.port, dry_run=False,
        )
        return self._run_flag_path(delegate)

    # ── menu rendering ───────────────────────────────────────────────────────

    def _render_menu(self, out, rows, *, show_all: bool) -> None:
        out("")
        scope = "all presets" if show_all else "presets that fit this rig"
        out(f"  {scope} ({len(rows)}):")
        out("  " + "─" * 66)
        for i, c in enumerate(rows, 1):
            glyph = _GLYPH["fit"] if c.can_run else _GLYPH["nofit"]
            metric = f"  {c.metric_label}" if c.metric_label else ""
            out(f"  [{i:>2}] {glyph} {c.preset_id}")
            out(f"        {c.status:<22}{metric}")
            out(f"        {c.title}")
            out(f"        fit: {c.verdict}")
        out("  " + "─" * 66)
        if not show_all:
            out("  (only fitting presets shown — re-run with --all to see every preset)")

    def _print_fit(self, out, candidate) -> None:
        out("")
        out(f"  preflight: {candidate.preset_id}")
        for c in candidate.report.checks:
            g = _GLYPH.get(c.status, "?")
            out(f"    {g} {c.dimension:<16} {c.status.upper():<5} "
                f"need {c.required} · have {c.detected}")
        out(f"  VERDICT: {candidate.verdict}")

    # ── escape hatch ─────────────────────────────────────────────────────────

    def _handle_escape_hatch(self, out, hatch, chosen, catalog, args):
        """Return (rc, chosen). rc is None to continue with (possibly new) chosen."""
        out("")
        out("  ✗ this preset cannot run on the current rig:")
        out(f"      {hatch.reason}")
        out(f"      single-card guide: {hatch.doc}")
        if hatch.fallback_preset is None:
            out("      no single-card fallback declared for this preset.")
            out("      pick a different preset (re-run `sndr launch`) or add a GPU.")
            return 2, chosen

        out(f"      single-card fallback available: {hatch.fallback_preset}")
        # In headless mode (--no-input), take the fallback automatically — the
        # escape hatch routes a single-card operator to a runnable preset
        # instead of dead-ending on the OOM-bound choice.
        if args.no_input:
            out(f"      routing to fallback: {hatch.fallback_preset}")
            return None, self._candidate_by_id(catalog, hatch.fallback_preset, chosen)

        if self._confirm(out, f"Use the single-card fallback `{hatch.fallback_preset}`?"):
            return None, self._candidate_by_id(catalog, hatch.fallback_preset, chosen)
        out("      keeping original choice (will likely OOM — see the guide).")
        return None, chosen

    def _candidate_by_id(self, catalog, preset_id, default):
        for c in catalog.candidates:
            if c.preset_id == preset_id:
                return c
        return default

    # ── interactive helpers ──────────────────────────────────────────────────

    @staticmethod
    def _ask(prompt: str) -> str:
        """Prompt on stderr, read from stdin.

        Routing the prompt to stderr keeps stdout clean for the resolved
        ``sndr launch <preset>`` command on the --dry-run path, so
        ``sndr launch --dry-run | sh`` stays runnable even when the wizard
        prompts interactively (the prompt and menu never land on stdout).
        """
        sys.stderr.write(prompt)
        sys.stderr.flush()
        return input().strip()

    def _prompt_choice(self, out, rows):
        for _ in range(3):
            try:
                raw = self._ask("  Choose a preset [number, default 1]: ")
            except KeyboardInterrupt:
                print(file=sys.stderr)
                return None
            except EOFError:
                # No interactive input available (closed/empty stdin) — accept
                # the top-ranked default rather than abort, so headless
                # --dry-run drivers resolve a command deterministically.
                print(file=sys.stderr)
                return rows[0]
            if not raw:
                return rows[0]
            try:
                idx = int(raw) - 1
                if 0 <= idx < len(rows):
                    return rows[idx]
            except ValueError:
                # Allow a literal preset id too.
                match = next((c for c in rows if c.preset_id == raw), None)
                if match is not None:
                    return match
            out(f"    invalid — pick 1-{len(rows)} or a preset id")
        return None

    def _confirm(self, out, msg: str) -> bool:
        try:
            raw = self._ask(f"  ? {msg} [Y/n]: ").lower()
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr)
            return False
        return raw in ("", "y", "yes")

    def _choose_rig_interactively(self, out, load_hardware):
        """No GPUs detected on a TTY — let the operator pick a builtin rig."""
        from sndr.model_configs.preflight_fit import rig_from_hardware_def
        from sndr.model_configs.registry_v2 import list_hardware

        ids = list_hardware()
        if not ids:
            return None
        out("")
        out("  no GPU detected — pick the rig to plan against:")
        for i, hid in enumerate(ids, 1):
            out(f"    [{i}] {hid}")
        try:
            raw = self._ask("  Choose a rig [number, default 1]: ")
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr)
            return None
        try:
            hid = ids[int(raw) - 1] if raw else ids[0]
        except (ValueError, IndexError):
            hid = raw if raw in ids else ids[0]
        try:
            return rig_from_hardware_def(load_hardware(hid), source=f"rig:{hid}")
        except Exception as exc:
            out(f"  could not load rig {hid!r}: {exc}")
            return None


__all__ = ["LaunchCommand"]
