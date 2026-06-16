# SPDX-License-Identifier: Apache-2.0
"""PN-FP8MOE-KPAD — FP8-core backport of vllm#45703.

Extend Marlin thread-tile padding to the MoE *intermediate* dim (FP8)
=====================================================================

vllm PR #45703 ("[Kernel] Extend Marlin thread-tile padding to MoE
(WNA16 + FP8/MXFP8)", OPEN) pads a tile-misaligned MoE intermediate size
to the next valid Marlin thread tile at WEIGHT PREP, so an FP8 MoE layer
whose intermediate dim is not a multiple of 64 can USE the fast Marlin
kernel instead of crashing with `Invalid thread config ... MKN=[16384,
352,2816] num_bits=8 group_size=-1` (the DiffusionGemma N=352 crash;
352 % 64 == 32) or falling back to the slow WNA16 path.

Why this is a clean, model-agnostic, prep-level fix
---------------------------------------------------

The pad is a pure SHAPE PROBE at prep: ``marlin_moe_padded_intermediate``
returns N unchanged for an already-tile-aligned N (e.g. the PROD 35B's
intermediate). When ``padded_n == n`` the whole prep-pad block is a
no-op — ZERO hot-path cost, NO 35B regression even when the patch is
enabled. The gate is NOT a gemma4 arch gate; it is intrinsic to the
shape. Aligned sizes pass through untouched; only misaligned sizes
(DiffusionGemma) get zero-padded to the next %64 tile.

Padded region self-cancels: w13's padded output channels are zeroed by
zero-padded scales (FP8 zero decodes to 0.0), so the padded inputs to w2
are zero. The pad multiple is ``lcm(64, group_size)`` (NOT %128 — that is
the dense P87/#40361 sibling; this patch must NOT double-pad on top of
the round_up base that dev491 already carries).

FP8-CORE SCOPE — exactly 3 vLLM files
-------------------------------------

  1. quantization/utils/marlin_utils.py
       + def marlin_moe_padded_intermediate(intermediate_size, group_size=-1)
       + widen check_moe_marlin_supports_layer(..., allow_tile_padding=False)
  2. quantization/utils/marlin_utils_fp8.py
       + _moe_pad_shard_rows + _moe_pad_last helpers
       + import marlin_moe_padded_intermediate
       + padded_n compute + w13/w2 pad + CONVERTED-SCALE pad in
         prepare_fp8_moe_layer_for_marlin (incl. the block-FP8 scale-row
         padding club-3090 punts on)
  3. compressed_tensors_moe/compressed_tensors_moe.py
       + allow_tile_padding=(not is_actorder) on the supports-layer check
         so the misaligned FP8 layer USES fast Marlin instead of WNA16

The mxfp8 hunk (prepare_mxfp8_moe_layer_for_marlin) and the INT-WNA16
oracle module that the current #45703 HEAD additionally touches are OUT
OF FP8-CORE SCOPE — this patch does NOT touch them.

Base already present on dev491 (PR45295 dense base): round_up, math,
marlin_padded_nk, marlin_pad_*. ``marlin_moe_padded_intermediate`` is
ABSENT (the FP8-core delta we add). VERIFIED 2026-06-17 against the live
dev491 container (vllm-qwen3.6-35b-balanced-k3, image
vllm/vllm-openai:nightly-1033ffac2).

Retirement
----------

The marlin_utils patcher carries the upstream-merge drift marker
``def marlin_moe_padded_intermediate`` — once #45703 merges, that def
exists upstream on a pristine file and the whole patch self-skips
(iron-rule-#11 outcome (a) boundary). The fp8 / moe_method patchers use
upstream-side markers (``_moe_pad_shard_rows`` / ``allow_tile_padding=``)
for the same self-skip.

Safety model
------------

  - default OFF; opt-in via GENESIS_ENABLE_PN_FP8MOE_KPAD=1. NOT yet
    rig-validated (DiffusionGemma boot + 35B regression bench are
    operator-gated), so committing is zero-risk.
  - Intrinsically shape-gated (padded_n == n -> no change).
  - All sub-patches required (textual integrity).
  - Idempotent via per-file marker; drift-aware on #45703 merge.

Author backport: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
Upstream PR: vllm#45703 (OPEN).
"""
from __future__ import annotations

