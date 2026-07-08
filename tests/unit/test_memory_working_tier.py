# SPDX-License-Identifier: Apache-2.0
"""Working-memory tier — the capacity-bounded short-term buffer + STM→LTM promotion.

The taxonomy (working/episodic/semantic/procedural) already makes `working`
memories decay fast. This adds the other two properties a real working memory
has:
  * capacity bound — only the N most-recent working items survive; older ones
    are evicted (a scratchpad, not an ever-growing log).
  * promotion — a working item that proved useful (recalled enough times)
    graduates to a durable episodic memory.

Both are pure engine ops over the existing store primitives (iter_nodes,
delete_node, remember) — no store-contract change.
"""
from __future__ import annotations

from sndr.memory.embedder import HashEmbedder
from sndr.memory.engine import MemoryEngine
from sndr.memory.inmemory import InMemoryStore


def _engine() -> MemoryEngine:
    return MemoryEngine(store=InMemoryStore(), embedder=HashEmbedder(dim=64))


def _kinds(eng, owner):
    return [n.kind for n in eng.store.iter_nodes(owner)]


def test_prune_working_keeps_only_capacity_most_recent():
    eng = _engine()
    ids = [eng.remember(owner_id=1, text=f"w{i}", kind="working", dedup=False)
           for i in range(5)]
    evicted = eng.prune_working(owner_id=1, capacity=2)
    assert evicted == 3
    survivors = {n.id for n in eng.store.iter_nodes(1)}
    # the two most-recent (highest ids) survive
    assert survivors == set(ids[-2:])


def test_prune_working_ignores_other_kinds():
    eng = _engine()
    eng.remember(owner_id=1, text="fact", kind="semantic", dedup=False)
    eng.remember(owner_id=1, text="event", kind="episodic", dedup=False)
    for i in range(4):
        eng.remember(owner_id=1, text=f"w{i}", kind="working", dedup=False)
    eng.prune_working(owner_id=1, capacity=1)
    kinds = sorted(_kinds(eng, 1))
    # semantic + episodic untouched, exactly 1 working left
    assert kinds == ["episodic", "semantic", "working"]


def test_prune_working_noop_under_capacity():
    eng = _engine()
    eng.remember(owner_id=1, text="w0", kind="working", dedup=False)
    assert eng.prune_working(owner_id=1, capacity=5) == 0


def test_promote_working_graduates_used_items_to_episodic():
    eng = _engine()
    keep = eng.remember(owner_id=1, text="useful", kind="working", dedup=False)
    eng.remember(owner_id=1, text="unused", kind="working", dedup=False)
    # simulate the "useful" one being recalled twice
    eng.store._touch([keep], now=1.0)
    eng.store._touch([keep], now=2.0)

    promoted = eng.promote_working(owner_id=1, min_access=2)
    assert promoted == 1
    kinds = sorted(_kinds(eng, 1))
    # the used working memory is now episodic; the unused one stays working
    assert kinds == ["episodic", "working"]
    # the promoted content survives
    contents = {n.content for n in eng.store.iter_nodes(1)}
    assert "useful" in contents


def test_promote_working_below_threshold_stays():
    eng = _engine()
    nid = eng.remember(owner_id=1, text="barely", kind="working", dedup=False)
    eng.store._touch([nid], now=1.0)  # only 1 access
    assert eng.promote_working(owner_id=1, min_access=2) == 0
    assert _kinds(eng, 1) == ["working"]


def test_promote_working_ignores_non_working():
    eng = _engine()
    nid = eng.remember(owner_id=1, text="fact", kind="semantic", dedup=False)
    eng.store._touch([nid], now=1.0)
    eng.store._touch([nid], now=2.0)
    assert eng.promote_working(owner_id=1, min_access=2) == 0
