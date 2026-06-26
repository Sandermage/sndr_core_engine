# SPDX-License-Identifier: Apache-2.0
"""P88 — prefix-cache stats retry de-duplication (rewrite of OPEN vllm#45202).

================================================================
PROBLEM (issue #43736)
================================================================

``KVCacheManager.get_computed_blocks`` records the local prefix-cache
query/hit stats at LOOKUP time (pristine
``v1/core/kv_cache_manager.py``)::

    if self.log_stats:
        assert self.prefix_cache_stats is not None
        self.prefix_cache_stats.record(
            num_tokens=request.num_tokens,
            num_hits=num_new_computed_tokens,
            preempted=request.num_preemptions > 0,
        )

A waiting request whose ``allocate_slots`` then FAILS (no free blocks)
stays in the waiting queue and repeats the lookup on a later scheduler
step — so the stats are counted once PER ATTEMPT. Under KV-pressure
burst retries (the Genesis long-context agent profile) the reported
``prefix_hit_rate`` inflates by tens of percent, poisoning the
P85 / TQ-KV A/B conclusions that read it off ``/metrics``.

================================================================
FIX — Genesis rewrite, NOT the upstream diff
================================================================

Upstream #45202 moves the record into the ~2000-line
``Scheduler.schedule()`` waiting loop. P88 instead keeps BOTH sites
inside ``kv_cache_manager.py`` (P79d-style minimal-anchor convention):

  * the LOOKUP site stashes a single pending record on
    ``self._genesis_p88_pending_stats`` (request_id, num_tokens,
    num_hits, preempted) instead of recording;
  * ``allocate_slots`` COMMITS that record exactly once, right after
    its last failure ``return None`` (so the allocation is guaranteed
    to succeed), gated on a request-id match so a stale stash from a
    different request is never consumed, and clears the slot so a
    second allocate for the same request (running-loop growth) does
    not double-record.

PIN COVERAGE (dual-anchor): the LOOKUP site is byte-identical on the
current pin 0.22.1rc1.dev259 and the candidate 0.22.1rc1.dev491, so it
is one required sub-patch. The COMMIT site (the available-blocks gate)
MOVED in dev491 — it gained a ``watermark_blocks`` headroom term and a
leading comment, so the predicate now reads
``required_blocks > available_blocks``. Both gate shapes are carried as
mutually-exclusive ``required=False`` commit variants (PN351 / PN32 /
P18B convention); exactly one matches per pin and ``apply()`` enforces
that at least one fired.

This is also MORE faithful than upstream for our configs: stats record
iff a real lookup happened, so ``enable_caching=False`` / no-lookup
paths record nothing (upstream's scheduler-side record can fire even
when pristine never recorded).

================================================================
SCOPE / SAFETY
================================================================

* Opt-in: ``GENESIS_ENABLE_P88_PREFIX_CACHE_STATS_DEDUP=1``
  (default_on=False in the registry — metrics-only, lands after a
  ``/metrics`` hit-rate sanity check on 35B).
* Fallback-disable when a KV connector is configured
  (``--kv-transfer-config`` / ``--kv-connector`` / LMCache env): with
  a connector driving allocation, the in-process retry de-dup does not
  model the transfer lifecycle, so we skip rather than risk a wrong
  count.
* Drift: if upstream merges #45202 it removes the lookup-site
  ``record(`` call, so the (required) LOOKUP anchor no longer matches
  and the patch self-skips cleanly — no explicit drift marker needed.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
"""
from __future__ import annotations

import logging
import os
import sys

from sndr.engines.vllm.detection.guards import resolve_vllm_file
from sndr.kernel import (
    TextPatch,
    TextPatcher,
    TextPatchResult,
    result_to_wiring_status,
)

log = logging.getLogger("genesis.wiring.p88_prefix_cache_stats_dedup")

GENESIS_P88_MARKER = (
    "Genesis P88 prefix-cache stats retry de-duplication "
    "(vllm#45202 rewrite — lookup stash + allocate commit)"
)

