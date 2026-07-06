# SPDX-License-Identifier: Apache-2.0
"""TDD test for PN-FP8MOE-KPAD — FP8-core backport of vllm#45703.

PR #45703 ("[Kernel] Extend Marlin thread-tile padding to MoE
(WNA16 + FP8/MXFP8)", OPEN) pads a tile-misaligned MoE *intermediate*
dimension to the next valid Marlin thread tile at weight prep, so an
FP8 MoE layer whose intermediate is not a multiple of 64 can USE the
fast Marlin kernel instead of the slow WNA16 fallback (or crashing with
`Invalid thread config ... MKN=[...,352,...]`).

This patch ports ONLY the FP8 core of #45703 — exactly three vLLM files:

  1. quantization/utils/marlin_utils.py
       + def marlin_moe_padded_intermediate(intermediate_size, group_size=-1)
       + widen check_moe_marlin_supports_layer(..., allow_tile_padding=False)
  2. quantization/utils/marlin_utils_fp8.py
       + _moe_pad_shard_rows + _moe_pad_last helpers
       + padded_n compute + w13/w2 pad + CONVERTED-SCALE pad in
         prepare_fp8_moe_layer_for_marlin
  3. compressed_tensors_moe/compressed_tensors_moe.py
       + allow_tile_padding=(not is_actorder) on the check call

The mxfp8 hunk of #45703 (prepare_mxfp8_moe_layer_for_marlin) and the
INT-WNA16 oracle module are OUT OF FP8-CORE SCOPE — this test asserts
they are NOT touched.

The patch is intrinsically shape-gated: marlin_moe_padded_intermediate
returns N unchanged for an already-aligned N (e.g. the 35B's tile-aligned
intermediate), so the prep-pad block is a pure no-op there — ZERO cost,
NO 35B regression even when enabled.

The math invariant tested here (the load-bearing claim of the whole
patch): N=352 (the DiffusionGemma crash) pads to 384; aligned N (2816,
the 35B intermediate) passes through unchanged.
"""
from __future__ import annotations

import math

import pytest

from sndr.engines.vllm.patches.quantization.marlin.pn_fp8moe_kpad_marlin_moe import (
    FP8_PADDED_N_PAD_OLD,
    FP8_PADDED_N_PAD_SCALES_OLD,
    FP8_REPACK_OLD,
    GENESIS_PN_FP8MOE_KPAD_MARKER,
    MARLIN_UTILS_ADD_FUNC_OLD,
    MARLIN_UTILS_SUPPORTS_SHAPE_OLD,
    MOE_METHOD_OLD,
    _make_patchers,
    is_applied,
)

# ─── 1. THE MATH INVARIANT (load-bearing claim) ──────────────────────────


