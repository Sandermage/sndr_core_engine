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

Fix (verbatim port of vllm#45477's core arithmetic; Marconi tail preserved)
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

0.23.1 anchor redesign (2026-06-17 — drift correction)
------------------------------------------------------
On 0.23.1 the live ``_mamba_block_aligned_split`` was RESTRUCTURED: the
signature gained ``num_uncached_common_prefix_tokens``; ``num_computed_tokens``
is now computed at the top; the four-way alignment branch is now NESTED
inside ``if num_computed_tokens < max(request.num_prompt_tokens,
request.num_tokens - 1):``; and a NEW Marconi common-prefix admission tail
follows the branch. The OLD full-function anchor (leading comment block
through ``else: pass``) matched 0 times. The anchor was therefore NARROWED
to the only byte-stable region — the inner four-way branch itself
(``num_computed_tokens_after_sched = ...`` through ``else: pass``). The
replacement is re-indented to 12 spaces and carries no setup/return lines.
Consequences for the two earlier divergences:
  * MARCONI TAIL NOW PRESERVED (not omitted). It lives OUTSIDE the narrowed
    anchor and is left untouched by the scheduler. It re-aligns to
    ``block_size``, so it can only shrink ``num_new_tokens`` to a block
    multiple — the alignment invariant still holds. ``prefill_end`` in the
    replacement equals the outer guard's RHS exactly, and
    ``block_size`` / ``last_cache_position`` / the eagle prune are already
    defined above the splice, so there is no NameError and no duplicate
    definition. The decode early-return of the old flat form is now the
    outer ``if`` wrapper, so it is preserved structurally.
  * INLINE ROUND-DOWN (unchanged). The PR imports ``round_down`` from
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
``required=False`` — the P85-on-PN346 convention): the canonical
post-P34-shaped variant (the live 0.23.1 form, byte-equal to the redesign's
new_anchor) and a pristine-shaped fallback derived from it by the INVERSE of
P34's documented transform. The registry entry sets
``requires_patches: ["P34"]`` so P34 boot-dispatches FIRST and the post-P34
variant is the one that fires on a real hybrid boot. PN388's new form SUBSUMES P34's zero-collapse intent: a
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


# ── Shared replacement body (PR #45477 flat form, Marconi tail preserved) ─
# 0.23.1 REDESIGN (2026-06-17): the live function was restructured — the
# outer ``if num_computed_tokens < max(...)`` guard, the ``block_size`` /
# ``last_cache_position`` / eagle-prune setup, and a NEW Marconi
# common-prefix admission tail all now live OUTSIDE the four-way branch.
# The anchor was therefore narrowed to ONLY the inner four-way branch
# (``num_computed_tokens_after_sched = ...`` through ``else: pass``); this
# replacement is re-indented to 12 spaces (the branch's nesting level) and
# carries no setup/return lines — those are preserved verbatim by the
# scheduler above the splice, and the Marconi tail below is preserved too
# (it realigns to ``block_size``, so the alignment invariant still holds).
# Rounds the chunk END position (not the chunk LENGTH). Inlined round-down
# arithmetic ``(x // block_size) * block_size`` keeps this a single anchor
# site (no separate import anchor).
_PN388_NEW_BODY = (
    "            # [Genesis PN388 vendor of vllm#45477] Mamba-block-aligned\n"
    "            # intermediate prefill split. Every NON-FINAL prefill chunk must\n"
    "            # end on a block boundary: the GDN kernel snapshots the recurrent\n"
    "            # state at the chunk end into an aligned block-table slot, and\n"
    "            # cache_blocks later hashes that slot as the boundary's state, so\n"
    "            # an unaligned chunk end poisons the prefix cache for every\n"
    "            # request that resumes from it (#43559). A chunk reaching\n"
    "            # last_cache_position must stop exactly there. Only the FINAL\n"
    "            # chunk may end unaligned (its mid-block state can never be hashed\n"
    "            # as a boundary snapshot). Rounding the chunk END (not LENGTH)\n"
    "            # also re-aligns an unaligned external-KV start. A budget-collapsed\n"
    "            # first chunk defers via num_new_tokens == 0 (both call sites\n"
    "            # already break/skip on 0) — which subsumes the Genesis P34\n"
    "            # zero-collapse deadlock guard. The Marconi common-prefix tail\n"
    "            # below is preserved (it realigns to block_size).\n"
    "            chunk_end = num_computed_tokens + num_new_tokens\n"
    "            prefill_end = max(request.num_prompt_tokens, request.num_tokens - 1)\n"
    "            if num_computed_tokens < last_cache_position:\n"
    "                chunk_end = min(\n"
    "                    (chunk_end // block_size) * block_size, last_cache_position\n"
    "                )\n"
    "            elif chunk_end < prefill_end:\n"
    "                chunk_end = (chunk_end // block_size) * block_size\n"
    "            num_new_tokens = max(chunk_end - num_computed_tokens, 0)\n"
)


# ── Anchor variant 2 (CANONICAL on 0.23.1): POST-P34 inner branch ────
# 0.23.1 REDESIGN (2026-06-17): on the live container the surrounding
# function was restructured (the outer ``if num_computed_tokens < max(...)``
# guard, the ``block_size`` / ``last_cache_position`` / eagle-prune setup,
# and a new Marconi common-prefix admission tail). Only the inner four-way
# branch (``num_computed_tokens_after_sched = ...`` through ``else: pass``)
# survived byte-for-byte, so the anchor was NARROWED to exactly that branch.
# This is the POST-P34 shape: P34 has already expanded the first branch into
# its zero-collapse guard (the live file is post-P34 because the registry
# sets requires_patches=["P34"], so P34 dispatches first). This is the
# variant that resolves on a real hybrid boot — it is the JSON
# new_anchor byte-for-byte (verified count==1 on the live container).
PN388_POST_P34_OLD = (
    "            num_computed_tokens_after_sched = num_computed_tokens + num_new_tokens\n"
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
    "                    num_new_tokens = aligned\n"
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
PN388_POST_P34_NEW = _PN388_NEW_BODY

# ── Anchor variant 1 (fallback): PRISTINE inner branch (P34 disabled) ─
# Same narrowed inner-branch window as the post-P34 variant, but with P34's
# zero-collapse guard reversed back to the single pristine alignment line.
# Derived from the post-P34 anchor by the inverse of P34's documented
# transform (``_P34_NEW`` → ``_P34_OLD``) so it stays byte-consistent with
# the canonical variant. Only matters on the reverse apply order (PN388
# before P34, P34 absent); on a real hybrid boot P34 runs first and the
# post-P34 variant above is the one that fires. Kept present-but-optional
# (required=False, see build_sub_patches) per the at-least-one convention.
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
PN388_PRISTINE_OLD = PN388_POST_P34_OLD.replace(_P34_NEW, _P34_OLD)
PN388_PRISTINE_NEW = _PN388_NEW_BODY


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
