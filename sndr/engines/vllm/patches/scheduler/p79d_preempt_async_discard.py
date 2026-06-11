# SPDX-License-Identifier: Apache-2.0
"""Wiring for Patch 79d v2 — preemption async-discard CREDIT grant.

Rewrite (2026-06-11) of the v1 backport of upstream PR
vllm-project/vllm#38624 (CodersAcademy006, still OPEN). v1 was STALE —
surfaced by the #45146 study (pr-sweep-50 roadmap chunk 2, promoted to
W2-IMMEDIATE).

================================================================
STALENESS HISTORY (why v1 had to be rewritten)
================================================================

v1 (v7.46 era) backported #38624 literally: on `_preempt_request()` it
set `request.num_output_placeholders = 0` and the boolean
`request.discard_latest_async_tokens = True`.

Byte-verified facts on pin 0.22.1rc1.dev259+g303916e93 (pristine tree):

  - `discard_latest_async_tokens` — 0 hits anywhere in the pristine
    tree. Upstream migrated to the INTEGER counter
    `async_tokens_to_discard` (request.py:142, init 0). The v1 write
    just created a dead attribute.
  - `AsyncScheduler._update_request_with_output` drains that counter
    (async_scheduler.py:46-51) and then asserts
    `request.num_output_placeholders >= 0` (async_scheduler.py:60).
  - Upstream's own credit grant lives ONLY in `reset_prefix_cache()`
    (scheduler.py:1970-1971):
        request.async_tokens_to_discard = request.num_output_placeholders
        request.num_output_placeholders = 0

So if v1 had been enabled on this pin: `_preempt_request()` zeroes the
placeholders WITHOUT granting credit -> the in-flight async frame
returns -> no credit, tokens append -> `num_output_placeholders -=
len(new_token_ids)` goes NEGATIVE -> assert at async_scheduler.py:60
crashes the engine. The patch meant to prevent token duplication had
become an assert-crash landmine.

NOTE: upstream #38624 itself is equally stale — its diff still writes
the dead boolean, so merged as-is it would trip the same assert.

================================================================
V2 DESIGN — grant discard credit BEFORE zeroing
================================================================

Four sub-patches across two files, applied ATOMICALLY (all or none):

1. `_preempt_request()` (scheduler.py) — the #38624 intent, adapted to
   the integer-credit era: convert the in-flight placeholder debt into
   discard credit BEFORE zeroing, on EVERY preemption path:
       request.async_tokens_to_discard += request.num_output_placeholders
       request.num_output_placeholders = 0
   `+=` (not upstream's `=`) so undrained debt from an earlier
   preemption is preserved, never overwritten.

2. `reset_prefix_cache()` (scheduler.py) — the pristine loop assigns
   credit with `=` AFTER calling `_preempt_request()`. With sub-patch 1
   in place the placeholders are already 0 there, so the pristine `=`
   would WIPE the just-granted credit. Convert `=` -> `+=` (a no-op
   after the grant, and strictly safer on repeated force-preemptions).

3. Spec-rejection adjustment in `update_from_output()` (scheduler.py) —
   the credit is TOKEN-denominated (placeholders grow by
   1 + scheduled-spec-tokens per in-flight step, see
   `AsyncScheduler._update_after_schedule`), but a stale frame returns
   only its ACCEPTED tokens. The rejected drafts' share of the credit
   must drain in the rejection branch. A returning frame is either
   STALE (credit outstanding -> drain credit, leave the live
   num_computed_tokens/placeholder counters alone — they now account
   for the resumed request's new frames) or LIVE (pristine behavior,
   bit-for-bit).

4. Credit drain in `AsyncScheduler._update_request_with_output`
   (async_scheduler.py) — upstream decrements 1 PER FRAME, which
   under-drains a token-denominated grant whenever spec decode is on:
   MTP K=3 grants 4 per frame, upstream's `-= 1` leaves 3 leftover
   credits that silently swallow the next 3 LEGITIMATE post-resume
   frames. v2 consumes `len(new_token_ids)` (the frame's accepted
   share; the rejected share drains in sub-patch 3). Exact balance per
   stale frame: num_rejected + (1 + num_accepted) = 1 + num_scheduled
   = the grant. `max(0, ...)` guards against over-drain if accounting
   ever drifts.

Credit math summary (MTP K=3, one frame in flight, 1 accepted draft):

    grant at preempt        credit = 0 + 4   placeholders 4 -> 0
    stale frame returns     credit 4 - 2 (rejected) - 2 (accepted) = 0
    post-resume frames      credit 0 -> normal append path, assert holds

================================================================
COMPATIBILITY
================================================================

- Coexists with P58 (vllm#40768 backport) in either apply order: the
  preempt anchor here is the single `request.num_preemptions += 1`
  line, which P58's preempt sub-patch keeps intact (P58 inserts above
  it; we insert below it).
- No other Genesis patch anchors `async_tokens_to_discard` or the
  spec-rejection adjustment block (grepped 2026-06-11).
- Activates only with `--async-scheduling` (sync path never has
  placeholders > 0 at preempt, the grant adds 0). Genesis 35B PROD
  (Qwen3.6-35B-A3B FP8, async + MTP K=3, 280K agent ctx) is the exact
  profile where standard preemptions under KV pressure hit this path.
- Known pristine edge NOT covered (matches pristine semantics): a
  frame returning with empty `new_token_ids` is skipped by
  `update_from_output` before the drain — same as pristine placeholder
  handling for empty frames.

================================================================
ENV
================================================================

GENESIS_ENABLE_P79D_PREEMPT_ASYNC_DISCARD=1   (opt-in, default OFF)

================================================================
RISK
================================================================

LOW-MEDIUM — four anchored edits, byte-verified count==1 each on the
pristine pin; atomic multi-file transaction (no partial state: a grant
without the token-denominated drain would under-drain under MTP).
Behavior change is confined to requests with `async_tokens_to_discard
> 0`, which only the preemption/reset paths produce.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
Rewrite of: vllm#38624 (CodersAcademy006, OPEN) for the integer
async_tokens_to_discard era; drain semantics informed by the #45146
study (reset placeholders on KV-load-failure rewind).
"""
from __future__ import annotations

