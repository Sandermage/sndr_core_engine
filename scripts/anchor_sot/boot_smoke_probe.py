#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Runtime boot-smoke probe for a single served model — the *dynamic* half of
the pin-bump gate.

The Phase-4 anchor-SoT tools (rebuild_pin / bump_preflight / new_pin_check) are
all **static**: they diff anchors, retire/version-gate state, dependency edges
and perf-landmines between two pin manifests. They cannot catch a *runtime* boot
regression — e.g. dev672 forcing ``disable_chunked_mm_input`` for Gemma-4, which
made G4_09's 2048 SWA-prefill clamp violate the new ``max_num_batched_tokens >=
max_tokens_per_mm_item`` assert (boot ValueError, yet Genesis apply=failed=0).

This probe closes that gap: point it at a freshly-booted engine and it checks
coherent generation + (optionally) a streaming tool-call. ``fleet_boot_smoke.sh``
runs it per model across the fleet on a candidate pin.

Exit 0 = PASS, non-zero = FAIL (machine-checkable in the fleet gate).
"""
from __future__ import annotations

import argparse
import json
import urllib.request


def _chat(base_url: str, api_key: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _smoke(base_url: str, api_key: str, model: str, timeout: float) -> tuple[bool, str]:
    """Coherent single-turn generation. reasoning-parser models route thinking to
    reasoning_content, so give a real token budget and accept a stop finish."""
    try:
        d = _chat(base_url, api_key, {
            "model": model,
            "messages": [{"role": "user", "content": "What is the capital of France? Reply with just the city name."}],
            "max_tokens": 256, "temperature": 0,
        }, timeout)
    except Exception as e:  # noqa: BLE001
        return False, f"smoke request failed: {e}"
    c = d["choices"][0]
    content = (c["message"].get("content") or "").strip()
    finish = c.get("finish_reason")
    # PASS = the engine produced a terminated response (content or a clean stop).
    # A block-diffusion model may return empty content but a valid stop; we accept
    # finish=stop as coherence-of-serving (tool-call below exercises real gen).
    ok = finish in ("stop", "length") and (bool(content) or finish == "stop")
    return ok, f"finish={finish} content={content[:60]!r}"


def _toolcall(base_url: str, api_key: str, model: str, timeout: float) -> tuple[bool, str]:
    """Streaming-parser tool-call: the model must emit a get_weather tool_call
    with a parseable city arg and NOT leak the call onto the content channel."""
    tools = [{"type": "function", "function": {
        "name": "get_weather", "description": "Get current weather for a city",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
    }}]
    try:
        d = _chat(base_url, api_key, {
            "model": model,
            "messages": [{"role": "user", "content": "What is the weather in Berlin right now?"}],
            "tools": tools, "tool_choice": "auto", "max_tokens": 200, "temperature": 0,
        }, timeout)
    except Exception as e:  # noqa: BLE001
        return False, f"tool-call request failed: {e}"
    c = d["choices"][0]
    m = c["message"]
    tc = m.get("tool_calls")
    if not tc:
        return False, f"NO tool_call (finish={c.get('finish_reason')}, content={(m.get('content') or '')[:60]!r})"
    fn = tc[0]["function"]
    leaked = bool((m.get("content") or "").strip())
    # Validate the arguments the docstring promises: a streaming-parser
    # regression can capture the name but drop/garble the JSON body, which the
    # old name-only check passed. Require a parseable, non-empty city arg.
    try:
        args = json.loads(fn.get("arguments") or "")
    except (ValueError, TypeError):
        return False, f"tool_call arguments not valid JSON: {(fn.get('arguments') or '')[:60]!r}"
    city = args.get("city") if isinstance(args, dict) else None
    ok = fn["name"] == "get_weather" and isinstance(city, str) and bool(city.strip()) and not leaked
    return ok, f"tool={fn['name']} city={city!r} leak={leaked}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Runtime boot-smoke probe for one served model.")
    ap.add_argument("--base-url", default="http://127.0.0.1:8102")
    ap.add_argument("--api-key", default="genesis-local")
    ap.add_argument("--model", required=True, help="served-model-name")
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--skip-toolcall", action="store_true",
                    help="skip the tool-call check (e.g. a throughput preset with no --tool-call-parser)")
    a = ap.parse_args(argv)

    ok_s, msg_s = _smoke(a.base_url, a.api_key, a.model, a.timeout)
    print(f"  smoke: {'PASS' if ok_s else 'FAIL'} — {msg_s}")
    ok_t, msg_t = (True, "skipped") if a.skip_toolcall else _toolcall(a.base_url, a.api_key, a.model, a.timeout)
    print(f"  tool:  {'PASS' if ok_t else 'FAIL'} — {msg_t}")
    return 0 if (ok_s and ok_t) else 1


if __name__ == "__main__":
    raise SystemExit(main())
