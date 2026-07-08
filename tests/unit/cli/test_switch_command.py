# SPDX-License-Identifier: Apache-2.0
"""`sndr switch` — one stateless step to change which model is running.

Matches club-3090's `switch.sh <variant>` ergonomics: stop the current stack,
boot another preset, optionally pin it as the default. Contract:

  * Registered on the curated dispatcher as `switch`.
  * `sndr switch` (bare) and `sndr switch --list` show the switchable presets,
    marking the current default.
  * `sndr switch <preset>` validates the target FIRST (unknown → error, nothing
    touched), then brings the stack DOWN and back UP on the new preset — in that
    order.
  * `--set-default` pins the target via user_prefs before switching (and a typo
    target is never pinned).
  * `--dry-run` forwards to down/up without doing real work.
"""
from __future__ import annotations

import argparse

import pytest

pytest.importorskip("pydantic")

from sndr.cli.commands import COMMAND_REGISTRY  # noqa: E402
from sndr.cli.commands import switch as switch_mod  # noqa: E402


@pytest.fixture(autouse=True)
def _populate_registry():
    from sndr.cli.main import build_parser

    build_parser()


def _a(**kw) -> argparse.Namespace:
    base = {
        "preset": None, "list": False, "set_default": False,
        "gui_port": 8765, "dry_run": False, "no_input": True, "timeout": 300,
    }
    base.update(kw)
    return argparse.Namespace(**base)


def test_switch_registered():
    assert "switch" in COMMAND_REGISTRY
    assert COMMAND_REGISTRY["switch"].name == "switch"
    assert COMMAND_REGISTRY["switch"].help


def test_known_presets_nonempty():
    ps = switch_mod._known_presets()
    assert isinstance(ps, set)
    assert len(ps) >= 1


def test_render_list_marks_current_default():
    out = switch_mod.render_list(
        ["prod-a", "prod-b"], current="prod-b"
    )
    assert "prod-a" in out
    assert "prod-b" in out
    # The current default is flagged somehow (a marker char near it).
    idx = out.index("prod-b")
    assert any(mark in out[max(0, idx - 6): idx + 8] for mark in ("*", "default", "◀", "current"))


def test_bare_switch_lists(monkeypatch, capsys):
    monkeypatch.setattr(switch_mod, "_known_presets", lambda: {"prod-a", "prod-b"})
    monkeypatch.setattr(switch_mod, "_down", lambda *a, **k: pytest.fail("must not switch"))
    rc = COMMAND_REGISTRY["switch"].execute(_a(preset=None))
    assert rc == 0
    assert "prod-a" in capsys.readouterr().out


def test_explicit_list_flag(monkeypatch, capsys):
    monkeypatch.setattr(switch_mod, "_known_presets", lambda: {"prod-a"})
    rc = COMMAND_REGISTRY["switch"].execute(_a(list=True))
    assert rc == 0
    assert "prod-a" in capsys.readouterr().out


def test_unknown_preset_errors_and_touches_nothing(monkeypatch):
    monkeypatch.setattr(switch_mod, "_known_presets", lambda: {"prod-a"})
    touched = []
    monkeypatch.setattr(switch_mod, "_down", lambda *a, **k: touched.append("down"))
    monkeypatch.setattr(switch_mod, "_up", lambda *a, **k: touched.append("up"))
    rc = COMMAND_REGISTRY["switch"].execute(_a(preset="nope"))
    assert rc != 0
    assert touched == [], "an unknown preset must not stop or start anything"


def test_switch_downs_then_ups_in_order(monkeypatch):
    monkeypatch.setattr(switch_mod, "_known_presets", lambda: {"prod-b"})
    order = []
    monkeypatch.setattr(switch_mod, "_down", lambda *a, **k: order.append("down") or 0)
    monkeypatch.setattr(switch_mod, "_up", lambda *a, **k: order.append("up") or 0)
    rc = COMMAND_REGISTRY["switch"].execute(_a(preset="prod-b"))
    assert rc == 0
    assert order == ["down", "up"]


def test_switch_propagates_up_rc(monkeypatch):
    monkeypatch.setattr(switch_mod, "_known_presets", lambda: {"prod-b"})
    monkeypatch.setattr(switch_mod, "_down", lambda *a, **k: 0)
    monkeypatch.setattr(switch_mod, "_up", lambda *a, **k: 7)
    rc = COMMAND_REGISTRY["switch"].execute(_a(preset="prod-b"))
    assert rc == 7


