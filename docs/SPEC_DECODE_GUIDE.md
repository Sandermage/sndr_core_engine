# Speculative Decoding — Operator Guide

This guide explains the speculative-decoding methods available in Genesis and
when to use each one. All three options ship in our pinned vLLM build and are
selectable per-preset via standard vLLM `--speculative-config` or the Genesis
convenience flag for Suffix Decoding (P75).

## TL;DR — which method?

| Workload class | Recommended method | Why |
|---|---|---|
| Free-chat single-user, short prompts | **MTP K=3** (current default) | Highest TPS on our 35B FP8 / 27B INT4 stack — empirically validated 200+ TPS on 35B-multiconc |
| Tool-call agentic (repetitive context) | **Suffix Decoding** (P75) | +40-60% over strict-ngram; suffix tree handles arbitrary-length repeats |
| Mixed structured + free-chat | **MTP K=3** with K_001 OFF | K_001 NOT_SIGNIFICANT across 3 bench cycles; default K=3 is the empirical optimum |
| Long-context (>32K) | **Suffix Decoding** (P75) or MTP K=2 | Suffix tree's per-prompt locality beats fixed-K speculation; MTP K=2 trades fewer draft tokens for longer-context stability |
| Multi-conc throughput (8+ concurrent) | **MTP K=3** | Multi-conc TTFT regression hits suffix harder than MTP |

## Method 1: MTP (Multi-Token Prediction)

**Default for qwen3.6 production presets.** Uses the model's own auxiliary
MTP heads (trained at fine-tune time) to draft K tokens per step. vLLM's
`DraftModelProposer` orchestrates the draft generation + verification.

**Configuration**: enabled by default in all `prod-qwen3.6-*` presets via
`spec_decode: { method: mtp, num_speculative_tokens: 3 }` in the profile
YAML. The K value (`num_speculative_tokens`) is the launcher cap; the
actual K per step can be adjusted via K_001 (see below — but empirically
NOT useful on our workloads).

**Pros**:

- Trained at fine-tune — high acceptance rate (0.78-0.80 on qwen3.6-35b)
- No external dependency
- Composes with TurboQuant + Genesis spec-decode patches (P62, P67, etc.)

**Cons**:

