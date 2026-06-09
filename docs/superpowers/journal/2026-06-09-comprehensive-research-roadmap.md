# 2026-06-09 — Comprehensive 3-week research synthesis + prioritized roadmap

Background-fanned 6 parallel research agents covering: (1) vLLM merged
PRs 2026-05-19 → 2026-06-09; (2) vLLM open PRs of vendoring value;
(3) vLLM open issues / performance regressions; (4) sister engines
(SGLang, LMCache, FlashInfer, fla-org, state-spaces/mamba, TensorRT-LLM);
(5) model-side updates (Qwen3.6 + Gemma 4 HuggingFace + arXiv);
(6) internal Genesis hot-path + tooling audit.

This document is the *unified* punch list — what every agent surfaced,
deduplicated, ranked by ROI/risk for our PROD shape (35B FP8 + TQ k8v4
+ MTP K=3 + GDN hybrid on 2× A5000 SM 8.6 TP=2, pin 0.22.1rc1.dev259+g303916e93).

------------------------------------------------------------------
## TIER 0 — CRITICAL CORRECTNESS / SILENT REGRESSION FIXES
------------------------------------------------------------------

### PN346 — vllm#43650 (zack041) — Mamba-state boundary fix for MTP + prefix-caching

**Vendor priority: ABSOLUTE TOP. 6 LOC.**

Issue #43559 reports **silent ~20 % accuracy drop** on Qwen3.6-35B-A3B
hybrid GDN + MTP K=3 when `--enable-prefix-caching` is active. Root
cause: `SingleTypeKVCacheManager` drops the final partial block on
FullAttention path during spec-decode but not on the Mamba/GDN path —
GDN state cache reads stale boundaries.

Fix is **6 lines** in `vllm/v1/core/single_type_kv_cache_manager.py`:
mirrors the FullAttention drop-final-partial-block treatment to the
Mamba path under `is_eagle_speculation`.

* Maintainer-acknowledged. Test plan: `lm-eval gsm8k --tasks
  qwen3.6-35b-a3b-fp8` with `--enable-prefix-caching` ON, vs ON+PN346.
  Expected: +1-3 pp / +20 % accuracy recovered on MTP+APC overlap path.

* **Verify exposure first**: we don't pass `--enable-prefix-caching`
  explicitly on the 35B launcher, but vllm V2 sometimes flips it on
  via heuristic. `bench_decode_tpot_clean_ab.py --runs 25 --prompts
  reused` ground-truth A/B before patch.

* Apply to all 4 PROD models (35B-A3B + 27B Lorbus + Gemma 4 26B-A4B
  + Gemma 4 31B) — every spec-decode-on-hybrid-or-Mamba pattern can
  hit this.

### PN347 — vllm#44113 (shernshiou) — Marlin FP8 silent data corruption when N==K on sm_75-88

**Vendor priority: MANDATORY CORRECTNESS FIX.**

Bug: in `vllm/model_executor/layers/quantization/marlin/scaled_mm.py`,
the guard

  ``if w_q.shape != (in, out):``

is always False when ``N == K`` (e.g. some 35B FP8 attention
projections), so the layout-transpose is silently skipped → wrong
multiply on **sm_75-sm_88 — our A5000 is SM 8.6, right in the bug's
range**.

Symptom is silent: output looks plausibly correct but logits are
subtly wrong on the affected square linears. No exception.

PR adds ``if w_q.shape == (in, out) or w_q.shape == (out, in):`` style
gate. ~10 LOC.

* Closes #44110.
* Bundle with PR #43910 (Marlin FP8 padding overhead) — same
  surface, same risk class.

### PN348 — vllm#44644 (Ntropic) — Qwen3.5/3.6 MTP backbone deduplication

**Vendor priority: ABSOLUTE — VRAM win + 0 risk.**

Today: Qwen3.5/3.6 MTP backbone re-allocates ``embed_tokens`` and
``lm_head`` even when the MTP config shares them with the target
model. Reporter measured **0.4–1.0 GiB of VRAM** wasted *per worker*.
At TP=2 that's **0.8–2.0 GiB free** on 2× A5000 24 GB cards.

Fix: skip reload in ``models/qwen3_5_mtp.py`` when the MTP config
declares shared weights (Qwen team's intended design — vLLM was
double-allocating against the model card).

