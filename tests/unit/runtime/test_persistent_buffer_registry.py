# SPDX-License-Identifier: Apache-2.0
"""Unit tests for PersistentBufferRegistry + BufferPool — v11.1.0 P3.3."""
from __future__ import annotations

import threading

import pytest

try:
    import torch
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False


def test_persistent_buffer_registry_is_singleton():
    """Registry() is Registry() — same identity across calls."""
    from vllm.sndr_core.runtime.persistent_buffer_registry import (
        PersistentBufferRegistry,
    )
    r1 = PersistentBufferRegistry()
    r2 = PersistentBufferRegistry()
    assert r1 is r2


def test_get_pool_returns_same_instance_for_same_name():
    """Repeated get_pool('x') returns the same BufferPool."""
    from vllm.sndr_core.runtime.persistent_buffer_registry import (
        PersistentBufferRegistry,
    )
    r = PersistentBufferRegistry()
    p1 = r.get_pool("test_pool_same_instance")
    p2 = r.get_pool("test_pool_same_instance")
    assert p1 is p2


def test_get_pool_creates_distinct_pools_for_distinct_names():
    """Different names = different BufferPool instances."""
    from vllm.sndr_core.runtime.persistent_buffer_registry import (
        PersistentBufferRegistry,
    )
    r = PersistentBufferRegistry()
    p1 = r.get_pool("test_pool_a")
    p2 = r.get_pool("test_pool_b")
    assert p1 is not p2
    assert p1.name == "test_pool_a"
    assert p2.name == "test_pool_b"


def test_all_pools_lists_registered():
    """all_pools() returns dict[name -> BufferPool]."""
    from vllm.sndr_core.runtime.persistent_buffer_registry import (
        PersistentBufferRegistry,
    )
    r = PersistentBufferRegistry()
    r.get_pool("pool_listing_test_1")
    r.get_pool("pool_listing_test_2")
    pools = r.all_pools()
    assert "pool_listing_test_1" in pools
    assert "pool_listing_test_2" in pools


@pytest.mark.skipif(not HAS_TORCH, reason="torch unavailable")
def test_buffer_pool_acquire_returns_tensor_with_requested_shape():
    """acquire((4, 8), torch.float32, 'cpu') returns a float32 tensor of shape (4, 8) on cpu."""
    from vllm.sndr_core.runtime.persistent_buffer_registry import (
        PersistentBufferRegistry,
    )
    pool = PersistentBufferRegistry().get_pool("test_acquire_shape")
    t = pool.acquire((4, 8), torch.float32, "cpu")
    assert t.shape == (4, 8)
    assert t.dtype == torch.float32
    assert t.device.type == "cpu"


@pytest.mark.skipif(not HAS_TORCH, reason="torch unavailable")
def test_buffer_pool_reuses_after_release():
    """After release, next acquire with same shape/dtype/device returns the SAME storage."""
    from vllm.sndr_core.runtime.persistent_buffer_registry import (
        PersistentBufferRegistry,
    )
    pool = PersistentBufferRegistry().get_pool("test_reuse")
    t1 = pool.acquire((4, 8), torch.float32, "cpu")
    t1_id = id(t1)
    pool.release(t1)
    t2 = pool.acquire((4, 8), torch.float32, "cpu")
    # Same storage (reused) — data_ptr identical
    assert t2.data_ptr() == t1.data_ptr()


def test_buffer_pool_stats_increment_correctly():
    """stats() reflects acquires + releases."""
    from vllm.sndr_core.runtime.persistent_buffer_registry import (
        PersistentBufferRegistry,
    )
    pool = PersistentBufferRegistry().get_pool("test_stats")
    initial = pool.stats()
    if HAS_TORCH:
        t = pool.acquire((2,), torch.float32, "cpu")
        pool.release(t)
        after = pool.stats()
        assert after["acquires"] == initial["acquires"] + 1
        assert after["releases"] == initial["releases"] + 1


def test_buffer_pool_thread_safe_acquire():
    """Concurrent acquires don't crash; each returns valid tensor."""
    if not HAS_TORCH:
        pytest.skip("torch unavailable")
    from vllm.sndr_core.runtime.persistent_buffer_registry import (
        PersistentBufferRegistry,
    )
    pool = PersistentBufferRegistry().get_pool("test_thread_safety")
    results = []
    errors = []

    def worker():
        try:
            t = pool.acquire((4,), torch.float32, "cpu")
            results.append(t)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent acquire raised: {errors}"
    assert len(results) == 8
    for t in results:
        assert t.shape == (4,)
        assert t.dtype == torch.float32
