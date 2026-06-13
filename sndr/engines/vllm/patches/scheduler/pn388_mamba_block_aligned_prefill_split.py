# SPDX-License-Identifier: Apache-2.0
"""PN388 — mamba-block-aligned intermediate prefill split (vendor of vllm#45477).

Upstream bug class (vllm#45477, FIX #43559, root cause of the Qwen3.5/3.6 +
MTP + ``--enable-prefix-caching`` accuracy collapse)
--------------------------------------------------------------------------
``Scheduler._mamba_block_aligned_split`` in ``v1/core/sched/scheduler.py``
keeps prefill chunk ends on mamba block boundaries so the ``align`` cache
mode invariant holds: a non-null mamba block at block-table position ``p``
holds the recurrent state of EXACTLY ``(p + 1) * block_size`` tokens.

With speculative decoding (EAGLE / MTP, ``self.use_eagle`` True) the eagle
prune ``last_cache_position = max(last_cache_position - block_size, 0)``
zeroes ``last_cache_position`` for any prompt shorter than
``2 * block_size`` (on Qwen3.6-27B the mamba block is 1600 tokens after
page-size alignment, so a 2002-token prompt is in this window). The old
four-way branch then hits its ``else: pass`` fall-through and accepts an
arbitrary chunk size. When the per-step token budget fragments concurrent
prefills, a request's first chunk ends UNALIGNED (e.g. 364 of 2002 tokens):

  1. The GDN kernel writes the chunk-end state (state@364) into the
     request's position-0 mamba slot.
  2. On the next allocation ``MambaManager.cache_blocks`` hashes that slot
     as the boundary snapshot (state@1600).
  3. Every request resuming from the poisoned hash silently loses up to a
     block of context → garbled output (stray ``</think>``, malformed tool
     calls, runaway generations); the poisoned entry persists until restart.

Single requests are accidentally safe (their position-0 slot is a null
block), so the bug only shows under CONCURRENT load with unequal prefixes —
exactly our PROD multiconc shape.

LIVE EXPOSURE on our stack
--------------------------
Qwen3.6-35B-A3B FP8 and Qwen3.6-27B int4 both run hybrid GDN+Mamba with
MTP K=3 (``use_eagle`` True) and APC (``--enable-prefix-caching``) under
concurrent load. The mamba block is 1600; a 2002-token tool-calling prompt
is < ``2 * 1600``, so the eagle prune zeroes ``last_cache_position`` and the
fall-through accepts mid-block chunk ends the moment the step budget
fragments. We are CURRENTLY EXPOSED.

PN346/P85 do NOT cover this (verified, PR author confirms "complementary"):
PN346 (#43650, hit-side) prunes the FINAL mamba block from cache-hit
lookup, which hides the poison only when all requests have the same length
(the poisoned block is then everyone's pruned final block). A longer request
sharing the same prefix still HITS the poisoned non-final block. P85 adds
fine-grained shadow hashes on the hit/lookup side. Neither removes the
poison at the SOURCE (the unaligned write). PN388 fixes the split site so
the mid-block snapshot is never written; it composes with PN346 + P85
(different files / different layers, zero anchor overlap) and costs nothing
on the hit path.

Fix (verbatim port of vllm#45477's core arithmetic, Marconi tail omitted)
--------------------------------------------------------------------------
Replace the four-way branch with the single invariant all branches were
enforcing — a prefill chunk's end must lie on a block boundary and must not
pass ``last_cache_position`` without stopping there; only the FINAL chunk may
end unaligned (its mid-block state can never be hashed as a boundary
snapshot). The collapsed form rounds the chunk END position, not the chunk
LENGTH:

    chunk_end = num_computed_tokens + num_new_tokens
    if num_computed_tokens < last_cache_position:
        chunk_end = min((chunk_end // block_size) * block_size, last_cache_position)
    elif chunk_end < prefill_end:
        chunk_end = (chunk_end // block_size) * block_size
    num_new_tokens = max(chunk_end - num_computed_tokens, 0)

Rounding the END (not the length) also fixes the unaligned-start variant:
externally-computed tokens from a KV connector need not be block aligned;
rounding the chunk length would propagate that misalignment to every
subsequent chunk end, re-poisoning through a different entry point —
rounding the end position recovers boundary alignment on the first chunk.
A budget-fragmented first chunk now defers (``num_new_tokens == 0``, which
the scheduler already handles) instead of ending mid-block.

Genesis divergences (documented per iron rule #10)
--------------------------------------------------
  * MARCONI TAIL OMITTED. The PR's new form ends with a Marconi
    ``num_uncached_common_prefix_tokens`` admission block, but that
    parameter does NOT exist in our pin's ``_mamba_block_aligned_split``
    signature (``def _mamba_block_aligned_split(self, request,
    num_new_tokens, num_new_local_computed_tokens=0,
    num_external_computed_tokens=0)`` — verified zero references in the
    whole pin file). Including it would raise ``NameError`` at runtime.
    The Marconi block is a pure-throughput cache-admission optimization,
    not part of the poison fix, so dropping it is correctness-neutral.
  * INLINE ROUND-DOWN. The PR imports ``round_down`` from
    ``vllm.utils.math_utils`` and adds an import line. We inline
    ``(x // block_size) * block_size`` (the exact body of ``round_down``)
    so the patch stays a SINGLE anchor site — no separate, fragile import
    anchor that could drift independently. Behaviour is byte-identical.

P34 coexistence (critical — same file, same function, different lines)
----------------------------------------------------------------------
P34 (effectively always-on legacy patch) rewrites the first branch of the
OLD form (``num_new_tokens // block_size * block_size`` → a zero-collapse
guard ``aligned = ...; if aligned > 0:``). P34's anchor lines are EXACTLY
the lines PN388 deletes, so the two cannot anchor on the same text. PN388
therefore carries a DUAL ANCHOR (required-at-least-one, both
``required=False`` — the P85-on-PN346 convention): a pristine-shaped
variant and a post-P34-shaped variant assembled from P34's own documented
transform. The registry entry sets ``requires_patches: ["P34"]`` so P34
boot-dispatches FIRST and the post-P34 variant is the one that fires on a
real hybrid boot. PN388's new form SUBSUMES P34's zero-collapse intent: a
budget-collapsed chunk now defers via ``num_new_tokens == 0`` (scheduler
handles it) rather than spinning — so the deadlock P34 guarded against
cannot reoccur through this path. The reverse apply order also composes
(the pristine variant then fires). apply() pre-gates on at-least-one-variant
present so a Site-only drift skips cleanly instead of half-applying.

Async-scheduling A/B caveat (Genesis — verify on server before flip)
--------------------------------------------------------------------
The PR validated end-to-end with ``--no-async-scheduling``. Our PROD runs
async overlap ON. The fix only changes which token offset a chunk ENDS at —
it does not touch GDN-state-write ordering — but the boundary timing of the
chunk-end state write versus the async-overlapped next step has NOT been
re-confirmed on our 30-GDN-layer 35B under async. STRONG RECOMMENDATION:
enable PN388 (``GENESIS_ENABLE_PN388_MAMBA_BLOCK_ALIGNED_SPLIT=1``) only
after a server A/B with async-scheduling ON confirms boundary-timing parity
(smoke + bench + the 10-way 2002-token tool-call fanout replay from the PR's
test plan, which reproduced 5/10 corrupted before the fix). Default OFF
until that A/B; this is a LIVE-BUG correctness patch whose enablement is
nonetheless gated on the async re-confirm.

Activation: opt-in via
``GENESIS_ENABLE_PN388_MAMBA_BLOCK_ALIGNED_SPLIT=1`` (default OFF in the
registry — pending the async-ON A/B above). Self-skips when #45477 lands
upstream: the drift markers below are exact substrings of the PR's merged
form (and deliberately NOT substrings of our own emitted text — our inline
round-down spells ``// block_size) * block_size`` where upstream writes
``round_down(...)``, so the lint_drift_markers self-collision contract
holds).

Author backport: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
Vendor target: vllm-project/vllm#45477 (OPEN as of 2026-06-13).
"""
from __future__ import annotations

