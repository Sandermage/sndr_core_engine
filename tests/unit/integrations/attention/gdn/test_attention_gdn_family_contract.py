# SPDX-License-Identifier: Apache-2.0
"""attention.gdn family contract — Theme 4 expansion (2026-05-11).

17 GDN patches — largest single-family contract. Covers all from
classic GDN (P7/P28) through hybrid attention helpers (P39a, P46) to
recent Cliff/streaming fixes (P103, PN59, PN79). Mix of legacy + active.
"""
from tests.unit.integrations._family_contract_helpers import (
    make_family_contract_class,
    make_family_registry_class,
)

PATCHES = [
    ("vllm.sndr_core.integrations.attention.gdn.p7_gdn_dual_stream", "P7"),
    ("vllm.sndr_core.integrations.attention.gdn.p7b_gdn_dual_stream_customop", "P7b"),
    ("vllm.sndr_core.integrations.attention.gdn.p28_gdn_core_attn", "P28"),
    ("vllm.sndr_core.integrations.attention.gdn.p39a_fla_kkt_buffer", "P39a"),
    ("vllm.sndr_core.integrations.attention.gdn.p46_gdn_gating_buffers", "P46"),
    ("vllm.sndr_core.integrations.attention.gdn.p60_gdn_ngram_state_recovery", "P60"),
    ("vllm.sndr_core.integrations.attention.gdn.p60b_gdn_ngram_triton_kernel", "P60b"),
    ("vllm.sndr_core.integrations._retired.p63_mtp_gdn_state_recovery", "P63"),
    ("vllm.sndr_core.integrations.attention.gdn.p103_fla_cliff2_chunked", "P103"),
    ("vllm.sndr_core.integrations.attention.gdn.pn11_gdn_a_b_contiguous", "PN11"),
    ("vllm.sndr_core.integrations.attention.gdn.pn29_gdn_chunk_o_scale_fold", "PN29"),
    ("vllm.sndr_core.integrations.attention.gdn.pn30_ds_layout_spec_decode_align", "PN30"),
    ("vllm.sndr_core.integrations.attention.gdn.pn32_gdn_chunked_prefill", "PN32"),
    ("vllm.sndr_core.integrations.attention.gdn.pn50_gdn_fused_proj", "PN50"),
    ("vllm.sndr_core.integrations.attention.gdn.pn54_gdn_contiguous_dedup", "PN54"),
    ("vllm.sndr_core.integrations.attention.gdn.pn59_streaming_gdn", "PN59"),
    ("vllm.sndr_core.integrations.attention.gdn.pn79_inplace_ssm_state", "PN79"),
]


class TestAttentionGdnPatchContract(
    make_family_contract_class("attention.gdn", PATCHES)
):
    pass


class TestAttentionGdnFamilyRegistry(
    make_family_registry_class(
        "attention.gdn", PATCHES, filesystem_dir="attention/gdn"
    )
):
    pass