import logging
import os

from sndr.engines.vllm.detection.guards import resolve_vllm_file, vllm_install_root
from sndr.kernel import TextPatch, TextPatcher, TextPatchResult

log = logging.getLogger("genesis.wiring.pn_fp8moe_kpad_marlin_moe")

GENESIS_PN_FP8MOE_KPAD_MARKER = (
    "Genesis PN-FP8MOE-KPAD FP8-core backport of vllm#45703 "
    "(Marlin MoE intermediate thread-tile pad) v1"
)

# ── Target files (dev491 site-packages layout). ──────────────────────────
MARLIN_UTILS_REL = (
    "model_executor/layers/quantization/utils/marlin_utils.py"
)
MARLIN_UTILS_FP8_REL = (
    "model_executor/layers/quantization/utils/marlin_utils_fp8.py"
)
COMPRESSED_TENSORS_MOE_REL = (
    "model_executor/layers/quantization/compressed_tensors/"
    "compressed_tensors_moe/compressed_tensors_moe.py"
)


# ═════════════════════════════════════════════════════════════════════════
# FILE 1 — marlin_utils.py
# ═════════════════════════════════════════════════════════════════════════
#
# Sub-patch 1a: insert marlin_moe_padded_intermediate ABOVE the
# check_moe_marlin_supports_layer def AND widen that def's signature to
# accept allow_tile_padding=False. Anchored on the verbatim dev491 def
# line (count==1 in dev491; the new func is ABSENT so this is unique).

MARLIN_UTILS_ADD_FUNC_OLD = (
    "def check_moe_marlin_supports_layer(layer: RoutedExperts, group_size: int) -> bool:\n"
)

MARLIN_UTILS_ADD_FUNC_NEW = (
    "def marlin_moe_padded_intermediate(intermediate_size: int, group_size: int = -1) -> int:\n"
    "    # [Genesis PN-FP8MOE-KPAD vllm#45703 backport] Smallest MoE\n"
    "    # intermediate size satisfying the Marlin MoE thread tiles. The kernel\n"
    "    # needs gate-up 2*intermediate % 128 == 0 and down intermediate % 64\n"
    "    # == 0, i.e. intermediate % 64 == 0. A misaligned size is zero-padded\n"
    "    # to the next valid tile at weight prep, kept a multiple of group_size\n"
    "    # so the group count stays integral. The padded region never reaches\n"
    "    # the MoE output: w13's padded output channels are zeroed by the\n"
    "    # zero-padded scales, so the padded inputs to w2 are zero.\n"
    "    group = group_size if group_size > 0 else 1\n"
    "    padded = round_up(intermediate_size, math.lcm(64, group))\n"
    "    if padded != intermediate_size:\n"
    "        logger.warning_once(\n"
    "            \"Marlin requires thread-tile padding for the MoE intermediate \"\n"
    "            \"size of some layers in this model. Padded experts pad/slice \"\n"
    "            \"activations on every forward; performance may be degraded.\"\n"
    "        )\n"
    "    return padded\n"
    "\n"
    "\n"
    "def check_moe_marlin_supports_layer(\n"
    "    layer: RoutedExperts, group_size: int, allow_tile_padding: bool = False\n"
    ") -> bool:\n"
)

# Sub-patch 1b: replace the supports_shape branch so that, when
# allow_tile_padding=True, a tile-misaligned intermediate is accepted
# (it will be zero-padded at prep). Anchored on the verbatim dev491
# supports_shape block (count==1).

MARLIN_UTILS_SUPPORTS_SHAPE_OLD = (
    "    # gate-up: (n, k) = (intermediate_size_per_partition * 2, hidden_size)\n"
    "    # down: (n, k) = (hidden_size, intermediate_size_per_partition)\n"
    "    # moe marlin requires n % 128 == 0 and k % 64 == 0\n"
    "    supports_shape = (\n"
    "        hidden_size % 128 == 0\n"
    "        and intermediate_size_per_partition % max(64, group_size) == 0\n"
    "    )\n"
)

