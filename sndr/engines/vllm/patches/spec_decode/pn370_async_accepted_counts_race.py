# SPDX-License-Identifier: Apache-2.0
"""PN370 — vendor OPEN PR vllm#45100 (async spec-decode accepted-counts race).

Two sub-fixes from the same upstream PR, vendored against pin
0.22.1rc1.dev259+g303916e93 (anchors byte-verified count==1 on the
pristine tree):

1. ``v1/worker/gpu_model_runner.py`` ``_prepare_inputs`` — SKIP the CPU
   accepted-counts read under async scheduling on the non-align mamba
   path. ``_update_states_after_model_execute`` writes the counts to
   ``input_batch.num_accepted_tokens_cpu_tensor`` with a NON-BLOCKING
   D2H copy; under async scheduling the next ``_prepare_inputs`` may
   also remap request rows after ``input_batch.swap_states()`` /
   ``condense()``. At a request's prefill-to-first-spec-decode
   transition GDN can therefore consume ANOTHER ROW's accepted-token
   count (e.g. 4 instead of 1) and restore the recurrent state from the
   wrong speculative state slot — for Qwen3.5/3.6 hybrids this loses
   prompt memory and the request ends quickly with garbled text + EOS
   (upstream repro: 16/20480 generations corrupted unpatched, 0/20480
   patched; Qwen3.5-27B MTP=3 + async + FULL_AND_PIECEWISE). The fix
   stays device-authoritative: counts default to 1 and the existing GPU
   correction kernel (``update_num_computed_tokens_for_batch_change``
   consuming ``valid_sampled_token_count``) overwrites the
   draft-participating rows. Align-mode (``mamba_cache_mode ==
   "align"``) keeps the synchronized CPU path because its preprocessing
   consumes CPU-side counts. BONUS: on the skipped path the per-step
   ``num_accepted_tokens_event.synchronize()`` + NumPy gather +
   ``copy_to_gpu()`` are gone (the upstream A/B shows ~1.2% tok/s and
   the roadmap estimates ~2-5% TPOT on our 35B PROD shape).

2. ``v1/attention/backends/gdn_attn.py`` ``build()`` — size the FULL
   cudagraph per-request metadata views by ``m.num_reqs`` instead of
   the token-padded ``m.num_actual_tokens``. The slices fed to
   ``GDNAttentionMetadata`` (``spec_state_indices_tensor``,
   ``spec_sequence_masks``, ``spec_query_start_loc``,
   ``num_accepted_tokens``, and the non-spec decode views) are indexed
   by REQUEST; padding them to the token budget (num_reqs * (K+1) under
   MTP K) hands the kernel oversized garbage rows.

Upstream did NOT vendor: the comment-only hunk inside the ``else:``
branch of the same region (zero behavior; the contract is documented
here and in the replacement comments instead — iron rule #10: adapt,
don't blind-copy).

================================================================
COMPOSITION WITH PN341 (MANDATORY — identical anchor line)
================================================================

PN341 sub-patch 4 (``pn341_mtp_decode_bubbles_gpu_runner.py``,
``PN341_PREPARE_OLD``) anchors the IDENTICAL pristine
``_prepare_inputs`` block (the ``if self.num_accepted_tokens_event is
not None:`` site). PN370 composes via the established chain convention
(PN32-imports-PN79 / PN365-imports-PN50 precedent):

- PN370 carries TWO runner anchor variants with required-at-least-one
  semantics (both ``required=False``; the TextPatcher kernel returns
  SKIPPED ``no_applicable_sub_patches`` when every sub-patch misses):

  * pristine-shaped variant (``PN370_PREPARE_PRISTINE_OLD`` ==
    PN341's ``PN341_PREPARE_OLD`` — byte-equality asserted in tests) —
    matches an untouched pristine file (PN341 disabled);
  * post-PN341-shaped variant (``PN370_PREPARE_POST_PN341_OLD`` IS
    PN341's own ``PN341_PREPARE_NEW`` constant, imported — the two
    modules cannot silently diverge). The replacement keeps PN341's
    GPU-only branch byte-identical and only re-gates the trailing
    ``elif`` (the event-backed CPU path) on NOT (async and non-align).

- APPLY-ORDER: PN341 dispatches BEFORE PN370 (boot dispatch parking
  lot: PN341 block precedes PN370's in
  ``sndr/apply/_per_patch_dispatch.py``; keep the registry entry after
  PN341's for SNDR_APPLY_VIA_SPECS parity). The REVERSE order still
  yields valid Python: PN370's pristine variant fires, then PN341's
  sub-patch 4 soft-skips (required=False) while its other three subs
  apply. Roadmap verdict: soft-skip acceptable — under async
  scheduling PN370's gate already routes to the device-authoritative
  default. CAVEAT (documented, not PROD-reachable): in that reverse
  order with async scheduling OFF + hybrid + MTP, PN341's producer-side
  early return loses its consumer (sub-patch 4) — run PN341 first, as
  the dispatch order does.

- PN290 composes cleanly: producer side
  (``_update_states_after_model_execute`` D2H copy) vs PN370's consumer
  side (``_prepare_inputs``) — disjoint anchors, any order.
- PN340 composes cleanly: its three gdn_attn.py anchors (init arange
  buffer / build spec-token indexing / copy gating) are disjoint from
  the ``batch_size`` line.

================================================================
SAFETY MODEL
================================================================

- Opt-in: ``GENESIS_ENABLE_PN370_ASYNC_ACCEPT_RACE=1`` (default OFF).
- Runner variants are required=False (at-least-one); the GDN anchor is
  required=True — a half-missing GDN anchor SKIPs loudly instead of
  silently shipping a partial vendor (PN286/PN290 half-apply lesson).
- Drift markers watch the merged form of vllm#45100:
  ``needs_cpu_accepted_counts`` (the variable the PR introduces; our
  emitted text deliberately uses ``_pn370_read_cpu_accepted_counts`` to
  stay disjoint — lint_drift_markers contract) and the PR's
  ``token-padded for FULL graph replay`` comment in gdn_attn.py.
- Behavior change is gated at RUNTIME by upstream's own condition
  (``use_async_scheduling`` and non-align) — on sync-scheduling or
  align-mode deployments the patched file is behavior-identical to
  pristine.

Expected effect (preserve BOTH): eliminates the silent-corruption class
on async + MTP hybrids (our exact 35B PROD config: Qwen3.6-35B-A3B FP8,
hybrid GDN + MoE, MTP K=3, async-scheduling ON) AND ~2-5% TPOT from the
deleted per-step synchronize.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
Upstream: https://github.com/vllm-project/vllm/pull/45100 (OPEN at
vendor time, 2026-06-11).
"""
from __future__ import annotations

