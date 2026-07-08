# SPDX-License-Identifier: Apache-2.0
"""A tiny OpenAI-compatible completion helper for the memory engine's batch
LLM steps (reflection, and later fact-extraction).

Dependency-free (urllib, like `client.py`) so it works inside the daemon image
without pulling httpx into the memory core. It turns the running vLLM engine
(any OpenAI-compatible `/v1/chat/completions`) into the plain `(prompt) -> text`
callable the engine's `reflect()` expects. The engine stays model-agnostic; this
is the seam that binds it to whatever inference endpoint the daemon points at.
"""
from __future__ import annotations

import json
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


def make_openai_llm(
    base_url: str,
    *,
    api_key: str | None = None,
    model: str = "local",
    temperature: float = 0.3,
    max_tokens: int = 256,
    timeout: float = 60.0,
) -> Callable[[str], str]:
    """Build a ``(prompt) -> text`` callable that hits an OpenAI-compatible
    ``/v1/chat/completions`` at ``base_url``. Non-2xx / malformed replies return
    an empty string, so a reflection step degrades to "no insight" rather than
    raising inside the batch."""
    base = base_url.rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"

    def _call(prompt: str) -> str:
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(  # noqa: S310 — base_url is operator-configured
            f"{base}/chat/completions", data=body, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                payload = json.loads(resp.read().decode("utf-8"))
            return (payload["choices"][0]["message"]["content"] or "").strip()
        except Exception:  # noqa: BLE001 — batch step: degrade to "no insight"
            return ""

    return _call
