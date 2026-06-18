# SPDX-License-Identifier: Apache-2.0
"""Wiring for P18B_TEXT — TurboQuant decode stage1 kernel-literal tune.

Genesis-original. The original P18b (kernels_legacy/tq_decode_tune.py +
dispatch hook in sndr/apply/_per_patch_dispatch.py:6275) reads the
``VLLM_TQ_DECODE_{BLOCK_KV,NUM_WARPS,NUM_STAGES}`` env vars and **logs**
their resolved value, but never patches the actual Triton launcher.

Kernels-audit + root-cause workflow (2026-06-08 / 2026-06-18) flagged
this as dead code that then SILENTLY BROKE on the pin bump: the kernel was
merged upstream and reshaped from a two-branch GQA/MHA launcher into a
SINGLE launch (KEY_FP8 became a constexpr kwarg), at 8-space kwarg indent.
The original 12-space two-branch anchors stopped matching, so P18b
soft-skipped on every boot and ``num_warps`` stayed at the upstream H100
default of 1 — a single warp that cannot latency-hide the per-token MSE
centroid gather on the scalar decode path. This is the "applies-cleanly is
not the same as still-effective" failure mode: NOT a failed=0, just inert.

This patch is the missing text-patch half, re-anchored 2026-06-18 to the
single-launch form. It rewrites the launch-param tail + the ``BLOCK_KV``
local of ``vllm/v1/attention/ops/triton_turboquant_decode.py`` in place at
boot using the values from ``resolve_decode_tune()``. The SM-8.6-validated
tune is ``num_warps=8, num_stages=3, BLOCK_KV=16``, but that is a
RECOMMENDED OVERRIDE, not the shipped default: ``resolve_decode_tune()``
returns the upstream values unless ``VLLM_TQ_DECODE_NUM_WARPS=8`` /
``VLLM_TQ_DECODE_NUM_STAGES=3`` / ``VLLM_TQ_DECODE_BLOCK_KV=16`` are set in
the environment. Without those env vars this patch rewrites the launcher to
the same upstream literals (inert). Set the env to realise the SM-8.6 tune.

Expected impact (HIGH confidence on the fix actually applying, MEDIUM
on the TPS number): +3-8 % on 35B-A3B-FP8 + TQ k8v4 + MTP K=3. Bench
A/B before promoting from experimental.

Safety:
  - Exact text-anchor match, soft-skip on drift.
  - Per-branch (GQA / MHA) sub-patches, both optional — partial-apply
    is allowed (some pins ship only one branch).
  - Operator override ``GENESIS_DISABLE_P18B_TEXT=1`` keeps upstream
    literals; ``VLLM_TQ_DECODE_NUM_WARPS`` / ``VLLM_TQ_DECODE_NUM_STAGES``
    flow through ``resolve_decode_tune()`` and tune the replacement.
  - Self-suppresses on non-NVIDIA / pre-Ampere via
    ``tq_decode_tune.should_apply()``.
  - Idempotent marker — re-apply is a no-op.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa
"""
from __future__ import annotations

import logging
import os

from sndr.engines.vllm.detection.guards import resolve_vllm_file
from sndr.engines.vllm.kernels_legacy.tq_decode_tune import (
    resolve_decode_tune,
    should_apply as tq_should_apply,
)
from sndr.kernel import TextPatch, TextPatcher, TextPatchResult

log = logging.getLogger("genesis.wiring.p18b_kernel_literals_textpatch")

GENESIS_P18B_TEXT_MARKER = (
    "Genesis P18b TEXT TurboQuant decode stage1 kernel-literal tune "
    "(SM 8.6 num_warps/num_stages override)"
)


# 2026-06-18 RE-ANCHOR for pin 0.23.1+ (dev101/dev148): the kernel was
# merged upstream into vllm/v1/attention/ops/triton_turboquant_decode.py
# as a SINGLE launch (KEY_FP8 is a constexpr kwarg, so there is no longer a
# two-branch GQA/MHA launcher). The old 12-space two-branch anchors below
# never matched the 8-space single launch -> P18b silently soft-skipped on
# every boot and num_warps stayed at the upstream H100 default of 1. The
# single launch block ends with FP8_E4B15 / num_warps=1 / num_stages=1 / `)`
# at 8-space kwarg indent (verified byte-exact on the live dev148 image).

# Launch-param tail — unique 8-space block that closes the _tq_decode_stage1
# launch. Anchored on the FP8_E4B15 + num_warps + num_stages + close-paren
# tail so it matches regardless of the (long, stable) kwarg list above it.
P18B_LAUNCH_OLD = (
    "        FP8_E4B15=fp8_e4b15,\n"
    "        num_warps=1,\n"
    "        num_stages=1,\n"
    "    )\n"
)

# BLOCK_KV tile size — set as a plain Python local just above the launch.
# Upstream ships 4 (the kernel signature comment even says "tokens per
# tile (16)"); retuning to 16 amortises the per-tile centroid-gather fixed
# cost over 4x more KV tokens.
P18B_BLOCK_KV_OLD = "    BLOCK_KV = 4\n"


