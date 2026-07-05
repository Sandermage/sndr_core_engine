# Speculative Decoding — Operator Guide

This guide explains the speculative-decoding methods available in Genesis and
when to use each one. All three options ship in our pinned vLLM build and are
selectable per-preset via standard vLLM `--speculative-config` or the Genesis
convenience flag for Suffix Decoding (P75).

## TL;DR — which method?

| Workload class | Recommended method | Why |
|---|---|---|
| Free-chat single-user, short prompts | **MTP K=5** on 35B / **K=4** on 27B TQ (current PROD defaults) | Highest TPS on our 35B FP8 / 27B INT4 stack — 35B K=5 re-tune (2026-06-19): 239.7 TPS / TPOT 3.94 ms vs K=3 207.1 / 4.46 = +15.8% TPS |
| Tool-call agentic (repetitive context) | **Suffix Decoding** (P75) | +40-60% over strict-ngram; suffix tree handles arbitrary-length repeats |
| Mixed structured + free-chat | **MTP** at the preset default K with K_001 OFF | K_001 NOT_SIGNIFICANT across 3 bench cycles; the per-preset re-tuned K is the empirical optimum |
| Long-context (>32K) | **Suffix Decoding** (P75) or MTP with reduced K | Suffix tree's per-prompt locality beats fixed-K speculation; a lower K trades fewer draft tokens for longer-context stability |
| Multi-conc throughput (8+ concurrent) | **MTP** | Multi-conc TTFT regression hits suffix harder than MTP (multi-conc aggregates last measured at K=3, 2026-05-23) |

## Method 1: MTP (Multi-Token Prediction)

**Default for qwen3.6 production presets.** Uses the model's own auxiliary
MTP heads (trained at fine-tune time) to draft K tokens per step. vLLM's
`DraftModelProposer` orchestrates the draft generation + verification.

**Configuration**: enabled by default in all `prod-qwen3.6-*` presets via
`spec_decode: { method: mtp, num_speculative_tokens: <K> }` in the model
YAML. Current PROD K values:

- **35B FP8: K=5** (re-tuned 2026-06-19 — 239.7 TPS / TPOT 3.94 ms vs
  K=3 207.1 / 4.46 = +15.8% TPS; K was under-tuned at 3).
- **27B INT4 TQ-k8v4: K=4** (2026-07-03 coherence K-sweep on dev714:
  K=5 over-proposed bad structural tokens → unparseable tool-calls;
  K=4 is the max coherent K at ~0 speed cost. MTP on this INT4 TQ path
  additionally requires `GENESIS_ENABLE_PN521_TQ_RAW_TAIL_VERIFY=1` —
  without it TQ×MTP collapses into token repetition).
- **Gemma-4: K=3** (31B kvauto-chat profile) / **K=4** (26B multiconc
  profile) via the separate MTP drafter — see the Gemma-4 note below.

The K value (`num_speculative_tokens`) is the launcher cap; the
actual K per step can be adjusted via K_001 (see below — but empirically
NOT useful on our workloads).

**Pros**:

- Trained at fine-tune — high acceptance rate. Per-K on qwen3.6-35b:
  0.78-0.80 at K=3 (historical, dev148 era); 0.653 window accept-rate at
  K=5 on the current dev748 pin (promotion gate 2026-07-04; 0.660 on the
  same-day dev714 canonical bench; floor 0.55 — a lower per-window rate
  at higher K still nets +15.8% TPS vs K=3). The 35B **FP8** checkpoint
  measures higher: 0.728 at K=5 (canonical `sndr launch` path, dev748
  fleet sweep 2026-07-04)
- No external dependency
- Composes with TurboQuant + Genesis spec-decode patches (P62, P67, etc.)

**Cons**:

