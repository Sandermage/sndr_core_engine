#!/usr/bin/env python3
"""OpenAI-compatible smoke test for the Genesis PROD endpoint.

Checks the key response contracts:

  1. HTTP 200 on POST /v1/chat/completions.
  2. choice.finish_reason in {stop, length}.
  3. (optional, --assert-content flag) message.content is non-empty,
     even on short max_tokens. This is the P0-3 audit contract —
     reasoning-mode models (Qwen3 thinking) can burn budget on
     reasoning and return content=null. The smoke catches that class
     of regressions.

Usage:

    python3 tools/openai_smoke.py \\
        --host http://127.0.0.1:8101 \\
        --api-key genesis-local \\
        --model qwen3.6-27b \\
        --max-tokens 128 \\
        --assert-content

Exit codes:
  0  all asserts passed
  1  http error / unexpected response shape
  2  assert-content failure (content empty)
  3  finish_reason unexpected (not stop/length)
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="http://127.0.0.1:8101")
    parser.add_argument("--api-key", default="genesis-local")
    parser.add_argument("--model", default="qwen3.6-27b")
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument(
        "--prompt", default="Say OK",
        help="user message",
    )
    parser.add_argument(
        "--assert-content", action="store_true",
        help="require message.content to be non-empty (P0-3 contract)",
    )
    parser.add_argument(
        "--enable-thinking", default=None,
        help=(
            "Pass chat_template_kwargs.enable_thinking explicitly. "
            "Values: 'true', 'false'. Unset — model default."
        ),
    )
    parser.add_argument(
        "--timeout", type=float, default=60.0,
        help="HTTP timeout in seconds",
    )
    parser.add_argument("--json", action="store_true",
                          help="emit parsed JSON of the response")
    args = parser.parse_args()

    body: dict = {
        "model": args.model,
        "messages": [{"role": "user", "content": args.prompt}],
        "max_tokens": args.max_tokens,
        "temperature": 0,
    }
    if args.enable_thinking is not None:
        flag = args.enable_thinking.strip().lower()
        body["chat_template_kwargs"] = {
            "enable_thinking": flag in ("1", "true", "yes", "on"),
        }

    req = urllib.request.Request(
        f"{args.host.rstrip('/')}/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {args.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"http error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))

    try:
        choice = payload["choices"][0]
        finish = choice.get("finish_reason")
        message = choice.get("message", {}) or {}
        content = message.get("content")
        reasoning = message.get("reasoning") or ""
        usage = payload.get("usage", {})
    except (KeyError, IndexError, TypeError) as e:
        print(f"unexpected response shape: {e}", file=sys.stderr)
        return 1

    print(
        f"finish_reason={finish}  "
        f"content_chars={len(content) if content else 0}  "
        f"reasoning_chars={len(reasoning)}  "
        f"completion_tokens={usage.get('completion_tokens')}"
    )

    if finish not in ("stop", "length", "tool_calls"):
        print(
            f"unexpected finish_reason={finish!r}", file=sys.stderr,
        )
        return 3

    if args.assert_content and not content:
        print(
            f"assert-content failed: message.content empty "
            f"(reasoning_chars={len(reasoning)}; finish={finish}). "
            f"For Qwen3-style models pass "
            f"chat_template_kwargs.enable_thinking=false OR set "
            f"GENESIS_PN16_CLASSIFIER_MAX_TOKENS so PN16 V7 "
            f"caps max_tokens on short-answer requests.",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
