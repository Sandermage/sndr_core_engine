# SPDX-License-Identifier: Apache-2.0
"""PN398 — fix the async spec-decode accepted-counts race (vllm#45100 backport).

RETIRED 2026-07-05 (lifecycle: retired, capped <0.23.1rc1.dev714): vllm#45100
MERGED 2026-06-22 (merge commit cec2ec1176) and both hunks are byte-identical
NATIVE in the pristine dev748 tree (gpu_model_runner.py:2057-2062 carries the
same ``needs_cpu_accepted_counts`` guard; gdn_attn.py:413-416 the same
``batch_size = m.num_reqs`` sizing) — deep-diff outcome (a). The patch had
already been self-skipping via its own ``needs_cpu_accepted_counts`` drift
marker. Kept for reference / pins that predate the merge. Twin of PN370
(the 0.22.x vendor variant, retired the same day).

================================================================
PROBLEM (vLLM 0.23.x regression for hybrid GDN/Mamba + MTP)
================================================================

On vLLM 0.23.x, async scheduling became the DEFAULT for MTP/EAGLE
speculative decoding (PRs #27614, #31998). This routed hybrid models with
``mamba_cache_mode="none"`` (our Qwen3.6-35B-A3B TurboQuant k8v4 + MTP K=3
config) through a RACY ``num_accepted_tokens`` path in ``_prepare_inputs``:

  ``_update_states_after_model_execute`` writes accepted-token counts from
  GPU to ``input_batch.num_accepted_tokens_cpu_tensor`` with a NON-BLOCKING
  D2H copy. Under async scheduling the next ``_prepare_inputs`` reads a STALE
  CPU copy of that tensor — and ``condense()`` may have reordered the
  input-batch rows. At a request's prefill -> first-spec-decode transition,
  GDN's ``causal_conv1d`` restores the recurrent (conv/SSM) state from the
  WRONG slot (``conv_state_token_offset = num_accepted_tokens - 1``) -> the
  request loses its prompt memory -> the model emits a degenerate
  constant-token loop, which the greedy verifier rubber-stamps (~93% accept).
  K=1 loops too. MTP-OFF is unaffected (no spec-decode path).

The GDN/conv kernel SOURCE is byte-identical to the last-working pin
(0.22.1rc1.dev491+g1033ffac2): the *exercise* changed (async default), not
the code. Confirmed live: ``--no-async-scheduling`` makes MTP K=3 generate
correctly (content + finish=stop) on the otherwise-broken pin.

A second, independent FULL-cudagraph bug also corrupts the metadata tail:
``gdn_attn.build()`` sized per-request tensors by ``m.num_actual_tokens``
(token-padded for FULL graph replay) instead of ``m.num_reqs``.

================================================================
FIX (vllm#45100 cherry-pick — OPEN, verified, approved upstream)
================================================================

Two surgical text-patches that KEEP async scheduling ON (its perf overlap):

  1. ``gpu_model_runner.py``: guard the CPU accepted-counts sync behind
     ``needs_cpu_accepted_counts`` — skip it under async + non-align, default
     ``num_accepted_tokens`` to 1 and let the existing GPU correction
     (``update_num_computed_tokens_for_batch_change``) overwrite draft rows.

  2. ``gdn_attn.py``: size per-request cudagraph metadata by ``m.num_reqs``,
     not the token-padded ``m.num_actual_tokens``.

================================================================
SCOPE
================================================================

Active when ``GENESIS_ENABLE_PN398_ASYNC_ACCEPTED_RACE=1``. Hybrid + spec
only. Auto-no-ops once #45100 lands upstream (drift marker
``needs_cpu_accepted_counts``). Boot-time text-patch, not hot-path.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
"""
from __future__ import annotations

import logging
import os

from sndr.engines.vllm.detection.guards import resolve_vllm_file, vllm_install_root
from sndr.kernel import (
    TextPatch,
    TextPatcher,
    TextPatchResult,
)

log = logging.getLogger("genesis.wiring.pn398_async_accepted_counts_race")

GENESIS_PN398_MARKER = "Genesis PN398 vllm#45100 async accepted-counts race"


def _is_enabled() -> bool:
    return os.environ.get(
        "GENESIS_ENABLE_PN398_ASYNC_ACCEPTED_RACE", ""
    ).strip().lower() in ("1", "true", "yes", "on")


# ─── Anchor 1: vllm/v1/worker/gpu_model_runner.py — the racy CPU sync ──────

GMR_OLD = (
    "        if self.num_accepted_tokens_event is not None:\n"
    "            self.num_accepted_tokens_event.synchronize()\n"
)
GMR_NEW = (
    "        # [Genesis PN398 vllm#45100 async accepted-counts race] skip the\n"
    "        # racy CPU num_accepted_tokens sync under async scheduling\n"
    "        # (non-align): the CPU copy races the in-flight D2H copy and the\n"
    "        # condense() input-batch row moves -> stale accepted count -> GDN\n"
    "        # recurrence restored from the wrong slot -> prompt-memory-loss\n"
    "        # constant-token loop. Default to 1; the GPU correction\n"
    "        # (update_num_computed_tokens_for_batch_change) overwrites draft\n"
    "        # rows from valid_sampled_token_count.\n"
    "        needs_cpu_accepted_counts = (\n"
    "            self.num_accepted_tokens_event is not None\n"
    "            and not (\n"
    "                self.use_async_scheduling\n"
    "                and self.cache_config.mamba_cache_mode != \"align\"\n"
    "            )\n"
    "        )\n"
    "        if needs_cpu_accepted_counts:\n"
    "            assert self.num_accepted_tokens_event is not None\n"
    "            self.num_accepted_tokens_event.synchronize()\n"
)

