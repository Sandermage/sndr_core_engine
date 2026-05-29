#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Agentic context-depth bench — TTFT growth as conversation accumulates.

Port of noonghunna/club-3090 `scripts/bench-agentic.sh` methodology
(see https://github.com/noonghunna/club-3090) adapted for Genesis stack.

What it measures
----------------
Multi-turn agentic conversation against a tool-call enabled endpoint
(qwen3_coder / qwen3_xml). Each turn:
  1. Send accumulated history + a fresh user follow-up.
  2. Streaming chat-completion with ``tool_choice="required"``.
  3. Capture prompt_tokens, TTFT (time to first SSE chunk), decode_tps.
  4. Append a synthetic ``tool_result`` to history so context grows.

Reports per-turn table + TTFT growth analysis ("flat = low incremental
prefill; linear = O(n) prefill recomputation").

Why this is useful
------------------
* Real agentic workloads (Cline / Claude Code / opencode) accumulate
  ~22-25K context by turn 5-10. The single-shot ``genesis_bench_suite``
  measures a single warm decode pass — it does NOT detect:
   - Cliff 2b (silent-empty turn at ~25K accumulated context)
   - Multi-turn arg-corruption under MTP×qwen3_coder (club-3090 #178)
   - Prefix-cache miss patterns when system prompt drifts turn-to-turn

* This bench surfaces TTFT-vs-depth curve and silent-empty turns
  (HTTP 200 + 0 completion tokens with finish_reason=stop).

What this is NOT
----------------
* Not a universal cache verdict — treat as a per-(engine, arch, config)
  curve-shape producer.
* Ramp depth is bounded by tool-call reliability: if the model can't
  emit a parseable tool call at depth, the ramp stops there. Use
  ``--continue-on-no-tool`` (synthetic tool_result fallback, club-3090
  issue #255) to push past tool-parse drops.

Examples
--------
  # 5-turn ramp on 35B PROD endpoint
  python3 tools/bench_agentic.py --turns 5

  # 12-turn deep ramp + capture JSON
  python3 tools/bench_agentic.py --turns 12 --sessions 2 \\
      --out tools/bench_results/agentic-35b_<pin>_<date>.json

  # 27B port (different served name + port)
  python3 tools/bench_agentic.py --url http://localhost:8101/v1 \\
      --model qwen3.6-27b --turns 10

  # Force ramp to continue even when a turn returns no tool call
  python3 tools/bench_agentic.py --turns 15 --continue-on-no-tool

Compatibility notes
-------------------
* Endpoint must support OpenAI-format ``chat/completions`` + streaming
  + ``tools`` + ``tool_choice``. Tested against our P64+PN56-protected
  qwen3_coder path.
* The fixture is intentionally minimal — 10 Claude-Code-like tools
  + a coding-agent system prompt — to keep this script auditable
  without external dependencies. Club-3090's 192 KB Claude session
  fixture is a richer (but redacted) alternative.

Sander 2026-05-29 — derived from club-3090 bench-agentic.sh research
during the K.1.R.R.X session cross-reference work.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import os
import statistics
import sys
import time
from typing import Any

try:
    import aiohttp
except ImportError:
    sys.stderr.write(
        "ERROR: aiohttp not installed. Install with: pip install aiohttp\n"
    )
    sys.exit(2)


DEFAULT_URL = "http://localhost:8000/v1"
DEFAULT_MODEL = "qwen3.6-35b-a3b"
DEFAULT_API_KEY = os.environ.get("VLLM_API_KEY", "genesis-local")


# Coding-agent system prompt (close to Claude Code's; bench-agentic.sh
# uses an identical-shape one).
SYSTEM_PROMPT = (
    "You are an autonomous coding assistant working inside a Python "
    "repository. The user is investigating a performance regression. "
    "When file contents, search results, or command output would "
    "materially change your answer, call the appropriate tool — don't "
    "speculate. After each tool call, briefly state what you learned "
    "and what your next planned step is. Keep responses concise "
    "(under 100 words); defer to tools for raw data."
)

# 10-tool Claude-Code-like schema. Each tool has a single string arg
# so the model can pick any tool easily — the goal is to exercise the
# tool-call pipeline, NOT to test parameter complexity.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "Read",
            "description": "Read the contents of a file at the given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute file path."},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Bash",
            "description": "Execute a bash command and return stdout/stderr.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Bash command."},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Edit",
            "description": "Apply an edit to a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                },
                "required": ["file_path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Write",
            "description": "Write text content to a file (overwrites).",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Grep",
            "description": "Search files for a regex pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Glob",
            "description": "List files matching a glob pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "LS",
            "description": "List entries in a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "TodoRead",
            "description": "Read the current task list.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "TodoWrite",
            "description": "Update the task list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {"type": "string"},
                },
                "required": ["todos"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "WebFetch",
            "description": "Fetch a URL and return its contents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                },
                "required": ["url"],
            },
        },
    },
]


