#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Gemma4 tool-call bench — 7 edge cases × N runs.

NOTE on Connection: close — vLLM may re-use ToolParser instances across
requests on the same HTTP keep-alive socket, which causes a state leak
in the gemma4 PR #42237 streaming path (case 5 nested-object loses the
trailing `"}` two chars on runs 2..N). This harness sends
`Connection: close` to force a fresh parser per request. Operators
deploying gemma4 PROD agents SHOULD do the same until upstream fixes
the parser reset condition.


Tests Gemma4 tool calling correctness with:
  1. Simple single tool call (warm-up)
  2. Thinking-then-tool (CoT preamble + tool call)
  3. Multi-tool sequential (call A then call B based on A's hypothetical result)
  4. String args with special chars (apostrophes, commas)
  5. Nested object args
  6. Mixed numeric + boolean args
  7. Two tools in one response

Pass criterion: response.choices[0].message.tool_calls has the expected
function name AND parseable JSON arguments AND finish_reason == "tool_calls".

Usage:
  python3 g4_tool_bench.py --port 8102 --model gemma4-31b-tq-mtp-structured-k4 --runs 1
"""
import argparse
import json
import sys
import time
import urllib.request


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a city",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"},
                    "units": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "description": "Temperature units",
                    },
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluate a math expression",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string"},
                    "precision": {"type": "integer"},
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_event",
            "description": "Create a calendar event",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "date": {"type": "string"},
                    "attendees": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "is_all_day": {"type": "boolean"},
                    "details": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string"},
                            "duration_min": {"type": "integer"},
                        },
                    },
                },
                "required": ["title", "date"],
            },
        },
    },
]


CASES = [
    {
        "id": "1_simple_single",
        "desc": "Simple single tool call (warm-up baseline)",
        "user": "What's the weather in Tokyo?",
        "expect_fn": "get_weather",
        "expect_args_keys": ["city"],
    },
    {
        "id": "2_thinking_then_tool",
        "desc": "CoT thinking preamble + tool call (Class 13 residual edge)",
        "user": (
            "I need to plan an outdoor picnic in Berlin tomorrow. "
            "Think step by step about what info you need, then check the weather."
        ),
        "expect_fn": "get_weather",
        "expect_args_keys": ["city"],
    },
    {
        "id": "3_multi_tool_seq",
        "desc": "Two distinct tools needed (weather then calc temp diff)",
        "user": (
            "Check the weather in Paris in celsius, then calculate "
            "the difference between 30 and that temperature. Start with weather."
        ),
        "expect_fn": "get_weather",
        "expect_args_keys": ["city", "units"],
    },
    {
        "id": "4_string_special_chars",
        "desc": "String args with apostrophe + comma",
        "user": (
            "Create a calendar event titled \"Sarah's Birthday, Take 2\" "
            "for 2026-06-15. No attendees needed."
        ),
        "expect_fn": "create_event",
        "expect_args_keys": ["title", "date"],
    },
    {
        "id": "5_nested_object",
        "desc": "Nested object arg (details.location + details.duration_min)",
        "user": (
            "Create a calendar event 'Team Standup' for 2026-06-01 "
            "with location 'Conference Room A' and duration 30 minutes."
        ),
        "expect_fn": "create_event",
        "expect_args_keys": ["title", "date"],
    },
    {
        "id": "6_mixed_numeric_bool",
        "desc": "Mixed numeric + boolean args",
        "user": (
            "Calculate 22/7 with precision 4 decimal places."
        ),
        "expect_fn": "calculate",
        "expect_args_keys": ["expression", "precision"],
    },
    {
        "id": "7_two_tools_one_resp",
        "desc": "Two tools, model may emit both in one response",
        "user": (
            "Get the weather in London AND in Madrid, both in celsius. "
            "Issue both tool calls at once."
        ),
        "expect_fn": "get_weather",
        "expect_args_keys": ["city"],
    },
]


def post_json(url, payload, timeout=180):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer genesis-local",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as f:
        return json.loads(f.read().decode("utf-8"))


def evaluate(case, resp):
    """Return (passed, reason, summary_dict)."""
    choices = resp.get("choices") or []
    if not choices:
        return False, "no choices", {"reason": "no_choices"}
    msg = choices[0].get("message", {}) or {}
    finish = choices[0].get("finish_reason")
    tcs = msg.get("tool_calls") or []
    content = msg.get("content") or ""

    if not tcs:
        return False, f"no tool_calls (finish={finish}, content_head={content[:80]!r})", {
            "reason": "no_tool_calls",
            "finish": finish,
            "content_head": content[:200],
        }

    tc0 = tcs[0]
    fn_name = (tc0.get("function") or {}).get("name", "")
    if fn_name != case["expect_fn"]:
        return False, f"wrong fn: got {fn_name!r} expected {case['expect_fn']!r}", {
            "reason": "wrong_fn",
            "got_fn": fn_name,
        }

    args_str = (tc0.get("function") or {}).get("arguments", "")
    try:
        args = json.loads(args_str)
    except Exception as e:
        return False, f"args not valid JSON: {e}; head={args_str[:80]!r}", {
            "reason": "invalid_json_args",
            "args_head": args_str[:200],
            "err": str(e),
        }

    missing = [k for k in case["expect_args_keys"] if k not in args]
    if missing:
        return False, f"missing keys: {missing}; got keys={list(args.keys())}", {
            "reason": "missing_keys",
            "missing": missing,
            "got_keys": list(args.keys()),
        }

    return True, f"OK fn={fn_name} keys={list(args.keys())}", {
        "fn": fn_name,
        "args_keys": list(args.keys()),
        "args": args,
        "n_tool_calls": len(tcs),
        "finish": finish,
    }


def run_case(host, port, model, case, max_tokens, temperature, top_p, top_k, seed=None, stream=False):
    url = f"http://{host}:{port}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": case["user"]}],
        "tools": TOOLS,
        "tool_choice": "auto",
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
    }
    if top_k is not None:
        payload["top_k"] = top_k
    if seed is not None:
        payload["seed"] = seed
    if stream:
        payload["stream"] = True
    t0 = time.perf_counter()
    if stream:
        # Streaming case — accumulate SSE deltas
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer genesis-local",
            },
        )
        tool_calls_accum = {}
        content_accum = ""
        finish = None
        with urllib.request.urlopen(req, timeout=180) as f:
            for line in f:
                line = line.decode("utf-8").strip()
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except Exception:
                    continue
                ch = (chunk.get("choices") or [{}])[0]
                delta = ch.get("delta", {}) or {}
                if delta.get("content"):
                    content_accum += delta["content"]
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    entry = tool_calls_accum.setdefault(idx, {
                        "id": "", "type": "function",
                        "function": {"name": "", "arguments": ""},
                    })
                    if tc.get("id"):
                        entry["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        entry["function"]["name"] = fn["name"]
                    if fn.get("arguments"):
                        entry["function"]["arguments"] += fn["arguments"]
                if ch.get("finish_reason"):
                    finish = ch["finish_reason"]
        t1 = time.perf_counter()
        resp = {"choices": [{
            "message": {
                "tool_calls": list(tool_calls_accum.values()),
                "content": content_accum,
            },
            "finish_reason": finish,
        }]}
        elapsed = t1 - t0
    else:
        resp = post_json(url, payload)
        t1 = time.perf_counter()
        elapsed = t1 - t0
    return resp, elapsed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=8102)
    ap.add_argument("--model", default="gemma4-31b-tq-mtp-structured-k4")
    ap.add_argument("--runs", type=int, default=1, help="repeats per case")
    ap.add_argument("--max-tokens", type=int, default=400)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--top-p", type=float, default=1.0)
    ap.add_argument("--top-k", type=int, default=1)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--stream", action="store_true",
                    help="Use streaming SSE path (exercises new parser code)")
    ap.add_argument("--output", default=None,
                    help="Save full results JSON")
    args = ap.parse_args()

    print(f"Bench: host={args.host}:{args.port} model={args.model} runs={args.runs}")
    print(f"Config: T={args.temperature} top_p={args.top_p} top_k={args.top_k} seed={args.seed} stream={args.stream}")
    print(f"Cases: {len(CASES)}")
    print("=" * 80)

    results = []
    passes_per_case = {}
    fails_per_case = {}
    total_pass = 0
    total = 0

    for case in CASES:
        passes_per_case[case["id"]] = 0
        fails_per_case[case["id"]] = []
        for run in range(args.runs):
            total += 1
            try:
                resp, elapsed = run_case(
                    args.host, args.port, args.model, case,
                    args.max_tokens, args.temperature, args.top_p,
                    args.top_k, args.seed, args.stream,
                )
                ok, reason, summary = evaluate(case, resp)
            except Exception as e:
                ok, reason, summary = False, f"exception: {e}", {"reason": "exception", "err": str(e)}
                elapsed = 0.0
            sym = "✓" if ok else "✗"
            print(f"  [{case['id']}] run {run+1}/{args.runs}: {sym} ({elapsed:.2f}s) — {reason}")
            results.append({
                "case": case["id"],
                "desc": case["desc"],
                "run": run + 1,
                "passed": ok,
                "reason": reason,
                "elapsed_s": round(elapsed, 3),
                "summary": summary,
            })
            if ok:
                passes_per_case[case["id"]] += 1
                total_pass += 1
            else:
                fails_per_case[case["id"]].append({"run": run + 1, "reason": reason, "summary": summary})

    print("=" * 80)
    print(f"\nSummary: {total_pass}/{total} passed ({100*total_pass/total:.1f}%)")
    print(f"Per case:")
    for case in CASES:
        p = passes_per_case[case["id"]]
        print(f"  [{case['id']}] {p}/{args.runs} — {case['desc']}")

    if args.output:
        with open(args.output, "w") as f:
            json.dump({
                "config": vars(args),
                "summary": {"total": total, "passed": total_pass, "rate": total_pass / total},
                "per_case": passes_per_case,
                "results": results,
                "fails": fails_per_case,
            }, f, indent=2)
        print(f"\nResults: {args.output}")


if __name__ == "__main__":
    sys.exit(main() or 0)