import logging
import os

from sndr.engines.vllm.detection.guards import resolve_vllm_file, vllm_install_root
from sndr.engines.vllm.patches.attention.gdn.pn341_mtp_decode_bubbles_gpu_runner import (
    PN341_PREPARE_NEW,
    PN341_PREPARE_OLD,
)
from sndr.kernel import TextPatch, TextPatcher, TextPatchResult

log = logging.getLogger("genesis.wiring.pn370_async_accepted_counts_race")

GENESIS_PN370_MARKER = (
    "Genesis PN370 vendor of vllm#45100 (async accepted-counts race) v1"
)

_RUNNER_REL = "v1/worker/gpu_model_runner.py"
_GDN_REL = "v1/attention/backends/gdn_attn.py"

# Fires when vllm#45100 merges. NOT "[Genesis"-prefixed entries must
# stay disjoint from every replacement below (tools/lint_drift_markers
# contract; asserted in tests).
_RUNNER_DRIFT_MARKERS = (
    "[Genesis PN370",
    # The PR introduces this variable name; our emitted gate variable is
    # `_pn370_read_cpu_accepted_counts` ("read", not "needs") so the
    # marker never matches our own output.
    "needs_cpu_accepted_counts",
    # NOTE (2026-06-19 dev148 TIER-1 audit): we deliberately do NOT add a
    # `condense() reordered indices` / `prev_positions` drift marker here.
    # That #42347 remap is ALREADY present in dev259 (g303916e93) — PN370's
    # own vendored target — and PN370 is DESIGNED to compose with it (the
    # accepted-counts block is byte-identical dev259<->dev148; the
    # TestEndToEndApply fixtures carry the condense block and assert valid
    # AST). PN370 is version-gated `<0.23.0`, so it never runs on dev148
    # anyway; the dev148 self-skip belongs to PN398 (the >=0.23.0 sibling),
    # not here. Adding the marker would false-skip PN370 on its valid
    # 0.22.x target.
)
_GDN_DRIFT_MARKERS = (
    "[Genesis PN370",
    # The PR's replacement comment in gdn_attn.py; our replacement
    # comment deliberately avoids this exact phrase.
    "token-padded for FULL graph replay",
)


