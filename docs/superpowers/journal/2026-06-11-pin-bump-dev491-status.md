# 2026-06-11 — Pin-bump dev259 → dev491: anchor-validated, promotion BLOCKED on stream tool-calls

## Target
- FROM: vllm 0.22.1rc1.dev259+g303916e93 (current PROD, 2026-06-08)
- TO:   vllm 0.22.1rc1.dev491+g1033ffac2 (candidate, 232 commits newer)
  digest sha256:779772129ce2cbd64329e370aed9dd8f27ffea9b8eb69038e9a2d5ee5791202d

## Status: ANCHOR-VALIDATED + BOOTS CLEAN, but PROMOTION DEFERRED

### What passed
1. **Preflight diagnostic** (pin_preflight vs dev491 pristine): of all 307
   patches, only **8 DRIFT_ANCHOR + 1 binding-fail** drifted across 232
   commits. PN351's proactive dual-anchor (batch-3) showed
   EXPECTED_ALTERNATE — no work needed. The predicted #45171 harmony
   landmine manifested as P107 drift.
2. **Fix-loop** (commit 82d17174): 9 patches dual-anchored
   (P58/P62/P87/P88/P89/P107/PN378/PN380 re-anchored vs BOTH pristine
   trees; G4_07 binding repointed). Re-sweep: dev491 DRIFT_ANCHOR 8→0,
   dev259 DRIFT_ANCHOR stays 0 (PROD anchors intact). lint-drift 0 on
   both trees, 516 tests green.
3. **Smoke boot** (with the full 137-var PROD env-file): dev491 boots
   **99-111 applied / 0 FAILED** — the dual-anchored patches apply
   cleanly on dev491. Non-stream tool-calls WORK (finish=tool_calls,
   get_weather extracted). No NameError (P107 re-anchor good).

### The blocker — streaming tool-calls regressed on dev491
With the SAME launcher (--tool-call-parser qwen3_xml --reasoning-parser
qwen3) that makes dev259 stream tool-calls work, dev491 returns the
tool XML as `delta.content` with `finish_reason=stop` and ZERO
`delta.tool_calls` — the parse_delta dead-zone class fixed on dev259 is
BACK on dev491. This is an upstream behavior change in the 232-commit
window (the studied PRs #45389/#45310/#45479/#45464 all touched the
streaming tool-parser / DelegatingParser path). Tool-calls are the
critical agent hot path, and streaming is the live path → promotion
BLOCKED until adapted.

### Rollback (clean)
PROD restored on dev259 (health 200, stream tool-calls verified working
= 3 delta.tool_calls). dev259 container kept throughout; nightly-303916e93
image preserved. Two PROD-down cycles total (~10 min each): the first
exposed a launcher/YAML env drift (137 -e vars set at docker run, absent
from the launcher — fold them in for reproducibility); the second
exposed the stream-tool-call regression.

## Next (to complete the promotion)
1. **Investigate the dev491 parse_delta streaming regression**: diff
   dev259 vs dev491 `parser/abstract_parser.py` (DelegatingParser.
   parse_delta / _in_tool_call_phase) + `tool_parsers/` + the
   chat_completion streaming generator. Find WHICH of the 232 commits
   changed the reasoning_ended / tool-phase gating, and adapt (likely a
   new Genesis patch or extending PN386). The studied #45389 (PN386,
   already vendored) + #45310 + #45479 are the prime suspects.
2. Re-smoke with the fix; if stream + non-stream tools both green +
   bench within CV of dev259 baseline (250/250/217.6 TPS) → promote:
   YAML pins/EXPECTED_PINS/ALLOWED_MODELDEF_PINS/anchor-manifest →
   dev491; fold the 137 env vars into the launcher; retire/version-cap
   P87+PN378+P26 (upstream-merged on dev491); tag rotation
   (nightly-303916e93 → previous, delete 626fa9bb per max-2 policy).
3. The fix-loop dual-anchors mean PROD can stay on dev259 indefinitely
   with zero risk while the stream-tools fix is developed — the bump is
   ready except this one runtime gap.

## Pin-bump system verdict
232 upstream commits → 9 patches needed re-anchoring (caught in minutes
by pin_preflight), and the only promotion blocker is a genuine runtime
behavior change that NO static tool could have caught — exactly the
gap the smoke-boot leg exists to find. The "painless pin transition"
goal is substantially met: the drift surface was mapped and fixed
automatically; only the runtime adaptation remains.

---

## Update (2026-06-14, post-PN392 server validation attempt)