import logging
import os

from sndr.engines.vllm.detection.guards import resolve_vllm_file
from sndr.kernel import TextPatch, TextPatcher, result_to_wiring_status

log = logging.getLogger(
    "genesis.wiring.pn388_mamba_block_aligned_prefill_split"
)

GENESIS_PN388_MARKER = (
    "Genesis PN388 mamba-block-aligned intermediate prefill split "
    "(vendor of vllm#45477) v1"
)

_TARGET_REL = "v1/core/sched/scheduler.py"

# Drift markers — exact substrings of #45477's merged form, taken from
# `gh pr diff 45477` on 2026-06-13. Absent in the pristine pin tree
# (g303916e93) and deliberately NOT substrings of our own replacement
# text: the PR imports/calls ``round_down(...)`` whereas we inline
# ``(... // block_size) * block_size`` (lint_drift_markers self-collision
# contract — tools/lint_drift_markers.py must stay 0).
_DRIFT_MARKERS = (
    # The PR's import line (added at module top by #45477).
    "from vllm.utils.math_utils import round_down\n",
    # The PR's chunk-end round-down line (upstream calls round_down).
    "            chunk_end = min(round_down(chunk_end, block_size), "
    "last_cache_position)\n",
)


# ── Shared replacement body (PR #45477 flat form, Marconi tail omitted) ──
# Rounds the chunk END position (not the chunk LENGTH). Inlined round-down
# arithmetic ``(x // block_size) * block_size`` keeps this a single anchor
# site (no separate import anchor). The trailing ``return num_new_tokens``
# stays OUTSIDE the anchor (preserved verbatim by the scheduler).
_PN388_NEW_BODY = (
    "        # [Genesis PN388 vendor of vllm#45477] Mamba-block-aligned\n"
    "        # intermediate prefill split. Every NON-FINAL prefill chunk\n"
    "        # must end on a block boundary: the GDN kernel snapshots the\n"
    "        # recurrent state at the chunk end into an aligned block-table\n"
    "        # slot, and cache_blocks later hashes that slot as the\n"
    "        # boundary's state, so an unaligned chunk end poisons the\n"
    "        # prefix cache for every request that resumes from it (#43559).\n"
    "        # A chunk reaching last_cache_position must stop exactly there:\n"
    "        # with Eagle, FullAttn prunes the last matching block, so the\n"
    "        # final chunk must be not smaller than block_size to avoid a\n"
    "        # Mamba cache miss. Only the FINAL chunk may end unaligned (its\n"
    "        # mid-block state can never be hashed as a boundary snapshot).\n"
    "        # Rounding the chunk END (not LENGTH) also re-aligns an\n"
    "        # unaligned external-KV start. A budget-collapsed first chunk\n"
    "        # defers via num_new_tokens == 0 (scheduler handles it) — which\n"
    "        # subsumes the Genesis P34 zero-collapse deadlock guard.\n"
    "        # Genesis divergence (iron rule #10): the PR's Marconi\n"
    "        # common-prefix admission tail is omitted (its param is absent\n"
    "        # from our pin's signature); round_down is inlined.\n"
    "        prefill_end = max(request.num_prompt_tokens, request.num_tokens - 1)\n"
    "        if num_computed_tokens >= prefill_end:\n"
    "            # Decode phase: no splitting.\n"
    "            return num_new_tokens\n"
    "        block_size = self.cache_config.block_size\n"
    "        last_cache_position = (request.num_tokens // block_size) * block_size\n"
    "        # eagle prune\n"
    "        if self.use_eagle:\n"
    "            last_cache_position = max(last_cache_position - block_size, 0)\n"
    "        chunk_end = num_computed_tokens + num_new_tokens\n"
    "        if num_computed_tokens < last_cache_position:\n"
    "            chunk_end = min(\n"
    "                (chunk_end // block_size) * block_size, last_cache_position\n"
    "            )\n"
    "        elif chunk_end < prefill_end:\n"
    "            chunk_end = (chunk_end // block_size) * block_size\n"
    "        num_new_tokens = max(chunk_end - num_computed_tokens, 0)\n"
)


