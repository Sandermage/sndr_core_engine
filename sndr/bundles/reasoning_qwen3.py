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

from sndr.env import Flags

from ._common import run_bundle


def apply() -> tuple[str, str]:
    """Apply qwen3 reasoning-parser bundle atomically."""
    from sndr.engines.vllm.patches.reasoning import p12_tool_call_reasoning as _p12

    from sndr.engines.vllm.patches.reasoning import p27_reasoning_before_think as _p27

    from sndr.engines.vllm._archive import p61_qwen3_multi_tool_first_occurrence as _p61  # moved to _retired/ 2026-05-14 — kept in bundle for legacy boot order, harmless no-op anchor

    # P61b + P59 + PN51 consolidated 2026-06-20 into one module; it exposes one
    # per-feature _make_*_patcher factory each (failure isolation + distinct
    # markers), so the bundle's per-patcher transaction layout is preserved.
    from sndr.engines.vllm.patches.reasoning import (
        p61b_p59_pn51_qwen3_reasoning_consolidated as _reasoning,
    )
    return run_bundle(
        name="reasoning_qwen3",
        umbrella_flag=Flags.BUNDLE_REASONING_QWEN3,
        tier="community",
        patcher_factories=[
            _p12._make_patcher,
            _p27._make_patcher,
            _reasoning._make_p59_patcher,
            _p61._make_patcher,
            _reasoning._make_p61b_patcher,
            _reasoning._make_pn51_patcher,
        ],
    )


__all__ = ["apply"]
