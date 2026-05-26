# SPDX-License-Identifier: Apache-2.0
"""Tests for ``scripts/audit_links.py`` — AUDIT-CLOSURE.1.A.3
(2026-05-26).

Coverage:

  * Inline + reference-style link extraction
  * Code-span stripping (inline backticks + fenced blocks) — prevents
    false positives on regex patterns / shell snippets shown in docs
  * Path verification + outside-repo skip
  * Inline allow marker waiver
  * GitHub-flavored slug correctness (double-hyphen from punctuation)
  * Opt-in anchor verification (``--anchors``)
  * Live tracked-tree default-mode (path-only) must stay clean
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "audit_links.py"


def _import_audit_module():
    spec = importlib.util.spec_from_file_location(
        "audit_links", SCRIPT_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["audit_links"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def audit_mod():
    return _import_audit_module()


class TestSlugify:
    """GitHub-flavored slug rules."""

    def test_basic_lowercase(self, audit_mod):
        assert audit_mod.slugify("Quickstart") == "quickstart"

    def test_space_to_hyphen(self, audit_mod):
        assert audit_mod.slugify("Quick Start Guide") == "quick-start-guide"

    def test_slash_produces_double_hyphen(self, audit_mod):
        """``A / B`` → ``a--b`` because slash strips and leaves two spaces."""
        assert audit_mod.slugify("Patch enable / disable flags") == \
            "patch-enable--disable-flags"

    def test_multiple_slashes(self, audit_mod):
        assert audit_mod.slugify(
            "PyTorch / CUDA / Triton standard env recommended values"
        ) == "pytorch--cuda--triton-standard-env-recommended-values"

    def test_backticks_stripped(self, audit_mod):
        assert audit_mod.slugify("Using `sndr launch` command") == \
            "using-sndr-launch-command"

    def test_punctuation_removed(self, audit_mod):
        assert audit_mod.slugify("Section: thinking-token-budget!") == \
            "section-thinking-token-budget"

    def test_underscore_preserved(self, audit_mod):
        """Underscores belong to ``\\w`` and stay in the slug."""
        assert audit_mod.slugify("test_function_name") == "test_function_name"


class TestStripCodeSpans:
    """Inline backticks + fenced code blocks must not leak link-like syntax."""

    def test_inline_backtick_stripped(self, audit_mod):
        text = "Regex: `^[a-z](?:[a-z0-9]*)[a-z]$`. Continue prose."
        stripped = audit_mod.strip_code_spans(text)
        assert "(?:" not in stripped, (
            f"inline code span should be removed, got: {stripped!r}"
        )

    def test_fenced_block_stripped(self, audit_mod):
        text = (
            "Before block.\n"
            "```\n"
            "[link in code](path/to/file.py)\n"
            "```\n"
            "After block.\n"
        )
        stripped = audit_mod.strip_code_spans(text)
        assert "[link in code]" not in stripped

    def test_line_numbers_preserved(self, audit_mod):
        """Stripping should keep line breaks so downstream line-number
        reporting remains accurate."""
        text = "L1\n`inline`\nL3\n"
        stripped = audit_mod.strip_code_spans(text)
        assert stripped.count("\n") == text.count("\n")


class TestLinkExtraction:
    """Inline link regex behavior."""

    def test_simple_inline_link(self, audit_mod):
        text = "Read [the docs](docs/README.md) for details.\n"
        stripped = audit_mod.strip_code_spans(text)
        links = audit_mod._find_inline_links(stripped)
        assert len(links) == 1
        _line, text_part, target = links[0]
        assert text_part == "the docs"
        assert target == "docs/README.md"

    def test_link_with_anchor(self, audit_mod):
        text = "[Section](docs/USAGE.md#quick-start)\n"
        links = audit_mod._find_inline_links(text)
        assert len(links) == 1
        assert links[0][2] == "docs/USAGE.md#quick-start"

    def test_external_link_extracted_but_skipped_later(self, audit_mod):
        """``_find_inline_links`` extracts all; external skip happens
        in ``_check_target``."""
        text = "[GitHub](https://github.com/example)\n"
        links = audit_mod._find_inline_links(text)
        assert len(links) == 1


class TestCheckTarget:
    """``_check_target`` logic — path/anchor verification."""

    def test_external_url_skipped(self, audit_mod, tmp_path):
        src = tmp_path / "test.md"
        src.write_text("placeholder", encoding="utf-8")
        kind, _ = audit_mod._check_target(
            "https://example.com/", src,
            repo_root=tmp_path,
            check_anchors=True, md_anchor_cache={},
        )
        assert kind is None

    def test_existing_path_passes(self, audit_mod, tmp_path):
        target_file = tmp_path / "TARGET.md"
        target_file.write_text("# Header\n", encoding="utf-8")
        src = tmp_path / "src.md"
        src.write_text("placeholder", encoding="utf-8")
        kind, _ = audit_mod._check_target(
            "TARGET.md", src,
            repo_root=tmp_path,
            check_anchors=True, md_anchor_cache={},
        )
        assert kind is None

    def test_missing_path_flagged(self, audit_mod, tmp_path):
        src = tmp_path / "src.md"
        src.write_text("placeholder", encoding="utf-8")
        kind, detail = audit_mod._check_target(
            "no-such-file.md", src,
            repo_root=tmp_path,
            check_anchors=True, md_anchor_cache={},
        )
        assert kind == "broken-path"
        assert "no-such-file.md" in detail

    def test_outside_repo_skipped(self, audit_mod, tmp_path):
        """Resolved path outside repo root is out-of-scope (operator's
        sibling private trees)."""
        src = tmp_path / "src.md"
        src.write_text("placeholder", encoding="utf-8")
        # ``../sibling`` resolves outside ``tmp_path``.
        kind, _ = audit_mod._check_target(
            "../sibling/anywhere.md", src,
            repo_root=tmp_path,
            check_anchors=True, md_anchor_cache={},
        )
        assert kind is None

    def test_missing_anchor_flagged_when_checked(self, audit_mod, tmp_path):
        target = tmp_path / "T.md"
        target.write_text("# Real Header\n", encoding="utf-8")
        src = tmp_path / "src.md"
        src.write_text("placeholder", encoding="utf-8")
        kind, detail = audit_mod._check_target(
            "T.md#fake-anchor", src,
            repo_root=tmp_path,
            check_anchors=True, md_anchor_cache={},
        )
        assert kind == "missing-anchor"
        assert "#fake-anchor" in detail

    def test_anchor_check_skipped_when_disabled(self, audit_mod, tmp_path):
        target = tmp_path / "T.md"
        target.write_text("# Real Header\n", encoding="utf-8")
        src = tmp_path / "src.md"
        src.write_text("placeholder", encoding="utf-8")
        kind, _ = audit_mod._check_target(
            "T.md#fake-anchor", src,
            repo_root=tmp_path,
            check_anchors=False, md_anchor_cache={},
        )
        assert kind is None  # path exists; anchor not checked


class TestInlineAllowMarker:
    """Same-line marker waiver."""

    def test_marker_waives_broken_link(self, audit_mod, tmp_path):
        """End-to-end through ``audit_tracked_tree`` is not the focus
        here (that needs git ls-files); test the line-level marker
        check directly."""
        raw = "Line 1\nBad [link](missing.md) <!-- audit-links: allow -->\n"
        assert audit_mod._line_has_allow_marker(raw, 2) is True

    def test_marker_on_different_line_doesnt_waive(self, audit_mod):
        raw = (
            "<!-- audit-links: allow -->\n"
            "Bad [link](missing.md)\n"
        )
        assert audit_mod._line_has_allow_marker(raw, 2) is False


class TestLiveCorpus:
    """Live tracked-tree default-mode must stay clean."""

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            capture_output=True, text=True, cwd=REPO_ROOT, check=False,
        )

    def test_live_default_exit_zero(self):
        """Path-only default mode must be clean post-narrow-fixes."""
        result = self._run()
        assert result.returncode == 0, (
            f"live tracked tree should be clean, got rc={result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert "All markdown links resolve cleanly" in result.stdout

    def test_live_json_shape(self):
        result = self._run("--json")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["count"] == 0
        assert data["findings"] == []
        assert data["check_anchors"] is False

    def test_help_works(self):
        result = self._run("--help")
        assert result.returncode == 0
        assert "audit_links" in result.stdout
        assert "--anchors" in result.stdout

    def test_anchors_mode_is_opt_in(self):
        """``--anchors`` is strict mode and may surface pre-existing
        doc rot; the test only verifies the flag is accepted and
        produces a clear exit code (0 or 1) without crashing."""
        result = self._run("--anchors")
        assert result.returncode in (0, 1), (
            f"--anchors should exit 0 or 1, got {result.returncode}\n"
            f"stderr:\n{result.stderr}"
        )