### Root cause CONFIRMED (deep-diff dev259 vs dev491 pristine)
vllm#45171-era refactor **deleted `tool_parsers/qwen3xml_tool_parser.py`**
and **remapped `qwen3_xml` → `Qwen3CoderToolParser`** in
`tool_parsers/__init__.py`. The coder parser is single-emission
(emits ≤1 structural delta per call, returns to advance assuming
token-by-token feeding); the dev491 unified streaming path feeds the
WHOLE `<tool_call>…</tool_call>` XML as one delta at the reasoning→tool
boundary → the parser flips its start-flag and returns emitting ZERO
`delta.tool_calls`. Verified the re-anchored P107/P89/PN288 are NOT
implicated, and `parse_delta`/`_in_tool_call_phase`/the qwen3 reasoning
parser are byte-identical between pins.

### PN392 fix (commit a3b84468) — server validation INCONCLUSIVE
PN392 (runtime wrap of `extract_tool_calls_streaming` on both
Qwen3Coder + Qwen3XML classes, draining the single-emission core to
coalesce deltas) passes 11 TDD tests + all repo gates (registry 308).
But the dev491+PN392=1 smoke-boot STILL showed the streaming tool-call
returning the raw XML as `delta.content` with `finish_reason=stop` and
0 `delta.tool_calls`. Non-stream tool-calls + reasoning split WORK on
dev491.

### Open questions for the next focused (live, INFO-logged) iteration
1. **Did PN392 actually apply?** The PROD env sets
   `VLLM_LOGGING_LEVEL=WARNING`, which MASKS the INFO-level
   `applied: PN392` line — so the empty grep is inconclusive. PN287
   (same `applies_to.tool_call_parser` gate) applies on dev259, so the
   gate is not the blocker. Re-smoke with `VLLM_LOGGING_LEVEL=INFO` to
   confirm PN392's apply + whether its class-wrap took effect on the
   live parser instance.
2. **If PN392 applied but the symptom persists**, the failure layer is
   DEEPER than the single-emission drain: the content shows the FULL
   XML leaking as content, suggesting the streaming generator may not
   be routing to `extract_tool_calls_streaming` at all (the
   reasoning→tool phase transition, or the coder parser's
   buffer-until-complete behavior swallowing the whole delta). Trace
   `chat_completion_stream_generator` on dev491 with the wrap active.
3. **PN374** (qwen3xml quoted-key) targets the now-deleted
   `qwen3xml_tool_parser.py` → dormant on dev491; re-target to
   `qwen3coder_tool_parser.py` in the same adaptation pass.

### Pin-bump state
ANCHOR-VALIDATED (both pins DRIFT=0, fix-loop 82d17174) + BOOTS CLEAN
(99/0 failed). PROD stays on dev259 at zero risk (dual-anchors). The
ONLY remaining promotion blocker is the streaming-tool-call fix, which
needs ONE live INFO-logged iteration to either confirm PN392 works or
locate the deeper streaming-dispatch layer. NOT a rollback — the
adaptation is 95% done; this is the last 5%.

---

## Update (2026-06-14, SYSTEMIC root cause of "PN392 inert" — FIXED)

Open question #1 above ("did PN392 actually apply? — re-smoke with INFO")
is now **definitively answered, and it was NOT a logging-mask artifact.**
PN392 never applied at boot — and neither does ANY new patch added since
the PR38 migration — for an architectural reason that affects the whole
pin-transition story.

### The finding (apply-loop architecture)
The orchestrator has TWO apply loops (`sndr/apply/orchestrator.py`):
- **legacy loop** — iterates `_state.PATCH_REGISTRY`, applies only the
  238 patches that have a hand-written `@register_patch` hook.
- **spec-driven loop** (`_run_via_specs`) — iterates
  `iter_patch_specs()`, applies via `spec.apply_module`. Gated behind
  `SNDR_APPLY_VIA_SPECS=1`, **default OFF**.

PROD boots in the **default = legacy** mode. **59 patches declare an
`apply_module` but have NO legacy hook** (the KNOWN_SPEC_ONLY set —
relocated to canonical technical-area homes as PR38 migrated away from
the parking lot). Among them: PN288, PN371–392, G4_79/80/81, P88, P89 —
i.e. essentially **every patch authored in the last several sessions,
including PN392.** Under legacy boot these are simply never invoked: an
operator can set `GENESIS_ENABLE_<X>=1`, `should_apply` returns True, the
module imports, a direct `apply()` wraps the class — but the BOOT apply
cycle iterates the legacy table, which doesn't contain them. That is
exactly why the dev491+PN392=1 smoke showed the streaming regression
unchanged: the fix was present on disk and import-valid, but inert at
boot. The earlier summary's "PN288 applies while PN392 doesn't" was
wrong — both are spec-only; neither applied. No contradiction.

### Why we could NOT just flip `SNDR_APPLY_VIA_SPECS=1` (the trap avoided)
A naive "switch the default to the spec loop" would have **silently
dropped 3 default_on bundled legacy patches on PROD**:
- **P1/P2** FP8 kernel dispatcher (`apply_patch_1_2_fp8_dispatcher`)
- **P17/P18** Marlin MoE per-SM tuning (`apply_patch_17_18_marlin_tuning`)
- **P32/P33** TurboQuant cu_2 + synth_seq_lens preallocs
  (`apply_patch_32_33_tq_bundled_preallocs`)

