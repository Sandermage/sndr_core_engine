# SPDX-License-Identifier: Apache-2.0
"""PN288 — qwen3_coder tool_call finish_reason override (§1.3 of the
unified plan, Phase B / dry-run scaffold).

What PN288 is for
-----------------
PN287 (deployed in §2.4 Phase A) **observes** the frequency of
malformed `tool_call.arguments` — when qwen3_coder under MTP truncates
a tool call's arguments mid-JSON-string because the model hit
`max_tokens`. PN287 emits no behavior change.

PN288 is the **mutating** companion. When upstream serving.py would
emit ``finish_reason="tool_calls"`` BUT the accumulated
``tool_call.arguments`` doesn't parse as JSON AND the underlying
``output.finish_reason`` is ``"length"`` (max_tokens cut), PN288
downgrades the response to ``finish_reason="length"``. OpenAI-format
clients (Cline, Claude Code, openai-python/-node) treat
``finish_reason="length"`` as the canonical "retry with higher
max_tokens" signal — so the downgrade lets them auto-recover the
chain without manual intervention.

The risk: a behavior change in the response shape is irreversible
per request — once mutated, the client semantics are different. The
plan §1.3 splits the risk into three phases:

  - **Phase A** (§2.4, done): PN287 labeled Prometheus counters for
    evidence gathering. No behavior change.
  - **Phase B** (this module): full decision logic + text-patch + opt-in
    env flag — but with ``GENESIS_PN288_DRY_RUN=1`` defaulted ON when
    PN288 itself is enabled. Logs "WOULD downgrade" + Prometheus
    counter; emits upstream's finish_reason unchanged.
  - **Phase C** (operator decision, future): flip ``DRY_RUN=0`` after
    2-4 weeks of Phase A+B evidence shows PN288 fires on a meaningful
    fraction of requests with the right model/context profile.

What this module does
---------------------
Pure-Python decision logic, callable from the text-patched bodies of
``OpenAIServingChat._create_chat_completion`` at two anchors
(streaming + non-streaming finish_reason assignment). The text patch
itself lives in
``vllm/sndr_core/integrations/serving/pn288_tool_finish_reason_override.py``
— this module hosts only the runtime logic so it can be unit-tested
in isolation without applying the overlay.

Gates
-----
  * ``GENESIS_ENABLE_PN288_TOOL_FINISH_REASON_OVERRIDE`` — overall
    enable. Default OFF (the text patch is only installed when this
    is ``1``). When unset, the helper still imports cleanly (so the
    text-patch fallback path can call it defensively without raising)
    and ALL paths return the upstream finish_reason unchanged.
  * ``GENESIS_PN288_DRY_RUN`` — Phase B vs Phase C selector. Default
    ``1`` (Phase B: log + count, no behavior change). Set ``0`` only
    after Phase A+B evidence justifies the behavior change.

Prometheus surface
------------------
Single counter ``vllm:pn288_finish_reason_override_total`` with labels
``(model, channel, action)``:

  * ``channel`` ∈ {``streaming``, ``non_streaming``}
  * ``action`` ∈ {``would_downgrade``, ``downgraded``,
    ``kept_tool_calls_args_valid``, ``kept_tool_calls_no_length_trunc``}

Cardinality budget: 3 models × 2 channels × 4 actions = 24 series,
well within Prometheus best practice.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional


log = logging.getLogger("genesis.middleware.pn288_finish_reason_override")


_ENV_ENABLE = "GENESIS_ENABLE_PN288_TOOL_FINISH_REASON_OVERRIDE"
_ENV_DRY_RUN = "GENESIS_PN288_DRY_RUN"

# Sentinels mirrored on the Prometheus action label; constants here so
# tests can reference them without hard-coding strings.
_ACTION_WOULD_DOWNGRADE = "would_downgrade"
_ACTION_DOWNGRADED = "downgraded"
_ACTION_KEPT_VALID = "kept_tool_calls_args_valid"
_ACTION_KEPT_NO_LENGTH = "kept_tool_calls_no_length_trunc"

_LABEL_NAMES = ("model", "channel", "action")

# Lazily-registered Prometheus Counter (None when prometheus_client
# isn't importable — torch-less CI, doc builds, lint).
_prom_counter: Any = None

# Module-global dict — backward-compat surface mirroring PN287. Keys are
# tuples (channel, action); values are integer counts. Useful for unit
# tests that don't want to depend on prometheus_client.
counters: dict[tuple[str, str], int] = {}


# ─── Env gates ──────────────────────────────────────────────────────────


def _env_truthy(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def is_enabled() -> bool:
    """Overall PN288 enable. False by default — opt-in only."""
    return _env_truthy(_ENV_ENABLE, default=False)


def is_dry_run() -> bool:
    """Phase B (dry-run) vs Phase C (actual override). Default True
    when PN288 is enabled — the operator must explicitly flip
    ``GENESIS_PN288_DRY_RUN=0`` after evidence justifies it."""
    return _env_truthy(_ENV_DRY_RUN, default=True)


# ─── Prometheus setup ──────────────────────────────────────────────────


def setup_prometheus_counters() -> bool:
    """Idempotent registration of the labeled Counter.

    Mirrors PN287's pattern: walk REGISTRY._collector_to_names and
    unregister any prior PN288 collectors before re-registering. Safe
    across worker spawns + hot reload.

    Returns True on success or already-registered, False if
    prometheus_client isn't importable (torch-less env).
    """
    global _prom_counter
    try:
        from prometheus_client import REGISTRY, Counter
    except ImportError:
        return False

    name = "vllm:pn288_finish_reason_override_total"
    for collector in list(REGISTRY._collector_to_names):
        names = REGISTRY._collector_to_names.get(collector, [])
        if any(n.startswith("vllm:pn288_finish_reason_override")
               for n in names):
            try:
                REGISTRY.unregister(collector)
            except (KeyError, ValueError):
                pass

    try:
        _prom_counter = Counter(
            name="vllm:pn288_finish_reason_override",
            documentation=(
                "PN288 finish_reason override decisions. "
                "Labels: model (request.model), "
                "channel (streaming|non_streaming), "
                "action (would_downgrade|downgraded|"
                "kept_tool_calls_args_valid|kept_tool_calls_no_length_trunc). "
                "Phase B dry-run mode increments only would_downgrade + "
                "kept_*; Phase C also fires downgraded."
            ),
            labelnames=_LABEL_NAMES,
        )
        return True
    except (ValueError, AttributeError) as exc:
        log.warning(
            "[PN288] failed to register Prometheus counter: %s. "
            "Module-global dict still active.", exc,
        )
        return False


def _track(*, model: str, channel: str, action: str) -> None:
    """Increment both surfaces (dict + Prometheus). Never raises."""
    counters[(channel, action)] = counters.get((channel, action), 0) + 1
    if _prom_counter is not None:
        try:
            _prom_counter.labels(
                model=model, channel=channel, action=action,
            ).inc()
        except Exception:
            pass  # observability must not break the request


# ─── Helpers ───────────────────────────────────────────────────────────


def _safe_model_name(request: Any) -> str:
    if request is None:
        return "unknown"
    try:
        m = getattr(request, "model", None)
        if isinstance(m, str) and m:
            return m
    except Exception:
        pass
    return "unknown"


def _validate_tool_call_args(tool_parser: Any) -> bool:
    """Walk ``tool_parser.prev_tool_call_arr`` and return True iff every
    non-empty ``arguments`` field is parseable JSON.

    Mirrors PN287's logic so the two patches stay in lockstep on what
    counts as "malformed". Empty / placeholder ``"{}"`` / missing
    ``arguments`` are treated as valid (no JSON to validate). Returns
    True (allow upstream behavior) when the parser doesn't expose
    ``prev_tool_call_arr`` at all — only intervene when we have
    positive evidence of malformation.
    """
    if tool_parser is None:
        return True
    try:
        arr = getattr(tool_parser, "prev_tool_call_arr", None) or []
    except Exception:
        return True
    for entry in arr:
        if not isinstance(entry, dict):
            continue
        args_str = entry.get("arguments") or ""
        if not args_str or args_str == "{}":
            continue
        try:
            json.loads(args_str)
        except (ValueError, TypeError):
            return False
    return True


def _output_finish_reason(output: Any) -> Optional[str]:
    if output is None:
        return None
    try:
        return getattr(output, "finish_reason", None)
    except Exception:
        return None


# ─── Streaming branch ──────────────────────────────────────────────────


def decide_streaming_finish_reason(
    *,
    auto_tools_called: bool,
    tools_streamed_i: bool,
    tool_choice_function_name: Any,
    use_harmony: bool,
    harmony_tools_streamed_i: bool,
    output: Any,
    request: Any,
    tool_parser: Any,
) -> str:
    """Replacement for the upstream streaming finish_reason if-block at
    ``serving.py:884-893`` (verified on pin 626fa9bb).

    Upstream logic:
        if (auto_tools_called or (tools_streamed[i] and not
                tool_choice_function_name)
                or (self.use_harmony and harmony_tools_streamed[i])):
            finish_reason_ = "tool_calls"
        else:
            finish_reason_ = output.finish_reason or "stop"

    PN288 layer:
      * Compute upstream's verdict first (preserves correctness when
        PN288 is disabled — when ``is_enabled()`` is False, the helper
        always returns the upstream verdict).
      * Only intervene on the (auto_tools_called + length + unparseable)
        triangle. Anything else short-circuits to upstream's verdict.
      * In dry-run mode (Phase B, default): log "WOULD downgrade",
        increment Prometheus counter, return upstream's verdict.
      * In actual mode (Phase C): log + count + return "length".
    """
    upstream_says_tool_calls = (
        auto_tools_called
        or (tools_streamed_i and not tool_choice_function_name)
        or (use_harmony and harmony_tools_streamed_i)
    )
    if upstream_says_tool_calls:
        upstream_verdict = "tool_calls"
    else:
        out_fr = _output_finish_reason(output)
        upstream_verdict = out_fr if out_fr else "stop"

    if not is_enabled():
        return upstream_verdict

    # Only consider downgrade when upstream would emit "tool_calls"
    # AND auto_tools_called fired (the canonical trigger condition).
    if not (upstream_says_tool_calls and auto_tools_called):
        return upstream_verdict

    out_fr = _output_finish_reason(output)
    if out_fr != "length":
        # Normal completion — no truncation suspicion, leave it.
        return upstream_verdict

    args_valid = _validate_tool_call_args(tool_parser)
    model = _safe_model_name(request)
    if args_valid:
        _track(model=model, channel="streaming",
               action=_ACTION_KEPT_VALID)
        return upstream_verdict

    # Trigger condition met: tool_calls + length + unparseable args.
    if is_dry_run():
        _track(model=model, channel="streaming",
               action=_ACTION_WOULD_DOWNGRADE)
        log.warning(
            "[PN288 dry-run] WOULD downgrade finish_reason "
            "'tool_calls' → 'length' (model=%s; channel=streaming; "
            "tool_call.arguments unparseable + output.finish_reason="
            "'length'). Set GENESIS_PN288_DRY_RUN=0 after evidence "
            "review to enable Phase C behavior change.",
            model,
        )
        return upstream_verdict

    _track(model=model, channel="streaming",
           action=_ACTION_DOWNGRADED)
    log.info(
        "[PN288] downgrading finish_reason 'tool_calls' → 'length' "
        "(model=%s; channel=streaming). Client should retry with "
        "higher max_tokens (OpenAI semantics).", model,
    )
    return "length"


# ─── Non-streaming branch ──────────────────────────────────────────────


def decide_non_streaming_is_tool_calls(
    *,
    auto_tools_called: bool,
    request: Any,
    output: Any,
    tool_parser: Any,
) -> bool:
    """Replacement for the upstream non-streaming bool at
    ``serving.py:1306-1310`` (verified on pin 626fa9bb).

    Upstream logic:
        is_finish_reason_tool_calls = auto_tools_called or (
            request.tool_choice
            and request.tool_choice == "required"
            and output.finish_reason == "stop"
        )

    Returns the same boolean as upstream, EXCEPT when PN288's downgrade
    condition fires — then returns False so the consumer's
    ``finish_reason="tool_calls" if is_finish_reason_tool_calls else
    output.finish_reason`` falls into the ``output.finish_reason``
    branch (which by construction is ``"length"`` in the downgrade
    case).
    """
    request_tool_choice = getattr(request, "tool_choice", None)
    upstream_verdict = bool(
        auto_tools_called
        or (
            request_tool_choice
            and request_tool_choice == "required"
            and _output_finish_reason(output) == "stop"
        )
    )

    if not is_enabled():
        return upstream_verdict

    if not (upstream_verdict and auto_tools_called):
        return upstream_verdict

    out_fr = _output_finish_reason(output)
    if out_fr != "length":
        return upstream_verdict

    args_valid = _validate_tool_call_args(tool_parser)
    model = _safe_model_name(request)
    if args_valid:
        _track(model=model, channel="non_streaming",
               action=_ACTION_KEPT_VALID)
        return upstream_verdict

    if is_dry_run():
        _track(model=model, channel="non_streaming",
               action=_ACTION_WOULD_DOWNGRADE)
        log.warning(
            "[PN288 dry-run] WOULD downgrade finish_reason "
            "'tool_calls' → 'length' (model=%s; channel=non_streaming; "
            "tool_call.arguments unparseable + output.finish_reason="
            "'length'). Set GENESIS_PN288_DRY_RUN=0 after evidence "
            "review to enable Phase C behavior change.",
            model,
        )
        return upstream_verdict

    _track(model=model, channel="non_streaming",
           action=_ACTION_DOWNGRADED)
    log.info(
        "[PN288] downgrading finish_reason 'tool_calls' → 'length' "
        "(model=%s; channel=non_streaming). Client should retry with "
        "higher max_tokens (OpenAI semantics).", model,
    )
    return False  # → consumer falls through to output.finish_reason ('length')


__all__ = [
    "is_enabled",
    "is_dry_run",
    "setup_prometheus_counters",
    "decide_streaming_finish_reason",
    "decide_non_streaming_is_tool_calls",
    "counters",
    "_track",
    "_validate_tool_call_args",
    "_safe_model_name",
    "_ACTION_WOULD_DOWNGRADE",
    "_ACTION_DOWNGRADED",
    "_ACTION_KEPT_VALID",
    "_ACTION_KEPT_NO_LENGTH",
]
