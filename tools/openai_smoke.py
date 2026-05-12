#!/usr/bin/env python3
"""OpenAI-совместимый smoke-тест для Genesis PROD endpoint.

Проверяет ключевые контракты ответа:

  1. HTTP 200 на POST /v1/chat/completions.
  2. choice.finish_reason ∈ {stop, length}.
  3. (опционально, флаг --assert-content) message.content не пустой,
     даже при коротких max_tokens. Это аудитный контракт P0-3 — модели
     с reasoning-режимом (Qwen3 thinking) могут расходовать budget на
     reasoning и возвращать content=null. Smoke ловит этот класс
     regression'ов.

Использование:

    python3 tools/openai_smoke.py \\
        --host http://127.0.0.1:8101 \\
        --api-key genesis-local \\
        --model qwen3.6-27b \\
        --max-tokens 128 \\
        --assert-content

Exit codes:
  0  все ассерты прошли
  1  http error / unexpected response shape
  2  assert-content failure (content пустой)
  3  finish_reason неожиданный (не stop/length)
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
        help="user-сообщение",
    )
    parser.add_argument(
        "--assert-content", action="store_true",
        help="требовать message.content непустым (P0-3 контракт)",
    )
    parser.add_argument(
        "--enable-thinking", default=None,
        help=(
            "Передать chat_template_kwargs.enable_thinking явно. "
            "Значения: 'true', 'false'. Не задано — default модели."
        ),
    )
    parser.add_argument(
        "--timeout", type=float, default=60.0,
        help="HTTP timeout сек",
    )
    parser.add_argument("--json", action="store_true",
                          help="выводить parsed JSON ответа")
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
            f"assert-content failed: message.content пустой "
            f"(reasoning_chars={len(reasoning)}; finish={finish}). "
            f"Для Qwen3-style моделей передайте "
            f"chat_template_kwargs.enable_thinking=false ИЛИ установите "
            f"GENESIS_PN16_CLASSIFIER_MAX_TOKENS чтобы PN16 V7 "
            f"ограничил max_tokens на short-answer requests.",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
