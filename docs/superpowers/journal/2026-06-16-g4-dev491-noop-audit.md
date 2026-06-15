# Gemma-4 G4_* dev491 silent-no-op audit — closing the gap the 35B-centric audit left open

**Date**: 2026-06-16. Pin under test: dev491 (`0.22.1rc1.dev491+g1033ffac2`) — the image the a5000-2x
hardware ships. **The Gemma-4 models are pin-HELD on dev259**, so their dev491 patch behaviour had
NEVER been audited (the 2026-06-14 audit checked only the 35B-Qwen live apply-matrix, where the
`G4_*` patches are arch-gated out and classed CORRECT_SKIP). G4_08 (found during the EAGLE-3 work)
proved the gap was real. This audit closes it.

**Method**: 11-agent workflow (`g4-dev491-noop-audit`, ~936K tokens). 6 family triagers classify all
36 enabled `G4_*` flags against the dev491 checkout → adversarial re-verify of each flagged suspect →
synthesis. **Control**: G4_08 (known SILENT_NO_OP) was independently re-derived by every agent that
touched it (rename `CompressedTensorsMoEWNA16MarlinMethod`→`CompressedTensorsWNA16MarlinMoEMethod`,
method `apply_weights`→`apply`, wrong class for AWQ) — **method validated.**

## Result — 36 flags

| Class | Count | Flags |
|---|---|---|
| APPLIED_OK | 23 | bind on dev491 + problem still exists upstream |
| CORRECT_SKIP | 4+ | default-off / version- / arch-gated (G4_18, G4_60B, G4_70_PN259*) |
| **SILENT_NO_OP** | **2** | **G4_08** (already loud-fixed), **G4_23** (fixed this session) |
| BENIGN_UPSTREAM_FIXED | 2 | G4_14, G4_68 — retire candidates |
| UNVERIFIED (needs rig) | 5 | G4_60B, G4_60C, G4_13, G4_71B/G4_75, G4_11 |

**Bottom line**: only **2 silent no-ops, both LOW severity** — no high/medium live exposure. The
patch system is largely healthy on dev491 too; the actionable item was G4_23.

## Confirmed SILENT_NO_OP — fixed

### G4_23_GEMMA4_VISION_FP16_OVERFLOW — FIXED this session (loud-noop)
- **Mechanism**: `_find_vision_tower_cls()` getattrs only `Gemma4VisionTower`/`Gemma4VisionModel`/
  `SiglipVisionModel` from `models/gemma4.py`. On dev491 `gemma4.py` has NO vision class — the vision
  tower is an HF `AutoModel.from_config` (`gemma4_mm.py:1041`). getattr→None → `apply()` silently
  returned `'skipped'` while `default_on=True`. The shipped image copy no-ops identically.
- **Exposure**: vllm#40124 FP16-overflow on the vision patch-embed is unguarded on dev491
  (`gemma4_mm.py:1297-1301` `vt.patch_embedder(...).to(model_dtype)`, no float32 upgrade / clamp). BUT
  the trigger is gated behind `--dtype float16`, and all 4 canonical Gemma-4 YAMLs run `bfloat16`
  (set 2026-05-17). So live exposure exists ONLY under a Gemma-4-MM `float16` profile (none live).
  **Severity LOW.**
- **Fix** (this session): `apply()` now distinguishes a MM-capable pin (probes for `gemma4_mm`) from a
  genuinely text-only build. On a MM pin where the class is absent it emits a **loud `log.warning`**
  (FP16 guard NOT installed; matters only under float16; canonical is bfloat16) instead of a silent
  skip; on a text-only build it stays quiet (expected). Behaviour unchanged (still `'skipped'`, no
  boot risk; no float16 fleet to regress). To actually restore the guard on a float16 MM profile,
  re-point the binding at the HF `patch_embedder` (deferred — no live float16 MM profile).