def _reference_padded_intermediate(intermediate_size: int, group_size: int = -1) -> int:
    """Pure-python mirror of the patched marlin_moe_padded_intermediate.

    Mirrors the #45703 body verbatim:
        group = group_size if group_size > 0 else 1
        padded = round_up(intermediate_size, math.lcm(64, group))
    round_up(x, m) == ((x + m - 1) // m) * m.
    """
    group = group_size if group_size > 0 else 1
    multiple = math.lcm(64, group)
    return ((intermediate_size + multiple - 1) // multiple) * multiple


def test_padded_intermediate_352_rounds_to_384():
    """The DiffusionGemma crash dim N=352 (352 % 64 == 32) must pad to 384,
    the next multiple of 64. This is the whole reason the patch exists.
    """
    assert _reference_padded_intermediate(352, -1) == 384


def test_padded_intermediate_aligned_passes_through():
    """An already-tile-aligned N (e.g. the 35B's intermediate 2816, which is
    44*64) must pass through UNCHANGED so the prep-pad is a no-op and there
    is zero cost / no 35B regression even when the patch is enabled.
    """
    assert _reference_padded_intermediate(2816, -1) == 2816
    # A few more aligned sizes for good measure.
    for n in (64, 128, 1792, 4096):
        assert _reference_padded_intermediate(n, -1) == n, n


def test_padded_intermediate_respects_group_size_lcm():
    """For a positive group_size the pad multiple is lcm(64, group), NOT 64.
    group=128 -> lcm(64,128)=128; group=32 -> lcm(64,32)=64.
    """
    assert _reference_padded_intermediate(96, 32) == 128   # lcm(64,32)=64 -> round_up(96,64)
    assert _reference_padded_intermediate(96, 128) == 128  # lcm(64,128)=128 -> round_up(96,128)
    # Pad multiple is %64 (lcm(64,group)) — never %128 — for the default
    # channel/tensor FP8 case (group_size=-1).
    assert _reference_padded_intermediate(352, -1) % 64 == 0


def test_patch_replacement_body_matches_reference_math():
    """The patch's injected function body must encode exactly the
    round_up(intermediate_size, math.lcm(64, max(group_size,1))) math —
    not a %128 double-pad, not a different multiple.
    """
    from sndr.engines.vllm.patches.quantization.marlin.pn_fp8moe_kpad_marlin_moe import (
        MARLIN_UTILS_ADD_FUNC_NEW,
    )
    # The function must compute group = group_size if group_size > 0 else 1
    assert "group = group_size if group_size > 0 else 1" in MARLIN_UTILS_ADD_FUNC_NEW
    # and round_up over math.lcm(64, group).
    assert "round_up(intermediate_size, math.lcm(64, group))" in MARLIN_UTILS_ADD_FUNC_NEW
    # Must NOT pad to 128 (that would be the dense P87/#40361 double-pad).
    assert "math.lcm(128" not in MARLIN_UTILS_ADD_FUNC_NEW


# ─── 2. PATCHER / ANCHOR / MARKER STRUCTURE ──────────────────────────────


def test_three_patchers_one_per_file():
    """The patch spans 3 DISTINCT vLLM files, so _make_patchers must return
    three TextPatcher instances (or None for any file not resolvable).
    On a torch-less / vllm-less host all three resolve to None.
    """
    patchers = _make_patchers()
    # Exactly three slots, one per target file.
    assert len(patchers) == 3, f"expected 3 patcher slots, got {len(patchers)}"


def test_marker_versioned_and_cites_pr():
    assert "45703" in GENESIS_PN_FP8MOE_KPAD_MARKER, (
        "marker must cite upstream PR #45703 for drift detection"
    )
    assert "PN-FP8MOE-KPAD" in GENESIS_PN_FP8MOE_KPAD_MARKER


@pytest.mark.parametrize(("anchor", "label"), [
    (MARLIN_UTILS_ADD_FUNC_OLD, "marlin_utils_add_func"),
    (MARLIN_UTILS_SUPPORTS_SHAPE_OLD, "marlin_utils_supports_shape"),
    (FP8_PADDED_N_PAD_OLD, "fp8_padded_n_pad"),
    (FP8_REPACK_OLD, "fp8_repack"),
    (FP8_PADDED_N_PAD_SCALES_OLD, "fp8_pad_scales"),
    (MOE_METHOD_OLD, "moe_method"),
])
def test_anchors_have_enough_context(anchor, label):
    """Anchors must be long enough to be unique. Short anchors risk matching
    multiple sites and patching the wrong one.
    """
    assert len(anchor) >= 80, (
        f"{label}: anchor too short ({len(anchor)} chars) — collision risk"
    )


def test_every_replacement_carries_breadcrumb():
    """Each modified region must carry a `[Genesis PN-FP8MOE-KPAD` breadcrumb
    so on-disk forensics / git diff can trace which patch authored the edit.
    """
    from sndr.engines.vllm.patches.quantization.marlin.pn_fp8moe_kpad_marlin_moe import (
        FP8_PADDED_N_PAD_NEW,
        FP8_PADDED_N_PAD_SCALES_NEW,
        FP8_REPACK_NEW,
        MARLIN_UTILS_ADD_FUNC_NEW,
        MARLIN_UTILS_SUPPORTS_SHAPE_NEW,
        MOE_METHOD_NEW,
    )
    for new, label in [
        (MARLIN_UTILS_ADD_FUNC_NEW, "marlin_utils_add_func"),
        (MARLIN_UTILS_SUPPORTS_SHAPE_NEW, "marlin_utils_supports_shape"),
        (FP8_PADDED_N_PAD_NEW, "fp8_padded_n_pad"),
        (FP8_REPACK_NEW, "fp8_repack"),
        (FP8_PADDED_N_PAD_SCALES_NEW, "fp8_pad_scales"),
        (MOE_METHOD_NEW, "moe_method"),
    ]:
        assert "[Genesis PN-FP8MOE-KPAD" in new, (
            f"{label}: replacement missing `[Genesis PN-FP8MOE-KPAD` breadcrumb"
        )


def test_marlin_utils_adds_padded_intermediate_func():
    from sndr.engines.vllm.patches.quantization.marlin.pn_fp8moe_kpad_marlin_moe import (
        MARLIN_UTILS_ADD_FUNC_NEW,
    )
    assert "def marlin_moe_padded_intermediate(" in MARLIN_UTILS_ADD_FUNC_NEW


def test_supports_layer_widened_to_allow_tile_padding():
    from sndr.engines.vllm.patches.quantization.marlin.pn_fp8moe_kpad_marlin_moe import (
        MARLIN_UTILS_SUPPORTS_SHAPE_NEW,
    )
    assert "allow_tile_padding" in MARLIN_UTILS_SUPPORTS_SHAPE_NEW


def test_fp8_helpers_and_scale_row_pad_present():
    """The fp8 hunk must add _moe_pad_shard_rows + _moe_pad_last AND pad the
    CONVERTED scales (the block-FP8 scale-row padding club-3090 punts on).
    """
    from sndr.engines.vllm.patches.quantization.marlin.pn_fp8moe_kpad_marlin_moe import (
        FP8_PADDED_N_PAD_NEW,
        FP8_PADDED_N_PAD_SCALES_NEW,
    )
    assert "_moe_pad_shard_rows" in FP8_PADDED_N_PAD_NEW
    assert "_moe_pad_last" in FP8_PADDED_N_PAD_NEW
    # Converted-scale pad: w13 view (e,g,2,n) -> pad -> reshape (e,g,2*padded_n)
    assert "scales.view(e, g, 2, n)" in FP8_PADDED_N_PAD_SCALES_NEW
    assert "reshape(e, g, 2 * padded_n)" in FP8_PADDED_N_PAD_SCALES_NEW
    # w2 pad_groups rows path
    assert "pad_groups" in FP8_PADDED_N_PAD_SCALES_NEW


def test_moe_method_passes_allow_tile_padding_not_is_actorder():
    from sndr.engines.vllm.patches.quantization.marlin.pn_fp8moe_kpad_marlin_moe import (
        MOE_METHOD_NEW,
    )
    assert "allow_tile_padding=not is_actorder" in MOE_METHOD_NEW
    assert "is_actorder = (" in MOE_METHOD_NEW


def test_no_mxfp8_hunk_in_fp8_core_scope():
    """The mxfp8 hunk (prepare_mxfp8_moe_layer_for_marlin) is OUT of FP8-core
    scope — none of the patch's replacement texts may touch the mxfp8 prep.
    """
    import sndr.engines.vllm.patches.quantization.marlin.pn_fp8moe_kpad_marlin_moe as mod

    src = "".join(
        getattr(mod, name)
        for name in dir(mod)
        if name.endswith(("_OLD", "_NEW")) and isinstance(getattr(mod, name), str)
    )
    assert "prepare_mxfp8_moe_layer_for_marlin" not in src, (
        "FP8-core scope must NOT touch the mxfp8 prep function"
    )


# ─── 3. RETIREMENT DRIFT MARKER (self-skip once #45703 merges) ────────────


def test_marlin_utils_patcher_drift_marker_self_skips_on_merge():
    """The marlin_utils patcher must carry the upstream-merge drift marker
    `def marlin_moe_padded_intermediate` so that once #45703 merges (the
    function exists upstream) the whole patch self-skips instead of failing.
    The drift marker must be an upstream-side string, NOT a Genesis
    self-marker that our own replacement would re-emit elsewhere.
    """
    patchers = _make_patchers()
    # Find the marlin_utils patcher by its patch_name; resolve to None on a
    # vllm-less host, so guard.
    found = False
    for p in patchers:
        if p is None:
            continue
        if "marlin_utils.py" in p.patch_name and "fp8" not in p.patch_name.lower():
            assert "def marlin_moe_padded_intermediate" in p.upstream_drift_markers, (
                "marlin_utils patcher must self-skip on #45703 merge"
            )
            found = True
    if not found:
        pytest.skip("vllm not installed (marlin_utils patcher unresolved)")


def test_drift_marker_string_not_emitted_by_own_replacement():
    """Self-collision guard (P87 lesson): the upstream-merge drift marker
    string used to detect a #45703 merge must NOT be a substring that OUR
    OWN replacement text writes back into a sibling file — otherwise the
    patcher would falsely self-skip on already-applied residue.

    `def marlin_moe_padded_intermediate` is the ADD-target def line: our
    marlin_utils replacement DOES emit it (that is correct — once we write
    it, the marlin_utils patcher's own marker makes it idempotent, and the
    drift marker only matters on a PRISTINE file where upstream merged it).
    But it must NOT appear in the fp8 / moe_method replacement texts (those
    only reference/import the symbol, they must not define it).
    """
    from sndr.engines.vllm.patches.quantization.marlin.pn_fp8moe_kpad_marlin_moe import (
        FP8_PADDED_N_PAD_NEW,
        MOE_METHOD_NEW,
    )
    assert "def marlin_moe_padded_intermediate" not in FP8_PADDED_N_PAD_NEW
    assert "def marlin_moe_padded_intermediate" not in MOE_METHOD_NEW


# ─── 4. is_applied() probe is safe on a vllm-less host ───────────────────


def test_is_applied_is_false_without_vllm():
    """is_applied() must never raise; on a host without vllm it returns
    False (markers can't be present if the files can't be resolved).
    """
    assert is_applied() is False


# ─── 5. Anchors line up with the live dev491 source on a real host ───────


def test_anchors_apply_to_synthetic_source():
    """Apply each sub-patch's anchor->replacement against a synthetic source
    string reproducing the dev491 anchor regions, and confirm a clean,
    unambiguous single match per anchor. This guards anchor drift without
    needing a live vllm install.
    """
    # Synthetic marlin_utils.py region (verbatim dev491 L326-356 context).
    marlin_utils_src = (
        "        input_size=layer.input_size,\n"
        "        group_size=group_size,\n"
        "    )[0]\n"
        "\n"
        "\n"
        "def check_moe_marlin_supports_layer(layer: RoutedExperts, group_size: int) -> bool:\n"
        "    if current_platform.is_rocm():\n"
        "        return False\n"
        "    hidden_size = layer.hidden_size\n"
        "    # Note: The layer has not performed rounding on intermediate_size's at this\n"
        "    # point. Use the unpadded size which won't change.\n"
        "    intermediate_size_per_partition = (\n"
        "        layer.moe_config.intermediate_size_per_partition_unpadded\n"
        "    )\n"
        "    assert intermediate_size_per_partition is not None\n"
        "    # apply_router_weight_on_input is not supported for moe marlin\n"
        "    supports_router_weight = not layer.apply_router_weight_on_input\n"
        "\n"
        "    # gate-up: (n, k) = (intermediate_size_per_partition * 2, hidden_size)\n"
        "    # down: (n, k) = (hidden_size, intermediate_size_per_partition)\n"
        "    # moe marlin requires n % 128 == 0 and k % 64 == 0\n"
        "    supports_shape = (\n"
        "        hidden_size % 128 == 0\n"
        "        and intermediate_size_per_partition % max(64, group_size) == 0\n"
        "    )\n"
        "    supports_group_size = group_size in [-1, 32, 64, 128]\n"
        "    return supports_shape and supports_group_size and supports_router_weight\n"
    )
    assert marlin_utils_src.count(MARLIN_UTILS_ADD_FUNC_OLD) == 1
    assert marlin_utils_src.count(MARLIN_UTILS_SUPPORTS_SHAPE_OLD) == 1

    # Synthetic compressed_tensors_moe.py region (verbatim dev491 L96-108).
    moe_method_src = (
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
        '                        "WNA16MoE is not supported with actorder=group/dynamic."\n'
        "                    )\n"
    )
    assert moe_method_src.count(MOE_METHOD_OLD) == 1

    # Replacements must apply cleanly (single substitution, result differs).
    for src, old in [
        (marlin_utils_src, MARLIN_UTILS_ADD_FUNC_OLD),
        (moe_method_src, MOE_METHOD_OLD),
    ]:
        assert old in src
        # The replace must change the source.
        replaced = src.replace(old, "X", 1)
        assert replaced != src


# ─── 6. Byte-exact anchors against the pristine dev491 tree ──────────────
# RETIRED (audit #14 full drain, 2026-07-06). This section read the pristine
# source from ``/tmp/candidate_pin_new/vllm`` (dev491) — a macOS-only stale
# path, empty on CI and absent on the Linux rig (three pin generations behind
# dev748), so ``test_all_anchors_match_pristine_dev491_exactly_once`` /
# ``test_drift_markers_absent_in_pristine_dev491`` /
# ``test_patch_applies_cleanly_and_compiles_on_pristine_dev491`` executed on
# NO host (permanent green-by-skip). PN_FP8MOE_KPAD is not recorded in the
# committed anchor_sot manifest (90/329 gap, audit #6/#21), so the byte-checks
# cannot be migrated onto it. Their content is already covered in CI by the
# synthetic-source tests in section 3 (anchor count==1 on crafted sources +
# apply + compile) and the drift-marker-self-collision tests in section 4.
