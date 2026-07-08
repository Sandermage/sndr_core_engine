# SPDX-License-Identifier: Apache-2.0
"""Curated docs must not drift from the registry's `default_on` count.

`scripts/check_doc_sync.py` guards the *total* patch count (329) across docs,
but nothing guarded the `default_on` numerator — so README claimed "58 of 329"
and FAQ "56 of 325" while the registry says 56 / 329 (verified drift, fixed
2026-07-08). This gate closes that gap: every curated doc that states a
default-on count is validated against the live `PATCH_REGISTRY`.

The auto-generated `docs/PATCHES_AUTO.md` is excluded — it is regenerated from
the registry and guarded by `generate_patches_md.py --check`.
"""
from __future__ import annotations

import re
from pathlib import Path

from sndr.dispatcher import registry

REPO_ROOT = Path(__file__).resolve().parents[3]

# Curated (hand-maintained) docs that cite a default-on count.
CURATED_DOCS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs" / "FAQ.md",
    REPO_ROOT / "docs" / "CONFIGURATION.md",
    REPO_ROOT / "docs" / "PATCHES.md",
]


def _registry_counts() -> tuple[int, int]:
    total = len(registry.PATCH_REGISTRY)
    default_on = sum(1 for e in registry.PATCH_REGISTRY.values() if e.get("default_on"))
    return default_on, total


# "N of M entries ... default_on" — README + FAQ prose form.
_N_OF_M = re.compile(
    r"(\d+)\s+of\s+(\d+)\s+entries[^.\n]*?default[_-]on", re.IGNORECASE
)
# "(N default-on)" — CONFIGURATION parenthetical.
_PAREN = re.compile(r"\((\d+)\s+default-on\)", re.IGNORECASE)
# "Default-on at boot | N" or "Default-on at boot: N / M".
_AT_BOOT = re.compile(
    r"Default-on at boot\s*[:|]\s*\**(\d+)\**\s*(?:/\s*(\d+))?", re.IGNORECASE
)


def test_registry_default_on_is_56_of_329():
    """Anchor the expected numbers so a registry change surfaces here too."""
    default_on, total = _registry_counts()
    assert (default_on, total) == (56, 329), (
        f"registry default_on/total changed to {default_on}/{total} — update the "
        f"curated docs and this anchor together."
    )


def test_curated_docs_default_on_counts_match_registry():
    default_on, total = _registry_counts()
    problems: list[str] = []

    for doc in CURATED_DOCS:
        if not doc.is_file():
            continue
        text = doc.read_text()
        rel = doc.relative_to(REPO_ROOT)

        for m in _N_OF_M.finditer(text):
            n, mtot = int(m.group(1)), int(m.group(2))
            if n != default_on or mtot != total:
                problems.append(
                    f"{rel}: '{n} of {mtot} entries ... default_on' but registry "
                    f"is {default_on} of {total}"
                )
        for m in _PAREN.finditer(text):
            n = int(m.group(1))
            if n != default_on:
                problems.append(
                    f"{rel}: '({n} default-on)' but registry default_on is {default_on}"
                )
        for m in _AT_BOOT.finditer(text):
            n = int(m.group(1))
            mtot = int(m.group(2)) if m.group(2) else total
            if n != default_on or mtot != total:
                problems.append(
                    f"{rel}: 'Default-on at boot {n}/{mtot}' but registry is "
                    f"{default_on}/{total}"
                )

    assert not problems, "default_on count drift:\n  " + "\n  ".join(problems)
