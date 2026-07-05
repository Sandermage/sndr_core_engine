# SPDX-License-Identifier: Apache-2.0
"""TDD test for P87 v7.62.10 — text-patch rewrite of Marlin sub-tile pad.

The v7.62 implementation used class-rebind (capture original methods +
monkey-patch new ones). Empirically observed under torch.compile +
FULL cudagraph capture: dynamo refused to trace through the wrapper
indirection and crashed with `Attempted to call function marked as
skipped`. The wrapper closure over `_ORIGINAL_APPLY_WEIGHTS` global
was the trigger.

This test enforces the v7.62.10 invariants: the patch IS a text-patch
(no class-rebind / no monkey-patch globals), the marker is versioned,
all 5 sub-patches are present and required, and the anchors line up
with what the patch replaces.
"""
from __future__ import annotations

import pytest

from sndr.engines.vllm.patches.kernels.p87_marlin_pad_sub_tile import (
    GENESIS_P87_MARKER,
    P87_APPLY_NEW,
    P87_APPLY_OLD,
    P87_CAN_IMPLEMENT_DEV491_NEW,
    P87_CAN_IMPLEMENT_DEV491_OLD,
    P87_CAN_IMPLEMENT_NEW,
    P87_CAN_IMPLEMENT_OLD,
    P87_IMPORTS_NEW,
    P87_IMPORTS_OLD,
    P87_LOGGER_NEW,
    P87_LOGGER_OLD,
    P87_PWA_NEW,
    P87_PWA_OLD,
    _make_patcher,
)
from tests.unit.anchor_sot._pin_manifest_assert import (
    assert_anchor_recorded,
    assert_variant_inactive,
)

# ─── Marker invariants ───────────────────────────────────────────────────


def test_p87_marker_versioned_textpatch():
    """The marker should embed v7.62.10 + textpatch tag so re-applies
    don't no-op against a stale class-rebind marker.
    """
    assert "v7.62.10_textpatch" in GENESIS_P87_MARKER, (
        f"P87 marker {GENESIS_P87_MARKER!r} should embed v7.62.10_textpatch"
    )
    assert "vllm#40361" in GENESIS_P87_MARKER, (
        "P87 marker should reference upstream PR for drift detection"
    )


# ─── No class-rebind residue ─────────────────────────────────────────────


def test_p87_module_has_no_class_rebind_globals():
    """The class-rebind variant defined module-level globals to capture
    the original methods (e.g. _ORIGINAL_APPLY_WEIGHTS). Those must be
    gone — they are the dynamo crash trigger.
    """
    import sndr.engines.vllm.patches.kernels.p87_marlin_pad_sub_tile as mod

    forbidden_names = [
        "_ORIGINAL_APPLY_WEIGHTS",
        "_ORIGINAL_PROCESS_WEIGHTS_AFTER_LOADING",
        "_ORIGINAL_CAN_IMPLEMENT",
    ]
    for name in forbidden_names:
        assert not hasattr(mod, name), (
            f"P87 module still exposes {name} — class-rebind residue. "
            "v7.62.10 must be pure text-patch."
        )


def test_p87_uses_text_patcher_not_class_rebind():
    """Confirm the apply path goes through TextPatcher, not class-rebind."""
    patcher = _make_patcher()
    if patcher is None:
        pytest.skip("vllm not installed (resolve_vllm_file returned None)")
    from sndr.kernel.text_patch import TextPatcher

    assert isinstance(patcher, TextPatcher), (
        "P87 _make_patcher must return TextPatcher instance"
    )


# ─── Sub-patch structure ─────────────────────────────────────────────────


def test_p87_has_six_sub_patches_with_dual_can_implement_anchor():
    """Post dev259->dev491 pin bump: 6 sub-patches. The four structural
    edits (imports, logger, pwa, apply) stay required=True. can_implement
    is a DUAL-ANCHOR pair (dev259 + dev491), both required=False with
    required-at-least-one semantics so exactly one fires per pin.
    """
    patcher = _make_patcher()
    if patcher is None:
        pytest.skip("vllm not installed")
    assert len(patcher.sub_patches) == 6, (
        f"Expected 6 sub-patches (4 structural + 2 can_implement variants), "
        f"got {len(patcher.sub_patches)}"
    )
    by_name = {sp.name: sp for sp in patcher.sub_patches}
    # The four structural edits must remain required.
    for name in (
        "p87_imports",
        "p87_logger_round_up_imports",
        "p87_pwa_with_maybe_pad_n",
        "p87_apply_weights_slice",
    ):
        assert by_name[name].required, (
            f"structural sub-patch {name!r} must stay required=True"
        )
    # The two can_implement variants are required-at-least-one (both False).
    for name in (
        "p87_can_implement_padded_dev259",
        "p87_can_implement_padded_dev491",
    ):
        assert not by_name[name].required, (
            f"can_implement variant {name!r} must be required=False "
            "(required-at-least-one dual-anchor semantics)"
        )


