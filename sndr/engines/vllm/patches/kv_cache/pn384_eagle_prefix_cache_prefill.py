# SPDX-License-Identifier: Apache-2.0
"""PN384 — Eagle/MTP prefix-cache prefill fix (vendor of vllm#44986).

Upstream bug class (vllm#44986, issue #44858)
=============================================

When EAGLE/MTP speculative decoding is enabled with ``--enable-prefix-
caching``, ``KVCacheManager.get_computed_blocks`` looks up the longest
prefix-cache hit and then *drops the last matched block* so the drafter
can recompute the hidden states it needs for the speculative tokens. The
drop is correct in the DECODE phase — the draft head consumes the final
block's hidden states to propose the next K tokens. But it is **wrong in
the PREFILL phase**: no draft tokens have been generated yet
(``num_output_tokens == 0``), so there is nothing to recompute and the
dropped block is pure loss. Every MTP request therefore recomputes one
extra block on its very first scheduling pass.

LIVE exposure on our stack — the bug was *filed* on Qwen3.6-27B with
``block_size=1536``, which is exactly our 27B int4 PROD config (TQ k8v4,
MTP K=3). The cost scales with ``block_size``:

  * Short prompt (prompt < block_size, e.g. 100 tokens, block_size 1536):
    the single matched block IS the whole hit — dropping it collapses the
    prefix-cache hit to **0 blocks** (100 % → 0 % reuse). The entire warm
    prefix is recomputed from scratch.
  * Medium prompt (e.g. 2000 tokens, 80 % repeat): loses 1 block = 1536
    tokens of needless recomputation on every prefill.
  * Long prompt (e.g. 16000 tokens): loses 1 of ~10 full blocks.

This is a direct TTFT regression on cache-warm agent / multi-turn and
long-context GDN prefill, with **zero decode benefit** (the dropped block
was never going to help prefill). Recovering it is a pure TTFT win.

The fix (PR #44986)
===================

Thread a ``skip_eagle_pop`` flag through ``find_longest_cache_hit``:

  * ``KVCacheManager.get_computed_blocks`` derives
    ``is_prefill_phase = num_output_tokens == 0`` and passes
    ``skip_eagle_pop=is_prefill_phase`` into the coordinator.
  * The coordinator's per-strategy ``find_longest_cache_hit`` (Unitary +
    Hybrid) folds ``and not skip_eagle_pop`` into its ``drop_eagle_block``
    decision, so the last-block drop is *suppressed during prefill only*.

In the DECODE phase ``skip_eagle_pop`` is False and the path is
**byte-for-byte the original behavior** — the drafter still gets its
recompute block. This prefill-only scoping is precisely why PN384
SUPERSEDES the retired P83/P84 patches: those tried to keep the last
cached block unconditionally and were flagged unsafe-to-reanchor because
they perturbed the speculative convergence invariant in decode. PN384
skips the drop ONLY when ``num_output_tokens == 0`` (no drafts in
flight), so the convergence invariant P83 protected is preserved
untouched. P83/P84 are now archived; PN384 is the correct, narrower fix.

Sites patched (verified against pristine pin 0.22.1rc1.dev259+g303916e93)
========================================================================

``v1/core/kv_cache_coordinator.py`` — four ``find_longest_cache_hit``
signatures gain ``skip_eagle_pop: bool = False`` (abstract base +
NoPrefixCache + Unitary + Hybrid) plus the two ``drop_eagle_block``
decision sites:

  * Unitary: ``drop_eagle_block=0 in self.eagle_group_ids`` becomes
    ``... and not skip_eagle_pop``.
  * Hybrid:  ``drop_eagle_block = use_eagle and idx not in eagle_verified``
    becomes ``... and not skip_eagle_pop``.

``v1/core/kv_cache_manager.py`` — the single caller in
``get_computed_blocks`` derives ``is_prefill_phase`` and threads
``skip_eagle_pop``.

Coordination with PN346 (#43650)
================================

PN346 (Mamba/GDN + MTP + APC accuracy fix) ALSO touches the EAGLE
last-block-drop logic, but in the SIBLING file
``v1/core/single_type_kv_cache_manager.py`` (``MambaManager.find_longest_
cache_hit``), where it walks the search boundary back by one block before
the loop. PN384 does NOT touch that file — it operates one level up in the
coordinator/manager. The two patches therefore have **zero anchor
overlap** and compose cleanly:

  * PN346 fixes a DECODE-phase accuracy regression on the Mamba state
    block (recovers GSM8K accuracy).
  * PN384 fixes a PREFILL-phase TTFT regression on the prefix-cache hit
    (recovers the dropped block).

When both are active and ``skip_eagle_pop=True`` (prefill), the
coordinator passes ``drop_eagle_block=False`` down to MambaManager, so
PN346's ``if drop_eagle_block and max_num_blocks > 0`` guard is a no-op in
prefill — exactly the desired behavior (no boundary walk-back when there
is no drop to compensate). In decode, ``skip_eagle_pop=False``, both
patches engage their original semantics. No conflict.

Genesis spelling divergence (drift-marker hygiene, iron rule #10)
================================================================

Our emitted wiring spells the boolean expressions WITHOUT the PR's exact
parenthesisation: we write ``... and not skip_eagle_pop`` where #44986
writes ``... and (not skip_eagle_pop)``, and the hybrid decision stays a
single line where the PR breaks it across four. The values are identical;
the divergence keeps the PR's exact structural lines usable as upstream
drift markers (the merged-form self-skip + lint_drift_markers self-
collision contract) without ever matching our own emitted text.

Activation
==========

Opt-in via ``GENESIS_ENABLE_PN384_EAGLE_PREFIX_CACHE_PREFILL=1``
(default_on=False in the registry — this is a TTFT win with no decode
cost, but the server A/B is pending). STRONG RECOMMENDATION: enable on the
27B int4 (block_size=1536) and 35B FP8 MTP-K=3 PROD configs after the A/B
confirms the TTFT recovery, since the bug was filed on our exact 27B
shape. Self-skips when #44986 lands upstream via the drift markers below.

Author backport: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
Vendor target: vllm-project/vllm#44986 (OPEN as of 2026-06-13).
Closes vllm#44858. Supersedes retired P83/P84.
"""
from __future__ import annotations

