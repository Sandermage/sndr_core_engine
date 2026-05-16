# SPDX-License-Identifier: Apache-2.0
"""kv_cache family contract — Theme 4 expansion (2026-05-11).

5 patches; previously 1/5 had a dedicated test (PN95). Family contract
closes the gap to 5/5 via shared helpers. Uses
`_family_contract_helpers.make_family_contract_class` factory.
"""
from tests.unit.integrations._family_contract_helpers import (
    make_family_contract_class,
    make_family_registry_class,
)

PATCHES = [
    ("vllm.sndr_core.integrations.kv_cache.p5_page_size", "P5"),
    ("vllm.sndr_core.integrations.kv_cache.p14_block_table", "P14"),
    ("vllm.sndr_core.integrations.kv_cache.p83_mtp_keep_last_cached_block", "P83"),
    ("vllm.sndr_core.integrations.kv_cache.p85_hybrid_fine_shadow_prefix_cache", "P85"),
    ("vllm.sndr_core.integrations.kv_cache.pn95_tier_aware_cache", "PN95"),
]


class TestKvCachePatchContract(
    make_family_contract_class("kv_cache", PATCHES)
):
    pass


class TestKvCacheFamilyRegistry(
    make_family_registry_class("kv_cache", PATCHES)
):
    pass
