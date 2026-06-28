# SPDX-License-Identifier: Apache-2.0
"""sndr CLI dispatcher.

Examples (resource commands use dotted names — ``engines.list``, not
``engines list``)::

    sndr --version
    sndr engines.list
    sndr engines.info vllm
    sndr pins.list --engine vllm
    sndr health
    sndr preflight prod-qwen3.6-35b-balanced
    sndr preflight prod-gemma4-26b-default --rig single-3090-24gbvram

Promoted operator commands (v12 split-brain closure) — thin pass-throughs
to the legacy implementation, so the canonical and ``genesis`` entry points
cannot drift::

    sndr report bundle --preset a5000-2x-35b-prod
    sndr doctor --full
    sndr preset list
    sndr preset recommend --workload agentic-coding
    sndr bench --help
    sndr tune plan a5000-2x-35b-prod
    sndr config explain a5000-2x-35b-prod

The CLI exists for headless automation (CI scripts, cron jobs, scripts);
operators primarily use the GUI.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from sndr.cli.commands import COMMAND_REGISTRY, build_subparsers
from sndr.cli.commands.promoted import PROMOTED_COMMANDS
from sndr.version import __version__

# Env markers that signal a non-interactive / CI context. When any is set we
# never auto-launch the wizard on a bare ``sndr`` invocation — scripted callers
# (and dashboards that scrape the help text) must keep the old help behaviour
# even if they happen to run under a pseudo-TTY.
_CI_ENV_MARKERS = ("CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS", "SNDR_NO_WIZARD")


def _interactive_no_args() -> bool:
    """True when a bare ``sndr`` should drop into the interactive wizard.

    Gated on BOTH stdin and stdout being a real TTY (so piped / redirected
    callers keep the help output) AND the absence of any CI marker. This is the
    only thing that turns the Ollama-style "type one thing → chatting" first
    experience on; everything else keeps the legacy help wall.
    """
    if any(os.environ.get(name) for name in _CI_ENV_MARKERS):
        return False
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except Exception:
        return False


def _run_wizard_no_args(argv: list[str]) -> int:
    """Dispatch a bare ``sndr`` to the interactive launch wizard.

    A bare invocation maps to ``sndr launch`` with no preset — the existing
    rig→preset→fit wizard. Kept as a separate seam (overridable in tests) so
    the no-args dispatch can be exercised without spinning up the whole wizard.
    """
    from sndr.cli.commands.launch import LaunchCommand

    parser = build_parser()
    args = parser.parse_args(["launch", *argv])
    return LaunchCommand().execute(args)


# Promoted pass-through commands delegate their entire argv tail to the
# legacy implementation. They must bypass the top-level argparse so that a
# leading ``--help`` (and any delegate-specific flags) forward verbatim —
# ``argparse.REMAINDER`` does not capture a leading optional like ``--help``.
_PASSTHROUGH_COMMANDS: dict[str, object] = {
    cmd.name: cmd for cmd in PROMOTED_COMMANDS
}


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="sndr",
        description="sndr-platform — multi-engine inference patch orchestrator.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--output",
        choices=("json", "yaml", "text"),
        default="text",
        help="Output format (default: text)",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        title="commands",
        metavar="COMMAND",
    )
    build_subparsers(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code."""
    if argv is None:
        argv = sys.argv[1:]

    # Fast-path for promoted pass-through commands (report / doctor / preset
    # / bench / tune / config). Delegate the whole tail to the legacy impl
    # before argparse runs, so ``sndr <cmd> --help`` and every flag forward
    # verbatim. Mirrors the legacy ``cli_main`` bridge fast-path.
    if argv and argv[0] in _PASSTHROUGH_COMMANDS:
        cmd = _PASSTHROUGH_COMMANDS[argv[0]]
        ns = argparse.Namespace(_extra_argv=list(argv[1:]))
        try:
            return cmd.execute(ns)  # type: ignore[attr-defined]
        except KeyboardInterrupt:
            sys.stderr.write("\nInterrupted.\n")
            return 130

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        # Ollama-style first experience: a bare ``sndr`` on an interactive TTY
        # drops straight into the launch wizard. ``-h``/``--help`` never reaches
        # here (argparse exits first), so this only fires on a truly bare call.
        # Non-TTY / piped / CI keeps the legacy help output unchanged.
        if not argv and _interactive_no_args():
            sys.stderr.write(
                "Welcome to sndr — let's get a model running. "
                "(Ctrl-C to exit, `sndr --help` for all commands)\n"
            )
            try:
                return _run_wizard_no_args([])
            except KeyboardInterrupt:
                sys.stderr.write("\nInterrupted.\n")
                return 130
        parser.print_help()
        return 0

    command = COMMAND_REGISTRY.get(args.command)
    if command is None:
        parser.error(f"Unknown command: {args.command}")

    try:
        return command.execute(args)
    except KeyboardInterrupt:
        sys.stderr.write("\nInterrupted.\n")
        return 130


if __name__ == "__main__":
    sys.exit(main())
