# SPDX-License-Identifier: Apache-2.0
"""attention.turboquant family contract — Theme 4 expansion (2026-05-11).

Largest single-family by registry: 23 patches but 4 are legacy registry-
only entries with NO dedicated file (P18b, P20, P32, P51 — pre-dispatcher
era, synthetic GENESIS_LEGACY_* flags applied via legacy auto-apply
path). Contract covers the 19 patches that have files on disk.
"""
from tests.unit.integrations._family_contract_helpers import (
    make_family_contract_class,
    make_family_registry_class,
)

PATCHES = [
    ("vllm.sndr_core.integrations.attention.turboquant.p3_tq_bf16_cast", "P3"),
    ("vllm.sndr_core.integrations.attention.turboquant.p22_tq_prealloc", "P22"),
    ("vllm.sndr_core.integrations.attention.turboquant.p26_prefill_output", "P26"),
    ("vllm.sndr_core.integrations.attention.turboquant.p38_tq_continuation_memory", "P38"),
    ("vllm.sndr_core.integrations.attention.turboquant.p40_tq_grouped_decode", "P40"),
    ("vllm.sndr_core.integrations.attention.turboquant.p44_tq_mixed_attn_out", "P44"),
    ("vllm.sndr_core.integrations.attention.turboquant.p65_turboquant_spec_cg_downgrade", "P65"),
    ("vllm.sndr_core.integrations.attention.turboquant.p67_tq_multi_query_kernel", "P67"),
    ("vllm.sndr_core.integrations.attention.turboquant.p67b_spec_verify_routing", "P67b"),
    ("vllm.sndr_core.integrations.attention.turboquant.p67c_sparse_v", "P67c"),
    ("vllm.sndr_core.integrations.attention.turboquant.p78_tolist_capture_guard", "P78"),
    ("vllm.sndr_core.integrations.attention.turboquant.p98_tq_workspace_revert", "P98"),
    ("vllm.sndr_core.integrations.attention.turboquant.p99_workspace_manager_memoize", "P99"),
    ("vllm.sndr_core.integrations.attention.turboquant.p101_tq_continuation_slicing", "P101"),
    ("vllm.sndr_core.integrations.attention.turboquant.pn14_tq_decode_oob_clamp", "PN14"),
    ("vllm.sndr_core.integrations.attention.turboquant.pn26_sparse_v_kernel", "PN26"),
    ("vllm.sndr_core.integrations.attention.turboquant.pn31_fa_varlen_persistent_out", "PN31"),
    ("vllm.sndr_core.integrations.attention.turboquant.pn34_workspace_lock_runtime_relax", "PN34"),
    ("vllm.sndr_core.integrations.attention.turboquant.pn57_tq_centroids_disk_cache", "PN57"),
]


class TestAttentionTurboquantPatchContract(
    make_family_contract_class("attention.turboquant", PATCHES)
):
    pass


class TestAttentionTurboquantFamilyRegistry(
    make_family_registry_class(
        "attention.turboquant", PATCHES, filesystem_dir="attention/turboquant"
    )
):
    pass
