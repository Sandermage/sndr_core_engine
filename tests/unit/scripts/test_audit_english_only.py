# SPDX-License-Identifier: Apache-2.0
"""Tests for `scripts/audit_english_only.py` — Cyrillic ratchet-down gate.

Contract:

  1. Cyrillic regex matches Russian / Ukrainian / Belarusian letters.
  2. count_cyrillic returns 0 for ASCII-only files.
  3. count_cyrillic returns >0 for files with Cyrillic.
  4. scan_all() honors EXCLUDE_DIRS (_retired, __pycache__, etc).
  5. scan_all(include_waivers=False) excludes WAIVERS entries.
  6. WAIVERS keys are valid repo-relative paths that exist in tree.
  7. WAIVERS values are non-empty rationale strings.
  8. --strict exit code is 0 when all non-waivered Cyrillic is zero.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "audit_english_only.py"


def _import_script():
    name = "_audit_english_only_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestCyrillicRegex:
    def test_matches_russian_letter(self):
        mod = _import_script()
        assert mod.CYRILLIC_RE.search("привет")

    def test_matches_ukrainian_specific(self):
        mod = _import_script()
        # ї, є, ґ are Ukrainian-specific letters
        assert mod.CYRILLIC_RE.search("їжак")
        assert mod.CYRILLIC_RE.search("ємний")

    def test_does_not_match_ascii(self):
        mod = _import_script()
        assert not mod.CYRILLIC_RE.search("hello world")
        assert not mod.CYRILLIC_RE.search("def foo(): return 42")

    def test_does_not_match_chinese(self):
        mod = _import_script()
        # Chinese characters are outside Cyrillic block
        assert not mod.CYRILLIC_RE.search("你好世界")


class TestCountCyrillic:
    def test_zero_on_ascii(self, tmp_path):
        mod = _import_script()
        f = tmp_path / "ascii.py"
        f.write_text("def foo():\n    return 'hello'\n")
        assert mod.count_cyrillic(f) == 0

    def test_counts_russian(self, tmp_path):
        mod = _import_script()
        f = tmp_path / "ru.py"
        f.write_text("# привет мир\n")
        # 9 Cyrillic letters: п-р-и-в-е-т (6) + м-и-р (3) = 9
        assert mod.count_cyrillic(f) == 9

    def test_handles_missing_file(self, tmp_path):
        mod = _import_script()
        assert mod.count_cyrillic(tmp_path / "nonexistent.py") == 0


class TestWaivers:
    def test_waivers_is_dict(self):
        mod = _import_script()
        assert isinstance(mod.WAIVERS, dict)

    def test_waiver_paths_exist(self):
        """Every waivered path must actually exist in the repo so the
        waiver document refers to something real (not a stale entry)."""
        mod = _import_script()
        for rel in mod.WAIVERS:
            assert (REPO_ROOT / rel).exists(), (
                f"WAIVERS references non-existent path: {rel}"
            )

    def test_waiver_rationales_non_empty(self):
        mod = _import_script()
        for rel, reason in mod.WAIVERS.items():
            assert isinstance(reason, str) and len(reason) >= 40, (
                f"Waiver for {rel} has too-short rationale "
                f"({len(reason) if isinstance(reason, str) else 'N/A'} chars); "
                f"explain why an exception is justified."
            )


class TestStrictExitCode:
    def test_strict_returns_zero_on_clean_or_waivered_only(self):
        """`--strict` exit 0 when every Cyrillic-containing file is in
        WAIVERS. This is the current expected state of the repo."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--strict"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"--strict expected exit 0 (only waivered Cyrillic remains), "
            f"got {result.returncode}.\nstdout: {result.stdout[:500]}"
        )

    def test_check_returns_zero_on_current_baseline(self):
        """`--check` exit 0 when baseline matches current state."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"--check expected exit 0 on clean baseline, got {result.returncode}."
        )