* Tested by author on Qwen3.5; per harsha20032020's PR #44720 the
  Qwen3.5 model class is reused for Qwen3.6 — direct portability.
* +Free VRAM headroom for either: longer context (320K → 384K+),
  or a fresh PN95 TierManager configuration with bigger CPU slabs.

### PN349 — vllm#44797 (Anai-Guo) — Gemma 4 skip k_norm/v_norm on KV-shared layers

**Vendor priority: HIGH for Gemma 4 PROD.**

Surgical fix in ``models/gemma4.py``: KV-shared (sliding-window)
layers in Gemma 4 SFT checkpoints lack k_norm/v_norm weights. Today
vLLM fails the load (or silently zeroes them) → **~1 % logit drift**
on the sliding layers.

~20 LOC. Direct hit on our Gemma 4 26B-A4B and 31B FP8 PROD.

------------------------------------------------------------------
## TIER 1 — HIGH-ROI PERFORMANCE WINS
------------------------------------------------------------------

### PN350 — Convergent GDN post-conv Q/K/V split fused Triton kernel

**Source: SGLang #26206 + TensorRT-LLM #12966. Both engines independently fused the same op.**

Replaces ``torch.split(...).view(...).contiguous()`` chain on the
post-conv GDN Q/K/V path with a single Triton kernel. SGLang
benched on Qwen3.6-35B-A3B at +**2.65 % output tok/s**, with GDN
QKV split time **18.97 ms → 3.33 ms per layer** (210 µs → 37 µs).

* ~100 LOC kernel + integration.
* GSM8K parity confirmed by SGLang.
* The convergence of SGLang + TRT-LLM independently on this op tells
  us it's a real, persistent hot path bottleneck.
* vLLM has **not** adopted it — clear vendoring opportunity.
* Affects all hybrid-GDN models: 35B-A3B, 27B Lorbus, and any future
  GDN model.

### PN351 — vllm#43257 (ShuaiShao93) — Triton unified_attention tune for head_dim ≥ 512

**Direct hit on Gemma 4 31B (head_dim=512).**

In ``vllm/v1/attention/ops/triton_unified_attention.py`` —
``num_warps=8``, ``num_stages=2``, larger tile size when ``head_size >= 512``.

* Author bench: occupancy 6-13 % → 25-40 % on Hopper.
* Same registers-per-thread budget on Ampere SM 8.6 → identical
  numerical class of win.
* Estimated: **decode_TPOT –3-7 %** on Gemma 4 31B FP8.
* 14-LOC diff. LOW risk.

### PN352 — vllm#44557 (xyang16) — topk=8 in moe_sum CUDA kernel

**Direct hit: Qwen3.6-A3B (top-k=8) + Gemma 4 (top-k=8 MoE).**

Today: ``csrc/moe/moe_align_sum_kernels.cu`` only has CUDA paths for
top-k ∈ {2, 4, 6}. Top-k=8 falls back to ``at::native::reduce_kernel``
→ **360 extra kernel launches per decode step on a 40-layer MoE**.

PR adds top-k=8 path. ~–700 µs/decode-step, –1-3 % TPOT estimated.

### PN353 — TurboQuant stack (vllm#43432 → #44053 → #43747 → #43887, lesj0610)

**Bundle vendor — TQ maintainer's full upgrade train.**

Order is critical because patches stack:

1. **#43432** — Lloyd-Max MSE quantization for V-cache (we currently
   use uniform min/max). Saves 2 B / V-vector ≈ –1-3 % cache; ppl
   ↓ 0.05-0.15 on Gemma 4 31B 16K (author bench on our exact
   model). +1124 LOC.
2. **#44053** — Reserve TQ scratch workspace **before** CUDA graph
   capture. Fixes "locked-workspace" assertion on long-context
   prefill. +162 LOC. **Supersedes our existing PN118 workaround**.
3. **#43747** — Remove illegal ``.tolist()`` GPU→CPU calls in
   ``_prefill_attention`` continuation branch during CG capture.
   Closes our open issue #40807. +168 LOC.
4. **#43887** — Route MTP K+1 verify batch through TQ-decode path
   (not prefill fallback). +1798 LOC. **decode_TPOT –5-9 % at K=3**.

Combined: eliminates two crash classes + V-cache quality up + decode
TPOT win. Risk: medium for #43887 (largest). Apply in order;
intermediate boot smoke tests between each.

