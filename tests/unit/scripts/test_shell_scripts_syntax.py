# SPDX-License-Identifier: Apache-2.0
"""Minimal test coverage for shell scripts — TOOLING-HARDENING.2 L.7
(2026-05-26).

Scope (per master plan §10.3 #12 + L.7 GO):

  * ``bash -n`` syntax check for every active ``.sh`` script under
    ``scripts/`` and ``tools/`` (parametrized).
  * Shebang sanity check — every script declares a bash interpreter
    (``#!/usr/bin/env bash`` or ``#!/bin/bash``).
  * Targeted usage-message smoke ONLY for scripts where calling with
    no/bad args is verified safe (no docker, no ssh, no rig touch).
    Currently: ``tools/audit_yaml_vs_runtime.sh`` (validated argc
    check at top of file, exits 2 with usage on bad argc).

Scripts requiring docker / SSH / live container / nvidia-smi are
**not** smoke-tested here. Their syntax + shebang are still checked.
Operator-driven scripts stay operator-driven; this layer only catches
the kind of regression where a script no longer parses at all.

Excluded by design:
  * Files under ``scripts/_retired/`` or ``tools/_retired/``
  * Files under ``scripts/launch/_archive/`` (historical launchers)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]


def _discover_shell_scripts() -> list[Path]:
    """Return active .sh scripts under scripts/ + tools/, sorted.

    Excludes ``_retired/`` and ``_archive/`` subtrees so we don't gate
    on historical artifacts whose linter status is irrelevant.
    """
    roots = [REPO_ROOT / "scripts", REPO_ROOT / "tools"]
    out: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.rglob("*.sh"):
            parts = set(p.relative_to(REPO_ROOT).parts)
            if "_retired" in parts or "_archive" in parts:
                continue
            out.append(p)
    return sorted(out)


SHELL_SCRIPTS = _discover_shell_scripts()


def _rel(p: Path) -> str:
    return str(p.relative_to(REPO_ROOT))


# Parametrize IDs so pytest output names the script being checked.
_SCRIPT_IDS = [_rel(p) for p in SHELL_SCRIPTS]


def test_inventory_non_empty():
    """Guard rail — if the discovery rule changes, fail loudly rather
    than silently passing zero parametrized tests."""
    assert len(SHELL_SCRIPTS) >= 10, (
        f"expected ≥10 shell scripts, found {len(SHELL_SCRIPTS)}: "
        f"{[_rel(p) for p in SHELL_SCRIPTS]}"
    )


@pytest.mark.parametrize("script", SHELL_SCRIPTS, ids=_SCRIPT_IDS)
def test_bash_syntax_clean(script: Path):
    """Every active shell script must parse cleanly under ``bash -n``.

    Catches:
      * unbalanced quotes / parens / heredocs
      * missing ``fi`` / ``done`` / ``esac``
      * stray operators in conditionals

    Does NOT execute the script — no side effects.
    """
    result = subprocess.run(
        ["bash", "-n", str(script)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, (
        f"{_rel(script)} failed bash -n:\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )


@pytest.mark.parametrize("script", SHELL_SCRIPTS, ids=_SCRIPT_IDS)
def test_has_bash_shebang(script: Path):
    """Every active shell script must declare a bash interpreter.

    Accepts ``#!/usr/bin/env bash`` (portable) or ``#!/bin/bash``
    (linux-only); rejects ``#!/bin/sh`` (different semantics) or
    missing shebang (relies on interpreter inference).
    """
    first_line = script.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("#!"), (
        f"{_rel(script)} lacks a shebang (first line: {first_line!r})"
    )
    assert "bash" in first_line, (
        f"{_rel(script)} shebang does not invoke bash: {first_line!r}"
    )


class TestAuditYamlVsRuntimeNoArgsSmoke:
    """``tools/audit_yaml_vs_runtime.sh`` is the one shell script where
    no-args invocation is verified safe — it argc-checks at line 35-38
    and exits 2 with a usage message before any docker / ssh / file IO.

    This smoke ensures the entry-point guard never regresses (e.g.
    accidental removal of the argc check would let downstream docker
    invocations run with empty args).
    """

    script = REPO_ROOT / "tools" / "audit_yaml_vs_runtime.sh"

    def test_no_args_exits_two(self):
        result = subprocess.run(
            ["bash", str(self.script)],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 2, (
            f"no-args invocation should exit 2 (usage error), got "
            f"rc={result.returncode}\nstdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    def test_no_args_prints_usage_to_stderr(self):
        result = subprocess.run(
            ["bash", str(self.script)],
            capture_output=True, text=True, check=False,
        )
        # Shell prints `Usage: <script> ...` to stderr on argc failure.
        assert "Usage:" in result.stderr, (
            f"expected 'Usage:' in stderr, got: {result.stderr!r}"
        )
        assert "yaml_path" in result.stderr
        assert "container_name" in result.stderr

    def test_missing_yaml_exits_two(self, tmp_path):
        """With 2 args but a non-existent YAML path, the early file
        existence check (line 44-47) exits 2 before any docker call."""
        result = subprocess.run(
            ["bash", str(self.script),
             str(tmp_path / "missing.yaml"), "fake-container"],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 2
        assert "not found" in result.stderr.lower()
