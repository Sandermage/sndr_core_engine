# SPDX-License-Identifier: Apache-2.0
"""multimodal family contract — Theme 4 expansion (2026-05-11)."""
from tests.unit.integrations._family_contract_helpers import (
    make_family_contract_class,
    make_family_registry_class,
)

PATCHES = [
    ("sndr.engines.vllm.patches.multimodal.pn62_text_only_vit_skip", "PN62"),
]


class TestMultimodalPatchContract(
    make_family_contract_class("multimodal", PATCHES)
):
    pass


class TestMultimodalFamilyRegistry(
    make_family_registry_class("multimodal", PATCHES)
):
    pass