# ── Anchor variant 1: PRISTINE pin form (P34 disabled) ───────────────
# Byte-exact copy of the pin g303916e93 _mamba_block_aligned_split body
# (lines 305-337: the leading comment block + the four-way branch through
# `else: pass`). The trailing `return num_new_tokens` is the splice
# boundary and is NOT part of the anchor.
PN388_PRISTINE_OLD = (
    "        # Perform block-aligned splitting at prefill phase, including:\n"
    "        # * non-resumed requests: num_computed_tokens < num_prompt_tokens + 0\n"
    "        # * resumed requests: num_computed_tokens < (\n"
    "        #                       num_prompt_tokens + num_output_tokens\n"
    "        #                     )\n"
    "        # NOTE: Use `request.num_tokens - 1` to bypass normal decoding.\n"
    "        if num_computed_tokens < max(request.num_prompt_tokens, request.num_tokens - 1):\n"
    "            # To enable block-aligned caching of the Mamba state, `num_new_tokens`\n"
    "            # must be a multiple of `block_size`.\n"
    "            # As an exception, if `num_new_tokens` is less than `block_size`, the\n"
    "            # state is simply not cached, requiring no special handling.\n"
    "            # Additionally, when Eagle mode is enabled, FullAttn prunes the last\n"
    "            # matching block. To prevent this from causing a Mamba cache miss, the\n"
    "            # last chunk must be not smaller than `block_size`.\n"
    "            block_size = self.cache_config.block_size\n"
    "            last_cache_position = request.num_tokens - request.num_tokens % block_size\n"
    "            # eagle prune\n"
    "            if self.use_eagle:\n"
    "                last_cache_position = max(last_cache_position - block_size, 0)\n"
    "            num_computed_tokens_after_sched = num_computed_tokens + num_new_tokens\n"
    "            if num_computed_tokens_after_sched < last_cache_position:\n"
    "                # align to block_size\n"
    "                num_new_tokens = num_new_tokens // block_size * block_size\n"
    "            elif (\n"
    "                num_computed_tokens\n"
    "                < last_cache_position\n"
    "                < num_computed_tokens_after_sched\n"
    "            ):\n"
    "                # force to cache the last chunk\n"
    "                num_new_tokens = last_cache_position - num_computed_tokens\n"
    "            else:\n"
    "                # prefill the last few tokens\n"
    "                pass\n"
)
PN388_PRISTINE_NEW = _PN388_NEW_BODY