_TARGET_REL = "v1/core/kv_cache_manager.py"


# ─── Anchors (byte-exact vs pristine 0.22.1rc1.dev259 / .dev491 + fake) ───
#
# DUAL-ANCHOR convention (PN351 / PN32 / P18B pattern). PROD 35B stays on
# dev259 until dev491 is validated, so P88 MUST keep working on dev259 AND
# start working on dev491. The LOOKUP site is byte-identical on both pins
# (verified count==1 in each pristine tree) so it stays a single required
# sub-patch. The ALLOC_COMMIT site MOVED in dev491 (vllm 0.22.1rc1.dev491
# +g1033ffac2): the available-blocks gate gained a `watermark_blocks`
# headroom term and a leading explanatory comment, and the predicate now
# reads `required_blocks > available_blocks` instead of
# `num_blocks_to_allocate > available_blocks`. We keep the dev259 anchor as
# one variant AND add a dev491-shaped variant, both required=False, with
# apply() enforcing that exactly one fired (required-at-least-one). On any
# given pin EXACTLY ONE commit anchor is present (the shapes are mutually
# exclusive — verified count==1 in its target tree, count==0 in the other)
# so the non-matching variant soft-skips.

# LOOKUP site — the record() call inside get_computed_blocks. Byte-identical
# on dev259 and dev491 (count==1 in each pristine tree).
P88_LOOKUP_ANCHOR = (
    "        if self.log_stats:\n"
    "            assert self.prefix_cache_stats is not None\n"
    "            self.prefix_cache_stats.record(\n"
    "                num_tokens=request.num_tokens,\n"
    "                num_hits=num_new_computed_tokens,\n"
    "                preempted=request.num_preemptions > 0,\n"
    "            )\n"
)

# The lookup becomes a pure STASH — recording here is the bug.
P88_LOOKUP_REPLACEMENT = (
    "        if self.log_stats:\n"
    "            assert self.prefix_cache_stats is not None\n"
    "            # [Genesis P88] STASH the lookup stats; the commit happens\n"
    "            # in allocate_slots once the allocation is past its last\n"
    "            # failure return. Recording here double-counted failed\n"
    "            # scheduling retries (#43736), inflating prefix_hit_rate\n"
    "            # under KV-pressure bursts (long-ctx agent profile).\n"
    "            self._genesis_p88_pending_stats = (\n"
    "                request.request_id,\n"
    "                request.num_tokens,\n"
    "                num_new_computed_tokens,\n"
    "                request.num_preemptions > 0,\n"
    "            )\n"
)

# COMMIT site — the available-blocks gate (the LAST failure return in
# allocate_slots; verified past the last `return None` in BOTH pins).
#
# The commit body appended by each variant is identical; only the matched
# gate shape differs between pins. Keeping the body in one helper avoids
# the two variants drifting apart.
_P88_COMMIT_BODY = (
    "\n"
    "        # [Genesis P88] commit the pending prefix-cache stats exactly\n"
    "        # once, now that the allocation is past its last failure\n"
    "        # return. Match on request_id so a stale stash from a\n"
    "        # different request is never consumed; clear the slot so a\n"
    "        # second allocate for the same request (running-loop growth)\n"
    "        # does not double-record.\n"
    "        _p88_pending = getattr(self, \"_genesis_p88_pending_stats\", None)\n"
    "        if _p88_pending is not None and _p88_pending[0] == request.request_id:\n"
    "            if self.log_stats and self.prefix_cache_stats is not None:\n"
    "                self.prefix_cache_stats.record(\n"
    "                    num_tokens=_p88_pending[1],\n"
    "                    num_hits=_p88_pending[2],\n"
    "                    preempted=_p88_pending[3],\n"
    "                )\n"
    "            self._genesis_p88_pending_stats = None\n"
)

