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

from sndr.memory.model import SEMANTIC_EDGE_TAU, SearchHit

if TYPE_CHECKING:
    from collections.abc import Callable

    from sndr.memory.embedder import Embedder
    from sndr.memory.store import MemoryStore

_SIMILAR_REL = "similar_to"

# Cap the observations quoted into a reflection prompt (context budget).
_REFLECT_MAX_OBS = 20


def _reflection_prompt(contents: list[str]) -> str:
    """Build the Generative-Agents-style reflection prompt from a cluster of
    observation texts."""
    obs = "\n".join(f"- {c.strip()}" for c in contents[:_REFLECT_MAX_OBS] if c.strip())
    return (
        "You are the reflective memory of an assistant. Given these related "
        "observations, state ONE concise higher-level insight they imply "
        "(one sentence, no preamble). If they imply nothing, answer with an "
        "empty line.\n\n"
        f"Observations:\n{obs}\n\nInsight:"
    )


def run_maintenance(
    engine: MemoryEngine,
    *,
    max_nodes: int,
    tau: float = SEMANTIC_EDGE_TAU,
    working_capacity: int = 50,
    working_promote_access: int = 2,
) -> dict[str, Any]:
    """One maintenance pass over every owner — the design's "nightly batch":
    promote proven working memories to long-term, bound the working scratchpad
    to `working_capacity`, consolidate (auto-link + communities + importance),
    then prune to `max_nodes` (the wired leak-bound). This is what the background
    scheduler calls on a timer. Returns a small report."""
    owners = engine.store.owner_ids()
    pruned = 0
    promoted = 0
    for owner_id in owners:
        promoted += engine.promote_working(
            owner_id=owner_id, min_access=working_promote_access
        )
        engine.prune_working(owner_id=owner_id, capacity=working_capacity)
        engine.consolidate(owner_id=owner_id, tau=tau)
        pruned += engine.store.prune(owner_id=owner_id, max_nodes=max_nodes)
    return {"owners": owners, "pruned": pruned, "promoted": promoted}


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
        dedup: bool = True,
    ) -> int:
        """Store `text` as a node; return its id. With `dedup` (default), an
        existing node with identical content for this owner is returned instead
        of inserting a duplicate (prevents memory bloat from repeated facts)."""
        if dedup:
            existing = self.store.find_by_content(owner_id=owner_id, content=text)
            if existing is not None:
                return existing
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
    def search(
        self, *, owner_id: int, query: str, limit: int = 10
    ) -> list[SearchHit]:
        """Pure ANN search by text — no graph expand, no side effects (the
        idempotent GET path). Use `recall` for the brain op."""
        return self.store.search(
            owner_id=owner_id, query=self.embedder.embed_one(query), limit=limit
        )

    def search_hybrid(
        self, *, owner_id: int, query: str, limit: int = 10, alpha: float = 0.5
    ) -> list[SearchHit]:
        """Blend semantic (vector) and lexical (keyword) search — alpha weights
        the vector side. Each side is max-normalized (divided by its own top
        score) to [0,1] before mixing, so exact terms/names/IDs (lexical) and
        meaning (vector) both count on a comparable scale."""
        vec = self.store.search(
            owner_id=owner_id, query=self.embedder.embed_one(query), limit=limit * 2
        )
        kw = self.store.keyword_search(owner_id=owner_id, query=query, limit=limit * 2)

        def _norm(hits: list[SearchHit]) -> dict[int, float]:
            top = max((h.score for h in hits), default=0.0)
            return {h.id: (h.score / top if top > 0 else 0.0) for h in hits}

        nv, nk = _norm(vec), _norm(kw)
        nodes = {h.id: h.node for h in kw}
        nodes.update({h.id: h.node for h in vec})
        scored = [
            SearchHit(node=nodes[i], score=alpha * nv.get(i, 0.0) + (1 - alpha) * nk.get(i, 0.0))
            for i in nodes
        ]
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:limit]

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

    # ── consolidation (the "nightly batch": link -> cluster -> rank) ──────
    def detect_communities(self, *, owner_id: int, max_iter: int = 20) -> dict[int, int]:
        """Assign community ids (the "clouds") via deterministic weighted label
        propagation over the owner's graph. Pure-Python (no igraph/Leiden dep);
        good enough for homelab-scale graphs. Persists community_id and returns
        {node_id: community}."""
        nodes = list(self.store.iter_nodes(owner_id))
        ids = {n.id for n in nodes}
        adj: dict[int, list[tuple[int, float]]] = {n.id: [] for n in nodes}
        for nid in ids:
            for neigh_id, _rel, weight in self.store.neighbors(nid):
                if neigh_id in ids:
                    adj[nid].append((neigh_id, weight))
        label = {nid: nid for nid in ids}
        order = sorted(ids)  # deterministic sweep
        for _ in range(max_iter):
            changed = False
            for nid in order:
                if not adj[nid]:
                    continue
                tally: dict[int, float] = {}
                for neigh_id, weight in adj[nid]:
                    tally[label[neigh_id]] = tally.get(label[neigh_id], 0.0) + weight
                # highest weighted label; tie-break on smallest id -> deterministic
                best = max(sorted(tally), key=lambda lab: tally[lab])
                if label[nid] != best:
                    label[nid] = best
                    changed = True
            if not changed:
                break
        # renumber to dense 0..k-1 (stable)
        remap = {lab: i for i, lab in enumerate(sorted(set(label.values())))}
        result = {nid: remap[label[nid]] for nid in ids}
        self.store.set_communities(result)
        return result

    def recompute_importance(self, *, owner_id: int) -> dict[int, float]:
        """Heuristic importance in [0,1] from connectivity + use: a hub matters
        more than a leaf or an isolated note. Blends degree COUNT (centrality —
        how many things connect here), weighted degree (how strongly), and access
        count (how often used), so neither a single very strong edge nor raw
        popularity alone dominates. Persists importance; returns {node_id: value}."""
        nodes = list(self.store.iter_nodes(owner_id))
        ids = {n.id for n in nodes}
        raw: dict[int, float] = {}
        for node in nodes:
            neighbours = [
                w for nb, _rel, w in self.store.neighbors(node.id) if nb in ids
            ]
            degree_count = len(neighbours)          # centrality (# connections)
            weighted_degree = sum(neighbours)        # connection strength
            raw[node.id] = degree_count + weighted_degree + 0.25 * node.access_count
        hi = max(raw.values(), default=0.0)
        result = {nid: (v / hi if hi > 0 else 0.0) for nid, v in raw.items()}
        self.store.set_importance(result)
        return result

    def consolidate(
        self, *, owner_id: int, tau: float = SEMANTIC_EDGE_TAU, k: int = 10
    ) -> dict[str, int]:
        """The full batch the design calls for, as one call: semantic auto-link
        -> community detection -> importance. Returns a small report. Cheap
        enough to run on demand (the GUI's button) or on a schedule."""
        linked = self.link_semantic(owner_id=owner_id, tau=tau, k=k)
        communities = self.detect_communities(owner_id=owner_id)
        self.recompute_importance(owner_id=owner_id)
        return {
            "linked": linked,
            "communities": len(set(communities.values())),
            "nodes": len(communities),
        }

    # ── working-memory tier (capacity-bounded short-term + promotion) ───────
    def prune_working(self, *, owner_id: int, capacity: int) -> int:
        """Keep only the ``capacity`` most-recent ``working`` memories for this
        owner; evict the rest. Working memory is a scratchpad, not an
        ever-growing log — this is its capacity bound. Returns how many were
        evicted. Non-working memories are never touched."""
        working = [
            n for n in self.store.iter_nodes(owner_id) if n.kind == "working"
        ]
        # newest first (created_at, id as tiebreak) — evict the tail.
        working.sort(key=lambda n: (n.created_at, n.id), reverse=True)
        evicted = 0
        for node in working[capacity:]:
            self.store.delete_node(node.id, owner_id=owner_id)
            evicted += 1
        return evicted

    def promote_working(
        self, *, owner_id: int, min_access: int = 2, to_kind: str = "episodic"
    ) -> int:
        """Graduate ``working`` memories that proved useful (recalled at least
        ``min_access`` times) into a durable ``to_kind`` memory — the STM->LTM
        promotion. The graduated content is re-stored under the new type (so it
        gets that type's slow decay) and the transient working original is
        dropped. Returns how many were promoted."""
        promoted = 0
        for node in list(self.store.iter_nodes(owner_id)):
            if node.kind != "working" or node.access_count < min_access:
                continue
            self.remember(
                owner_id=owner_id,
                text=node.content,
                kind=to_kind,
                importance=node.importance,
                properties={**node.properties, "promoted_from": "working"},
                dedup=False,
            )
            self.store.delete_node(node.id, owner_id=owner_id)
            promoted += 1
        return promoted

    # ── reflection: the generative step (CREATES new knowledge) ─────────────
    def reflect(
        self,
        *,
        owner_id: int,
        llm: Callable[[str], str],
        min_cluster: int = 3,
        max_reflections: int = 5,
    ) -> dict[str, int]:
        """Generative-Agents reflection: cluster related memories, ask the LLM
        to synthesise a higher-level insight per cluster, and store each insight
        as a NEW ``semantic`` node linked back to the observations it came from
        (``derived_from`` edges). This is the only op that creates knowledge that
        was not written verbatim; everything else only connects/ranks/decays.

        ``llm`` is an injected ``(prompt) -> text`` callable so the engine stays
        model-agnostic (the product wires it to the running vLLM engine). Derived
        nodes are never fed back as source observations, so repeated passes do
        not runaway into reflections-of-reflections. Returns ``{reflections: N}``.
        """
        communities = self.detect_communities(owner_id=owner_id)
        by_comm: dict[int, list[int]] = {}
        for nid, comm in communities.items():
            by_comm.setdefault(comm, []).append(nid)

        created = 0
        for _comm, nids in sorted(by_comm.items()):
            if created >= max_reflections:
                break
            nodes = [self.store.get_node(nid) for nid in nids]
            # Only reflect over raw observations — skip prior insights.
            observations = [
                n for n in nodes if n and not n.properties.get("derived")
            ]
            if len(observations) < min_cluster:
                continue
            prompt = _reflection_prompt([n.content for n in observations])
            insight = (llm(prompt) or "").strip()
            if not insight:
                continue
            source_ids = [n.id for n in observations]
            new_id = self.remember(
                owner_id=owner_id,
                text=insight,
                kind="semantic",
                importance=0.5,  # a derived insight is more salient than a raw turn
                properties={"derived": True, "sources": source_ids},
                dedup=False,
            )
            for sid in source_ids:
                self.store.add_edge(new_id, sid, "derived_from", weight=1.0)
            created += 1
        return {"reflections": created}

    # ── graph view ───────────────────────────────────────────────────────
    def graph(
        self, *, owner_id: int, limit: int = 200
    ) -> tuple[list, list[tuple[int, int, str, float]]]:
        """Return (nodes, edges) for an owner's memory graph, bounded to `limit`
        nodes — the data the GUI force-graph renders. Edges are the undirected
        set among the returned nodes (deduped). Storage-agnostic.

        The bound keeps the most IMPORTANT (hub) nodes, not the first-inserted:
        for a large memory a plain head-`limit` would render an arbitrary stale
        corner. `sorted` is stable, so with importance unset (all 0.0) this
        degrades to deterministic insertion order."""
        nodes = sorted(
            self.store.iter_nodes(owner_id), key=lambda n: n.importance, reverse=True
        )[:limit]
        ids = {n.id for n in nodes}
        edges: list[tuple[int, int, str, float]] = []
        seen: set[tuple[int, int, str]] = set()
        for node in nodes:
            for neigh_id, rel, weight in self.store.neighbors(node.id):
                if neigh_id not in ids:
                    continue
                key = (min(node.id, neigh_id), max(node.id, neigh_id), rel)
                if key in seen:
                    continue
                seen.add(key)
                edges.append((key[0], key[1], rel, weight))
        return nodes, edges

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
