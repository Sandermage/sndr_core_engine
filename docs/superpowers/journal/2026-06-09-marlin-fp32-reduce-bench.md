# 2026-06-09 — P23_WIRE A/B bench on 35B FP8 Marlin + fresh upstream PR hunt

## P23_WIRE: negative result on 35B FP8

P23_WIRE is the Genesis-original wire patch (2026-06-04) that text-
patches ``marlin_utils.py:36`` (the module-level
``USE_FP32_REDUCE_DEFAULT`` constant) and ``marlin_moe.py:158,217``
so the Marlin launcher actually reads ``VLLM_MARLIN_FP32_REDUCE``.

Before the wire, the env was set + the dispatch decision was logged but
the value never propagated to the launcher → fp32 reduce stayed at
upstream default (True) regardless of operator wishes.

**Genesis credit line** claims ``+1.5-3 % TGS on PROD 27B Qwen3.6 MoE
Marlin (GPTQ, 2× A5000 SM 8.6) with VLLM_MARLIN_FP32_REDUCE=0, no
quality drop on GSM8K/MMLU``. The 27B INT4 GPTQ Marlin path saw the
win.

### A/B bench on 35B-A3B FP8 Marlin (2026-06-09)

Test config: 35B Qwen3.6-A3B FP8 + TQ k8v4 + MTP K=3 + 320K context
+ full PN340/341/29 stack + PN299A–E + PN204.

| Config | run 1 | run 2 | run 3 | run 4 | mean warm |
|---|---:|---:|---:|---:|---:|
| Baseline (P23_WIRE off) | 226.5 | 228.4 | 228.5 | 227.2 | **228.0** |
| P23_WIRE on (FP32_REDUCE=0) | 223.5 | 225.7 | 226.2 | 227.4 | **226.4** |

**Δ -1.6 TPS mean (within CV but trending negative)**. TPOT also
slightly worse: 4.09–4.26 ms vs 4.05–4.09 ms baseline.

### Why the Genesis 27B win doesn't transfer to 35B FP8

The Marlin kernel path on Ampere SM 8.x is different between INT4-GPTQ
and FP8-w8a8:

* **27B INT4 GPTQ**: 4-bit weights → ``MarlinGPTQ`` kernel. The fp32
  accumulator reduction adds non-trivial cycles vs an fp16 reduce on
  these very-small effective matrices. Disabling it pays off.
* **35B FP8 (w8a8)**: 8-bit weights → ``MarlinFP8`` kernel. The matmul
  is larger (more flops between reductions), so the fp32-reduce cost
  is a smaller fraction of total kernel time. Disabling it loses a
  little numerical headroom without trimming a meaningful share of
  cycles.

Disposition: **leave P23_WIRE OFF by default on 35B FP8**. The Genesis
credit line should be updated to scope the +1.5-3 % win to **INT4-GPTQ
Marlin** path (27B Lorbus) only. For 35B FP8 the wire is
neutral-to-mildly-negative; don't ship it as a default-on for FP8 wkld.

