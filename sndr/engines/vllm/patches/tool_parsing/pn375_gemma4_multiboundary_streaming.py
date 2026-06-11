# SPDX-License-Identifier: Apache-2.0
"""PN375 — Gemma4 multi-boundary streaming tool-call deltas (vllm#44741).

Problem
-------
Upstream issue #41967: under MTP/speculative decoding (our Gemma-4
profiles run MTP K=3/K=4) a single streamed delta can cross multiple
tool-call boundaries — closing one call and starting (or completing)
the next inside the same delta. The pristine pin parser
(``vllm/tool_parsers/gemma4_tool_parser.py``, state-machine variant
with ``buffered_delta_text``) selects exactly ONE branch per delta, so
argument fragments on the far side of a boundary are dropped: silent
first-tool-call argument loss in multi-tool streaming turns.

Upstream fix
------------
PR #44741 (OPEN, studied via ``gh pr view/diff`` 2026-06-11) adds
``_extract_streaming_delta_segments``: split a multi-boundary delta on
the tool-call delimiter tokens, replay the delimiter-aligned segments
through the EXISTING ``_extract_streaming`` (no state-machine rewrite),
and merge the per-segment ``DeltaMessage``s into one response. Ordinary
zero/one-boundary deltas keep the pristine path. Four racing PRs exist
(#42006 / #42237 / #42300 / #43037); #44741 is the deliberately
narrow one, which is why it vendors cleanly as a runtime hook.

Genesis adaptations (iron rule #10 — adapt, don't blind-copy)
-------------------------------------------------------------
1. **Binding site**: upstream edits the ``extract_tool_calls_streaming``
   call site. We instead rebind ``Gemma4ToolParser._extract_streaming``
   itself and call the saved original per segment. This composes with
   the G4_14 wrapper on ``extract_tool_calls_streaming`` regardless of
   apply order, and keeps upstream's buffering + content short-circuit
   + try/except wrapper byte-untouched.
2. **CRITICAL roadmap caveat (chunk-5 Theme A)**: the G4_14 pad-token
   set (``<pad>``/``<eos>``/``<bos>``/turn boundaries/``<unk>``) is
   stripped from ``current_text`` AND ``delta_text`` BEFORE the PR's
   consistency check. The PR requires
   ``current_text.endswith(delta_text)``; any pad asymmetry introduced
   by a stripping wrapper (G4_14 class) or by pads landing inside the
   delta makes the check fail → permanent silent fallback to the
   single-pass path → the fix never engages exactly when MTP emits
   pads. Stripping both sides restores the invariant AND keeps pad
   text out of the replayed segments (no ``<pad>`` content leaks).
   Single source of truth: G4_14's ``_strip_control_tokens``.
3. **Variant self-skip**: the live Gemma-4 launchers bind-mount the
   G4_T1 v2 overlay (PR #42237 accumulated-text rescan), whose
   ``_extract_streaming(self, current_text)`` is structurally immune to
   multi-boundary deltas. PN375 probes the method signature and
   self-skips on anything but the pristine
   ``(previous_text, current_text, delta_text)`` shape — it is
   insurance for pristine-parser deployments (overlay rollback /
   un-mounted runs).
4. **Function dict-or-object tolerance**: the pristine parser emits
   ``function=DeltaFunctionCall(...).model_dump(exclude_none=True)``
   (a dict, coerced by pydantic in-engine). The merge logic reads
   name/arguments through a helper that accepts both shapes instead of
   assuming attribute access like the upstream PR does.

Retire trigger: #44741 (or any of the racing PRs) merged + in pin —
deep-diff first (iron rule #11). The companion test
``test_pristine_parser_loses_args_on_multiboundary_delta`` flips to
FAILED on a pin that contains an upstream fix.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
References:
  * https://github.com/vllm-project/vllm/pull/44741 (OPEN 2026-06-11)
  * https://github.com/vllm-project/vllm/issues/41967
"""
from __future__ import annotations

import inspect
import logging
import re

from sndr.engines.vllm.patches.model_compat.gemma4.g4_14_gemma4_tool_call_parser_pad_token import (  # noqa: E501
    _strip_control_tokens,
)
from sndr.env import Flags, is_enabled

log = logging.getLogger("genesis.tool_parsing.pn375_gemma4_multiboundary")

GENESIS_PN375_MARKER = (
    "Genesis PN375 gemma4 multi-boundary streaming delta segments v1 "
    "(vendors vllm#44741 segment replay + G4_14 pad-set strip before "
    "the consistency check)"
)

