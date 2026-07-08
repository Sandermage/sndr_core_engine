# SPDX-License-Identifier: Apache-2.0
"""Reflection — the generative half of the brain.

Every other mechanic (Hebbian, decay, spreading activation, communities) only
connects, strengthens, or ranks memories that already exist. Reflection is the
one step that CREATES new knowledge: it clusters related memories and asks an
LLM to synthesise a higher-level insight, then stores that insight as a new
`semantic` node linked back to the observations it was derived from — the
Generative-Agents reflection tree.

The LLM is an injected callable `(prompt: str) -> str`, so the whole thing is
unit-tested deterministically with a fake — no engine, no network.
"""
from __future__ import annotations

from sndr.memory.embedder import HashEmbedder
from sndr.memory.engine import MemoryEngine
from sndr.memory.inmemory import InMemoryStore


def _engine() -> MemoryEngine:
    return MemoryEngine(store=InMemoryStore(), embedder=HashEmbedder(dim=64))


def _cluster(eng: MemoryEngine, owner: int, texts: list[str]) -> list[int]:
    """A connected cluster (so community detection groups them together)."""
    ids = [eng.remember(owner_id=owner, text=t, kind="episodic", dedup=False) for t in texts]
    for a in ids:
        for b in ids:
            if a < b:
                eng.store.add_edge(a, b, "similar_to", weight=1.0)
    return ids


def test_reflection_creates_a_new_derived_node():
    eng = _engine()
    before = _cluster(eng, 1, ["met Klaus at the library",
                               "Klaus skipped lunch again",
                               "Klaus stayed late reading"])
    rep = eng.reflect(owner_id=1, llm=lambda _p: "Klaus has been unusually withdrawn.",
                      min_cluster=3)
    assert rep["reflections"] == 1
    nodes = list(eng.store.iter_nodes(1))
    # A brand-new node exists beyond the originals.
    assert len(nodes) == len(before) + 1
    insight = next(n for n in nodes if n.id not in before)
    assert "withdrawn" in insight.content


def test_reflection_node_is_semantic_and_marked_derived():
    eng = _engine()
    src = _cluster(eng, 1, ["a", "b", "c"])
    eng.reflect(owner_id=1, llm=lambda _p: "an insight", min_cluster=3)
    insight = next(n for n in eng.store.iter_nodes(1) if n.id not in src)
    assert insight.kind == "semantic"
    assert insight.properties.get("derived") is True
    assert set(insight.properties.get("sources", [])) == set(src)


def test_reflection_links_insight_to_its_sources():
    eng = _engine()
    src = _cluster(eng, 1, ["a", "b", "c"])
    eng.reflect(owner_id=1, llm=lambda _p: "an insight", min_cluster=3)
    insight = next(n for n in eng.store.iter_nodes(1) if n.id not in src)
    neigh = {nid for nid, rel, _w in eng.store.neighbors(insight.id) if rel == "derived_from"}
    assert neigh == set(src)


def test_small_clusters_are_skipped():
    eng = _engine()
    _cluster(eng, 1, ["only", "two"])  # below min_cluster=3
    rep = eng.reflect(owner_id=1, llm=lambda _p: "insight", min_cluster=3)
    assert rep["reflections"] == 0


def test_empty_llm_output_creates_nothing():
    eng = _engine()
    src = _cluster(eng, 1, ["a", "b", "c"])
    rep = eng.reflect(owner_id=1, llm=lambda _p: "   ", min_cluster=3)
    assert rep["reflections"] == 0
    assert len(list(eng.store.iter_nodes(1))) == len(src)


def test_max_reflections_caps_output():
    eng = _engine()
    _cluster(eng, 1, ["a1", "a2", "a3"])
    _cluster(eng, 1, ["b1", "b2", "b3"])
    _cluster(eng, 1, ["c1", "c2", "c3"])
    rep = eng.reflect(owner_id=1, llm=lambda _p: "insight", min_cluster=3, max_reflections=2)
    assert rep["reflections"] == 2


def test_reflection_does_not_reflect_on_derived_nodes():
    """A second reflection pass must not treat prior insights as raw observations
    (no runaway reflection-of-reflections)."""
    eng = _engine()
    _cluster(eng, 1, ["a", "b", "c"])
    eng.reflect(owner_id=1, llm=lambda _p: "insight-1", min_cluster=3)
    calls = []

    def spy_llm(prompt):
        calls.append(prompt)
        return "insight-2"

    eng.reflect(owner_id=1, llm=spy_llm, min_cluster=3)
    # The derived node must not have been fed back in as a source observation.
    assert "insight-1" not in "".join(calls)


def test_prompt_receives_the_cluster_contents():
    eng = _engine()
    _cluster(eng, 1, ["alpha fact", "beta fact", "gamma fact"])
    seen = {}
    eng.reflect(owner_id=1, llm=lambda p: seen.setdefault("p", p) or "x", min_cluster=3)
    assert "alpha fact" in seen["p"]
    assert "beta fact" in seen["p"]
