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
    ("sndr.engines.vllm.patches.tool_parsing.p15_qwen3_none_null", "P15"),
    # P64 + P61c + PN56 consolidated 2026-06-20 into one module (all three
    # patch tool_parsers/qwen3coder_tool_parser.py at disjoint regions). The
    # trio is represented by the surviving primary id P64 pointing at the
    # consolidated module.
    ("sndr.engines.vllm.patches.tool_parsing.p64_p61c_pn56_qwen3coder_consolidated", "P64"),
]


class TestToolParsingPatchContract(
    make_family_contract_class("tool_parsing", PATCHES)
):
    pass


class TestToolParsingFamilyRegistry(
    make_family_registry_class("tool_parsing", PATCHES)
):
    pass
