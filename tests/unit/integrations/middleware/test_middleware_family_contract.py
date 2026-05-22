# SPDX-License-Identifier: Apache-2.0
"""middleware family contract — Theme 4 expansion (2026-05-11).

3 patches: PN16 (lazy-reasoner request hook), PN16_V6 (streaming
truncator companion), PN65 (access log).
"""
from tests.unit.integrations._family_contract_helpers import (
    make_family_contract_class,
    make_family_registry_class,
)

PATCHES = [
    ("vllm.sndr_core.integrations.middleware.pn16_lazy_reasoner", "PN16"),
    ("vllm.sndr_core.integrations.middleware.pn16_v6_streaming_truncator", "PN16_V6"),
    ("vllm.sndr_core.integrations.middleware.pn65_access_log", "PN65"),
]


class TestMiddlewarePatchContract(
    make_family_contract_class("middleware", PATCHES)
):
    pass


class TestMiddlewareFamilyRegistry(
    make_family_registry_class("middleware", PATCHES)
):
    pass
