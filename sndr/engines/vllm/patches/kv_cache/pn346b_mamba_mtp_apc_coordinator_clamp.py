# SPDX-License-Identifier: Apache-2.0
"""PN346B — coordinator-half clamp (vendor of OPEN PR vllm#45614).

The COORDINATOR half of the SAME fix whose MANAGER half is PN346
==============================================================

Upstream PR vllm#45614 ("[Bugfix][Core] Fix Mamba prefix cache EAGLE
hit", closes vllm#43559) ships TWO halves that together fix the hybrid
Mamba + EAGLE/MTP + ``--enable-prefix-caching`` prefix-cache poison on
our exact PROD shape (Qwen3.6-35B-A3B FP8, MTP K=3, prefix caching on):

  * MANAGER half — ``single_type_kv_cache_manager.py``: walk the
    ``MambaManager`` search boundary back by one block on the EAGLE/MTP
    path so the partially-accepted final SSM state block is never
    matched. **Genesis already vendors this as PN346.**

  * COORDINATOR half — ``v1/core/kv_cache_coordinator.py`` (THIS patch):
    clamp ``curr_hit_length`` so it is **monotonically non-increasing**
    across ``HybridKVCacheCoordinator.find_longest_cache_hit``'s
    fixed-point iteration. **Genesis was MISSING this half.**

Genesis shipped only the manager half (PN346). The coordinator clamp
is the missing sibling — without it, the fixed-point loop can re-grow
``curr_hit_length`` on a verify pass and re-admit the very state block
PN346 walked back, partially defeating the manager-half guard. The two
halves MUST compose and ship together (registry ``composes_with``
cross-references PN346 ⇄ PN346B).

Root cause — the eagle-drop branch can GROW curr_hit_length
=========================================================

Inside ``HybridKVCacheCoordinator.find_longest_cache_hit`` (a while/for
fixed-point loop) each group computes::

    _new_hit_length = len(hit_blocks[0]) * spec.block_size
    if drop_eagle_block:                  # (dev491) / `if use_eagle:` (PROD)
        eagle_verified.add(idx)
    elif _new_hit_length < curr_hit_length:
        # length shrunk; invalidate previous eagle verifications
        eagle_verified.clear()
    curr_hit_length = _new_hit_length     # <-- BUG: naked assignment

The naked assignment unconditionally overwrites ``curr_hit_length``
with ``_new_hit_length``. On the eagle-drop branch ``_new_hit_length``
can be LONGER than the current candidate; the assignment then GROWS
``curr_hit_length`` on a verify pass and re-admits the partially-
accepted final state block — the exact poison PN346 fixes in the
manager. The fix clamps so the value can only stay or shrink::

    curr_hit_length = min(curr_hit_length, _new_hit_length)

This matches the manager-half guard's intent: the hit length is
monotonically non-increasing across the fixed-point iteration.

Pin-agnostic anchor (resolves byte-identically on dev491 AND PROD)
=================================================================

The line IMMEDIATELY ABOVE the clamp diverges by pin:

  * dev491 (0.22.1rc1.dev491+g1033ffac2): ``if drop_eagle_block:``
    (loop unpacks ``(spec, group_ids, manager_cls, use_eagle)``;
    local ``drop_eagle_block = use_eagle and idx not in eagle_verified``).
  * PROD   (0.21.1rc0+g626fa9bba):        ``if use_eagle:``
    (loop unpacks ``(spec, group_ids, manager_cls)``;
    local ``use_eagle = idx in self.eagle_attn_group_indices and
    idx not in eagle_verified``).

So the anchor DELIBERATELY EXCLUDES that ``if ...:`` line. The 4-line
anchor (``elif _new_hit_length < curr_hit_length:`` →
``curr_hit_length = _new_hit_length``) is byte-identical AND
grep-unique (count==1) on BOTH pins. Verified: ``min(curr_hit_length``
is absent on the live dev491 container AND the PROD image → the clamp
is genuinely missing on both.

Why we vendor this OPEN PR (not just wait for upstream merge)
=============================================================

  * It is the missing half of a correctness fix Genesis ALREADY ships
    default-ON (PN346). A half-fix is worse than none: the manager
    guard can be partially undone by the unclamped coordinator re-grow.
  * The fix is a ONE-LINE ``min()`` clamp — surgical, no perf cost on
    the non-EAGLE path, no signature change, no caller change.
  * Same upstream issue (#43559), same PR (#45614) as PN346 — they are
    a unit. Composition + default-ON parity guarantee both land
    together on every boot.

Part-B defensive belt (vendor of vllm#46281 Part B)
===================================================

A SECOND, ``required=False`` sub-patch folds in the Mamba-group
post-loop truncation from the THIRD independent upstream attempt at the
same #43559 poison (PR vllm#46281). After the fixed-point loop,
``find_longest_cache_hit`` already truncates the FULL-ATTENTION group's
hit-block list to the final ``hit_length``; the belt mirrors that for
the Mamba group on a simple hybrid (``FullAttentionManager`` drops its
last hit block on the EAGLE look-ahead path but ``MambaManager`` does
not, so the two block lists can be left misaligned). It is LATENT on
PROD (APC OFF on our hybrid 27B/35B) and largely redundant given PN346's
manager-half walk-back, but survives the thin window where PN346's
manager anchor drift-skips while PN346B still applies. Guarded on
``is_simple_hybrid and len(attention_groups) > 1 and
isinstance(attention_groups[1].spec, MambaSpec)`` (edge-case hardening
over the PR's bare index assumption) so it is a strict no-op on any
non-simple-hybrid / non-Mamba topology. ``required=False`` so a missing
FA-truncation anchor (future refactor) soft-skips and the load-bearing
Part-A clamp still lands. No new patch id — the belt rides PN346B's
existing env flag, lifecycle, and version range (design t1 §4).

Composition + safety
====================

  * Targets ``v1/core/kv_cache_coordinator.py`` — a DIFFERENT file than
    PN346 (``single_type_kv_cache_manager.py``). Zero anchor overlap;
    the two coexist by construction.
  * No P85-style anchor overlap exists on the coordinator file, so
    PN346B needs no dual-anchor variants.
  * Opt-out-only (default-ON), mirroring PN346: honors
    ``GENESIS_DISABLE_PN346B``, ignores ``GENESIS_ENABLE_PN346B``.
  * Self-skips once #45614 merges upstream via the drift marker
    ``curr_hit_length = min(curr_hit_length, _new_hit_length)`` (the
    exact merged shape) → idempotent / skip, file untouched.

Upstream regression test (lives in the vLLM tree, not Genesis):
``test_hybrid_mamba_eagle_does_not_reuse_lookahead_state`` in
``tests/v1/core/test_prefix_caching.py`` (carried by PR #45614).

Risk: LOW — one-line ``min()`` clamp, only narrows the hit length.
Effort: XS.

Author: Sander Barzov Aleksandr (Sandermage, Ukraine, Odessa).
Vendor target: vllm-project/vllm#45614 (open as of 2026-06-17).
Sibling of PN346 (manager half). Closes vllm#43559 (coordinator half).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from sndr.engines.vllm.detection.guards import resolve_vllm_file
from sndr.kernel import TextPatch, TextPatcher, TextPatchResult

log = logging.getLogger(
    "genesis.wiring.pn346b_mamba_mtp_apc_coordinator_clamp"
)

GENESIS_PN346B_MARKER = (
    "Genesis PN346B vendor of vllm#45614 "
    "(Mamba/GDN + EAGLE/MTP + APC coordinator clamp) v1"
)


# Anchor: the 4-line sequence inside
# HybridKVCacheCoordinator.find_longest_cache_hit right where the loop
# overwrites curr_hit_length. It DELIBERATELY EXCLUDES the line above
# (`if drop_eagle_block:` on dev491 / `if use_eagle:` on PROD) which
# diverges by pin — so this anchor is byte-identical and grep-unique
# (count==1) on BOTH the live dev491 container and the PROD image.
PN346B_ANCHOR_OLD = (
    "                elif _new_hit_length < curr_hit_length:\n"
    "                    # length shrunk; invalidate previous eagle verifications\n"
    "                    eagle_verified.clear()\n"
    "                curr_hit_length = _new_hit_length\n"
)

PN346B_ANCHOR_NEW = (
    "                elif _new_hit_length < curr_hit_length:\n"
    "                    # length shrunk; invalidate previous eagle verifications\n"
    "                    eagle_verified.clear()\n"
    "                # [Genesis PN346B vendor of vllm#45614] Coordinator half of the\n"
    "                # Mamba+EAGLE/MTP APC prefix-cache fix. The eagle-drop branch can\n"
    "                # report a _new_hit_length LONGER than the current candidate; the\n"
    "                # naked assignment would then GROW curr_hit_length on a verify pass\n"
    "                # and re-admit the partially-accepted final state block. Clamp so\n"
    "                # the hit length is monotonically non-increasing across the\n"
    "                # fixed-point iteration, matching the manager-half guard (PN346).\n"
    "                curr_hit_length = min(curr_hit_length, _new_hit_length)\n"
)


# ── Part-B belt: Mamba-group post-loop truncation (vllm#46281 Part B) ─
#
# PR vllm#46281 ("Align hybrid model prefix-cache hit lengths …") is a
# THIRD, independent upstream attempt at the same #43559 poison. Its
# Part A (curr_hit_length min() clamp) is byte-identical to what PN346B
# already ships above, so it adds nothing. Its Part B is a DIFFERENT
# site: after the fixed-point loop, mirror the existing full-attention
# block truncation for the Mamba group so the Mamba hit-block list is
# also trimmed to the final hit_length (FullAttentionManager drops its
# last hit block on the EAGLE look-ahead path but MambaManager does not,
# so without the mirror the two block lists can be left misaligned).
#
# We fold ONLY Part B into PN346B as a required=False DEFENSIVE BELT
# (design t1 §4). It is latent on PROD (APC is OFF for our hybrid 27B/35B)
# and largely redundant given PN346's manager-half walk-back, which makes
# the final-state block never *considered*. It survives the thin window
# where PN346's manager anchor drift-skips on a future pin but PN346B
# still applies — in that window the post-loop Mamba trim is the only
# thing left trimming the Mamba list.
#
# Anchor: the post-loop full-attention truncation block (byte-identical
# and grep-unique on dev424). Replacement: append a Mamba-group mirror.
#
# Edge-case hardening over the raw PR (iron-rule #10): the PR's Part B
# assumes attention_groups[1] exists and is the Mamba spec. We guard on
# is_simple_hybrid (the loop-local already computed above) AND
# len(self.attention_groups) > 1 AND isinstance(...[1].spec, MambaSpec)
# so the belt is a strict no-op on any non-simple-hybrid / non-Mamba
# topology rather than an IndexError. required=False so a missing
# FA-truncation anchor (e.g. a future refactor) soft-skips and the
# load-bearing Part-A clamp still lands.
PN346B_MAMBA_TRIM_ANCHOR = (
    "        # Truncate full attention blocks to final hit_length (if present)\n"
    "        first_group = self.attention_groups[0]\n"
    "        if isinstance(first_group.spec, FullAttentionSpec):\n"
    "            num_blocks = hit_length // first_group.spec.block_size\n"
    "            for group_id in first_group.group_ids:\n"
    "                if (blks := hit_blocks_by_group[group_id]) is not None:\n"
    "                    del blks[num_blocks:]\n"
)

PN346B_MAMBA_TRIM_REPLACE = (
    "        # Truncate full attention blocks to final hit_length (if present)\n"
    "        first_group = self.attention_groups[0]\n"
    "        if isinstance(first_group.spec, FullAttentionSpec):\n"
    "            num_blocks = hit_length // first_group.spec.block_size\n"
    "            for group_id in first_group.group_ids:\n"
    "                if (blks := hit_blocks_by_group[group_id]) is not None:\n"
    "                    del blks[num_blocks:]\n"
    "\n"
    "        # [Genesis PN346B Part-B belt vendor of vllm#46281] Mirror the\n"
    "        # full-attention truncation above for the Mamba group on a simple\n"
    "        # hybrid. FullAttentionManager drops its last hit block on the\n"
    "        # EAGLE look-ahead path but MambaManager does not, so the two block\n"
    "        # lists can be left misaligned; trim the Mamba group to the final\n"
    "        # hit_length too. Defensive belt (APC OFF on our hybrid, and PN346's\n"
    "        # manager walk-back already handles the common case) that survives a\n"
    "        # PN346 manager-half anchor drift-skip. Guarded so it is a strict\n"
    "        # no-op on any non-simple-hybrid / non-Mamba topology.\n"
    "        if (\n"
    "            is_simple_hybrid\n"
    "            and len(self.attention_groups) > 1\n"
    "            and isinstance(self.attention_groups[1].spec, MambaSpec)\n"
    "        ):\n"
    "            second_group = self.attention_groups[1]\n"
    "            num_blocks = hit_length // second_group.spec.block_size\n"
    "            for group_id in second_group.group_ids:\n"
    "                if (blks := hit_blocks_by_group[group_id]) is not None:\n"
    "                    del blks[num_blocks:]\n"
)


# ── Upstream drift markers ────────────────────────────────────────────
# [2026-07-05, batch-triage STEP 0b] OPEN vllm#47491 ("Preserve attention
# cache hits when Mamba group misses", #45238) inserts 5 lines INSIDE the
# 4-line PN346B_ANCHOR_OLD span (between `eagle_verified.clear()` and the
# naked `curr_hit_length = _new_hit_length` — verified against `gh pr diff
# 47491`, commit 05855b2b5). On merge the required anchor byte-splits; the
# PR's exact inserted comment lines below pre-classify that event as a
# LOUD upstream-merge in preflight instead of an unexplained anchor drift.
# Both lines are absent from PN346B's own replacement text
# (SELF_COLLISION-safe, PN369 contract; pinned by
# tests/unit/dispatcher/test_batch_triage_2026_07_05_step0.py).
# ON-MERGE SEMANTIC RECONCILIATION IS STILL MANDATORY (see the
# upstream_watchlist #47491 row): PN346B's min() clamp must be re-derived
# to sit AFTER upstream's `continue`, and upstream's attention-hit
# preservation skips the hit_blocks_by_group update for the missing Mamba
# group — a resumed request would skip N tokens with NO Mamba state (the
# boots-clean-but-garbage class); P85's shadow fine-hash stays OUR
# mechanism for that half (iron-rule-10 outcome: different-broken-
# approach-same-goal).
PN346B_UPSTREAM_DRIFT_MARKERS = (
    # Genesis sentinel (our own idempotency banner; defended convention
    # entry). The #45614-merge case is additionally handled by ANCHOR-
    # ABSENCE: once #45614 lands, the naked `curr_hit_length =
    # _new_hit_length` anchor is gone, so the patcher SKIPs cleanly. A bare
    # `curr_hit_length = min(...)` marker would self-collide with this
    # patch's own replacement (caught by tools/lint_drift_markers.py), so
    # it is intentionally NOT used as a drift sentinel.
    "[Genesis PN346B",
    # vllm#47491's exact inserted comment lines (never emitted by us).
    "# Mamba/linear-attention groups may miss when their single",
    "# Don't let a Mamba miss zero out valid attention cache hits.",
)


def _env_disabled() -> bool:
    return os.environ.get("GENESIS_DISABLE_PN346B", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _make_patcher() -> Optional[TextPatcher]:
    """Build the coordinator-clamp patcher, or None if target absent."""
    target = resolve_vllm_file("v1/core/kv_cache_coordinator.py")
    if target is None:
        return None
    return TextPatcher(
        patch_name=(
            "PN346B vllm/v1/core/kv_cache_coordinator.py — "
            "Mamba/GDN + EAGLE/MTP + APC curr_hit_length min() clamp "
            "(coordinator half of #45614)"
        ),
        target_file=str(target),
        marker=GENESIS_PN346B_MARKER,
        sub_patches=[
            TextPatch(
                name="pn346b_coordinator_curr_hit_length_clamp",
                anchor=PN346B_ANCHOR_OLD,
                replacement=PN346B_ANCHOR_NEW,
                required=True,
            ),
            # Part-B belt (vllm#46281 Part B): post-loop Mamba-group
            # truncation mirror. required=False — a missing FA-truncation
            # anchor (future refactor) soft-skips while the load-bearing
            # clamp above still lands. Latent on PROD (APC OFF); composes
            # with PN346's manager walk-back (this is the post-loop belt).
            TextPatch(
                name="pn346b_mamba_group_post_trim",
                anchor=PN346B_MAMBA_TRIM_ANCHOR,
                replacement=PN346B_MAMBA_TRIM_REPLACE,
                required=False,
            ),
        ],
        upstream_drift_markers=list(PN346B_UPSTREAM_DRIFT_MARKERS),
    )


def apply() -> tuple[str, str]:
    """Apply PN346B — coordinator-half curr_hit_length min() clamp."""
    if _env_disabled():
        return "skipped", "PN346B disabled via GENESIS_DISABLE_PN346B=1"

    patcher = _make_patcher()
    if patcher is None:
        return "skipped", "v1/core/kv_cache_coordinator.py not found"

    try:
        result, failure = patcher.apply()
    except Exception as e:  # noqa: BLE001
        return "failed", f"PN346B apply raised {e!r}"

    if result == TextPatchResult.FAILED:
        reason = failure.reason if failure else "unknown"
        return "failed", f"PN346B: {reason}"
    if result == TextPatchResult.SKIPPED:
        reason = failure.reason if failure else "unknown"
        return "skipped", f"PN346B: {reason}"
    if result == TextPatchResult.IDEMPOTENT:
        return "applied", "PN346B already applied (idempotent)"

    return "applied", (
        "PN346B applied: HybridKVCacheCoordinator.find_longest_cache_hit now "
        "clamps curr_hit_length = min(curr_hit_length, _new_hit_length) so the "
        "fixed-point hit length is monotonically non-increasing. Coordinator "
        "half of OPEN PR vllm#45614 (closes #43559); composes with the manager "
        "half PN346 — the two MUST ship together. 1-LOC surgical clamp. No-op "
        "on the non-EAGLE path."
    )


def is_applied() -> bool:
    from pathlib import Path
    target = resolve_vllm_file("v1/core/kv_cache_coordinator.py")
    if target is None:
        return False
    try:
        return GENESIS_PN346B_MARKER in Path(str(target)).read_text(
            encoding="utf-8"
        )
    except (OSError, UnicodeDecodeError):
        return False
