# SPDX-License-Identifier: Apache-2.0
"""lora family contract — Theme 4 expansion (2026-05-11)."""
from tests.unit.integrations._family_contract_helpers import (
    make_family_contract_class,
    make_family_registry_class,
)

PATCHES = [
    ("vllm.sndr_core.integrations._retired.pn80_lora_tensorizer_device", "PN80"),
]


class TestLoraPatchContract(make_family_contract_class("lora", PATCHES)):
    pass


class TestLoraFamilyRegistry(make_family_registry_class("lora", PATCHES)):
    pass
