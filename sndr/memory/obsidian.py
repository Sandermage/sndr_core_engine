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
_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)
_UNSAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _wikilink_target(raw: str) -> str:
    """`[[Note|alias]]` / `[[Note#heading]]` -> the bare note title `Note`."""
    target = raw.split("|", 1)[0]
    target = target.split("#", 1)[0]
    return target.strip()


def _parse_frontmatter(text: str) -> tuple[dict[str, list[str]], str]:
    """Split a leading Obsidian `---` YAML frontmatter block off `text`.

    Returns ({key: [values]}, body). Dependency-free: handles the two common
    list forms — inline ``tags: [a, b]`` and block ``tags:`` + ``  - a`` — for
    the keys we care about (tags, aliases). Anything unparseable is ignored,
    never raised.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    block, body = m.group(1), text[m.end():]
    fields: dict[str, list[str]] = {}
    current: str | None = None
    for raw in block.splitlines():
        if not raw.strip():
            continue
        if raw[:1].isspace():  # block-list continuation ("  - value")
            item = raw.strip().lstrip("-").strip().strip("'\"")
            if current and item:
                fields.setdefault(current, []).append(item)
            continue
        if ":" not in raw:
            continue
        key, _, val = raw.partition(":")
        current = key.strip().lower()
        val = val.strip()
        if not val:
            continue  # values arrive on following block-list lines
        if val.startswith("[") and val.endswith("]"):
            items = [v.strip().strip("'\"") for v in val[1:-1].split(",")]
            fields[current] = [v for v in items if v]
        else:
            fields[current] = [val.strip("'\"")]
    return fields, body


def _safe_filename(name: str, node_id: int) -> str:
    stem = _UNSAFE_FILENAME_RE.sub("-", name).strip() or f"node-{node_id}"
    return f"{stem}.md"


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
        frontmatter, _body = _parse_frontmatter(text)
        # Tags = inline #tags UNION frontmatter `tags:`. Aliases from frontmatter
        # become extra resolution keys for wikilinks (Obsidian resolves [[alias]]).
        aliases = frontmatter.get("aliases", [])
        rel_path = str(real.relative_to(root_real))
        tags = sorted(set(_TAG_RE.findall(text)) | set(frontmatter.get("tags", [])))
        node_id = engine.remember(
            owner_id=owner_id,
            text=text,
            kind=kind,
            properties={
                "title": title, "source": "obsidian", "tags": tags,
                "path": rel_path, "aliases": aliases,
            },
            dedup=True,
        )
        # Index by the filename stem, the first H1, AND every frontmatter alias,
        # case-INSENSITIVELY — Obsidian resolves [[Note]] to any of them.
        title_to_id[title.lower()] = node_id
        h1 = _H1_RE.search(text)
        if h1:
            title_to_id.setdefault(h1.group(1).strip().lower(), node_id)
        for alias in aliases:
            title_to_id.setdefault(alias.strip().lower(), node_id)
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


def _node_title(node) -> str:
    """Display title for a node: its stored `title`, else the first H1, else a
    stable node-id fallback."""
    title = node.properties.get("title")
    if title:
        return str(title)
    h1 = _H1_RE.search(node.content or "")
    return h1.group(1).strip() if h1 else f"node-{node.id}"


def export_vault(
    *, engine: MemoryEngine, owner_id: int, vault_path: str
) -> dict[str, int]:
    """Materialize this owner's memory graph OUT as an Obsidian vault: one `.md`
    note per node (its content), with outgoing non-invalidated edges rendered as
    a `## Links` section of `[[wikilinks]]` to the neighbour nodes' titles.

    The inverse of :func:`import_vault` — so agent-generated memories become notes
    you can open in Obsidian. Returns {notes, links}. Path safety (confining the
    vault to an allowed root) is the caller's job; this needs a real directory.
    """
    root = Path(vault_path)
    root.mkdir(parents=True, exist_ok=True)
    root_real = root.resolve()

    nodes = list(engine.store.iter_nodes(owner_id))
    id_to_title = {n.id: _node_title(n) for n in nodes}

    used: set[str] = set()
    notes = 0
    links = 0
    for node in nodes:
        title = id_to_title[node.id]
        fname = _safe_filename(title, node.id)
        if fname in used:  # title collision -> disambiguate by id
            fname = _safe_filename(f"{title}-{node.id}", node.id)
        used.add(fname)

        body = (node.content or "").rstrip()
        wikilinks = []
        for dst_id, _rel, _w in engine.store.neighbors(node.id):
            dst_title = id_to_title.get(dst_id)
            if dst_title:
                wikilinks.append(f"- [[{dst_title}]]")
                links += 1
        parts = [body]
        if wikilinks:
            parts.append("\n## Links\n" + "\n".join(wikilinks))
        out_path = (root_real / fname)
        # Defense in depth: never write outside the vault root.
        if out_path.resolve().parent != root_real:
            continue
        out_path.write_text("\n".join(parts) + "\n", encoding="utf-8")
        notes += 1

    return {"notes": notes, "links": links}
