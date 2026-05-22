# GDN/Mamba memory-allocation optimization landscape

**Date:** 2026-05-06 evening
**Trigger:** User pushback on lazy ROI analysis ("48 MiB save was conservative — during work we might find processes that give bigger wins; can study other projects' kernels including C++ code")

## Executive summary

Cross-project research found **two stackable optimization vectors**:

1. **Decode-side: vllm PR #41824 → PN79 backport** (in-place SSM state via cache-pool indexing). Eliminates per-decode-step gather/scatter copies (4.5–36 GiB cumulative fp32 traffic per multi-turn session per author claim). Orthogonal to PN59 (which is prefill-side).

2. **Prefill-side Phase A: Mamba2 ssd_combined model** (chunk-streaming pre-h ops). Currently PN59 streaming ONLY addresses Phase B (h-allocation) — Phase A still allocates full-T at ~775 MiB on T=64K. Mamba2 demonstrates how to make Phase A also chunk-iterative.

**PN59 alone fixes ~50% of Cliff 2b memory cliff** (Phase B 768 MiB out of total ~1543 MiB). Phase A streaming is the remaining 50%.

## Per-project findings

### 1. llama.cpp `ssm-scan.cu`
**Pattern:** register-resident state scan, zero per-token allocation.
- State loaded once from global to `regs[N]`; full token loop keeps state in registers.
- `b_h += b_k @ b_v` style updates happen entirely in register space.
- **Backportable?** No — would require fusing FLA's `fwd_h` + `fwd_o` into single kernel. Multi-week kernel rewrite.

### 2. SGLang Mamba/GDN
**Pattern:** in-place pool + cache-indexed kernel — kernel reads/writes directly into global state cache.
- `causal_conv1d_fn(... cache_indices, has_initial_state, conv_states)` — conv_states updated in-place.
- `MambaPool.alloc(need_size)` — slot-based memory pool with zero-init.
- **Caveat:** SGLang issue #20791 — under aggressive `no_buffer` reuse, FlashInfer in-place degraded accuracy 0.99 → 0.89. Triton path unaffected. Closed via PR #21861.
- **Backportable?** This pattern IS what vllm #41824 ports to vllm/FLA Triton path. Use that.