# ─── Runner sub-fix, variant 1: pristine-shaped (PN341 disabled) ──────
# Byte-identical to PN341's PN341_PREPARE_OLD (same upstream block —
# cross-checked in tests).
PN370_PREPARE_PRISTINE_OLD = (
    "        # Sync num_accepted_tokens from CPU (set by\n"
    "        # _update_states_after_model_execute for hybrid models).\n"
    "        if self.num_accepted_tokens_event is not None:\n"
    "            self.num_accepted_tokens_event.synchronize()\n"
)
PN370_PREPARE_PRISTINE_NEW = (
    "        # Sync num_accepted_tokens from CPU (set by\n"
    "        # _update_states_after_model_execute for hybrid models).\n"
    "        # [Genesis PN370 vendor of vllm#45100] async + non-align mamba:\n"
    "        # do NOT read the CPU accepted-counts mirror. It races with the\n"
    "        # in-flight non-blocking D2H copy and with input-batch row moves\n"
    "        # (swap_states/condense); at a prefill-to-first-spec-decode\n"
    "        # transition GDN can consume another row's count and restore the\n"
    "        # wrong recurrent-state slot (prompt-memory loss, garbled\n"
    "        # early-EOS output). Fall through to the device-side default\n"
    "        # below: counts start at 1 and the GPU correction kernel\n"
    "        # overwrites draft-participating rows from\n"
    "        # valid_sampled_token_count. Align-mode preprocessing consumes\n"
    "        # CPU-side counts, so it keeps the synchronized path.\n"
    "        _pn370_read_cpu_accepted_counts = (\n"
    "            self.num_accepted_tokens_event is not None\n"
    "            and not (\n"
    "                self.use_async_scheduling\n"
    "                and self.cache_config.mamba_cache_mode != \"align\"\n"
    "            )\n"
    "        )\n"
    "        if _pn370_read_cpu_accepted_counts:\n"
    "            assert self.num_accepted_tokens_event is not None\n"
    "            self.num_accepted_tokens_event.synchronize()\n"
)


# ─── Runner sub-fix, variant 2: post-PN341-shaped ─────────────────────
#
# The anchor IS PN341's PN341_PREPARE_NEW exactly as PN341 writes it
# (chain convention). The replacement keeps PN341's GPU-only branch
# verbatim and re-gates ONLY the trailing event-backed ``elif`` with
# upstream's async/non-align condition.
_PN341_ELIF_TAIL = (
    "        elif self.num_accepted_tokens_event is not None:\n"
    "            self.num_accepted_tokens_event.synchronize()\n"
)
_PN370_GATED_ELIF_TAIL = (
    "        # [Genesis PN370 vendor of vllm#45100] async + non-align mamba:\n"
    "        # skip the racy CPU accepted-counts read. PN341's branch above\n"
    "        # already serves hybrid + MTP device-side; this re-gates the\n"
    "        # remaining event-backed CPU path with upstream's condition so\n"
    "        # async non-align falls through to the device-side default.\n"
    "        elif self.num_accepted_tokens_event is not None and not (\n"
    "            self.use_async_scheduling\n"
    "            and self.cache_config.mamba_cache_mode != \"align\"\n"
    "        ):\n"
    "            self.num_accepted_tokens_event.synchronize()\n"
)

PN370_PREPARE_POST_PN341_OLD = PN341_PREPARE_NEW
if (
    PN341_PREPARE_NEW.count(_PN341_ELIF_TAIL) == 1
    and PN341_PREPARE_NEW.endswith(_PN341_ELIF_TAIL)
):
    PN370_PREPARE_POST_PN341_NEW = (
        PN341_PREPARE_NEW[: -len(_PN341_ELIF_TAIL)] + _PN370_GATED_ELIF_TAIL
    )
