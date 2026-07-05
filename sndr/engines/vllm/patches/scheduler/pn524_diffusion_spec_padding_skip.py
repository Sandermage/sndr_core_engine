# SPDX-License-Identifier: Apache-2.0
"""PN524 — skip uniform spec-decode padding for diffusion (vllm#47464).

================================================================
UPSTREAM BUG (vllm#47464) — ENGINE DEATH ON THE DIFFUSION LANE
================================================================

Diffusion schedulers are initialized with ``num_spec_tokens =
canvas_length`` while ``num_sampled_tokens_per_step = 0``
(``Scheduler.__init__``, ``model_config.is_diffusion``). Diffusion
"spec tokens" are the fixed-size denoising CANVAS, not rejectable
drafts. The spec-decode padding block in ``Scheduler.schedule`` pads a
1-token decode request joining a running-decode batch to ``1 +
num_spec_tokens`` (to preserve full cudagraph); on a diffusion lane
that pads a resumed / prefix-cache-hit request to 1 + canvas_length ->
canvas overflow RuntimeError -> engine death.

REACHABLE on prod-diffusiongemma-tp2 (byte/config-verified 2026-07-05):
``max_num_seqs=2`` + KV pool capped at 8192 blocks = 131072 tokens =
``max_model_len`` + prefix caching default-on -> a preemption/resume or
a full-prompt prefix hit while another request decodes is organic under
aggregator dual-stream traffic. Boots-clean is NOT proof of absence —
the crash needs the 1-token-resume-while-decoding shape.

================================================================
THE FIX — upstream's one-line guard, verbatim
================================================================

PR #47464 adds ``and self.num_sampled_tokens_per_step > 0`` to the
padding condition. The guard is arch/model-neutral and INERT for AR MTP
lanes (AR schedulers set ``num_sampled_tokens_per_step >= 1``), so
upstream's existing gates (spec-tokens-configured, no dynamic-SD,
bare-decode, running-batch-without-prefill) are preserved exactly.
PN524 vendors that line verbatim; only the added comment is
Genesis-worded, so the PR's comment line ("Not for diffusion where
draft tokens can't be padded.") serves as the SELF_COLLISION-safe
drift marker.

================================================================
SAFETY MODEL
================================================================

  * One extra integer comparison in the schedule loop; bit-identical
    scheduling for every AR lane (35B/27B MTP, G4 lanes).
  * Opt-in (default_on=False), enabled on the DiffusionGemma ModelDef —
    the only lane where the buggy shape exists.
  * Same-file hygiene (grep-verified 2026-07-05): p58/p34/p74/p79c/
    pn388 anchors are disjoint from the padding block; the padding
    block contains no ``num_sampled_tokens_per_step`` text in pristine
    dev748 (p58's regions are elsewhere in the file).
  * Anchor byte-verified count==1 in pristine dev748 (2dfaae752, gh
    api, 2026-07-05); guard confirmed ABSENT there.

Author backport: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
Original PR: vllm#47464 (OPEN as of 2026-07-05).
"""

from __future__ import annotations

import logging
import os

from sndr.engines.vllm.detection.guards import resolve_vllm_file, vllm_install_root
from sndr.kernel import (
    TextPatch,
    TextPatcher,
)

log = logging.getLogger("genesis.wiring.pn524_diffusion_spec_padding_skip")

GENESIS_PN524_MARKER = (
    "Genesis PN524 diffusion spec-decode padding skip (vendor of vllm#47464) v1"
)

# ── Sub-patch (required): the one-line condition guard ────────────────
# Anchor: the full padding condition block (the 812-818 region on
# pristine dev748) — comment pair + the 4-line `if (...)`. Byte-verified
# count==1 in pristine dev748 (2dfaae752, gh api 2026-07-05).

PN524_PADDING_GUARD_OLD = (
    "                    # Pad new decode requests to uniform spec decoding size to\n"
    "                    # preserve full cudagraph for this step.\n"
    "                    if (\n"
    "                        (self.num_spec_tokens > 0 and self.dynamic_sd_lookup is None)\n"
    "                        and num_new_tokens == 1\n"
    "                        and (scheduled_running_reqs and not prefill_scheduled)\n"
    "                    ):\n"
)

