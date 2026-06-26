# SPDX-License-Identifier: Apache-2.0
"""PN372 — eagle_step zero/negative-seqlen slot-mapping guard (vendor of vllm#45005).

Upstream bug class (vllm#40756, vllm#39295): the fused EAGLE/MTP
draft-step slot-mapping kernel ``eagle_step_slot_mapping_metadata_kernel``
in ``v1/spec_decode/utils.py`` advances EVERY row with
``req_idx < batch_size``, including inactive padding rows inside the
captured batch whose ``seq_lens`` entry is 0. Those rows carry
``block_table`` entries of ``-1``; computing
``slot_id = block_id * block_size + offset`` from a ``-1`` block id
produces an invalid slot mapping, which surfaces later in the MTP/EAGLE
draft loop as CUDA illegal memory access / device-side asserts. This is
the exact crash class observed on our 262-280K-token agent sessions
(Qwen3.6-35B FP8 hybrid GDN + MTP K=3 + async-scheduling, TP=2).

Vendor of OPEN PR vllm#45005 (ashishpatel26, studied via ``gh pr view`` +
``gh pr diff`` 2026-06-11): early-return for inactive rows — write
``PADDING_SLOT_ID`` to the slot mapping, zero the clamped position, and
leave the row's sequence length untouched. The PR also hoists the
``seq_len`` load above the guard so the later "update seq_lens" block
reuses it; we vendor that hoist as an optional dedup sub-patch.

Genesis divergence — STRICTER guard (documented per iron rule #10):
upstream #45005 guards ``seq_len == 0``; we guard ``seq_len <= 0``.
#40756-class traces also showed NEGATIVE sequence lengths on corrupted
rows (in-place ``seq_lens`` updates racing with async scheduling can
drive a parked row below zero); a negative length row is just as
inactive as a zero one and must not be advanced into a real request.
``<= 0`` subsumes upstream's check at identical kernel cost (one
register compare on an already-loaded value).

P108 retirement criterion (roadmap chunk-3 Theme A, 2026-06-11):
P108 (vendor of vllm#42603) works around the SAME #40756 crash class by
synchronizing the draft-loop stream — a symptom patch upstream rejected
as not root-caused. SUCCESS CRITERION for retiring P108: with PN372
enabled, an A/B on the 35B PROD profile (MTP K=3, long-context agent
workload) shows the IMA class gone with P108 OFF -> P108's per-step
synchronize is redundant and retiring it recovers the 2-6% TPOT it
costs. The A/B is PLANNED; this module does NOT touch P108 — both can
run together safely (different files, orthogonal mechanisms).
Sibling: P58 (#40768 async-scheduler -1 placeholder root-cause fix).

Rebind analysis (verified against pristine pin g303916e93): the kernel
is a module-level ``@triton.jit`` function referenced ONLY by
``eagle_step_update_slot_mapping_and_metadata`` in the SAME file;
``llm_base_proposer.py`` imports that wrapper, so a source-level text
patch applied before import needs NO runtime rebind. The CPU worker
(``cpu_model_runner.py``) rebinds the kernel to the SGL CPU shim — out
of scope (we run CUDA; the CPU shim never sees padded CUDA-graph rows).

Activation: opt-in via ``GENESIS_ENABLE_PN372_EAGLE_ZERO_SEQLEN_GUARD=1``
(default OFF until the planned A/B bench cycle together with PN370 —
roadmap: land both in the same cycle to harden the full MTP K=3 failure
chain). Self-skips when #45005 (or an equivalently-worded guard) lands
upstream: drift markers below are exact substrings of the PR's form.

Author backport: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
Vendor target: vllm-project/vllm#45005 (OPEN as of 2026-06-11).
"""
from __future__ import annotations

import logging

from sndr.engines.vllm.detection.guards import resolve_vllm_file
from sndr.kernel import TextPatch, TextPatcher, result_to_wiring_status

log = logging.getLogger("genesis.wiring.pn372_eagle_step_zero_seqlen_guard")

GENESIS_PN372_MARKER = (
    "Genesis PN372 eagle_step zero-seqlen slot-mapping guard "
    "(vendor of vllm#45005) v1"
)

_TARGET_REL = "v1/spec_decode/utils.py"

# Drift markers — exact substrings of #45005's form, taken from
# `gh pr diff 45005` on 2026-06-11. Absent in the pristine pin tree
# (g303916e93: both count 0, byte-verified) and deliberately NOT
# substrings of our own replacement texts: our guard reads
# `if seq_len <= 0:` (never `== 0`) and our comment block is original
# wording (lint_drift_markers self-collision contract).
_DRIFT_MARKERS = (
    # The PR's comment pair right above its guard.
    "    # Padded rows inside the captured batch can have seq_lens == 0 and\n"
    "    # block_table entries of -1. Do not advance them into a real request.\n",
    # The PR's structural guard head (== 0 vs our <= 0).
    "    if seq_len == 0:\n"
    "        tl.store(out_clamped_positions_ptr + req_idx, 0)\n",
)