# ── Anchor variant 2: POST-P34 form (P34 already applied) ────────────
# Identical to the pristine anchor except P34 has expanded the first
# branch into its zero-collapse guard. Assembled from P34's own documented
# anchor/replacement constants so it byte-matches a real hybrid boot file
# after P34 has run (P34 dispatches first via requires_patches=["P34"]).
_P34_OLD = (
    "            if num_computed_tokens_after_sched < last_cache_position:\n"
    "                # align to block_size\n"
    "                num_new_tokens = num_new_tokens // block_size * block_size"
)
_P34_NEW = (
    "            if num_computed_tokens_after_sched < last_cache_position:\n"
    "                # align to block_size\n"
    "                # [Genesis P34] Zero-collapse deadlock guard (upstream PR #40757).\n"
    "                # When two adjacent multimodal inputs can't fit in the encoder\n"
    "                # cache simultaneously, the gap can be < block_size; aligning\n"
    "                # down then collapses to 0 and the scheduler spins forever.\n"
    "                # Keep the sub-block value when alignment would zero-out —\n"
    "                # Mamba state is still maintained by preprocess_mamba via\n"
    "                # mamba_state_idx (\"simply not cached\" exception applies).\n"
    "                aligned = num_new_tokens // block_size * block_size\n"
    "                if aligned > 0:\n"
    "                    num_new_tokens = aligned"
)
PN388_POST_P34_OLD = PN388_PRISTINE_OLD.replace(_P34_OLD, _P34_NEW)
PN388_POST_P34_NEW = _PN388_NEW_BODY


def build_sub_patches() -> list[TextPatch]:
    """The two anchor variants (required-at-least-one).

    Both are ``required=False`` so the kernel soft-skips the variant whose
    anchor is absent. They are mutually exclusive by construction: the
    post-P34 anchor carries P34's ``[Genesis P34`` comment lines (absent
    from pristine) and P34's expansion breaks the contiguous first-branch
    run the pristine anchor needs. ``apply()`` pre-gates on
    ``at-least-one-present`` so a both-miss drift skips before any write.
    """
    return [
        TextPatch(
            name="pn388_split_pristine",
            anchor=PN388_PRISTINE_OLD,
            replacement=PN388_PRISTINE_NEW,
            required=False,
        ),
        TextPatch(
            name="pn388_split_post_p34",
            anchor=PN388_POST_P34_OLD,
            replacement=PN388_POST_P34_NEW,
            required=False,
        ),
    ]