PN524_PADDING_GUARD_NEW = (
    "                    # Pad new decode requests to uniform spec decoding size to\n"
    "                    # preserve full cudagraph for this step.\n"
    "                    # [Genesis PN524 vendor of vllm#47464] Never pad on a\n"
    "                    # diffusion lane (num_sampled_tokens_per_step == 0):\n"
    "                    # diffusion spec tokens are the fixed-size denoising\n"
    "                    # canvas, not rejectable drafts — padding a 1-token\n"
    "                    # resumed/prefix-hit request to 1 + canvas overflows the\n"
    "                    # canvas (RuntimeError -> engine death). Guard line is\n"
    "                    # upstream-verbatim; inert for AR lanes (>= 1).\n"
    "                    if (\n"
    "                        (self.num_spec_tokens > 0 and self.dynamic_sd_lookup is None)\n"
    "                        and self.num_sampled_tokens_per_step > 0\n"
    "                        and num_new_tokens == 1\n"
    "                        and (scheduled_running_reqs and not prefill_scheduled)\n"
    "                    ):\n"
)

# Drift marker — #47464's exact inserted comment line (from `gh pr diff
# 47464`, 2026-07-05). Byte-verified absent in pristine dev748 (count 0)
# and never emitted by our replacement (Genesis-worded comment instead)
# -> SELF_COLLISION-safe. NOTE: the guard LINE itself is upstream-verbatim
# in our replacement, so it must NOT be a drift marker.
_DRIFT_MARKERS = (
    "# Not for diffusion where draft tokens can't be padded.\n",
    # Defended convention entry (our own banner).
    "[Genesis PN524",
)


def _make_patcher() -> TextPatcher | None:
    target = resolve_vllm_file("v1/core/sched/scheduler.py")
    if target is None:
        return None
    return TextPatcher(
        patch_name=(
            "PN524 v1/core/sched/scheduler.py — skip uniform spec-decode "
            "padding for diffusion (vendor of vllm#47464)"
        ),
        target_file=str(target),
        marker=GENESIS_PN524_MARKER,
        sub_patches=[
            TextPatch(
                name="pn524_diffusion_spec_padding_guard",
                anchor=PN524_PADDING_GUARD_OLD,
                replacement=PN524_PADDING_GUARD_NEW,
                required=True,
            ),
        ],
        upstream_drift_markers=list(_DRIFT_MARKERS),
    )


def apply() -> tuple[str, str]:  # noqa: PLR0911 - dispatcher early-return cascade: distinct skip/self-retire reasons per gate
    """Apply PN524 — diffusion spec-decode padding skip. Never raises.

    Gated through the dispatcher on
    ``GENESIS_ENABLE_PN524_DIFFUSION_SPEC_PADDING_SKIP`` (opt-in,
    enabled on the DiffusionGemma ModelDef — the only lane where
    ``num_sampled_tokens_per_step == 0`` makes the padding lethal).
    """
    from sndr.dispatcher import log_decision, should_apply

    decision, reason = should_apply("PN524")
    log_decision("PN524", decision, reason)
    if not decision:
        return "skipped", reason

    if vllm_install_root() is None:
        return "skipped", "vllm install root not discoverable"

    patcher = _make_patcher()
    if patcher is None:
        return "skipped", "vllm/v1/core/sched/scheduler.py not found"

    if not os.path.isfile(patcher.target_file):
        return "skipped", f"target disappeared: {patcher.target_file}"
    with open(patcher.target_file, encoding="utf-8") as f:
        content = f.read()
    if patcher.marker in content:
        return "skipped", f"{patcher.patch_name}: already applied (marker present)"
    for m in patcher.upstream_drift_markers:
        if m.startswith("[Genesis"):
            continue
        if m in content:
            return (
                "skipped",
                f"upstream drift marker {m!r} present — upstream PR "
                "#47464 (or equivalent fix) appears merged (upstream_merged)",
            )

    try:
        result, failure = patcher.apply()
    except Exception as e:  # noqa: BLE001 - dispatcher contract: never raise
        return "failed", f"PN524 apply raised {e!r}"

    from sndr.kernel import TextPatchResult

    if result == TextPatchResult.FAILED:
        return "failed", f"PN524: {failure.reason if failure else 'unknown'}"
    if result == TextPatchResult.SKIPPED:
        return "skipped", f"PN524: {failure.reason if failure else 'unknown'}"
    if result == TextPatchResult.IDEMPOTENT:
        return "applied", "PN524 already applied (idempotent)"

    return (
        "applied",
        "PN524 applied: Scheduler.schedule spec-decode padding now skips "
        "diffusion lanes (num_sampled_tokens_per_step == 0), so a 1-token "
        "resumed/prefix-hit request is never padded to 1 + canvas_length "
        "(canvas overflow RuntimeError -> engine death, vllm#47464). "
        "Upstream guard line verbatim; bit-identical for AR lanes.",
    )


def is_applied() -> bool:
    """Return True iff our marker is present in the target file."""
    if vllm_install_root() is None:
        return False
    patcher = _make_patcher()
    if patcher is None:
        return False
    try:
        with open(patcher.target_file, encoding="utf-8") as f:
            return patcher.marker in f.read()
    except OSError:
        return False
