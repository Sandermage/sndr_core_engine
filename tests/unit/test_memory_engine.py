# SPDX-License-Identifier: Apache-2.0
"""TDD contract for `MemoryEngine` (Phase 1, verifiable without a DB).

The engine is the storage-agnostic, text-level facade the proxy middleware and
the product-API will call: it owns the embedder and delegates persistence +
brain mechanics to a `MemoryStore`. It also runs the semantic auto-linker
(kNN -> `similar_to` edges) that turns isolated notes into a connected graph.

Backed here by `HashEmbedder` + `InMemoryStore`, so it is fully verified
locally; the same engine runs unchanged on the Postgres backend.
"""
from __future__ import annotations

from sndr.memory.embedder import HashEmbedder
from sndr.memory.engine import MemoryEngine
from sndr.memory.inmemory import InMemoryStore


def _engine() -> MemoryEngine:
    return MemoryEngine(store=InMemoryStore(), embedder=HashEmbedder(dim=512))


class TestRememberRecall:
    def test_remember_returns_id_and_recall_finds_it(self):
        eng = _engine()
        nid = eng.remember(owner_id=1, text="postgres vector memory graph")
        hits = eng.recall(owner_id=1, query="postgres vector memory graph", limit=5)
        assert nid in [h.id for h in hits]

    def test_recall_ranks_topical_over_unrelated(self):
        eng = _engine()
        topical = eng.remember(owner_id=1, text="postgres vector memory engine")
        eng.remember(owner_id=1, text="banana orange weather guitar")
        hits = eng.recall(owner_id=1, query="postgres vector memory graph",
                          limit=5, expand_depth=0)
        assert hits[0].id == topical

    def test_remember_is_owner_scoped(self):
        eng = _engine()
        eng.remember(owner_id=1, text="shared topic words here")
        hits = eng.recall(owner_id=2, query="shared topic words here", limit=5)
        assert hits == []


class TestSemanticLinking:
    def test_links_similar_notes_not_dissimilar(self):
        eng = _engine()
        a = eng.remember(owner_id=1, text="postgres vector memory graph")
        b = eng.remember(owner_id=1, text="postgres vector memory engine")
        c = eng.remember(owner_id=1, text="banana orange weather guitar")
        created = eng.link_semantic(owner_id=1, tau=0.5, k=10)
        assert created >= 1
        # a and b share 3/4 tokens (cosine ~0.75) -> linked
        assert eng.store.edge_weight(min(a, b), max(a, b), "similar_to") > 0.0
        # c shares nothing -> not linked to a
        assert eng.store.edge_weight(min(a, c), max(a, c), "similar_to") == 0.0
        assert eng.store.edge_weight(min(b, c), max(b, c), "similar_to") == 0.0

    def test_link_semantic_does_not_self_link(self):
        eng = _engine()
        a = eng.remember(owner_id=1, text="alpha beta gamma delta")
        eng.link_semantic(owner_id=1, tau=0.1, k=10)
        assert eng.store.edge_weight(a, a, "similar_to") == 0.0

    def test_recall_expand_reaches_semantically_linked_neighbor(self):
        eng = _engine()
        # x matches the query; y is similar to x but NOT to the query token
        x = eng.remember(owner_id=1, text="postgres vector memory graph")
        y = eng.remember(owner_id=1, text="postgres vector memory store")
        eng.link_semantic(owner_id=1, tau=0.5, k=10)
        direct = {h.id for h in eng.recall(owner_id=1, query="graph",
                                          limit=10, expand_depth=0, reinforce=False)}
        expanded = {h.id for h in eng.recall(owner_id=1, query="graph",
                                            limit=10, expand_depth=1, reinforce=False)}
        assert x in direct          # x is a direct ANN hit on the query token
        assert y not in direct      # y is not (it lacks the query token)
        assert y in expanded        # but it is reached via the similar_to edge
