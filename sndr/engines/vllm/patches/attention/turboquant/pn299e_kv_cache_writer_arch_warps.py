# SPDX-License-Identifier: Apache-2.0
"""PN299E — arch-aware cap on the KV cache writer (``triton_reshape_and_cache_flash.py``).

CRITICAL hot-path finding (2026-06-08 loop iter):
``vllm/v1/attention/ops/triton_reshape_and_cache_flash.py`` is the KV
cache writer — fires PER TOKEN PER LAYER on every prefill and decode
step. Three independent launchers in the file set ``num_warps`` AND
``num_stages`` for the CUDA-Ampere/Hopper path:

  Launcher 1 (``_reshape_cache_per_token_head``, ~line 291):
    ``num_warps = min(16, max(1, head_size_padded // 32))``
    For Qwen3.6-A3B (head_size=256) this picks num_warps=8.

  Launcher 2 (``reshape_and_cache_kernel_flash``, ~line 398-401):
    ``num_warps = 16, num_stages = 10`` (hardcoded CUDA branch).
    The branch has ``if device_capability[0] < 9: TILE_SIZE = 512``
    but does NOT adjust ``num_warps`` / ``num_stages`` — bug upstream.

  Launcher 3 (``reshape_and_cache_kernel_flash_diffkv``, ~line 575-578):
    ``num_warps = 16, num_stages = 10`` (same hardcoded CUDA branch).

On SM 8.6 (A5000 / 3090, 100 KB shared / 64 KB L1 per SM, 64 KB max
shared per thread block):

  * num_warps=16 → 512 threads per CTA (only 32-warp programs see
    benefit, this is over-subscription on Ampere)
  * num_stages=10 → 10 pipeline buffers in flight, multiplies the
    shared/registers footprint by 10
  * Combined: massive register spill + shared overflow → autotune
    eviction → recompile → ~slow

PN299E caps both ``num_warps`` (via ``GENESIS_TRITON_AUTOTUNE_MAX_WARPS``,
PN296 default 4 on Ampere) and ``num_stages`` (via
``GENESIS_TRITON_AUTOTUNE_MAX_STAGES``, PN296 default 2 on Ampere).
Hopper+ stays at the upstream defaults via env fallback `'8'`/`'10'`.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
"""
from __future__ import annotations

import logging
import os

from sndr.engines.vllm.detection.guards import resolve_vllm_file
from sndr.kernel import TextPatch, TextPatcher, TextPatchResult

log = logging.getLogger("genesis.wiring.pn299e_kv_cache_writer")

GENESIS_PN299E_MARKER = (
    "Genesis PN299E KV cache writer arch-aware NUM_WARPS cap "
    "(SM 8.6) v2 — bench-validated stages=10 preserved"
)


# ─── Launcher 1 — _reshape_cache_per_token_head ────────────────────────
# The heuristic line. Anchor uses both the ROCm/XPU branch and the CUDA
# branch to be unique in the file.
PN299E_L1_OLD = (
    "    if current_platform.is_rocm() or current_platform.is_xpu():\n"
    "        num_warps = 4\n"
    "    else:\n"
    "        num_warps = min(16, max(1, head_size_padded // 32))\n"
    "\n"
    "    _reshape_cache_per_token_head[(num_tokens, num_kv_heads)](\n"
)
PN299E_L1_NEW = (
    "    if current_platform.is_rocm() or current_platform.is_xpu():\n"
    "        num_warps = 4\n"
    "    else:\n"
    "        # [Genesis PN299E] arch-aware cap on the upstream heuristic.\n"
    "        # PN296 auto-sets GENESIS_TRITON_AUTOTUNE_MAX_WARPS=4 on SM 8.6\n"
    "        # where 16-warp configs spill the 100 KB shared/SM budget.\n"
    "        num_warps = min(\n"
    "            min(16, max(1, head_size_padded // 32)),\n"
    "            int(__import__('os').environ.get('GENESIS_TRITON_AUTOTUNE_MAX_WARPS', '16')),\n"
    "        )\n"
    "\n"
    "    _reshape_cache_per_token_head[(num_tokens, num_kv_heads)](\n"
)


# ─── Launcher 2 — reshape_and_cache_kernel_flash ───────────────────────
# Anchor on the full ROCm/CUDA if/else block including the TILE_SIZE
# downgrade — unique in the file.
PN299E_L2_OLD = (
    "    TILE_SIZE = min(2048, triton.next_power_of_2(n))\n"
    "    if current_platform.is_rocm() or current_platform.is_xpu():\n"
    "        num_stages = 4\n"
    "        num_warps = 8\n"
    "    else:  # cuda\n"
    "        num_stages = 10\n"
    "        num_warps = 16\n"
    "        if torch.cuda.get_device_capability(key.device)[0] < 9:\n"
    "            TILE_SIZE = min(512, TILE_SIZE)\n"
)
PN299E_L2_NEW = (
    "    TILE_SIZE = min(2048, triton.next_power_of_2(n))\n"
    "    if current_platform.is_rocm() or current_platform.is_xpu():\n"
    "        num_stages = 4\n"
    "        num_warps = 8\n"
    "    else:  # cuda\n"
    "        # [Genesis PN299E v2 2026-06-09 bench-validated] arch-aware\n"
    "        # cap on num_warps only. num_stages stays at 10 — empirical\n"
    "        # bench showed capping stages crushes write-pipeline latency\n"
    "        # hiding (-8 TPS at conc=1). Capping warps alone keeps the\n"
    "        # spill-avoidance benefit (+20 TPS at conc=2) without the\n"
    "        # pipeline degradation.\n"
    "        num_stages = 10\n"
    "        num_warps = min(\n"
    "            16, int(__import__('os').environ.get('GENESIS_TRITON_AUTOTUNE_MAX_WARPS', '16')),\n"
    "        )\n"
    "        if torch.cuda.get_device_capability(key.device)[0] < 9:\n"
    "            TILE_SIZE = min(512, TILE_SIZE)\n"
)


