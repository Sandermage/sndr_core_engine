# SPDX-License-Identifier: Apache-2.0
"""CLI command: ``sndr update`` — the one-command "keep me current + healthy".

The simple front door for updates. Under the hood the project has a lot of
machinery (pin bumps, patch re-anchoring, drift audits); this command exposes
the part a normal user cares about — *is my install current, and is it
healthy?* — behind one verb.

**Two things it deliberately does NOT do**, so it is safe to run any time:

  * It never pulls a new **engine image**. The vLLM pin is content-addressed and
    changing it is an operator decision (bench + patch re-validation); see
    ``docs/PIN_BUMP_PLAYBOOK.md``. ``sndr update`` only moves the *product*
    (CLI + GUI + configs) forward.
  * Default (no ``--apply``) is **read-only**: it reports version, pin, and how
    far the local repo is behind upstream, then tells you the one command to
    apply it. Nothing is mutated until you pass ``--apply``.

Design: the logic (home resolution, behind-count parsing, status rendering,
apply sequence) is split into small pure/injectable helpers so it is testable
offline without a network, a git checkout, or a real reinstall.
"""
from __future__ import annotations

import argparse  # noqa: TC003 — runtime Namespace typing on the public execute() seam
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

# A runner has the subprocess.run signature; injected in tests.
Runner = Callable[..., "subprocess.CompletedProcess[str]"]

DEFAULT_HOME = "~/.sndr"


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Default command runner — real subprocess. Tests inject a fake."""
    return subprocess.run(  # noqa: S603 — fixed argv lists, no shell
        cmd, capture_output=True, text=True, check=False, **kwargs
    )


def _home_dir() -> Path:
    """Resolve the sndr install directory — ``$SNDR_HOME`` or the ``~/.sndr``
    default the installer uses."""
    return Path(os.environ.get("SNDR_HOME", DEFAULT_HOME)).expanduser()


def _behind_count(home: str | Path, *, runner: Runner = _run) -> int | None:
    """How many commits the local checkout is behind its upstream branch.

    Returns 0 when current, a positive int when behind, or ``None`` when it
    can't be determined (no upstream, not a git repo, offline). Read-only:
    it fetches and counts but never merges/pulls.
    """
    home = str(home)
    # Refresh remote refs (best effort — offline just leaves the count stale).
    runner(["git", "-C", home, "fetch", "--quiet"])
    r = runner(["git", "-C", home, "rev-list", "--count", "HEAD..@{u}"])
    if r.returncode != 0:
        return None
    out = (r.stdout or "").strip()
    return int(out) if out.isdigit() else None


def _installed_version() -> str:
    try:
        from sndr.version import __version__

        return __version__
    except Exception:  # pragma: no cover - defensive
        return "unknown"


def _engine_pin() -> str:
    try:
        from sndr import pins

        return pins.current()
    except Exception:  # pragma: no cover - defensive
        return "unknown"


def render_status(
    *, version: str, pin: str, behind: int | None, home: str, applied: bool
) -> str:
    lines: list[str] = []
    lines.append(f"sndr {version}   (install: {home})")
    lines.append(f"engine pin: {pin}")
    lines.append("")

    if applied:
        lines.append("✓ Updated to the latest product code and reinstalled.")
    elif behind is None:
        lines.append(
            "Could not check for product updates (no upstream / offline). "
            "Your install still works; run `sndr update --apply` when online."
        )
    elif behind == 0:
        lines.append("✓ Product is up to date.")
    else:
        lines.append(
            f"↑ {behind} commit(s) behind upstream. Apply the update with:"
        )
        lines.append("      sndr update --apply")

    lines.append("")
    lines.append(
        "Note: the engine pin is NOT auto-upgraded — that is an operator "
        "decision (bench + patch re-validation). See docs/PIN_BUMP_PLAYBOOK.md."
    )
    lines.append("Check health any time with:  sndr doctor")
    return "\n".join(lines)


def _apply_update(home: str | Path, *, runner: Runner = _run) -> int:
    """Fast-forward the product repo and reinstall the package. Never touches
    the engine image (pin policy)."""
    home = str(home)
    pull = runner(["git", "-C", home, "pull", "--ff-only", "--quiet"])
    if pull.returncode != 0:
        sys.stderr.write(
            "update: `git pull --ff-only` failed — resolve local changes and "
            f"retry.\n{(pull.stderr or '').strip()}\n"
        )
        return 1
    reinstall = runner(
        [sys.executable, "-m", "pip", "install", "--quiet", "--no-deps", "-e", home]
    )
    if reinstall.returncode != 0:
        sys.stderr.write(
            "update: editable reinstall failed.\n"
            f"{(reinstall.stderr or '').strip()}\n"
        )
        return 1
    return 0


class UpdateCommand:
    name = "update"
    help = (
        "Update the sndr install (CLI + GUI + configs) and re-check health. "
        "Engine-pin upgrades stay operator-gated."
    )

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually pull the update + reinstall (default: just report).",
        )
        parser.add_argument(
            "-y",
            "--yes",
            action="store_true",
            help="Non-interactive: assume yes to prompts.",
        )
        parser.add_argument(
            "--no-fetch",
            action="store_true",
            help="Skip the network fetch; report from local refs only.",
        )
        parser.add_argument(
            "--json", action="store_true", help="Machine-readable status."
        )

    def execute(self, args: argparse.Namespace) -> int:
        home = _home_dir()
        version = _installed_version()
        pin = _engine_pin()

        if getattr(args, "apply", False):
            rc = _apply_update(home)
            if rc != 0:
                return rc
            behind = 0
            applied = True
        else:
            applied = False
            behind = None if getattr(args, "no_fetch", False) else _behind_count(home)

        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "version": version,
                        "engine_pin": pin,
                        "home": str(home),
                        "behind": behind,
                        "applied": applied,
                    }
                )
            )
            return 0

        print(
            render_status(
                version=version,
                pin=pin,
                behind=behind,
                home=str(home),
                applied=applied,
            )
        )
        return 0
