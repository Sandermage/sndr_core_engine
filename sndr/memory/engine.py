# SPDX-License-Identifier: Apache-2.0
"""`MemoryEngine` — the storage-agnostic, text-level facade.

This is what the proxy memory-middleware and the product-API call. It owns the
embedder, turns text into vectors, and delegates persistence + brain mechanics
to a `MemoryStore`. It also runs the semantic auto-linker (`link_semantic`):
kNN over embeddings -> `similar_to` edges, which is the mechanism that turns a
pile of isolated notes into the connected "neuron cloud" graph.

Everything here is backend-agnostic: swap `InMemoryStore` for the Postgres
backend and the engine is unchanged.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sndr.memory.model import SEMANTIC_EDGE_TAU

if TYPE_CHECKING:
    from sndr.memory.embedder import Embedder
    from sndr.memory.model import SearchHit
    from sndr.memory.store import MemoryStore

_SIMILAR_REL = "similar_to"


class MemoryEngine:
    def __init__(self, *, store: MemoryStore, embedder: Embedder) -> None:
        self.store = store
        self.embedder = embedder

    # ── write ────────────────────────────────────────────────────────────
    def remember(
        self,
        *,
        owner_id: int,
        text: str,
        kind: str = "note",
        importance: float = 0.0,
        properties: dict[str, Any] | None = None,
    ) -> int:
        embedding = self.embedder.embed_one(text)
        return self.store.add_node(
            owner_id=owner_id,
            kind=kind,
            content=text,
            embedding=embedding,
            importance=importance,
            properties=properties,
        )

    # ── read ─────────────────────────────────────────────────────────────
    def recall(
        self,
        *,
        owner_id: int,
        query: str,
        limit: int = 10,
        expand_depth: int = 2,
        reinforce: bool = True,
    ) -> list[SearchHit]:
        query_vec = self.embedder.embed_one(query)
        return self.store.recall(
            owner_id=owner_id,
            query=query_vec,
            limit=limit,
            expand_depth=expand_depth,
            reinforce=reinforce,
        )

    # ── batch graph building ─────────────────────────────────────────────
    def link_semantic(
        self,
        *,
        owner_id: int,
        tau: float = SEMANTIC_EDGE_TAU,
        k: int = 10,
    ) -> int:
        """Connect each node to its kNN neighbours above cosine `tau` with a
        (canonical, undirected) `similar_to` edge weighted by the similarity.
        Returns the number of distinct edges created. Idempotent on weight
        (re-running re-asserts the same edge). Storage-agnostic: uses only
        iter_nodes + search + add_edge.
        """
        linked: set[tuple[int, int]] = set()
        for node in list(self.store.iter_nodes(owner_id)):
            for hit in self.store.search(
                owner_id=owner_id, query=node.embedding, limit=k + 1
            ):
                if hit.id == node.id or hit.score < tau:
                    continue
                a, b = min(node.id, hit.id), max(node.id, hit.id)
                if (a, b) in linked:
                    continue
                linked.add((a, b))
                self.store.add_edge(a, b, _SIMILAR_REL, weight=hit.score)
        return len(linked)