# ─── Launcher 3 — reshape_and_cache_kernel_flash_diffkv ────────────────
# Distinct from Launcher 2: TILE_SIZE here uses ``max(head_size_k,
# head_size_v)`` instead of ``next_power_of_2(n)``, and there's no
# ``device_capability < 9`` TILE_SIZE downgrade.
PN299E_L3_OLD = (
    "    # heuristics instead of autotuning\n"
    "    TILE_SIZE = max(head_size_k, head_size_v)\n"
    "    TILE_SIZE = triton.next_power_of_2(TILE_SIZE)\n"
    "    if current_platform.is_rocm() or current_platform.is_xpu():\n"
    "        num_stages = 4\n"
    "        num_warps = 8\n"
    "    else:  # cuda\n"
    "        num_stages = 10\n"
    "        num_warps = 16\n"
)
PN299E_L3_NEW = (
    "    # heuristics instead of autotuning\n"
    "    TILE_SIZE = max(head_size_k, head_size_v)\n"
    "    TILE_SIZE = triton.next_power_of_2(TILE_SIZE)\n"
    "    if current_platform.is_rocm() or current_platform.is_xpu():\n"
    "        num_stages = 4\n"
    "        num_warps = 8\n"
    "    else:  # cuda\n"
    "        # [Genesis PN299E v2 2026-06-09 bench-validated] num_warps\n"
    "        # cap only (diffkv launcher). Same rationale as Launcher 2.\n"
    "        num_stages = 10\n"
    "        num_warps = min(\n"
    "            16, int(__import__('os').environ.get('GENESIS_TRITON_AUTOTUNE_MAX_WARPS', '16')),\n"
    "        )\n"
)


def _env_disabled() -> bool:
    return os.environ.get("GENESIS_DISABLE_PN299E", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def apply() -> tuple[str, str]:
    """Apply PN299E — cap the KV cache writer's CUDA launcher params."""
    if _env_disabled():
        return "skipped", "PN299E disabled via GENESIS_DISABLE_PN299E=1"

    target = resolve_vllm_file("v1/attention/ops/triton_reshape_and_cache_flash.py")
    if target is None:
        return "skipped", (
            "PN299E: triton_reshape_and_cache_flash.py not found in vllm "
            "install — pin may predate the v1 cache writer or have a "
            "different layout"
        )

    patcher = TextPatcher(
        patch_name=(
            "PN299E v1/attention/ops/triton_reshape_and_cache_flash.py — "
            "arch-aware NUM_WARPS+NUM_STAGES cap on 3 launchers"
        ),
        target_file=str(target),
        marker=GENESIS_PN299E_MARKER,
        sub_patches=[
            TextPatch(
                name="pn299e_l1_per_token_head",
                anchor=PN299E_L1_OLD,
                replacement=PN299E_L1_NEW,
                required=False,
            ),
            TextPatch(
                name="pn299e_l2_kernel_flash",
                anchor=PN299E_L2_OLD,
                replacement=PN299E_L2_NEW,
                required=False,
            ),
            TextPatch(
                name="pn299e_l3_kernel_flash_diffkv",
                anchor=PN299E_L3_OLD,
                replacement=PN299E_L3_NEW,
                required=False,
            ),
        ],
        upstream_drift_markers=["[Genesis PN299E", "GENESIS_TRITON_AUTOTUNE_MAX_WARPS"],
    )

    try:
        result, failure = patcher.apply()
    except Exception as e:
        log.warning("[PN299E] apply() raised %s — leaving upstream launchers", e)
        return "skipped", f"PN299E raised at apply: {e!r}"

    if result == TextPatchResult.SKIPPED:
        reason = failure.reason if failure else "anchor drift / not eligible"
        detail = f" ({failure.detail})" if failure and failure.detail else ""
        return "skipped", f"PN299E: {reason}{detail}"

    if result == TextPatchResult.FAILED:
        reason = failure.reason if failure else "unknown"
        detail = f" ({failure.detail})" if failure and failure.detail else ""
        return "failed", f"PN299E: {reason}{detail}"

    if result == TextPatchResult.IDEMPOTENT:
        return "applied", "PN299E idempotent: marker already present"

    applied = ", ".join(patcher.applied_sub_patches) or "(unknown)"
    return "applied", (
        f"PN299E applied: KV cache writer launchers capped to PN296's "
        f"GENESIS_TRITON_AUTOTUNE_MAX_WARPS / MAX_STAGES on SM 8.6 via "
        f"sub-patches [{applied}]. Closes the upstream 16-warp/10-stage "
        f"bug for Ampere on the per-token-per-layer hot path."
    )


def is_applied() -> bool:
    target = resolve_vllm_file("v1/attention/ops/triton_reshape_and_cache_flash.py")
    if target is None:
        return False
    try:
        return GENESIS_PN299E_MARKER in target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