def anchor_present(content: str) -> bool:
    """True iff at least one anchor variant matches ``content``.

    Required-at-least-one belt for ``apply()``: both variants are
    ``required=False`` so the kernel cannot abort on a both-miss drift —
    we skip BEFORE any write instead of silently no-op'ing and stamping the
    idempotency marker on an unpatched (still-poisoning) file.
    """
    return PN388_PRISTINE_OLD in content or PN388_POST_P34_OLD in content


def _make_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(_TARGET_REL)
    if target is None:
        return None
    return TextPatcher(
        patch_name=(
            "PN388 v1/core/sched/scheduler.py — mamba-block-aligned "
            "intermediate prefill split (vendor of vllm#45477)"
        ),
        target_file=str(target),
        marker=GENESIS_PN388_MARKER,
        sub_patches=build_sub_patches(),
        upstream_drift_markers=list(_DRIFT_MARKERS),
    )


def apply() -> tuple[str, str]:
    """Apply PN388 — mamba-block-aligned prefill split. Never raises.

    Opt-in: gated through the dispatcher on
    ``GENESIS_ENABLE_PN388_MAMBA_BLOCK_ALIGNED_SPLIT`` (default_on=False in
    the registry — pending the async-ON server A/B; see module docstring).
    """
    from sndr.dispatcher import log_decision, should_apply

    decision, reason = should_apply("PN388")
    log_decision("PN388", decision, reason)
    if not decision:
        return "skipped", reason

    patcher = _make_patcher()
    if patcher is None:
        return "skipped", f"PN388: target file {_TARGET_REL} not found"

    if not os.path.isfile(patcher.target_file):
        return "skipped", f"PN388: target disappeared: {patcher.target_file}"
    with open(patcher.target_file, encoding="utf-8") as f:
        content = f.read()
    if patcher.marker in content:
        log.info("[PN388] marker present — skip (idempotent)")
        return "skipped", f"{patcher.patch_name}: already applied (marker present)"
    for dm in patcher.upstream_drift_markers:
        if dm in content:
            return (
                "skipped",
                f"upstream_merged: drift marker {dm!r} in "
                f"{patcher.target_file} — vllm#45477 may have landed",
            )

    # Required-at-least-one pre-gate: both variants are required=False so
    # the kernel's all-miss SKIP would otherwise look identical to a clean
    # apply. Skip BEFORE any write when neither anchor shape is present —
    # the file has drifted (neither pristine nor post-P34).
    if not anchor_present(content):
        return (
            "skipped",
            "PN388: neither anchor variant (pristine-shaped nor "
            "post-P34-shaped) matches _mamba_block_aligned_split — anchor "
            "drift; file left untouched",
        )

    result, failure = patcher.apply()
    return result_to_wiring_status(
        result, failure,
        applied_message=(
            "PN388 applied: _mamba_block_aligned_split now rounds the chunk "
            "END to a block boundary (not the chunk length), so every "
            "non-final prefill chunk ends on a mamba block boundary and a "
            "budget-fragmented first chunk defers (num_new_tokens == 0) "
            "instead of writing a mid-block state into the position-0 slot. "
            "Closes the LIVE prefix-cache poison on Qwen3.6 GDN+Mamba + MTP "
            "K=3 + APC under concurrent prefixes (vllm#45477). Composes with "
            "PN346/P85 (hit-side) and subsumes P34's zero-collapse guard. "
            "Marconi tail omitted; round_down inlined (iron rule #10)."
        ),
        patch_name=patcher.patch_name,
    )


def is_applied() -> bool:
    """Return True iff our marker is present in the target file."""
    patcher = _make_patcher()
    if patcher is None:
        return False
    try:
        with open(patcher.target_file, encoding="utf-8") as f:
            return patcher.marker in f.read()
    except (OSError, UnicodeDecodeError):
        return False