else:
    # PN341's PREPARE NEW text changed shape — the post-PN341
    # replacement can no longer be assembled safely. Disable the
    # variant with a never-matching sentinel (the pristine variant
    # still serves PN341-disabled deployments) and fail loudly in the
    # unit test (test_post_pn341_anchor_built_from_pn341_constant).
    log.warning(
        "[PN370] PN341_PREPARE_NEW no longer ends with the expected "
        "event-backed elif tail exactly once — disabling the post-PN341 "
        "anchor variant. Re-verify PN370/PN341 composition."
    )
    PN370_PREPARE_POST_PN341_OLD = (
        "# [Genesis PN370 sentinel - post-PN341 variant disabled, "
        "PN341 PREPARE NEW drifted]\n"
    )
    PN370_PREPARE_POST_PN341_NEW = PN370_PREPARE_POST_PN341_OLD


# ─── GDN sub-fix: FULL-cudagraph metadata sized by request count ──────
PN370_GDN_BATCH_SIZE_OLD = (
    "        # Prepare tensors for cudagraph\n"
    "        # Note: m.num_actual_tokens is already padded by the model runner for CUDAGraph\n"
    "        batch_size = m.num_actual_tokens\n"
)
PN370_GDN_BATCH_SIZE_NEW = (
    "        # [Genesis PN370 vendor of vllm#45100] Size the per-request\n"
    "        # cudagraph metadata views by request count. m.num_actual_tokens\n"
    "        # is padded to the graph's token budget on FULL-graph replay\n"
    "        # (num_reqs * (K+1) under MTP K), but spec_state_indices_tensor /\n"
    "        # spec_sequence_masks / spec_query_start_loc /\n"
    "        # num_accepted_tokens (and the non-spec decode views below) are\n"
    "        # indexed by request, not by token.\n"
    "        batch_size = m.num_reqs\n"
)


def build_runner_sub_patches() -> list[TextPatch]:
    """The two runner anchor variants, required-at-least-one semantics.

    Both ``required=False``: the kernel soft-skips the variant whose
    anchor is absent and returns SKIPPED ``no_applicable_sub_patches``
    only when BOTH miss. The variants are mutually exclusive by
    construction (the post-PN341 anchor contains PN341's ``[Genesis
    PN341`` comment, absent from pristine; PN341's apply destroys the
    pristine block) — verified in
    tests/unit/integrations/spec_decode/test_pn370_async_accepted_counts_race.py.
    """
    return [
        TextPatch(
            name="pn370_skip_racy_cpu_read_pristine",
            anchor=PN370_PREPARE_PRISTINE_OLD,
            replacement=PN370_PREPARE_PRISTINE_NEW,
            required=False,
        ),
        TextPatch(
            name="pn370_skip_racy_cpu_read_post_pn341",
            anchor=PN370_PREPARE_POST_PN341_OLD,
            replacement=PN370_PREPARE_POST_PN341_NEW,
            required=False,
        ),
    ]


def build_gdn_sub_patches() -> list[TextPatch]:
    """Single required GDN anchor — SKIPs loudly rather than shipping a
    silent partial vendor when the build() region drifts."""
    return [
        TextPatch(
            name="pn370_gdn_full_cg_metadata_num_reqs",
            anchor=PN370_GDN_BATCH_SIZE_OLD,
            replacement=PN370_GDN_BATCH_SIZE_NEW,
            required=True,
        ),
    ]


def _make_runner_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(_RUNNER_REL)
    if target is None:
        return None
    return TextPatcher(
        patch_name=(
            "PN370 v1/worker/gpu_model_runner.py — skip racy CPU "
            "accepted-counts read under async non-align (vendor vllm#45100)"
        ),
        target_file=str(target),
        marker=GENESIS_PN370_MARKER,
        sub_patches=build_runner_sub_patches(),
        upstream_drift_markers=list(_RUNNER_DRIFT_MARKERS),
    )