import logging
import os

from sndr.engines.vllm.detection.guards import resolve_vllm_file, vllm_install_root
from sndr.kernel import (
    TextPatcher,
    TextPatch,
)
from sndr.kernel.multi_file import MultiFilePatchTransaction

log = logging.getLogger("genesis.wiring.p79d_preempt_async_discard")

GENESIS_P79D_MARKER = (
    "Genesis P79d preempt async-discard credit grant vllm#38624 v2 2026-06-11"
)


# ─── sub-patch 1: _preempt_request() credit grant (scheduler.py) ──────────
#
# Narrow single-line anchor (NOT the 3-line spec_token_ids block v1
# used): P58's preempt sub-patch inserts a line INSIDE that block, so
# the wide anchor breaks when P58 applies first. The
# `request.num_preemptions += 1` line is unique in scheduler.py
# (count==1 byte-verified on the pristine pin) and survives P58 in
# either order.

P79D_PREEMPT_ANCHOR = "        request.num_preemptions += 1\n"

P79D_PREEMPT_REPLACEMENT = (
    "        request.num_preemptions += 1\n"
    "\n"
    "        # ════════════════════════════════════════════════════════════\n"
    "        # [Genesis P79d v2 — credit-grant rewrite of vllm#38624]\n"
    "        # Convert in-flight async output placeholders into discard\n"
    "        # credit on EVERY preemption path (upstream grants only in\n"
    "        # reset_prefix_cache). Credit MUST be granted BEFORE zeroing:\n"
    "        # the v1 variant (a boolean flag that is a dead symbol on this\n"
    "        # pin) zeroed without credit, so the stale frame's return drove\n"
    "        # num_output_placeholders negative and tripped\n"
    "        # 'assert request.num_output_placeholders >= 0' in\n"
    "        # AsyncScheduler._update_request_with_output.\n"
    "        # '+=' (not '=') preserves undrained debt from an earlier\n"
    "        # preemption instead of overwriting it.\n"
    "        # CREDIT: CodersAcademy006 vllm#38624 (OPEN; concept), adapted\n"
    "        # by Genesis to the integer async_tokens_to_discard era.\n"
    "        # ════════════════════════════════════════════════════════════\n"
    "        request.async_tokens_to_discard += request.num_output_placeholders\n"
    "        request.num_output_placeholders = 0\n"
)


# ─── sub-patch 2: reset_prefix_cache() wipe neutralization ────────────────
#
# Pristine assigns the credit with '=' AFTER _preempt_request() returns.
# With sub-patch 1 in place the placeholders are already 0 at that
# point, so the pristine '=' would overwrite the just-granted credit
# with 0 — re-arming the very assert this patch removes.

P79D_RESET_CREDIT_ANCHOR = (
    "                request.async_tokens_to_discard = request.num_output_placeholders\n"
    "                request.num_output_placeholders = 0\n"
)

