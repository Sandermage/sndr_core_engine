# SPDX-License-Identifier: Apache-2.0
"""pool_budget cross-pool accounting primitive (incl. set_pool_size)."""
from __future__ import annotations

from sndr.runtime import pool_budget as pb


def test_set_pool_size_uses_latest_not_sum():
    """set_pool_size SETS the tally (grow-in-place semantics) so repeated grows
    reflect the LATEST footprint, not the sum of every grow."""
    pb._reset_caches()
    pb.set_pool_size("PN59", 100 * 1024 * 1024)
    assert pb.usage_bytes("PN59") == 100 * 1024 * 1024
    pb.set_pool_size("PN59", 250 * 1024 * 1024)  # grew in place
    assert pb.usage_bytes("PN59") == 250 * 1024 * 1024, "latest, not 350"
    assert pb.usage_bytes() == 250 * 1024 * 1024
    pb._reset_caches()


def test_set_pool_size_feeds_total_budget_assertion(monkeypatch):
    """A pool wired via set_pool_size is visible to assert_total_under_budget."""
    pb._reset_caches()
    monkeypatch.setenv("GENESIS_POOL_TOTAL_MAX_MIB", "200")
    pb._reset_caches()  # re-read env
    pb.set_pool_size("PN59", 150 * 1024 * 1024)
    pb.assert_total_under_budget()  # 150 <= 200, ok
    pb.set_pool_size("P37", 100 * 1024 * 1024)  # total 250 > 200
    import pytest
    with pytest.raises(pb.PoolBudgetExceeded):
        pb.assert_total_under_budget()
    pb._reset_caches()
