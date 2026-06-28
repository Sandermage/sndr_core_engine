# SPDX-License-Identifier: Apache-2.0
"""Minimal interactive chat REPL over a running engine.

This is the thin terminal front-end shared by ``sndr chat`` and the tail of
``sndr run``. It owns ONLY the loop: read a line, append it to the running
message history, call the injected chat function, print the reply. The actual
HTTP work is the product-API engine client's chat proxy
(:func:`sndr.product_api.legacy.engine_client.engine_chat`) — the REPL never
talks to a socket itself, so it stays a front-end onto the same path the GUI
chat uses, not a parallel chat engine.

The chat call and the input source are injected (``chat_fn`` / ``input_fn``) so
the loop is unit-testable without a socket or a TTY. The default wiring in
:func:`chat_loop` binds them to the real engine client and ``builtins.input``.

Design notes:
  * history accumulates in OpenAI ``messages`` shape so multi-turn context is
    preserved across turns (the engine is stateless per request);
  * ``/exit`` / ``/quit`` and EOF / Ctrl-C end the loop cleanly (rc 0);
  * an engine error is surfaced as one friendly line on stderr and the loop
    CONTINUES — a single bad turn must not drop the whole session.
"""
from __future__ import annotations

import sys
from typing import Any, Callable, Optional

# Lines that end the session instead of being sent to the model.
_EXIT_WORDS = frozenset({"/exit", "/quit", "/q", "/bye"})


def run_repl(
    *,
    chat_fn: Callable[[list[dict[str, Any]]], dict[str, Any]],
    input_fn: Callable[[str], str],
    model_label: str,
    system_prompt: Optional[str] = None,
) -> int:
    """Run the read-eval-print loop. Returns an exit code (always 0 on a clean
    exit; the loop never propagates a per-turn engine error as a non-zero rc).

    ``chat_fn(messages) -> {"reply": str, "usage": dict, ...}`` is the engine
    call. ``input_fn(prompt) -> str`` reads one user line (``builtins.input``
    in production). ``model_label`` is shown in the prompt banner.
    """
    messages: list[dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    print(f"  chatting with {model_label} — type your message, "
          "/exit to quit.", file=sys.stderr)
    print(file=sys.stderr)

    while True:
        try:
            raw = input_fn("you> ")
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr)
            return 0

        line = raw.strip()
        if not line:
            continue
        if line.lower() in _EXIT_WORDS:
            return 0

        messages.append({"role": "user", "content": line})
        try:
            result = chat_fn(messages)
        except KeyboardInterrupt:
            # Interrupt mid-generation: drop the unanswered user turn so the
            # history stays consistent, then keep the session alive.
            messages.pop()
            print("\n  (interrupted — type /exit to quit)", file=sys.stderr)
            continue
        except Exception as exc:  # noqa: BLE001 — surface, do not crash the REPL
            messages.pop()
            print(f"  ! engine error: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            print("  (the engine may still be warming up — try again, or "
                  "/exit)", file=sys.stderr)
            continue

        reply = (result or {}).get("reply") or ""
        messages.append({"role": "assistant", "content": reply})
        print(reply)
        reasoning = (result or {}).get("reasoning")
        if reasoning:
            # Show the model's thinking dimmed-ish, after the answer, so the
            # answer reads first. Keep it plain (no ANSI) for pipe-safety.
            print(f"  [reasoning] {reasoning}", file=sys.stderr)


def chat_loop(
    host: str,
    port: int,
    *,
    preset_id: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> int:
    """Production wiring: bind :func:`run_repl` to the real engine client and
    ``builtins.input``. Returns the loop's exit code.

    The chat proxy is the same ``engine_chat`` the GUI uses; the model label
    prefers the engine's own served-model id (so the banner matches what the
    engine answers as), falling back to the preset id / a generic label.
    """
    from sndr.product_api.legacy import engine_client

    # Resolve the served-model label for the banner — best effort.
    label = model or preset_id or "engine"
    try:
        status = engine_client.engine_status(host, port=port, timeout=3.0)
        models = status.get("models") or []
        if models:
            label = models[0]
    except Exception:
        pass

    def _chat_fn(messages: list[dict[str, Any]]) -> dict[str, Any]:
        return engine_client.engine_chat(
            {
                "messages": messages,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            host=host,
            port=port,
        )

    import builtins

    return run_repl(chat_fn=_chat_fn, input_fn=builtins.input, model_label=label)


__all__ = ["run_repl", "chat_loop"]
