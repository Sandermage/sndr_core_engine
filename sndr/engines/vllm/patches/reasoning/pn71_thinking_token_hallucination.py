# SPDX-License-Identifier: Apache-2.0
"""PN71 — runtime `</thinking>` → `</think>` hallucination normalizer.

The Qwen 3.6 27B and 35B-A3B models occasionally hallucinate the wrong
closing tag — `</thinking>` (the full word) instead of the canonical
`</think>` token they were trained on. froggeric's enhanced chat
template handles this in the prompt-side jinja for PAST turns, but it
does NOT help the LIVE generated output of the CURRENT turn — by the
time the chat template sees content, the model has already finished.

When the model emits `</thinking>` instead of `</think>` in live
generation:
  1. `Qwen3ReasoningParser.extract_reasoning()` looks for `</think>`
     literally, doesn't find it, and routes ALL output to reasoning
     (with `content=None`).
  2. Streaming: `delta.reasoning` keeps growing forever, `delta.content`
     never opens, client sees an empty response with reasoning-only.

PN71 normalizes the hallucinated tag in both surfaces:

  - `extract_reasoning(model_output, ...)`: replace `</thinking>` →
    `</think>` once at function entry. The partition logic then works
    on a normalized string.
  - `extract_reasoning_streaming(..., current_text=...)`: same normalize
    on `current_text` so the streaming-state machine sees `</think>`.

This is a pure runtime safety net — no template dependency. Even with
the default model-bundled template the parser stays robust.

Env gate: `GENESIS_ENABLE_PN71_THINKING_TAG_NORMALIZE=1` (default OFF).
Strictly additive — only fires when the model hallucinates the wrong
tag, which is a rare edge per the upstream Qwen 3.6 bug tracker.
"""
from __future__ import annotations

import logging
import os

from sndr.engines.vllm.detection.guards import resolve_vllm_file, vllm_install_root
from sndr.kernel import TextPatch, TextPatcher

log = logging.getLogger("genesis.wiring.pn71_thinking_token_hallucination")

GENESIS_MARKER = "Genesis PN71 </thinking> → </think> runtime normalizer"


def _enabled() -> bool:
    return os.environ.get(
        "GENESIS_ENABLE_PN71_THINKING_TAG_NORMALIZE", "0",
    ).strip().lower() in ("1", "true", "yes", "on")


# Anchor: Qwen3Parser.extract_reasoning method (state-machine parser at
# vllm/parser/qwen3.py, post upstream #45588 which deleted the old
# reasoning/qwen3_reasoning_parser.py). The new design inserts a
# `_preprocess_feed` override BEFORE this method — the universal text-feed
# chokepoint that covers both non-streaming (whole output in one feed) and
# streaming (per-delta) paths — and re-emits extract_reasoning verbatim.
PN71_OLD_NON_STREAMING = (
    "    def extract_reasoning(\n"
    "        self,\n"
    "        model_output: str,\n"
    "        request: ChatCompletionRequest | ResponsesRequest,\n"
    "    ) -> tuple[str | None, str | None]:\n"
    "        if not self.thinking_enabled:\n"
    "            return None, model_output\n"
    "        return super().extract_reasoning(model_output, request)\n"
)
PN71_NEW_NON_STREAMING = (
    "    # [Genesis PN71] Normalize hallucinated </thinking> -> </think> at\n"
    "    # feed entry. Qwen 3.6 occasionally emits the full word instead of\n"
    "    # the canonical </think> token; </thinking> tokenizes to ordinary\n"
    "    # sub-word pieces (no </think> special-token id) so the state machine\n"
    "    # never sees the THINK_END terminal, leaving the parser stuck in\n"
    "    # REASONING and routing all output to reasoning with empty content.\n"
    "    # Overriding _preprocess_feed covers every path (non-streaming\n"
    "    # extract_reasoning/parse feed the whole output in one call; streaming\n"
    "    # parse_delta/extract_*_streaming feed each delta).\n"
    "    def _preprocess_feed(self, delta_text, delta_token_ids):\n"
    "        if delta_text and \"</thinking>\" in delta_text:\n"
    "            delta_text = delta_text.replace(\"</thinking>\", \"</think>\")\n"
    "        return super()._preprocess_feed(delta_text, delta_token_ids)\n"
    "\n"
    "    def extract_reasoning(\n"
    "        self,\n"
    "        model_output: str,\n"
    "        request: ChatCompletionRequest | ResponsesRequest,\n"
    "    ) -> tuple[str | None, str | None]:\n"
    "        if not self.thinking_enabled:\n"
    "            return None, model_output\n"
    "        return super().extract_reasoning(model_output, request)\n"
)


def _make_patcher() -> TextPatcher | None:
    if not _enabled():
        return None
    target = resolve_vllm_file("parser/qwen3.py")
    if target is None:
        return None
    return TextPatcher(
        patch_name="PN71 </thinking> tag hallucination normalizer",
        target_file=str(target),
        marker=GENESIS_MARKER,
        sub_patches=[
            TextPatch(
                name="pn71_extract_reasoning_normalize",
                anchor=PN71_OLD_NON_STREAMING,
                replacement=PN71_NEW_NON_STREAMING,
                required=True,
            ),
        ],
        upstream_drift_markers=[
            "Genesis PN71",
            "Normalize hallucinated </thinking>",
        ],
    )


def apply() -> tuple[str, str]:
    """Apply PN71 text-patch. Returns (wiring_status, message)."""
    if not _enabled():
        return "skipped", "PN71 disabled (set GENESIS_ENABLE_PN71_THINKING_TAG_NORMALIZE=1)"
    if vllm_install_root() is None:
        return "skipped", "vllm install root not discoverable"
    patcher = _make_patcher()
    if patcher is None:
        return "skipped", "target file parser/qwen3.py not resolvable"
    if not os.path.isfile(patcher.target_file):
        return "skipped", f"target disappeared: {patcher.target_file}"
    with open(patcher.target_file) as fh:
        content = fh.read()
    if patcher.marker in content:
        return "applied", "idempotent (marker present)"
    for m in patcher.upstream_drift_markers:
        if m in content:
            return "skipped", f"drift marker {m!r} already in file"
    result, failure = patcher.apply()
    from sndr.kernel import result_to_wiring_status
    return result_to_wiring_status(
        result, failure,
        applied_message="PN71 </thinking>→</think> hallucination normalizer active",
        patch_name=patcher.patch_name,
    )