import logging

from sndr.engines.vllm.detection.guards import resolve_vllm_file
from sndr.kernel import TextPatch, TextPatcher, result_to_wiring_status

log = logging.getLogger("genesis.wiring.pn384_eagle_prefix_cache_prefill")

GENESIS_PN384_MARKER = (
    "Genesis PN384 Eagle/MTP prefix-cache prefill fix "
    "(vendor of vllm#44986) v1"
)

_COORDINATOR_REL = "v1/core/kv_cache_coordinator.py"
_MANAGER_REL = "v1/core/kv_cache_manager.py"

# ─────────────────────────────────────────────────────────────────────
# Drift markers — exact substrings of #44986's MERGED form, taken from
# `gh pr diff 44986` on 2026-06-13. All absent in the pristine pin tree
# (g303916e93: count 0, byte-verified) and deliberately NOT substrings of
# our own replacement text (lint_drift_markers self-collision contract).
#
# We do NOT use `skip_eagle_pop: bool = False,` as a marker even though it
# is in the PR: our own signature replacement emits that identical line,
# so it would self-collide (PN369 rule). We use only the lines where our
# emitted spelling diverges from the PR (parenthesisation / line breaks).
# ─────────────────────────────────────────────────────────────────────

_COORDINATOR_DRIFT_MARKERS = (
    # Unitary decision — PR parenthesises `(not skip_eagle_pop)`; we don't.
    "            drop_eagle_block=(0 in self.eagle_group_ids) and "
    "(not skip_eagle_pop),\n",
    # Hybrid decision — PR breaks the boolean across four lines; we keep
    # it on one. This middle line is unique to the PR's multi-line form.
    "                    and (idx not in eagle_verified)\n",
)