def test_up_receives_target_preset(monkeypatch):
    monkeypatch.setattr(switch_mod, "_known_presets", lambda: {"prod-b"})
    seen = {}
    monkeypatch.setattr(switch_mod, "_down", lambda *a, **k: 0)

    def fake_up(preset, **k):
        seen["preset"] = preset
        return 0

    monkeypatch.setattr(switch_mod, "_up", fake_up)
    COMMAND_REGISTRY["switch"].execute(_a(preset="prod-b"))
    assert seen["preset"] == "prod-b"


def test_set_default_pins_target(monkeypatch):
    monkeypatch.setattr(switch_mod, "_known_presets", lambda: {"prod-b"})
    monkeypatch.setattr(switch_mod, "_down", lambda *a, **k: 0)
    monkeypatch.setattr(switch_mod, "_up", lambda *a, **k: 0)
    pinned = []
    monkeypatch.setattr(switch_mod, "_set_default", pinned.append)
    COMMAND_REGISTRY["switch"].execute(_a(preset="prod-b", set_default=True))
    assert pinned == ["prod-b"]


def test_no_set_default_does_not_pin(monkeypatch):
    monkeypatch.setattr(switch_mod, "_known_presets", lambda: {"prod-b"})
    monkeypatch.setattr(switch_mod, "_down", lambda *a, **k: 0)
    monkeypatch.setattr(switch_mod, "_up", lambda *a, **k: 0)
    pinned = []
    monkeypatch.setattr(switch_mod, "_set_default", pinned.append)
    COMMAND_REGISTRY["switch"].execute(_a(preset="prod-b", set_default=False))
    assert pinned == []


def test_dry_run_forwarded(monkeypatch):
    monkeypatch.setattr(switch_mod, "_known_presets", lambda: {"prod-b"})
    seen = {}

    def fake_down(*a, **k):
        seen["down_dry"] = k.get("dry_run")
        return 0

    def fake_up(*a, **k):
        seen["up_dry"] = k.get("dry_run")
        return 0

    monkeypatch.setattr(switch_mod, "_down", fake_down)
    monkeypatch.setattr(switch_mod, "_up", fake_up)
    COMMAND_REGISTRY["switch"].execute(_a(preset="prod-b", dry_run=True))
    assert seen["down_dry"] is True
    assert seen["up_dry"] is True


# ── Namespace contract: switch must satisfy the REAL up/down execute() ─────────
# (the unit tests above mock _down/_up, so they cannot catch a missing arg that
# only the real DownCommand/UpCommand.execute reads — that surfaced as a silent
# "engine not stopped" half-switch when _down omitted rig/fake_gpus).


def _attrs_read_by(class_name: str) -> set[str]:
    import ast
    import pathlib
    import re

    src = pathlib.Path(
        pathlib.Path(switch_mod.__file__).parent / "up.py"
    ).read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for fn in node.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == "execute":
                    seg = ast.get_source_segment(src, fn)
                    attrs = set(re.findall(r"args\.([a-z_]+)", seg))
                    attrs |= set(re.findall(r'getattr\(args,\s*["\']([a-z_]+)', seg))
                    return attrs
    return set()


def _capture_namespace(monkeypatch, seam_command: str) -> argparse.Namespace:
    """Run switch._down/_up but intercept the Namespace handed to the real
    command, so we can compare its attrs to what execute() reads."""
    captured = {}

    class _Spy:
        def execute(self, ns):
            captured["ns"] = ns
            return 0

    import sndr.cli.commands.up as up_mod

    monkeypatch.setattr(up_mod, seam_command, _Spy)
    return captured


def test_down_namespace_satisfies_downcommand(monkeypatch):
    cap = _capture_namespace(monkeypatch, "DownCommand")
    switch_mod._down("prod-x", gui_port=8765, dry_run=True)
    provided = set(vars(cap["ns"]))
    required = _attrs_read_by("DownCommand")
    missing = required - provided
    assert not missing, f"_down Namespace missing {missing} that DownCommand.execute reads"


def test_up_namespace_satisfies_upcommand(monkeypatch):
    cap = _capture_namespace(monkeypatch, "UpCommand")
    switch_mod._up("prod-x", gui_port=8765, dry_run=True, no_input=True, timeout=300)
    provided = set(vars(cap["ns"]))
    required = _attrs_read_by("UpCommand")
    missing = required - provided
    assert not missing, f"_up Namespace missing {missing} that UpCommand.execute reads"
