# SPDX-License-Identifier: Apache-2.0
"""tool_parsing family contract — Theme 4 expansion (2026-05-11).

Note: registry has 5 entries (P15, P29, P61c, P64, PN56) but P29 is a
legacy synthetic-flag-only entry with NO dedicated file (legacy auto-
apply pattern via dispatcher). Contract covers the 4 patches that have
files on disk.
"""
from tests.unit.integrations._family_contract_helpers import (
    make_family_contract_class,
    make_family_registry_class,
)

PATCHES = [
    ("vllm.sndr_core.integrations.tool_parsing.p15_qwen3_none_null", "P15"),
    ("vllm.sndr_core.integrations.tool_parsing.p61c_qwen3coder_deferred_commit", "P61c"),
    ("vllm.sndr_core.integrations.tool_parsing.p64_qwen3coder_mtp_streaming", "P64"),
    ("vllm.sndr_core.integrations.tool_parsing.pn56_qwen3coder_xml_fallback", "PN56"),
]


class TestToolParsingPatchContract(
    make_family_contract_class("tool_parsing", PATCHES)
):
    pass


class TestToolParsingFamilyRegistry(
    make_family_registry_class("tool_parsing", PATCHES)
):
    pass