# Variant A — CURRENT pin g303916e93 (0.22.1rc1.dev259, the tree PROD 35B
# runs). The gate reads `num_blocks_to_allocate > available_blocks` and has
# no watermark headroom term. count==1 in dev259, count==0 in dev491.
P88_ALLOC_COMMIT_ANCHOR = (
    "        available_blocks = self.block_pool.get_num_free_blocks() - reserved_blocks\n"
    "        if num_blocks_to_allocate > available_blocks:\n"
    "            # Cannot allocate new blocks\n"
    "            return None\n"
)

P88_ALLOC_COMMIT_REPLACEMENT = P88_ALLOC_COMMIT_ANCHOR + _P88_COMMIT_BODY

# Variant B — CANDIDATE pin g1033ffac2 (0.22.1rc1.dev491, 232 commits newer).
# The available-blocks gate grew a leading two-line comment plus a
# `required_blocks = num_blocks_to_allocate + watermark_blocks` headroom
# term, and the predicate now reads `required_blocks > available_blocks`.
# It is still the LAST `return None` in allocate_slots (verified: the later
# allocation path has no further failure return), so the commit point stays
# correct. count==1 in dev491, count==0 in dev259.
P88_ALLOC_COMMIT_DEV491_ANCHOR = (
    "        # Keep `reserved_blocks` free for other in-flight sequences, and an\n"
    "        # additional watermark of headroom for waiting/preempted admissions.\n"
    "        available_blocks = self.block_pool.get_num_free_blocks() - reserved_blocks\n"
    "        required_blocks = num_blocks_to_allocate + watermark_blocks\n"
    "        if required_blocks > available_blocks:\n"
    "            # Cannot allocate new blocks\n"
    "            return None\n"
)

P88_ALLOC_COMMIT_DEV491_REPLACEMENT = (
    P88_ALLOC_COMMIT_DEV491_ANCHOR + _P88_COMMIT_BODY
)

# Names of the two mutually-exclusive commit-anchor variants. apply()
# requires that AT LEAST ONE fired — a lookup-only half-apply is incoherent
# (the lookup site becomes a pure stash that is then never committed, so the
# stats silently stop recording entirely).
_COMMIT_VARIANT_NAMES = (
    "p88_alloc_commit",
    "p88_alloc_commit_dev491",
)


def _connector_configured() -> str | None:
    """Return a short reason string when a KV connector is configured
    (so P88 should fallback-disable), else None.

    Probes the live launch ``sys.argv`` for ``--kv-transfer-config`` /
    ``--kv-connector`` (space- or ``=``-separated) and the LMCache /
    vLLM connector env vars.
    """
    for tok in list(sys.argv):
        if tok in ("--kv-transfer-config", "--kv-connector"):
            return f"CLI flag {tok}"
        if tok.startswith("--kv-transfer-config=") or tok.startswith(
            "--kv-connector="
        ):
            return f"CLI flag {tok.split('=', 1)[0]}"
    for var in ("VLLM_KV_TRANSFER_CONFIG", "LMCACHE_CONFIG_FILE"):
        if os.environ.get(var):
            return f"env {var}"
    return None


