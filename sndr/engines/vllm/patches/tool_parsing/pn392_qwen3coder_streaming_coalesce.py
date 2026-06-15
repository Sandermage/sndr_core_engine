# SPDX-License-Identifier: Apache-2.0
"""PN392 — qwen3_coder streaming tool-call within-call coalescing.

RETIRED (dev491): superseded by the engine-native Qwen3CoderToolParser after
vllm#45171 remapped ``qwen3_xml`` -> ``Qwen3CoderToolParser`` and made it handle
streaming directly. registry lifecycle=retired; this module is kept for audit
provenance. See the root-cause note below.

Root cause (dev491 pin bump 0.22.1rc1.dev491+g1033ffac2)
--------------------------------------------------------
The upstream vllm#45171-era refactor (232-commit window dev259→dev491)
DELETED ``vllm/tool_parsers/qwen3xml_tool_parser.py`` and remapped the
``qwen3_xml`` parser registry key from the dedicated
``Qwen3XMLToolParser`` to ``Qwen3CoderToolParser``
(``vllm/tool_parsers/__init__.py``: ``"qwen3_xml": ("qwen3coder_tool_parser",
"Qwen3CoderToolParser")``). The launcher's ``--tool-call-parser
qwen3_xml`` therefore loads a DIFFERENT parser on dev491 than on dev259.

``Qwen3CoderToolParser.extract_tool_calls_streaming`` is a
single-emission incremental state machine: per invocation it emits AT
MOST ONE structural delta (the function header, then ``{``, then a batch
of params, then ``}``) and ``return``s to advance — it assumes
token-by-token feeding where it is called many times with a growing
``current_text``.

But the dev491 unified streaming path delegates to
``vllm/parser/abstract_parser.py parse_delta``. At the reasoning→tool
boundary (when the qwen3 reasoning parser sets ``reasoning_ended`` on
``</think>``) ``parse_delta`` does::

    if self._in_tool_call_phase(state):
        if not state.tool_call_text_started:
            state.tool_call_text_started = True
            state.previous_text = ""
            delta_text = current_text          # <-- the WHOLE tool XML

i.e. it feeds the ENTIRE accumulated ``<tool_call>...</tool_call>`` text
as a SINGLE ``extract_tool_calls_streaming`` call. On that one call the
coder parser detects the ``<tool_call>`` start token, flips
``is_tool_call_started = True``, and ``return``s — emitting ZERO
``delta.tool_calls``. The whole tool call is silently dropped: the
client receives ``finish_reason=stop`` with no ``delta.tool_calls`` (and,
depending on token chunking, the raw XML can leak onto the ``content``
channel). NON-streaming is unaffected (``extract_tool_calls`` parses the
complete output in one pass).

This is the dev491 streaming tool-call regression. It is DISTINCT from
the dev259 "parse_delta dead-zone" (tool parser but ``reasoning_ended``
never set → both phases inactive → passthrough as content), which was
fixed on dev259 by adding ``--reasoning-parser qwen3`` (journal
2026-06-11-fleet-validation). On dev491 the reasoning parser IS set and
``reasoning_ended`` DOES flip — but the now-selected coder parser drops
the call because it cannot coalesce a whole-XML-in-one-delta payload.

The dev259 ``Qwen3XMLToolParser`` did NOT have this defect: its expat
push-parser emitted MULTIPLE deltas per call and merged them via
``_merge_new_deltas_to_single_response`` — so feeding the whole XML at
once produced all the tool_calls. PN392 restores that coalescing
semantics onto the dev491 single-emission coder parser.

What PN392 does
---------------
Runtime monkey-patch of ``extract_tool_calls_streaming`` on BOTH target
classes (``Qwen3CoderToolParser`` and, when present, ``Qwen3XMLToolParser``
— so the fix works on dev259 PROD AND dev491 candidate regardless of
which class ``qwen3_xml`` / ``qwen3_coder`` resolves to on the running
pin). The wrapper:

  1. Calls the original core ONCE with the real arguments — preserving
     the parser's own reset / content-passthrough / between-call
     semantics verbatim. A pure-content delta (no tool call) is returned
     UNCHANGED and stops the drain (re-feeding it would duplicate the
     content).
  2. While the parser still has PENDING in-flight tool structure
     (``in_function`` open, or more unprocessed ``<tool_call>`` starts in
     ``current_text`` than processed, or a closed-but-not-advanced tool
     whose end tag is already buffered), re-drives the core on the SAME
     accumulated text. The core advances one structural step per call
     (header → ``{`` → params → ``}`` → advance) and the wrapper merges
     every emitted ``DeltaToolCall`` into ONE ``DeltaMessage``. The loop
     stops at a true fixpoint (no observable state field moved and
     nothing was emitted).

Net effect: whatever shape the tool XML arrives in — one delta, two
deltas, the whole thing at the reasoning boundary, or token-by-token —
the wrapper emits the full coalesced tool call(s) in the SAME
``parse_delta`` invocation. ``streamed_args_for_tool`` and
``prev_tool_call_arr`` (which the serving layer reads to compute
remaining args at stream end) advance exactly as in the
called-many-times path, because the loop simply runs those same calls
back-to-back.

Why a runtime monkey-patch (not a text-patch)
---------------------------------------------
The fix is a control-flow wrapper around one method, identical in shape
for both parser classes. A source-text anchor would have to splice a
drain loop into the middle of a ~360-line method body — fragile across
pins and impossible to keep byte-stable. The wrapper is opaque to
torch.compile / dynamo (the tool parser runs in the API-server process,
not the compiled forward path — same property PN287 relies on), and it
re-binds via plain class-attribute assignment so re-importing the parser
module preserves it. This is the PN287 pattern (runtime wrap of the same
method on the same two classes) applied to a behavior-CHANGING fix
instead of a read-only observer.

Composition with PN287 (args-validity observer)
-----------------------------------------------
PN287 wraps the SAME method (read-only) and stores
``_GENESIS_PN287_ORIGINAL``. PN392 and PN287 are independent and
order-robust: each wraps whatever bound method it finds at apply() time
and delegates to it. If both are enabled, the outer wrapper delegates to
the inner; the coalescing drain re-drives the (possibly PN287-wrapped)
core, so PN287's per-call observation simply runs once per drain step —
harmless (it inspects ``prev_tool_call_arr`` which only grows). Each
patch's ``revert()`` restores only its own captured original.

Relationship to P107 (MTP truncation detector)
----------------------------------------------
P107 is the SAFETY NET, PN392 is the FIX. Before PN392, the dropped tool
call left ``tools_streamed[i]`` False and ``finish_reason="stop"`` — the
exact condition P107 raises a retryable ``GenerationError`` on (when
enabled). With PN392 the tool call is emitted, ``tools_streamed[i]``
becomes True, and the stream ends with ``finish_reason="tool_calls"`` —
so P107 never fires on this path. They compose cleanly.

Gate
----
``GENESIS_ENABLE_PN392_QWEN3CODER_STREAMING_COALESCE=1``. Default OFF
(opt-in) per the runtime-monkey-patch convention. STRONGLY recommended
ON for any streaming tool-call workload on dev491 with
``--tool-call-parser qwen3_xml`` (or ``qwen3_coder``) — it is the
promotion-blocker fix for the dev259→dev491 pin bump.

Compatibility
-------------
- Pure control-flow wrap; no anchor on text → no drift markers, no
  ``lint_drift_markers`` surface.
- Auto-skips on torch-less environments (CI, docs) — parser classes not
  importable.
- Idempotent: marker on the patched class' own ``__dict__`` (never
  inherited from the shared ``ToolParser`` base).
- Self-retires per class if upstream ships its own within-call
  coalescing (drift attribute ``_within_call_coalescing``).
- ``revert()`` restores the original bound method on every wrapped class.

Author: Sandermage (Sander Barzov Aleksandr), Ukraine, Odessa — 2026-06-13.
Genesis-original (no upstream PR coalesces the coder parser's streaming
within a single call as of 2026-06-13).
"""
from __future__ import annotations

