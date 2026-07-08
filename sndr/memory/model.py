# SPDX-License-Identifier: Apache-2.0
"""Data model + tuned constants for the memory engine.

These dataclasses mirror the `mem_node` / `mem_edge` schema in
docs/design/memory-engine-production-design.md. They are backend-agnostic:
the in-memory backend stores them directly; the Postgres backend maps them to
rows. Keeping the brain-mechanic constants here (one source of truth) means the
in-memory reference and the SQL backend stay numerically identical.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Hebbian co-access (HeLa-Mem):  w <- (1 - lambda) * w + eta * [co-accessed]
# Verified tuning from the survey literature; see design doc section 2.
HEBBIAN_ETA: float = 0.02     # learning rate per co-access
HEBBIAN_LAMBDA: float = 0.995  # retention (1 - decay) per co-access step

# ── Ebbinghaus retention:  R = exp(-age / (S * importance_boost))
# S is the base memory-strength time-constant in seconds; importance scales it.
EBBINGHAUS_S: float = 86_400.0  # 1 day base half-life scale

# ── Cognitive memory taxonomy (working / episodic / semantic / procedural).
# The brain forgets different kinds of memory at very different rates: a
# working-memory scratchpad fades in minutes, an episode over a day or two, a
# learned fact over weeks, a skill barely at all. Each type scales the base
# Ebbinghaus time-constant `S` by its factor (applied once in store._retention,
# so both backends stay identical). ANY other/legacy kind ("note",
# "conversation", …) maps to 1.0 — exactly the pre-taxonomy behaviour, so
# nothing already stored changes.
MEMORY_TYPES: tuple[str, ...] = ("working", "episodic", "semantic", "procedural")
DEFAULT_MEMORY_TYPE: str = "episodic"  # a captured experience is episodic by default

TYPE_DECAY_FACTOR: dict[str, float] = {
    "working": 0.02,      # ~30 min half-life — the current-context scratchpad
    "episodic": 1.0,      # ~1 day — an experience/event (the historical baseline)
    "semantic": 8.0,      # ~1 week — a consolidated fact/concept
    "procedural": 30.0,   # ~1 month — a learned skill / how-to (persists longest)
}


def type_decay_factor(kind: str) -> float:
    """Ebbinghaus time-constant multiplier for a memory kind. Unknown/legacy
    kinds return 1.0 (neutral — the pre-taxonomy behaviour)."""
    return TYPE_DECAY_FACTOR.get(kind, 1.0)


def normalize_memory_type(value: str | None) -> str:
    """Coerce a user-supplied type to a canonical one, defaulting to episodic.
    Never raises — a bad value degrades to the default rather than blocking a
    write."""
    if not value:
        return DEFAULT_MEMORY_TYPE
    v = str(value).strip().lower()
    return v if v in MEMORY_TYPES else DEFAULT_MEMORY_TYPE

# ── Spreading activation along the graph during expand (design section 3).
SPREAD_DAMPING: float = 0.5   # beta: score multiplier per hop
MAX_EXPAND_DEPTH: int = 3     # bounded traversal (cycle-safe)

# Semantic auto-edge threshold (kNN cosine) — used by the batch linker.
SEMANTIC_EDGE_TAU: float = 0.8

CO_ACCESS_REL: str = "co_access"


@dataclass
class MemoryNode:
    """One memory atom (note / fact / entity / summary)."""

    id: int
    owner_id: int
    kind: str
    content: str
    embedding: list[float] = field(default_factory=list)
    importance: float = 0.0       # Generative-Agents importance (LLM-rated, batch)
    strength: float = 1.0         # Ebbinghaus retention base
    access_count: int = 0
    community_id: int | None = None  # Leiden cluster ("cloud"); set by batch
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0       # epoch seconds
    accessed_at: float = 0.0      # epoch seconds (updated on retrieval)


@dataclass
class MemoryEdge:
    """A relationship between two nodes. `weight` carries the Hebbian strength."""

    src_id: int
    dst_id: int
    rel: str
    weight: float = 0.0
    properties: dict[str, Any] = field(default_factory=dict)
    valid_at: float = 0.0
    invalid_at: float | None = None  # bi-temporal: invalidated, not deleted


@dataclass
class SearchHit:
    """A node returned from a similarity / activation query, with its score."""

    node: MemoryNode
    score: float

    @property
    def id(self) -> int:
        return self.node.id