MARLIN_UTILS_SUPPORTS_SHAPE_NEW = (
    "    # [Genesis PN-FP8MOE-KPAD vllm#45703 backport] gate-up needs\n"
    "    # n=2*intermediate % 128, down needs k=intermediate % 64. With\n"
    "    # allow_tile_padding the misaligned intermediate is zero-padded at\n"
    "    # prep, so only a group straddling the padded boundary stays\n"
    "    # unsupported; hidden_size (the MoE I/O extent) is never padded.\n"
    "    if allow_tile_padding:\n"
    "        supports_shape = hidden_size % 128 == 0 and (\n"
    "            group_size <= 0 or intermediate_size_per_partition % group_size == 0\n"
    "        )\n"
    "    else:\n"
    "        supports_shape = (\n"
    "            hidden_size % 128 == 0\n"
    "            and intermediate_size_per_partition % max(64, group_size) == 0\n"
    "        )\n"
)


# ═════════════════════════════════════════════════════════════════════════
# FILE 2 — marlin_utils_fp8.py
# ═════════════════════════════════════════════════════════════════════════
#
# Sub-patch 2a: import marlin_moe_padded_intermediate into the existing
# marlin_utils import block. Anchored on the adjacent
# marlin_make_workspace_new import line (count==1).

FP8_IMPORT_OLD = (
    "    get_marlin_input_dtype,\n"
    "    marlin_make_workspace_new,\n"
    "    marlin_pad_dim,\n"
)

FP8_IMPORT_NEW = (
    "    get_marlin_input_dtype,\n"
    "    marlin_make_workspace_new,\n"
    "    # [Genesis PN-FP8MOE-KPAD vllm#45703 backport]\n"
    "    marlin_moe_padded_intermediate,\n"
    "    marlin_pad_dim,\n"
)

# Sub-patch 2b: add the two zero-pad helpers BEFORE
# prepare_fp8_moe_layer_for_marlin, and insert the padded_n compute +
# w13/w2 pad block INSIDE the prep body (right after weight_block_size =
# getattr(...)). The helpers go just above the def; we anchor on the
# whole `def prepare_fp8_moe_layer_for_marlin(` signature head plus the
# preceding blank lines, then the n/w13_n/weight_block_size lines.
#
# The helpers-insert and the padded_n-insert are TWO distinct edit sites;
# we keep them in one sub-patch by spanning the anchor from the def head
# through weight_block_size. This keeps the contiguity of #45703's hunk
# and guarantees the helpers and the padded_n block move together.

FP8_PADDED_N_PAD_OLD = (
    "def prepare_fp8_moe_layer_for_marlin(\n"
    "    layer: torch.nn.Module,\n"
    "    w13_weight: torch.Tensor,\n"
    "    w2_weight: torch.Tensor,\n"
    "    w13_weight_scale: torch.Tensor,\n"
    "    w2_weight_scale: torch.Tensor,\n"
)

FP8_PADDED_N_PAD_HELPERS = (
    "# [Genesis PN-FP8MOE-KPAD vllm#45703 backport] MoE intermediate zero-pad\n"
    "# helpers. FP8 zero decodes to 0.0, so padded rows/cols contribute nothing.\n"
    "def _moe_pad_shard_rows(x: torch.Tensor, n: int, padded_n: int) -> torch.Tensor:\n"
    "    \"\"\"Zero-pad each gate/up shard of a (E, 2 * n, ...) tensor to\n"
    "    padded_n rows.\"\"\"\n"
    "    if padded_n == n:\n"
    "        return x\n"
    "    e = x.size(0)\n"
    "    rest = x.shape[2:]\n"
    "    x = x.view(e, 2, n, *rest)\n"
    "    x = torch.nn.functional.pad(x, (0, 0) * len(rest) + (0, padded_n - n))\n"
    "    return x.reshape(e, 2 * padded_n, *rest)\n"
    "\n"
    "\n"
    "def _moe_pad_last(x: torch.Tensor, n: int, padded_n: int) -> torch.Tensor:\n"
    "    \"\"\"Zero-pad the last dim of a (E, ..., n) tensor to padded_n.\"\"\"\n"
    "    if padded_n == n:\n"
    "        return x\n"
    "    return torch.nn.functional.pad(x, (0, padded_n - n))\n"
    "\n"
    "\n"
)

