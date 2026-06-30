#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Reddit/localllama-style context-depth speed sweep for the live engine.

Separates PREFILL (prompt processing) from DECODE (token generation) by
streaming and timing time-to-first-token, then sweeps input size x content type
to expose the speed-degradation curve as context grows. Plus a small concurrency
sweep. Stdlib only (urllib) so it runs on the server against localhost (no LAN
latency polluting TTFT).
"""
import json
import os
import sys
import time
import urllib.request
import concurrent.futures as cf

# Env-overridable so this runs against any OpenAI-compatible engine without
# editing the file (defaults match the local 35B PROD on the rig).
URL = os.environ.get("GENESIS_BENCH_URL", "http://127.0.0.1:8102/v1") + "/chat/completions"
KEY = os.environ.get("GENESIS_BENCH_KEY", "genesis-local")
MODEL = os.environ.get("GENESIS_BENCH_MODEL", "qwen3.6-35b-a3b")

# ── content generators (rough ~3.6 chars/token; exact prompt_tokens read back) ──
_CODE = '''def process_batch(items, cfg):
    """Transform a batch with the given config; returns (ok, errors)."""
    ok, errors = [], []
    for i, item in enumerate(items):
        try:
            v = item["value"] * cfg.get("scale", 1.0)
            if v > cfg["threshold"]:
                ok.append({"idx": i, "out": round(v, 4), "tag": item.get("tag", "n/a")})
            else:
                errors.append((i, "below_threshold"))
        except KeyError as e:
            errors.append((i, f"missing:{e}"))
    return ok, errors

'''
_PROSE = ("The afternoon light fell across the workshop floor in long amber bars, "
          "and the old engineer traced the wiring diagram with a calloused finger, "
          "muttering about tolerances that no datasheet would ever admit to. "
          "Outside, the rain had started again, soft and insistent against the glass. ")
_STRUCT = '{"id": %d, "name": "node-%d", "metrics": {"tps": %d, "lat_ms": %d}, "ok": true}\n'


def make_prompt(kind, approx_tokens):
    chars = int(approx_tokens * 3.6)
    if kind == "code":
        body = (_CODE * (chars // len(_CODE) + 1))[:chars]
        ask = "\n\nSummarize what the code above does in one sentence."
    elif kind == "prose":
        body = (_PROSE * (chars // len(_PROSE) + 1))[:chars]
        ask = "\n\nIn one sentence, what is the mood of the passage above?"
    else:  # struct
        body = "".join(_STRUCT % (i, i, i % 250, i % 90) for i in range(chars // 70 + 1))[:chars]
        ask = "\n\nHow many records are above are there roughly? Answer with a number."
    return body + ask


DECODE = 256  # forced decode length so decode_tps is comparable across depths


def run_once(prompt, max_tokens=DECODE, think=False, timeout=1200, force_len=True):
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": True,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": think},
    }
    if force_len:
        # vLLM extensions: decode EXACTLY max_tokens regardless of natural EOS,
        # so the decode rate reflects per-token cost at this KV depth, not the
        # answer length. This is what makes the degradation curve clean.
        payload["ignore_eos"] = True
        payload["min_tokens"] = max_tokens
    req = urllib.request.Request(
        URL, data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    ttft = None
    last = t0
    ptoks = ctoks = 0
    text_first = ""
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except Exception:
                continue
            ch = obj.get("choices") or []
            if ch:
                delta = ch[0].get("delta", {})
                piece = delta.get("content") or delta.get("reasoning_content") or ""
                if piece and ttft is None:
                    ttft = time.perf_counter() - t0
                if piece:
                    last = time.perf_counter()
                    if len(text_first) < 80:
                        text_first += piece
            if obj.get("usage"):
                ptoks = obj["usage"].get("prompt_tokens", 0)
                ctoks = obj["usage"].get("completion_tokens", 0)
    total = time.perf_counter() - t0
    decode_t = max(last - (t0 + (ttft or 0)), 1e-6)
    return {
        "prompt_tokens": ptoks, "completion_tokens": ctoks,
        "ttft_s": round(ttft or total, 3),
        "prefill_tps": round(ptoks / (ttft or total), 1) if ptoks else 0,
        "decode_tps": round(max(ctoks - 1, 1) / decode_t, 1),
        "e2e_tps": round(ctoks / total, 1) if ctoks else 0,
        "total_s": round(total, 2),
        "sample": text_first.replace("\n", " ")[:60],
    }


def warmup():
    try:
        run_once("Say OK.", max_tokens=5)
    except Exception as e:
        print(f"warmup error: {e}")


def sweep():
    sizes = [512, 2048, 8192, 16384, 32768, 65536]
    kinds = ["code", "prose", "struct"]
    print("\n## Context-depth sweep (forced 256-token decode, temp=0, thinking=off)\n")
    print("| content | approx_in | prompt_tok | TTFT s | prefill tok/s | DECODE tok/s | e2e tok/s | total s |")
    print("|---|---|---|---|---|---|---|---|")
    rows = []
    for kind in kinds:
        for sz in sizes:
            try:
                r = run_once(make_prompt(kind, sz))
                r.update(kind=kind, approx=sz)
                rows.append(r)
                print(f"| {kind} | {sz} | {r['prompt_tokens']} | {r['ttft_s']} | "
                      f"{r['prefill_tps']} | **{r['decode_tps']}** | {r['e2e_tps']} | {r['total_s']} |")
                sys.stdout.flush()
            except Exception as e:
                print(f"| {kind} | {sz} | ERR | {str(e)[:40]} | | | | |")
                sys.stdout.flush()
    return rows


def conc_sweep():
    print("\n## Concurrency sweep (code, ~4k in, forced 256 decode) — max-num-seqs=2\n")
    print("| concurrency | agg tok/s | per-stream decode tok/s | mean TTFT s | wall s |")
    print("|---|---|---|---|---|")
    prompt = make_prompt("code", 4096)
    for conc in [1, 2, 4, 8]:
        t0 = time.perf_counter()
        with cf.ThreadPoolExecutor(max_workers=conc) as ex:
            res = list(ex.map(lambda _: run_once(prompt), range(conc)))
        wall = time.perf_counter() - t0
        per = sum(r["decode_tps"] for r in res) / len(res)
        agg = sum(r["completion_tokens"] for r in res) / wall
        ttft = sum(r["ttft_s"] for r in res) / len(res)
        print(f"| {conc} | {round(agg,1)} | {round(per,1)} | {round(ttft,2)} | {round(wall,2)} |")
        sys.stdout.flush()


if __name__ == "__main__":
    warmup()
    rows = sweep()
    conc_sweep()
    with open("/tmp/ctx_sweep_results.json", "w") as f:
        json.dump(rows, f, indent=2)
    print("\n(results JSON -> /tmp/ctx_sweep_results.json)")