- Requires model to ship with MTP heads (Qwen3.6 does; vanilla Qwen3 doesn't)
- K is a hyper-parameter — different optimum per workload
- Not adaptive — Genesis K_001 (DynamicProposer port of vllm#26504) was
  designed to fix this but **empirically NOT_SIGNIFICANT** across three
  independent bench cycles (see `evidence/bench/v11.2.0_k001_validation/`)

**Operator notes**:

- `GENESIS_ENABLE_PN90_PROBABILISTIC_DRAFT` is **DISABLED in PROD (keep
  `0`)**. The old "+2.8% accept" measurement was on pre-#40269 pins; on
  dev371+ probabilistic draft is a measured regressor (−5.9% TPS, −10%
  accept — see the ROLLBACK note in
  `sndr/model_configs/builtin/model/qwen3.6-35b-a3b-fp8.yaml`). PROD runs
  greedy draft; re-activation also unmasks a latent P71⊥PN390 NameError.
- Current empirical optima (don't change without re-benching): **K=5** on
  the 35B (re-tuned 2026-06-19), **K=4** on the 27B TQ-k8v4 (max coherent
  K for tool-calls, 2026-07-03 sweep). Current pin:
  `0.23.1rc1.dev748+g2dfaae752` — always check `sndr/pins.yaml` for the
  live value.
- **Verify acceptance after any change** via the engine `/metrics`
  endpoint — the spec-decode counters
  (`vllm:spec_decode_num_accepted_tokens_total` vs
  `vllm:spec_decode_num_draft_tokens_total`) should give a ratio at or
  above the 0.55 floor; the canonical suite reports the same figure as
  the MTP window accept-rate (0.653 on dev748, 2026-07-04; same-day
  dev714 reference 0.660).

### Gemma-4 MTP (separate drafter)

The Gemma-4 presets (`prod-gemma4-26b-*`, `prod-gemma4-31b-*`) use MTP via
a **separate drafter**, not model-native heads like Qwen3.6. Current
profile K values: **K=3** (`gemma4-31b-kvauto-chat`), **K=4**
(`gemma4-26b-multiconc`). A code-workload variant exists as a model YAML
(`gemma-4-31b-it-awq-mtp-n8-code`, `num_speculative_tokens: 8` — +9% code
TPS vs n=4, −3% narrative, per club-3090 A/B). Fresh points: the 31B
kvauto-chat profile (K=3, +PN351 on head_dim=512) measured **window
accept-rate 0.744** on verified dev748 (2026-07-05 re-run; TPOT 9.42 ms,
noisy CV — within CV of dev714, no gain claim) and **0.728** on dev714
(2026-07-04 first pass, TPOT 11.51 ms; per the post-release audit that
lane had booted the dev714 rollback engine via a stale image digest, and
the previously quoted 0.933 was a pre-run scrape snapshot — see the
fleet-sweep table in `BENCHMARKS.md`). The older Gemma tables there
remain historical, labeled with their pin/date.

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

## Method 5 (archived): DFlash draft-model decoding — **pending re-validation**

DFlash uses a small external draft model (z-lab reference) instead of MTP
heads or a suffix tree. Genesis shipped four DFlash presets; **all four
were archived** to `sndr/model_configs/builtin/presets/_archive/`
(`prod-qwen3.6-27b-dflash`, `prod-qwen3.6-27b-dflash-multiconc`,
`prod-qwen3.6-35b-dflash`, `prod-qwen3.6-35b-dflash-multiconc`), plus the
`experimental-qwen3.6-27b-tq-dflash-ab` A/B preset. Do **not** route new
deployments to them.

- Their bench rows remain in [`BENCHMARKS.md`](BENCHMARKS.md) as
  historical tables labeled with their pin/date.
- The model YAMLs (`qwen3.6-27b-dflash`, `qwen3.6-35b-a3b-fp8-dflash`)
  still exist with the z-lab reference N values (N=5 / N=3).
- Status: archived pending re-validation on the current pin lineage —
  restoring one means moving the preset YAML back out of `_archive/` and
  running the full canonical bench + tool-call gate before any PROD use.

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
5. **Verify acceptance via `/metrics`** before trusting the switch:

   ```bash
   curl -s http://localhost:8102/metrics | grep spec_decode_num
   # expect both counters advancing; accepted/draft ratio >= 0.55
   # (MTP baseline on dev748: 0.653 window accept-rate, 2026-07-04;
   #  same-day dev714 reference: 0.660)
   ```

6. **Revert**: remove the `GENESIS_ENABLE_P75_SUFFIX_DECODING` env line,
   relaunch the preset, and confirm `/metrics` shows the MTP accept-rate
   back at its baseline.

### Switching MTP → NGRAM (rare)

1. Edit your profile YAML's `spec_decode` block:
   `{ method: ngram, num_speculative_tokens: 3, prompt_lookup_max: 5 }`
2. Re-render launchers: `sndr profile render-launchers <profile_id>`.
3. Enable Genesis NGRAM stack: `GENESIS_ENABLE_P70_AUTO_STRICT_NGRAM=1`,
   `GENESIS_ENABLE_P77_ADAPTIVE_NGRAM_K=1`,
   `GENESIS_ENABLE_PN72_FREQUENCY_NGRAM_DRAFTER=1`.
4. **Verify + revert**: same `/metrics` check as above (ngram acceptance
   will be materially lower than MTP on free-chat — that is expected).
   To revert, restore the original `spec_decode` block, drop the three
   env flags, re-render, and relaunch.

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

- **EAGLE-3 fusion** — status as assessed 2026-02 (re-verify upstream
  before acting): vLLM-side infra ready (PRs #35029, #35040, Qwen3 PR
  #43132 active at the time). Blocked on **Qwen3.6 EAGLE-3 drafter
  checkpoint** (did not exist publicly). Genesis G4_71/G4_75
  drafter-routing patches already prepare the model-side hook. Tracked
  in master plan Phase 7.
- **Mamba-3** — research-track. No vLLM serving support; would need a
  trained Qwen-3.x-Mamba3 hybrid model first. Reference code exists at
  state-spaces/mamba + fla-org/flash-linear-attention.