- Requires model to ship with MTP heads (Qwen3.6 does; vanilla Qwen3 doesn't)
- K is a hyper-parameter — different optimum per workload
- Not adaptive — Genesis K_001 (DynamicProposer port of vllm#26504) was
  designed to fix this but **empirically NOT_SIGNIFICANT** across three
  independent bench cycles (see `evidence/bench/v11.2.0_k001_validation/`)

**Operator notes**:

- `GENESIS_ENABLE_PN90_PROBABILISTIC_DRAFT=1` is recommended; it switches
  the acceptance rule from argmax to `min(1, target_p / draft_p)` which
  tightens the math (closer to true speculative sampling). Already enabled
  in `prod-qwen3.6-35b-multiconc`.
- K=3 is the empirical optimum across both 27B-multiconc and 35B-multiconc
  on the current pin (`0.21.1rc1.dev354+g626fa9bba`). Don't change without
  re-benching.

## Method 2: Suffix Decoding (P75 → vllm#25784)

**Recommended for agentic / tool-call workloads with repetitive context.**
Ports vLLM PR #25784 (Aurick Qiao / Snowflake), which merged 2025-11-03
and is present in our pinned binary. Uses a per-prompt suffix tree to
generate draft tokens via branch-frequency lookup — no external drafter
model.

**Reference**: arxiv 2411.04975 (SuffixDecoding NeurIPS 2025 Spotlight),
[snowflakedb/ArcticInference](https://github.com/snowflakedb/ArcticInference).

**Enable via Genesis flag**:

```bash
# In your launch script env block:
-e GENESIS_ENABLE_P75_SUFFIX_DECODING=1 \
-e GENESIS_P75_TREE_DEPTH=24 \
-e GENESIS_P75_SPEC_FACTOR=2.0 \
-e GENESIS_P75_MIN_PROB=0.10
```

P75 auto-rewrites `speculative_config.method` from `ngram` to `suffix`
when the env flag is set. Equivalent to passing `--speculative-config
'{"method":"suffix",...}'` to `vllm serve` manually, but lets you keep
the same launch script template.

**Pros**:

- No drafter model — pure CPU suffix-tree lookup
- **Per-prompt** locality — handles tool-call repeats that fixed-K methods miss
- Dynamic K per step (no fixed `num_speculative_tokens` truncation)
- Cross-request response cache (FIFO eviction, bounded by
  `suffix_decoding_max_cached_requests`, default 10000)

**Cons**:

- Requires `pip install arctic-inference` in the container image (lazy
  import — failure is loud, falls back to ngram)
- CPU overhead — at very high concurrency the suffix-tree lookups can
  saturate the host CPU; profile before deploying
- Quality depends on prompt diversity — for highly varied prompts the
  suffix tree gives less leverage

**When NOT to use**:

- Highly diverse short prompts (free-chat with no repetition) — MTP wins
- Very high concurrency (>8) — CPU contention can outweigh draft gains

## Method 3: NGRAM (P70 + P77 + PN72 stack)

**Not recommended for production unless Suffix Decoding is unavailable.**
vLLM's stock ngram speculator using suffix-array matching on the prompt.
Genesis stack:

- **P70** auto-strict-ngram — enforces `prompt_lookup_min >= 8` to
  eliminate spurious tool-call acceptance (closes vllm#40875)
- **P77** adaptive K controller — EMA + hysteresis state machine,
  modulates K based on acceptance rate feedback (K ∈ {0, 1, 3, 5})
- **PN72** frequency-based post-filter — rejects drafts with first-token
  count < 4 in the last 1024 tokens (mirrors llama.cpp's
  `draft_min_sample_size`)

**When to use**:

- Pre-2025-11 vLLM pins (no Suffix Decoding available)
- Operator wants minimum dependencies (no `arctic-inference` install)
- Profiling Genesis spec-decode patches without changing the underlying
  draft method

**Empirical**: P70+P77+PN72 stack achieves ~75 tok/s on our strict-ngram
config — about half the win of Suffix Decoding on tool-call workloads.

## Method 4 (research): K_001 Dynamic K MTP — **default OFF, empirically NOT useful**

Genesis port of vllm#26504 (DynamicProposer). Per-seq SequenceState with
rolling acceptance-rate window (len=10), K hysteresis (avg_acc >=
threshold+0.05 → K++ up to launcher cap; avg_acc <= threshold-0.05 →
K-- down to MIN=1).

**Three independent bench cycles all NOT_SIGNIFICANT**:

| Bench | Δ wall_TPS | Welch t | p | Verdict |
|---|---:|---:|---:|---|
| 35B-multiconc quick (n=25) | -1.66% | -0.570 | 0.5688 | NOT_SIGNIFICANT |
| 27B-multiconc quick (n=25) | +0.21% | +0.088 | 0.9295 | NOT_SIGNIFICANT |
| 35B multi-turn 12×2 (n=24) | +1.40% | +0.169 | 0.8656 | NOT_SIGNIFICANT |
| 35B multi-turn late window (n=6) | +1.20% | +0.906 | 0.3651 | NOT_SIGNIFICANT |

**Default OFF is the empirically correct setting.** Don't enable without
re-benching against your specific workload AND verifying p < 0.05.

Evidence: [evidence/bench/v11.2.0_k001_validation/](../evidence/bench/v11.2.0_k001_validation/)

## How to switch between methods

### Switching MTP → Suffix Decoding

1. Add `-e GENESIS_ENABLE_P75_SUFFIX_DECODING=1` to your launch script.
2. Optionally tune `GENESIS_P75_TREE_DEPTH=24` / `SPEC_FACTOR=2.0` /
   `MIN_PROB=0.10`.
3. Verify `arctic_inference` is importable inside the container
   (`docker exec <name> python -c 'import arctic_inference'` — if it
   fails, P75 falls back to ngram and logs a WARNING).
4. Boot, bench against your previous MTP baseline (use
   `tools/genesis_bench_suite.py --quick` for short prompts +
   `tools/bench_multiturn_tps.py --turns 12 --sessions 2` for the
   agentic shape).

### Switching MTP → NGRAM (rare)

1. Edit your profile YAML's `spec_decode` block:
   `{ method: ngram, num_speculative_tokens: 3, prompt_lookup_max: 5 }`
2. Re-render launchers: `sndr profile render-launchers <profile_id>`.
3. Enable Genesis NGRAM stack: `GENESIS_ENABLE_P70_AUTO_STRICT_NGRAM=1`,
   `GENESIS_ENABLE_P77_ADAPTIVE_NGRAM_K=1`,
   `GENESIS_ENABLE_PN72_FREQUENCY_NGRAM_DRAFTER=1`.

## Bench reference (where to look)

- `evidence/bench/v11.2.0_k001_validation/` — K_001 falsification across
  3 cycles.
- `tools/genesis_bench_suite.py --quick` — single-prompt n=25 baseline.
- `tools/bench_multiturn_tps.py --turns 12 --sessions 2` — multi-turn
  TPS evolution (added v11.2.0+, K_001 multi-turn validation).
- `tools/bench_agentic.py --turns 12 --sessions 2` — agentic with
  tool-call enabled endpoint (requires `--tool-call-parser` in
  launch script).

## Future work

- **EAGLE-3 fusion** — vLLM-side infra ready since 2026-02
  (PRs #35029, #35040, Qwen3 PR #43132 active). Blocked on **Qwen3.6
  EAGLE-3 drafter checkpoint** (does not exist publicly yet). Genesis
  G4_71/G4_75 drafter-routing patches already prepare the model-side
  hook. Tracked in master plan Phase 7.
- **Mamba-3** — research-track. No vLLM serving support; would need a
  trained Qwen-3.x-Mamba3 hybrid model first. Reference code exists at
  state-spaces/mamba + fla-org/flash-linear-attention.