P79D_RESET_CREDIT_REPLACEMENT = (
    "                # [Genesis P79d v2] _preempt_request (patched above)\n"
    "                # already converted this request's placeholder debt into\n"
    "                # discard credit and zeroed the placeholders — the\n"
    "                # pristine '=' here would WIPE that credit with 0.\n"
    "                # '+=' keeps it (and is a no-op after the grant).\n"
    "                request.async_tokens_to_discard += request.num_output_placeholders\n"
    "                request.num_output_placeholders = 0\n"
)


# ─── sub-patch 3: stale-vs-live rejection adjustment (scheduler.py) ───────
#
# The token-denominated credit includes the stale frame's REJECTED
# drafts, but the drain (sub-patch 4) only sees the accepted tokens.
# Drain the rejected share here. The else-branch is pristine behavior
# bit-for-bit (re-indented) — live frames never see credit > 0 because
# stale frames return in step order before any post-resume frame.

P79D_SPEC_REJECT_ANCHOR = (
    "                if request.num_computed_tokens > 0:\n"
    "                    request.num_computed_tokens -= num_rejected\n"
    "                # If async scheduling, num_output_placeholders also includes\n"
    "                # the scheduled spec tokens count and so is similarly adjusted.\n"
    "                if request.num_output_placeholders > 0:\n"
    "                    request.num_output_placeholders -= num_rejected\n"
)

P79D_SPEC_REJECT_REPLACEMENT = (
    "                # [Genesis P79d v2] A returning frame is either STALE\n"
    "                # (discard credit outstanding — it was already in flight\n"
    "                # when the request was preempted) or LIVE. A stale\n"
    "                # frame's rejected drafts drain the token-denominated\n"
    "                # credit; they must NOT touch num_computed_tokens or\n"
    "                # num_output_placeholders, which account for the resumed\n"
    "                # request's new frames.\n"
    "                if request.async_tokens_to_discard > 0:\n"
    "                    request.async_tokens_to_discard = max(\n"
    "                        0, request.async_tokens_to_discard - num_rejected\n"
    "                    )\n"
    "                else:\n"
    "                    if request.num_computed_tokens > 0:\n"
    "                        request.num_computed_tokens -= num_rejected\n"
    "                    # If async scheduling, num_output_placeholders also\n"
    "                    # includes the scheduled spec tokens count and so is\n"
    "                    # similarly adjusted.\n"
    "                    if request.num_output_placeholders > 0:\n"
    "                        request.num_output_placeholders -= num_rejected\n"
)


# ─── sub-patch 4: token-denominated drain (async_scheduler.py) ────────────

P79D_DRAIN_ANCHOR = (
    "        if request.async_tokens_to_discard > 0:\n"
    "            # The request was force-preempted in reset_prefix_cache; drop one\n"
    "            # stale in-flight async output frame per call until the counter\n"
    "            # is drained.\n"
    "            request.async_tokens_to_discard -= 1\n"
    "            return [], False\n"
)

P79D_DRAIN_REPLACEMENT = (
    "        if request.async_tokens_to_discard > 0:\n"
    "            # [Genesis P79d v2] The request was preempted (any path, not\n"
    "            # only reset_prefix_cache) with this output frame in flight —\n"
    "            # the frame is stale, drop it. The credit is token-\n"
    "            # denominated (1 + scheduled spec tokens per in-flight step),\n"
    "            # so consume this frame's accepted-token share; the rejected\n"
    "            # share drains in update_from_output. Upstream's 1-per-frame\n"
    "            # decrement under-drains whenever spec decode is on (MTP K=3\n"
    "            # grants 4 per frame) and the leftover credit would silently\n"
    "            # swallow legitimate post-resume frames. max(0, ...) guards\n"
    "            # against over-drain if accounting ever drifts.\n"
    "            request.async_tokens_to_discard = max(\n"
    "                0, request.async_tokens_to_discard - len(new_token_ids)\n"
    "            )\n"
    "            return [], False\n"
)


