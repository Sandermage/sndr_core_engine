# SPDX-License-Identifier: Apache-2.0
"""H2 regression: PN106 named pools must not pin their peak size forever.

A single huge prefill grows gdn_h to multi-GiB; with the old code that buffer
stayed resident for the life of the process (and could exceed what vLLM's
memory profiler saw → OOM headroom risk). The ceiling routes over-cap requests
to a transient tensor so the PERSISTENT pool stays bounded. Default
(GENESIS_PN106_POOL_MAX_BYTES unset/0) keeps the prior unlimited behavior.
"""
from __future__ import annotations

import pytest

try:
    import torch
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False


@pytest.mark.skipif(not HAS_TORCH, reason="torch unavailable")
def test_pn106_ceiling_caps_persistent_pool(monkeypatch):
    from sndr.cache import _pn95_runtime as _rt
    from sndr.cache.pn95.shared_buffers import pn106_get_pooled_buf

    _rt._PN106_NAMED_POOLS.clear()
    monkeypatch.setenv("GENESIS_PN106_POOL_MAX_BYTES", str(64 * 1024))  # 64 KiB cap
    key = ("gdn_h", "cpu", str(torch.float32))

    small = pn106_get_pooled_buf("gdn_h", (4, 8), torch.float32, "cpu")
    assert small is not None and tuple(small.shape) == (4, 8)
    assert key in _rt._PN106_NAMED_POOLS  # small request pooled normally

    big = pn106_get_pooled_buf("gdn_h", (100000,), torch.float32, "cpu")  # 400 KB > cap
    assert big is not None and tuple(big.shape) == (100000,), "must still return a usable tensor"
    pool = _rt._PN106_NAMED_POOLS[key]
    assert pool.numel() * pool.element_size() <= 64 * 1024, (
        "over-ceiling request must not grow the persistent pool"
    )
    _rt._PN106_NAMED_POOLS.clear()


@pytest.mark.skipif(not HAS_TORCH, reason="torch unavailable")
def test_pn106_default_unlimited_preserves_pooling(monkeypatch):
    """With no ceiling env (default), a large request DOES grow the persistent
    pool (unchanged behavior — no regression)."""
    from sndr.cache import _pn95_runtime as _rt
    from sndr.cache.pn95.shared_buffers import pn106_get_pooled_buf

    _rt._PN106_NAMED_POOLS.clear()
    monkeypatch.delenv("GENESIS_PN106_POOL_MAX_BYTES", raising=False)
    key = ("gdn_o", "cpu", str(torch.float32))
    t = pn106_get_pooled_buf("gdn_o", (100000,), torch.float32, "cpu")
    assert t is not None
    assert key in _rt._PN106_NAMED_POOLS
    assert _rt._PN106_NAMED_POOLS[key].numel() >= 100000  # grew to hold it
    _rt._PN106_NAMED_POOLS.clear()
