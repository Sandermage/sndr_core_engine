# Phase 7 Research Track — Status & Watchlist

Long-term research items from the Genesis master plan, with current
upstream state, Genesis-side readiness, and concrete next steps when
each item becomes actionable.

Compiled 2026-06-03 from 6 parallel scout subagents + live external
verification via `gh api` and arxiv lookups.

## 1. Suffix Decoding — ✅ DONE / ACTIONABLE NOW

**Status**: vLLM PR [#25784](https://github.com/vllm-project/vllm/pull/25784)
merged 2025-11-03 (Aurick Qiao @ Snowflake). Present in our current
pin `0.21.1rc1.dev354+g626fa9bba`. Reference paper: arxiv 2411.04975
(SuffixDecoding, NeurIPS 2025 Spotlight).

**Genesis state**: Already wired via patch `P75_SUFFIX_DECODING`
(env flag `GENESIS_ENABLE_P75_SUFFIX_DECODING=1`). Auto-rewrites
`speculative_config.method=ngram → suffix`. Tunables:
`GENESIS_P75_TREE_DEPTH=24`, `GENESIS_P75_SPEC_FACTOR=2.0`,
`GENESIS_P75_MIN_PROB=0.10`.

**Empirical**: Per merge PR benchmark — on H200 vs ngram, suffix wins
across all concurrencies. Specbench TPOT conc=1: suffix 4.39ms vs
ngram[3,5] 5.16ms. Acceptance rate ~2-3× higher than ngram.

**Operator action**: see [docs/SPEC_DECODE_GUIDE.md](SPEC_DECODE_GUIDE.md)
for enable recipe + when-to-use guidance.

**Dependency**: `pip install arctic-inference` in container image
(lazy import; P75 falls back to ngram with WARN if missing).

## 2. EAGLE-3 — ⏳ PREP COMPLETE / WAITING FOR DRAFTER CHECKPOINT

**Status**: vLLM upstream production-stable since 2026-02. 30+
EAGLE-3 PRs landed (Qwen3.5 #36658, Gemma4 #39450, MiniMax-M2 #37512,
DSv4 #42413, norm_before_fc #42143). Qwen3 PR [#43132](https://github.com/vllm-project/vllm/pull/43132)
still open. Reference paper: arxiv [2503.01840](https://arxiv.org/abs/2503.01840)
— Feature fusion + Training-Time Test, up to 4.79× on LLaMA-3.3-70B.

**Genesis state**: Patch `SNDR_EAGLE3_AUX_HIDDEN_001` shipped 2026-06-03
(commit `d53c26a5`). Provides the target-model API surface:
- `register_aux_hidden_state_hooks(model, layer_ids)` — captures
  intermediate hidden states
- `pop_aux_hidden_states(model)` — drains into stacked tensor for
  drafter consumption
- `clear_aux_hidden_state_hooks(model)` — cleanup

Default OFF + zero runtime cost without explicit caller invoke.
17/17 unit tests pass.

**Blocker**: a Qwen3.6 EAGLE-3 drafter checkpoint does NOT exist
publicly. EAGLE-3 requires both (a) the auxiliary hidden-state tap
on the target (DONE in Genesis), and (b) a trained drafter model
that maps that aux input → next-token predictions.

**Watch signals** — revisit when:
- A Qwen3.6 EAGLE-3 drafter checkpoint is published on HuggingFace
  (search: `eagle3 qwen3.6` or `qwen3-6 eagle`).
- vLLM PR #43132 (Qwen3 EAGLE-3) merges — likely brings Qwen3.6
  compatibility on the upstream side.
- EAGLE-3 paper authors release Qwen-family drafter weights
  (current public set covers LLaMA / Mistral).

**Estimated effort once unblocked**: <1 day for boot-to-serve, +2
days for full acceptance-rate tuning. Wire-up template:

  1. New patch `SNDR_EAGLE3_DRAFTER_001` instantiates the drafter
     following the `G4_71-G4_76` template (proven on Gemma4 MTP).
  2. Drafter init calls `register_aux_hidden_state_hooks(target, layers)`.
  3. Drafter.propose() calls `pop_aux_hidden_states(target)` per
     step and fuses with input_embeds + last_hidden.
  4. Model config YAML enables `spec_decode.method=eagle3` +
     checkpoint path.

**Critical empirical step**: determining `aux_hidden_state_layer_ids`
for Qwen3.6's 41-layer hybrid (30 GDN + 11 attn). Operator overrides
via `GENESIS_SNDR_EAGLE3_AUX_LAYER_IDS=0,4,8,12,...` without
re-patching. Indexing convention (0-based vs 1-based) needs
verification at checkpoint-ingest time.

## 3. Mamba-3 MIMO — 📚 RESEARCH WATCHLIST

**Status**: Paper [arxiv 2603.15569](https://arxiv.org/abs/2603.15569).
Reference implementations exist in two production-quality repos:

- [state-spaces/mamba](https://github.com/state-spaces/mamba)
  (18.3k★, pushed 2026-06-02). Main-branch architecture is Mamba-3
  with kernel backends:
  - Triton: `mamba_ssm/ops/triton/mamba3/`
  - Tilelang: `mamba_ssm/ops/tilelang/mamba3/`
  - CUTLASS: `mamba_ssm/ops/cute/mamba3/`

- [fla-org/flash-linear-attention](https://github.com/fla-org/flash-linear-attention)
  (5.2k★, pushed 2026-05-31). Mamba-3 ported 2026-04. Provides
  `Mamba3Config` + `Mamba3ForCausalLM` + AutoConfig registration +
  pytest coverage.

**vLLM upstream**: ❌ No Mamba-3 model PRs as of 2026-06-03. Closest
is hybrid plumbing (NIXL routing, KV-cache hybrid loads, etc.). No
serving-stack support yet.

**Genesis state**: No code — strict research watchlist. Our existing
GDN + Mamba2 integration (Qwen3.6 27B INT4) targets a TRAINED model
architecture. We don't pick Mamba-3 unless someone trains and
releases a Qwen-3.x-Mamba3 hybrid.

**Mamba-3 value proposition** (if a target model exists):
- 4× higher decode arithmetic intensity (high relevance on 2×A5000
  which is memory-bandwidth-starved)
- Richer state tracking via complex-valued updates
- MIMO formulation pushes from memory-bound into compute-bound regime
- +1.8pp vs Gated DeltaNet at 1.5B scale (per paper Tab 1)

**Watch signals** — revisit when:
- A Qwen-3.x-Mamba3 or similar hybrid model is published.
- vLLM PR opens for Mamba-3 model architecture support.
- state-spaces/mamba publishes a "Mamba-3 serving guide".

**Estimated effort once unblocked**: Weeks (new patch family parallel
to G4_*, new attention backend, hybrid metadata wiring, kernel
selection between triton/tilelang/cute). Would need a "G6_*" or
"M3_*" series.

## Phase 7 priority ladder (revised 2026-06-03)

1. ✅ **Suffix Decoding** — DONE, P75 wired, operator docs published
2. ✅ **EAGLE-3 model-side prep** — DONE, SNDR_EAGLE3_AUX_HIDDEN_001 shipped
3. ⏳ **EAGLE-3 drafter wire-up** — blocked on Qwen3.6 EAGLE-3 checkpoint
4. 📚 **Mamba-3 architecture port** — blocked on Mamba-3-flavoured target model
5. 🔬 **Adjacent research** (not in master plan, surfacing for future):
   - **MTP K=2 vs K=3 long-ctx** — needs rig bench
   - **Multi-modal speculation** — Qwen2VL has spec-decode patches; no public
     multi-modal drafter checkpoints yet
   - **Disaggregated prefill/decode** — vLLM disagg-prefill landed; Genesis
     has PN92 NIXL trial import patch but no disagg preset
   - **FP4/MXFP6 KV cache** — Blackwell-specific; need SM 10.0 hardware

## Status table

| Item | Upstream | Genesis | Effort | Blocker |
|---|---|---|---|---|
| Suffix Decoding | ✅ in pin | ✅ P75 wired | 0 (done) | — |
| EAGLE-3 model-side | ✅ in pin | ✅ SNDR_EAGLE3_AUX_001 | 0 (done) | — |
| EAGLE-3 drafter | ✅ infra ready | ⏳ template ready | <1 day | Qwen3.6 EAGLE-3 checkpoint |
| Mamba-3 architecture | ❌ no PR | ❌ no code | weeks | target model |
| MTP K-tuning | n/a (workload) | bench scripts exist | <1 day | rig bench window |

## How to extend this document

When a research item becomes actionable:
1. Update the section above with checkpoint URL / PR link / hardware spec.
2. Move from "watchlist" to a concrete plan in master plan §3 (next
   phase) or open a planning issue.
3. If a Genesis-side patch shipped (like P75 + SNDR_EAGLE3_AUX_001),
   update the "Status table" + the priority ladder.
4. Cross-reference from `docs/SPEC_DECODE_GUIDE.md` if it affects
   speculative decoding method choices.

Author: Sander (Sandermage) Barzov Aleksandr, Ukraine, Odessa.
Last refreshed: 2026-06-03 (Tier 2 sweep — EAGLE-3 prep landed).
