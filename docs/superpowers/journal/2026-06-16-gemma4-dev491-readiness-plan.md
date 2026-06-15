# Gemma-4 dev491-readiness + speed/quality plan (the durable roadmap)

**Date**: 2026-06-16. Source: comprehensive multi-source study (engine dev491 + our patches + community
club-3090/SGLang/vLLM). The Gemma-4 + 27B models are pin-HELD on dev259 because the spec-decode/TQ/gemma4
patch stack isn't dev491-ready. This is the precise plan to fix it + the speed/quality upside.

## Headline verdicts

- **EAGLE-3: DEPRIORITIZE — keep MTP.** club-3090 #171 (CLOSED not-planned): MTP 121 vs EAGLE-3 111 t/s
  *even on Blackwell*; on Ampere the CUTE_DSL graph-capture HANGS (~15-18 t/s). Our native MTP-K3
  assistant-drafter is already **+65% thinking / +51% code / +31% multi-turn** on dev491 (clean A/B, n=3).
  Mechanism: the external dense ~0.5B drafter bypasses MoE expert routing → both GPUs symmetric at 98% util
  (why MTP helps Gemma-4 MoE but *hurt* Qwen 35B-A3B −51%). EAGLE-3 would cost real drift-fix effort to
  *maybe* match a baseline MTP already beats. Revisit only if a `qwen3_next_eagle3` path lands.
- The pin-hold is **~3h of code (A1+A2) + 1 rig boot (A3)**, not endless firefighting.

## The drift-bug chain (why pin-held on dev259)

- **Chain A — rejection_sampler signature growth** (`use_fp64_gumbel`, vllm#43150, passed unconditionally
  at rejection_sampler.py:182-184). PN282 + PN248 wrappers had explicit stale signatures → TypeError every
  spec-decode step when enabled. **FIXED (commit 23a28079)**: forward-proof `*args/**kwargs` + signature-bind
  side-channel. Drift recorded in registry (d0711acc).
- **Chain B — PN390 dropped `target_probs`** (vendored vllm#45369): P71/PN369 reference undefined
  `target_probs` → NameError (caught → silent no-op). Dormant on PROD (`draft_sample_method='greedy'` gates
  P71 off). Registry already declares `P71 conflicts_with PN390` (registry.py:648-652) — **enforce at
  dispatch (A2-enforce, pending)**.
- **Chain C — 31B boot crash**: launcher bind-mounts the stale `overlays/pr42637/kv_cache_utils.py` which
  lacks `get_kv_cache_capacity` (dev491 keeps it at kv_cache_utils.py:1732; core.py:48 imports it) →
  ImportError → Exited(1). **Fix (A3)**: stop bind-mounting the 8 pr42637 files; native TQ is end-to-end on
  dev491; enable **G4_79** (`supports_mm_prefix->True`, the only remaining gate), remove version-dead
  **G4_60L** (`<0.21`) + over-broad **G4_32**; drive layers 58/59 via native `--kv-cache-dtype-skip-layers`.
  **Needs a rig boot to validate** (does G4_79 alone clear the gate, or is G4_31 needed for AWQ kv_cache_scheme?).
- **Chain D — MoE/cudagraph renames**: G4_08 (made loud, 440e0b28), G4_68 false-green (getattr on an
  inherited classmethod vs the dev491 ClassVar `_cudagraph_support`), G4_60K hasattr-skip.
- **Correctly obsolete (healthy self-skip, leave alone)**: PN90 (native #40269), PN378 (native #45060),
  G4_60e (native #45207/#45181).

## NEW dev491 features for QUALITY + other aspects (adopt)

| Feature | What it gives | Enable |
|---|---|---|
| `use_fp64_gumbel` (config/model.py:229) | **Quality**: fp64 exponential-race noise preserves lower-tail sampling events fp32 truncates at 2⁻²⁴ (vllm#43150: 0 vs 32 tail hits at 262K vocab — Gemma-4's vocab). NOT a speed/accept lever. | `--use-fp64-gumbel` (after A1; bench A5000 TPS cost) |
| Native probabilistic `draft_probs` (#40269) | **+accept-rate** (the +0.5-2% PN90 chased), native + monkeypatch-free | `draft_sample_method='probabilistic'` (default 'greedy') |
| INT8-per-token-head KV (kv_cache_interface.py:42-43) | **Quality + VRAM**: club-3090 ships INT8-PTH = ×8.2 context for ~10% TPS, NIAH PASS at 137K. INT8 not fp8 (Triton fp8e4nv unsupported on sm_86) | KVQuantMode INT8 on the TRITON_ATTN-locked path; quality A/B gate |
| Native GELU-tanh MoE (activation.py:18,74) | Removes need for a GLU-fusion shim; re-scope G4_04 to key-remap only | native (already wired) |

## Community-proven (adopt/adapt)

- **club-3090 26B-A4B MTP recipe** (#326, awq/mtp.yml): stock v0.22, cyankiwi AWQ-4bit, external ~0.5B
  assistant drafter n=4, bf16 KV, NO `--attention-backend`. Matches our +51-65%. **ADOPT.**
- **vllm#45703 (OPEN)** MoE Marlin K-pad incl. nibble-aware AWQ-int4 — **WATCH; retire G4_08 / re-decide
  G4_02 on merge** (until then G4_02/G4_08 are still load-bearing — marlin_utils.py:314 "MoE prep does not
  pad yet").
- **vllm#38887 (OPEN) + SGLang#25006**: head_dim 256/512 forces Triton on Ampere — hardware-physical, ACCEPT.
- **EARS adaptive acceptance threshold** (arXiv 2512.13194, +18% throughput <0.84% acc drop) — EVALUATE vs
  P82's fixed-0.3 OR-clause (biased; loses unbiased-sampling guarantee).
- **DFlash-on-Ampere in-vLLM via G4_10+G4_71b+G4_75** — the SWA+FULL drafter contract club-3090 abandoned
  (moved to beellama.cpp); a genuine Genesis differentiator, default-OFF, +18% code at 32K. Cheap later A/B.

## Sequenced plan

```
PHASE A — UNBLOCK (drift chain)
  A1 [DONE 23a28079] forward-proof PN282/PN248 wrappers           → kills use_fp64_gumbel crash
  A2 [drift record DONE d0711acc; enforce pending] P71/PN369↔PN390 conflict hard-refuse at dispatch
  A3 [code+RIG] retire pr42637 overlay, enable G4_79, drop G4_60L/G4_32, native skip-layers
       └ RIG BOOT: gemma4-31b-tq-mtp-chat-k3 on dev491 (no ImportError, gate clears, turboquant_4bit_nc, GSM8K>0)
  A4 [code] version-cap dead G4_60-series/G4_68/P65
PHASE B — QUALITY (after A)
  B1 --use-fp64-gumbel (RIG: TPS cost + tail-recall)
  B2 draft_sample_method='probabilistic' (RIG: accept-length A/B; UNVERIFIED Gemma4Proposer interaction)
  B3 INT8-per-token-head KV (RIG: perplexity/accept/tool-call JSON + VRAM — quality gate, may be negative)
PHASE C — WATCH: #45703 merge → retire G4_08; EARS threshold; DFlash A/B
```

## Caveat
The `/private/tmp/dev491_vllm` checkout is a Genesis-PATCHED working tree (no .git) — anchor re-validation
needs a clean extraction from the actual nightly-1033ffac2 image layer before trusting apply-order claims.
