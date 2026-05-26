#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""audit_links.py — markdown link integrity audit
(§9.A.3, AUDIT-CLOSURE.1.A.3, 2026-05-26).

Walks every tracked-tree markdown file and verifies inline links
``[text](target)`` + reference-style links ``[ref]: target``. Catches
the post-consolidation rot we hit during 2026-05-16 doc reshape:

  * stale references to merged-and-removed files (CLIFFS.md /
    OOM_RECIPES.md / BENCHMARK_GUIDE.md were merged into
    TROUBLESHOOTING.md + BENCHMARKS.md, but stale links lingered)
  * relative path miscalculation across moves
  * anchor drift (heading renamed but ``#old-slug`` references not
    updated)

Rules:

  * External URLs (``http://``, ``https://``, ``mailto:``, ``tel:``,
    ``ftp://``) are **never** verified — no network in scope.
  * Paths resolving OUTSIDE the repo root (sibling private trees) are
    **skipped** — they belong to operator's filesystem, not the audit's
    integrity surface.
  * Inline allow marker ``<!-- audit-links: allow -->`` on the same
    line waives a finding (historical reference, intentional placeholder,
    operator-acknowledged outlier).
  * Inline code spans (``` ` `` quotes ```) and fenced code blocks
    (``` ``` `` ``` ```) are stripped before link detection — they
    contain teaching examples / regex literals / shell snippets that
    look like markdown links but aren't.
  * Anchor verification: when a target ``foo.md#bar`` references a
    tracked markdown file, ``#bar`` must match a slugified header in
    that file. Slugification is GitHub-style: lowercase, replace
    ``\\W+`` with ``-``, strip leading/trailing hyphens.

Exit codes:
  0 — every in-tree link resolves; every checked anchor exists
  1 — at least one broken link or missing anchor
  2 — internal error / git not available

Modes:

  python3 scripts/audit_links.py            # path-only (default, gating)
  python3 scripts/audit_links.py --anchors  # also verify anchors (strict)
  python3 scripts/audit_links.py --json     # machine-readable

Anchor verification is **opt-in** because GitHub-flavored slug rules
have edge cases that can produce noisy false-positives on legitimate
docs (numbered-prefix headers, emoji, multiple-same-text headers with
``-1`` / ``-2`` disambiguation). Path verification is the high-
confidence gate; anchor strictness is operator-run during doc
reconciliation phases (§9.R) to surface TOC drift.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parent.parent


# ─── External / skip prefixes ─────────────────────────────────────────────


_EXTERNAL_PREFIXES: tuple[str, ...] = (
    "http://", "https://", "mailto:", "tel:", "ftp://",
    "ftps://", "file:",
)


# ─── Allow marker ─────────────────────────────────────────────────────────


# Lines carrying this marker (anywhere on the line) are exempt. Matches
# the convention used by ``audit_ai_attribution`` /
# ``audit_public_docs`` for explicit operator-acknowledged exceptions.
INLINE_ALLOW_MARKER = "<!-- audit-links: allow -->"


# ─── Markdown link patterns ───────────────────────────────────────────────


# Inline link  [text](target)
# ``target`` may contain spaces only inside ``< >``; we keep it tight to
# avoid matching shell-output snippets that happen to contain parens.
_INLINE_LINK_RE = re.compile(
    r"(?<!\\)\[([^\]\n]+)\]\(([^()\s]+)\)"
)

# Reference-style link target  [ref]: target
_REF_LINK_RE = re.compile(
    r"^\s{0,3}\[([^\]]+)\]:\s+(\S+)", re.MULTILINE,
)

# Fenced code block (``` or ~~~) — captured greedily; strip whole block.
_FENCED_CODE_RE = re.compile(
    r"(?P<fence>^[ \t]{0,3}(?:```|~~~)[^\n]*\n)"
    r"(?P<body>.*?)"
    r"(?P=fence)?$",
    re.MULTILINE | re.DOTALL,
)
# Inline code span: `...` or ``...`` (1+ backticks, balanced count).
_INLINE_CODE_RE = re.compile(r"(`+)[^\n]*?\1")

# Markdown headers — for slugifying anchors.
_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.MULTILINE)


# ─── Code-span stripping ──────────────────────────────────────────────────