import functools
import importlib
import logging
from typing import Any

log = logging.getLogger("genesis.wiring.pn392_qwen3coder_streaming_coalesce")

# Full env var name (for tests / operator docs); the dispatcher gate reads
# the canonical flag from the PN392 registry entry via should_apply().
ENV_FLAG_FULL = "GENESIS_ENABLE_PN392_QWEN3CODER_STREAMING_COALESCE"

_CLASS_MARKER = "_GENESIS_PN392_STREAMING_COALESCE_INSTALLED"
_ORIGINAL_ATTR = "_GENESIS_PN392_ORIGINAL"
# Drift: if upstream adds its own within-call coalescing, self-retire.
_UPSTREAM_DRIFT_MARKER = "_within_call_coalescing"

# Safety bound on the drain loop — far above any realistic per-delta
# structural-step count (a tool call is header + '{' + params-batch + '}'
# = ~4 steps; many tool calls in one delta scale linearly). Guards against
# a pathological non-advancing core spinning forever.
_MAX_DRAIN_STEPS = 512


def _tool_calls_of(delta: Any) -> list:
    """Return the delta's tool_calls list (or [] for None / no attr)."""
    if delta is None:
        return []
    tcs = getattr(delta, "tool_calls", None)
    return tcs or []


def _content_of(delta: Any) -> Any:
    """Return the delta's content (or None for None / no attr)."""
    if delta is None:
        return None
    return getattr(delta, "content", None)


