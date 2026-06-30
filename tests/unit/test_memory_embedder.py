# SPDX-License-Identifier: Apache-2.0
"""TDD contract for the embedder layer (Phase 1, verifiable without a DB).

`Embedder` is the pluggable text->vector seam. `HashEmbedder` is a
deterministic, dependency-free feature-hashing embedder: it is both the
unit-test double AND a genuine (if low-quality) CPU fallback — same text maps
to the same vector, and texts sharing tokens land closer in cosine space. The
production CPU embedder (Model2Vec / fastembed) plugs into the same interface
and is validated on a host where that dependency is installed.

Design: docs/design/memory-engine-production-design.md (embedder != chat model;
one embedder per store).
"""
from __future__ import annotations

import math

import pytest

from sndr.memory.embedder import Embedder, HashEmbedder


def _norm(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def _cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


class TestHashEmbedder:
    def test_is_an_embedder(self):
        assert isinstance(HashEmbedder(dim=64), Embedder)

    def test_dim_and_vector_length(self):
        emb = HashEmbedder(dim=128)
        assert emb.dim == 128
        assert len(emb.embed_one("hello world")) == 128

    def test_deterministic_across_calls(self):
        emb = HashEmbedder(dim=64)
        assert emb.embed_one("the cat sat") == emb.embed_one("the cat sat")

    def test_deterministic_across_instances(self):
        # stable hash (not Python's salted hash) -> reproducible across processes
        assert HashEmbedder(dim=64).embed_one("x y z") == \
               HashEmbedder(dim=64).embed_one("x y z")

    def test_unit_normalized(self):
        v = HashEmbedder(dim=128).embed_one("some non empty text here")
        assert _norm(v) == pytest.approx(1.0, abs=1e-9)

    def test_empty_text_is_zero_vector(self):
        v = HashEmbedder(dim=32).embed_one("   ")
        assert _norm(v) == pytest.approx(0.0)

    def test_shared_tokens_are_more_similar_than_disjoint(self):
        emb = HashEmbedder(dim=512)
        base = emb.embed_one("postgres vector memory graph")
        near = emb.embed_one("postgres vector memory engine")   # 3 shared tokens
        far = emb.embed_one("banana orange weather guitar")      # 0 shared tokens
        assert _cos(base, near) > _cos(base, far)

    def test_batch_embed_matches_embed_one(self):
        emb = HashEmbedder(dim=64)
        texts = ["alpha beta", "gamma", "delta epsilon zeta"]
        batch = emb.embed(texts)
        assert len(batch) == 3
        assert batch[0] == emb.embed_one("alpha beta")
        assert batch[2] == emb.embed_one("delta epsilon zeta")