FP8_PADDED_N_PAD_NEW = (
    FP8_PADDED_N_PAD_HELPERS + FP8_PADDED_N_PAD_OLD
)

# Sub-patch 2c: insert the group_size + padded_n compute + w13/w2 pad
# block right after the weight_block_size = getattr(...) line. The
# existing later `group_size = -1 if weight_block_size is None ...` line
# is removed by sub-patch 2e (the scale-comment change), so we move it up
# here (the def's own group_size). Anchored on the n/w13_n/weight_block
# triple (count==1).

FP8_INTERMEDIATE_OLD = (
    "    n = layer.intermediate_size_per_partition\n"
    "    w13_n = w13_weight.size(1)\n"
    "    weight_block_size = getattr(layer, \"weight_block_size\", None)\n"
)

FP8_INTERMEDIATE_NEW = (
    "    n = layer.intermediate_size_per_partition\n"
    "    w13_n = w13_weight.size(1)\n"
    "    weight_block_size = getattr(layer, \"weight_block_size\", None)\n"
    "    # [Genesis PN-FP8MOE-KPAD vllm#45703 backport] pad a tile-misaligned\n"
    "    # intermediate to a valid Marlin thread tile. FP8 zero decodes to 0.0,\n"
    "    # so padded weights drop out; the converted scales are padded to match\n"
    "    # below (the padded values are irrelevant). No-op when padded_n == n.\n"
    "    group_size = -1 if weight_block_size is None else weight_block_size[1]\n"
    "    padded_n = marlin_moe_padded_intermediate(n, group_size)\n"
    "    if padded_n != n:\n"
    "        w13_weight = _moe_pad_shard_rows(w13_weight, n, padded_n)\n"
    "        w2_weight = _moe_pad_last(w2_weight, n, padded_n)\n"
)

# Sub-patch 2d: repack_weight derives size_n/size_k from the (already
# padded) tensor shape instead of the pre-pad (w13_n, k)/(k, n) tuples.
# Anchored on the verbatim dev491 repack body (count==1).

FP8_REPACK_OLD = (
    "    def repack_weight(name: str, weight: torch.Tensor) -> torch.Tensor:\n"
    "        tensor_list = []\n"
    "        if \"w13\" in name:\n"
    "            size_n, size_k = w13_n, k\n"
    "        else:\n"
    "            size_n, size_k = k, n\n"
    "\n"
    "        assert weight.shape == (e, size_n, size_k)\n"
    "\n"
)

FP8_REPACK_NEW = (
    "    def repack_weight(name: str, weight: torch.Tensor) -> torch.Tensor:\n"
    "        # [Genesis PN-FP8MOE-KPAD vllm#45703 backport] derive size from the\n"
    "        # (possibly padded) tensor so the padded intermediate is honored.\n"
    "        tensor_list = []\n"
    "        size_n, size_k = weight.size(1), weight.size(2)\n"
)

# Sub-patch 2e: change the scale comment + REMOVE the later
# `group_size = ...` line (moved up to the padding block in 2c). Anchored
# on the verbatim dev491 `# Permute scales` + group_size + def
# permute_scales region (count==1).

FP8_SCALES_GROUP_OLD = (
    "    # WEIGHT SCALES\n"
    "    # Permute scales\n"
    "    group_size = -1 if weight_block_size is None else weight_block_size[1]\n"
    "\n"
    "    def permute_scales(scales: torch.Tensor, name: str) -> torch.Tensor:\n"
)

FP8_SCALES_GROUP_NEW = (
    "    # WEIGHT SCALES\n"
    "    # [Genesis PN-FP8MOE-KPAD vllm#45703 backport] Permute scales (convert\n"
    "    # at the original size, then pad to the tile). group_size is computed\n"
    "    # above with the padding block.\n"
    "    def permute_scales(scales: torch.Tensor, name: str) -> torch.Tensor:\n"
)

# Sub-patch 2f: pad the CONVERTED (E, G, size_n) scales to the padded
# thread tile — the block-FP8 scale-row padding. Anchored on the verbatim
# dev491 `scales[..., :size_n].contiguous()` + blank + `for i in range(e)`
# (count==1: `[..., :size_n].contiguous()` appears only in the block
# branch). The pad block is inserted BETWEEN the contiguous() line and the
# for-loop.

