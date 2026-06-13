# SPDX-License-Identifier: Apache-2.0
"""Wiring for P107 — vllm#41467 backport: MTP truncation detector.

With MTP K>=1 + tools + reasoning parser there is a rare (~0.25% per
author measurement on Qwen3.6-27B-FP8) condition: the model emits EOS
at the reasoning->tool_call boundary. finish_reason=stop + tools
configured + neither tool_calls nor content delivered → silent
client-side error.

Fix: defensive guard in `chat_completion_stream_generator` that
detects this combo and raises GenerationError (retryable) instead of
emitting a silent stop. The client receives an SSE error event and
retries.

Directly affects our PROD: 27B Lorbus + MTP K=3 + tools — exactly
the config the author reported. P107 is a safety net on top of an
already-defended path (P59/P60/P61/P62/P64/P68/P69 family).

Default OFF — defensive backport. Risk: low; adds one extra branch
in the hot path, no effect on the happy path.

Author: Sandermage backport (ToastyTheBot, vllm#41467).
"""
from __future__ import annotations

import logging
import os

from sndr.engines.vllm.detection.guards import resolve_vllm_file, vllm_install_root
from sndr.kernel import (
    TextPatch,
    TextPatcher,
    TextPatchResult,
)

log = logging.getLogger("genesis.wiring.p107_mtp_truncation_detector")

GENESIS_P107_MARKER = "Genesis P107 MTP truncation detector (vllm#41467)"


def _is_enabled() -> bool:
    return os.environ.get(
        "GENESIS_ENABLE_P107_MTP_TRUNCATION_DETECTOR", ""
    ).strip().lower() in ("1", "true", "yes", "on")


# Anchor on stable finish_reason_ if/else block.
# v2 (2026-06-08): upstream refactored the leading conditional and DROPPED
# the ``auto_tools_called`` OR-clause from the if-head — live file at
# vllm/entrypoints/openai/chat_completion/serving.py:820-826 now reads
# ``if (tools_streamed[i] and ...) or (self.use_harmony and ...):``. The
# v3 (2026-06-11): the v2 comment claiming ``auto_tools_called`` still
# exists in the streaming generator was WRONG — on this pin the variable
# lives only in the NON-streaming full generator (pristine serving.py
# 1069+, streaming generator is 399-1000). The baked v2 text raised a
# live NameError at stream end on every tool-bearing streamed request
# (caught by fleet validation 2026-06-11, predicted by the preflight
# triage). The clause is dropped; ``not tools_streamed[i]`` +
# ``not delta_message.tool_calls`` retain the detector's protection. P107's misleading ``# likely
# upstream merged`` skip-message was wrong (PR #41467 still OPEN); the
# anchor drift was code-shape refactor, not behavioral upstreaming.
# v4 (2026-06-13, dev491 pin bump): this dev259 block is now ONE of two
# mutually-exclusive anchor variants (required=False). It stays byte-stable
# (the validated PROD anchor + the PN288 chain depend on it); the dev491
# variant is defined below as ANCHOR_DEV491_OLD/NEW. See _make_patcher.
ANCHOR_OLD = (
    "                        if (tools_streamed[i] and not tool_choice_function_name) or (\n"
    "                            self.use_harmony and harmony_tools_streamed[i]\n"
    "                        ):\n"
    "                            finish_reason_ = \"tool_calls\"\n"
    "                        else:\n"
    "                            finish_reason_ = (\n"
    "                                output.finish_reason if output.finish_reason else \"stop\"\n"
    "                            )\n"
    "                        choice_data = ChatCompletionResponseStreamChoice("
)

ANCHOR_NEW = (
    "                        if (tools_streamed[i] and not tool_choice_function_name) or (\n"
    "                            self.use_harmony and harmony_tools_streamed[i]\n"
    "                        ):\n"
    "                            finish_reason_ = \"tool_calls\"\n"
    "                        else:\n"
    "                            finish_reason_ = (\n"
    "                                output.finish_reason if output.finish_reason else \"stop\"\n"
    "                            )\n"
    "\n"
    "                        # [Genesis P107 vllm#41467] MTP truncation detector.\n"
    "                        # ~0.25% rate on Qwen3.6 27B-FP8 + MTP K=3 (per upstream\n"
    "                        # author): EOS at reasoning→tool_call boundary leaves\n"
    "                        # finish_reason=stop with no content/tool_calls. Raise\n"
    "                        # retryable error so client retries instead of seeing\n"
    "                        # silent empty response. Defensive: 6 AND-conditions,\n"
    "                        # no impact on happy path.\n"
    "                        if (\n"
    "                            finish_reason_ == \"stop\"\n"
    "                            and request.tools\n"
    "                            and not tools_streamed[i]\n"
    "                            and reasoning_parser is not None\n"
    "                            and delta_message is not None\n"
    "                            and not delta_message.content\n"
    "                            and not delta_message.tool_calls\n"
    "                        ):\n"
    "                            from vllm.entrypoints.openai.chat_completion.protocol import GenerationError as _P107_GenError\n"
    "                            logger.warning(\n"
    "                                \"[Genesis P107] MTP truncation detected for request %s: \"\n"
    "                                \"finished with 'stop' but tools configured and only \"\n"
    "                                \"reasoning produced.\",\n"
    "                                request_id,\n"
    "                            )\n"
    "                            raise _P107_GenError(\n"
    "                                \"MTP speculative decoding truncated tool call \"\n"
    "                                \"generation. Please retry.\"\n"
    "                            )\n"
    "                        choice_data = ChatCompletionResponseStreamChoice("
)


