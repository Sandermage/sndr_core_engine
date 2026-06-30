# SPDX-License-Identifier: Apache-2.0
"""TDD contract for the real CPU embedder (Model2Vec, static, ~30MB).

Skipped unless `model2vec` is installed (it is an optional [memory-embed] extra;
the engine core + HashEmbedder stay dependency-free). Where present, it loads
minishlab/potion-base-8M (256-dim) and must satisfy the same Embedder contract,
with genuinely semantic similarity (the quality upgrade over feature hashing).
"""
from __future__ import annotations

import math

import pytest

pytest.importorskip("model2vec")

from sndr.memory.embedder import Embedder, Model2VecEmbedder  # noqa: E402


def _cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


@pytest.fixture(scope="module")
def emb() -> Model2VecEmbedder:
    return Model2VecEmbedder()  # potion-base-8M, cached after first load


def test_is_an_embedder(emb: Model2VecEmbedder):
    assert isinstance(emb, Embedder)


def test_dim_256(emb: Model2VecEmbedder):
    assert emb.dim == 256
    assert len(emb.embed_one("hello world")) == 256


def test_deterministic(emb: Model2VecEmbedder):
    assert emb.embed_one("the cat sat") == emb.embed_one("the cat sat")


def test_unit_normalized(emb: Model2VecEmbedder):
    v = emb.embed_one("some non empty text")
    assert math.sqrt(sum(x * x for x in v)) == pytest.approx(1.0, abs=1e-5)


def test_semantic_similarity_beats_unrelated(emb: Model2VecEmbedder):
    base = emb.embed_one("postgres vector memory graph")
    near = emb.embed_one("a database for storing embeddings and similarity search")
    far = emb.embed_one("a recipe for banana bread with cinnamon")
    assert _cos(base, near) > _cos(base, far)


def test_batch_matches_embed_one(emb: Model2VecEmbedder):
    batch = emb.embed(["alpha beta", "gamma delta"])
    assert len(batch) == 2
    assert batch[0] == pytest.approx(emb.embed_one("alpha beta"), abs=1e-6)
