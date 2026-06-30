# SPDX-License-Identifier: Apache-2.0
"""Embedder layer — the pluggable text -> vector seam.

The store works with vectors; the engine works with text. `Embedder` is the
boundary, so the chat model and the embedding model stay independent (the
design's "embedder != chat model" rule) and the CPU embedder can be swapped
(static Model2Vec, ONNX bge, a remote /v1/embeddings service) without touching
the store or the brain mechanics.

`HashEmbedder` is the dependency-free default: deterministic feature hashing
(stable BLAKE2b, NOT Python's per-process salted hash), L2-normalized. It is the
unit-test double and a real low-quality CPU fallback — texts sharing tokens land
closer in cosine space, which is enough to exercise semantic linking end to end.
A production-quality CPU embedder implements this same interface.
"""
from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


class Embedder(ABC):
    """Maps text to a fixed-dimension embedding vector."""

    @property
    @abstractmethod
    def dim(self) -> int:
        """Embedding dimension (the store's vector column width)."""

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts (one vector per input, in order)."""

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


class HashEmbedder(Embedder):
    """Deterministic feature-hashing embedder (dependency-free)."""

    def __init__(self, dim: int = 256) -> None:
        if dim <= 0:
            raise ValueError("dim must be positive")
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def _bucket(self, token: str) -> tuple[int, float]:
        # 8 stable bytes -> (index in [0,dim), sign in {-1,+1}).
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        h = int.from_bytes(digest, "big")
        index = h % self._dim
        sign = 1.0 if (h >> 63) & 1 else -1.0
        return index, sign

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        for token in _TOKEN_RE.findall(text.lower()):
            index, sign = self._bucket(token)
            vec[index] += sign
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0.0:
            return vec  # empty / token-less text -> zero vector
        return [x / norm for x in vec]


class Model2VecEmbedder(Embedder):
    """Real CPU embedder — Model2Vec static distillation (no GPU, ~30 MB).

    Default minishlab/potion-base-8M (256-dim). `model2vec` is an optional
    dependency ([memory-embed] extra), lazy-imported so this module stays
    importable without it. Output is L2-normalized for cosine consistency with
    the rest of the engine.
    """

    def __init__(self, model: str = "minishlab/potion-base-8M") -> None:
        from model2vec import StaticModel  # lazy: optional dependency

        self._model = StaticModel.from_pretrained(model)
        # Probe one vector to learn the dimension (robust across model versions).
        self._dim = len(self._model.encode(["x"])[0])

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for row in self._model.encode(list(texts)):
            vec = [float(x) for x in row]
            norm = math.sqrt(sum(x * x for x in vec))
            out.append([x / norm for x in vec] if norm else vec)
        return out