def test_p87_sub_patch_names_complete():
    """Sub-patches must cover: imports, logger+round_up, can_implement
    (dev259 + dev491 dual-anchor), process_weights_after_loading prelude,
    apply_weights output slice.
    """
    patcher = _make_patcher()
    if patcher is None:
        pytest.skip("vllm not installed")
    names = {sp.name for sp in patcher.sub_patches}
    expected = {
        "p87_imports",
        "p87_logger_round_up_imports",
        "p87_can_implement_padded_dev259",
        "p87_can_implement_padded_dev491",
        "p87_pwa_with_maybe_pad_n",
        "p87_apply_weights_slice",
    }
    assert names == expected, (
        f"Sub-patch name set mismatch.\nGot:      {names}\nExpected: {expected}"
    )


# ─── Anchor / replacement integrity ──────────────────────────────────────


@pytest.mark.parametrize(("old", "new", "label"), [
    (P87_IMPORTS_OLD, P87_IMPORTS_NEW, "imports"),
    (P87_LOGGER_OLD, P87_LOGGER_NEW, "logger_round_up"),
    (P87_CAN_IMPLEMENT_OLD, P87_CAN_IMPLEMENT_NEW, "can_implement_dev259"),
    (P87_CAN_IMPLEMENT_DEV491_OLD, P87_CAN_IMPLEMENT_DEV491_NEW,
     "can_implement_dev491"),
    (P87_PWA_OLD, P87_PWA_NEW, "pwa_maybe_pad_n"),
    (P87_APPLY_OLD, P87_APPLY_NEW, "apply_slice"),
])
def test_p87_anchors_nonempty_and_replacements_differ(old, new, label):
    """Every sub-patch must have a non-empty anchor and a replacement
    that actually differs from the anchor (otherwise it's a no-op
    that hides drift).
    """
    assert old.strip(), f"{label}: anchor is empty"
    assert new.strip(), f"{label}: replacement is empty"
    assert old != new, f"{label}: replacement equals anchor (no-op patch)"


@pytest.mark.parametrize(("new", "label"), [
    (P87_IMPORTS_NEW, "imports"),
    (P87_LOGGER_NEW, "logger_round_up"),
    (P87_CAN_IMPLEMENT_NEW, "can_implement_dev259"),
    (P87_CAN_IMPLEMENT_DEV491_NEW, "can_implement_dev491"),
    (P87_PWA_NEW, "pwa_maybe_pad_n"),
    (P87_APPLY_NEW, "apply_slice"),
])
def test_p87_each_replacement_carries_genesis_breadcrumb(new, label):
    """Every modified region must carry a `[Genesis P87` breadcrumb so
    `git diff` and on-disk forensics can trace which patch authored each
    edit (drift detection relies on this).
    """
    assert "[Genesis P87" in new, (
        f"{label}: replacement missing `[Genesis P87` breadcrumb"
    )


# ─── Semantic invariants of the rewrite ──────────────────────────────────


def test_p87_can_implement_uses_round_up():
    """can_implement must wrap partition_weight_shape[1] with round_up
    so sub-tile shards report supported.
    """
    assert "_genesis_p87_round_up" in P87_CAN_IMPLEMENT_NEW, (
        "can_implement replacement must call round_up helper"
    )
    assert "_GENESIS_P87_MIN_THREAD_N" in P87_CAN_IMPLEMENT_NEW, (
        "can_implement replacement must reference MIN_THREAD_N constant"
    )


def test_p87_pwa_inserts_maybe_pad_n_method():
    """The PWA sub-patch must INSERT a new `_maybe_pad_n` method and
    call it as the very first statement of process_weights_after_loading.
    """
    assert "def _maybe_pad_n(self, layer:" in P87_PWA_NEW, (
        "PWA replacement must define _maybe_pad_n method"
    )
    # Ensure the call site is BEFORE the device = ... line (i.e. first stmt).
    pwa_call_idx = P87_PWA_NEW.find("self._maybe_pad_n(layer)")
    device_idx = P87_PWA_NEW.find("device = getattr(layer, self.w_q_name)")
    assert pwa_call_idx > 0, (
        "PWA replacement must call self._maybe_pad_n(layer) inside PWA body"
    )
    assert pwa_call_idx < device_idx, (
        "self._maybe_pad_n(layer) must be called BEFORE the device = ... line "
        "(first statement of process_weights_after_loading)"
    )