_MANAGER_DRIFT_MARKERS = (
    # Manager caller — PR omits the parens we add around the comparison
    # (`is_prefill_phase = (request.num_output_tokens == 0)` in our form),
    # so the PR's bare line never appears in our replacement text. We do
    # NOT use the `skip_eagle_pop=is_prefill_phase,` call line as a marker:
    # our own replacement emits that identical line (PN369 self-collision).
    "        is_prefill_phase = request.num_output_tokens == 0\n",
)


# ─────────────────────────────────────────────────────────────────────
# Coordinator sub-patches: 4 signature sites + 2 decision sites.
# Anchors byte-verified count==1 against the pristine pin tree
# /private/tmp/candidate_pin_current/vllm/v1/core/kv_cache_coordinator.py.
# ─────────────────────────────────────────────────────────────────────

# --- Signature site 1: the @abstractmethod base. Disambiguated by the
#     leading `@abstractmethod` decorator and the trailing `pass`. ---
PN384_SIG_ABSTRACT_OLD = (
    "    @abstractmethod\n"
    "    def find_longest_cache_hit(\n"
    "        self,\n"
    "        block_hashes: list[BlockHash],\n"
    "        max_cache_hit_length: int,\n"
    "    ) -> tuple[tuple[list[KVCacheBlock], ...], int]:\n"
    "        pass\n"
)
PN384_SIG_ABSTRACT_NEW = (
    "    @abstractmethod\n"
    "    def find_longest_cache_hit(\n"
    "        self,\n"
    "        block_hashes: list[BlockHash],\n"
    "        max_cache_hit_length: int,\n"
    "        # [Genesis PN384 vendor of vllm#44986] Prefill-only flag: when\n"
    "        # True (num_output_tokens == 0) the EAGLE/MTP last-block drop is\n"
    "        # suppressed, since no draft tokens exist yet to recompute.\n"
    "        skip_eagle_pop: bool = False,\n"
    "    ) -> tuple[tuple[list[KVCacheBlock], ...], int]:\n"
    "        pass\n"
)

# --- Signature site 2: NoPrefixCache override. Disambiguated by the
#     trailing `blocks: tuple[...] = tuple(` body line. ---
PN384_SIG_NOPREFIX_OLD = (
    "    def find_longest_cache_hit(\n"
    "        self,\n"
    "        block_hashes: list[BlockHash],\n"
    "        max_cache_hit_length: int,\n"
    "    ) -> tuple[tuple[list[KVCacheBlock], ...], int]:\n"
    "        blocks: tuple[list[KVCacheBlock], ...] = tuple(\n"
)
PN384_SIG_NOPREFIX_NEW = (
    "    def find_longest_cache_hit(\n"
    "        self,\n"
    "        block_hashes: list[BlockHash],\n"
    "        max_cache_hit_length: int,\n"
    "        # [Genesis PN384 vendor of vllm#44986] Accepted for signature\n"
    "        # parity with the base; prefix caching is disabled here so the\n"
    "        # flag is inert (this override returns an empty hit).\n"
    "        skip_eagle_pop: bool = False,\n"
    "    ) -> tuple[tuple[list[KVCacheBlock], ...], int]:\n"
    "        blocks: tuple[list[KVCacheBlock], ...] = tuple(\n"
)