# Coding-agent user prompts — each one is a realistic follow-up that
# would prompt a tool call. The script cycles through them; on long
# ramps it loops, simulating an extended debugging session.
USER_PROMPTS = [
    "What's in the repo root? List directory contents.",
    "Read the README to understand the project.",
    "Search for TODO comments across the codebase.",
    "Open the main entry point file.",
    "Check git status for uncommitted changes.",
    "Find all Python files under src/.",
    "Read the tests directory listing.",
    "Run pytest with -v on the unit tests.",
    "Check the requirements.txt for outdated packages.",
    "Search for any FIXME markers.",
    "Read the changelog for recent changes.",
    "List files in scripts/ directory.",
    "Grep for 'def main' to find entry points.",
    "Fetch the latest release notes from GitHub.",
    "Update the todo list with current progress.",
]


# Synthetic tool-result payloads, varying size to grow context per turn.
# Targets: turn 1 → ~200 tok payload, turn N → ~1000 tok payload
def _make_tool_result(turn_idx: int, tool_name: str) -> str:
    base = (
        f"[Tool result for {tool_name} on turn {turn_idx}]\n"
        f"Status: OK (synthetic fixture, real call would return live data).\n"
    )
    # Pad with plausible coding-context noise to grow context.
    # ~80 chars/line × (50 + turn_idx*8) lines → grows with depth.
    pad_lines = 50 + turn_idx * 8
    pad = "\n".join(
        f"  L{i:04d}: src/genesis_demo/module_{i % 16}.py:{(i * 31) % 200} "
        f"# placeholder fixture line — content not meaningful, "
        f"only used to grow accumulated context"
        for i in range(pad_lines)
    )
    return base + pad


async def _stream_turn(
    session: aiohttp.ClientSession,
    url: str,
    model: str,
    api_key: str,
    messages: list[dict],
    tools: list[dict],
    max_tokens: int,
    temperature: float,
    request_timeout: float,
) -> dict:
    """Run one streaming chat-completion turn. Return turn metrics."""
    body = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "required",
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    t0 = time.perf_counter()
    ttft: float | None = None
    n_content_chunks = 0
    n_tokens = 0
    accumulated_content = ""
    accumulated_tool_calls: list[dict] = []
    finish_reason: str | None = None
    usage: dict | None = None
    error: str | None = None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with session.post(
            f"{url.rstrip('/')}/chat/completions",
            json=body,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=request_timeout),
        ) as resp:
            if resp.status != 200:
                err_body = await resp.text()
                return {
                    "error": f"HTTP {resp.status}: {err_body[:500]}",
                    "wall_ms": (time.perf_counter() - t0) * 1000.0,
                    "ttft_ms": None,
                    "completion_tokens": 0,
                    "prompt_tokens": None,
                    "decode_tps": None,
                    "finish_reason": None,
                    "tool_calls": [],
                    "content": "",
                }
            async for raw_line in resp.content:
                if not raw_line.startswith(b"data: "):
                    continue
                chunk = raw_line[6:].strip()
                if chunk == b"[DONE]":
                    break
                try:
                    j = json.loads(chunk)
                except Exception:
                    continue
                if ttft is None:
                    ttft = time.perf_counter() - t0
                if "usage" in j and j["usage"] is not None:
                    usage = j["usage"]
                if not j.get("choices"):
                    continue
                choice = j["choices"][0]
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    accumulated_content += delta["content"]
                    n_content_chunks += 1
                if delta.get("tool_calls"):
                    for tc in delta["tool_calls"]:
                        # Coalesce tool_calls by index.
                        idx = tc.get("index", 0)
                        while len(accumulated_tool_calls) <= idx:
                            accumulated_tool_calls.append(
                                {"id": "", "type": "function",
                                 "function": {"name": "", "arguments": ""}}
                            )
                        slot = accumulated_tool_calls[idx]
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        if tc.get("function", {}).get("name"):
                            slot["function"]["name"] = tc["function"]["name"]
                        if tc.get("function", {}).get("arguments"):
                            slot["function"]["arguments"] += (
                                tc["function"]["arguments"]
                            )
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]
    except asyncio.TimeoutError:
        error = f"timeout after {request_timeout}s"
    except Exception as e:
        error = f"exception: {type(e).__name__}: {e}"

    wall = time.perf_counter() - t0
    prompt_tokens = (usage or {}).get("prompt_tokens")
    n_tokens = (usage or {}).get("completion_tokens") or len(
        accumulated_content
    ) // 4  # rough token estimate when usage missing
    decode_tps: float | None
    if ttft is not None and (wall - ttft) > 1e-6 and n_tokens:
        decode_tps = n_tokens / (wall - ttft)
    else:
        decode_tps = None
    return {
        "error": error,
        "wall_ms": wall * 1000.0,
        "ttft_ms": (ttft * 1000.0) if ttft is not None else None,
        "completion_tokens": int(n_tokens),
        "prompt_tokens": prompt_tokens,
        "decode_tps": decode_tps,
        "finish_reason": finish_reason,
        "tool_calls": accumulated_tool_calls,
        "content": accumulated_content,
    }


