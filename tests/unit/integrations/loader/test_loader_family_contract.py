# SPDX-License-Identifier: Apache-2.0
"""loader family contract — Theme 4 expansion (2026-05-11)."""
from tests.unit.integrations._family_contract_helpers import (
    make_family_contract_class,
    make_family_registry_class,
)

PATCHES = [
    ("sndr.engines.vllm.patches.loader.pn8_mtp_draft_online_quant_propagation", "PN8"),
    ("sndr.engines.vllm.patches.loader.pn61_qwen3_vl_keyerror_guard", "PN61"),
]


class TestLoaderPatchContract(make_family_contract_class("loader", PATCHES)):
    pass


class TestLoaderFamilyRegistry(make_family_registry_class("loader", PATCHES)):
    pass
