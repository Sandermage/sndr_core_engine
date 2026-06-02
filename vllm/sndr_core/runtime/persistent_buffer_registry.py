# SPDX-License-Identifier: Apache-2.0
"""Operator-visible unified buffer pool registry — v11.1.0 P3.3.

Master plan section P3.3: 4 separate buffer pool managers (P36/PN12/P46/P39a)
share a common pattern — allocate-once, reuse-forever buffers in vLLM
hot paths. This module centralizes the lookup surface so:

  - Operators can `sndr patches show buffer_registry` and see all pools
    + sizes + per-pool stats in one place.
  - Future pools migrate via a single API (~10 LOC each).
  - Each pool's allocation logic stays IDENTICAL (byte-equivalent).

NOT a refactor of the pool LOGIC. Each pool's internal torch.empty() call
is unchanged. Only the LOOKUP SURFACE is unified.

Public surface:

  PersistentBufferRegistry — singleton, `Registry().get_pool(name)`
  BufferPool — single named pool; .acquire / .release / .stats

  POOL_TQ_DECODE_SHARED         — P36 (TurboQuant shared decode buffers)
  POOL_FFN_INTERMEDIATE_SCRATCH — PN12 (FFN intermediate scratch)
  POOL_GDN_GATING               — P46 (GDN gating buffers)
  POOL_FLA_KKT_PERSISTENT_A     — P39a (FLA chunk_scaled_dot_kkt pool)

Migration pattern (per pool):

  # Before
  def _ensure_buffer(layer, shape, dtype):
      if not hasattr(layer, "_buf"):
          layer._buf = torch.empty(shape, dtype=dtype, device="cuda")
      return layer._buf

  # After (thin wrapper, byte-equivalent)
  def _ensure_buffer(layer, shape, dtype):
      from vllm.sndr_core.runtime.persistent_buffer_registry import (
          PersistentBufferRegistry, POOL_TQ_DECODE_SHARED,
      )
      pool = PersistentBufferRegistry().get_pool(POOL_TQ_DECODE_SHARED)
      return pool.acquire(shape, dtype, "cuda")

The pool's acquire() does the same torch.empty() when no buffer of the
exact shape+dtype+device is in the free list — semantics are identical
to the per-patch helper.

Thread safety: BufferPool uses an RLock around the free-list. Acquires
under contention either reuse a free buffer or allocate fresh; no
deadlock or race possible. PersistentBufferRegistry uses an RLock
around the pool index.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
v11.1.0 Phase 6 P3.3 closeout.
"""
from __future__ import annotations

import logging
from threading import RLock
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import torch

log = logging.getLogger("genesis.runtime.persistent_buffer_registry")


# Pool name constants — referenced by migrated patches + sndr CLI surfaces.
POOL_TQ_DECODE_SHARED = "tq_decode_shared"
POOL_FFN_INTERMEDIATE_SCRATCH = "ffn_intermediate_scratch"
POOL_GDN_GATING = "gdn_gating"
POOL_FLA_KKT_PERSISTENT_A = "fla_kkt_persistent_a"


class BufferPool:
    """One named buffer pool — pre-allocates on first acquire, reuses
    after release.

    Each pool keeps a free-list keyed by (shape_tuple, dtype, device).
    Acquire pops a free buffer if available; else allocates fresh via
    torch.empty() — same as the per-patch helper had.

    Release pushes back to the free-list for reuse. No copy-on-release;
    callers MUST NOT keep a reference to the returned tensor across the
    release call.

    Thread-safe via internal RLock around the free-list.
    """

    def __init__(self, name: str, max_size: int = 64):
        self.name = name
        self._free_lists: dict[tuple, list] = {}
        self._lock = RLock()
        self._stats = {
            "acquires": 0,
            "releases": 0,
            "allocations": 0,
            "reuses": 0,
        }
        self._max_size = max_size

    def acquire(self, shape, dtype: "torch.dtype", device) -> "torch.Tensor":
        """Return a tensor of the requested shape/dtype/device.

        Reuses from free-list if a buffer with the EXACT same
        (shape, dtype, device) is available; else allocates fresh
        via torch.empty().
        """
        import torch

        shape_tuple = tuple(shape)
        device_key = str(device) if not isinstance(device, str) else device
        key = (shape_tuple, dtype, device_key)
        with self._lock:
            self._stats["acquires"] += 1
            free = self._free_lists.get(key)
            if free:
                tensor = free.pop()
                self._stats["reuses"] += 1
                return tensor
            self._stats["allocations"] += 1
        # Allocate outside the lock to avoid holding it during CUDA sync
        tensor = torch.empty(shape_tuple, dtype=dtype, device=device)
        return tensor

    def release(self, tensor: "torch.Tensor") -> None:
        """Mark tensor reusable. Caller MUST drop its reference."""
        shape_tuple = tuple(tensor.shape)
        device_key = str(tensor.device)
        key = (shape_tuple, tensor.dtype, device_key)
        with self._lock:
            self._stats["releases"] += 1
            free = self._free_lists.setdefault(key, [])
            if len(free) < self._max_size:
                free.append(tensor)

    def stats(self) -> dict:
        """Return a snapshot of acquire/release/alloc/reuse counts."""
        with self._lock:
            return dict(self._stats)

    def __repr__(self) -> str:
        with self._lock:
            shapes = sorted(self._free_lists.keys(), key=lambda k: k[0])
            return f"BufferPool(name={self.name!r}, shapes={len(shapes)}, stats={self._stats})"


class PersistentBufferRegistry:
    """Singleton index of named BufferPools.

    Pools are created lazily on first get_pool(name) call. The index
    is process-global — every patch in the process shares the same
    pool for the same name.
    """

    _instance: Optional["PersistentBufferRegistry"] = None
    _instance_lock = RLock()

    def __new__(cls) -> "PersistentBufferRegistry":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._pools = {}
                    instance._pool_lock = RLock()
                    cls._instance = instance
        return cls._instance

    def get_pool(self, name: str, max_size: int = 64) -> BufferPool:
        """Return the named pool, creating it on first call."""
        with self._pool_lock:
            if name not in self._pools:
                self._pools[name] = BufferPool(name, max_size=max_size)
                log.debug("[buffer_registry] created pool %r", name)
            return self._pools[name]

    def all_pools(self) -> dict[str, BufferPool]:
        """Snapshot of all registered pools."""
        with self._pool_lock:
            return dict(self._pools)

    def summary(self) -> dict:
        """Operator-facing summary — used by `sndr patches show buffer_registry`."""
        with self._pool_lock:
            return {
                "pool_count": len(self._pools),
                "pools": {
                    name: {
                        "stats": p.stats(),
                        "shape_count": len(p._free_lists),
                    }
                    for name, p in self._pools.items()
                },
            }


__all__ = [
    "BufferPool",
    "PersistentBufferRegistry",
    "POOL_TQ_DECODE_SHARED",
    "POOL_FFN_INTERMEDIATE_SCRATCH",
    "POOL_GDN_GATING",
    "POOL_FLA_KKT_PERSISTENT_A",
]
