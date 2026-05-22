# `sndr memory explain` — MVP design

**Дата:** 2026-05-12
**Owner:** sandermage
**Source:** PROJECT_ROADMAP_V2_REVIEW_NOTES §P1.2
**Status:** draft (design only; implementation in roadmap Phase 4.7)

---

## 0. Зачем именно MVP

Roadmap до этого момента ставил `sndr memory explain` в P3 research-уровень.
Но проект ориентирован на A5000/3090, long context, hybrid GDN, TQ k8v4,
DFlash, MTP — все эти штуки делятся на "запустится" и "OOM в profile_run"
по достаточно предсказуемой математике.

Пользователю нужно ответить на простой вопрос:

> "Запустится ли prod-35b на моих 2× A5000 с context=64k и max_num_seqs=4?
>  Сколько VRAM съест? Где OOM ближайший?"

И MVP может ответить **до запуска**. Это превращает проект из "набор
patches" в "engine который умеет объяснять собственное поведение".

MVP ≠ research. MVP даёт честную оценку с **explicit uncertainty bands**,
без cudagraph fine-tracing и без profile_run перехвата. Точность ±10-15%
на VRAM, достаточно чтобы определить "точно влезет", "пограничный случай",
"гарантированно OOM".

---

## 1. CLI surface

```bash
# Mode 1 — explain a known preset
sndr memory explain --profile prod-35b

# Mode 2 — explain a composed triplet
sndr memory explain \
  --model qwen3.6-35b-a3b-fp8 \
  --hardware a5000-2x-24gbvram-16cpu-128gbram \
  --ctx 64000 \
  --seqs 4 \
  --tp 2

# Mode 3 — sweep across context sizes
sndr memory explain --profile prod-35b --ctx-sweep 16k,32k,64k,131k,320k

# Mode 4 — JSON for tooling
sndr memory explain --profile prod-35b --json
```

---

## 2. Memory model (MVP scope)

The MVP estimates the following components in MiB **per GPU**:

| Component | Formula (simplified) | Source of params |
|---|---|---|
| Weights | `model_params * bytes_per_weight / tp` | model.capabilities.quantization + dtype |
| KV cache | `n_layers * 2 * n_kv_heads * head_dim * seq_len * batch * kv_bytes / tp` | model.config + capabilities.kv_cache_dtype |
| Activations | `batch * seq_len * hidden_dim * activation_bytes * activation_factor` | activation_factor heuristic (3-5× for chunked prefill) |
| Cudagraph reserve | `cudagraph_size_mib_per_seq * max_num_seqs` | Wave 9 measured per-arch: 50-150 MiB/seq |
| Quantization overhead | TQ k8v4: ~400 MiB; AutoRound: ~200 MiB; FP8 native: 0 | model.quantization + model.capabilities.kv_cache_dtype |
| Fragmentation reserve | `max(0.05 * total_vram, 1024)` | conservative heuristic |
| Drafter (DFlash) | drafter weights / tp + drafter KV | spec_decode.method == 'dflash' |

**Output:**

```
prod-35b on a5000-2x-24gbvram-16cpu-128gbram, ctx=320000, seqs=2, tp=2

  Per-GPU VRAM budget: 24576 MiB (24 GB physical, ≥22000 MiB usable)

  Estimated usage per GPU:
    weights (FP8, qwen3.6-35b-a3b)        14200 MiB  ±5%
    KV cache (TQ k8v4)                     5800 MiB  ±10%
    cudagraph reserve (FULL_AND_PIECEWISE)  200 MiB  ±20%
    activations (chunked prefill 4096)     1200 MiB  ±25%
    quantization overhead                   400 MiB  ±10%
    drafter (n/a — MTP integrated)            0 MiB
    fragmentation reserve                   800 MiB  fixed
    ─────────────────────────────────────────────────
    TOTAL (median estimate)               22600 MiB
    TOTAL (p95 estimate)                  24400 MiB  ← within budget
    TOTAL (worst-case)                    25800 MiB  ← above budget, OOM risk

  Host RAM:  2.4 GiB used out of 128 GiB available  ✓
  Docker shm: 8 GiB configured (no warning)         ✓

  Verdict: TIGHT — within p95 estimate, but worst-case exceeds by 1.2 GiB.
  Recommend: reduce ctx to 280000 OR drop max_num_seqs to 1 for safety margin.

  Closest OOM cliff: max_num_seqs=3 at ctx≥160000 (estimated p95 24800 MiB).
```