# ── dev491 anchor variant (pin bump 0.22.1rc1.dev491+g1033ffac2) ────────
# vllm#45171 (merged 2026-06-11) deleted ~74 lines from serving.py and
# moved harmony streaming out to parser/harmony.py — so the dev259 streaming
# finish_reason block CHANGED SHAPE. Verified byte-exact 2026-06-13 against
# BOTH pristine trees:
#   * dev259 (CURRENT PROD, /private/tmp/candidate_pin_current): the if-head
#     is the two-clause ``(tools_streamed[i] and ...) or (self.use_harmony
#     and harmony_tools_streamed[i])`` form — matched by ANCHOR_OLD above
#     (count==1 in dev259 tree, count==0 in dev491 tree).
#   * dev491 (CANDIDATE, /tmp/candidate_pin_new): #45171 DROPPED the harmony
#     OR-clause from the if-head — it is now the single-line
#     ``if tools_streamed[i] and not tool_choice_function_name:`` form
#     (ANCHOR_DEV491_OLD; count==1 in dev491 tree, count==0 in dev259 tree).
# The two anchors are mutually exclusive: exactly one matches per pin under
# the PN351/PN32/P18B required-at-least-one convention (both required=False;
# apply() asserts at least one fired).
#
# Two scope deltas in the dev491 stream generator drive the replacement text:
#   1. ``reasoning_parser`` is NOT a local here. dev491 uses a single unified
#      ``parser`` (serving.py:575 ``parser.parse_delta(...)``) that subsumes
#      reasoning + tool parsing; the old per-name ``reasoning_parser`` local
#      no longer exists in this generator — referencing it would raise
#      NameError at stream end (the exact dev259-v2 class of bug). The
#      equivalent guard is ``parser is not None`` (a parser is configured and
#      thus reasoning/tool extraction is active but produced nothing).
#   2. ``GenerationError`` is already imported at MODULE level on dev491
#      (serving.py:46 ``from vllm.entrypoints.openai.engine.serving import
#      GenerationError``) AND the whole streaming loop is wrapped in
#      ``try ... except GenerationError`` (serving.py:780) which converts it
#      to a retryable SSE error via
#      ``_convert_generation_error_to_streaming_response``. So the dev491
#      variant raises the module-level ``GenerationError`` directly — no
#      fragile local import (the dev259 variant's local import targets
#      ``chat_completion.protocol`` which does NOT export GenerationError;
#      that latent ImportError never fires only because the detector is
#      default-OFF — left untouched here to keep the validated dev259 anchor
#      byte-stable).
#
# PN288 chain: PN288 (CHAINED_ANCHOR on P107 per preflight) re-applies the
# bare finish_reason block shifted +4 inside its except-fallback. P107's
# dev491 ANCHOR_DEV491_NEW preserves that bare block verbatim and the emitted
# warning/raise text is IDENTICAL to the dev259 variant — so PN288's
# (separately re-anchored) dev491 streaming anchor still resolves exactly
# once against P107's output.
ANCHOR_DEV491_OLD = (
    "                        if tools_streamed[i] and not tool_choice_function_name:\n"
    "                            finish_reason_ = \"tool_calls\"\n"
    "                        else:\n"
    "                            finish_reason_ = (\n"
    "                                output.finish_reason if output.finish_reason else \"stop\"\n"
    "                            )\n"
    "                        choice_data = ChatCompletionResponseStreamChoice("
)