def _make_gdn_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(_GDN_REL)
    if target is None:
        return None
    return TextPatcher(
        patch_name=(
            "PN370 v1/attention/backends/gdn_attn.py — FULL-cudagraph "
            "per-request metadata sized by num_reqs (vendor vllm#45100)"
        ),
        target_file=str(target),
        marker=GENESIS_PN370_MARKER,
        sub_patches=build_gdn_sub_patches(),
        upstream_drift_markers=list(_GDN_DRIFT_MARKERS),
    )


def _enabled() -> bool:
    return os.environ.get(
        "GENESIS_ENABLE_PN370_ASYNC_ACCEPT_RACE", ""
    ).strip().lower() in ("1", "true", "yes", "on")


def _wiring_status(
    result: TextPatchResult, failure, what: str
) -> tuple[str, str]:
    if result == TextPatchResult.APPLIED:
        return "applied", f"{what}: applied"
    if result == TextPatchResult.IDEMPOTENT:
        return "applied", f"{what}: already applied (marker present)"
    reason = failure.reason if failure else "unknown"
    detail = f" ({failure.detail})" if failure and failure.detail else ""
    if result == TextPatchResult.FAILED:
        return "failed", f"{what}: {reason}{detail}"
    return "skipped", f"{what}: {reason}{detail}"


def apply() -> tuple[str, str]:
    """Apply PN370 — vendor vllm#45100. Never raises."""
    if not _enabled():
        return "skipped", (
            "PN370 default OFF — set GENESIS_ENABLE_PN370_ASYNC_ACCEPT_RACE=1 "
            "to engage. Targets the async + MTP hybrid accepted-counts race "
            "(silent output corruption) + GDN FULL-cudagraph metadata "
            "over-sizing (vendor of OPEN PR vllm#45100)."
        )

    if vllm_install_root() is None:
        return "skipped", "vllm install root not discoverable"

    runner = _make_runner_patcher()
    if runner is None:
        return "skipped", f"PN370: {_RUNNER_REL} not resolvable"
    gdn = _make_gdn_patcher()
    if gdn is None:
        return "skipped", f"PN370: {_GDN_REL} not resolvable"

    try:
        r_result, r_failure = runner.apply()
    except Exception as e:  # noqa: BLE001 — wiring must never raise
        log.warning("[PN370] runner apply() raised %s — leaving upstream", e)
        return "skipped", f"PN370 raised at runner apply: {e!r}"
    r_status, r_reason = _wiring_status(r_result, r_failure, "runner")
    if r_status == "failed":
        return "failed", f"PN370 runner sub-fix failed: {r_reason}"

    try:
        g_result, g_failure = gdn.apply()
    except Exception as e:  # noqa: BLE001
        log.warning("[PN370] gdn apply() raised %s — leaving upstream", e)
        return "skipped", f"PN370 raised at gdn apply: {e!r}"
    g_status, g_reason = _wiring_status(g_result, g_failure, "gdn_attn")
    if g_status == "failed":
        return "failed", f"PN370 gdn sub-fix failed: {g_reason}"

    if r_status == "applied" or g_status == "applied":
        r_subs = ", ".join(runner.applied_sub_patches) or "(idempotent)"
        return "applied", (
            f"PN370 applied (vendor of OPEN PR vllm#45100): (1) "
            f"_prepare_inputs skips the racy CPU accepted-counts read under "
            f"async + non-align [{r_subs}] — kills the wrong-row GDN state "
            f"restore corruption on async + MTP hybrids and deletes the "
            f"per-step num_accepted_tokens_event.synchronize(); (2) "
            f"gdn_attn.py FULL-cudagraph per-request metadata sized by "
            f"m.num_reqs instead of token-padded m.num_actual_tokens. "
            f"runner: {r_reason} | gdn_attn: {g_reason}"
        )
    return "skipped", f"PN370: runner: {r_reason} | gdn_attn: {g_reason}"


def is_applied() -> bool:
    for rel in (_RUNNER_REL, _GDN_REL):
        target = resolve_vllm_file(rel)
        if target is None:
            continue
        try:
            if GENESIS_PN370_MARKER in open(
                str(target), encoding="utf-8"
            ).read():
                return True
        except (OSError, UnicodeDecodeError):
            continue
    return False