def _make_kv_cache_manager_patcher(
    target_file: str | None = None,
) -> TextPatcher:
    """Build the two-site KVCacheManager patcher.

    ``target_file`` is injectable so the unit tests can run the de-dup
    semantics end-to-end against a synthetic-but-compilable fake; in
    production it resolves through the alternate-root seam.
    """
    if target_file is None:
        resolved = resolve_vllm_file(_TARGET_REL)
        target_file = str(resolved) if resolved is not None else _TARGET_REL
    return TextPatcher(
        patch_name=(
            "P88 v1/core/kv_cache_manager.py — prefix-cache stats retry "
            "de-duplication (vllm#45202 rewrite)"
        ),
        target_file=target_file,
        marker=GENESIS_P88_MARKER,
        sub_patches=[
            # LOOKUP site — byte-identical on dev259 and dev491, so a single
            # required sub-patch covers both pins. If #45202 merges upstream
            # it removes this record() call, the anchor vanishes, and the
            # whole patch self-skips (the correct drift behavior).
            TextPatch(
                name="p88_lookup_stash",
                anchor=P88_LOOKUP_ANCHOR,
                replacement=P88_LOOKUP_REPLACEMENT,
                required=True,
            ),
            # COMMIT site — DUAL-ANCHOR (required-at-least-one). Both
            # variants required=False; the non-matching one soft-skips
            # (siblings continue). apply() asserts at least one fired so a
            # lookup-only half-apply fails loudly instead of silently
            # zeroing the prefix-cache stats.
            # Variant A — current pin dev259 (num_blocks_to_allocate gate).
            TextPatch(
                name="p88_alloc_commit",
                anchor=P88_ALLOC_COMMIT_ANCHOR,
                replacement=P88_ALLOC_COMMIT_REPLACEMENT,
                required=False,
            ),
            # Variant B — candidate pin dev491 (required_blocks/watermark gate).
            TextPatch(
                name="p88_alloc_commit_dev491",
                anchor=P88_ALLOC_COMMIT_DEV491_ANCHOR,
                replacement=P88_ALLOC_COMMIT_DEV491_REPLACEMENT,
                required=False,
            ),
        ],
        # No explicit upstream_drift_markers: if #45202 merges it removes
        # the required LOOKUP record() anchor, so the patcher self-skips
        # with "anchor not found" — the correct drift behavior, with no
        # self-collision risk (PN369 class).
        upstream_drift_markers=[],
    )


def apply() -> tuple[str, str]:
    """Apply P88 — prefix-cache stats retry de-dup. Never raises."""
    from sndr.dispatcher import log_decision, should_apply

    decision, reason = should_apply("P88")
    log_decision("P88", decision, reason)
    if not decision:
        return "skipped", reason

    conn = _connector_configured()
    if conn is not None:
        return "skipped", (
            f"P88 fallback-disabled: KV connector configured ({conn}); the "
            "in-process retry de-dup does not model a connector-driven "
            "allocation lifecycle"
        )

    patcher = _make_kv_cache_manager_patcher()
    result, failure = patcher.apply()

    # At-least-one commit variant must have fired. Both commit variants are
    # required=False, so a future drift that breaks BOTH gate shapes would
    # let the required LOOKUP sub apply alone — turning the lookup site into
    # a pure stash that is never committed, silently zeroing the
    # prefix-cache stats. Detect that and FAIL loudly (PN351 convention).
    if result == TextPatchResult.APPLIED:
        if not set(patcher.applied_sub_patches).intersection(
            _COMMIT_VARIANT_NAMES
        ):
            return "failed", (
                "P88 FAILED — lookup-stash sub-patch applied but NEITHER "
                "alloc-commit anchor variant matched (dev259 "
                "num_blocks_to_allocate gate / dev491 required_blocks "
                "watermark gate). The commit is the load-bearing half; a "
                "lookup-only apply turns the record() into a never-committed "
                "stash and zeroes the prefix-cache stats. Anchor drift past a "
                "NEW pin shape — re-derive the allocate_slots commit anchor."
            )

    return result_to_wiring_status(
        result,
        failure,
        applied_message=(
            "P88 applied: KVCacheManager prefix-cache stats now stash at "
            "lookup and commit once on a successful allocate_slots "
            "(request-id matched, slot cleared). Failed scheduling retries "
            "(#43736) no longer inflate prefix_hit_rate; enable_caching="
            "False / no-lookup paths record nothing (more faithful than "
            "the upstream scheduler-side rewrite)."
        ),
        patch_name=patcher.patch_name,
    )


def is_applied() -> bool:
    """Return True iff our marker is present in the target file."""
    patcher = _make_kv_cache_manager_patcher()
    try:
        with open(patcher.target_file, encoding="utf-8") as f:
            return patcher.marker in f.read()
    except (OSError, UnicodeDecodeError):
        return False
