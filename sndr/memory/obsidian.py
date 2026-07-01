# SPDX-License-Identifier: Apache-2.0
"""Obsidian vault import — bring an existing knowledge graph into memory.

An Obsidian vault is already a graph: notes connected by `[[wikilinks]]`. This
importer maps it directly onto our model — each `.md` note becomes a memory node
(deduped by content), each wikilink becomes a `wikilink` edge between the two
notes, and `#tags` are captured in `properties`. So the memory graph inherits the
structure you already built by hand in Obsidian, and the brain mechanics
(semantic linking, communities, decay) layer on top.

Two-pass: create all nodes first (title -> id), then resolve wikilinks to edges.
Path safety (confining the vault to an allowed root) is enforced by the API
layer; this function just needs a real directory.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sndr.memory.engine import MemoryEngine

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_TAG_RE = re.compile(r"(?:^|\s)#(\w[\w/-]*)")
_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)  # the note's display title (first H1)


def _wikilink_target(raw: str) -> str:
    """`[[Note|alias]]` / `[[Note#heading]]` -> the bare note title `Note`."""
    target = raw.split("|", 1)[0]
    target = target.split("#", 1)[0]
    return target.strip()


def import_vault(
    *, engine: MemoryEngine, owner_id: int, vault_path: str, kind: str = "note"
) -> dict[str, int]:
    """Import every `.md` note under `vault_path` into the owner's memory.

    Returns a report: {notes, links, missing} (missing = wikilinks with no target
    note in the vault). Idempotent — re-importing dedups on content.
    """
    root = Path(vault_path)
    if not root.is_dir():
        raise NotADirectoryError(f"vault is not a directory: {vault_path}")
    root_real = root.resolve()

    files = sorted(p for p in root.rglob("*.md") if p.is_file())

    # Pass 1 — a node per note, keyed by title (the file stem, as Obsidian does).
    title_to_id: dict[str, int] = {}
    wikilinks: dict[int, list[str]] = {}
    notes = 0
    for path in files:
        # Defense in depth: skip files (e.g. symlinks) that resolve OUTSIDE the
        # vault root, so an in-vault symlink can't exfiltrate arbitrary files.
        try:
            real = path.resolve()
        except OSError:
            continue
        if real != root_real and root_real not in real.parents:
            continue
        try:
            text = real.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        title = path.stem
        tags = sorted(set(_TAG_RE.findall(text)))
        node_id = engine.remember(
            owner_id=owner_id,
            text=text,
            kind=kind,
            properties={"title": title, "source": "obsidian", "tags": tags},
            dedup=True,
        )
        # Index by BOTH the filename stem AND the first H1, case-INSENSITIVELY —
        # Obsidian resolves [[Note]] to either, ignoring case, so a link like
        # [[Qwen3.6-35B]] finds qwen.md whose H1 is "# Qwen3.6-35B".
        title_to_id[title.lower()] = node_id
        h1 = _H1_RE.search(text)
        if h1:
            title_to_id.setdefault(h1.group(1).strip().lower(), node_id)
        wikilinks[node_id] = [_wikilink_target(m) for m in _WIKILINK_RE.findall(text)]
        notes += 1

    # Pass 2 — resolve wikilinks to edges (skip self-links and unknown targets).
    links = 0
    missing = 0
    for src_id, targets in wikilinks.items():
        for target in targets:
            dst_id = title_to_id.get(target.strip().lower())
            if dst_id is None:
                missing += 1
                continue
            if dst_id == src_id:
                continue
            engine.store.add_edge(src_id, dst_id, "wikilink", weight=1.0)
            links += 1

    return {"notes": notes, "links": links, "missing": missing}