# Full env var name (for tests / operator docs); canonical bare flag in
# sndr.env.Flags.PN375_GEMMA4_MULTIBOUNDARY_STREAMING.
ENV_FLAG_FULL = "GENESIS_ENABLE_PN375_GEMMA4_MULTIBOUNDARY_STREAMING"

_INSTALLED_ATTR = "_genesis_pn375_installed"
_ORIGINAL_ATTR = "_genesis_pn375_original_extract_streaming"

_REQUIRED_PARAMS = {"previous_text", "current_text", "delta_text"}

_APPLIED = False
_PATCHED_CLS = None


def _fn_get(function, key):
    """Read a DeltaFunctionCall field whether it is a dict (the pristine
    parser emits ``model_dump`` dicts) or a protocol object."""
    if function is None:
        return None
    if isinstance(function, dict):
        return function.get(key)
    return getattr(function, key, None)


def _find_gemma4_parser_class():
    """Locate the Gemma4 tool parser class across vLLM pin layouts."""
    candidates = [
        ("vllm.tool_parsers.gemma4_tool_parser", "Gemma4ToolParser"),
        # Pre-restructure layouts (kept for older pins).
        ("vllm.entrypoints.openai.tool_parsers.gemma4_tool_parser", "Gemma4ToolParser"),
        ("vllm.entrypoints.openai.tool_parsers", "Gemma4ToolParser"),
    ]
    for mod_path, cls_name in candidates:
        try:
            mod = __import__(mod_path, fromlist=[cls_name])
        except ImportError:
            continue
        cls = getattr(mod, cls_name, None)
        if cls is not None:
            return cls
    return None


def install_on_class(cls) -> tuple[bool, str]:
    """Attach ``_extract_streaming_delta_segments`` and rebind
    ``_extract_streaming`` on ``cls``. Returns (bound, reason)."""
    if getattr(cls, _INSTALLED_ATTR, False):
        return True, "PN375 already installed on this class (idempotent)"

    original = getattr(cls, "_extract_streaming", None)
    if original is None or not callable(original):
        return False, (
            "PN375 self-skip: class has no _extract_streaming — unknown "
            "parser variant"
        )
    try:
        params = set(inspect.signature(original).parameters)
    except (TypeError, ValueError):
        return False, "PN375 self-skip: _extract_streaming signature unreadable"
    if not _REQUIRED_PARAMS <= params:
        return False, (
            "PN375 self-skip: _extract_streaming signature lacks "
            f"{sorted(_REQUIRED_PARAMS - params)} — accumulated-rescan "
            "overlay variant (G4_T1 v2 / PR #42237) is structurally "
            "immune to multi-boundary deltas"
        )

    # Protocol classes come from the target module's own globals so the
    # hook emits exactly the types the surrounding serving code expects.
    target_globals = getattr(original, "__globals__", {})
    delta_message_cls = target_globals.get("DeltaMessage")
    delta_tool_call_cls = target_globals.get("DeltaToolCall")
    delta_function_call_cls = target_globals.get("DeltaFunctionCall")
    if None in (delta_message_cls, delta_tool_call_cls, delta_function_call_cls):
        return False, (
            "PN375 self-skip: target module lacks Delta* protocol classes"
        )

    def _extract_streaming_delta_segments(
        self,
        previous_text: str = "",
        current_text: str = "",
        delta_text: str = "",
    ):
        """Replay delimiter-aligned delta segments through the original
        parser (vendored vllm#44741 design + Genesis pad-strip)."""

        def extract_once():
            return original(
                self,
                previous_text=previous_text,
                current_text=current_text,
                delta_text=delta_text,
            )

        # [Genesis PN375] Strip the G4_14 pad/control-token set from BOTH
        # texts BEFORE the consistency check below — a pad asymmetry
        # (wrapper-stripped current_text vs raw delta, or pads inside a
        # multi-boundary delta) would otherwise fail the endswith check
        # and silently degrade to the single-pass path forever.
        stripped_current = _strip_control_tokens(current_text)
        stripped_delta = _strip_control_tokens(delta_text)
        if not stripped_delta:
            return extract_once()

        pattern = (
            f"({re.escape(self.tool_call_start_token)}|"
            f"{re.escape(self.tool_call_end_token)})"
        )
        segments = [seg for seg in re.split(pattern, stripped_delta) if seg]
        if len(segments) <= 1:
            return extract_once()

        processed_current_text = stripped_current
        buffered = getattr(self, "buffered_delta_text", "")
        if buffered:
            if not processed_current_text.endswith(buffered):
                return extract_once()
            processed_current_text = processed_current_text[: -len(buffered)]
        if not processed_current_text.endswith(stripped_delta):
            return extract_once()

        segment_previous_text = processed_current_text[: -len(stripped_delta)]
        combined = delta_message_cls()
        tool_calls_by_index: dict = {}

        for segment in segments:
            segment_current_text = segment_previous_text + segment
            message = original(
                self,
                previous_text=segment_previous_text,
                current_text=segment_current_text,
                delta_text=segment,
            )
            segment_previous_text = segment_current_text
            if message is None:
                continue

            if message.content:
                combined.content = (combined.content or "") + message.content

            for tool_call in message.tool_calls or []:
                merged = tool_calls_by_index.get(tool_call.index)
                if merged is None:
                    merged = delta_tool_call_cls(
                        index=tool_call.index,
                        function=delta_function_call_cls(),
                    )
                    tool_calls_by_index[tool_call.index] = merged
                    combined.tool_calls.append(merged)

                if getattr(merged, "id", None) is None and (
                    getattr(tool_call, "id", None) is not None
                ):
                    merged.id = tool_call.id
                if getattr(merged, "type", None) is None and (
                    getattr(tool_call, "type", None) is not None
                ):
                    merged.type = tool_call.type

                function = getattr(tool_call, "function", None)
                if function is None:
                    continue
                merged_function = merged.function
                if merged_function is None:
                    merged_function = delta_function_call_cls()
                    merged.function = merged_function
                name = _fn_get(function, "name")
                if name is not None and merged_function.name is None:
                    merged_function.name = name
                arguments = _fn_get(function, "arguments")
                if arguments is not None:
                    merged_function.arguments = (
                        merged_function.arguments or ""
                    ) + arguments

        if not (combined.content or combined.tool_calls):
            return None
        return combined

    setattr(cls, _ORIGINAL_ATTR, original)
    cls._extract_streaming_delta_segments = _extract_streaming_delta_segments
    cls._extract_streaming = _extract_streaming_delta_segments
    setattr(cls, _INSTALLED_ATTR, True)
    log.info(
        "[PN375] installed: Gemma4 streaming parser replays multi-boundary "
        "deltas as delimiter-aligned segments (vllm#44741) with the G4_14 "
        "pad set stripped before the consistency check."
    )
    return True, (
        "PN375 installed: _extract_streaming_delta_segments bound over "
        "_extract_streaming (multi-boundary MTP deltas replayed; "
        "single-boundary path unchanged)"
    )