def _build_launch_replacement(num_warps: int, num_stages: int) -> str:
    """Render the new single-launch tail with our resolved SM 8.6 tune."""
    note = (
        "        # [Genesis P18b TEXT, 2026-06-18] single-launch tune for\n"
        "        # Ampere SM 8.6 (RTX A5000 / 3090). Upstream ships\n"
        "        # num_warps=1/num_stages=1 (H100-shaped) -> 1 warp cannot\n"
        "        # latency-hide the per-token MSE centroid gather. Override\n"
        "        # via VLLM_TQ_DECODE_NUM_WARPS / _NUM_STAGES (tq_decode_tune).\n"
    )
    return (
        "        FP8_E4B15=fp8_e4b15,\n"
        + note
        + f"        num_warps={num_warps},\n"
        + f"        num_stages={num_stages},\n"
        + "    )\n"
    )


def _make_patcher() -> TextPatcher | None:
    target = resolve_vllm_file("v1/attention/ops/triton_turboquant_decode.py")
    if target is None:
        return None

    bkv, num_warps, num_stages = resolve_decode_tune()

    launch_new = _build_launch_replacement(num_warps, num_stages)
    block_kv_new = (
        f"    BLOCK_KV = {bkv}  # [Genesis P18b TEXT, 2026-06-18] SM 8.6 tile\n"
    )

    return TextPatcher(
        patch_name=(
            "P18b TEXT v1/attention/ops/triton_turboquant_decode.py — "
            "kernel-literal tune (num_warps/num_stages/BLOCK_KV SM 8.6)"
        ),
        target_file=str(target),
        marker=GENESIS_P18B_TEXT_MARKER,
        sub_patches=[
            TextPatch(
                name="p18b_text_single_launch_tune",
                anchor=P18B_LAUNCH_OLD,
                replacement=launch_new,
                required=False,
            ),
            TextPatch(
                name="p18b_text_block_kv_tune",
                anchor=P18B_BLOCK_KV_OLD,
                replacement=block_kv_new,
                required=False,
            ),
        ],
        upstream_drift_markers=["[Genesis P18b TEXT"],
    )


def _env_disabled() -> bool:
    return os.environ.get("GENESIS_DISABLE_P18B_TEXT", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def apply() -> tuple[str, str]:
    """Apply P18b TEXT — text-patch the TQ decode launch literals."""
    if _env_disabled():
        return "skipped", (
            "P18b TEXT disabled via GENESIS_DISABLE_P18B_TEXT=1 — leaving "
            "upstream H100-default kernel launch params"
        )

    if not tq_should_apply():
        return "skipped", (
            "P18b TEXT: TurboQuant not applicable on this device "
            "(non-CUDA or pre-Ampere) — kernel literals not patched"
        )

    patcher = _make_patcher()
    if patcher is None:
        return "skipped", (
            "P18b TEXT: triton_turboquant_decode.py not found in vllm "
            "install — pin may predate TurboQuant or have a different layout"
        )

    bkv, num_warps, num_stages = resolve_decode_tune()

    try:
        result, failure = patcher.apply()
    except Exception as e:  # never raise out of an apply hook
        log.warning(
            "[P18b TEXT] apply() raised %s — leaving upstream kernel literals",
            e,
        )
        return "skipped", f"P18b TEXT raised at apply: {e!r}"

    if result == TextPatchResult.SKIPPED:
        reason = failure.reason if failure else "anchor drift / not eligible"
        detail = f" ({failure.detail})" if failure and failure.detail else ""
        return "skipped", (
            f"P18b TEXT: {reason}{detail}. Resolved tune was "
            f"BLOCK_KV={bkv} num_warps={num_warps} num_stages={num_stages}; "
            f"kernel literals NOT overridden — upstream H100 defaults remain."
        )

    if result == TextPatchResult.FAILED:
        reason = failure.reason if failure else "unknown"
        detail = f" ({failure.detail})" if failure and failure.detail else ""
        return "failed", f"P18b TEXT: {reason}{detail}"

    if result == TextPatchResult.IDEMPOTENT:
        return "applied", (
            f"P18b TEXT idempotent: marker already present (num_warps="
            f"{num_warps} num_stages={num_stages} previously installed)."
        )

    applied = ", ".join(patcher.applied_sub_patches) or "(unknown)"
    return "applied", (
        f"P18b TEXT applied: TQ decode stage1 launch literals overridden "
        f"to num_warps={num_warps} num_stages={num_stages} via sub-patches "
        f"[{applied}]. Closes the dead-code finding (upstream H100 defaults "
        f"4/2 + 1/1 were silently in use despite env overrides; tq_decode_tune "
        f"was logging-only)."
    )


def is_applied() -> bool:
    """Best-effort check by reading the target file for our marker."""
    target = resolve_vllm_file("v1/attention/ops/triton_turboquant_decode.py")
    if target is None:
        return False
    try:
        return GENESIS_P18B_TEXT_MARKER in target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