# --- Signature site 3: Unitary override. Disambiguated by the trailing
#     `hit_blocks = self.single_type_managers[0]...` body line. ---
PN384_SIG_UNITARY_OLD = (
    "    def find_longest_cache_hit(\n"
    "        self,\n"
    "        block_hashes: list[BlockHash],\n"
    "        max_cache_hit_length: int,\n"
    "    ) -> tuple[tuple[list[KVCacheBlock], ...], int]:\n"
    "        hit_blocks = self.single_type_managers[0].find_longest_cache_hit(\n"
)
PN384_SIG_UNITARY_NEW = (
    "    def find_longest_cache_hit(\n"
    "        self,\n"
    "        block_hashes: list[BlockHash],\n"
    "        max_cache_hit_length: int,\n"
    "        # [Genesis PN384 vendor of vllm#44986] Prefill-only flag; folded\n"
    "        # into drop_eagle_block below so the EAGLE drop is skipped in\n"
    "        # prefill (num_output_tokens == 0), recovering the lost block.\n"
    "        skip_eagle_pop: bool = False,\n"
    "    ) -> tuple[tuple[list[KVCacheBlock], ...], int]:\n"
    "        hit_blocks = self.single_type_managers[0].find_longest_cache_hit(\n"
)

# --- Signature site 4: Hybrid override. Disambiguated by the trailing
#     docstring opening + the iterative-fixed-point summary line. ---
PN384_SIG_HYBRID_OLD = (
    "    def find_longest_cache_hit(\n"
    "        self,\n"
    "        block_hashes: list[BlockHash],\n"
    "        max_cache_hit_length: int,\n"
    "    ) -> tuple[tuple[list[KVCacheBlock], ...], int]:\n"
    '        """\n'
    "        Find the longest cache hit using an iterative fixed-point algorithm.\n"
)
PN384_SIG_HYBRID_NEW = (
    "    def find_longest_cache_hit(\n"
    "        self,\n"
    "        block_hashes: list[BlockHash],\n"
    "        max_cache_hit_length: int,\n"
    "        # [Genesis PN384 vendor of vllm#44986] Prefill-only flag; folded\n"
    "        # into the per-group drop_eagle_block decision below so the\n"
    "        # last-block drop is skipped in prefill (num_output_tokens == 0).\n"
    "        skip_eagle_pop: bool = False,\n"
    "    ) -> tuple[tuple[list[KVCacheBlock], ...], int]:\n"
    '        """\n'
    "        Find the longest cache hit using an iterative fixed-point algorithm.\n"
)

# --- Decision site A: Unitary drop_eagle_block. We append `and not
#     skip_eagle_pop` WITHOUT the PR's `(not skip_eagle_pop)` parens so the
#     PR's exact line stays a valid drift marker. ---
PN384_UNITARY_DROP_OLD = (
    "            drop_eagle_block=0 in self.eagle_group_ids,\n"
)
PN384_UNITARY_DROP_NEW = (
    "            # [Genesis PN384 vendor of vllm#44986] Suppress the EAGLE\n"
    "            # last-block drop during prefill: skip_eagle_pop is True iff\n"
    "            # num_output_tokens == 0, so decode keeps the original drop.\n"
    "            drop_eagle_block=(0 in self.eagle_group_ids) "
    "and not skip_eagle_pop,\n"
)

# --- Decision site B: Hybrid drop_eagle_block. Single-line form (the PR
#     breaks it across four). ---
PN384_HYBRID_DROP_OLD = (
    "                drop_eagle_block = use_eagle and idx not in eagle_verified\n"
)
PN384_HYBRID_DROP_NEW = (
    "                # [Genesis PN384 vendor of vllm#44986] Suppress the EAGLE\n"
    "                # last-block drop during prefill (skip_eagle_pop True iff\n"
    "                # num_output_tokens == 0); decode keeps the original drop.\n"
    "                drop_eagle_block = (\n"
    "                    use_eagle and idx not in eagle_verified "
    "and not skip_eagle_pop\n"
    "                )\n"
)


# ─────────────────────────────────────────────────────────────────────
# Manager sub-patch: derive is_prefill_phase + thread skip_eagle_pop.
# Anchor byte-verified count==1 against the pristine pin tree
# /private/tmp/candidate_pin_current/vllm/v1/core/kv_cache_manager.py.
# We add parens around the comparison (`(request.num_output_tokens == 0)`)
# so the PR's bare form stays a valid drift marker.
# ─────────────────────────────────────────────────────────────────────

