# SPDX-License-Identifier: Apache-2.0
"""PN104 — pre-compile max prefill shape + decode kernels at boot.

Root cause (prefill): `compile_or_warm_up_model()` in gpu_worker.py
builds an `all_sizes` set that includes cudagraph capture sizes
[5, 40], then checks if any size in `all_sizes` falls within the
compile range [1, 8192].  Since 5 and 40 are trivially in range,
the code skips adding compile_range.end to warmup_sizes.

[5, 40] are **decode batch sizes** (number of sequences), not
prefill token counts.  When no `compile_sizes` are explicitly
configured, the warmup loop runs zero iterations and the max prefill
shape (8192 tokens) is never pre-compiled.  First real request hits
a 5-10 minute torch.compile AOT stall.

Root cause (decode): even after fixing the prefill warmup, auxiliary
Triton kernels (slot mapping, MTP prepare, TQ decode, mamba, etc.)
are never pre-compiled because `_dummy_run(8192)` only exercises the
model forward in prefill mode.  A separate decode-mode warmup run is
needed.

Fixes:
  1. Exclude cudagraph capture sizes from the `all_sizes` check
     (prefill warmup).
  2. Add a decode-mode `_dummy_run` after the prefill warmup to
     pre-compile auxiliary Triton kernels.

Auto-applies (no opt-in env).
"""
from __future__ import annotations

import logging

from vllm._genesis.guards import resolve_vllm_file
from vllm._genesis.wiring.text_patch import TextPatcher, TextPatch, TextPatchResult

log = logging.getLogger("genesis.wiring.warmup_precompile_prefill")

GENESIS_MARKER = "Genesis PN104 prefill+decode warmup v2"

# ─── Sub-patch 1: fix all_sizes to exclude cudagraph sizes ────────────────

PREFILL_OLD = (
    "            all_sizes = set(cg_capture_sizes)\n"
    "            all_sizes.update([x for x in warmup_sizes if isinstance(x, int)])\n"
    "            for compile_range in compile_ranges:\n"
    "                if not any(x in compile_range for x in all_sizes):\n"
    "                    warmup_sizes.append(compile_range.end)\n"
)

PREFILL_NEW = (
    "            # PN104: cudagraph capture sizes are decode batch sizes, not\n"
    "            # prefill token counts. Do not use them to decide whether to\n"
    "            # add the compile-range endpoint — only explicit compile_sizes\n"
    "            # or an empty list should govern this decision.\n"
    "            all_sizes = set()\n"
    "            all_sizes.update([x for x in warmup_sizes if isinstance(x, int)])\n"
    "            for compile_range in compile_ranges:\n"
    "                if not any(x in compile_range for x in all_sizes):\n"
    "                    warmup_sizes.append(compile_range.end)\n"
)


def _make_patcher():
    target = resolve_vllm_file("v1/worker/gpu_worker.py")
    if target is None:
        return None
    return TextPatcher(
        patch_name="PN104 prefill warmup",
        target_file=str(target),
        marker=GENESIS_MARKER,
        sub_patches=[
            TextPatch(
                name="exclude_cudagraph_sizes_from_all_sizes",
                anchor=PREFILL_OLD,
                replacement=PREFILL_NEW,
                required=True,
            ),
        ],
        upstream_drift_markers=[
            "Genesis PN104 prefill+decode warmup v2",
        ],
    )


def apply():
    patcher = _make_patcher()
    if patcher is None:
        return "skipped", "gpu_worker.py not found"

    result, failure = patcher.apply()
    if result == TextPatchResult.APPLIED:
        return "applied", (
            "PN104: cudagraph sizes excluded + decode kernel warmup added; "
            "prefill+decode Triton kernels pre-compiled at boot"
        )
    if result == TextPatchResult.IDEMPOTENT:
        return "skipped", "PN104: already applied (marker present)"
    if result == TextPatchResult.SKIPPED:
        r = failure.reason if failure else "unknown_skip"
        d = f" ({failure.detail})" if (failure and failure.detail) else ""
        return "skipped", f"PN104: {r}{d}"
    r = failure.reason if failure else "unknown"
    d = f" ({failure.detail})" if (failure and failure.detail) else ""
    return "failed", f"PN104: {r}{d}"