FP8_PADDED_N_PAD_SCALES_OLD = (
    "            # size_n may not divisible by block_size[0]\n"
    "            scales = scales[..., :size_n].contiguous()\n"
    "\n"
    "        for i in range(e):\n"
)

FP8_PADDED_N_PAD_SCALES_NEW = (
    "            # size_n may not divisible by block_size[0]\n"
    "            scales = scales[..., :size_n].contiguous()\n"
    "\n"
    "        # [Genesis PN-FP8MOE-KPAD vllm#45703 backport] pad the converted\n"
    "        # (E, G, size_n) scales to the padded thread tile.\n"
    "        if padded_n != n:\n"
    "            if \"w13\" in name:\n"
    "                g = scales.size(1)\n"
    "                scales = scales.view(e, g, 2, n)\n"
    "                scales = torch.nn.functional.pad(scales, (0, padded_n - n))\n"
    "                scales = scales.reshape(e, g, 2 * padded_n)\n"
    "                size_n = 2 * padded_n\n"
    "            else:\n"
    "                if group_size > 0:\n"
    "                    pad_groups = (padded_n - n) // group_size\n"
    "                    scales = torch.nn.functional.pad(scales, (0, 0, 0, pad_groups))\n"
    "                size_k = padded_n\n"
    "\n"
    "        for i in range(e):\n"
)


# ═════════════════════════════════════════════════════════════════════════
# FILE 3 — compressed_tensors_moe.py
# ═════════════════════════════════════════════════════════════════════════
#
# Sub-patch 3a: hoist the is_actorder computation above the if, pass
# allow_tile_padding=(not is_actorder) to the supports-layer check, and
# collapse the inner actorder condition to `if is_actorder:`. Anchored on
# the verbatim dev491 get_moe_method region (count==1).

MOE_METHOD_OLD = (
    "            # Prefer to use the MarlinMoE kernel when it is supported.\n"
    "            if (\n"
    "                not check_moe_marlin_supports_layer(layer, group_size)\n"
    "                or current_platform.is_rocm()\n"
    "            ):\n"
    "                if (\n"
    "                    weight_quant.strategy == QuantizationStrategy.GROUP\n"
    "                    and weight_quant.actorder\n"
    "                    in (ActivationOrdering.GROUP, ActivationOrdering.DYNAMIC)\n"
    "                ):\n"
    "                    raise ValueError(\n"
    "                        \"WNA16MoE is not supported with actorder=group/dynamic.\"\n"
    "                    )\n"
)

MOE_METHOD_NEW = (
    "            # [Genesis PN-FP8MOE-KPAD vllm#45703 backport] Prefer the\n"
    "            # MarlinMoE kernel; with allow_tile_padding the misaligned FP8\n"
    "            # intermediate is zero-padded at prep so it USES fast Marlin\n"
    "            # instead of the slow WNA16 fallback. Act-order keeps strict\n"
    "            # shape (cannot be fixed by padding).\n"
    "            is_actorder = (\n"
    "                weight_quant.strategy == QuantizationStrategy.GROUP\n"
    "                and weight_quant.actorder\n"
    "                in (ActivationOrdering.GROUP, ActivationOrdering.DYNAMIC)\n"
    "            )\n"
    "            if (\n"
    "                not check_moe_marlin_supports_layer(\n"
    "                    layer, group_size, allow_tile_padding=not is_actorder\n"
    "                )\n"
    "                or current_platform.is_rocm()\n"
    "            ):\n"
    "                if is_actorder:\n"
    "                    raise ValueError(\n"
    "                        \"WNA16MoE is not supported with actorder=group/dynamic.\"\n"
    "                    )\n"
)


# ─── Patcher construction ────────────────────────────────────────────────


