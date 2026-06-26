# SPDX-License-Identifier: Apache-2.0
"""attention.flash family contract — Theme 4 expansion (2026-05-11).

2 patches: PN17 (FA2 softmax_lse clamp, PROD-active perf win per
empirical bench) + P100 (FlashInfer full CG for spec-decode).
"""
from tests.unit.integrations._family_contract_helpers import (
    make_family_contract_class,
    make_family_registry_class,
)

PATCHES = [
    ("sndr.engines.vllm.patches.attention.flash.p100_flashinfer_full_cg_specdec", "P100"),
    ("sndr.engines.vllm.patches.attention.flash.pn17_fa2_softmax_lse_clamp", "PN17"),
]


class TestAttentionFlashPatchContract(
    make_family_contract_class("attention.flash", PATCHES)
):
    pass


class TestAttentionFlashFamilyRegistry(
    make_family_registry_class(
        "attention.flash", PATCHES, filesystem_dir="attention/flash"
    )
):
    pass