def strip_code_spans(text: str) -> str:
    """Remove fenced code blocks + inline code spans from ``text``.

    Replaces each block / span with a same-length blank string so line
    numbers stay aligned for downstream line-number reporting.
    """
    # Fenced first.
    out: list[str] = []
    in_fence = False
    fence_marker: Optional[str] = None
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if not in_fence:
            if stripped.startswith("```") or stripped.startswith("~~~"):
                marker = stripped[:3]
                fence_marker = marker
                in_fence = True
                out.append("\n" if line.endswith("\n") else "")
                continue
            # Inline code spans
            out.append(_INLINE_CODE_RE.sub(
                lambda m: " " * len(m.group(0)), line))
        else:
            assert fence_marker is not None
            if stripped.startswith(fence_marker):
                in_fence = False
                fence_marker = None
            out.append("\n" if line.endswith("\n") else "")
    return "".join(out)


# ─── Anchor slugification (GitHub-style) ──────────────────────────────────


def slugify(header: str) -> str:
    """GitHub-flavored markdown slug for a header text.

    GitHub's actual rules (verified empirically against tracked-tree
    anchors in 2026-05-26 audit):

      1. Strip inline backticks ``` ` ```.
      2. Lowercase.
      3. Remove punctuation (anything that's not letter/digit/space/
         hyphen/underscore — so ``/``, ``&``, ``(``, ``)``, ``,`` etc.
         disappear). Adjacent whitespace remains.
      4. Replace whitespace runs with ``-`` per-character (NOT
         collapsed) — so "A / B" becomes "a--b" because the slash
         leaves two spaces.
      5. Strip leading/trailing hyphens.

    Multiple headers with the same text produce ``slug``, ``slug-1``,
    ``slug-2`` on GitHub — disambiguation NOT modeled here. The audit
    only verifies that ``slug`` exists for at least one header text.
    """
    # Strip inline backticks
    s = re.sub(r"`([^`]+)`", r"\1", header)
    s = s.lower()
    # Remove characters that aren't word char (letter/digit/_),
    # whitespace, or hyphen. Punctuation like `/`, `&`, `(`, `)`,
    # `,`, `:` is stripped — but the surrounding whitespace stays,
    # producing double hyphens after the next step (matches GitHub).
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    # Replace each whitespace character with hyphen (NOT collapsed).
    # Run-length collapse would destroy GitHub-preserved double-hyphens
    # from punctuation-adjacent spaces.
    s = re.sub(r"\s", "-", s)
    return s.strip("-")


def extract_headers(text: str) -> set[str]:
    """Return slugified anchor set for every header in ``text``."""
    out: set[str] = set()
    for m in _HEADER_RE.finditer(text):
        out.add(slugify(m.group(2)))
    return out


# ─── Tracked tree discovery ───────────────────────────────────────────────


def _git_ls_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True, text=True, cwd=REPO_ROOT, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git ls-files failed (rc={result.returncode}): {result.stderr}"
        )
    return [line for line in result.stdout.splitlines() if line]


# ─── Audit core ───────────────────────────────────────────────────────────


@dataclasses.dataclass
class Finding:
    source: str
    line: int
    raw_target: str
    resolved_path: Optional[str]
    kind: str       # "broken-path" | "missing-anchor"
    detail: str

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def _find_inline_links(stripped_text: str) -> list[tuple[int, str, str]]:
    """Return (line_number, link_text, target) for every inline link."""
    out: list[tuple[int, str, str]] = []
    for m in _INLINE_LINK_RE.finditer(stripped_text):
        lineno = stripped_text.count("\n", 0, m.start()) + 1
        out.append((lineno, m.group(1), m.group(2)))
    return out


def _find_ref_links(stripped_text: str) -> list[tuple[int, str, str]]:
    out: list[tuple[int, str, str]] = []
    for m in _REF_LINK_RE.finditer(stripped_text):
        lineno = stripped_text.count("\n", 0, m.start()) + 1
        out.append((lineno, m.group(1), m.group(2)))
    return out


def _line_has_allow_marker(raw_text: str, line_number: int) -> bool:
    """Check the marker on the ORIGINAL (un-stripped) line — we want
    the operator-readable line to carry the marker, not the parsed
    representation."""
    lines = raw_text.splitlines()
    if 0 < line_number <= len(lines):
        return INLINE_ALLOW_MARKER in lines[line_number - 1]
    return False