def apply() -> tuple[str, str]:
    """Install the PN375 runtime hook. Never raises."""
    global _APPLIED, _PATCHED_CLS

    if not is_enabled(Flags.PN375_GEMMA4_MULTIBOUNDARY_STREAMING):
        return "skipped", (
            f"PN375 disabled (set {ENV_FLAG_FULL}=1 to replay Gemma4 "
            "multi-boundary streaming deltas as segments — vllm#44741, "
            "issue #41967)"
        )

    if _APPLIED:
        return "applied", "PN375 already installed (idempotent)"

    cls = _find_gemma4_parser_class()
    if cls is None:
        return "skipped", (
            "no Gemma4ToolParser class found in this vLLM pin; PN375 is "
            "no-op (you may not be running --tool-call-parser gemma4)"
        )

    bound, reason = install_on_class(cls)
    if not bound:
        return "skipped", reason
    _APPLIED = True
    _PATCHED_CLS = cls
    return "applied", reason


def is_applied() -> bool:
    return _APPLIED


def revert() -> bool:
    global _APPLIED, _PATCHED_CLS
    if not _APPLIED or _PATCHED_CLS is None:
        return False
    original = getattr(_PATCHED_CLS, _ORIGINAL_ATTR, None)
    if original is not None:
        _PATCHED_CLS._extract_streaming = original
    if hasattr(_PATCHED_CLS, "_extract_streaming_delta_segments"):
        del _PATCHED_CLS._extract_streaming_delta_segments
    setattr(_PATCHED_CLS, _INSTALLED_ATTR, False)
    _APPLIED = False
    _PATCHED_CLS = None
    return True


__all__ = [
    "GENESIS_PN375_MARKER",
    "ENV_FLAG_FULL",
    "install_on_class",
    "apply",
    "is_applied",
    "revert",
]
