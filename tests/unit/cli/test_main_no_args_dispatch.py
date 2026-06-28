# SPDX-License-Identifier: Apache-2.0
"""``sndr`` with no args — TTY-gated dispatch to the interactive wizard.

The Ollama-style first experience: typing bare ``sndr`` on an interactive
terminal drops the operator straight into the launch wizard, instead of
printing the argparse help wall. This MUST be TTY-gated so scripted /
piped / CI callers keep the old help behaviour (parsers and dashboards
that run ``sndr`` with no args and scrape the help text must not break).

Contract under test:
  * interactive TTY (stdin+stdout isatty) + no args  -> dispatch to the wizard;
  * non-TTY (piped / CI) + no args                   -> print help (unchanged);
  * ``-h`` / ``--help`` always prints help, even on a TTY;
  * an explicit subcommand is never intercepted.
"""
from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout

import pytest

pytest.importorskip("pydantic")

import sndr.cli.main as cli_main  # noqa: E402
from sndr.cli.main import main  # noqa: E402


def _force_interactive(monkeypatch, *, interactive: bool) -> None:
    """Override the TTY/CI gate directly.

    ``redirect_stdout``/``redirect_stderr`` swap ``sys.stdout``/``sys.stderr``
    for StringIO buffers (whose ``isatty()`` is False), so monkeypatching
    ``isatty`` on the real streams would be masked inside the redirect context.
    Patching the gate seam is the deterministic way to exercise both branches.
    """
    monkeypatch.setattr(cli_main, "_interactive_no_args", lambda: interactive)
    # Clear any ambient CI marker so the gate seam is the only signal.
    for name in ("CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS"):
        monkeypatch.delenv(name, raising=False)


def _force_tty(monkeypatch, *, stdin: bool, stdout: bool) -> None:
    # Back-compat shim for the env-marker test, which exercises the real gate.
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: stdin, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: stdout, raising=False)
    monkeypatch.delenv("CI", raising=False)


class TestNoArgsTtyDispatch:
    def test_tty_no_args_dispatches_to_wizard(self, monkeypatch):
        _force_interactive(monkeypatch, interactive=True)
        calls: dict[str, object] = {}

        def fake_wizard(argv):
            calls["argv"] = list(argv)
            return 0

        # The dispatcher routes the empty argv through the wizard launcher.
        monkeypatch.setattr(cli_main, "_run_wizard_no_args", fake_wizard)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = main([])
        assert rc == 0
        assert "argv" in calls, "no-args on a TTY must dispatch to the wizard"

    def test_tty_no_args_emits_welcome_banner(self, monkeypatch):
        _force_interactive(monkeypatch, interactive=True)
        monkeypatch.setattr(cli_main, "_run_wizard_no_args", lambda argv: 0)
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            rc = main([])
        assert rc == 0
        assert "Welcome to sndr" in err.getvalue()
        assert "sndr --help" in err.getvalue()


class TestNoArgsNonTtyHelp:
    def test_non_tty_no_args_prints_help(self, monkeypatch):
        _force_interactive(monkeypatch, interactive=False)
        # Wizard must NOT be reached in a non-TTY context.
        monkeypatch.setattr(
            cli_main, "_run_wizard_no_args",
            lambda argv: pytest.fail("wizard must not run in a non-TTY context"),
        )
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            rc = main([])
        assert rc == 0
        text = out.getvalue()
        assert "usage:" in text.lower()
        assert "COMMAND" in text

    def test_ci_env_no_args_prints_help_even_on_tty(self, monkeypatch):
        # Exercise the REAL gate: isatty true on both streams, but a CI marker
        # must keep the scripted help path. (No redirect of stdout here, so the
        # monkeypatched real-stream isatty is the live signal the gate reads.)
        import sys

        monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
        monkeypatch.setenv("CI", "true")
        assert cli_main._interactive_no_args() is False

    def test_real_gate_true_when_tty_and_no_ci(self, monkeypatch):
        import sys

        monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
        for name in ("CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS", "SNDR_NO_WIZARD"):
            monkeypatch.delenv(name, raising=False)
        assert cli_main._interactive_no_args() is True

    def test_real_gate_false_when_stdout_not_tty(self, monkeypatch):
        import sys

        monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: False, raising=False)
        for name in ("CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS", "SNDR_NO_WIZARD"):
            monkeypatch.delenv(name, raising=False)
        assert cli_main._interactive_no_args() is False


class TestHelpFlagAlwaysPrintsHelp:
    def test_help_flag_on_tty_prints_help_not_wizard(self, monkeypatch):
        _force_interactive(monkeypatch, interactive=True)
        monkeypatch.setattr(
            cli_main, "_run_wizard_no_args",
            lambda argv: pytest.fail("`-h` must print help, not run the wizard"),
        )
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            with pytest.raises(SystemExit) as exc:
                main(["-h"])
        assert exc.value.code == 0
        assert "usage:" in out.getvalue().lower()


class TestExplicitCommandNotIntercepted:
    def test_health_subcommand_runs_normally_on_tty(self, monkeypatch):
        _force_interactive(monkeypatch, interactive=True)
        monkeypatch.setattr(
            cli_main, "_run_wizard_no_args",
            lambda argv: pytest.fail("explicit command must not hit the wizard"),
        )
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            rc = main(["health"])
        assert rc == 0
        assert "sndr-platform" in out.getvalue()


class TestCtrlCExitsCleanly:
    """A Ctrl-C anywhere in dispatch must end with the same clean line + the
    conventional 130 exit code (128 + SIGINT), never a raw KeyboardInterrupt
    traceback that leaks the call stack to the operator."""

    def test_ctrl_c_in_command_returns_130_no_traceback(self, monkeypatch):
        from sndr.cli.commands import COMMAND_REGISTRY
        from sndr.cli.main import build_parser

        build_parser()

        def boom(self, args):  # noqa: ANN001 — raise as if the user hit Ctrl-C
            raise KeyboardInterrupt

        monkeypatch.setattr(type(COMMAND_REGISTRY["health"]), "execute", boom)
        err = io.StringIO()
        # No pytest.raises: a leaked KeyboardInterrupt would propagate here and
        # fail the test, which is exactly the regression this guards.
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            rc = main(["health"])
        assert rc == 130, "Ctrl-C must exit 130 (128 + SIGINT)"
        assert "Interrupted." in err.getvalue()
        assert "Traceback" not in err.getvalue()

    def test_ctrl_c_in_no_args_wizard_returns_130(self, monkeypatch):
        _force_interactive(monkeypatch, interactive=True)

        def boom(argv):
            raise KeyboardInterrupt

        monkeypatch.setattr(cli_main, "_run_wizard_no_args", boom)
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            rc = main([])
        assert rc == 130
        assert "Interrupted." in err.getvalue()

    def test_ctrl_c_in_passthrough_returns_130(self, monkeypatch):
        # A promoted pass-through (doctor) that the user Ctrl-Cs mid-run.
        import sndr.compat.cli as compat_cli

        def boom(argv):
            raise KeyboardInterrupt

        monkeypatch.setattr(compat_cli, "main", boom)
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            rc = main(["doctor", "--full"])
        assert rc == 130
        assert "Interrupted." in err.getvalue()