def _state_key(parser: Any) -> tuple:
    """A cheap snapshot of the coder/xml parser's streaming progress.

    Used to detect whether a re-drive advanced any observable state. We
    read whatever of these fields exist (coder and xml parsers expose
    different subsets) — ``getattr`` with a default keeps it total."""
    return (
        getattr(parser, "is_tool_call_started", None),
        getattr(parser, "current_tool_index", None),
        getattr(parser, "header_sent", None),
        getattr(parser, "json_started", None),
        getattr(parser, "json_closed", None),
        getattr(parser, "param_count", None),
        getattr(parser, "in_function", None),
        # tool_call_index is the XML parser's progress counter.
        getattr(getattr(parser, "parser", None), "tool_call_index", None),
        tuple(getattr(parser, "streamed_args_for_tool", []) or []),
    )


def _has_pending_tool(parser: Any, current_text: str) -> bool:
    """True while there is in-flight tool structure left to emit.

    Mirrors the coder parser's own advance conditions:
      * ``in_function`` open → mid function body, more to emit.
      * more ``<tool_call>`` starts in current_text than processed.
      * a closed-but-not-advanced tool whose end tag is already buffered
        (the parser advances ``current_tool_index`` on the next call).
    The XML parser exposes ``in_function`` differently; we additionally
    treat ``current_function_open`` (its analog) as pending.
    """
    start_tok = getattr(parser, "tool_call_start_token", "<tool_call>")
    end_tok = getattr(parser, "tool_call_end_token", "</tool_call>")
    starts = current_text.count(start_tok)
    if getattr(parser, "in_function", False):
        return True
    if getattr(parser, "current_function_open", False):
        return True
    idx = getattr(parser, "current_tool_index", 0) or 0
    if getattr(parser, "is_tool_call_started", False) and idx < starts:
        return True
    # A closed-but-not-advanced tool whose end tag is already buffered: the
    # core advances current_tool_index on its next call, so it is pending.
    return bool(
        getattr(parser, "json_closed", False)
        and not getattr(parser, "in_function", False)
        and current_text.count(end_tok) > idx
    )


def _rebind_previous_text(
    call_args: tuple, call_kwargs: dict, value: str
) -> tuple[tuple, dict]:
    """Return (args, kwargs) with ``previous_text`` set to ``value``.

    Drain re-drives MUST pass a NON-EMPTY ``previous_text`` — otherwise the
    coder/xml core's ``if not previous_text: self.reset()`` guard fires on
    every iteration and wipes the very state we just advanced. The first
    call keeps the real (empty) ``previous_text`` so the reset happens
    exactly once; subsequent drain calls reuse ``current_text`` as
    ``previous_text`` (the same trick parse_delta itself uses when it
    flips ``tool_call_text_started``).

    ``previous_text`` is positional index 0 of the post-``self`` args, or
    the ``previous_text`` kwarg. Handle both call styles."""
    if "previous_text" in call_kwargs:
        new_kwargs = dict(call_kwargs)
        new_kwargs["previous_text"] = value
        return call_args, new_kwargs
    if call_args:
        new_args = (value,) + tuple(call_args[1:])
        return new_args, call_kwargs
    return call_args, call_kwargs


def _resolve_current_text(call_args: tuple, call_kwargs: dict) -> str:
    """Best-effort extraction of ``current_text`` from the call.

    Signature: ``(self, previous_text, current_text, delta_text,
    previous_token_ids, current_token_ids, delta_token_ids, request)``.
    ``self`` is bound separately, so ``call_args`` is 0-indexed at
    ``previous_text`` → ``current_text`` is index 1. vLLM serving calls
    positionally; handle kwargs too. Returns "" on any failure."""
    ct = call_kwargs.get("current_text")
    if ct is None and len(call_args) >= 2:
        ct = call_args[1]
    return ct if isinstance(ct, str) else ""