### 3. FLA upstream
- **RFC #485** (`memory_efficient` flag, sustcsonglin) — **OPEN, no PR**. Won't help short-term.
- **Recent merged PRs** (#703 KDA chunk lowerbound, #688 KDA fused bwd, #698 reduce H2D) — KDA-specific, none touch our `chunk_gated_delta_rule_fwd_h` allocation site.
- **Allocation confirmed** at `fla/ops/gated_delta_rule/chunk_h.py:750-759` (matches our pin's `vllm/model_executor/layers/fla/ops/chunk_delta_h.py:332-334`). PN59 already shrinks `h` to `WINDOW_NT`; FLA upstream has no equivalent.

### 4. vllm PR #41824 (in-place SSM state) ⭐ MOST ACTIONABLE
**Status:** OPEN, awaiting review (ZJY0516/vadiklyutiy/tdoublep).

**What it does:**
- Adds `ssm_state_indices`, `has_initial_state` params to `chunk_gated_delta_rule_fwd_kernel_h_blockdim64`
- 2 new constexprs: `IS_CONTINUOUS_BATCHING`, `HAS_INITIAL_STATE_MASK`
- 4 new strides: `stride_indices_seq`, `stride_has_initial_state`, etc.
- Removes gather (`initial_state = ssm_state[indices].contiguous()`) + scatter (`ssm_state[indices] = final_state`) from `gdn_linear_attn.py`
- Pass `ssm_state` + indices directly; kernel does in-place

**Memory eliminated:** initial/final state copy per call. Decode-step cumulative fp32 traffic 4.5–36 GiB depending on model size (Qwen3.5-0.8B → Qwen3.6-27B per author).

**Critical clarification:** #41824 does **NOT** eliminate the per-call `h = k.new_empty(B, NT, HV, K, V)` allocation in `chunk_gated_delta_rule_fwd_h`. That's PN59's territory. The two are orthogonal:
- PN59: kills `h` materialization (long-prefill peak)
- #41824: kills `initial_state`/`final_state` copies (decode steady-state allocator pressure)

### 5. Mamba2 `ssd_combined`
**Pattern:** chunk streaming with per-chunk-only intermediates — Phase A IS chunk-iterative.

```python
# mamba_ssm/ops/triton/ssd_combined.py:1005-1030
def mamba_chunk_scan_combined(x, dt, A, B, C, chunk_size, ...):
    dA_cumsum, dt_out = _chunk_cumsum_fwd(dt, A, chunk_size, ...)   # (B,H,nchunks,chunk_size)
    states = _chunk_state_fwd(B, x, dt, dA_cumsum, ...)              # per-chunk only
    states, final_states = _state_passing_fwd(states, dA_cumsum, ...)# stream chunk→chunk
    CB = _bmm_chunk_fwd(C, B, chunk_size)                            # per-chunk only
    out, out_x = _chunk_scan_fwd(CB, x, dt, dA_cumsum, C, B, states, ...)
```

States flow chunk→chunk via `_state_passing_fwd`; only per-chunk slabs materialize. **This is what FLA's Phase A SHOULD do** but doesn't — instead `chunk_local_cumsum`, `chunk_scaled_dot_kkt_fwd`, `solve_tril`, `recompute_w_u_fwd` all materialize full-T.

**Backportable?** Yes, but NEW kernel-level work. Estimate: 4-8h refactor — adapt FLA's chunk-decomposed Phase A to accept window slices, return window outputs.

## Phase A allocation breakdown (the missing 50% of Cliff 2b)

For 27B Hybrid GDN at T=64K, Phase A allocates:

| Buffer | Shape | Dtype | Size at T=64K |
|---|---|---|---|
| `g` (cumsum output) | (B, T, H) | bf16 | ~3 MiB |
| `A` (kkt output) | (B, NT, H, K, K) | **fp32** | **~390 MiB** |
| `w` (recompute_w) | (B, T, H, K) | bf16 | ~191 MiB |
| `u` (recompute_u) | (B, T, H, V) | bf16 | ~191 MiB |
| **Phase A total** | — | — | **~775 MiB** |

PN59 streaming reduces Phase B from 768 MiB → 3 MiB, but Phase A's 775 MiB persists. **Cliff 2b OOM at extreme T (>128K) is still possible.**

## Decision matrix

| Optimization | Effort | Win | Stacks with PN59? |
|---|---|---|---|
| **PN79 (vllm #41824 backport)** | 3-4h | DECODE: 4.5-36 GiB cumulative fp32 traffic eliminated | ✅ Orthogonal, fully stackable |
| **Phase A streaming (Mamba2-inspired)** | 4-8h | PREFILL Phase A: ~775 MiB → ~50 MiB at T=64K | ✅ Direct extension |
| **register-resident scan (llama.cpp)** | weeks | Unbounded peak win | ⚠️ Replaces PN59 entirely |
| **Pool h_w + v_new_w buffers** | 2-3h | Allocator-pressure (not peak) ~770 MiB churn → const | ✅ Within PN59 streaming |

## Recommended priority order

1. **Mem-trace instrumentation FIRST** — get empirical data on actual Phase A vs Phase B allocator pressure during real workloads. Implemented in this session as `GENESIS_PN59_MEM_TRACE_AGG=1`.

2. **PN79 backport (#41824)** — concrete diff exists, decode-side win, stackable. Highest ROI for known-finished work.

3. **Phase A streaming** — bigger architectural change, addresses PN59's "only HALF" gap. Worth doing after #41824 lands.

4. **Pool h_w/v_new_w** — internal-streaming optimization. May or may not show win per measurement (allocator caching might handle this already). Validate with mem-trace data first.

## What's been done in this session (foundational)

- ✅ `GENESIS_PN59_BYPASS_T_MULTIPLIER` env var (Phase D-light)
- ✅ `GENESIS_PN59_MEM_TRACE` + `GENESIS_PN59_MEM_TRACE_AGG` env vars + `get_mem_trace_summary()` API
- ✅ Tests for instrumentation (4 tests)
- ⏳ Empirical bench on 27B with mem-trace AGG enabled — pending sync + boot

## Sources

- [llama.cpp ssm-scan.cu](https://github.com/ggml-org/llama.cpp/blob/master/ggml/src/ggml-cuda/ssm-scan.cu)
- [vllm PR #41824](https://github.com/vllm-project/vllm/pull/41824)
- [FLA RFC #485](https://github.com/fla-org/flash-linear-attention/issues/485)
- [FLA chunk_h.py allocation site](https://github.com/fla-org/flash-linear-attention/blob/main/fla/ops/gated_delta_rule/chunk_h.py)
- [Mamba2 ssd_combined.py](https://github.com/state-spaces/mamba/blob/main/mamba_ssm/ops/triton/ssd_combined.py)
- [SGLang causal_conv1d.py](https://github.com/sgl-project/sglang/blob/main/python/sglang/srt/layers/attention/mamba/causal_conv1d.py)
- [SGLang MambaPool memory_pool.py](https://github.com/sgl-project/sglang/blob/main/python/sglang/srt/mem_cache/memory_pool.py)
- [SGLang issue #20791 no_buffer accuracy](https://github.com/sgl-project/sglang/issues/20791)