def _make_marlin_utils_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(MARLIN_UTILS_REL)
    if target is None:
        return None
    return TextPatcher(
        patch_name="PN-FP8MOE-KPAD marlin_utils.py — moe intermediate tile pad (vllm#45703)",
        target_file=str(target),
        marker=GENESIS_PN_FP8MOE_KPAD_MARKER,
        sub_patches=[
            TextPatch(
                name="kpad_marlin_utils_add_func_and_widen",
                anchor=MARLIN_UTILS_ADD_FUNC_OLD,
                replacement=MARLIN_UTILS_ADD_FUNC_NEW,
                required=True,
            ),
            TextPatch(
                name="kpad_marlin_utils_supports_shape",
                anchor=MARLIN_UTILS_SUPPORTS_SHAPE_OLD,
                replacement=MARLIN_UTILS_SUPPORTS_SHAPE_NEW,
                required=True,
            ),
        ],
        # Upstream-merge marker: once #45703 merges, the def exists on a
        # pristine file -> whole patch self-skips. This is an upstream-side
        # string; our marlin_utils replacement DOES emit it (correct — the
        # per-file marker makes that idempotent), but on a PRISTINE file the
        # def only appears if upstream merged it. The fp8 / moe_method
        # replacement texts never define it (self-collision guarded by test).
        upstream_drift_markers=[
            "def marlin_moe_padded_intermediate",
        ],
    )


def _make_marlin_utils_fp8_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(MARLIN_UTILS_FP8_REL)
    if target is None:
        return None
    return TextPatcher(
        patch_name="PN-FP8MOE-KPAD marlin_utils_fp8.py — prep pad (vllm#45703)",
        target_file=str(target),
        marker=GENESIS_PN_FP8MOE_KPAD_MARKER,
        sub_patches=[
            TextPatch(
                name="kpad_fp8_import",
                anchor=FP8_IMPORT_OLD,
                replacement=FP8_IMPORT_NEW,
                required=True,
            ),
            TextPatch(
                name="kpad_fp8_helpers",
                anchor=FP8_PADDED_N_PAD_OLD,
                replacement=FP8_PADDED_N_PAD_NEW,
                required=True,
            ),
            TextPatch(
                name="kpad_fp8_padded_n_compute",
                anchor=FP8_INTERMEDIATE_OLD,
                replacement=FP8_INTERMEDIATE_NEW,
                required=True,
            ),
            TextPatch(
                name="kpad_fp8_repack",
                anchor=FP8_REPACK_OLD,
                replacement=FP8_REPACK_NEW,
                required=True,
            ),
            TextPatch(
                name="kpad_fp8_scales_group_move",
                anchor=FP8_SCALES_GROUP_OLD,
                replacement=FP8_SCALES_GROUP_NEW,
                required=True,
            ),
            TextPatch(
                name="kpad_fp8_scale_row_pad",
                anchor=FP8_PADDED_N_PAD_SCALES_OLD,
                replacement=FP8_PADDED_N_PAD_SCALES_NEW,
                required=True,
            ),
        ],
        # Upstream-side merge marker (our replacement DOES emit the helper
        # name, but on a PRISTINE file the helper exists only if upstream
        # merged it; the per-file marker makes our own emission idempotent).
        upstream_drift_markers=[
            "def _moe_pad_shard_rows",
        ],
    )


def _make_compressed_tensors_moe_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(COMPRESSED_TENSORS_MOE_REL)
    if target is None:
        return None
    return TextPatcher(
        patch_name="PN-FP8MOE-KPAD compressed_tensors_moe.py — allow_tile_padding (vllm#45703)",
        target_file=str(target),
        marker=GENESIS_PN_FP8MOE_KPAD_MARKER,
        sub_patches=[
            TextPatch(
                name="kpad_moe_method_allow_tile_padding",
                anchor=MOE_METHOD_OLD,
                replacement=MOE_METHOD_NEW,
                required=True,
            ),
        ],
        # Upstream-side merge marker: the `allow_tile_padding=` kwarg on the
        # supports-layer CALL is the #45703 signal. Our replacement emits it
        # too, but the per-file marker guards idempotency; on a pristine file
        # it appears only if upstream merged the widened call.
        upstream_drift_markers=[
            "allow_tile_padding=not is_actorder",
        ],
    )


