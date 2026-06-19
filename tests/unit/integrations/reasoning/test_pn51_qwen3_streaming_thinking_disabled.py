# SPDX-License-Identifier: Apache-2.0
"""TDD for PN51 — Qwen3 streaming `enable_thinking=false` content routing.

Backport of upstream issue vllm#40816 (OPEN). Validates:

  1. Anchor matches both pristine upstream form AND the post-P27/P61/P61b
     mutated form (since PN51 anchors on the docstring tail, which neither
     of those touches).
  2. Idempotency (second apply is no-op).
  3. Opt-in env-flag gating (default OFF).
  4. The replacement text contains the new short-circuit branch.

Behavioural validation requires a live container running with
`--default-chat-template-kwargs '{"enable_thinking": false}' --reasoning-parser qwen3`
and a streaming client (curl -N) — see Genesis_Doc/streaming_audit/.
"""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest


PRISTINE_PARSER_TAIL = (
    'class Qwen3ReasoningParser:\n'
    '    """Reasoning parser stub."""\n'
    '\n'
    '    def extract_reasoning_streaming(\n'
    '        self,\n'
    '        previous_text,\n'
    '        current_text,\n'
    '        delta_text,\n'
    '        previous_token_ids,\n'
    '        current_token_ids,\n'
    '        delta_token_ids,\n'
    '    ):\n'
    '        """\n'
    '        Extract reasoning content from a streaming delta.\n'
    '\n'
    '        NOTE: When thinking is disabled, no think tokens appear in the\n'
    '        generated output. The serving layer detects this via\n'
    '        prompt_is_reasoning_end and routes deltas as content without\n'
    '        calling this method.\n'
    '        """\n'
    '        # Strip <think> from delta if present (old template / edge case\n'
    '        # where the model generates <think> itself).\n'
    '        if self.start_token_id in delta_token_ids:\n'
    '            pass\n'
)


def _load_anchors():
    """Load the anchor strings out of the wiring module.

    PN51 was consolidated 2026-06-20 into the P61b reasoning merged module
    (p61b_p59_pn51_qwen3_reasoning_consolidated); it re-exports PN51's anchor
    constants verbatim under the original names, so these assertions still
    hold against the consolidated module.
    """
    import importlib
    M = importlib.import_module(
        "sndr.engines.vllm.patches.reasoning."
        "p61b_p59_pn51_qwen3_reasoning_consolidated"
    )
    return M.ANCHOR_OLD, M.ANCHOR_NEW, M.GENESIS_PN51_MARKER


def test_anchor_old_substring_present_in_pristine_form():
    """The PN51 anchor must match a pristine upstream parser body."""
    anchor_old, _, _ = _load_anchors()
    assert anchor_old in PRISTINE_PARSER_TAIL, (
        "PN51 anchor doesn't match pristine upstream — "
        "regenerate from current vllm/reasoning/qwen3_reasoning_parser.py"
    )


def test_anchor_new_contains_pn51_marker_and_check():
    """The replacement body must inject the new short-circuit branch."""
    _, anchor_new, marker = _load_anchors()
    assert "PN51" in anchor_new
    assert "vllm#40816" in anchor_new
    assert "not self.thinking_enabled" in anchor_new
    assert "self.end_token_id not in current_token_ids" in anchor_new
    assert "DeltaMessage(content=delta_text)" in anchor_new
    # Marker is referenced separately by the patcher
    assert "PN51" in marker


def test_replacement_preserves_original_comment():
    """The replacement must keep the next line that the anchor ends on,
    so that downstream patches anchored on the same comment still apply."""
    anchor_old, anchor_new, _ = _load_anchors()
    tail = "# Strip <think> from delta if present (old template / edge case"
    assert tail in anchor_old
    assert tail in anchor_new


def test_apply_idempotent_on_synthetic(tmp_path: Path, monkeypatch):
    """Apply once, then apply again; second call should be a no-op."""
    from sndr.kernel.text_patch import (
        TextPatch, TextPatcher, TextPatchResult,
    )
    anchor_old, anchor_new, marker = _load_anchors()

    target = tmp_path / "qwen3_reasoning_parser.py"
    target.write_text(PRISTINE_PARSER_TAIL)

    patcher = TextPatcher(
        patch_name="PN51 test",
        target_file=str(target),
        marker=marker,
        sub_patches=[TextPatch(name="pn51", anchor=anchor_old,
                                replacement=anchor_new, required=True)],
    )

    # First apply
    r1, _ = patcher.apply()
    assert r1 == TextPatchResult.APPLIED
    body_after_first = target.read_text()
    assert "PN51" in body_after_first
    assert "not self.thinking_enabled" in body_after_first

    # Second apply — must be idempotent
    r2, _ = patcher.apply()
    assert r2 == TextPatchResult.IDEMPOTENT
    assert target.read_text() == body_after_first


def test_pn51_consolidated_into_p61b_via_env_flag_alias(monkeypatch):
    """PN51 was consolidated into the P61b entry 2026-06-20; its enable flag
    is retained as an env_flag_alias on P61b. With version enforcement OFF,
    setting ONLY the PN51 alias must engage should_apply('P61b') (the
    alias-honoring _resolve_env_state path), and clearing all flags must skip.
    """
    from sndr.dispatcher import should_apply
    monkeypatch.setenv("GENESIS_ENFORCE_VERSION_RANGE", "0")
    for f in (
        "GENESIS_ENABLE_P61B_STREAMING_OVERLAP",
        "SNDR_ENABLE_P61B_STREAMING_OVERLAP",
        "GENESIS_ENABLE_PN51_QWEN3_STREAMING_THINKING_DISABLED",
        "SNDR_ENABLE_PN51_QWEN3_STREAMING_THINKING_DISABLED",
    ):
        monkeypatch.delenv(f, raising=False)
    decision, reason = should_apply("P61b")
    assert decision is False  # all flags off -> skip
    assert "opt-in" in reason.lower() or "off" in reason.lower()

    monkeypatch.setenv(
        "GENESIS_ENABLE_PN51_QWEN3_STREAMING_THINKING_DISABLED", "1",
    )
    decision, _ = should_apply("P61b")
    assert decision is True  # alias-only engages the merged module


def test_registry_entry_consolidated_into_p61b():
    """PN51 is no longer a standalone registry id — it is consolidated into
    the P61b entry as an env_flag_alias, and the P61b apply_module points at
    the reasoning merged module."""
    from sndr.dispatcher import PATCH_REGISTRY
    assert "PN51" not in PATCH_REGISTRY
    meta = PATCH_REGISTRY["P61b"]
    assert (
        "GENESIS_ENABLE_PN51_QWEN3_STREAMING_THINKING_DISABLED"
        in meta.get("env_flag_aliases", [])
    )
    assert meta["apply_module"].endswith(
        "p61b_p59_pn51_qwen3_reasoning_consolidated"
    )
    # PN51's vllm#40816 narrative is preserved on the merged entry.
    assert "40816" in meta["title"] or "40816" in meta.get("credit", "")


def test_apply_all_registers_pn51():
    """apply_all still exposes the PN51 legacy boot hook (it now delegates to
    the consolidated module)."""
    from sndr.apply import apply_all
    assert hasattr(
        apply_all, "apply_patch_N51_qwen3_streaming_thinking_disabled"
    ), "PN51 legacy boot hook missing from apply_all"
