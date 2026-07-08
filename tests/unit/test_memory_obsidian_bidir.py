# SPDX-License-Identifier: Apache-2.0
"""Obsidian integration, both directions.

Before this the vault link was import-only, and the importer ignored YAML
frontmatter (tags/aliases/title). This adds:
  * `export_vault` — materialize the memory graph back OUT as Obsidian markdown
    (one note per node, edges rendered as [[wikilinks]]), so agent-generated
    memories show up in your vault.
  * frontmatter-aware import — parse the `---` block for tags + aliases, and
    resolve wikilinks that target an alias.
"""
from __future__ import annotations

from sndr.memory.embedder import HashEmbedder
from sndr.memory.engine import MemoryEngine
from sndr.memory.inmemory import InMemoryStore
from sndr.memory.obsidian import export_vault, import_vault


def _engine() -> MemoryEngine:
    return MemoryEngine(store=InMemoryStore(), embedder=HashEmbedder(dim=64))


# ── export: memory -> vault ───────────────────────────────────────────────────


def test_export_writes_one_markdown_file_per_node(tmp_path):
    eng = _engine()
    eng.remember(owner_id=1, text="Qwen3.6-35B runs at TP=2",
                 properties={"title": "Qwen Rig"})
    eng.remember(owner_id=1, text="Gemma 4 26B fits one card",
                 properties={"title": "Gemma Rig"})
    rep = export_vault(engine=eng, owner_id=1, vault_path=str(tmp_path))
    md = sorted(p.name for p in tmp_path.rglob("*.md"))
    assert len(md) == 2
    assert rep["notes"] == 2
    # Content is materialized.
    joined = "\n".join(p.read_text() for p in tmp_path.rglob("*.md"))
    assert "TP=2" in joined


def test_export_renders_edges_as_wikilinks(tmp_path):
    eng = _engine()
    a = eng.remember(owner_id=1, text="note A", properties={"title": "Alpha"})
    b = eng.remember(owner_id=1, text="note B", properties={"title": "Beta"})
    eng.store.add_edge(a, b, "wikilink", weight=1.0)
    export_vault(engine=eng, owner_id=1, vault_path=str(tmp_path))
    joined = "\n".join(p.read_text() for p in tmp_path.rglob("*.md"))
    assert "[[Beta]]" in joined


def test_export_only_touches_own_owner(tmp_path):
    eng = _engine()
    eng.remember(owner_id=1, text="mine", properties={"title": "Mine"})
    eng.remember(owner_id=2, text="theirs", properties={"title": "Theirs"})
    rep = export_vault(engine=eng, owner_id=1, vault_path=str(tmp_path))
    assert rep["notes"] == 1


def test_import_then_export_round_trips(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "A.md").write_text("# A\nlinks to [[B]]\n")
    (vault / "B.md").write_text("# B\nleaf\n")
    eng = _engine()
    import_vault(engine=eng, owner_id=1, vault_path=str(vault))
    out = tmp_path / "out"
    out.mkdir()
    rep = export_vault(engine=eng, owner_id=1, vault_path=str(out))
    assert rep["notes"] == 2
    # The [[B]] edge survives the round-trip into the exported markdown.
    joined = "\n".join(p.read_text() for p in out.rglob("*.md"))
    assert "[[B]]" in joined


# ── frontmatter-aware import ──────────────────────────────────────────────────


def test_import_parses_frontmatter_tags(tmp_path):
    vault = tmp_path
    (vault / "Note.md").write_text(
        "---\ntags: [rig, gpu]\naliases: [TheRig]\n---\n# Note\nbody\n"
    )
    eng = _engine()
    import_vault(engine=eng, owner_id=1, vault_path=str(vault))
    node = next(eng.store.iter_nodes(1))
    tags = node.properties.get("tags", [])
    assert "rig" in tags
    assert "gpu" in tags


def test_import_resolves_wikilink_to_frontmatter_alias(tmp_path):
    vault = tmp_path
    (vault / "Canonical.md").write_text(
        "---\naliases: [Nick]\n---\n# Canonical\nthe real note\n"
    )
    (vault / "Other.md").write_text("# Other\nsee [[Nick]]\n")
    eng = _engine()
    rep = import_vault(engine=eng, owner_id=1, vault_path=str(vault))
    # The [[Nick]] link resolves to the aliased note -> a real edge, not missing.
    assert rep["links"] >= 1
    assert rep["missing"] == 0
