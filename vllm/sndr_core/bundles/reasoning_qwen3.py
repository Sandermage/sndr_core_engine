# SPDX-License-Identifier: Apache-2.0
"""Bundle: qwen3 reasoning-parser fixes (community tier).

Atomic apply of 6 patches on `reasoning/qwen3_reasoning_parser.py`:

  P12  — Implicit reasoning-end on `<tool_call>` token (vllm#XXXXX).
  P27  — BEFORE-THINK fallback for tools-without-thinking models.
  P59  — Tool-call recovery when reasoning_parser drops XML
         (PR #39055 backport — Qwen3 reasoning parser drops tool_call
         XML inside `<think>` block).
  P61  — Multi-tool first-occurrence (vllm#33041 backport).
  P61b — Streaming partial-tag overlap guard (vllm#40783 backport,
         ExtReMLapin).
  PN51 — Streaming thinking-disabled content routing.

All 6 touch the same file — bundle gives atomic commit of the entire
reasoning parser chain (no partial state across reboots).

Tier:    community
Flag:    SNDR_ENABLE_BUNDLE_REASONING_QWEN3=1
Targets: reasoning/qwen3_reasoning_parser.py
"""
from __future__ import annotations

from vllm.sndr_core.env import Flags

from ._common import run_bundle


def apply() -> tuple[str, str]:
    """Apply qwen3 reasoning-parser bundle atomically."""
    from vllm.sndr_core.integrations.reasoning import p12_tool_call_reasoning as _p12

    from vllm.sndr_core.integrations.reasoning import p27_reasoning_before_think as _p27
    from vllm.sndr_core.integrations.reasoning import p59_qwen3_reasoning_tool_call_recovery as _p59

    from vllm.sndr_core.integrations.reasoning import p61_qwen3_multi_tool_first_occurrence as _p61

    from vllm.sndr_core.integrations.reasoning import p61b_qwen3_streaming_overlap_guard as _p61b

    from vllm.sndr_core.integrations.reasoning import pn51_qwen3_streaming_thinking_disabled as _pn51
    return run_bundle(
        name="reasoning_qwen3",
        umbrella_flag=Flags.BUNDLE_REASONING_QWEN3,
        tier="community",
        patcher_factories=[
            _p12._make_patcher,
            _p27._make_patcher,
            _p59._make_patcher,
            _p61._make_patcher,
            _p61b._make_patcher,
            _pn51._make_patcher,
        ],
    )


__all__ = ["apply"]
