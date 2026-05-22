# 35B PROD — Composite Reference Report (2026-05-09)

Final reference bench for 35B PROD config after Wave 7 + Sprint 1 + Sprint 4
patch consolidation. Baseline for all subsequent A/B sweeps.

## Configuration

- Model: `qwen3.6-35b-a3b` (Qwen3.6-35B-A3B-FP8)
- vLLM: `0.20.2rc1.dev93+g51f22dcfd`
- Hardware: 2× RTX A5000 24 GiB (TP=2)
- Image: `vllm-genesis-pinned:dev93-2026-05-09`
- Container: `vllm-server-p82-sweep` (proven script `~/start_35b_p82_sweep.sh 0.3`)

### Engine flags

```
--max-model-len 320000 --max-num-seqs 2 --max-num-batched-tokens 4096
--dtype float16 --kv-cache-dtype turboquant_k8v4
--tool-call-parser qwen3_coder --reasoning-parser qwen3
--enable-chunked-prefill --disable-custom-all-reduce
--language-model-only --enable-auto-tool-choice
--speculative-config '{"method": "mtp", "num_speculative_tokens": 3}'
--no-scheduler-reserve-full-isl --performance-mode interactivity
--attention-config.flash_attn_version 2
--gpu-memory-utilization 0.9
```

### Genesis enabled patches (Wave 1–7 + Sprint 1)

P37, P58, P60, P60b, P61, P61b, P61c, P62, P64, P66, P67 (NUM_KV_SPLITS=48),
P68, P69, P70, P71, P72, P74, P81, P82 (threshold=0.3), P95, P99, P101, P107,
PN8, PN9, PN11, PN16 V8 (lazy reasoner, tool budget=200), PN17, PN19, PN52,
PN56, PN66, PN67, PN77, PN90.

### Notable Genesis env

```
GENESIS_P67_NUM_KV_SPLITS=48        # Sprint 1 winner (was 32)
GENESIS_PN16_TOOL_THINK_BUDGET=200  # V8 system-msg hint
GENESIS_PN16_CLASSIFIER_MAX_TOKENS=0
GENESIS_OBSERVABILITY=1
GENESIS_TQ_MAX_MODEL_LEN=320000
GENESIS_PROFILE_RUN_CAP_M=4096
```

### Notable engine env

```
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,max_split_size_mb:256
VLLM_FLOAT32_MATMUL_PRECISION=high
VLLM_MARLIN_USE_ATOMIC_ADD=1
VLLM_USE_FLASHINFER_SAMPLER=1
VLLM_USE_FUSED_MOE_GROUPED_TOPK=1
VLLM_MOE_USE_DEEP_GEMM=0
VLLM_USE_DEEP_GEMM=0
NCCL_P2P_DISABLE=1
CUDA_DEVICE_MAX_CONNECTIONS=8
```

## Results — composite

| Metric | Value | Sprint 1 ref (V8 baseline) | Δ vs Sprint 1 |
|---|---|---|---|
| **Tool-call (positive)** | **7/7 PASS** | 7/7 | identical |
| wall_TPS | **233.84** (CV 0.063) | 241.35 | -3.1% (within CV) |
| decode_TPOT_ms | 3.96 (CV 0.050) | 3.85 | +2.9% |
| TTFT_ms | 110.9 (CV 0.330) | 103.0 | +7.7% |
| Window accept_rate | 0.809 | 0.819 | -1.2% (within noise) |
| Multi-turn TTFT range | 134.7–148.1 ms | similar | stable |

**Verdict:** Numbers within Sprint 1 CV band (TPS noise envelope ±6.3%). No
regression vs Sprint 1 reference. Tool-call quality fully retained
(london_think + tokyo_think still PASS — V8 system-msg hint working).

## Tool-call breakdown (8/8 cases including denial)

All 7 positive `get_weather` cases passed across both no-think and think
modes. The denial case (negative — model correctly refuses to call tool)
also passed. **8/8 total** with no failures.

| Case | Thinking | Verdict |
|---|---|---|
| paris_no_think | False | PASS |
| tokyo_think | True | PASS |
| nyc_no_think | False | PASS |
| london_think | True | PASS |
| kyiv_no_think | False | PASS |
| multi_no_think | False | PASS |
| error_recovery | False | PASS |
| denial_no_think | False | PASS |

london_think — historically the boundary case fixed by PN16 V8 — remains
green on this PROD reference.

## Files

- `35b_final_reference_2026-05-09.json` — full machine-readable bench output
- `35b_final_reference_2026-05-09.md` — bench suite human-readable summary
- `COMPOSITE_REPORT_35B_2026-05-09.md` — this file (composite + context)

## Bench methodology

- Suite: `tools/genesis_bench_suite.py --quick`
- Tool-call: 8 cases, single-shot SSE, qwen3_coder parser
- Decode: 5 runs × 5 prompts × 1024 max_tokens (n=25 sample)
- Multi-turn: 5 turns sequential SSE
- Context probe: window-only (max=1K in quick mode; 320K capability proven
  in earlier Sprint 1 runs at decode_TPOT 3.85)

## Acceptance for "PROD reference"

This run replaces the Sprint 1 reference in
`vllm/sndr_core/model_configs/builtin/a5000-2x-35b-prod.yaml`'s
`reference_metrics` block? **No — keep Sprint 1 numbers.**

Reasoning: Sprint 1's 241.35 TPS is the upper bound (best-of-N at the
config landing day). This 233.84 is a single-bench re-validation that
proves the proven config still hits the target band. PROD YAML
reference_metrics should remain anchored to Sprint 1 to avoid drift
upward in the regression budget.

This composite is the **regression sentinel** — if any future sweep drops
below ~228 TPS (Sprint 1 minus 5.5%) the config has actually regressed and
needs root-cause investigation.
