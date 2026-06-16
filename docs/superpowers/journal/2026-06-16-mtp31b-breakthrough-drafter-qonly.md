# 31B MTP breakthrough — the drafter is Q-ONLY; the prior direction was a dead end

**Date:** 2026-06-16
**Trigger:** user — "deeply study + implement the RIGHT fully-working approach (study repos + others' proposals)".

A 5-angle research workflow (studied the checkpoint header + the live dev491 vllm source + upstream
#41745/#45181/#45207 + external repos) produced a decisive reframe of the banked 31B MTP.

## The finding: the gemma-4-31B assistant drafter computes NO K/V

Verified three independent ways:
1. Live `vllm/v1/spec_decode/gemma4.py` / `gemma4_mtp.py`: `Gemma4MTPAttention` builds only
   `q_proj/q_norm/o_proj` and calls `self.attn(q, kv_dummy, kv_dummy)` with
   `kv_dummy = torch.empty(...)`, `is_kv_shared_layer=True`.
2. The checkpoint header has `q_proj/q_norm/o_proj` and NO `k_proj`/`v_proj`/`qkv_proj`.
3. Genesis' own retired G4_78/PN270 audit docstring states it verbatim.
Upstream PR #41745 confirms the gemma4 MTP drafter shares the target's KV by design.

## Consequences (the prior G4_71–G4_77 direction was self-inflicted)

- An **independent drafter cache is impossible** — it can only hold `kv_dummy` zeros → permanent
  0% acceptance regardless of memory or warm-up. **G4_77 (warm-up) is architecturally VOID.**
- The "3-way bind" was CAUSED by the independent-drafter stack: G4_74 cap → OOB; G4_71/G4_72 bf16
  independent cache → +9.27GiB OOM; G4_76c dtype-coerce → boot reshape mismatch. Reverting the
  stack (G4_71/71b/72/74/75/76 = 0) dissolves binds 2&3 (boot-level) — confirmed by the earlier E4
  boot, which booted CLEAN (healthy 190s, no OOM/reshape) and crashed only at the verify step.
- #45181/#45207 do NOT unlock anything here — they PAD (don't bucket), and are already vendored in
  G4_60e. The drafter needs the target's real K/V (kv_sharing), not a page fix.

## The correct path (kv_sharing ON + group-aware verify)

S1 — revert G4_71/71b/72/74/75/76 (keep upstream `_setup_gemma4_kv_sharing`; kv_sharing ON, native
   MTP rail). LOW risk. Dissolves binds 1-3's boot-level parts.
S2 — VERIFY the drafter resolves to the TurboQuant backend + keeps its `turboquant_*` dtype so it can
   READ the aliased TQ-compressed target cache. (G4_60g must emit TQ specs; depends on S1 removing
   G4_76c's coercion.)
S3 — interim cudagraph=NONE boot to isolate aliasing correctness from the verify route.
S4 — **the one real remaining blocker:** make the K+1 TQ spec-verify route GROUP-AWARE. The 31B has
   two cache groups (sliding head_dim=256 / global head_dim=512); the synthetic-decode verify route
   must select each group's block_table + head_dim. Base on G4_81 (no head-size gate; writes into
   `output`); iterate `kv_cache_group_id`; retire G4_67 (superseded). G4_82 (prefill SDPA) stays
   enabled in parallel (orthogonal, required). MEDIUM-HIGH — this is where the real time goes.
S5 — acceptance + coherence validation on a real 31B-tq MTP boot (tool-call + needle 10/30/60K;
   metric: spec_decode_num_accepted_tokens > 0 and coherent). The live 35B proves the mechanism
   (68.8% acceptance with MTP+TQ+shared-KV).

## Honest feasibility

Achievable on dev491/A5000 — no new HW, no upstream needed (kv_sharing aliasing + the TQ decode
kernel both exist on the pin; the live 35B proves MTP+TQ+shared-KV works). NOT a 1-session patch:
S1-S3 are easy/verify, S4 (the two-head-dim group-aware verify route) is the genuine engineering +
iterative 31B boots. But the DIRECTION is now correct and verified — the prior multi-day "independent
drafter + warm-up" framing was chasing an impossible target.
