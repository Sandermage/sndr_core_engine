# SPDX-License-Identifier: Apache-2.0
"""Tests for ``tools/bench_agentic.py``.

The bench is an HTTP client (aiohttp) so we don't exercise full sessions
in unit tests. Instead:
    1. argparse contract — flags accepted, defaults sane
    2. ``_make_tool_result`` — payload grows with turn index (intended)
    3. ``_summarize`` — aggregation math (mean/p50, growth) on synthetic
       per-turn metrics
    4. SYSTEM_PROMPT / TOOLS / USER_PROMPTS — schema invariants
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = REPO_ROOT / "tools" / "bench_agentic.py"

if not pytest.importorskip("aiohttp", reason="aiohttp required by bench_agentic"):
    pytest.skip("aiohttp missing", allow_module_level=True)


def _import_tool():
    spec = importlib.util.spec_from_file_location("bench_agentic", TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["bench_agentic"] = mod
    assert spec.loader is not None  # nosec
    spec.loader.exec_module(mod)
    return mod


def test_argparse_defaults_sane() -> None:
    mod = _import_tool()
    args = mod._parse_args.__wrapped__() if hasattr(
        mod._parse_args, "__wrapped__"
    ) else None
    # Simulate empty argv via direct argparser exercise.
    import argparse as _argp
    # Re-build the argparser standalone (since _parse_args reads sys.argv).
    saved_argv = sys.argv
    try:
        sys.argv = ["bench_agentic.py"]
        args = mod._parse_args()
    finally:
        sys.argv = saved_argv
    assert args.turns == 8
    assert args.sessions == 1
    assert args.max_tokens == 150
    assert 0.0 <= args.temperature <= 1.5
    assert args.request_timeout > 0
    assert args.continue_on_no_tool is False


def test_argparse_continue_on_no_tool_flag() -> None:
    mod = _import_tool()
    saved_argv = sys.argv
    try:
        sys.argv = ["bench_agentic.py", "--continue-on-no-tool",
                    "--turns", "3", "--sessions", "2"]
        args = mod._parse_args()
    finally:
        sys.argv = saved_argv
    assert args.continue_on_no_tool is True
    assert args.turns == 3
    assert args.sessions == 2


def test_tool_result_grows_with_turn() -> None:
    mod = _import_tool()
    short = mod._make_tool_result(1, "Read")
    long = mod._make_tool_result(20, "Read")
    assert len(long) > len(short), (
        "tool-result payload should grow with turn index — the bench's "
        "whole purpose is to ramp accumulated context"
    )


def test_tools_schema_shape() -> None:
    mod = _import_tool()
    assert len(mod.TOOLS) == 10
    for t in mod.TOOLS:
        assert t["type"] == "function"
        fn = t["function"]
        assert isinstance(fn["name"], str) and fn["name"]
        assert "description" in fn
        assert "parameters" in fn


def test_user_prompts_present() -> None:
    mod = _import_tool()
    assert isinstance(mod.USER_PROMPTS, list)
    assert len(mod.USER_PROMPTS) >= 10
    for p in mod.USER_PROMPTS:
        assert isinstance(p, str) and p.strip()


def test_summarize_silent_empty_detection() -> None:
    mod = _import_tool()
    # Synthetic per-turn metrics: 3 good turns + 1 silent-empty.
    turns = [
        {"turn": 1, "session": 1, "ttft_ms": 100.0, "decode_tps": 50.0,
         "completion_tokens": 80, "prompt_tokens": 200,
         "finish_reason": "tool_calls", "error": None, "silent_empty": False},
        {"turn": 2, "session": 1, "ttft_ms": 110.0, "decode_tps": 48.0,
         "completion_tokens": 90, "prompt_tokens": 400,
         "finish_reason": "tool_calls", "error": None, "silent_empty": False},
        {"turn": 3, "session": 1, "ttft_ms": 200.0, "decode_tps": 45.0,
         "completion_tokens": 70, "prompt_tokens": 800,
         "finish_reason": "tool_calls", "error": None, "silent_empty": False},
        {"turn": 4, "session": 1, "ttft_ms": 250.0, "decode_tps": None,
         "completion_tokens": 0, "prompt_tokens": 1200,
         "finish_reason": "stop", "error": None, "silent_empty": True},
    ]
    summary = mod._summarize(turns)
    assert summary["total_turns"] == 4
    assert summary["successful_turns"] == 3
    assert summary["silent_empty_turns"] == 1
    assert summary["error_turns"] == 0
    assert summary["ttft_p50_ms"] is not None
    # TTFT grows from turn 1 → 3: ~100 → 200 ms — should be positive.
    if "ttft_growth_ms_p50" in summary:
        assert summary["ttft_growth_ms_p50"] >= 0


def test_summarize_handles_all_errors() -> None:
    mod = _import_tool()
    turns = [
        {"turn": 1, "session": 1, "ttft_ms": None, "decode_tps": None,
         "completion_tokens": 0, "prompt_tokens": None,
         "finish_reason": None, "error": "timeout", "silent_empty": False},
    ]
    summary = mod._summarize(turns)
    assert summary["successful_turns"] == 0
    assert summary["error_turns"] == 1
    assert "note" in summary