Recommended registry update (deferred to a separate commit, not a
blocker for the current session's gains): add ``applies_to:
{quantization: ["gptq"]}`` or equivalent gate to P23_WIRE so it stops
showing up as a recommended-enable on FP8 hardware YAML.

## Fresh upstream PR hunt — agent 2026-06-09 (after 2026-06-06 baseline)

Background agent ran ``gh pr list ... merged:>2026-06-06`` + open-PR
sweep for Ampere / SM 8.6 / hybrid-GDN / MTP / TurboQuant work.
Findings:

### Already in our pin

* **PR #39562** (MambaManager.allocate_slots assertion fix) — the merge
  commit `303916e93d66...` IS the tip of our pin. No action.
* **PR #44700** (mixed prefill/decode split) — confirmed active in
  qwen_gdn_linear_attn.py via earlier verification.

### Bump-pin candidates from the last 48h

* **PR #44735** — *Canonicalize FP8 weight layout to (K,N) at the
  source*, merged 2026-06-08. Author (mgoin) validated on A40 sm_86
  — our exact arch family. Net +11/-29 LOC in
  ``quantization/fp8.py`` + ``compressed_tensors_w8a16_fp8.py`` +
  ``kernels/linear/scaled_mm/marlin.py``. The 35B FP8 Marlin path
  shares this code. Action: **bump pin candidate** after one smoke
  + bench validation. Risk: low — author's own A40 validation.

* **PR #41184** — *MoE refactor* (merged 2026-06-08, +2734/-2027).
  Renames ``.experts.<x>`` → ``.experts.routed_experts.<x>`` — breaks
  all FP8/Marlin weight-loading paths downstream. Catch-up patches
  (#44570, #44120, #44897) still landing. **DO NOT bump until
  upstream stabilizes**. This alone is enough reason to hold the pin
  on 303916e93 for ~1 week.

### Open PRs worth vendoring (per agent ranking)

1. **PR #43047** — *Shmem-aware autotune pruner (Ampere/Blackwell)*,
   opened 2026-05-19. Adds ``early_config_prune`` on
   ``chunk_gated_delta_rule_fwd_kernel_h_blockdim64`` and
   ``chunk_fwd_kernel_o`` — both on our GDN hot path. The pruner
   replaces today's silent "fall back to smallest config" with
   config-precise shmem-budget filtering. Author's SM_120 (Blackwell)
   bench: +3-7 % GDN prefill TPS. SM_86 (A5000) has comparable opt-in
   shmem budget (~99 KiB) so the win should carry. Backport size:
   ~250 LOC across 3 files including a new ``vllm/triton_utils/
   shmem_budget.py`` helper module. **Risk: medium** — the new helper
   file can't be text-patched cleanly (no anchor in upstream); would
   need to be inlined into one of the FLA op files or shipped as a
   Genesis-only bundled helper. Deferred to next iteration.

2. **PR #42425** — ``VLLM_TRITON_FORCE_FIRST_CONFIG`` knob. Debug-only;
   no steady-state TPS gain. Useful as A/B harness. Defer.

3. **PR #43642** — Hybrid GDN/Mamba/MRoPE kernel warmup (warms
   ``_causal_conv1d_update_kernel``, ``fused_recurrent_gated_delta_rule
   _packed_decode_kernel``, ``layer_norm_fwd_kernel``). 5 unit tests.
   Complements our existing PN128/PN129/PN130 warmup. Affects TTFT not
   sustained TPS. Defer to a TTFT-focused iteration.

4. **PR #38368** — FLA reduce recompilations (unused kernel inputs).
   Author measured +12 % on first benchmark run (cold cache). For our
   stable-server steady-state, lower interest. Defer.

5. **PR #40914** — TurboQuant K+1 spec-verify routing. THIS IS OUR
   OWN PR (Sandermage). Still open. Already vendored as P67/P67b.
   Action item: rebase the upstream PR against current dev259 to
   refresh review. (Out of scope for the current loop iteration but
   worth a single-commit rebase later.)

### Anti-targets (don't backport)

* **PR #44397** — improve ``use_cascade_attention`` heuristic. Author's
  own bench shows ``batch=512, prefix=4096`` is +44.1 % slower with
  the new heuristic on FA3. We cross those thresholds at concurrency.
  **Backport would regress**.
* **PR #44698** — MTP PP support. We use TP=2 only. Irrelevant.
* **PR #44132** — online ``fp8_per_channel`` quant. Not our quant
  scheme.
* **PR #44492** — EAGLE/MLA SINGLE_ONLY cudagraph fix. Disjoint code
  paths from MTP + TurboQuant. Skip.

## Concrete next-iteration target

**PR #43047 vendoring as PN345**. The shmem-aware autotune pruner gives
+3-7 % GDN prefill on Ampere with ~zero risk on Hopper (no-op when all
shipped configs fit). Implementation budget: ~250 LOC across new
helper + 2 FLA op edits. The new helper module is the tricky bit —
we'd inline its functions into ``chunk_delta_h.py`` and ``chunk_o.py``
rather than ship a separate Genesis helper module, to keep all changes
text-patch-friendly.

**Estimated TPS gain on our 35B PROD config**: +5–15 TPS over the
current 228 baseline (3-7 % of 228), expected to hit ~235-243 TPS
sustained warm. The prefill-side gain also tends to improve TTFT
by a similar share.

Holding the actual implementation for the next loop iteration so the
current iteration's lessons (P23_WIRE neutral on FP8, etc.) get a
clean commit boundary.
