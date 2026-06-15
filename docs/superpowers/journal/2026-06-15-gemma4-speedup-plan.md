# Gemma-4 speedup — investigation synthesis + prioritized plan

**Date**: 2026-06-15. Pin dev491. Hardware: 2× A5000 24GB (SM8.6 Ampere, TP=2, no NVLink).
**Baselines (chat-matrix, no-MTP)**: 26B-A4B thinking_off 119.5 TPS / TPOT 8.23ms; 31B 49.0 / 20.2ms.
**Three parallel investigations**: empirical MTP bench (rig) + internal-levers workflow + external-solutions workflow.

## Headline findings

### 1. 26B-A4B: MTP K=3 ALREADY gives +56-65% (empirically validated NOW) — the default is stale
| variant | no-MTP | MTP K=3 | Δ |
|---|---|---|---|
| thinking_off | 119.5 | **198.0** | +66% |
| thinking_on | ~119 | 192.5 | +62% |
| code_gen | 121.3 | 188.7 | +56% |
TPOT 8.23 → 4.87ms. **MTP accepts drafts now** (the speedup proves it). The "0% acceptance / gate-MTP-off-for-chat"
policy was a **dev259-era finding** (docs/_internal/MTP_TQ_GEMMA4_*_2026-05-18/19); on dev491 + the G4_71-76 stack
it works. **Action: validate deeper (accept-length + output quality, n≥5) then make MTP-K3 the 26B chat default.**

### 2. EAGLE-3 is the BETTER drafter — official RedHatAI heads for BOTH targets, structurally fix our failure
- `RedHatAI/gemma-4-26B-A4B-it-speculator.eagle3` (~0.93B) + `RedHatAI/gemma-4-31B-it-speculator.eagle3` (~2.2B).
- **Loadable in our binary, NO pin bump**: vLLM PR#39450 "Add Gemma4 Eagle3 support" merged 2026-04-10 (before
  dev491); Gemma4ForCausalLM + Gemma4ForConditionalGeneration declare SupportsEagle3.
- **Why it beats MTP for us**: EAGLE-3 reads the target's intermediate HIDDEN STATES (layers [2,15,27]), NOT the
  shared KV cache. Our internal root-cause (H6) showed the MTP head collapsed reading TurboQuant-COMPRESSED shared
  KV → dequant noise → degenerate loop. EAGLE-3 structurally sidesteps that exact failure mode.
- Reported accept-lengths: 26B HumanEval 2.75 / 31B 3.10 → ~2-2.5× (Qwen-MTP ballpark).
- Serve: `--speculative-config '{"model":"RedHatAI/...eagle3","num_speculative_tokens":3,"method":"eagle3"}'`
  against the plain AWQ target (NOT inside the TQ-MTP profiles). **OPEN A/B RISKS:** (a) accept-rate vs an AWQ
  (vs bf16) target is unverified — EAGLE-3 is quant-agnostic (reads dequant activations) so SHOULD work, must bench;
  (b) **SWA-start bug risk** — SGLang PR#22892 + a vLLM issue show EAGLE+EAGLE3 historically couldn't start on SWA
  targets (Gemma 2/3/4) due to draft_extend; confirm the vLLM gemma4 eagle path handles SWA before trusting it.

### 3. 31B: the speedup IS achievable (community proof) — but our 31B-MTP profile boot-FAILED
- Our `gemma4-31b-tq-mtp-chat-k3` boot failed (likely the TQ+MTP combo or MTP-IMA on TP>1, PR#43909).
- **club-3090 (noonghunna, sister A5000/3090 community) runs Gemma-4-31B MTP at 119-154 TPS — 2.4-3.1× our 49**
  (docs/DUAL_CARD.md). Their config is the proof it's possible; pull + diff it.
- **OR** the 31B EAGLE-3 drafter (AWQ-target-direct, no TQ stack) — sidesteps our boot failure entirely.

## Don't-do (verified dead ends)
- **DFlash on Ampere = BROKEN** (vllm#40382 unservable, #44889 CUDA IMA, fix #44916 unmerged). RedHat's DFlash
  drafters beat MTP on the 26B (1.73×) but need a backend not in our Ampere binary. Skip on A5000.
- **G4_15/G4_24 fused norm/softcap**: the YAML's +5-10%/+3-5% claims are FICTIONAL — Inductor already fuses under
  torch.compile (both profiles enforce_eager:false). Correct the comments; do not enable expecting a gain.
- Marlin block_size_m/num_warps tuning (P17/P18/P24): silently inert for the 26B-A4B Marlin decode shape. Dead.

## Base-decode bottlenecks (non-spec, harder)
- **Ampere attention-backend tax**: Gemma-4's heterogeneous head dims (256 SWA / 512 global) force the SLOW
  TRITON_ATTN backend on Ampere (FlashInfer/FA2 reject head_dim>256) — vllm#38887. This is the structural reason
  Gemma-4 is slow on A5000; hard to fix without an upstream backend change.
- **26B is at ~16% roofline** (8.23ms vs 1.3ms floor) — dominated by MoE dispatch (sort/router + dual MLP+MoE),
  not weight reads. Profile (nsys) before any kernel patch.
- **One real kernel lever**: G4_08 K-pad routes the 26B MoE w2/down_proj through a slow Genesis Triton kernel
  (0.6-0.8× Marlin) instead of native moe_wna16_marlin_gemm — a G4_08 fast-mode could recover a fraction.
- **FP8 quant alternative**: official `RedHatAI/gemma-4-{26B,31B}-it-FP8-Dynamic` (W8A8 E4M3) may decode faster
  than AWQ-4bit on A5000 — worth an A/B (also unblocks fp8 KV cleanly).

## Recommended execution order (highest value first)
1. **26B → MTP K=3** as the chat default (validate accept-length + quality n≥5 first). DONE-able now, +65%, zero new deps.
2. **31B → EAGLE-3** (RedHatAI 31B drafter, AWQ-target-direct) — most likely to fix the 31B (our MTP profile crashes;
   EAGLE-3 avoids the TQ/shared-KV path). A/B vs club-3090's MTP config.
3. **26B → EAGLE-3** A/B vs the working MTP-K3 (may be more robust / faster; check the SWA-start + AWQ-accept risks).
4. **FP8-Dynamic checkpoints** A/B vs AWQ for raw decode speed on both models.
5. **G4_08 w2→native-Marlin** kernel fast-mode (base decode, after profiling confirms w2 is a real fraction).

## Implementation notes
- EAGLE-3 needs the drafter models pulled to /models (e.g. RedHatAI/gemma-4-31B-it-speculator.eagle3). Wire a NEW
  Genesis profile `gemma4-{26b,31b}-eagle3` (method:eagle3, explicit num_speculative_tokens:3, --model = the plain
  AWQ target). Bench accept-length + chat-matrix vs MTP/no-MTP. Keep dev491 (no pin bump — loader already present).
- SpecForge (sgl-project, 891★) can TRAIN a custom EAGLE-3 head if the off-the-shelf underperforms on our AWQ+SWA.
