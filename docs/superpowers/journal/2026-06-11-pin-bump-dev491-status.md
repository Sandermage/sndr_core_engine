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