def _make_scheduler_patcher(target_file: str | None = None) -> TextPatcher | None:
    """Build the scheduler.py patcher (sub-patches 1-3).

    ``target_file`` overrides resolution for tests; default resolves the
    installed vllm tree.
    """
    if target_file is None:
        resolved = resolve_vllm_file("v1/core/sched/scheduler.py")
        if resolved is None:
            return None
        target_file = str(resolved)
    return TextPatcher(
        patch_name="P79d v2 v1/core/sched/scheduler.py — preempt credit grant",
        target_file=target_file,
        marker=GENESIS_P79D_MARKER + " :: scheduler.py",
        sub_patches=[
            TextPatch(
                name="p79d_preempt_credit_grant",
                anchor=P79D_PREEMPT_ANCHOR,
                replacement=P79D_PREEMPT_REPLACEMENT,
                required=True,
            ),
            TextPatch(
                name="p79d_reset_credit_wipe_neutralization",
                anchor=P79D_RESET_CREDIT_ANCHOR,
                replacement=P79D_RESET_CREDIT_REPLACEMENT,
                required=True,
            ),
            TextPatch(
                name="p79d_stale_frame_rejection_drain",
                anchor=P79D_SPEC_REJECT_ANCHOR,
                replacement=P79D_SPEC_REJECT_REPLACEMENT,
                required=True,
            ),
        ],
        # Self-collision lint (PN369 class): only the defended
        # '[Genesis'-prefixed form — catches marker-line residue after a
        # partial revert. Real upstream absorption is detected by (a) the
        # required anchors going missing (Layer 5 auto-skip — sub-patches
        # 2-4 anchor the exact pristine credit/drain lines) and (b) the
        # occurrence-count probe in apply().
        upstream_drift_markers=[
            "[Genesis P79d",
        ],
    )


def _make_async_scheduler_patcher(
    target_file: str | None = None,
) -> TextPatcher | None:
    """Build the async_scheduler.py patcher (sub-patch 4)."""
    if target_file is None:
        resolved = resolve_vllm_file("v1/core/sched/async_scheduler.py")
        if resolved is None:
            return None
        target_file = str(resolved)
    return TextPatcher(
        patch_name="P79d v2 v1/core/sched/async_scheduler.py — token drain",
        target_file=target_file,
        marker=GENESIS_P79D_MARKER + " :: async_scheduler.py",
        sub_patches=[
            TextPatch(
                name="p79d_token_denominated_drain",
                anchor=P79D_DRAIN_ANCHOR,
                replacement=P79D_DRAIN_REPLACEMENT,
                required=True,
            ),
        ],
        upstream_drift_markers=[
            "[Genesis P79d",
        ],
    )


def apply() -> tuple[str, str]:
    """Apply P79d v2 atomically across scheduler.py + async_scheduler.py.

    All four sub-patches or none — a credit grant without the
    token-denominated drain would under-drain whenever spec decode is
    on, silently swallowing legitimate post-resume frames.
    """
    from sndr.dispatcher import should_apply, log_decision
    decision, reason = should_apply("P79d")
    log_decision("P79d", decision, reason)
    if not decision:
        return "skipped", reason

    if vllm_install_root() is None:
        return "skipped", "vllm install root not discoverable"

    sched_patcher = _make_scheduler_patcher()
    async_patcher = _make_async_scheduler_patcher()
    if sched_patcher is None:
        return "skipped", "v1/core/sched/scheduler.py not resolvable"
    if async_patcher is None:
        return "skipped", "v1/core/sched/async_scheduler.py not resolvable"

    if not os.path.isfile(sched_patcher.target_file):
        return "skipped", f"target disappeared: {sched_patcher.target_file}"
    try:
        with open(sched_patcher.target_file, encoding="utf-8") as f:
            sched_content = f.read()
    except OSError as e:
        return "skipped", f"cannot read {sched_patcher.target_file}: {e}"

    if sched_patcher.marker in sched_content:
        log.info("[P79d] marker present — skip (idempotent)")
        return "applied", "idempotent (marker present)"

    # Upstream-extension probe: the pristine pin has exactly ONE
    # `request.async_tokens_to_discard` site in scheduler.py (the
    # reset_prefix_cache grant). 2+ sites WITHOUT our marker means
    # upstream extended the credit pattern to more paths (e.g. a #38624
    # successor merged the grant into _preempt_request) — self-retire
    # and re-study rather than stacking a second grant blindly.
    # (Our own applied state is unreachable here: the marker check above
    # returns first.)
    credit_sites = sched_content.count("request.async_tokens_to_discard")
    if credit_sites >= 2:
        return "skipped", (
            f"request.async_tokens_to_discard found at {credit_sites} sites "
            "in scheduler.py (pristine pin has 1) — upstream may have merged "
            "a credit grant on more preemption paths; re-study before apply"
        )

    txn = MultiFilePatchTransaction(
        [sched_patcher, async_patcher],
        name="P79d",
    )
    status, detail = txn.apply_or_skip()
    if status == "applied":
        return "applied", (
            "P79d v2 applied: _preempt_request() grants token-denominated "
            "discard credit BEFORE zeroing placeholders (all preemption "
            "paths); reset_prefix_cache '=' wipe neutralized; stale-frame "
            "rejected drafts drain credit; async drain consumes "
            "len(new_token_ids) per stale frame. Rewrite of vllm#38624 "
            "(OPEN) for the integer async_tokens_to_discard era."
        )
    return status, detail
