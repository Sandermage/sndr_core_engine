#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline deterministic reproduction of the dev491 streaming tool-call leak.

Runs the FULL DelegatingParser.parse_delta chain (reasoning=qwen3 +
tool=qwen3_xml) on a synthetic Qwen3.6 model output, feeding deltas
token-by-token AND in MTP-K=3 chunks, printing per-delta what each parse_delta
emits (reasoning / content / tool_calls). No GPU — parsers are pure Python — so
the fix can be iterated offline. Run inside the dev491 container with the model
mounted at /models.
"""
from __future__ import annotations

import sys

MODEL = "/models/Qwen3.6-35B-A3B-FP8"

# Synthetic Qwen3.6 reasoning + tool-call output (the exact shape that leaked).
THINK = "Okay, the user wants the weather in Paris. I'll call get_weather."
TOOL = (
    "\n<tool_call>\n<function=get_weather>\n<parameter=city>\nParis\n"
    "</parameter>\n</function>\n</tool_call>"
)
FULL = f"{THINK}</think>{TOOL}"  # model emits reasoning, </think>, then tool XML


def _load_tokenizer():
    for path, attr in (
        ("vllm.transformers_utils.tokenizer", "get_tokenizer"),
        ("vllm.tokenizers", "get_tokenizer"),
    ):
        try:
            mod = __import__(path, fromlist=[attr])
            fn = getattr(mod, attr, None)
            if fn:
                return fn(MODEL, trust_remote_code=True)
        except Exception as e:
            print(f"[tok] {path}.{attr} failed: {type(e).__name__}: {str(e)[:80]}")
    # last resort: HF directly
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)


def _build_request(tok):
    from vllm.entrypoints.openai.chat_completion.protocol import (
        ChatCompletionRequest,
    )

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather for a city",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
    ]
    return ChatCompletionRequest(
        model="qwen3.6-35b-a3b",
        messages=[{"role": "user", "content": "weather in Paris?"}],
        tools=tools,
        tool_choice="auto",
        stream=True,
    )


def _summarize(dm) -> str:
    if dm is None:
        return "None"
    parts = []
    r = getattr(dm, "reasoning", None)
    c = getattr(dm, "content", None)
    tc = getattr(dm, "tool_calls", None)
    if r:
        parts.append(f"reasoning={r!r}")
    if c is not None and c != "":
        parts.append(f"CONTENT={c!r}")
    if tc:
        for t in tc:
            fn = getattr(t, "function", None)
            nm = getattr(fn, "name", None) if fn else None
            ar = getattr(fn, "arguments", None) if fn else None
            parts.append(f"TOOL_CALL(name={nm!r} args={ar!r})")
    return " | ".join(parts) if parts else "empty-delta"


def run(chunk: int, label: str):
    from vllm.parser.parser_manager import ParserManager

    tok = _load_tokenizer()
    req = _build_request(tok)
    ParserCls = ParserManager.get_parser(
        tool_parser_name="qwen3_xml",
        reasoning_parser_name="qwen3",
        enable_auto_tools=True,
    )
    parser = ParserCls(tok, req.tools)

    ids = tok.encode(FULL, add_special_tokens=False)
    print(f"\n===== {label} (chunk={chunk}, {len(ids)} tokens) =====")
    prev_text, prev_ids = "", []
    n_content, n_tool = 0, 0
    i = 0
    while i < len(ids):
        d_ids = ids[i : i + chunk]
        d_text = tok.decode(d_ids)
        cur_text = prev_text + d_text
        cur_ids = prev_ids + d_ids
        finished = (i + chunk) >= len(ids)
        try:
            dm = parser.parse_delta(
                d_text, d_ids, req, prompt_token_ids=None, finished=finished
            )
        except Exception as e:
            print(f"  [{i:3d}] EXC {type(e).__name__}: {str(e)[:90]}")
            dm = None
        s = _summarize(dm)
        if "CONTENT=" in s:
            n_content += 1
        if "TOOL_CALL" in s:
            n_tool += 1
        # only print interesting (tool/content) deltas to keep it readable
        if "CONTENT=" in s or "TOOL_CALL" in s:
            print(f"  [{i:3d}] delta={d_text!r:30s} -> {s}")
        prev_text, prev_ids = cur_text, cur_ids
        i += chunk
    print(f"  SUMMARY {label}: content-deltas={n_content}  tool_call-deltas={n_tool}")
    print(f"  VERDICT: {'BROKEN (XML leaked to content)' if n_tool == 0 else 'OK (tool_calls emitted)'}")
    return n_tool


def _apply_pn392():
    import os

    os.environ["GENESIS_ENABLE_PN392_QWEN3CODER_STREAMING_COALESCE"] = "1"
    from sndr.engines.vllm.patches.tool_parsing import (
        pn392_qwen3coder_streaming_coalesce as m,
    )

    status, reason = m.apply()
    print(f"[PN392] apply -> {status}: {reason[:90]}")
    return status == "applied"


def _apply_p107():
    import os

    # P107 default env name guess; apply() will gate itself.
    try:
        from sndr.engines.vllm.patches.serving import (
            p107_mtp_truncation_detector as m,
        )

        status, reason = m.apply()
        print(f"[P107] apply -> {status}: {reason[:90]}")
        return status == "applied"
    except Exception as e:
        print(f"[P107] apply failed: {type(e).__name__}: {str(e)[:80]}")
        return False


if __name__ == "__main__":
    import sys as _sys

    mode = _sys.argv[1] if len(_sys.argv) > 1 else "raw"
    if mode in ("pn392", "both"):
        _apply_pn392()
    if mode in ("p107", "both"):
        _apply_p107()
    print(f"\n##### MODE = {mode} #####")
    # K=1 (no MTP, token-by-token) and K=3 (MTP) — compare.
    t1 = run(1, "token-by-token (no MTP)")
    t3 = run(3, "MTP K=3 (3-token chunks)")
    sys.exit(0 if (t1 > 0 and t3 > 0) else 7)