# ── Sub-patch 1 (required): the guard ────────────────────────────────
# Anchor: cudagraph-padding early-return + the position load that
# follows it. Unique in the file (count==1 byte-verified against
# /private/tmp/candidate_pin_current/vllm at pin g303916e93).

PN372_GUARD_OLD = (
    "    if req_idx >= batch_size:\n"
    "        tl.store(out_slot_mapping_ptr + req_idx, PAD_ID)\n"
    "        return\n"
    "\n"
    "    # Load current position and increment\n"
    "    position = tl.load(positions_ptr + req_idx)\n"
)

PN372_GUARD_NEW = (
    "    if req_idx >= batch_size:\n"
    "        tl.store(out_slot_mapping_ptr + req_idx, PAD_ID)\n"
    "        return\n"
    "\n"
    "    # [Genesis PN372 vendor of vllm#45005] Inactive rows inside the\n"
    "    # captured batch are not real requests: their block_table row is\n"
    "    # all -1, and advancing them computes slot ids from garbage block\n"
    "    # ids -> CUDA illegal memory access / device-side assert later in\n"
    "    # the MTP/EAGLE draft loop (vllm#40756 class). Park the row:\n"
    "    # clamped position 0, PADDING_SLOT_ID slot, seq_lens untouched.\n"
    "    # STRICTER than upstream's `== 0` guard: #40756-class traces also\n"
    "    # showed NEGATIVE sequence lengths on corrupted rows, so any\n"
    "    # non-positive length is treated as inactive.\n"
    "    seq_len = tl.load(seq_lens_ptr + req_idx)\n"
    "    if seq_len <= 0:\n"
    "        tl.store(out_clamped_positions_ptr + req_idx, 0)\n"
    "        tl.store(out_slot_mapping_ptr + req_idx, PAD_ID)\n"
    "        return\n"
    "\n"
    "    # Load current position and increment\n"
    "    position = tl.load(positions_ptr + req_idx)\n"
)

# ── Sub-patch 2 (optional): dedup the now-hoisted seq_len load ───────
# Parity with #45005's hoist. A second load of the same value is
# redundant but harmless, so this sub-patch never aborts the guard
# (required=False) if its anchor drifts.

PN372_DEDUP_OLD = (
    "    # Update seq_lens: +1 normally, or 1 if exceeded\n"
    "    seq_len = tl.load(seq_lens_ptr + req_idx)\n"
    "    new_seq_len = tl.where(exceeds_max, 1, seq_len + 1)\n"
)

PN372_DEDUP_NEW = (
    "    # Update seq_lens: +1 normally, or 1 if exceeded\n"
    "    # [Genesis PN372 vendor of vllm#45005] seq_len already loaded by\n"
    "    # the zero/negative-seqlen guard above — reuse it (parity with\n"
    "    # the upstream PR, which hoists this load).\n"
    "    new_seq_len = tl.where(exceeds_max, 1, seq_len + 1)\n"
)


def _make_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(_TARGET_REL)
    if target is None:
        return None
    return TextPatcher(
        patch_name=(
            "PN372 v1/spec_decode/utils.py — eagle_step zero/negative-"
            "seqlen slot-mapping guard (vendor of vllm#45005)"
        ),
        target_file=str(target),
        marker=GENESIS_PN372_MARKER,
        sub_patches=[
            TextPatch(
                name="pn372_zero_seqlen_guard",
                anchor=PN372_GUARD_OLD,
                replacement=PN372_GUARD_NEW,
                required=True,
            ),
            TextPatch(
                name="pn372_seq_len_load_dedup",
                anchor=PN372_DEDUP_OLD,
                replacement=PN372_DEDUP_NEW,
                required=False,
            ),
        ],
        upstream_drift_markers=list(_DRIFT_MARKERS),
    )


def apply() -> tuple[str, str]:
    """Apply PN372 — eagle_step zero/negative-seqlen guard. Never raises.

    Opt-in: gated through the dispatcher on
    ``GENESIS_ENABLE_PN372_EAGLE_ZERO_SEQLEN_GUARD`` (default_on=False
    in the registry — pending the PN370+PN372 bench cycle).
    """
    from sndr.dispatcher import log_decision, should_apply

    decision, reason = should_apply("PN372")
    log_decision("PN372", decision, reason)
    if not decision:
        return "skipped", reason

    patcher = _make_patcher()
    if patcher is None:
        return "skipped", f"PN372: target file {_TARGET_REL} not found"

    result, failure = patcher.apply()
    return result_to_wiring_status(
        result, failure,
        applied_message=(
            "PN372 applied: eagle_step slot-mapping kernel now parks "
            "inactive rows (seq_len <= 0, STRICTER than vllm#45005's "
            "== 0) at PADDING_SLOT_ID instead of advancing them through "
            "a -1 block_table row. Kills the #40756-class CUDA IMA on "
            "long MTP sessions. Success criterion for retiring P108's "
            "draft-loop synchronize — A/B planned, P108 untouched."
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
