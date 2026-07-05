# SPDX-License-Identifier: Apache-2.0
"""Recurrence gate for audit finding #16 (2026-07-04).

Both INT4 27B builtin model YAMLs (TQ-k8v4 and fp8kv) serve the SAME
Qwen3.6-27B-int4-AutoRound checkpoint, which emits invalid tool-call
structure under tool_choice=auto (no grammar built → garbage). The fix
is GENESIS_P68_FORCE_ON_ALL_TOOLS=1. It drifted onto the TQ lane only;
the fp8kv lane (same garbage risk) was left without it. This gate keeps
the two lanes' tool-call-critical flags in lockstep so the drift cannot
silently reappear.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_MODEL_DIR = (
    Path(__file__).resolve().parents[3]
    / "sndr" / "model_configs" / "builtin" / "model"
)
_INT4_27B = [
    "qwen3.6-27b-int4-autoround-tq-k8v4.yaml",
    "qwen3.6-27b-int4-autoround-fp8kv.yaml",
]
_TOOLCALL_CRITICAL_FLAGS = [
    "GENESIS_ENABLE_P68_AUTO_FORCE_TOOL",
    "GENESIS_P68_FORCE_ON_ALL_TOOLS",
]


def _patch_env(name: str) -> dict:
    doc = yaml.safe_load((_MODEL_DIR / name).read_text(encoding="utf-8"))
    return (doc or {}).get("patches", {}) or {}


def test_both_int4_27b_carry_the_toolcall_critical_flags():
    for name in _INT4_27B:
        env = _patch_env(name)
        for flag in _TOOLCALL_CRITICAL_FLAGS:
            assert env.get(flag) == "1", (
                f"{name} missing tool-call-critical {flag}=1 — the INT4 27B "
                f"emits garbage tool_calls under tool_choice=auto without it"
            )