async def run_session(
    args: argparse.Namespace, session_idx: int
) -> list[dict]:
    """Run a single multi-turn session. Return list of per-turn metrics."""
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    turns: list[dict] = []
    async with aiohttp.ClientSession() as http:
        for turn_idx in range(1, args.turns + 1):
            user_prompt = USER_PROMPTS[(turn_idx - 1) % len(USER_PROMPTS)]
            messages.append({"role": "user", "content": user_prompt})
            print(
                f"  [session {session_idx}] turn {turn_idx}/{args.turns} → "
                f"user msg ({len(user_prompt)} chars), accumulated="
                f"{sum(len(m.get('content') or '') for m in messages)}",
                flush=True,
            )
            metrics = await _stream_turn(
                http,
                url=args.url,
                model=args.model,
                api_key=args.api_key,
                messages=messages,
                tools=TOOLS,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                request_timeout=args.request_timeout,
            )
            metrics["turn"] = turn_idx
            metrics["session"] = session_idx
            turns.append(metrics)
            # Silent-empty detection.
            is_silent_empty = (
                metrics.get("error") is None
                and metrics.get("finish_reason") == "stop"
                and metrics.get("completion_tokens", 0) == 0
            )
            metrics["silent_empty"] = is_silent_empty
            if is_silent_empty:
                print(
                    f"    ⚠ silent-empty turn (HTTP 200, 0 completion "
                    f"tokens, finish_reason=stop) — Cliff 2b signature",
                    flush=True,
                )
            tool_calls = metrics.get("tool_calls") or []
            valid_tool = bool(tool_calls and tool_calls[0]["function"]["name"])
            # Validate tool_call.arguments is parseable JSON before
            # appending to history. qwen3_coder × MTP at depth can emit
            # truncated mid-JSON-string arguments (club-3090 #178
            # arg-corruption mode); appending the broken tool_call would
            # poison every subsequent turn with HTTP 400 "Unterminated
            # string" on history validation. Empirically observed on
            # 35B PROD coder baseline 2026-05-29: session 1 turns 9-12
            # failed cascading after a broken tool_call at turn 8.
            if valid_tool:
                args_str = tool_calls[0]["function"].get("arguments") or ""
                try:
                    json.loads(args_str) if args_str else None
                    args_ok = True
                except json.JSONDecodeError:
                    args_ok = False
                if not args_ok:
                    metrics["malformed_tool_args"] = True
                    metrics["malformed_args_preview"] = args_str[:120]
                    valid_tool = False  # treat as no-tool for history
                    print(
                        f"    ⚠ malformed tool_call.arguments — JSON "
                        f"parse failed at depth (club-3090 #178). "
                        f"Synthetic placeholder injected; ramp continues.",
                        flush=True,
                    )
            content = metrics.get("content") or ""
            # Assistant turn — append what model actually produced, so
            # next turn's accumulated context reflects reality.
            assistant_msg: dict[str, Any] = {"role": "assistant"}
            if content:
                assistant_msg["content"] = content
            if valid_tool:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)
            # Tool-result injection: only when we got a tool call OR
            # --continue-on-no-tool is set (club-3090 #255 mitigation).
            if valid_tool:
                tool_name = tool_calls[0]["function"]["name"]
                tool_call_id = tool_calls[0].get("id") or f"call_{turn_idx}"
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": _make_tool_result(turn_idx, tool_name),
                })
            elif args.continue_on_no_tool:
                # Synthetic tool_result append even without a tool call,
                # so the ramp keeps growing per #255.
                messages.append({
                    "role": "user",
                    "content": (
                        f"[Synthetic tool-result fixture for turn "
                        f"{turn_idx} — tool call did not parse; "
                        f"continuing ramp anyway per --continue-on-no-tool]\n"
                        + _make_tool_result(turn_idx, "Unknown")
                    ),
                })
            else:
                if not valid_tool:
                    print(
                        f"    ⚠ no parseable tool call this turn — ramp "
                        f"may stall. Use --continue-on-no-tool to force "
                        f"progression (club-3090 #255).",
                        flush=True,
                    )
                    break
            print(
                f"    ttft={metrics['ttft_ms']:.0f} ms  "
                f"prompt_tok={metrics['prompt_tokens']}  "
                f"completion_tok={metrics['completion_tokens']}  "
                f"decode_tps="
                f"{metrics['decode_tps']:.1f}" if metrics['decode_tps']
                else (
                    f"    ttft={metrics['ttft_ms']}  "
                    f"prompt_tok={metrics['prompt_tokens']}  "
                    f"completion_tok={metrics['completion_tokens']}  "
                    f"decode_tps=N/A"
                ),
                flush=True,
            )
    return turns


