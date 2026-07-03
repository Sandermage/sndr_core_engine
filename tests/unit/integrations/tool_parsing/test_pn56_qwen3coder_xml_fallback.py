# SPDX-License-Identifier: Apache-2.0
"""TDD for PN56 — qwen3coder XML parse fallback (vllm#41466)."""
from __future__ import annotations

import pytest


def _wiring():
    # PN56 consolidated 2026-06-20 into the P64 coder merged module
    # (p64_p61c_pn56_qwen3coder_consolidated); it re-exports PN56's anchor
    # constants verbatim under the original names.
    import importlib
    return importlib.import_module(
        "sndr.engines.vllm.patches.tool_parsing."
        "p64_p61c_pn56_qwen3coder_consolidated"
    )


def test_anchor_targets_try_block():
    M = _wiring()
    assert "_parse_xml_function_call" in M.ANCHOR_A_OLD
    assert "parsed_tool.function.arguments" in M.ANCHOR_A_OLD
    assert "except Exception:" in M.ANCHOR_A_OLD


def test_replacement_adds_pn56_logic():
    M = _wiring()
    assert "_pn56_parse_succeeded = False" in M.ANCHOR_A_NEW
    assert "_pn56_parse_succeeded = True" in M.ANCHOR_A_NEW
    assert "if (\n                        not _pn56_parse_succeeded" in M.ANCHOR_A_NEW
    # After audit A-14 fix: streamed_args + suffix (computed via rstrip check)
    assert "_pn56_streamed = self.streamed_args_for_tool[" in M.ANCHOR_A_NEW
    assert "_pn56_suffix = \"\" if _pn56_streamed.rstrip().endswith(\"}\") else \"}\"" in M.ANCHOR_A_NEW
    assert "_pn56_streamed + _pn56_suffix" in M.ANCHOR_A_NEW


def test_a14_no_double_close_brace():
    """Audit A-14 invariant: replacement must conditionally append `}` based on
    rstrip().endswith() check — never blind concatenation."""
    M = _wiring()
    # Must NOT have the unconditional + "}" pattern
    assert "self.current_tool_index\n                        ] + \"}\"" not in M.ANCHOR_A_NEW, (
        "A-14 violation: blind `streamed_args + \"}\"` would double-close. "
        "Must use rstrip().endswith(\"}\") guard."
    )
    # Must HAVE the rstrip guard
    assert "rstrip().endswith(\"}\")" in M.ANCHOR_A_NEW


def test_replacement_carries_marker():
    M = _wiring()
    assert "PN56" in M.ANCHOR_A_NEW
    assert "vllm#41466" in M.ANCHOR_A_NEW


def test_idempotent_on_synthetic(tmp_path):
    from sndr.kernel.text_patch import (
        TextPatch, TextPatcher, TextPatchResult,
    )
    M = _wiring()
    target = tmp_path / "qwen3coder_tool_parser.py"
    target.write_text("# header\n" + M.ANCHOR_A_OLD + "\n# tail\n")
    patcher = TextPatcher(
        patch_name="PN56 test",
        target_file=str(target),
        marker=M.GENESIS_PN56_MARKER,
        sub_patches=[TextPatch(name="pn56", anchor=M.ANCHOR_A_OLD,
                                replacement=M.ANCHOR_A_NEW, required=True)],
    )
    r1, _ = patcher.apply()
    assert r1 == TextPatchResult.APPLIED
    body1 = target.read_text()
    assert "PN56" in body1
    r2, _ = patcher.apply()
    assert r2 == TextPatchResult.IDEMPOTENT


def test_pn56_consolidated_into_p64_via_env_flag_alias(monkeypatch):
    """PN56 consolidated into the P64 entry 2026-06-20 as an env_flag_alias
    (that consolidation is preserved — see test_registry_entry_consolidated_
    into_p64, which still asserts the alias lives on the P64 entry).

    Retired reality (2026-06, commit c9a01f81): upstream vllm#45413 (Streaming
    Parser Engine refactor, merged in the current pin) DELETED the qwen3coder
    tool parser target file, so P64 is now lifecycle="retired" — an inert
    strand on the current pin, retained in place only for rollback to a
    pre-#45413 pin. The dispatcher skips retired patches, so the PN56 alias no
    longer engages should_apply('P64') on the current pin even when set."""
    from sndr.dispatcher import should_apply
    monkeypatch.setenv("GENESIS_ENFORCE_VERSION_RANGE", "0")
    for f in (
        "GENESIS_ENABLE_P64_QWEN3CODER_MTP_STREAMING",
        "SNDR_ENABLE_P64_QWEN3CODER_MTP_STREAMING",
        "GENESIS_ENABLE_PN56_QWEN3CODER_XML_FALLBACK",
        "SNDR_ENABLE_PN56_QWEN3CODER_XML_FALLBACK",
    ):
        monkeypatch.delenv(f, raising=False)
    assert should_apply("P64")[0] is False
    monkeypatch.setenv("GENESIS_ENABLE_PN56_QWEN3CODER_XML_FALLBACK", "1")
    # Retired per vllm#45413: alias no longer engages on the current pin.
    decision, reason = should_apply("P64")
    assert decision is False
    assert "retired" in reason.lower() or "superseded" in reason.lower()


def test_registry_entry_consolidated_into_p64():
    from sndr.dispatcher import PATCH_REGISTRY
    assert "PN56" not in PATCH_REGISTRY
    meta = PATCH_REGISTRY["P64"]
    assert (
        "GENESIS_ENABLE_PN56_QWEN3CODER_XML_FALLBACK"
        in meta.get("env_flag_aliases", [])
    )
    assert meta["apply_module"].endswith(
        "p64_p61c_pn56_qwen3coder_consolidated"
    )
    # PN56's vllm#41466 provenance preserved on the merged entry.
    assert "41466" in meta.get("credit", "")


def test_apply_all_registers_pn56():
    from sndr.apply import apply_all
    assert hasattr(apply_all, "apply_patch_N56_qwen3coder_xml_fallback")