def test_p87_pwa_stores_marlin_orig_n():
    """_maybe_pad_n must record orig_n on the layer so apply_weights can
    slice correctly. The early-return no-op path must also set it.
    """
    assert "layer._marlin_orig_n = orig_n" in P87_PWA_NEW, (
        "_maybe_pad_n must set layer._marlin_orig_n"
    )
    # Defense: the assignment must come BEFORE the early-return so that
    # the no-op case (already aligned) still gets the attribute.
    assign_idx = P87_PWA_NEW.find("layer._marlin_orig_n = orig_n")
    early_return_idx = P87_PWA_NEW.find("if padded_n == orig_n:")
    assert assign_idx < early_return_idx, (
        "layer._marlin_orig_n must be set BEFORE the `if padded_n == orig_n` "
        "early-return so the aligned no-op path still records orig_n"
    )


def test_p87_apply_weights_slices_output():
    """apply_weights replacement must slice the output back to orig_n
    and pad bias if caller supplied at orig_n.
    """
    assert "_marlin_orig_n" in P87_APPLY_NEW, (
        "apply_weights replacement must read _marlin_orig_n from layer"
    )
    # Slice may be split across lines for line-length; collapse whitespace
    # and check the slice expression.
    import re
    collapsed = re.sub(r"\s+", " ", P87_APPLY_NEW)
    assert "[ ..., :_genesis_p87_orig_n ]" in collapsed or \
        "[..., :_genesis_p87_orig_n]" in collapsed, (
        "apply_weights replacement must slice output back to orig_n"
    )
    # Bias-pad guard:
    assert "F.pad(" in P87_APPLY_NEW, (
        "apply_weights replacement must F.pad bias when caller supplied "
        "at orig_n but kernel was loaded at padded_n"
    )


def test_p87_imports_add_dataclasses_and_F():
    """The imports sub-patch must add dataclasses (for dataclasses.replace
    of self.config) and torch.nn.functional as F (for F.pad).
    """
    assert "import dataclasses" in P87_IMPORTS_NEW, (
        "imports must add `import dataclasses` for self.config replace"
    )
    assert "import torch.nn.functional as F" in P87_IMPORTS_NEW, (
        "imports must add `import torch.nn.functional as F` for F.pad"
    )


# ─── Drift detection — anchors must be specific ──────────────────────────


def test_p87_anchors_have_enough_context():
    """Anchors must be long enough to be unique against the full file.
    Short anchors risk matching multiple sites and patching the wrong one.
    Heuristic: at least 80 chars per anchor.
    """
    for label, anchor in [
        ("imports", P87_IMPORTS_OLD),
        ("logger", P87_LOGGER_OLD),
        ("can_implement_dev259", P87_CAN_IMPLEMENT_OLD),
        ("can_implement_dev491", P87_CAN_IMPLEMENT_DEV491_OLD),
        ("pwa", P87_PWA_OLD),
        ("apply", P87_APPLY_OLD),
    ]:
        assert len(anchor) >= 80, (
            f"{label}: anchor too short ({len(anchor)} chars). Risk of "
            "matching multiple sites in marlin.py."
        )


# ─── dev491 dual-anchor (pin bump dev259 -> dev491) ──────────────────────
#
# On pin 0.22.1rc1.dev491+g1033ffac2 upstream merged the equivalent of
# #40361 natively. The dev259 can_implement anchor no longer exists; a
# dev491-shaped variant matches the upstream-merged form instead. These
# tests pin the dual-anchor contract: mutual exclusivity, behavior
# preservation of the dev491 variant, breadcrumb presence, and the
# patcher-level drift marker that suppresses the pwa/apply sub-patches on
# dev491 so they never double-pad over upstream's native padding.