def _make_patchers() -> list[TextPatcher | None]:
    """Return one TextPatcher per target file (None if a file is unresolvable
    — e.g. torch-less/vllm-less host or a pin that moved the file)."""
    return [
        _make_marlin_utils_patcher(),
        _make_marlin_utils_fp8_patcher(),
        _make_compressed_tensors_moe_patcher(),
    ]


def apply() -> tuple[str, str]:
    """Apply PN-FP8MOE-KPAD — FP8-core backport of vllm#45703 (3 files)."""
    from sndr.dispatcher import log_decision, should_apply

    decision, reason = should_apply("PN-FP8MOE-KPAD")
    log_decision("PN-FP8MOE-KPAD", decision, reason)
    if not decision:
        return "skipped", reason

    if vllm_install_root() is None:
        return "skipped", "vllm install root not discoverable"

    patchers = _make_patchers()
    if all(p is None for p in patchers):
        return "skipped", (
            "PN-FP8MOE-KPAD: no target file resolved (pin moved the Marlin "
            "MoE FP8 files or this kernel is not present)"
        )

    applied_files: list[str] = []
    for patcher in patchers:
        if patcher is None:
            # A target file is missing — required for correctness of the whole
            # patch (all three move together). Skip the whole patch rather than
            # leave a half-applied tree.
            return "skipped", (
                "PN-FP8MOE-KPAD: one of the three FP8-core target files is "
                "unresolved — refusing a partial apply"
            )

        if not os.path.isfile(patcher.target_file):
            return "skipped", f"target disappeared: {patcher.target_file}"

        with open(patcher.target_file) as f:
            content = f.read()

        # Per-file marker -> idempotent skip.
        if patcher.marker in content:
            log.info("[PN-FP8MOE-KPAD] marker present in %s — skip (idempotent)",
                     patcher.target_file)
            applied_files.append(f"{patcher.patch_name} (idempotent)")
            continue

        # Upstream-merge drift scan: if #45703 merged, the upstream-side
        # symbol is present on the (otherwise-pristine) file -> self-skip.
        drift_hit = next(
            (m for m in patcher.upstream_drift_markers if m in content), None
        )
        if drift_hit is not None:
            return "skipped", (
                f"PN-FP8MOE-KPAD: upstream drift marker {drift_hit!r} present in "
                f"{patcher.target_file} — vllm#45703 (or equivalent) appears merged"
            )

        result, failure = patcher.apply()
        if result == TextPatchResult.IDEMPOTENT:
            applied_files.append(f"{patcher.patch_name} (idempotent)")
            continue
        if result == TextPatchResult.SKIPPED:
            _r = failure.reason if failure else "anchor drift / not eligible"
            _d = f" ({failure.detail})" if (failure and failure.detail) else ""
            return "skipped", f"{patcher.patch_name}: {_r}{_d}"
        if result == TextPatchResult.FAILED:
            return "failed", (
                f"{patcher.patch_name}: "
                f"{failure.reason if failure else 'unknown'} "
                f"({failure.detail if failure else ''})"
            )
        applied_files.append(patcher.patch_name)

    return (
        "applied",
        "PN-FP8MOE-KPAD applied (FP8-core backport of vllm#45703, 3 files): "
        "marlin_utils.py {+marlin_moe_padded_intermediate, widened "
        "check_moe_marlin_supports_layer}, marlin_utils_fp8.py {+_moe_pad_* "
        "helpers, padded_n prep pad of w13/w2 + converted scales}, "
        "compressed_tensors_moe.py {allow_tile_padding=not is_actorder}. "
        "Tile-misaligned FP8 MoE intermediate (e.g. DiffusionGemma N=352->384) "
        "now uses fast Marlin; aligned sizes (e.g. 35B) pass through unchanged "
        f"(zero cost). Files: {', '.join(applied_files)}"
    )


def is_applied() -> bool:
    """True iff the marker is present in ALL THREE target files (full apply).

    Never raises; returns False on a vllm-less host (files unresolvable)."""
    if vllm_install_root() is None:
        return False
    patchers = _make_patchers()
    if any(p is None for p in patchers):
        return False
    try:
        for patcher in patchers:
            assert patcher is not None  # narrowed by the any() guard above
            with open(patcher.target_file) as f:
                if patcher.marker not in f.read():
                    return False
        return True
    except Exception:
        return False