def _summarize(all_turns: list[dict]) -> dict:
    """Compute summary stats across all sessions."""
    # Per-session ramp analysis: prompt_tokens growth rate, ttft growth.
    sessions: dict[int, list[dict]] = {}
    for t in all_turns:
        sessions.setdefault(t["session"], []).append(t)
    for s in sessions.values():
        s.sort(key=lambda t: t["turn"])

    # Aggregate metrics.
    successful = [
        t for t in all_turns
        if t.get("error") is None and (t.get("completion_tokens") or 0) > 0
    ]
    silent_empty_count = sum(1 for t in all_turns if t.get("silent_empty"))
    malformed_args_count = sum(
        1 for t in all_turns if t.get("malformed_tool_args")
    )
    errors = [t for t in all_turns if t.get("error")]
    if successful:
        ttfts = [t["ttft_ms"] for t in successful if t.get("ttft_ms")]
        decode_tps_vals = [
            t["decode_tps"] for t in successful if t.get("decode_tps")
        ]
        prompt_toks = [
            t["prompt_tokens"] for t in successful if t.get("prompt_tokens")
        ]
        summary = {
            "total_turns": len(all_turns),
            "successful_turns": len(successful),
            "silent_empty_turns": silent_empty_count,
            "malformed_tool_args_turns": malformed_args_count,
            "error_turns": len(errors),
            "ttft_p50_ms": statistics.median(ttfts) if ttfts else None,
            "ttft_p95_ms": (
                statistics.quantiles(ttfts, n=20)[18]
                if len(ttfts) >= 5 else None
            ),
            "decode_tps_p50": (
                statistics.median(decode_tps_vals)
                if decode_tps_vals else None
            ),
            "prompt_tokens_max": max(prompt_toks) if prompt_toks else None,
            "prompt_tokens_min": min(prompt_toks) if prompt_toks else None,
        }
        # TTFT-growth analysis: first warm turn vs final turn (exclude
        # cold start — club-3090's 30134970 fix).
        warm_turns_per_session = [s[1:] for s in sessions.values() if len(s) >= 2]
        if warm_turns_per_session:
            growths = []
            for warm in warm_turns_per_session:
                first_ttft = warm[0].get("ttft_ms")
                last_ttft = warm[-1].get("ttft_ms")
                if first_ttft and last_ttft:
                    growths.append(last_ttft - first_ttft)
            if growths:
                summary["ttft_growth_ms_p50"] = statistics.median(growths)
    else:
        summary = {
            "total_turns": len(all_turns),
            "successful_turns": 0,
            "silent_empty_turns": silent_empty_count,
            "malformed_tool_args_turns": malformed_args_count,
            "error_turns": len(errors),
            "note": "no successful turns — endpoint or tool-parser broken",
        }
    return summary


