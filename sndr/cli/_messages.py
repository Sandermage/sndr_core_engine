# SPDX-License-Identifier: Apache-2.0
"""One CLI voice for the operator-facing commands (rustup/uv style).

The no-args wizard, ``sndr run`` / ``sndr up`` / ``sndr chat`` and the
friendly-error interceptor all emit short advisory lines. Before this module
each grew its own ad-hoc ``out()`` closure and its own ``✓`` / ``✗`` / "still
warming up" wording, so the surface read as several tools. :class:`Emitter`
gives them ONE voice — the same ``info`` / ``ok`` / ``warn`` / ``hint`` shape as
``install.sh`` — and :func:`heartbeat` replaces the two copy-pasted readiness
"still warming up" closures that lived in ``run`` and ``up``.

Two invariants this module preserves:

  * **stderr by default.** Advisory output goes to ``sys.stderr`` so a piped
    stdout stays clean for the scriptable payload (the resolved ``sndr launch``
    command, the ``--dry-run`` plan, an ``sndr open`` URL). Callers that need a
    different stream pass it in.
  * **plain text, pipe-safe.** No ANSI; the glyphs (``✓`` / ``✗`` / ``»``) are
    the same ones the commands and ``sndr/cli/commands/launch.py`` already
    print, so existing output and its test assertions are unchanged.
"""
from __future__ import annotations

import sys
from typing import Callable, Optional, TextIO

# Glyphs — identical to sndr/cli/commands/launch.py / preflight.py so the whole
# CLI renders one symbol set.
GLYPH_OK = "✓"
GLYPH_ERR = "✗"

# Indent for the body of a multi-line message (the rustup ``hint`` gutter). Four
# leading spaces line a hint up under the ``✓``/``✗`` it explains.
_BODY_INDENT = "    "


class Emitter:
    """A thin advisory-line writer bound to one stream (stderr by default).

    Methods map to the install.sh voice — :meth:`ok` / :meth:`err` carry a
    leading glyph; :meth:`hint` is indented continuation text under the line it
    explains; :meth:`line` / :meth:`blank` are the raw escape hatches for
    headers, menus and plan rows. Every method writes to the bound stream so a
    command keeps stdout free for its scriptable payload.
    """

    __slots__ = ("_stream",)

    def __init__(self, stream: Optional[TextIO] = None) -> None:
        self._stream = stream if stream is not None else sys.stderr

    # ── raw ──────────────────────────────────────────────────────────────────

    def line(self, msg: str = "") -> None:
        """Write one verbatim line (kept for headers / menus / plan rows)."""
        print(msg, file=self._stream)

    def blank(self) -> None:
        """A single blank separator line."""
        print(file=self._stream)

    # ── voiced lines ─────────────────────────────────────────────────────────

    def ok(self, msg: str) -> None:
        """A success line: ``  ✓ <msg>``."""
        print(f"  {GLYPH_OK} {msg}", file=self._stream)

    def err(self, msg: str) -> None:
        """A failure line: ``  ✗ <msg>``."""
        print(f"  {GLYPH_ERR} {msg}", file=self._stream)

    def hint(self, msg: str) -> None:
        """Indented continuation text under the preceding line."""
        print(f"{_BODY_INDENT}{msg}", file=self._stream)


def heartbeat(
    emit: Callable[[str], None],
    *,
    every: int = 5,
    label: Optional[str] = None,
    step_seconds: int = 2,
) -> Callable[[float], None]:
    """Build a throttled readiness heartbeat for a ``wait_ready`` poll loop.

    Returns a ``tick(_now)`` callback (the ``on_progress`` shape the lifecycle
    probes accept). It counts ticks and, every ``every`` ticks, calls ``emit``
    with one "still warming up (<elapsed>s)" line — so the operator sees the
    wait is alive without a per-poll spam. ``label`` namespaces the line
    (``[engine] …``) when a command waits on more than one thing; ``step_seconds``
    is the poll cadence used to render an approximate elapsed time.

    Replaces the two near-identical ``_progress`` closures that ``run`` and ``up``
    each carried (the only difference between them was the optional label).
    """
    state = {"ticks": 0}

    def _tick(_now: float) -> None:
        state["ticks"] += 1
        if state["ticks"] % max(1, every) == 0:
            elapsed = state["ticks"] * step_seconds
            prefix = f"[{label}] " if label else ""
            emit(f"{_BODY_INDENT}{prefix}… still warming up ({elapsed}s)")

    return _tick


__all__ = ["Emitter", "heartbeat", "GLYPH_OK", "GLYPH_ERR"]