def test_p87_can_implement_dev491_variant_differs_from_dev259():
    """The dev491 variant must be a genuinely different anchor from the
    dev259 variant — otherwise the dual-anchor is a no-op duplicate.
    """
    assert P87_CAN_IMPLEMENT_DEV491_OLD != P87_CAN_IMPLEMENT_OLD, (
        "dev491 can_implement anchor must differ from the dev259 anchor"
    )
    # The dev491 anchor must NOT contain the dev259-specific single-call
    # form, and vice versa (mutual exclusivity at the string level).
    assert P87_CAN_IMPLEMENT_OLD not in P87_CAN_IMPLEMENT_DEV491_OLD
    assert P87_CAN_IMPLEMENT_DEV491_OLD not in P87_CAN_IMPLEMENT_OLD


def test_p87_can_implement_dev491_is_behavior_preserving():
    """On dev491 upstream already reports misaligned shapes as supported
    (`return True, None`). Our dev491 variant must preserve that exact
    control flow — it only adds a breadcrumb, never changes the return.
    """
    # The merged decision must be retained verbatim.
    assert "return True, None" in P87_CAN_IMPLEMENT_DEV491_OLD
    assert "return True, None" in P87_CAN_IMPLEMENT_DEV491_NEW
    # The group-straddle guard must survive untouched in the replacement.
    assert (
        "# A group straddling TP ranks cannot be fixed by padding."
        in P87_CAN_IMPLEMENT_DEV491_NEW
    )
    # The replacement must carry the Genesis breadcrumb.
    assert "[Genesis P87" in P87_CAN_IMPLEMENT_DEV491_NEW
    # Guard against the self-collision the patcher-level drift marker
    # would otherwise hit: the dev491 can_implement text must NOT emit the
    # `marlin_padded_nk` call string used as the upstream-merge marker.
    assert "marlin_padded_nk" not in P87_CAN_IMPLEMENT_DEV491_OLD
    assert "marlin_padded_nk" not in P87_CAN_IMPLEMENT_DEV491_NEW


def test_p87_patcher_carries_dev491_upstream_drift_marker():
    """The patcher must carry the dev491-only upstream-merge marker so the
    whole P87 patch skips on dev491 (preventing a double-pad over
    upstream's native padding). The marker must not be a `[Genesis`
    self-marker.
    """
    patcher = _make_patcher()
    if patcher is None:
        pytest.skip("vllm not installed")
    marker = "padded_n, padded_k = marlin_padded_nk(size_n, size_k, c.group_size)"
    assert marker in patcher.upstream_drift_markers, (
        "patcher must carry the dev491 upstream-merge marker so P87 skips "
        "on dev491 and never double-pads"
    )
    assert not marker.startswith("[Genesis"), (
        "the dev491 drift marker must be an upstream-side string, not a "
        "Genesis self-marker"
    )


# ── Current-pin anchor manifest (MIGRATED from the /tmp pristine gates) ─
# Audit finding #14: the three tests below byte-checked the can_implement
# variants against ``/private/tmp/candidate_pin_current`` (dev259) and
# ``/tmp/candidate_pin_new`` (dev491) — two stale-pin trees absent on every
# CI host (permanently green-by-skip). MIGRATED to read the COMMITTED per-pin
# manifest. On the current pin the DEV491 can_implement variant is the one
# that fires (recorded), the DEV259 variant does not, and P87's whole anchor
# set is recorded active with merge_status==not_merged — i.e. the dev491
# ``marlin_padded_nk`` upstream-merge marker is ABSENT in the current pristine
# (so P87 applies, no double-pad). Ties the LIVE variant CONSTANTS to the
# recorded bytes; a variant-selection drift at the next regen fails loud.


def test_p87_dev491_can_implement_variant_active_on_current_pin():
    assert_anchor_recorded(
        "P87", "p87_can_implement_padded_dev491", P87_CAN_IMPLEMENT_DEV491_OLD
    )


def test_p87_dev259_can_implement_variant_inactive_on_current_pin():
    assert_variant_inactive("P87", P87_CAN_IMPLEMENT_OLD)


def test_p87_core_sub_anchors_recorded_active():
    # The pwa/apply/imports/logger subs are recorded active (merge not_merged)
    # -> the dev491 upstream-merge drift marker is absent in current pristine,
    # so P87 applies and does not double-pad.
    for sub, old in (
        ("p87_pwa_with_maybe_pad_n", P87_PWA_OLD),
        ("p87_apply_weights_slice", P87_APPLY_OLD),
        ("p87_imports", P87_IMPORTS_OLD),
        ("p87_logger_round_up_imports", P87_LOGGER_OLD),
    ):
        assert_anchor_recorded("P87", sub, old)