PN384_MANAGER_OLD = (
    "        max_cache_hit_length = request.num_tokens - 1\n"
    "        computed_blocks, num_new_computed_tokens = (\n"
    "            self.coordinator.find_longest_cache_hit(\n"
    "                request.block_hashes, max_cache_hit_length\n"
    "            )\n"
    "        )\n"
)
PN384_MANAGER_NEW = (
    "        max_cache_hit_length = request.num_tokens - 1\n"
    "        # [Genesis PN384 vendor of vllm#44986] Prefill phase has no draft\n"
    "        # tokens yet (num_output_tokens == 0), so the EAGLE/MTP\n"
    "        # last-block drop is pure loss here. Thread skip_eagle_pop so the\n"
    "        # coordinator keeps the final matched block during prefill,\n"
    "        # recovering 1 prefix-cache block per prefill on every MTP request\n"
    "        # (the entire hit when block_size > prompt). Decode is unchanged.\n"
    "        is_prefill_phase = (request.num_output_tokens == 0)\n"
    "        computed_blocks, num_new_computed_tokens = (\n"
    "            self.coordinator.find_longest_cache_hit(\n"
    "                request.block_hashes,\n"
    "                max_cache_hit_length,\n"
    "                skip_eagle_pop=is_prefill_phase,\n"
    "            )\n"
    "        )\n"
)


def coordinator_sub_patches() -> list[TextPatch]:
    """Return the coordinator sub-patches (exposed for tests)."""
    return [
        TextPatch(
            name="pn384_sig_abstract",
            anchor=PN384_SIG_ABSTRACT_OLD,
            replacement=PN384_SIG_ABSTRACT_NEW,
            required=True,
        ),
        TextPatch(
            name="pn384_sig_noprefix",
            anchor=PN384_SIG_NOPREFIX_OLD,
            replacement=PN384_SIG_NOPREFIX_NEW,
            required=True,
        ),
        TextPatch(
            name="pn384_sig_unitary",
            anchor=PN384_SIG_UNITARY_OLD,
            replacement=PN384_SIG_UNITARY_NEW,
            required=True,
        ),
        TextPatch(
            name="pn384_sig_hybrid",
            anchor=PN384_SIG_HYBRID_OLD,
            replacement=PN384_SIG_HYBRID_NEW,
            required=True,
        ),
        TextPatch(
            name="pn384_unitary_drop",
            anchor=PN384_UNITARY_DROP_OLD,
            replacement=PN384_UNITARY_DROP_NEW,
            required=True,
        ),
        TextPatch(
            name="pn384_hybrid_drop",
            anchor=PN384_HYBRID_DROP_OLD,
            replacement=PN384_HYBRID_DROP_NEW,
            required=True,
        ),
    ]


def manager_sub_patches() -> list[TextPatch]:
    """Return the manager sub-patches (exposed for tests)."""
    return [
        TextPatch(
            name="pn384_manager_thread",
            anchor=PN384_MANAGER_OLD,
            replacement=PN384_MANAGER_NEW,
            required=True,
        ),
    ]


def _make_coordinator_patcher_from(target_file: str) -> TextPatcher:
    """Build the coordinator TextPatcher for an explicit target path."""
    return TextPatcher(
        patch_name=(
            "PN384 v1/core/kv_cache_coordinator.py — thread skip_eagle_pop "
            "through find_longest_cache_hit (vendor of vllm#44986)"
        ),
        target_file=target_file,
        marker=GENESIS_PN384_MARKER,
        sub_patches=coordinator_sub_patches(),
        upstream_drift_markers=list(_COORDINATOR_DRIFT_MARKERS),
    )