def _make_coalescing_streaming(original_fn):
    """Build the coalescing ``extract_tool_calls_streaming`` wrapper.

    Closure over ``original_fn`` preserves the original (possibly already
    wrapped, e.g. by PN287) method for delegation. Never raises — on any
    internal error the FIRST original result is returned unchanged so a
    user request is never crashed by the coalescing logic.
    """

    @functools.wraps(original_fn)
    def wrapped(self, *args, **kwargs):
        # First call: verbatim original semantics (reset / content
        # passthrough / between-call handling all preserved).
        first = original_fn(self, *args, **kwargs)
        try:
            first_calls = _tool_calls_of(first)
            first_content = _content_of(first)

            # Pure content delta (no tool call) → return as-is, no drain.
            # Re-feeding the same delta would duplicate this content.
            if first is not None and first_content is not None and not first_calls:
                return first

            current_text = _resolve_current_text(args, kwargs)

            # If nothing tool-related is pending after the first call, the
            # original result already represents the full step — return it
            # untouched (covers the token-by-token happy path where each
            # call legitimately emits one delta).
            if not _has_pending_tool(self, current_text):
                return first

            merged_calls: list = list(first_calls)
            merged_content: list = []
            if first_content:
                merged_content.append(first_content)
            # Template for the coalesced output — the parser's own
            # DeltaMessage class. Capture the first non-None delta we see
            # (``first`` may be None on the start-detection call, in which
            # case a drained delta supplies the class).
            template = first

            # Drain re-drives reuse current_text as previous_text so the
            # core's reset guard does NOT re-fire (see _rebind_previous_text).
            drain_args, drain_kwargs = _rebind_previous_text(
                args, kwargs, current_text
            )

            steps = 0
            while _has_pending_tool(self, current_text) and steps < _MAX_DRAIN_STEPS:
                steps += 1
                before = _state_key(self)
                nxt = original_fn(self, *drain_args, **drain_kwargs)
                after = _state_key(self)
                if nxt is not None and template is None:
                    template = nxt
                nxt_calls = _tool_calls_of(nxt)
                if nxt_calls:
                    merged_calls.extend(nxt_calls)
                    nxt_content = _content_of(nxt)
                    if nxt_content:
                        merged_content.append(nxt_content)
                # A pure-content result inside the drain is the parser's
                # delta-echo branch; the accumulated tool text already drove
                # the structural deltas, so echoing delta_text here would
                # duplicate it — drop it and keep draining structure.
                if after == before and not nxt_calls:
                    break  # true fixpoint: nothing advanced, nothing emitted

            if not merged_calls and not merged_content:
                # Nothing coalesced — defer to the original first result so
                # we never swallow a legitimate None / passthrough.
                return first

            joined_content = "".join(merged_content) if merged_content else None
            return _build_delta_like(template, merged_calls, joined_content)
        except Exception:  # noqa: BLE001 — never crash a user request
            log.debug(
                "[PN392] coalescing drain failed; returning original result",
                exc_info=True,
            )
            return first

    return wrapped


def _build_delta_like(template: Any, tool_calls: list, content: Any) -> Any:
    """Construct a DeltaMessage of the same class as ``template``.

    The wrapper must return the parser's own ``DeltaMessage`` type (the
    serving layer is duck-typed but downstream Pydantic validation is
    not). We reuse the class of a delta the original method already
    produced — no ``vllm`` import, torch-less-safe. ``template`` is always
    a delta we actually saw (``first`` or a drained one); a None template
    raises into the wrapper's except, which returns the original result.
    """
    cls = type(template) if template is not None else None
    if cls is None:
        raise RuntimeError("PN392: no DeltaMessage template available")
    try:
        out = cls(tool_calls=tool_calls)
    except TypeError:
        # Some DeltaMessage constructors require all-kw / different shape;
        # build empty then set attributes.
        out = cls()
        out.tool_calls = tool_calls
    if content:
        out.content = content
    return out


# Per target: human label, class name, import-candidate module paths
# (current layout first — PROD pins 0.21.1rc1+ / 0.22.1rc1+ — then the
# pre-2026-05 legacy entrypoints layout). Both classes are wrapped when
# importable; only the one selected by --tool-call-parser ever fires.
def _parser_targets() -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    return (
        (
            "qwen3_coder",
            "Qwen3CoderToolParser",
            (
                "vllm.tool_parsers.qwen3coder_tool_parser",
                "vllm.entrypoints.openai.tool_parsers.qwen3coder_tool_parser",
            ),
        ),
        (
            "qwen3_xml",
            "Qwen3XMLToolParser",
            (
                "vllm.tool_parsers.qwen3xml_tool_parser",
                "vllm.entrypoints.openai.tool_parsers.qwen3xml_tool_parser",
            ),
        ),
    )