### PN354 — Apply USE_EXP2 flag (vllm#43195) to Qwen3.6 GDN chunk kernel

**Currently KDA-only. Extend to Qwen3.6 GDN for +3-5 % TTFT on prefill.**

PR 43195 adds ``USE_EXP2: tl.constexpr`` to
``chunk_gated_delta_rule_fwd_kernel_h_blockdim64`` and replaces ``exp(...)``
with ``exp2(...)`` (hardware-accelerated PTX, ~2× throughput).
Currently the flag is set True only for KDA, False for Qwen3.5/3.6
GDN.

Investigation needed first: numerical equivalence (FP rounding
differs by ~1 ULP) — validate via GSM8K on 27B Lorbus before
promoting. Effort M; expected **+3-5 % TTFT on GDN prefill**.

### PN355 — vllm#43642 (lesj0610) — Hybrid GDN/Mamba/MRoPE startup warmup

**Vendor priority: HIGH — completes our PN126/128/129/130 warmup family.**

Adds startup warmup for the kernels we currently see JIT-spike on
first user request (per journal 2026-06-09-deep-dive-bugfix-followup
section #1):

* ``_compute_slot_mapping_kernel``
* ``_causal_conv1d_update_kernel``
* ``fused_recurrent_gated_delta_rule_packed_decode_kernel``
* ``layer_norm_fwd_kernel``

Win class: **TTFT –200-600 ms** on first request after restart.
+864 LOC.

------------------------------------------------------------------
## TIER 2 — DIRECT HITS, SMALL FIXES
------------------------------------------------------------------

### PN356 — vllm#44333 (MidasMining) — Enable MTP on Qwen3.6-27B int4 (currently broken)

Our 27B int4-AutoRound + MTP path crashes silently because
``FusedMoE.__init__`` on MTP layers reads global GPTQ ``quant_config``
but the MTP layers carry unquantized BF16 weights → shape mismatch.

Wrapping MTP construction in temp ``quant_config=None`` context fixes
the load. +43 LOC. **Unlocks** MTP K=3 on 27B int4. Material gain.

### PN357 — vllm#43349 (yewentao256) — Optimize draft greedy token selection

Sparse remap on draft-id → target-id instead of dense full-vocab
scatter. **37–81 % kernel speedup** on the spec-decode helper.
+134 LOC. Direct hit for our MTP K=3 hot path.

### PN358 — vllm#44868 (weicj) — Refresh forward-context tensors before FULL CUDA graph replay

Safety/correctness fix for ``cudagraph_mode=FULL_AND_PIECEWISE`` (our
PROD). Captures forward-context tensor tree at FULL CG capture; copies
live tensor values in before each replay. Prevents stale
attn_metadata / slot-mapping / batch-descriptor under high concurrency
+ mixed batches.

A/B test before adopting (new mechanism — confirm no replay cost
regression). Medium risk.

### PN359 — vllm#44297 + vllm#44441 — MTP + structured-output bitmask at reasoning boundary

Mid-window reasoning-end loses the bitmask switch with MTP/EAGLE →
500 "Failed to advance FSM" when streaming tool calls with
``VLLM_ENFORCE_STRICT_TOOL_CALLING=1`` (Qwen ``</think>`` boundary).
Direct fix for our PROD Qwen3.6 tool-calling path.

### PN360 — vllm#44643 (chaunceyjiang) — Spurious "System message must be at beginning"

Tiny fix in ``vllm/renderers/hf.py`` — eliminates 400-errors on
legitimate Qwen3.6 multi-system chat templates. +80 LOC.

### PN361 — vllm#44869 — Fail-closed on missing spec-decode draft probabilities

20-LOC safety net: raises ``RuntimeError`` instead of silently falling
back from exact-probabilistic to greedy when draft probs are missing
on rows with draft tokens. Observability — converts a silent quality
regression into a visible error. Trivial vendor.

------------------------------------------------------------------
## TIER 3 — CONFIG / LAUNCHER CHANGES (NO PATCH NEEDED)
------------------------------------------------------------------

### Launch script enhancements (zero code, immediate effect)

1. **``VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR=/var/cache/vllm/flashinfer_autotune``**
   (vllm#42537) — saves **30 s – 2 min** of container restart time on
   Qwen3.6 + Gemma 4 stacks. Persistent across restarts.

2. **``VLLM_SSM_CONV_STATE_LAYOUT=DS``** — vllm CI uses this on
   Qwen3.5/3.6 + MTP path. Sets SSM conv state layout to
   ``(dim, state_len)`` (TP-friendly) instead of default ``SD``.
   A/B test first; if measurable on our shape, set in YAML.

3. **`--stream-interval 1` defensive flag** — vllm#43436 fixed Qwen
   MTP parser loses `</think>` and tool-call empty args when
   ``stream-interval > 1``. Defensive: set 1 explicitly so the fix
   applies and future operator can't accidentally raise.

4. **`--enable-prefix-caching` audit** — verify whether vllm V2
   auto-enables this on our config; if so, PN346 vendor is urgent.
   Otherwise, ensure it stays off until #43650 lands.

5. **`--max-model-len` cap at 280K**, not 320K — gives back ~3-4 GiB
   per card under sustained load. Already journaled (2026-05-15
   session #17.4); confirm propagated to the launcher.

### Model-side weight refresh

1. **Gemma 4 31B chat template** — PR #118 merged 8 Jun 2026 fixes
   null handling, tool_call arg type validation, multi-turn reasoning
   loss, turn-tag imbalance. ``wget`` raw ``chat_template.jinja`` from
   HF and restart container. **HIGH urgency** — affects every Gemma 4
   tool-call request.

2. **Gemma 4 26B-A4B chat template** — same fixes via PR #47 (8 Jun
   2026). Pull and restart.

3. **Gemma 4 31B FP8 weights** — RedHatAI re-uploaded 8 Jun 2026.
   ``git lfs pull`` recommended; verify SHA-256.

4. **Qwen3.6-35B-A3B-FP8 identity** — confirmed on server: actually
   ``Qwen/Qwen3.6-35B-A3B-FP8`` (official Qwen team), README on disk
   confirms. Earlier "cyankiwi/..." label in memory/YAML was a
   misattribution. **No action needed** — but the model is the
   canonical release, no surprises.

5. **Lorbus 27B AutoRound vs Intel/Qwen3.6-27B-int4-AutoRound** —
   Intel re-uploaded 21 May 2026 (canonical AutoRound source; Lorbus
   is downstream). Diff quantization config; if Intel updated
   scales, consider migrating.

### Gemma 4 tool parser leaks (vllm#44522 + #44715)

`<|"` and `"|>` sentinels leak into streaming responses and dict
keys on Gemma 4 tool calls. PRs #44532 (detokenizer) and an inline
key-strip patch fix them. Vendor both as a small Gemma 4
tool-parser patch.

------------------------------------------------------------------
## TIER 4 — DEFER / WATCH / VERIFY
------------------------------------------------------------------

### Defensive monitoring needed (Tier 3 agent findings)

1. **#44209 — hybrid GDN non-deterministic KV reservation** → CUDA
   graph capture OOM after /health passes → silent crash-loop risk.
   Reporter is Qwen3.6-35B-A3B (our exact model). Mitigation: pin
   ``--kv-cache-memory-bytes`` explicitly + capped ``cudagraph_capture_sizes``
   + ``cudagraph_mode=PIECEWISE``. Add a post-capture liveness probe
   to healthcheck.

2. **#44740 — negative CUDA graph memory estimation (-35 GiB) on
   Qwen3.6-35B-A3B + MTP**. Bug in profiler arithmetic. Cap
   ``--gpu-memory-utilization`` at 0.85 (from current 0.9) on the
   35B+MTP path until upstream fixes the profiler.

3. **#43436 + #43338** — Qwen MTP parser corruption — pin
   ``stream-interval=1`` defensive config; track upstream fixes.

### Trackers (no immediate vendor)

* **#44735 (FP8 weight layout canonicalization)** — only post-pin
  PR in our hot area. Bundle into next pin bump, not standalone.
* **#41184 (MoE refactor)** — anti-target, in catch-up cycle. Hold pin.
* **FlashInfer pin bump** — when we bump, look for #3485 (FP8 KV
  BF16-staging prefill kernel, +1.07-1.30× on FP8 KV) + #3324
  (Mamba2 checkpointing_ssu kernel for MTP) inclusion. Both work
  on SM 8.6.

### Insight-only / future research

* **MTP+SSM replay convergence** (FlashInfer #3324 + TRT-LLM
  #13711/#13725 + SGLang #23273) — three engines independently
  converged on a "two-kernel replay+state-update" pattern with
  conditional HBM-skip. Genesis adapter would deliver **+20 %
  throughput on MTP K=3** but is ~3-4 day effort. Park for a focused
  iteration once Tier 1 lands.
* **Spec-V2 tree drafting** for hybrid GDN (SGLang #27463) —
  unlocks topk > 1 MTP. Worth a design doc.
* **arXiv 2605.22791 GatedDeltaNet-2** (NVIDIA, May 2026) — decouples
  erase/write gates. Not retrofittable to Qwen3.6-27B without retrain.
  Informational.

### Bench/correctness studies queued

* lm-eval GSM8K with/without prefix-caching on 35B (#43559 verify).
* PN350 GDN QKV fused kernel A/B (after vendor).
* PN353 stack TurboQuant bundle A/B (after vendor).
* PN354 USE_EXP2 numerical equivalence on 27B (GSM8K).
* USE_EXP2 + DS conv-state-layout combined A/B.

------------------------------------------------------------------
## INTERNAL HOT-PATH AUDIT (Agent #6)
------------------------------------------------------------------

### Genuine findings worth fixing this loop

* **A2** — `p98_tq_workspace_revert.py:121-122` per-call ``torch.empty()``
  in dev354+ fallback. Replace with ``GenesisPreallocBuffer.get_or_create``.
* **A5** — `p67_tq_multi_query_kernel.py:270-274` ``.item()/.tolist()``
  in telemetry path. Compile-time-resolvable bool gate; document
  cost (10-25 % TPS if accidentally enabled).
* **A7** — PN340/PN341 anchor risk on `gdn_attn.py` + `gpu_model_runner.py`.
  Tooling fix (B1 anchor_drift_watcher).
* **A9** — PN345 YAML comment claims perf win; today's bench says
  NEUTRAL. Reword to "JIT-OOR defensive safety".
* **A10** — P23_WIRE registry missing ``applies_to: {quantization:
  ["gptq"]}`` gate. Add to prevent silent FP8 regression.
* **A11** — Build PN131: warmup for the remaining 10 JIT-spike
  kernels (see PN355 above as upstream alternative — partial overlap).
* **A12/A13** — PN50 + PN67 retire candidates (upstream-merged).
  Move to ``_retired/`` + ``lifecycle="retired"``.
* **A15** — PN200 ``gdn_scratch_pool.acquire_o_output`` unbounded
  default. Add sane cap based on ``max_num_seqs``.

### Internal tooling — TOP 5 builds

* **B2 — `tools/registry_version_audit.py`** (S, ~2 h). Iterate
  PATCH_REGISTRY; evaluate each ``vllm_version_range`` against live
  pin; report ``WOULD_SKIP/APPLIES/UNCONSTRAINED``. Red-flag
  ``default_on=True`` entries that skip. Catches drift like A1 in
  seconds.
* **B1 — `tools/anchor_drift_watcher.py`** (S, ~3 h, extend
  ``check_upstream_drift.py``). For every TextPatch, grep upstream
  for the OLD anchor; report PRESENT/MISSING/MULTI-MATCH per
  (patch_id, anchor_name, target_file). Sort by "blast radius".
* **B4 — `tools/hot_path_alloc_lint.py`** (M, ~half-day). AST-walk
  every TextPatch ``*_NEW`` string; regex for
  ``torch.(empty|zeros|empty_like|arange|ones)``. Per-match flag.
  Optional ``--ci`` exit-1. Catches PN118/p98/p40 class bugs.
* **B7 — `tools/bench_a_b_runner.py`** (M, ~half-day). One CLI:
  ``genesis ab --patch PN345 --arm-a off --arm-b on --runs 10 ...``
  → restart, bench, Welch, emit YAML row for registry. Formalizes
  the ritual every loop iteration repeats.
* **B6 — `sndr/runtime/cudacapture_guard.py`** (S, ~2 h). Reusable
  helper for ``.item()`` / ``.tolist()`` under cudagraph capture.
  Removes recurring antipattern from patches.

------------------------------------------------------------------
## FALSE ALARMS / AGENT MISCALLS (defensive — for posterity)
------------------------------------------------------------------

* **Agent #1 — PR #41126 op-rename**: claimed our PN204 was likely
  broken. **VERIFIED FALSE.** PN204 has zero references to
  ``gdn_attention_core``. Only PN32 docstring (line 10) mentions
  old name (no runtime impact). ``kernels_legacy/gdn_core_attn_manager.py``
  references old name but isn't loaded.
* **Agent #5 — "cyankiwi/Qwen3.6-35B-A3B-FP8 doesn't exist"**:
  partially true — cyankiwi only has AWQ on HF. But our actual PROD
  model on disk is ``Qwen/Qwen3.6-35B-A3B-FP8`` (official Qwen team).
  The cyankiwi label in our skill memory was a misattribution; the
  model itself is the canonical release.
* **Agent #6 — A1 "30 patches silently skipped"**: stale
  ``vllm_version_range="<0.22.0"`` exists on many patches, but live
  boot trace shows PN126/PN128/PN129/PN130/PN299/P67 all
  ``status=applied``. The version-range field appears to be
  informational (used by doctor, not enforced as a runtime gate by
  dispatcher). The genuine work is to fix the documentation drift,
  not to expect runtime fallout.

These three are recorded so the next loop iteration doesn't re-chase
them.

------------------------------------------------------------------
## ROADMAP — NEXT 3 LOOP ITERATIONS
------------------------------------------------------------------

### Iteration N+1 (this session if user authorizes)

1. **A/B verify #43559 exposure** on our PROD (lm-eval gsm8k with/
   without prefix-caching).
2. **PN346** — 6-LOC mamba boundary fix vendor.
3. **PN347** — Marlin FP8 N==K correctness fix vendor.
4. **PN348** — Qwen3.5/3.6 MTP backbone dedup (+0.8-2.0 GiB VRAM).
5. **B2** — `tools/registry_version_audit.py` build.
6. **Config tweaks**: ``VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR``,
   ``--stream-interval 1``.

### Iteration N+2

7. **PN349** — Gemma 4 k_norm/v_norm skip.
8. **PN350** — Fused GDN Q/K/V split Triton kernel (SGLang #26206 port).
9. **PN351** — Triton unified_attention tune (Gemma 4 head_dim ≥ 512).
10. **PN352** — topk=8 moe_sum CUDA path.
11. **Gemma 4 chat template refresh** (PR #118 + #47).
12. **B1** — anchor_drift_watcher build.

### Iteration N+3

13. **PN353 stack** — TurboQuant bundle (#43432 → #44053 → #43747 → #43887).
14. **PN354** — USE_EXP2 extension to Qwen3.6 GDN (with GSM8K validation).
15. **PN355** — Hybrid GDN/Mamba/MRoPE startup warmup (vllm#43642).
16. **PN356-PN361** small fixes batch.
17. **B7** — bench_a_b_runner CLI build.

### Reserved for focused iteration

* **MTP+SSM replay adapter** (FlashInfer #3324 + TRT-LLM #13711/13725
  algorithm). +20 % throughput, but 3-4 day effort. Park.

------------------------------------------------------------------
## CUMULATIVE EXPECTED WIN
------------------------------------------------------------------

Conservative add-up (lower-bound estimates, decode TPOT on 35B FP8 +
MTP K=3 sustained):

* PN346 — accuracy recovery (no TPS impact, but corrects silent
  regression → unlocks safe use of prefix-caching)
* PN347 — correctness (no TPS, eliminates silent quality drift)
* PN348 — VRAM headroom (no direct TPS, enables longer context or
  bigger PN95 slabs)
* PN350 — +2.65 % output tok/s (SGLang measured)
* PN351 — –3-7 % decode_TPOT on Gemma 4 31B
* PN352 — –1-3 % decode_TPOT (top-k=8 moe_sum CUDA)
* PN353 stack — –5-9 % decode_TPOT + V-cache quality + crash fixes
* PN354 — +3-5 % TTFT on GDN prefill (numerical validation gate)
* PN355 — TTFT –200-600 ms on first request
* PN357 — –10-15 µs draft step
* config tweaks — ~30 s – 2 min cold-start reduction
* Internal tooling — defensive (no direct TPS)

**Combined floor on 35B FP8 PROD shape**: another **~7-12 % decode
TPS / TPOT** on top of current 228 TPS sustained warm baseline.
Plus ~1-2 GiB VRAM headroom + correctness recovery on MTP+prefix-
caching + Gemma 4 path stability.

This is the comprehensive Tier 0-3 menu; final selection per loop
iteration is the operator's call.
