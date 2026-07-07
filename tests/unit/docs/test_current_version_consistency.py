# SPDX-License-Identifier: Apache-2.0
"""Docs must not present a stale version as CURRENT (audit #15).

The shipped version drifted: README + ~13 docs said "Current ... v12.0.0"
while sndr.version was 12.1.0, mis-attributing 329 patches to 12.0.0. This
gate greps the current-context version claims in README + docs and asserts
they match sndr.version.__version__. Genuine history (changelog rows, "since
vX", "vX.Y.Z.md" links) is exempt.
"""
from __future__ import annotations

import re
from pathlib import Path

from sndr.version import __version__

_ROOT = Path(__file__).resolve().parents[3]
_DOCS = [_ROOT / "README.md", *sorted((_ROOT / "docs").glob("*.md"))]

# "current"-context lines that pin a version as the live one.
_CURRENT = re.compile(
    r"(current[^\n]*?|SNDR[ %]20?Core[- ]|SNDR Core |Genesis )v?(\d+\.\d+\.\d+)",
    re.I,
)
_HISTORY = re.compile(
    r"v\d+\.\d+\.\d+\.md|CHANGELOG|→|->|\bsince\b|\bwas\b|\bprevious\b"
    r"|series|superseded|2026-06-2\d|release\b[^\n]*2026-06",
    re.I,
)


def test_no_doc_presents_a_stale_version_as_current():
    offenders = []
    for doc in _DOCS:
        for n, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if _HISTORY.search(line):
                continue
            m = _CURRENT.search(line)
            if not m:
                continue
            found = m.group(2)
            # Only Genesis-version claims (same major); vLLM pins like
            # "current pin 0.23.1..." share the word "current" but are a
            # different version namespace — skip them.
            if found.split(".")[0] != __version__.split(".")[0]:
                continue
            if found != __version__:
                offenders.append(
                    f"{doc.relative_to(_ROOT)}:{n}: '{found}' != {__version__}"
                )
    assert not offenders, (
        "docs present a non-current version as current:\n  " + "\n  ".join(offenders)
    )
