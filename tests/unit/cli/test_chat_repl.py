# SPDX-License-Identifier: Apache-2.0
"""Thin interactive chat REPL over a running engine (``sndr chat`` / the tail
of ``sndr run``).

The REPL reuses the product-API engine client's non-streaming chat proxy
(``engine_chat``) so it is a thin front-end, never a parallel chat engine.
These tests drive the loop with an injected chat callable + a scripted input
iterator (no socket, no TTY), asserting:

  * a user turn is sent and the assistant reply is printed;
  * multi-turn history accumulates (the second request carries the first
    exchange);
  * ``/exit`` (and EOF) end the loop cleanly with rc 0;
  * an engine error is surfaced as a friendly line, not a traceback, and the
    loop continues.
"""
from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout

import pytest

from sndr.cli.chat_repl import run_repl  # noqa: E402


def _scripted_inputs(lines):
    it = iter(lines)

    def _input(_prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    return _input


class TestReplBasics:
    def test_single_turn_prints_reply(self):
        seen = []

        def fake_chat(messages):
            seen.append(list(messages))
            return {"reply": "hello back", "usage": {}}

        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            rc = run_repl(
                chat_fn=fake_chat,
                input_fn=_scripted_inputs(["hi there", "/exit"]),
                model_label="served-model",
            )
        assert rc == 0
        assert "hello back" in out.getvalue()
        # The user message reached the chat function.
        assert seen[0][-1]["role"] == "user"
        assert seen[0][-1]["content"] == "hi there"

    def test_multi_turn_accumulates_history(self):
        seen = []

        def fake_chat(messages):
            seen.append(list(messages))
            return {"reply": f"reply-{len(seen)}", "usage": {}}

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = run_repl(
                chat_fn=fake_chat,
                input_fn=_scripted_inputs(["first", "second", "/exit"]),
                model_label="m",
            )
        assert rc == 0
        # Second request includes the first user msg + the first assistant reply.
        second = seen[1]
        roles = [m["role"] for m in second]
        assert roles == ["user", "assistant", "user"]
        assert second[1]["content"] == "reply-1"
        assert second[2]["content"] == "second"


class TestReplExit:
    def test_eof_exits_cleanly(self):
        def fake_chat(messages):
            return {"reply": "x", "usage": {}}

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = run_repl(
                chat_fn=fake_chat,
                input_fn=_scripted_inputs([]),  # immediate EOF
                model_label="m",
            )
        assert rc == 0

    def test_slash_exit_does_not_call_chat(self):
        called = {"n": 0}

        def fake_chat(messages):
            called["n"] += 1
            return {"reply": "x", "usage": {}}

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = run_repl(
                chat_fn=fake_chat,
                input_fn=_scripted_inputs(["/exit"]),
                model_label="m",
            )
        assert rc == 0
        assert called["n"] == 0

    def test_blank_lines_are_skipped(self):
        called = {"n": 0}

        def fake_chat(messages):
            called["n"] += 1
            return {"reply": "ok", "usage": {}}

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = run_repl(
                chat_fn=fake_chat,
                input_fn=_scripted_inputs(["", "   ", "real", "/exit"]),
                model_label="m",
            )
        assert rc == 0
        assert called["n"] == 1  # only the non-blank "real" line was sent


class TestReplCtrlC:
    def test_ctrl_c_at_prompt_exits_cleanly(self):
        # Ctrl-C while waiting for the next line ends the session with rc 0 —
        # no traceback, like Ctrl-C out of a normal shell REPL.
        def at_prompt_interrupt(_prompt=""):
            raise KeyboardInterrupt

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = run_repl(
                chat_fn=lambda m: {"reply": "x"},
                input_fn=at_prompt_interrupt,
                model_label="m",
            )
        assert rc == 0

    def test_ctrl_c_mid_generation_keeps_session_alive(self):
        # Ctrl-C DURING a model turn drops just that unanswered turn and keeps
        # the loop alive (the next line still works) — a single interrupted
        # generation must not end the whole chat.
        calls = {"n": 0}

        def flaky_chat(messages):
            calls["n"] += 1
            if calls["n"] == 1:
                raise KeyboardInterrupt  # interrupt the first generation
            return {"reply": "second-ok"}

        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            rc = run_repl(
                chat_fn=flaky_chat,
                input_fn=_scripted_inputs(["interrupt me", "now answer", "/exit"]),
                model_label="m",
            )
        assert rc == 0
        assert "second-ok" in out.getvalue()
        assert calls["n"] == 2  # both turns were attempted; loop survived


class TestReplErrorHandling:
    def test_engine_error_is_friendly_and_loop_continues(self):
        calls = {"n": 0}

        def flaky_chat(messages):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("engine exploded")
            return {"reply": "recovered", "usage": {}}

        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = run_repl(
                chat_fn=flaky_chat,
                input_fn=_scripted_inputs(["boom", "again", "/exit"]),
                model_label="m",
            )
        assert rc == 0
        # The first turn errored but did NOT crash the REPL; second turn worked.
        combined = out.getvalue() + err.getvalue()
        assert "engine exploded" in combined
        assert "recovered" in out.getvalue()
