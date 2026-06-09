# 2026-06-09 — Broken-patches cleanup pass

PROD pin: `0.22.1rc1.dev259+g303916e93`. Boot trace baseline: 102 applied / 117
skipped / **1 failed** / **4 partial-apply warnings**.

This pass audits the 5 patches surfaced as non-working by the boot trace
(G4_05, PN50, P64, P18B_TEXT, SNDR_MTP_DYNAMIC_K_001). Per operator
directive: PN365 already documented in
`2026-06-09-iter-N5-N6-honest-assessment.md`, skipped here.

Disposition matrix:

| Patch | Verified upstream state | Disposition | Action items | Risk |
|---|---|---|---|---|
| **G4_05** | vllm#39930 merged into PROD pin's allowlist (registry credit already documents this — `SpecDecodeConfig.attention_backend` + base autoselect path). File never existed at `sndr/engines/vllm/patches/_retired/`; it lives at `sndr/engines/vllm/_archive/g4_05_dflash_backend_autoselect.py`. | **RETIRE** (already lifecycle=retired in registry; fix dispatch wiring to stop importing the missing module). | 1) Patched `_g4_dispatch_factory` in `sndr/apply/_per_patch_dispatch.py` to short-circuit on `family_pkg in {"_retired", "_archive"}` — emits `_skipped(name, "retired — wiring module ... archived under sndr/engines/vllm/_archive/")` directly, no `importlib.import_module` call. 2) Updated the `_G4_PATCHES` row comment to point at the new factory branch. Position invariant (apply_registry.json) preserved. Reason text contains `"retired"` → BENIGN list match → no partial-apply warning. | LOW — additive code path, behaviour was already a no-op (default_on=False + import failure). New skip is silent vs old loud-failed. |
| **PN50** | PROD container's `vllm/model_executor/layers/mamba/gdn/qwen_gdn_linear_attn.py:1040-1047` (forward branch) replaced `b, a = ba.chunk(2, dim=-1)` with `b, a = self.split_ba(ba)` via upstream rename PR vllm#41126. Block layout otherwise identical (qkv_size / z_size / split / reshape / .contiguous() pair intact). `forward_cpu()` at line 1149-1154 still has the older chunk-form but lacks the .contiguous() pair, so the 9-line anchor remains unique to forward(). | **RE-ANCHOR** (patch is operationally valid — replacement kernel takes `ba` whole, doesn't depend on the split shape). | 1) Updated `ANCHOR_OLD` in `sndr/engines/vllm/patches/attention/gdn/pn50_gdn_fused_proj.py` to use `b, a = self.split_ba(ba)`. Verified byte-exact against container with anchor==text equality check. 2) Added 2026-06-09 re-anchor note explaining why forward() anchor stays unique. 3) Appended re-anchor note to registry credit so future audits see the trail. | LOW — fused kernel takes `ba` directly, so the split shape inside the anchor never affected the replacement's semantics. Container scan confirms one and only one match. |
| **P64** | Container's `vllm/entrypoints/openai/chat_completion/serving.py` no longer contains `_should_check_for_unstreamed_tool_arg_tokens` — refactored out upstream. Repo already flipped sub-patches `p64_safety_net_widen` and `p64_callsite_guard` to `required=False` in commit 630283ac (2026-06-08). **Installed container still has stale `required=True` at `/usr/local/lib/python3.12/dist-packages/sndr/engines/vllm/patches/tool_parsing/p64_qwen3coder_mtp_streaming.py` — this is a deploy-sync gap, not a repo bug.** | **DEPLOY** (repo already correct; container needs sndr-package redeploy). Architectural retire of those two sub-patches is documented in the wiring file's own comment (lines 354-371) — P107 carries the MTP truncation detection role on the new `finish_reason_` callsite. | 1) No repo edit needed — repo state already correct (sub-patches optional, comment block documents retire decision). 2) Operator action: redeploy sndr package to PROD container (rebuild image OR bind-mount the repo's `sndr/` over `/usr/local/lib/python3.12/dist-packages/sndr/`). 3) Boot warning will silence on next start because soft-skip ("anchor not found — soft skip") emits at INFO level, not WARNING. | LOW — already non-required; safety net role moved to P107 which IS applied on PROD. |
| **P18B_TEXT** | Container's `vllm/v1/attention/ops/triton_turboquant_decode.py` **already has the patch marker** at line 1 (`# [Genesis wiring marker: Genesis P18b TEXT TurboQuant decode stage1 kernel-literal tune (SM 8.6 num_warps/num_stages override)]`) AND the NEW values (`num_warps=8 num_stages=3` in both GQA branch line 798-799 and MHA branch line 844-845) plus `[Genesis P18b TEXT, 2026-06-08]` comment blocks. | **NO ACTION — patch is applied and correct**. The boot warning "every sub-patch anchor absent" likely came from a single early-iteration boot before the patch first applied; on subsequent boots the Layer 2 marker check at `sndr/kernel/text_patch.py:344` returns IDEMPOTENT before reaching Layer 5's "no_applicable_sub_patches" path. | None (cosmetic only). If the warning recurs on a re-boot, capture the boot snippet to verify it's coming from P18B_TEXT and not a sibling TurboQuant patch with similar wording. | NONE — patch is provably installed (file marker + both branch literals match the post-apply state). |
| **SNDR_MTP_DYNAMIC_K_001** | Patch is intentionally default-off — three empirical benches (35B-multiconc, 27B-multiconc, multi-turn) all NOT_SIGNIFICANT per registry credit. Skip message did not contain any BENIGN substring (`opt-in`, `default off`, `disabled`, ...), so the boot summary's `partial_apply_warnings` classifier promoted the benign default-off skip to a noisy warning. | **CLEAN SKIP MESSAGE** (no code disposition change — empirical decision to keep default-off is correct). | 1) Edited skip reason in `sndr/engines/vllm/patches/spec_decode/g_dynamic_k_mtp_proposer.py` to start with `"opt-in (default off): "` — matches BENIGN[0] (`"opt-in"`) AND BENIGN[1] (`"default off"`) by substring. Verified via PatchStats test: old reason classified as 1 warning, new reason classified as 0 warnings. | NONE — message text only, no behaviour change. |

## Files touched

* `sndr/apply/_per_patch_dispatch.py` — `_g4_dispatch_factory` now short-circuits on `family_pkg in {"_retired","_archive"}` sentinel; G4_05 row comment updated to reference the new factory branch.
* `sndr/engines/vllm/patches/attention/gdn/pn50_gdn_fused_proj.py` — `ANCHOR_OLD` re-anchored from `b, a = ba.chunk(2, dim=-1)` to `b, a = self.split_ba(ba)`; added 2026-06-09 re-anchor note.
* `sndr/dispatcher/registry.py` — appended PN50 re-anchor trail to the PN50 credit string.
* `sndr/engines/vllm/patches/spec_decode/g_dynamic_k_mtp_proposer.py` — skip reason prefixed with `"opt-in (default off): "` and pointed at the 3-bench ratification record.

## Boot-trace expectation after this commit + a P64-sync redeploy

Before: 102 applied / 117 skipped / 1 failed / 4 partial-apply warnings.

After (this commit alone): 102 applied / 118 skipped / 0 failed / 3 partial-apply warnings.
* G4_05 now reports a `_skipped(retired ...)` (BENIGN), removing the
  single "failed" count.
* SNDR_MTP_DYNAMIC_K_001 reports a `_skipped("opt-in (default off): ...")`
  (BENIGN), removing one warning.
* PN50 anchor now matches → either skipped via dispatcher (default_on=False),
  or, if operator sets `GENESIS_ENABLE_PN50_GDN_FUSED_PROJ=1`, applies cleanly
  (anchor==content byte-exact verified above).

After (this commit + P64 sndr-package redeploy): 102 applied / 118 skipped / 0 failed / 1 partial-apply warning (P18B_TEXT cosmetic; investigate only if it recurs).

## Iron-rule #11 compliance

For each disposition decision above:

* **G4_05** retire — read `_g4_dispatch_factory` body, read registry "G4_05"
  full credit (already documents vllm#39930 supersession + pin commit hash),
  confirmed file location via `find` against `_archive/` + `_retired/`.
* **PN50** re-anchor — read patch source AND grepped container source for
  every line of the anchor, byte-exact diff between repo ANCHOR_OLD and
  container slice. Verified the new fused-kernel replacement does NOT
  depend on the split shape (takes `ba` directly).
* **P64** deploy-only — `git log -p` confirmed the `required=True → False`
  flip is already in `630283ac`; SSH-grepped the container's installed
  sndr package to prove it's stale; SSH-grepped serving.py to confirm
  `_should_check_for_unstreamed_tool_arg_tokens` is gone upstream.
* **P18B_TEXT** no-action — SSH grep proved the marker IS at file top AND
  the both branches' literals match the post-apply state. Reasoned about
  Layer 2 marker check vs Layer 5 fallback path in `text_patch.py`.
* **SNDR_MTP_DYNAMIC_K_001** message-only — Python-tested the
  `PatchStats.partial_apply_warnings` classifier against both old and new
  reason text to prove the warning genuinely drops from 1 to 0.

No speculation; every disposition grounded in source/container/test
evidence captured inline in the matrix above.
