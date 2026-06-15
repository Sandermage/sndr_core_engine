# vLLM upstream survey (post-dev491) — adaptable fixes

**Date**: 2026-06-15
**Pin**: dev491 = 0.22.1rc1.dev491+g1033ffac2 (~2026-06-13).
**Ask**: survey the vLLM repo for fixes that appeared and can be adapted to our
models/stack (2× A5000 SM8.6, TP=2, latency-bound decode; Qwen3.6-35B/27B hybrid
GDN+MTP+TQ, Gemma-4-26B/31B AWQ).

## Net conclusion: our stack is CURRENT — no risky backports needed now

The relevant post-pin fixes are either already in dev491, superseded by code
in dev491, or require a pin bump (forbidden by policy until validated). Two
items are worth tracking; everything else is a no-op for our shape.

## Track these two

### 1. PR#43447 — Selective prefix-cache retention (MERGED 2026-06-04, IN dev491)
Targets exactly Gemma-4's interleaved 5:1 SWA pathology: a request's transient
sliding-window block allocations churn the prefix-cache free queue. The PR's
free-queue reordering (non-cached blocks to front, cached to back) is **already
active in dev491** and helps Gemma-4 concurrent load with no patch. The fuller
benefit needs prefix-caching ON. **Action (launcher-level, zero-patch):**
evaluate `--enable-prefix-caching` on the Gemma-4 launchers (26B/31B) — A/B for
the SWA churn win. No code change; profile-knob only.

### 2. PR#43914 — TritonAttention fp8-kv hard guard (merged 2026-06-15, NOT in dev491; 45 commits ahead)
Adds a guard in `TritonAttentionImpl.__init__` rejecting fp8 kv_cache_dtype on
backends that can't honor it. **NOT in dev491; pin policy forbids a bump now.**
**Pin-bump pre-flight item:** when a future pin including fa63bb9db is validated,
add a third arm to `g4_80_fp8e5m2_kv_weight_*` so our Gemma-4 fp8-e5m2 KV path
composes with the new upstream guard (else double-guard / conflict). Recorded so
the next pin-bump deep-diff (iron rule #11) catches it.

## Explicitly ruled OUT (do not vendor)
- **PR#41527** (Marlin pad small-N, OPEN) — superseded by #45295 already in
  dev491; vendoring would collide with the dense path. Our P87 (marlin pad
  sub-tile) registry credit should note #40361→superseded (LOW doc fix).
- **PR#44176** (fuse qk-rmsnorm-rope for qwen3.5, MERGED, in dev491) — targets
  Qwen3Next full-attn layers; verify on the live container whether it actually
  fires for `Qwen3_5ForConditionalGeneration` (our 27B subclass) before any
  Genesis adoption. No CUDA work needed for non-Qwen3-Next models. (rig probe.)
- GDN/Mamba2 + MTP/spec-decode merged window 2026-06-13..15 (52 commits) — no
  fix that helps our MTP-K3 hybrid decode beyond what's already in-pin or vendored
  (PN340/PN341/PN59). The MTP-vs-packed-decode exclusion (R4, refuted earlier)
  has no upstream remedy.

## The real value this session was in the CODEBASE sweep, not upstream
The companion defect audit found the high-value work was internal: 18 pre-commit
hooks + 3 CI workflows whose `files:` regexes still pointed at the dead
`vllm/sndr_core/` path (so the gates silently never fired — which is how the
dev491 hardware-YAML drift slipped through), a gating `audit-config-keys` failure
(2 real policy keys missing from `_POLICY_KEYS`), and several fixable audit gates
(short-sha image regex, qwen3_xml capability, retired-lifecycle attribution).
Those are being applied. See the companion commit.