### G4_08_MARLIN_KDIM_PAD — already loud-fixed (commit 440e0b28)
LOUD `log.warning` + `'skipped'`, `default_on=False`; sibling G4_02 (block-2 wraps `AWQMarlinMoEMethod`)
fail-loud-covers the live AWQ 26B-A4B path. Correct fix = upstream PR#45703 (retire on merge) or keep
the dev259 pin_hold. No further action.

## Follow-up items (documented, NOT changed this session)

Each is code-only and low-risk but touches a patch that may be load-bearing on the **dev259 rollback**
(Gemma-4's held pin), so each needs its own careful change rather than a blind sweep. Tracked here:

1. **G4_18 false "supersedes G4_13" registry claim** — dev491 `get_num_kv_heads(self, parallel_config)`
   (`config/model.py:1257`) has NO `layer_idx` kwarg, so G4_18's per-layer branch can never fire; the
   registry markets it as superseding G4_13 but that does not hold on ≥0.22. Action: drop the claim or
   add a version-gate note; keep `default_on=False`; production must rely on G4_13. [code-only]
2. **G4_19 + G4_19B orphaned-producer OOM trap** — G4_19B inflates `available_memory` 4–5.33× to pass
   256K preflight, but its only consumer **G4_19C is RETIRED** (registry.py:9164-9205). So enabling
   G4_19+G4_19B without G4_19C lets a 256K boot pass preflight then OOM at real uncompressed-KV alloc.
   Action: add a registry conflict/requires so G4_19B can't enable without a live compressor. [code-only;
   rig to demonstrate the OOM]
3. **G4_14 dead monkeypatch (BENIGN)** — parser moved `entrypoints.openai.tool_parsers`→`vllm.tool_parsers`;
   patch searches the old path → no-ops. Benign: dev491's rewritten `gemma4_tool_parser` (PR42006/42237/
   44844) fixes the #39392 `<pad>`-mid-JSON leak. Action: retire or re-point (only if the explicit
   `<pad>`-in-args strip is wanted). Do NOT retire blindly — verify the dev259 rollback first. [code-only]
4. **G4_68 marker-only verifier defect (BENIGN today)** — its `getattr(builder_cls,'get_cudagraph_support')`
   resolves the INHERITED base method, so it green-lights `'applied'` even without the P65-v2 override
   (a G4_08-shaped mis-bind to an inherited symbol). Harmless now (TURBOQUANT rejected for Gemma-4 MM),
   but re-audit if G4_79/G4_31 un-gate TQ for Gemma-4 MM. Action: tighten to `'get_cudagraph_support' in
   builder_cls.__dict__` or retire. [code-only]
5. **G4_60K partial redundancy** — its boundary skip-layer union + FA2-force halves are now upstream-native
   (`arg_utils.py:1792-1801`, `:2125-2134`). Only the KV-sharing-target union + PN247 forced-skip remain
   additive. Action: trim/dedup. [code-only]
6. **G4_32 over-broad bypass** — returning `[]` from the consolidated `validate_configuration` now also
   masks the NEW mm-prefix/compute-capability/sink gates dev491 added. Surgical alternative = G4_79. [code-only]

## UNVERIFIED — need a dev491 rig boot (Gemma-4 pin-held on dev259)
G4_60B/G4_60C (whether the PR42637 overlay is bind-mounted — both are LOUD-failing verifiers, correct by
construction), G4_13 (per-layer asymmetry probe vs the live HF schema), G4_71B/G4_75 (fire only when the
MTP drafter boots), G4_11 (chat-template YAML wiring). None is a confirmed exposure; all contingent on a
live boot. Settle these in the same dev491 re-validation pass as gemma4-31b-tq-mtp-chat-k3.

## Net
This session's silent-no-op closures: **G4_08** (loud, 440e0b28) + **G4_23** (loud, this commit). The
user's feared class — "enabled patch silently no-ops while the problem still exists" — is now down to
zero *invisible* instances in the Gemma-4 set: both are loud + accurately scoped. The remaining 6 items
are hardening/dedup/retire follow-ups with full evidence above.