def _print_table(all_turns: list[dict]) -> None:
    print()
    print(
        "  turn  session  prompt_tok  ttft_ms  decode_tps  finish_reason  "
        "silent_empty  error"
    )
    print("  " + "-" * 100)
    for t in sorted(all_turns, key=lambda x: (x["session"], x["turn"])):
        pt = t.get("prompt_tokens")
        pt_s = f"{pt:>8}" if pt is not None else "    N/A"
        tt = t.get("ttft_ms")
        tt_s = f"{tt:6.0f}" if tt is not None else "   N/A"
        dt = t.get("decode_tps")
        dt_s = f"{dt:7.1f}" if dt is not None else "    N/A"
        fr = t.get("finish_reason") or "-"
        se = "Y" if t.get("silent_empty") else "."
        err = (t.get("error") or "")[:35]
        print(
            f"  {t['turn']:>4}  {t['session']:>7}  {pt_s}  "
            f"{tt_s}    {dt_s}    {fr:>11}  {se:>11}  {err}"
        )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Multi-turn agentic context-depth bench. Reports TTFT growth "
            "and detects silent-empty turns (Cliff 2b signature)."
        ),
    )
    p.add_argument("--url", default=DEFAULT_URL,
                   help=f"vLLM endpoint /v1 base URL (default: {DEFAULT_URL})")
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help=f"served_model_name (default: {DEFAULT_MODEL})")
    p.add_argument("--api-key", default=DEFAULT_API_KEY,
                   help="bearer token (default from $VLLM_API_KEY or "
                        "'genesis-local')")
    p.add_argument("--turns", type=int, default=8,
                   help="turns per session (default: 8)")
    p.add_argument("--sessions", type=int, default=1,
                   help="independent sessions (default: 1)")
    p.add_argument("--max-tokens", type=int, default=150,
                   help="max_tokens per turn (default: 150 — keep small "
                        "so the bench measures TTFT, not decode time)")
    p.add_argument("--temperature", type=float, default=0.3,
                   help="sampling temperature (default: 0.3)")
    p.add_argument("--request-timeout", type=float, default=180.0,
                   help="per-turn request timeout in seconds (default: 180)")
    p.add_argument("--continue-on-no-tool", action="store_true",
                   help="when a turn returns no parseable tool call, "
                        "inject a synthetic tool result and keep ramping "
                        "(club-3090 #255 mitigation)")
    p.add_argument("--out", type=str, default=None,
                   help="write full results to JSON path")
    return p.parse_args()


async def _amain() -> int:
    args = _parse_args()
    print(f"# Agentic context-depth bench")
    print(f"# URL: {args.url}  model: {args.model}")
    print(f"# turns/session={args.turns}  sessions={args.sessions}")
    print(f"# max_tokens={args.max_tokens}  temp={args.temperature}")
    print()

    all_turns: list[dict] = []
    for s_idx in range(1, args.sessions + 1):
        print(f"== session {s_idx}/{args.sessions} ==")
        turns = await run_session(args, s_idx)
        all_turns.extend(turns)
        print()

    _print_table(all_turns)
    summary = _summarize(all_turns)
    print()
    print("# Summary")
    for k, v in summary.items():
        if isinstance(v, float):
            print(f"  {k}: {v:.2f}")
        else:
            print(f"  {k}: {v}")

    if summary.get("silent_empty_turns", 0) > 0:
        print()
        print(
            "  ⚠ silent-empty turns detected. This is the Cliff 2b "
            "signature on single-card vLLM at >25K accumulated context, "
            "or qwen3_coder × MTP arg-corruption (club-3090 #178). "
            "Re-run with `--continue-on-no-tool` to characterize the "
            "downstream context-depth shape."
        )

    if args.out:
        out = {
            "schema": "genesis-bench-agentic-v1",
            "captured_at": _dt.datetime.now().isoformat(),
            "endpoint": {
                "url": args.url,
                "model": args.model,
            },
            "config": {
                "turns": args.turns,
                "sessions": args.sessions,
                "max_tokens": args.max_tokens,
                "temperature": args.temperature,
                "continue_on_no_tool": args.continue_on_no_tool,
            },
            "summary": summary,
            "turns": all_turns,
        }
        out_path = args.out
        with open(out_path, "w") as f:
            json.dump(out, f, indent=2, default=str)
        print()
        print(f"# Wrote {out_path}")
    return 0 if summary.get("successful_turns", 0) > 0 else 1


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    sys.exit(main())