Each is a *bundled* hook (one `@register_patch` applies a pair of patch
ids) and therefore has **no `apply_module`** — the spec loop skips
`apply_module is None` with "informational entry", so `_run_via_specs`
alone would NOT apply them. Critically, **`shadow --strict` does NOT
catch this**: its `legacy_only` check compares against ALL spec ids, not
only those with an `apply_module`. The safety check that DID catch it was
an explicit `legacy_hooked ∩ specs_without_apply_module` intersection
(P1/P17/P32, all `default_on=True, lifecycle=legacy`; plus P20 retired/
off → harmless).

### The fix (two commits, local-verified)
1. **`41dd46f1` shadow parser → CLEAN.** `_patch_id_from_legacy_name`
   could not lift underscore-suffix ids (`P23_WIRE`, `P29_HEAL`,
   `P18B_TEXT`, `PN118_V2_MD5_*`, `PN79_V2_MD5_*`) or `SNDR_`-prefix ids
   (`SNDR_EAGLE3_AUX_HIDDEN_001`) — `\b` finds no boundary before `_`.
   Extended the regex with a `(?:_[A-Za-z0-9]+)*` tail + `SNDR_`
   alternative + token-boundary lookahead, added an `SNDR_` verbatim
   normalization branch. Provably regression-free (old `\b` already
   returned None for any name with `_` after the id → none of the 230
   parsing names carry an underscore tail). Before/after over all 238
   names: 0 regressions, exact 8 newly parsed, 0 still None.
   `shadow --strict`: DIVERGENT → **CLEAN**.
2. **`1a84f632` spec-only supplement.** New `_run_spec_only_supplement`,
   called from `run()` after the legacy loop, applies the ENABLED
   spec-only patches (apply_module set AND patch id absent from the live
   legacy register table) and skips disabled ones **silently** (no stats
   row, no import, no log). All 59 spec-only patches are `default_off`,
   so a clean default boot adds **zero** rows and is byte-identical to
   pre-supplement behavior; work happens only once an operator opts a
   patch in. P1/P17/P32 stay on their legacy hooks — nothing dropped.
   Refactor: the per-spec gate→import→apply→classify sequence was
   extracted into `_apply_spec_module`, shared by `_run_via_specs` and
   the supplement so the two paths can never drift (proven byte-identical
   — `_run_via_specs` dry-run = same 313 tuples before/after).

### Local verification (torch-less dry-run)
- `should_apply("PN392")` = True with the env flag (no hardware gate);
  PN392's `apply_module` imports torch-less → deterministic test.
- LEGACY boot + `GENESIS_ENABLE_PN392…=1` (dry-run): boot log emits
  `[Genesis spec-only] applied: PN392 … — dry-run: apply_module ready`
  + `[Genesis spec-only supplement] 1 applied / 0 failed`. PN392 present.
- LEGACY boot, clean env: PN392 rows = 0, spec-only applied = 0 → no-op.
- Gates: `shadow --strict` CLEAN, 19/19 spec-loop tests (8 new),
  344 dispatcher+apply tests. The pre-existing `failed:1` (PN364
  torch-less import gap) is present before AND after (git-stash proven),
  unrelated.

### What this changes for the dev491 promotion
The remaining live step is unchanged in goal but now has the actual
mechanism in place: re-smoke dev491 with `GENESIS_ENABLE_PN392…=1` —
the supplement now applies PN392 at boot (look for the
`[Genesis spec-only] applied: PN392` line), so the parser wrap is live
in the serving process BEFORE the first stream. If streaming tool-calls
then emit `delta.tool_calls`, the blocker is cleared and promotion
proceeds (YAML pins / EXPECTED_PINS / ALLOWED_MODELDEF_PINS / anchor
manifest → dev491; fold 137 env vars into launcher; retire/version-cap
P87+PN378+P26; tag rotation). If the symptom persists even with PN392
provably applied, open question #2 (deeper streaming-dispatch layer)
becomes the focus — but the "is the fix even active?" ambiguity is gone.

### Follow-ups surfaced
- **Migrate the 3 bundled legacy patches to `apply_module`** (P1/P2,
  P17/P18, P32/P33) so `_run_via_specs` can eventually become the single
  default boot path and the supplement can retire. Until then the
  legacy-loop + supplement combination is the correct, safe boot.
- **Extend `shadow --strict`** with a `would_be_dropped_under_spec_boot`
  check (`legacy_hooked ∩ no_apply_module`) so this class of silent-drop
  risk is caught by the parity gate, not by ad-hoc analysis.
- **PN374** re-target to `qwen3coder_tool_parser.py` (still pending,
  dormant on dev491).
