# SPDX-License-Identifier: Apache-2.0
"""Batch triage 2026-07-05 STEP 0 — G4_26 retirement + PN346B tripwire.

Pins the two pre-patch actions of the 34-PR triage batch (47382..47564):

  STEP 0a — G4_26 iron-rule-11 retire audit (contradiction C1):
    Pristine dev748 (pin 2dfaae752) REPLACED G4_26's dev491 anchor site
    with a NATIVE sharded soft-embed: vllm#46177 (fix for issue #45719,
    MERGED 2026-06-26, merge commit 701a23d99) computes the
    self-conditioning soft embed from the LOCAL vocab shard
    (``probs[..., sc_vocab_start:sc_vocab_end] @ embed_weight_shard``)
    followed by an all_reduce — a DIFFERENT approach than G4_26's
    full-weight all-gather (deep-diff outcome (c): different-approach
    supersession -> retire, nothing of ours to keep). Byte-verified via
    gh api at the pin commits (2026-07-05): the required sub-3 anchor
    ``embed_weight=self.model.model.embed_tokens.weight,`` has count 0 and
    ``sc_vocab_start`` count 10 in dev672 (93d8f834d), dev714 (09663abde)
    AND dev748 (2dfaae752); #46177's merge commit is an ancestor of all
    three (gh compare status "ahead"). Yet diffusiongemma-tp2.yaml still
    expected "G4_26 ... confirmed APPLIED at boot" and the ModelDef kept
    GENESIS_ENABLE_G4_26_DIFFUSIONGEMMA_TP_VOCAB='1' — the enabled-flag-
    on-a-dead-patch landmine class (PN399 precedent). Real retirement =
    lifecycle retired + flag removed from launch configs + range cap
    (range caps alone do NOT stop opt-in patches).

  STEP 0b — PN346B #47491 collision tripwire:
    OPEN vllm#47491 inserts 5 lines INSIDE the 4-line PN346B_ANCHOR_OLD
    span (between ``eagle_verified.clear()`` and the naked
    ``curr_hit_length = _new_hit_length``). On merge, the required anchor
    byte-splits. We pre-arm PN346B with the PR's inserted comment lines as
    upstream_drift_markers so the merge is caught as a LOUD, classified
    upstream-merge event in preflight instead of an unexplained anchor
    drift. The markers are absent from PN346B's own replacement text
    (SELF_COLLISION-safe, PN369 contract). SEMANTIC reconciliation on
    merge stays mandatory: PN346B's min() clamp must sit AFTER upstream's
    continue, and upstream's attention-hit preservation skips the
    hit_blocks_by_group update for the missing Mamba group — a resumed
    request would skip N tokens with NO Mamba state (boots-clean-but-
    garbage class); see the upstream_watchlist #47491 row.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

G4_26_FLAG = "GENESIS_ENABLE_G4_26_DIFFUSIONGEMMA_TP_VOCAB"

MODEL_YAML = REPO_ROOT / "sndr/model_configs/builtin/model/diffusiongemma-26b-a4b-fp8.yaml"
PROFILE_YAML = REPO_ROOT / "sndr/model_configs/builtin/profile/diffusiongemma-tp2.yaml"

# The two comment lines #47491 inserts (exact, from `gh pr diff 47491`
# 2026-07-05, commit 05855b2b5). Kept as module constants so the
# SELF_COLLISION assertion below and the patch module share one source.
PR_47491_MARKERS = (
    "# Mamba/linear-attention groups may miss when their single",
    "# Don't let a Mamba miss zero out valid attention cache hits.",
)


def _registry() -> dict:
    from sndr.dispatcher.registry import PATCH_REGISTRY
    return PATCH_REGISTRY


# ── STEP 0a: G4_26 retired with supersession provenance ─────────────


def test_g4_26_retired_with_supersession_provenance():
    """#46177 (merged 2026-06-26) ships a different-approach native TP
    fix in every live pin — outcome (c): retire, flag off, range cap."""
    body = _registry()["G4_26"]
    assert body["lifecycle"] == "retired"
    sb = str(body.get("superseded_by", ""))
    assert "46177" in sb, "G4_26 superseded_by must name merged vllm#46177"
    assert "45719" in sb, "G4_26 superseded_by must name the fixed issue #45719"
    rng = body.get("vllm_version_range") or body.get("applies_to", {}).get(
        "vllm_version_range"
    )
    assert rng, "G4_26 needs a vllm_version_range cap"
    parts = rng if isinstance(rng, (tuple, list)) else (rng,)
    assert any("<0.23.1rc1.dev672" in str(p) for p in parts), (
        f"G4_26 range must cap below dev672 (earliest pin byte-verified "
        f"native), got {rng!r}"
    )


def test_g4_26_flag_removed_from_model_yaml():
    """Range caps do NOT stop opt-in patches (dispatcher rule 1): the
    enabled flag must leave the ModelDef patches block."""
    text = MODEL_YAML.read_text(encoding="utf-8")
    assert f"{G4_26_FLAG}: '1'" not in text, (
        "diffusiongemma ModelDef still opts in to the retired G4_26 — the "
        "enabled-flag-on-a-dead-patch landmine class"
    )


def test_g4_26_profile_verify_note_reconciled():
    """The promotion contract must no longer require G4_26 'confirmed
    APPLIED at boot' — the anchor is byte-absent on every live pin, so
    that gate can never pass again (contradiction C1)."""
    text = PROFILE_YAML.read_text(encoding="utf-8")
    assert "G4_26 + PN-FP8MOE-KPAD both confirmed APPLIED at boot" not in text
    # The replacement note must still gate PN-FP8MOE-KPAD and explain the
    # G4_26 supersession.
    assert "PN-FP8MOE-KPAD" in text
    assert "46177" in text, (
        "profile promotion contract should record WHY G4_26 is no longer "
        "expected at boot (native vllm#46177)"
    )


# ── STEP 0b: PN346B pre-armed for the #47491 anchor byte-split ──────


def _pn346b_module():
    from sndr.engines.vllm.patches.kv_cache import (
        pn346b_mamba_mtp_apc_coordinator_clamp as mod,
    )
    return mod


def test_pn346b_carries_47491_drift_markers(tmp_path):
    mod = _pn346b_module()
    target = tmp_path / "kv_cache_coordinator.py"
    target.write_text("# fixture\n", encoding="utf-8")
    patcher = mod._make_patcher_for_target(str(target)) if hasattr(
        mod, "_make_patcher_for_target"
    ) else None
    if patcher is None:
        # Fall back to the module-level marker constants if the builder
        # is target-resolving only.
        markers = getattr(mod, "PN346B_UPSTREAM_DRIFT_MARKERS", None)
        assert markers is not None, (
            "PN346B must expose its drift markers for the tripwire test "
            "(PN346B_UPSTREAM_DRIFT_MARKERS or _make_patcher_for_target)"
        )
    else:
        markers = patcher.upstream_drift_markers
    for m in PR_47491_MARKERS:
        assert any(m in dm for dm in markers), (
            f"PN346B must carry #47491's inserted comment {m!r} as an "
            "upstream drift marker (loud preflight classification on merge)"
        )


def test_pn346b_47491_markers_are_self_collision_safe():
    """PN369 contract: the new markers must not appear in PN346B's own
    replacement text or idempotency marker."""
    mod = _pn346b_module()
    own_text = "\n".join(
        [
            mod.PN346B_ANCHOR_NEW,
            mod.PN346B_MAMBA_TRIM_REPLACE,
            mod.GENESIS_PN346B_MARKER,
        ]
    )
    for m in PR_47491_MARKERS:
        assert m not in own_text, (
            f"drift marker {m!r} collides with PN346B's own emitted text — "
            "would false-fire as upstream-merged (PN369 class)"
        )