# ─── Anchor 2: vllm/v1/attention/backends/gdn_attn.py — token-padded size ──

GDN_OLD = (
    "        # Note: m.num_actual_tokens is already padded by the model runner for CUDAGraph\n"
    "        batch_size = m.num_actual_tokens\n"
)
GDN_NEW = (
    "        # [Genesis PN398 vllm#45100] per-request cudagraph metadata is\n"
    "        # indexed by request; m.num_actual_tokens is token-padded for FULL\n"
    "        # graph replay and must NOT size spec_state/query/accepted tensors.\n"
    "        batch_size = m.num_reqs\n"
)


def _make_gmr_patcher() -> TextPatcher | None:
    target = resolve_vllm_file("v1/worker/gpu_model_runner.py")
    if target is None:
        return None
    return TextPatcher(
        patch_name="PN398 gpu_model_runner.py — async accepted-counts guard",
        target_file=str(target),
        marker=GENESIS_PN398_MARKER,
        sub_patches=[
            TextPatch(name="pn398_gmr_guard", anchor=GMR_OLD,
                      replacement=GMR_NEW, required=True),
        ],
        # `needs_cpu_accepted_counts` is the variable name #45100 introduces.
        # `condense() reordered indices` is the comment the IN-PIN async fix
        # (#42347, present on dev148) writes into _prepare_inputs: dev148
        # already remaps num_accepted_tokens via self.prev_positions after
        # condense(), so PN398's guard would CONFLICT with it (skip the sync ->
        # all-1 accepted-counts corruption). Either marker makes PN398 self-skip
        # on dev148. The marker is disjoint from PN398's own GMR_NEW (verified).
        upstream_drift_markers=[
            "needs_cpu_accepted_counts",
            "condense() reordered indices",
        ],
    )


def _make_gdn_patcher() -> TextPatcher | None:
    target = resolve_vllm_file("v1/attention/backends/gdn_attn.py")
    if target is None:
        return None
    return TextPatcher(
        patch_name="PN398 gdn_attn.py — per-request cudagraph metadata size",
        target_file=str(target),
        marker=GENESIS_PN398_MARKER + " :: gdn_attn.py",
        sub_patches=[
            TextPatch(name="pn398_gdn_num_reqs", anchor=GDN_OLD,
                      replacement=GDN_NEW, required=True),
        ],
        upstream_drift_markers=[],
    )


def apply() -> tuple[str, str]:  # noqa: PLR0911 - dispatcher early-return cascade: distinct skip/self-retire reasons per gate
    """Apply the vllm#45100 backport (async accepted-counts race). All-or-nothing."""
    from sndr.dispatcher import log_decision, should_apply
    decision, reason = should_apply("PN398")
    log_decision("PN398", decision, reason)
    if not decision:
        return "skipped", reason

    if vllm_install_root() is None:
        return "skipped", "vllm install root not discoverable"

    patchers = [_make_gmr_patcher(), _make_gdn_patcher()]
    if any(p is None for p in patchers):
        return "skipped", "one or more target files not found"

    # Pre-flight: confirm anchors/markers before any write (avoid half-apply).
    for p in patchers:
        if not os.path.isfile(p.target_file):
            return "skipped", f"target disappeared: {p.target_file}"
        with open(p.target_file) as f:
            content = f.read()
        if p.marker in content:
            continue  # idempotent
        for m in p.upstream_drift_markers:
            if m in content:
                return (
                    "skipped",
                    f"upstream drift marker {m!r} in {p.target_file} — "
                    "vllm#45100 likely already merged/backported.",
                )
        for sp in p.sub_patches:
            if sp.required and sp.anchor not in content:
                return (
                    "skipped",
                    f"required anchor for {sp.name!r} not found in "
                    f"{p.target_file} — anchor drifted, PN398 cannot apply.",
                )

    results = []
    for p in patchers:
        result, failure = p.apply()
        if result == TextPatchResult.FAILED:
            return "failed", (
                f"{p.patch_name}: {failure.reason if failure else 'unknown'} "
                f"({failure.detail if failure else ''})"
            )
        results.append((p.patch_name, result))

    applied = sum(1 for _, r in results if r == TextPatchResult.APPLIED)
    idempotent = sum(1 for _, r in results if r == TextPatchResult.IDEMPOTENT)
    return "applied", (
        f"PN398 applied: {applied} modified, {idempotent} idempotent. Async "
        "spec-decode accepted-counts race fixed (vllm#45100); async scheduling "
        "stays ON. Hybrid GDN/Mamba + MTP recurrence restored from the correct "
        "slot — no more constant-token loop."
    )


def is_applied() -> bool:
    target = resolve_vllm_file("v1/worker/gpu_model_runner.py")
    if target is None or not os.path.isfile(str(target)):
        return False
    with open(str(target)) as f:
        return GENESIS_PN398_MARKER in f.read()


__all__ = ["GENESIS_PN398_MARKER", "apply", "is_applied"]
