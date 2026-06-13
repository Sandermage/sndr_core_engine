# SPDX-License-Identifier: Apache-2.0
"""Wiring for PN387 Layer 2 — gateway-edge degenerate structured_outputs guard.

Injects a guard call at the TOP of
``OpenAIServingChat._create_chat_completion`` that runs
``sndr.engines.vllm.middleware.reject_degenerate_structured_outputs.reject_request``
and, when it returns an ``ErrorResponse`` (degenerate ``structured_outputs``
— the #45346 DoS triggers), EARLY-RETURNS that 400 so the request never
descends into the engine loop.

This is the Genesis extra paired with the source overlay
``patches/serving/pn387_reject_degenerate_structured_outputs.py`` (the
verbatim PR #45346 backport). Both layers are gated on the SAME opt-in
flag ``GENESIS_ENABLE_PN387_REJECT_DEGENERATE_STRUCTURED_OUTPUTS``
(default_on=False).

ANCHOR / COMPOSITION:
Anchors on the ``# Streaming response`` + ``tokenizer = self.renderer
.tokenizer`` pair at the top of ``_create_chat_completion`` — the SAME
pair P68/P69 and PN16 anchor on. Each of those patches re-emits the pair,
so all three compose by stacking above it; PN387's edge guard is purely
additive and order-independent w.r.t. them (it only READS
``request.structured_outputs`` and either short-circuits or falls
through). Unlike the mutate-in-place P68/P69 + PN16 hooks, this one can
RETURN an ``ErrorResponse`` to short-circuit, so the injected snippet is
``if (err := reject_request(self, request)) is not None: return err``.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
Original PR: vllm#45346.
"""

from __future__ import annotations

import logging
import os

from sndr.engines.vllm.detection.guards import resolve_vllm_file, vllm_install_root
from sndr.kernel import (
    TextPatch,
    TextPatcher,
    result_to_wiring_status,
)

log = logging.getLogger("genesis.wiring.pn387_reject_degenerate_structured_outputs")

GENESIS_PN387_EDGE_MARKER = (
    "Genesis PN387 gateway-edge degenerate structured_outputs guard "
    "(vendor of vllm#45346) v1"
)

# Anchor: the `# Streaming response` + tokenizer-fetch pair at the top of
# `_create_chat_completion`. Stable across upstream and survives P68/P69
# + PN16 application (each inserts ABOVE this pair and re-emits it).
PN387_EDGE_ANCHOR = (
    "        # Streaming response\n        tokenizer = self.renderer.tokenizer\n"
)

PN387_EDGE_REPLACEMENT = (
    "        # [Genesis PN387 gateway-edge guard, vendor of vllm#45346]\n"
    "        # Reject degenerate `structured_outputs` (json_object=False /\n"
    '        # json="") at the gateway edge with a clean 400, BEFORE the\n'
    "        # request reaches the per-request-isolation-free EngineCore step\n"
    "        # loop where it would raise and brick the engine (instance-wide\n"
    "        # DoS). No-op when the env flag is unset or the request is\n"
    "        # healthy. Source-overlay Layer 1 in sampling_params.py is the\n"
    "        # backstop if this returns None for any reason.\n"
    "        try:\n"
    "            from sndr.engines.vllm.middleware."
    "reject_degenerate_structured_outputs import (\n"
    "                reject_request as _genesis_pn387_reject_request,\n"
    "            )\n"
    "            _genesis_pn387_error = _genesis_pn387_reject_request(self, request)\n"
    "            if _genesis_pn387_error is not None:\n"
    "                return _genesis_pn387_error\n"
    "        except Exception:\n"
    "            # Guard failure is non-fatal — fall through to the standard\n"
    "            # path; Layer 1 (_validate_structured_outputs) backstops.\n"
    "            import logging as _genesis_pn387_logging\n"
    "            _genesis_pn387_logging.getLogger(\n"
    "                'genesis.middleware.reject_degenerate_structured_outputs'\n"
    "            ).debug('Genesis PN387 edge guard raised; ignored', exc_info=True)\n"
    "        # Streaming response\n"
    "        tokenizer = self.renderer.tokenizer\n"
)


def _make_patcher() -> TextPatcher | None:
    target = resolve_vllm_file("entrypoints/openai/chat_completion/serving.py")
    if target is None:
        return None
    return TextPatcher(
        patch_name=(
            "PN387 serving.py — gateway-edge degenerate structured_outputs "
            "guard (vendor of vllm#45346)"
        ),
        target_file=str(target),
        marker=GENESIS_PN387_EDGE_MARKER,
        sub_patches=[
            TextPatch(
                name="pn387_edge_guard_hook",
                anchor=PN387_EDGE_ANCHOR,
                replacement=PN387_EDGE_REPLACEMENT,
                required=True,
            ),
        ],
        upstream_drift_markers=[
            # Self-collision lint contract: only the defended banner — the
            # `reject_request` symbol is baked by our OWN replacement, so it
            # must NOT be a drift marker (PN369 self-collision class).
            "[Genesis PN387",
        ],
    )


def apply() -> tuple[str, str]:
    """Apply PN387 Layer 2 — gateway-edge guard hook injection. Never raises.

    Opt-in: gated through the dispatcher on
    ``GENESIS_ENABLE_PN387_REJECT_DEGENERATE_STRUCTURED_OUTPUTS``
    (default_on=False — same flag as Layer 1).
    """
    from sndr.dispatcher import log_decision, should_apply

    decision, reason = should_apply("PN387")
    log_decision("PN387", decision, reason)
    if not decision:
        return "skipped", reason

    if vllm_install_root() is None:
        return "skipped", "vllm install root not discoverable"

    patcher = _make_patcher()
    if patcher is None:
        return "skipped", "target file not resolvable"

    if not os.path.isfile(patcher.target_file):
        return "skipped", f"target disappeared: {patcher.target_file}"

    result, failure = patcher.apply()
    return result_to_wiring_status(
        result,
        failure,
        applied_message=(
            "PN387 Layer 2 applied: gateway-edge guard injected at the top of "
            "_create_chat_completion. A degenerate structured_outputs request "
            '(json_object=False / json="") now short-circuits with a clean '
            "400 BadRequestError BEFORE reaching the engine loop, instead of "
            "raising an EngineDeadError that bricks the instance (vllm#45346 "
            "DoS). Composes with P68/P69 + PN16 (same anchor pair, re-emitted). "
            "Default OFF — set "
            "GENESIS_ENABLE_PN387_REJECT_DEGENERATE_STRUCTURED_OUTPUTS=1."
        ),
        patch_name=patcher.patch_name,
    )


def is_applied() -> bool:
    """Return True iff our edge marker is present in the target file."""
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
