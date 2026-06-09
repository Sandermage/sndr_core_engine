# SPDX-License-Identifier: Apache-2.0
"""PN351 — vendor of OPEN PR vllm#43257 (ShuaiShao93) Triton unified_attention tune for head_dim >= 512.

Triton unified attention tile-size + warps + stages tuned for very large head dims
==================================================================================

**Problem**: ``vllm/v1/attention/ops/triton_unified_attention.py``
hardcodes ``num_warps=4`` and ``num_stages=3`` in the kernel launch.
For head sizes < 256 this is the sweet spot — high occupancy, good
pipeline coverage. But for head_dim >= 512 (Gemma 4 31B uses 512;
Gemma 4 26B-A4B uses 256 + extra global heads with 512), the kernel
hits a register cliff: per-thread register pressure forces the
backend to spill or cap occupancy. Author bench on Hopper SM 9.0 + FP8:

  * head_dim=512, prefill, FP8 KV — occupancy at default 4w/3s: 6-13 %
  * head_dim=512, prefill, FP8 KV — with 8w/2s + 64-tile: 25-40 %

The same architectural class applies on Ampere SM 8.6 (A5000): same
register file size, same shared-memory layout class. The numerical
improvement transfers — actual wall-clock varies because A5000 has
6 % less SM count than A100 and 25 % of H100, but the *occupancy
fraction unlock* carries directly. Expected: ``-3-7 % decode_TPOT``
on Gemma 4 31B FP8 prefill on our PROD.

**Three changes in one method + kernel launch**:

  1. ``_get_tile_size`` (helper): add a fast-path for ``head_size >= 512
     and is_prefill and element_size == 1`` → return 64 (vs default
     32). Larger inner-K tile improves L2 reuse on large head dims.
     Restricted to FP8 element size because at BF16 the K+V shared
     memory would exceed the per-SM limit and the kernel would fail
     to launch (verified by author).

  2. ``unified_attention`` (caller): add two kwargs on the kernel
     ``triton_unified_attention[...](...)`` launch::

         num_warps=8 if head_size >= 512 else 4,
         num_stages=2 if head_size >= 512 else 3,

     8 warps spreads the accumulator across more warps relieving
     register pressure; 2-stage pipeline is shallower but uses less
     shared memory (offsetting the larger tile size).

**What our PROD hits**:

  * Gemma 4 31B FP8: head_dim=512 → all three improvements fire on
    prefill. Decode is < 32 query tokens — different tile path.
  * Gemma 4 26B-A4B FP8: standard layer head_dim=256 (no change);
    global-attention heads have head_dim=512 → improvements fire on
    the global-attention layers (every 4th layer per Gemma 4 pattern).
  * Qwen3.6 35B FP8: head_dim=128 — no change (default 32-tile + 4w/3s
    preserved).
  * Qwen3.6 27B INT4: head_dim=128 — no change.

So PN351 is a Gemma-4-specific perf win; no-op on Qwen3.6 (preserves
current well-tuned defaults).

**Why we vendor an OPEN PR**:

  * 14-LOC diff, surgical, gated by ``head_size >= 512`` so the
    Qwen / FA2 / Mamba paths see ZERO change.
  * Author bench shows real occupancy unlock; same numerical class on
    Ampere SM 8.6.
  * No interaction with shmem budget — the FP8 gate keeps the
    K+V shared-memory footprint within ~99 KiB opt-in (the same
    constraint PN345 enforces precisely).

Implementation strategy
=======================

Two atomic sub-patches on a single file
(``v1/attention/ops/triton_unified_attention.py``):

  * Sub-1 (``_get_tile_size``): replace the docstring and add the
    ``head_size >= 512 and is_prefill and element_size == 1`` branch
    BEFORE the default behaviour.
  * Sub-2 (``unified_attention`` kernel launch): add ``num_warps`` and
    ``num_stages`` kwargs on the triton kernel call. Anchored on 3
    existing kwargs (``CHUNK_SIZE``, ``USE_TD``, ``USE_TD_QO``) for
    unique-match safety.

All ``required=True``. Both must apply for the fast path to fire
end-to-end — Sub-1 sets the tile, Sub-2 sets the launch config.
Either alone is incoherent.

Composition + safety
====================

* No overlap with PN29x / PN345 (those target FLA chunk kernels — a
  different file). PN351 touches ``triton_unified_attention.py``
  which is the unified backend for full-attention layers.
* No overlap with PN340/PN341 (MTP decode bubbles — different files).
* Composes with all our existing patches.
* Risk: LOW — gated path; non-Gemma-4 models bypass it entirely.

Author: Sander (Sandermage / Aleksandr Barzov), Odessa, Ukraine.
Vendor target: vllm-project/vllm#43257 (OPEN as of 2026-06-09).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from sndr.engines.vllm.detection.guards import resolve_vllm_file
from sndr.kernel import TextPatch, TextPatcher, TextPatchResult

log = logging.getLogger("genesis.wiring.pn351_triton_unified_attention_large_head")

GENESIS_PN351_MARKER = (
    "Genesis PN351 vendor of vllm#43257 (Triton unified_attention head_dim>=512) v1"
)

_TARGET_REL = "v1/attention/ops/triton_unified_attention.py"


# ── Sub-1: _get_tile_size head_size >= 512 branch ───────────────────────
# Anchor: the function docstring + the Gemma3 branch + the default-behaviour
# comment, ensuring unique match.
PN351_TILE_OLD = (
    "    \"\"\"Select tile size with Gemma3-specific optimization.\"\"\"\n"
    "    if _is_gemma3_attention(head_size, sliding_window):\n"
    "        # Gemma3: use 32 for decode (default is 16)\n"
    "        return 32\n"
    "\n"
    "    # Default behavior\n"
    "    if is_prefill:\n"
)
PN351_TILE_NEW = (
    "    \"\"\"Select tile size with head-size-specific optimization.\n"
    "\n"
    "    [Genesis PN351 vendor of vllm#43257]: for head_dim >= 512 FP8\n"
    "    prefill (Gemma 4 31B / 26B global-attention heads), use a larger\n"
    "    inner-K tile (64 vs default 32) to improve L2 reuse. Restricted\n"
    "    to element_size == 1 (FP8) because with 2-byte dtypes the K+V\n"
    "    shared-memory footprint exceeds the per-SM limit and the kernel\n"
    "    would fail to launch.\"\"\"\n"
    "    if _is_gemma3_attention(head_size, sliding_window):\n"
    "        # Gemma3: use 32 for decode (default is 16)\n"
    "        return 32\n"
    "\n"
    "    # [Genesis PN351] head_dim >= 512 FP8 prefill: larger tile.\n"
    "    if head_size >= 512 and is_prefill and element_size == 1:\n"
    "        return 64\n"
    "\n"
    "    # Default behavior\n"
    "    if is_prefill:\n"
)


# ── Sub-2: unified_attention kernel launch — add num_warps + num_stages ──
# Anchor: existing kwargs CHUNK_SIZE/USE_TD/USE_TD_QO followed by the
# trailing `)` of the kernel call. The 3-kwarg sequence is unique in
# the file.
PN351_LAUNCH_OLD = (
    "        CHUNK_SIZE=chunk_size,\n"
    "        USE_TD=use_td,\n"
    "        USE_TD_QO=use_td_qo,\n"
    "    )\n"
)
PN351_LAUNCH_NEW = (
    "        CHUNK_SIZE=chunk_size,\n"
    "        USE_TD=use_td,\n"
    "        USE_TD_QO=use_td_qo,\n"
    "        # [Genesis PN351 vendor of vllm#43257] head_dim >= 512 hits a\n"
    "        # register cliff under default 4w/3s. 8 warps spreads the\n"
    "        # accumulator across more warps; 2-stage pipeline is shallower\n"
    "        # but uses less shmem (offsetting the larger 64-tile). Gemma 4\n"
    "        # 31B + 26B-A4B global heads benefit; Qwen3.6 head_dim=128\n"
    "        # bypasses entirely.\n"
    "        num_warps=8 if head_size >= 512 else 4,\n"
    "        num_stages=2 if head_size >= 512 else 3,\n"
    "    )\n"
)


def _env_disabled() -> bool:
    return os.environ.get("GENESIS_DISABLE_PN351", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def apply() -> tuple[str, str]:
    if _env_disabled():
        return "skipped", "PN351 disabled via GENESIS_DISABLE_PN351=1"

    target = resolve_vllm_file(_TARGET_REL)
    if target is None:
        return "skipped", f"PN351: target file {_TARGET_REL} not found"

    patcher = TextPatcher(
        patch_name="PN351 triton_unified_attention head_dim>=512 (vllm#43257)",
        target_file=str(target),
        marker=GENESIS_PN351_MARKER,
        sub_patches=[
            TextPatch(
                name="pn351_get_tile_size_large_head",
                anchor=PN351_TILE_OLD,
                replacement=PN351_TILE_NEW,
                required=True,
            ),
            TextPatch(
                name="pn351_kernel_launch_warps_stages",
                anchor=PN351_LAUNCH_OLD,
                replacement=PN351_LAUNCH_NEW,
                required=True,
            ),
        ],
        upstream_drift_markers=[
            "[Genesis PN351",
        ],
    )

    try:
        result, failure = patcher.apply()
    except Exception as e:  # noqa: BLE001
        return "failed", f"PN351 apply raised {e!r}"

    if result == TextPatchResult.FAILED:
        return "failed", f"PN351 FAILED — {failure.reason if failure else 'unknown'}"
    if result == TextPatchResult.SKIPPED:
        return "skipped", f"PN351 skipped — {failure.reason if failure else 'unknown'}"
    if result == TextPatchResult.IDEMPOTENT:
        return "applied", "PN351 idempotent (already applied)"

    n = len(patcher.applied_sub_patches)
    return "applied", (
        f"PN351 applied: {n}/2 sub-patches on triton_unified_attention.py — "
        f"head_dim >= 512 prefill (Gemma 4 31B + 26B-A4B global heads) "
        f"now uses 64-tile + 8w/2s. Expected -3-7% decode_TPOT on Gemma 4 "
        f"31B FP8. No-op on Qwen3.6 (head_dim=128). Vendor of OPEN PR vllm#43257."
    )


def is_applied() -> bool:
    target = resolve_vllm_file(_TARGET_REL)
    if target is None:
        return False
    try:
        return GENESIS_PN351_MARKER in Path(str(target)).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
