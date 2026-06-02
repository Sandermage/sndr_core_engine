# SPDX-License-Identifier: Apache-2.0
"""Byte-equivalent verification for P46 buffer registry migration.

P46 is a TEXT WIRING patch — it edits vLLM's gdn_linear_attn.py to
delegate g + beta_output allocation to GdnGatingBufferManager. The
actual torch.empty() call lives in that manager (process-wide pool,
allocate-once-keep-forever, pointer-stable for CUDA-graph capture).

The v11.1.0 P3.3 migration adds PersistentBufferRegistry as the
operator-visible lookup surface — the underlying
GdnGatingBufferManager behavior is UNCHANGED.
"""
from __future__ import annotations

import pytest

try:
    import torch
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False


@pytest.mark.skipif(not HAS_TORCH, reason="torch unavailable")
def test_p46_registry_pool_visible_after_module_import():
    """After p46 module import + ensure_pool_registered(), POOL_GDN_GATING
    is visible in PersistentBufferRegistry."""
    from vllm.sndr_core.runtime.persistent_buffer_registry import (
        PersistentBufferRegistry,
        POOL_GDN_GATING,
    )
    import vllm.sndr_core.integrations.attention.gdn.p46_gdn_gating_buffers as p46

    p46.ensure_pool_registered()

    pools = PersistentBufferRegistry().all_pools()
    assert POOL_GDN_GATING in pools, (
        f"P46 pool not registered; pools={list(pools)}"
    )


def test_p46_module_uses_registry_after_migration():
    """Source imports PersistentBufferRegistry + POOL_GDN_GATING constant."""
    import vllm.sndr_core.integrations.attention.gdn.p46_gdn_gating_buffers as p46
    source = open(p46.__file__).read()
    assert "PersistentBufferRegistry" in source
    assert "POOL_GDN_GATING" in source
