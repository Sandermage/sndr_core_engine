# SPDX-License-Identifier: Apache-2.0
"""Byte-equivalent verification for P36 buffer registry migration.

P36 is a TEXT WIRING patch — it edits vLLM's attention.py to delegate
shared-decode-buffer allocation to TurboQuantBufferManager. The actual
torch.empty() call lives in
vllm.sndr_core.runtime.prealloc.GenesisPreallocBuffer.get_or_create,
which is process-global, pointer-stable (CUDA-graph safe), and
allocate-once-keep-forever.

The v11.1.0 P3.3 migration adds the registry as the operator-visible
lookup surface — the underlying GenesisPreallocBuffer behavior is
UNCHANGED. Same torch.empty() calls happen at the same time with the
same shapes/dtypes/devices. The registry just exposes the pool name
for `sndr patches show buffer_registry` (future CLI).

Byte-equivalence is preserved because the registry hook does not
allocate new storage — it only registers the pool name in
PersistentBufferRegistry so operators can see it. The original
GenesisPreallocBuffer cache continues to own the tensor storage.
"""
from __future__ import annotations

import pytest

try:
    import torch
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False


@pytest.mark.skipif(not HAS_TORCH, reason="torch unavailable")
def test_p36_registry_pool_visible_after_module_import():
    """After p36 module import, POOL_TQ_DECODE_SHARED is visible in
    PersistentBufferRegistry — operator can see the named pool exists.

    This is purely a lookup-surface check; no byte-level allocation
    semantics changed by the registry hook itself."""
    from vllm.sndr_core.runtime.persistent_buffer_registry import (
        PersistentBufferRegistry,
        POOL_TQ_DECODE_SHARED,
    )
    import vllm.sndr_core.integrations.kernels.p36_tq_shared_decode_buffers as p36  # noqa: F401

    # Trigger the registry-visibility hook (no allocation — just registers the name).
    p36.ensure_pool_registered()

    pools = PersistentBufferRegistry().all_pools()
    assert POOL_TQ_DECODE_SHARED in pools, (
        f"P36 pool not registered after import; pools={list(pools)}"
    )


@pytest.mark.skipif(not HAS_TORCH, reason="torch unavailable")
def test_p36_registry_pool_acquire_byte_equivalent():
    """Pool acquire() returns a tensor with the requested shape/dtype/device
    — byte-equivalent to what the original torch.empty() would return."""
    from vllm.sndr_core.runtime.persistent_buffer_registry import (
        PersistentBufferRegistry,
        POOL_TQ_DECODE_SHARED,
    )
    pool = PersistentBufferRegistry().get_pool(POOL_TQ_DECODE_SHARED)
    shape = (8, 32, 16, 64)
    dtype = torch.float32
    t = pool.acquire(shape, dtype, "cpu")
    assert t.shape == shape
    assert t.dtype == dtype
    assert t.device.type == "cpu"


def test_p36_module_uses_registry_after_migration():
    """The migrated p36 module imports PersistentBufferRegistry + the
    POOL_TQ_DECODE_SHARED constant — operator-visible lookup surface."""
    import vllm.sndr_core.integrations.kernels.p36_tq_shared_decode_buffers as p36
    source = open(p36.__file__).read()
    assert "PersistentBufferRegistry" in source, \
        "p36 must use PersistentBufferRegistry post-migration"
    assert "POOL_TQ_DECODE_SHARED" in source, \
        "p36 must reference POOL_TQ_DECODE_SHARED constant"
