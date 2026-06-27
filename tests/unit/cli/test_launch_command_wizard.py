# SPDX-License-Identifier: Apache-2.0
"""Integration tests for ``sndr launch`` (v12 CLI command) — the wizard surface.

Drives the real command end-to-end against the live preset corpus using offline
rig sources (--fake-gpus) and the scriptable ``--dry-run`` path, so there is no
nvidia-smi / TTY / real-launch dependency. Asserts the clean-stdout contract
(stdout carries ONLY the resolved ``sndr launch <preset>`` command) and the
wizard's behaviour: fit-filtering, the --all toggle, top-fit auto-pick, and the
single-card escape-hatch routing.
"""
from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout

import pytest

# The CLI entrypoint pulls in product-API schemas (pydantic) transitively; skip
# cleanly when pydantic is absent (mirrors test_preflight_command.py).
pytest.importorskip("pydantic")

from sndr.cli.main import main  # noqa: E402


def _run(argv, stdin_text: str = "") -> tuple[int, str, str]:
    """Run the CLI, returning (rc, stdout, stderr). Feeds stdin_text via a
    monkeypatched builtins.input so interactive prompts resolve deterministically."""
    import builtins

    lines = iter(stdin_text.splitlines())

    def fake_input(_prompt: str = "") -> str:
        try:
            return next(lines)
        except StopIteration:
            raise EOFError

    out, err = io.StringIO(), io.StringIO()
    orig = builtins.input
    builtins.input = fake_input
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(argv)
    finally:
        builtins.input = orig
    return rc, out.getvalue(), err.getvalue()


SINGLE_3090 = "RTX 3090:24576:8.6"
TWO_A5000 = "RTX A5000:24564:8.6;RTX A5000:24564:8.6"


class TestLaunchCommandRegistered:
    def test_launch_in_registry(self):
        from sndr.cli.commands import COMMAND_REGISTRY
        from sndr.cli.main import build_parser
        build_parser()
        assert "launch" in COMMAND_REGISTRY


class TestWizardDryRunCleanStdout:
    def test_single_card_autopick_emits_clean_command(self):
        rc, out, err = _run(
            ["launch", "--fake-gpus", SINGLE_3090, "--dry-run", "--no-input"]
        )
        assert rc == 0
        # stdout is exactly the resolved command — nothing else.
        assert out.strip().startswith("sndr launch ")
        assert len(out.strip().splitlines()) == 1
        # the menu + advisory landed on stderr, not stdout.
        assert "interactive wizard" in err
        assert "interactive wizard" not in out

    def test_two_card_rig_autopicks_a_2gpu_preset(self):
        rc, out, err = _run(
            ["launch", "--fake-gpus", TWO_A5000, "--dry-run", "--no-input"]
        )
        assert rc == 0
        # On a 2× rig the top-ranked fit is a 2-GPU production preset.
        assert out.strip().startswith("sndr launch ")
        assert "VERDICT: CAN RUN" in err


class TestWizardFitFiltering:
    def test_default_menu_hides_nonfitting(self):
        rc, out, err = _run(
            ["launch", "--fake-gpus", SINGLE_3090, "--dry-run", "--no-input"]
        )
        # default (fitting-only) menu shows the ✓ rows, not the 2-GPU ✗ rows.
        assert "presets that fit this rig" in err
        assert "✗ prod-qwen3.6-35b-balanced" not in err

    def test_all_toggle_reveals_nonfitting(self):
        rc, out, err = _run(
            ["launch", "--fake-gpus", SINGLE_3090, "--all", "--dry-run", "--no-input"]
        )
        assert "all presets" in err
        assert "✗ " in err  # at least one non-fitting row is shown


class TestWizardInteractiveChoice:
    def test_piped_choice_overrides_autopick(self):
        # Pick row 2 explicitly (a fitting single-card example preset).
        rc, out, err = _run(
            ["launch", "--fake-gpus", SINGLE_3090, "--dry-run"],
            stdin_text="2\n",
        )
        assert rc == 0
        assert out.strip().startswith("sndr launch ")

    def test_empty_stdin_falls_back_to_top_fit(self):
        rc, out, err = _run(
            ["launch", "--fake-gpus", SINGLE_3090, "--dry-run"],
            stdin_text="",  # EOF immediately
        )
        assert rc == 0
        assert out.strip().startswith("sndr launch ")


class TestWizardEscapeHatch:
    def test_2gpu_preset_on_single_card_routes_to_fallback(self):
        # prod-gemma4-31b-kvauto-chat (2-GPU) declares fallback
        # prod-gemma4-31b-tq-default. Selecting it then accepting the fallback
        # must resolve the command to the fallback preset.
        rc, out, err = _run(
            ["launch", "--fake-gpus", SINGLE_3090, "--all", "--dry-run"],
            stdin_text="prod-gemma4-31b-kvauto-chat\ny\n",
        )
        assert rc == 0
        assert "cannot run on the current rig" in err
        assert "docs/SINGLE_CARD.md" in err
        assert out.strip() == "sndr launch prod-gemma4-31b-tq-default"

    def test_decline_fallback_keeps_original(self):
        rc, out, err = _run(
            ["launch", "--fake-gpus", SINGLE_3090, "--all", "--dry-run"],
            stdin_text="prod-gemma4-31b-kvauto-chat\nn\n",
        )
        assert rc == 0
        assert out.strip() == "sndr launch prod-gemma4-31b-kvauto-chat"

    def test_no_fallback_preset_returns_error_rc(self):
        # prod-gemma4-26b-default (2-GPU) declares NO fallback → escape hatch
        # surfaces the guide but cannot route; rc is non-zero.
        rc, out, err = _run(
            ["launch", "--fake-gpus", SINGLE_3090, "--all", "--dry-run"],
            stdin_text="prod-gemma4-26b-default\n",
        )
        assert rc == 2
        assert "no single-card fallback declared" in err


class TestNonTtyGuard:
    def test_no_preset_no_tty_no_flags_errors(self, monkeypatch):
        # Headless with neither a preset nor --dry-run/--no-input is a usage
        # error (nothing to pick against silently).
        import sys
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        rc, out, err = _run(["launch"])
        assert rc == 2
        assert "not a TTY" in err
