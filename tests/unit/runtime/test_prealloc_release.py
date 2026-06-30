# SPDX-License-Identifier: Apache-2.0
"""GenesisPreallocBuffer.release() must actually free the namespace.

Regression guard for the keying-mismatch leak: the registry is keyed by the
4-tuple (namespace, shape, dtype, device), but release() popped by the bare
namespace string, so it silently removed nothing — every grown pool (e.g.
FlaKktBufferManager on each grow) leaked its prior tensor into _REGISTRY for
the life of the process.
"""
from __future__ import annotations

import pytest

try:
    import torch
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False


@pytest.mark.skipif(not HAS_TORCH, reason="torch unavailable")
def test_release_removes_the_namespace_entry():
    from sndr.runtime.prealloc import GenesisPreallocBuffer as GPB

    GPB.clear_for_tests()
    GPB.get_or_create("leaky_ns", (4, 8), torch.float32, "cpu")
    assert GPB.get_registry_info()["total_buffers"] == 1
    assert GPB.release("leaky_ns") is True, "release must report it removed the entry"
    assert GPB.get_registry_info()["total_buffers"] == 0, "release must drop the buffer"
    GPB.clear_for_tests()


@pytest.mark.skipif(not HAS_TORCH, reason="torch unavailable")
def test_release_frees_all_shapes_of_a_grown_pool():
    from sndr.runtime.prealloc import GenesisPreallocBuffer as GPB

    GPB.clear_for_tests()
    GPB.get_or_create("grow_ns", (4, 8), torch.float32, "cpu")
    GPB.get_or_create("grow_ns", (8, 16), torch.float32, "cpu")  # grown → 2 keys
    assert GPB.get_registry_info()["total_buffers"] == 2
    assert GPB.release("grow_ns") is True
    assert GPB.get_registry_info()["total_buffers"] == 0, "grown pool's old tensor must not leak"
    GPB.clear_for_tests()


@pytest.mark.skipif(not HAS_TORCH, reason="torch unavailable")
def test_release_missing_namespace_returns_false():
    from sndr.runtime.prealloc import GenesisPreallocBuffer as GPB

    GPB.clear_for_tests()
    assert GPB.release("never_created") is False