ANCHOR_DEV491_NEW = (
    "                        if tools_streamed[i] and not tool_choice_function_name:\n"
    "                            finish_reason_ = \"tool_calls\"\n"
    "                        else:\n"
    "                            finish_reason_ = (\n"
    "                                output.finish_reason if output.finish_reason else \"stop\"\n"
    "                            )\n"
    "\n"
    "                        # [Genesis P107 vllm#41467] MTP truncation detector.\n"
    "                        # ~0.25% rate on Qwen3.6 27B-FP8 + MTP K=3 (per upstream\n"
    "                        # author): EOS at reasoning→tool_call boundary leaves\n"
    "                        # finish_reason=stop with no content/tool_calls. Raise\n"
    "                        # retryable error so client retries instead of seeing\n"
    "                        # silent empty response. Defensive: 6 AND-conditions,\n"
    "                        # no impact on happy path. (dev491 variant: vllm#45171\n"
    "                        # dropped the harmony OR-clause from the if-head and\n"
    "                        # unified the parser — ``parser is not None`` replaces\n"
    "                        # the removed ``reasoning_parser`` local, and the\n"
    "                        # module-level GenerationError is raised directly into\n"
    "                        # the generator's enclosing ``except GenerationError``.)\n"
    "                        if (\n"
    "                            finish_reason_ == \"stop\"\n"
    "                            and request.tools\n"
    "                            and not tools_streamed[i]\n"
    "                            and parser is not None\n"
    "                            and delta_message is not None\n"
    "                            and not delta_message.content\n"
    "                            and not delta_message.tool_calls\n"
    "                        ):\n"
    "                            logger.warning(\n"
    "                                \"[Genesis P107] MTP truncation detected for request %s: \"\n"
    "                                \"finished with 'stop' but tools configured and only \"\n"
    "                                \"reasoning produced.\",\n"
    "                                request_id,\n"
    "                            )\n"
    "                            raise GenerationError(\n"
    "                                \"MTP speculative decoding truncated tool call \"\n"
    "                                \"generation. Please retry.\"\n"
    "                            )\n"
    "                        choice_data = ChatCompletionResponseStreamChoice("
)


# Names of the two mutually-exclusive pin-specific anchor variants. apply()
# asserts AT LEAST ONE fired — a both-miss outcome means a NEW pin shape
# drifted past both anchors and the detector silently vanished (must FAIL
# loudly, not report a misleading "applied").
_VARIANT_NAMES = (
    "p107_mtp_truncation",          # dev259 (current PROD)
    "p107_mtp_truncation_dev491",   # dev491 (candidate pin)
)


def _make_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(
        "entrypoints/openai/chat_completion/serving.py"
    )
    if target is None:
        return None
    return TextPatcher(
        patch_name="P107 MTP truncation detector (vllm#41467)",
        target_file=str(target),
        marker=GENESIS_P107_MARKER,
        # Dual-anchor (PN351/PN32/P18B convention): both required=False so
        # the non-matching pin's variant soft-skips; apply() enforces that
        # exactly one of the two fired. dev259 variant kept byte-stable so
        # the validated PROD anchor + the PN288 chain test are untouched.
        sub_patches=[
            TextPatch(
                name="p107_mtp_truncation",
                anchor=ANCHOR_OLD,
                replacement=ANCHOR_NEW,
                required=False,
            ),
            TextPatch(
                name="p107_mtp_truncation_dev491",
                anchor=ANCHOR_DEV491_OLD,
                replacement=ANCHOR_DEV491_NEW,
                required=False,
            ),
        ],
        upstream_drift_markers=[
            # Self-collision lint (triage plan §6 2026-06-11): former
            # entries "MTP truncation detected" / "MTP speculative decoding
            # truncated" are message strings baked verbatim by our own
            # vllm#41467 backport replacement — they cannot distinguish a
            # real upstream merge from our residue (false "upstream_merged"
            # skip, PN369 class). Residue coverage moves to the sanctioned
            # banner prefix; real-merge detection via required-anchor
            # mismatch (Layer 5) + preflight deep-diff.
            "[Genesis P107",
        ],
    )


def apply() -> tuple[str, str]:
    from sndr.dispatcher import log_decision, should_apply

    decision, reason = should_apply("P107")
    log_decision("P107", decision, reason)
    if not decision:
        return "skipped", reason
    if vllm_install_root() is None:
        return "skipped", "vllm install root not discoverable"
    patcher = _make_patcher()
    if patcher is None:
        return "skipped", "serving.py not found"
    result, failure = patcher.apply()
    if result == TextPatchResult.APPLIED:
        # Dual-anchor at-least-one guard: with both variants required=False,
        # a future pin that drifts past BOTH the dev259 and dev491 anchors
        # would let TextPatcher return a vacuous APPLIED with zero splices.
        # That silently drops the detector — FAIL loudly instead.
        applied = set(patcher.applied_sub_patches)
        fired = applied.intersection(_VARIANT_NAMES)
        if not fired:
            return "failed", (
                "P107 FAILED — neither the dev259 nor the dev491 streaming "
                "finish_reason anchor matched. The MTP truncation detector is "
                "the load-bearing splice; a no-splice apply silently removes "
                "it. Re-derive the chat_completion_stream_generator "
                "finish_reason anchor for the new pin shape."
            )
        variant = (
            "dev491 anchor variant"
            if "p107_mtp_truncation_dev491" in fired
            else "dev259 anchor variant"
        )
        return "applied", (
            f"P107 applied ({variant}): MTP truncation now raises retryable "
            f"error"
        )
    if result == TextPatchResult.IDEMPOTENT:
        return "applied", "already applied (idempotent)"
    if result == TextPatchResult.SKIPPED:
        msg = failure.reason if failure else "anchor not found"
        return "skipped", f"{msg} — likely upstream merged"
    return "failed", failure.reason if failure else "unknown failure"