---

## 3. Calibration data

MVP ships with `tools/memory_explain_calibration/v1.yaml`:

```yaml
schema_version: 1
calibration_set: "wave9-2x-a5000-2026-05"
maintainer: sandermage

# Per-architecture cudagraph reserve (MiB per active seq, FULL_AND_PIECEWISE)
cudagraph_reserve_per_seq:
  hybrid_gdn_moe: 120
  dense: 50
  hybrid_mamba: 80

# Per-quantization activation overhead multiplier (1.0 = baseline)
activation_factor:
  fp8: 1.0
  int4_autoround: 1.15
  none: 1.0

# Per-KV-cache-dtype overhead (MiB constant)
kv_overhead:
  fp16: 0
  fp8_e5m2: 0
  turboquant_k8v4: 400

# Drafter delta for DFlash (MiB per GPU after TP split)
dflash_drafter_overhead_mib:
  "Qwen3.6-27B-DFlash": 4500
  "Qwen3.6-35B-A3B-DFlash": 6200
```

Calibration data is **bench-derived**, not assumed. Each entry has
provenance — which bench run produced which number. Re-bench updates
the file via PR + evidence ledger entry.

---

## 4. Honesty about uncertainty

MVP **does NOT** claim more accuracy than calibration provides. Every
component has explicit uncertainty band. Total reports:

- median estimate
- p95 estimate (statistically reasonable upper bound)
- worst-case (max calibration deviation × all components)

If `worst-case > vram_budget`, verdict is `OOM RISK`. If `p95 >
vram_budget`, verdict is `TIGHT`. If `p95 ≤ vram_budget`, verdict is
`SAFE`.

**Never reports a single point estimate without uncertainty.** That's
the difference between a useful tool and a misleading tool.

---

## 5. What MVP does NOT do (deferred to P3)

- profile_run live capture (would catch fragmentation pattern but
  requires GPU access at explain-time — that's full research, not MVP).
- per-layer attention map sizing (would help long-ctx prediction but
  needs model graph trace).
- cudagraph capture warmup overhead delta (transient, not OOM-relevant).
- swap/pinned memory dynamic prediction (host RAM stress under heavy
  load — out of scope until tier-aware cache lands).

---

## 6. Roadmap placement

Phase 4.7 (Day 13, P1, after Phase 4.5 RuntimeCommandSpec):

1. `vllm/sndr_core/memory/explain.py` — estimator logic.
2. `tools/memory_explain_calibration/v1.yaml` — seeded with current
   Wave 9 bench data.
3. `vllm/sndr_core/cli/memory.py` — CLI surface.
4. Tests: 30+ unit tests covering all 11 V2 aliases against known-good
   bench-derived expected values (±tolerance).

**Acceptance:**

```bash
sndr memory explain --profile prod-35b --json | \
  jq -e '.verdict == "SAFE" and .total_p95_mib < 24576 * 2'
```

For all 11 aliases, the verdict matches what we know from existing
benches (prod-35b → SAFE, long-ctx-27b → TIGHT at ctx=280k, etc.).

---

## 7. Связи

- Roadmap Phase 4.7 (new, P1).
- Implements: PROJECT_ROADMAP_V2_REVIEW_NOTES §P1.2.
- Depends on: Phase 4.5 (RuntimeCommandSpec) — explain consumes
  composed config the same way emitters do.
- Mitigates: R7 (bench reproducibility) — explain output goes into bench
  result JSON as a "pre-flight estimate vs actual" delta.
