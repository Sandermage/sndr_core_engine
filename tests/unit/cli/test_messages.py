# SPDX-License-Identifier: Apache-2.0
"""Shared CLI message voice (``sndr.cli._messages``).

R2 polish: the no-args wizard, ``run``, ``up``, ``chat`` and the friendly-error
interceptor all printed advisory lines in slightly different shapes. This module
gives them ONE rustup/uv-style voice (matching ``install.sh``'s
``info``/``ok``/``warn``/``hint``) so the whole CLI reads as one product.

The voice contract these tests pin:
  * every advisory line goes to the bound stream (stderr by default) so a piped
    stdout stays clean for the scriptable resolved-command / plan output;
  * ``ok`` / ``err`` carry the same ✓ / ✗ glyphs the commands already used (so
    the existing substring assertions hold);
  * ``hint`` is indented continuation text under the preceding line;
  * ``heartbeat`` is a throttled "still warming up" factory shared by ``run`` and
    ``up`` (one line every N ticks), replacing the two copy-pasted ``_progress``
    closures.
"""
from __future__ import annotations

import io

from sndr.cli._messages import Emitter, heartbeat


class TestEmitterStream:
    def test_writes_to_bound_stream(self):
        buf = io.StringIO()
        em = Emitter(stream=buf)
        em.line("plain")
        assert buf.getvalue() == "plain\n"

    def test_ok_carries_check_glyph(self):
        buf = io.StringIO()
        Emitter(stream=buf).ok("Ready — chat at http://x")
        assert "✓" in buf.getvalue()
        assert "Ready — chat at http://x" in buf.getvalue()

    def test_err_carries_cross_glyph(self):
        buf = io.StringIO()
        Emitter(stream=buf).err("engine did not become ready")
        assert "✗" in buf.getvalue()
        assert "engine did not become ready" in buf.getvalue()

    def test_hint_is_indented_continuation(self):
        buf = io.StringIO()
        Emitter(stream=buf).hint("sndr chat my-preset")
        out = buf.getvalue()
        assert "sndr chat my-preset" in out
        assert out.startswith(" "), "hint must be indented continuation text"

    def test_blank_line(self):
        buf = io.StringIO()
        Emitter(stream=buf).blank()
        assert buf.getvalue() == "\n"


class TestHeartbeat:
    def test_emits_one_line_every_interval(self):
        lines: list[str] = []
        tick = heartbeat(lines.append, every=3, label=None)
        for _ in range(9):
            tick(0.0)
        # 9 ticks at every=3 -> exactly 3 heartbeat lines (3rd, 6th, 9th).
        assert len(lines) == 3
        assert all("warming up" in s for s in lines)

    def test_label_is_namespaced(self):
        lines: list[str] = []
        tick = heartbeat(lines.append, every=1, label="engine")
        tick(0.0)
        assert "[engine]" in lines[0]

    def test_no_label_has_no_brackets(self):
        lines: list[str] = []
        tick = heartbeat(lines.append, every=1, label=None)
        tick(0.0)
        assert "[" not in lines[0]

    def test_elapsed_seconds_grow(self):
        lines: list[str] = []
        tick = heartbeat(lines.append, every=1, label=None, step_seconds=2)
        tick(0.0)
        tick(0.0)
        # first line ~2s, second ~4s
        assert "2s" in lines[0]
        assert "4s" in lines[1]