def _resolve_parser_class(
    class_name: str, candidates: tuple[str, ...], errors: list[str]
) -> Any:
    """Import the parser class from the first resolvable candidate path.
    Appends failure reasons to ``errors``. Returns None when none resolve.
    """
    for candidate in candidates:
        try:
            module = importlib.import_module(candidate)
            return getattr(module, class_name)
        except (ImportError, AttributeError) as exc:
            errors.append(f"{candidate}: {exc}")
    return None


def apply() -> tuple[str, str]:
    """Install PN392 coalescing wrapper on every importable target parser.

    Opt-in: gated through the dispatcher on the PN392 registry env_flag
    (default_on=False). Always idempotent. Never raises.
    """
    from sndr.dispatcher import log_decision, should_apply

    decision, reason = should_apply("PN392")
    log_decision("PN392", decision, reason)
    if not decision:
        return "skipped", reason

    import_errors: list[str] = []
    wrapped_now: list[str] = []
    already_installed: list[str] = []
    drift_retired: list[str] = []
    any_importable = False

    for label, class_name, candidates in _parser_targets():
        cls = _resolve_parser_class(class_name, candidates, import_errors)
        if cls is None:
            continue
        any_importable = True

        # Drift detection: upstream shipped its own within-call coalescing.
        if hasattr(cls, _UPSTREAM_DRIFT_MARKER):
            drift_retired.append(label)
            continue

        # Idempotency — per class own __dict__ only (never the shared base).
        if cls.__dict__.get(_CLASS_MARKER, False):
            already_installed.append(label)
            continue

        original = cls.extract_tool_calls_streaming
        cls.extract_tool_calls_streaming = _make_coalescing_streaming(original)
        setattr(cls, _ORIGINAL_ATTR, original)
        setattr(cls, _CLASS_MARKER, True)
        wrapped_now.append(label)

    if not any_importable:
        return "skipped", (
            "vllm Qwen3CoderToolParser / Qwen3XMLToolParser not importable "
            "from any known path: " + "; ".join(import_errors)
        )

    if drift_retired and not wrapped_now and not already_installed:
        return "skipped", (
            f"upstream parser(s) {', '.join(drift_retired)} already carry "
            f"`{_UPSTREAM_DRIFT_MARKER}` — PN392 self-retires; consider "
            f"flipping `lifecycle=retired` in registry"
        )

    parts = []
    if wrapped_now:
        parts.append(f"wrapped: {', '.join(wrapped_now)}")
    if already_installed:
        parts.append(
            f"already installed (idempotent re-apply): "
            f"{', '.join(already_installed)}"
        )
    if drift_retired:
        parts.append(f"drift self-retired: {', '.join(drift_retired)}")
    return "applied", (
        "PN392 installed — extract_tool_calls_streaming within-call "
        "coalescing [" + "; ".join(parts) + "]. Drains the single-emission "
        "core so a whole-XML-in-one-delta tool call (parse_delta "
        "reasoning→tool boundary) emits delta.tool_calls instead of being "
        "silently dropped. Only the parser selected by --tool-call-parser "
        "ever fires; the other wrap is inert."
    )


def is_applied() -> bool:
    """True if the coalescing wrapper is installed on at least one class."""
    errors: list[str] = []
    for _label, class_name, candidates in _parser_targets():
        cls = _resolve_parser_class(class_name, candidates, errors)
        if cls is not None and cls.__dict__.get(_CLASS_MARKER, False):
            return True
    return False


def revert() -> bool:
    """Restore the original ``extract_tool_calls_streaming`` on every
    wrapped parser class. Returns True if at least one was reverted."""
    reverted_any = False
    errors: list[str] = []
    for _label, class_name, candidates in _parser_targets():
        cls = _resolve_parser_class(class_name, candidates, errors)
        if cls is None:
            continue
        original = cls.__dict__.get(_ORIGINAL_ATTR)
        if original is None:
            continue
        cls.extract_tool_calls_streaming = original
        delattr(cls, _ORIGINAL_ATTR)
        setattr(cls, _CLASS_MARKER, False)
        reverted_any = True
    return reverted_any


__all__ = [
    "ENV_FLAG_FULL",
    "_CLASS_MARKER",
    "_UPSTREAM_DRIFT_MARKER",
    "_make_coalescing_streaming",
    "apply",
    "is_applied",
    "revert",
]
