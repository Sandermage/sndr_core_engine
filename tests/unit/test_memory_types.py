# SPDX-License-Identifier: Apache-2.0
"""Typed memory taxonomy — the cognitive working / episodic / semantic /
procedural distinction, and its effect on the Ebbinghaus decay time-constant.

The brain does not forget all memories at the same rate: a working-memory
scratchpad fades in minutes, an episode over days, a learned fact over weeks, a
skill barely at all. Before this, every node decayed on the same 1-day base
constant regardless of what kind of memory it was. This gives each memory TYPE
its own decay multiplier, applied at the single shared `_retention` seam so both
backends stay numerically identical.

Regression safety: any *unknown* kind (the historical "note"/"conversation"
values, and the contract-test default "note") maps to factor 1.0 — i.e. exactly
the previous behaviour — so nothing already stored changes.
"""
from __future__ import annotations

import math

from sndr.memory import model


def test_canonical_memory_types_defined():
    assert model.MEMORY_TYPES == ("working", "episodic", "semantic", "procedural")


def test_type_decay_factor_ordering():
    """working forgets fastest, procedural slowest — a strict ladder."""
    f = model.type_decay_factor
    assert f("working") < f("episodic") < f("semantic") < f("procedural")


def test_working_memory_is_short_lived():
    """Working memory's factor is well under a day (fast-expiring scratchpad)."""
    assert model.type_decay_factor("working") < 0.1


def test_unknown_kind_is_neutral_factor_one():
    """No regression: legacy/unknown kinds decay exactly as before (factor 1.0)."""
    assert model.type_decay_factor("note") == 1.0
    assert model.type_decay_factor("conversation") == 1.0
    assert model.type_decay_factor("") == 1.0
    assert model.type_decay_factor("something-new") == 1.0


def test_normalize_type_accepts_canonical_and_defaults():
    assert model.normalize_memory_type("semantic") == "semantic"
    assert model.normalize_memory_type("SEMANTIC") == "semantic"
    # An unrecognized value falls back to the episodic default, never crashes.
    assert model.normalize_memory_type("nonsense") == "episodic"
    assert model.normalize_memory_type(None) == "episodic"


# ── decay behaviour through the real store seam ───────────────────────────────


def _node(kind: str) -> model.MemoryNode:
    return model.MemoryNode(
        id=1, owner_id=1, kind=kind, content="x",
        strength=1.0, importance=0.0, accessed_at=0.0,
    )


def _retention(store, node, now):
    return store._retention(node, now)


def test_working_decays_faster_than_semantic_at_same_age():
    from sndr.memory.inmemory import InMemoryStore

    store = InMemoryStore()
    age = model.EBBINGHAUS_S  # one base time-constant of elapsed time
    r_working = _retention(store, _node("working"), age)
    r_semantic = _retention(store, _node("semantic"), age)
    assert r_working < r_semantic


def test_note_retention_unchanged_vs_manual_formula():
    """The historical 'note' path must still equal the bare Ebbinghaus formula."""
    from sndr.memory.inmemory import InMemoryStore

    store = InMemoryStore()
    age = 3600.0
    expected = math.exp(-age / (model.EBBINGHAUS_S * 1.0 * 1.0))  # strength=1, imp=0
    assert abs(_retention(store, _node("note"), age) - expected) < 1e-9


def test_remember_accepts_and_stores_memory_type():
    from sndr.memory.embedder import HashEmbedder
    from sndr.memory.engine import MemoryEngine
    from sndr.memory.inmemory import InMemoryStore

    eng = MemoryEngine(store=InMemoryStore(), embedder=HashEmbedder(dim=64))
    nid = eng.remember(owner_id=1, text="Paris is the capital of France",
                       kind="semantic")
    node = eng.store.get_node(nid)
    assert node.kind == "semantic"