def _check_target(
    target: str,
    source_md: Path,
    *,
    repo_root: Path,
    check_anchors: bool,
    md_anchor_cache: dict[Path, set[str]],
) -> tuple[Optional[str], Optional[str]]:
    """Verify ``target`` resolves and (optionally) anchor exists.

    Returns ``(kind, detail)`` where ``kind`` is None if OK, else
    ``broken-path`` / ``missing-anchor`` with ``detail`` describing
    the issue.
    """
    # Skip external + pure-anchor (same-page) targets.
    if any(target.startswith(p) for p in _EXTERNAL_PREFIXES):
        return None, None
    if target.startswith("#"):
        # Same-file anchor — verify if checking anchors.
        if not check_anchors:
            return None, None
        text = source_md.read_text(encoding="utf-8", errors="replace")
        anchors = md_anchor_cache.setdefault(
            source_md, extract_headers(text),
        )
        slug = target[1:]
        if slug not in anchors:
            return "missing-anchor", (
                f"same-file anchor #{slug} not found "
                f"(headers in {source_md.name}: {sorted(anchors)[:5]}…)"
            )
        return None, None

    # Split off anchor
    path_part, _, anchor = target.partition("#")
    if not path_part:
        return None, None

    # Resolve relative to source file's directory.
    resolved = (source_md.parent / path_part).resolve()
    # If resolved is outside repo, skip (operator's filesystem).
    try:
        resolved.relative_to(repo_root)
    except ValueError:
        return None, None

    if not resolved.exists():
        return "broken-path", (
            f"target does not exist: {resolved.relative_to(repo_root)}"
        )

    # Anchor verification (only for .md targets).
    if check_anchors and anchor and resolved.suffix.lower() == ".md":
        text = resolved.read_text(encoding="utf-8", errors="replace")
        anchors = md_anchor_cache.setdefault(
            resolved, extract_headers(text),
        )
        if anchor not in anchors:
            return "missing-anchor", (
                f"anchor #{anchor} not in "
                f"{resolved.relative_to(repo_root)}"
            )

    return None, None


def audit_tracked_tree(
    *,
    check_anchors: bool = True,
    repo_root: Optional[Path] = None,
) -> list[Finding]:
    repo_root = (repo_root or REPO_ROOT).resolve()
    files = _git_ls_files()
    md_files = [repo_root / rel for rel in files if rel.endswith(".md")]

    findings: list[Finding] = []
    md_anchor_cache: dict[Path, set[str]] = {}

    for md in md_files:
        if not md.exists():
            continue
        raw = md.read_text(encoding="utf-8", errors="replace")
        stripped = strip_code_spans(raw)

        # Inline links
        for lineno, _text, target in _find_inline_links(stripped):
            if _line_has_allow_marker(raw, lineno):
                continue
            kind, detail = _check_target(
                target, md,
                repo_root=repo_root,
                check_anchors=check_anchors,
                md_anchor_cache=md_anchor_cache,
            )
            if kind is None:
                continue
            findings.append(Finding(
                source=str(md.relative_to(repo_root)),
                line=lineno,
                raw_target=target,
                resolved_path=None,
                kind=kind,
                detail=detail or "",
            ))

        # Reference-style links
        for lineno, _ref, target in _find_ref_links(stripped):
            if _line_has_allow_marker(raw, lineno):
                continue
            kind, detail = _check_target(
                target, md,
                repo_root=repo_root,
                check_anchors=check_anchors,
                md_anchor_cache=md_anchor_cache,
            )
            if kind is None:
                continue
            findings.append(Finding(
                source=str(md.relative_to(repo_root)),
                line=lineno,
                raw_target=target,
                resolved_path=None,
                kind=kind,
                detail=detail or "",
            ))

    return findings


# ─── Render ───────────────────────────────────────────────────────────────


def _render_text(findings: list[Finding]) -> str:
    lines: list[str] = []
    lines.append("audit-links: markdown link integrity")
    lines.append("─" * 70)
    lines.append(f"  findings: {len(findings)}")
    by_kind: dict[str, int] = {}
    for f in findings:
        by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
    for kind, count in sorted(by_kind.items()):
        lines.append(f"    {kind:20s} {count}")
    lines.append("")
    for f in findings[:60]:
        lines.append(f"  ✗ {f.source}:{f.line}  [{f.kind}]")
        lines.append(f"      target: {f.raw_target}")
        lines.append(f"      detail: {f.detail}")
    if len(findings) > 60:
        lines.append(f"  … ({len(findings) - 60} more)")
    if not findings:
        lines.append("  ✓ All markdown links resolve cleanly")
    else:
        lines.append("")
        lines.append(
            "  ✗ Fix: update the link target OR add the inline marker\n"
            f"      to acknowledge a historical reference: "
            f"{INLINE_ALLOW_MARKER}"
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable JSON")
    ap.add_argument(
        "--anchors", action="store_true",
        help="ALSO verify in-file/cross-file anchors (strict mode; "
             "opt-in due to slug-rule edge cases)",
    )
    args = ap.parse_args()

    try:
        findings = audit_tracked_tree(check_anchors=args.anchors)
    except RuntimeError as e:
        print(f"audit-links: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({
            "findings": [f.as_dict() for f in findings],
            "count": len(findings),
            "check_anchors": args.anchors,
        }, indent=2, sort_keys=True))
    else:
        print(_render_text(findings))

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
