# SPDX-License-Identifier: Apache-2.0
"""serving family contract — Theme 4 expansion (2026-05-11).

5 registry entries map to 4 files: P68 + P69 share `p68_69_long_ctx_
tool_adherence.py` (paired patch for long-context tool adherence).
"""
from tests.unit.integrations._family_contract_helpers import (
    make_family_contract_class,
    make_family_registry_class,
)

PATCHES = [
    ("vllm.sndr_core.integrations.serving.p62_structured_output_spec_decode_timing", "P62"),
    ("vllm.sndr_core.integrations.serving.p68_69_long_ctx_tool_adherence", "P68"),
    ("vllm.sndr_core.integrations.serving.p68_69_long_ctx_tool_adherence", "P69"),
    ("vllm.sndr_core.integrations.serving.p107_mtp_truncation_detector", "P107"),
    ("vllm.sndr_core.integrations.serving.pn70_tool_schema_subset_filter", "PN70"),
]


class TestServingPatchContract(make_family_contract_class("serving", PATCHES)):
    pass


class TestServingFamilyRegistry(make_family_registry_class("serving", PATCHES)):
    pass