def _make_manager_patcher_from(target_file: str) -> TextPatcher:
    """Build the manager TextPatcher for an explicit target path."""
    return TextPatcher(
        patch_name=(
            "PN384 v1/core/kv_cache_manager.py — derive is_prefill_phase + "
            "thread skip_eagle_pop (vendor of vllm#44986)"
        ),
        target_file=target_file,
        marker=GENESIS_PN384_MARKER,
        sub_patches=manager_sub_patches(),
        upstream_drift_markers=list(_MANAGER_DRIFT_MARKERS),
    )


def _make_coordinator_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(_COORDINATOR_REL)
    if target is None:
        return None
    return _make_coordinator_patcher_from(str(target))


def _make_manager_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(_MANAGER_REL)
    if target is None:
        return None
    return _make_manager_patcher_from(str(target))


def apply() -> tuple[str, str]:
    """Apply PN384 — Eagle/MTP prefix-cache prefill fix. Never raises.

    Opt-in: gated through the dispatcher on
    ``GENESIS_ENABLE_PN384_EAGLE_PREFIX_CACHE_PREFILL`` (default_on=False
    in the registry — direct TTFT win with zero decode cost, server A/B
    pending). Patches BOTH the coordinator and the manager file; a missing
    target is a clean ``skipped`` (not a failure).
    """
    from sndr.dispatcher import log_decision, should_apply

    decision, reason = should_apply("PN384")
    log_decision("PN384", decision, reason)
    if not decision:
        return "skipped", reason

    coord_patcher = _make_coordinator_patcher()
    mgr_patcher = _make_manager_patcher()
    if coord_patcher is None or mgr_patcher is None:
        return (
            "skipped",
            "PN384: target file(s) not resolvable "
            f"(coordinator={_COORDINATOR_REL}, manager={_MANAGER_REL})",
        )

    statuses: list[tuple[str, str]] = []
    for patcher, applied_msg in (
        (
            coord_patcher,
            "PN384 coordinator patch applied — find_longest_cache_hit now "
            "accepts skip_eagle_pop and suppresses the EAGLE/MTP last-block "
            "drop when it is True (prefill, num_output_tokens == 0). Decode "
            "path byte-unchanged (vendor of vllm#44986).",
        ),
        (
            mgr_patcher,
            "PN384 manager patch applied — get_computed_blocks derives "
            "is_prefill_phase = num_output_tokens == 0 and threads "
            "skip_eagle_pop into the coordinator, recovering 1 prefix-cache "
            "block per prefill on every MTP request (the entire hit when "
            "block_size > prompt). Direct TTFT win, zero decode cost.",
        ),
    ):
        result, failure = patcher.apply()
        statuses.append(
            result_to_wiring_status(
                result,
                failure,
                applied_message=applied_msg,
                patch_name=patcher.patch_name,
            )
        )

    # Fail if any sub-patcher hard-failed; otherwise "applied" if at least
    # one file changed, else "skipped" (idempotent / drift on both files).
    if any(s == "failed" for s, _ in statuses):
        detail = " | ".join(d for _, d in statuses)
        return "failed", f"PN384 (vllm#44986): {detail}"
    if any(s == "applied" for s, _ in statuses):
        detail = " | ".join(d for _, d in statuses)
        return "applied", f"PN384 (vllm#44986): {detail}"
    detail = " | ".join(d for _, d in statuses)
    return "skipped", f"PN384 (vllm#44986): {detail}"


def is_applied() -> bool:
    """Return True iff our marker is present in BOTH target files."""
    coord_patcher = _make_coordinator_patcher()
    mgr_patcher = _make_manager_patcher()
    if coord_patcher is None or mgr_patcher is None:
        return False
    for patcher in (coord_patcher, mgr_patcher):
        try:
            with open(patcher.target_file, encoding="utf-8") as f:
                if patcher.marker not in f.read():
                    return False
        except (OSError, UnicodeDecodeError):
            return False
    return True
