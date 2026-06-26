# SPDX-License-Identifier: Apache-2.0
"""PN361 — vendor of OPEN PR vllm#44869 (masterFoad) fail-closed on missing draft probs.

Defensive observability fix: convert silent quality regression to visible RuntimeError
=====================================================================================

**Today's behaviour** in ``GPUModelRunner._get_spec_decode_draft_probs``:

  * For each request with ``num_draft > 0``, look up the cached draft
    probability row by ``req_id``.
  * If the row is MISSING (cache miss for a request that nevertheless
    has drafted tokens), emit a ``logger.warning`` and ``return None``.
  * Caller treats ``None`` as "no probabilistic rejection available"
    and silently falls back to the GREEDY rejection sampler.

The problem
-----------

Probabilistic rejection (the ``min(1, target_p / draft_p)`` rule per
the Leviathan-Kalman-Mehta 2023 paper) gives strictly higher
acceptance than greedy on properly-trained draft distributions.
Our PROD launches with::

    spec_decode:
      rejection_sample_method: standard
      draft_sample_method: probabilistic

This signals "the operator wants probabilistic rejection". A silent
fallback to greedy means the operator's intent is silently downgraded,
and the silent log warning is easily lost in the 1000+ lines of boot
trace — we may have been running in degraded mode for hours without
noticing.

The fix (PR #44869)
-------------------

Replace the silent ``logger.warning + return None`` with a
``raise RuntimeError`` carrying a precise message::

    Missing cached draft probabilities for request {req_id}; cannot
    run exact probabilistic speculative rejection sampling without
    the draft distribution for every drafted request.

Caller propagates → engine logs the exception → operator notices →
operator can flip ``draft_sample_method`` to ``greedy`` consciously
OR investigate why the draft-prob cache is missing rows.

**Why we vendor an OPEN PR**:

  * Pure observability defensive — converts silent quality regression
    to visible error.
  * The replacement is 4 lines (logger.warning → RuntimeError).
  * We measured earlier in PROD that probabilistic was advertised but
    silent fall-backs may have been happening — exact symptom is
    invisible without this fix.

**Note** — the fix is a "fail-closed" pattern. It will surface
exceptions on a code path that today silently degrades. If the
exception fires in PROD, the operator either:
  (a) sets ``draft_sample_method: greedy`` to acknowledge the silent
     behaviour was the design, OR
  (b) fixes the upstream missing-row bug.

Either response is better than silent degradation.

Implementation strategy
=======================

Single text-patch on
``vllm/v1/worker/gpu_model_runner.py``. Anchor on the 5-line
``if row_idx is None: logger.warning(... return None`` block which
appears exactly once in the file (only inside
``_get_spec_decode_draft_probs``).

Composition + safety
====================

* No anchor overlap with PN341 (same file but PN341 anchors at
  ``_update_states_after_model_execute`` / ``_compute_prev_positions``
  / ``_prepare_inputs`` — different methods, no overlap).
* No interaction with PN340 (different file).
* Risk: LOW for our config — the RuntimeError fires only if the
  upstream draft-prob cache is silently missing rows, which is the
  exact failure mode we WANT to surface.
* If concerned, opt-out via ``GENESIS_DISABLE_PN361=1`` to restore
  the silent-fallback behaviour.

Author: Sander (Sandermage / Aleksandr Barzov), Odessa, Ukraine.
Vendor target: vllm-project/vllm#44869 (OPEN as of 2026-06-09).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from sndr.engines.vllm.detection.guards import resolve_vllm_file
from sndr.kernel import TextPatch, TextPatcher, TextPatchResult

log = logging.getLogger("genesis.wiring.pn361_spec_decode_fail_closed_missing_probs")

GENESIS_PN361_MARKER = (
    "Genesis PN361 vendor of vllm#44869 (spec-decode fail-closed missing draft probs) v1"
)

_TARGET_REL = "v1/worker/gpu_model_runner.py"


# Anchor: 5 lines of the silent-fallback block in
# `_get_spec_decode_draft_probs`. Unique in the file.
PN361_OLD = (
    "            row_idx = row_by_req_id.get(req_id)\n"
    "            if row_idx is None:\n"
    "                logger.warning(\n"
    "                    \"Missing cached draft probabilities for request %s; \"\n"
    "                    \"falling back to legacy speculative rejection behavior.\",\n"
    "                    req_id,\n"
    "                )\n"
    "                return None\n"
    "            draft_probs_rows.append(self._draft_probs[row_idx, :num_draft])\n"
)
PN361_NEW = (
    "            row_idx = row_by_req_id.get(req_id)\n"
    "            if row_idx is None:\n"
    "                # [Genesis PN361 vendor of vllm#44869] FAIL CLOSED.\n"
    "                # Today's silent fallback to greedy rejection downgrades\n"
    "                # the operator's `draft_sample_method: probabilistic`\n"
    "                # signal without surfacing the issue. Raise instead so\n"
    "                # the exception propagates to engine logs and the\n"
    "                # missing-row bug is visible.\n"
    "                raise RuntimeError(\n"
    "                    f\"Missing cached draft probabilities for request {req_id}; \"\n"
    "                    \"cannot run exact probabilistic speculative rejection \"\n"
    "                    \"sampling without the draft distribution for every drafted \"\n"
    "                    \"request.\"\n"
    "                )\n"
    "            draft_probs_rows.append(self._draft_probs[row_idx, :num_draft])\n"
)


def _env_disabled() -> bool:
    return os.environ.get("GENESIS_DISABLE_PN361", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def apply() -> tuple[str, str]:
    if _env_disabled():
        return "skipped", "PN361 disabled via GENESIS_DISABLE_PN361=1"

    target = resolve_vllm_file(_TARGET_REL)
    if target is None:
        return "skipped", f"PN361: target file {_TARGET_REL} not found"

    patcher = TextPatcher(
        patch_name="PN361 gpu_model_runner.py — fail-closed missing draft probs (vllm#44869)",
        target_file=str(target),
        marker=GENESIS_PN361_MARKER,
        sub_patches=[
            TextPatch(
                name="pn361_fail_closed_missing_probs",
                anchor=PN361_OLD,
                replacement=PN361_NEW,
                required=True,
            ),
        ],
        upstream_drift_markers=[
            "[Genesis PN361",
        ],
    )

    try:
        result, failure = patcher.apply()
    except Exception as e:  # noqa: BLE001
        return "failed", f"PN361 apply raised {e!r}"

    if result == TextPatchResult.FAILED:
        return "failed", f"PN361 FAILED — {failure.reason if failure else 'unknown'}"
    if result == TextPatchResult.SKIPPED:
        return "skipped", f"PN361 skipped — {failure.reason if failure else 'unknown'}"
    if result == TextPatchResult.IDEMPOTENT:
        return "applied", "PN361 idempotent (already applied)"

    return "applied", (
        "PN361 applied: _get_spec_decode_draft_probs now FAILS CLOSED on "
        "missing draft-prob rows. Converts silent quality regression "
        "(silent fallback to greedy) into a visible RuntimeError. Vendor "
        "of OPEN PR vllm#44869. Composes with PN340 + PN341."
    )


def is_applied() -> bool:
    target = resolve_vllm_file(_TARGET_REL)
    if target is None:
        return False
    try:
        return GENESIS_PN361_MARKER in Path(str(target)).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
