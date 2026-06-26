# SPDX-License-Identifier: Apache-2.0
"""PN287 — qwen3_coder × MTP arg-corruption frequency observer.

Why this patch exists
---------------------
Server-validated bench 2026-05-29 on 35B-A3B FP8 PROD (pin 626fa9bb, MTP
K=3, agentic multi-turn, max_tokens=150) hit the symptom club-3090
maintainer flagged on noonghunna/club-3090#178 as "distinct from
streaming bug #145":

    HTTP 400: "Unterminated string starting at: line 1 column 13"

Root cause: at depth ~20K accumulated context, qwen3_coder under MTP K=3
emits a tool_call whose `arguments` field is a truncated mid-JSON-string
(parser hit max_tokens budget mid-quote) — but the parser STILL claims
`finish_reason="tool_calls"` (signaling success). Downstream consumers
that re-feed the broken tool_call into chat history fail subsequent
turns with JSON validation errors.

Our existing 3-layer defense covers different surfaces:
    P64   (vllm#39598)  — streaming early-return removal (fixes cascade)
    PN56  (vllm#41466)  — XML parse fallback ("{}" leak fix)
    P61C  (deferred)    — qwen3coder SSE deferred-commit
None of them validate that the FINAL accumulated `arguments` is parseable
JSON. PN287 fills that observability gap.

What PN287 does (and explicitly does NOT do)
--------------------------------------------
DOES:
  • Monkey-patch ``Qwen3CoderToolParser.extract_tool_calls_streaming``
    to inspect ``self.prev_tool_call_arr`` after each invocation.
  • v2 (2026-06-10, call-site drift audit): ALSO monkey-patch
    ``Qwen3XMLToolParser.extract_tool_calls_streaming`` — PROD container
    vllm-qwen3.6-35b-balanced-k3 (pin 0.22.1rc1.dev259+g303916e93) runs
    ``--tool-call-parser qwen3_xml``, so the coder-only wrap never fired
    there and its counters were permanently zero. Both classes are
    wrapped when importable; the inactive parser's wrap never fires
    (the serving layer instantiates only the configured parser).
  • For every tool entry whose ``arguments`` is non-empty and non-"{}",
    attempt ``json.loads(arguments)``. On JSONDecodeError, emit a
    structured warning (one per request, dedup by request key) with:
      - tool name
      - args length
      - args first 80 chars (for diagnostic — no PII risk vs full body)
      - accumulated completion_tokens at observation time (if available)
  • Track aggregate count via process-level Counter for /metrics scrape.

v2 parser-semantics note (why the XML wrap differs internally)
--------------------------------------------------------------
The coder parser writes ``prev_tool_call_arr[i]["arguments"]`` as a
COMPLETE JSON string only at function close (or via the PN56 fallback
restore). The XML parser instead ACCUMULATES fragments per delta
(``arguments += fragment``), so mid-stream the accumulated string is
legitimately partial JSON. A naive post-invocation ``json.loads`` would
false-positive on every chunk. The XML wrap therefore gates validation
on tool-call completeness — an entry is validated only once the count
of ``</tool_call>`` end tokens in ``current_text`` exceeds its index —
with a per-instance validated-index set (reset on new stream, which
upstream signals via empty ``previous_text``). Scope: completed-call
corruption (XML framing intact, argument JSON corrupt — the club-3090
#178 MTP mode). Final-call max_tokens truncation (end token never
arrives) is the serving-layer surface PN288 owns.

DOES NOT (deliberately):
  • Mutate any model output (read-only observation)
  • Override finish_reason (out of scope — would need serving-layer hook
    and risks breaking strict OpenAI-format clients)
  • Repair truncated JSON (would lose information; bench-tool defense
    in tools/bench_agentic.py is the right place for client-side guard)

Why observability first
-----------------------
Before we ship a behavior-changing fix (override finish_reason="tool_calls"
→ "length" on parse failure, or auto-close truncated args), we need
production frequency data: is this 1% of agentic calls? 10%? Only on
35B-A3B? Only with MTP? PN287 surfaces that data without risk. After
~weeks of prod observation, the operator can decide:
  - Frequency too low → close as observed; accept the trade-off
  - Frequency meaningful + concentrated on 35B-A3B → ship the
    finish_reason override as PN288
  - Frequency meaningful + cross-model → file vllm upstream PR

Gate
----
``GENESIS_ENABLE_PN287_QWEN3CODER_ARGS_OBSERVER=1``. Default OFF.

Compatibility
-------------
- Pure observation; no anchor on text. Re-wraps the bound method via
  ``types.MethodType`` so re-importing the parser module preserves the
  patch. Re-application is idempotent (marker on the patched class).
- Auto-skips on torch-less environments (CI, docs).
- Auto-skips if upstream adds its own `_args_validation` attribute
  (drift detection).

Companion: ``tools/bench_agentic.py`` (client-side history-poisoning
defense, ships in same 2026-05-29 club-3090 cross-reference wave).

Author: Sandermage (Sander Barzov Aleksandr), Ukraine, Odessa — 2026-05-29.
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("genesis.wiring.pn287_qwen3coder_args_observer")

_ENV_FLAG = "GENESIS_ENABLE_PN287_QWEN3CODER_ARGS_OBSERVER"
_CLASS_MARKER = "_GENESIS_PN287_ARGS_OBSERVER_INSTALLED"
_UPSTREAM_DRIFT_MARKER = "_args_validation_installed"

# Process-level counters. Three surfaces, single source of truth:
#   1. Module-global ``counters`` dict — primary state, backward compat
#      for unit tests + existing operator CLI inspections
#   2. prometheus_client.Counter — auto-exposed on vLLM's /metrics endpoint
#      via the default REGISTRY (see __init.py of vllm/v1/metrics/prometheus)
#   3. Structured WARN log — per-request (deduplicated)
#
# Pattern adopted from external survey 2026-05-30 (per CLAUDE.md
# "Investigation discipline" rule, Step 4 Search + Step 5 Compare):
#   - SGLang `cpu_monitor.py` — module-level Counter on default REGISTRY
#   - LMCache `observability.py` — REGISTRY.unregister idempotency guard
#   - vLLM `v1/metrics/loggers.py` — `vllm:` namespace convention
#
# Multiproc safety: tool parser runs in API-server process (same proc
# that mounts /metrics endpoint), so single-process Counter just works.
# Even in multiproc, vLLM's PROMETHEUS_MULTIPROC_DIR + MultiProcessCollector
# auto-aggregate without explicit wiring.
counters: dict[str, int] = {
    "tool_calls_total": 0,
    "tool_calls_malformed_args": 0,
    "warnings_emitted": 0,
}

# §2.4 Phase A labels — per-model + per-context-depth bucketing on the
# Prometheus surface so PN288 evidence-gathering can distinguish:
#   - Frequency by model (35B-A3B suspect vs 27B vs gemma4)
#   - Frequency by context depth (PN287 hypothesis: depth ~20K spike)
# v2 adds `parser` (qwen3_coder | qwen3_xml) so the two wrap targets
# produce distinct series — operator can tell which parser class the
# corruption mode manifests under.
# Cardinality budget: 3 models × 4 ctx_buckets × 2 parsers = 24 series
# per counter; well within Prometheus best practice ceiling.
_LABEL_NAMES = ("model", "ctx_bucket", "parser")
_CTX_BUCKET_LIMITS: tuple[tuple[int, str], ...] = (
    (5_000,   "0-5K"),
    (15_000,  "5-15K"),
    (30_000,  "15-30K"),
)
_CTX_BUCKET_OVERFLOW = "30K+"


def _ctx_bucket(n_tokens: int) -> str:
    """Map an integer token count to one of 4 context-depth buckets."""
    for upper, name in _CTX_BUCKET_LIMITS:
        if n_tokens < upper:
            return name
    return _CTX_BUCKET_OVERFLOW


def _extract_request_and_ctx(
    call_args: tuple, call_kwargs: dict,
) -> tuple[str, str]:
    """Best-effort extraction of (model, ctx_bucket) for label tagging.

    Signature of ``Qwen3CoderToolParser.extract_tool_calls_streaming`` is
    ``(self, previous_text, current_text, delta_text, previous_token_ids,
    current_token_ids, delta_token_ids, request)``. vLLM serving.py calls
    it with kwargs in current pin (0.21.1rc1+), but downstream wrappers
    or older pins may call positionally. Handle both.

    Returns ``("unknown", "<bucket>")`` on any extraction failure — never
    raises. The observer must never crash a user request to capture
    telemetry.
    """
    request = call_kwargs.get("request")
    current_token_ids = call_kwargs.get("current_token_ids")
    # Positional fallback (parser receives `self` separately, so call_args
    # is 0-indexed at previous_text). current_token_ids is the 5th arg
    # (index 4), request is the 7th (index 6).
    if request is None and len(call_args) >= 7:
        request = call_args[6]
    if current_token_ids is None and len(call_args) >= 5:
        current_token_ids = call_args[4]
    model = "unknown"
    if request is not None:
        try:
            m = getattr(request, "model", None)
            if isinstance(m, str) and m:
                model = m
        except Exception:
            pass
    n_tokens = 0
    if current_token_ids is not None:
        try:
            n_tokens = len(current_token_ids)
        except Exception:
            pass
    return model, _ctx_bucket(n_tokens)


# Prometheus Counter handles — lazily created on first apply() to avoid
# import-time cost in torch-less environments (tests, lint, docs build).
_prom_extract_total: Any = None
_prom_malformed_total: Any = None
_prom_warnings_total: Any = None


def _setup_prometheus_counters() -> bool:
    """Idempotent Counter creation on default prometheus_client REGISTRY.

    Returns True on success or already-registered, False if prometheus_client
    not importable (torch-less env, no monitoring stack).

    Idempotency pattern (LMCache + vLLM canonical):
    walk REGISTRY._collector_to_names; unregister any collector whose
    name starts with our prefix. Then re-register fresh Counter objects.
    Handles patch re-application across worker spawns / hot reload.
    """
    global _prom_extract_total, _prom_malformed_total, _prom_warnings_total
    try:
        from prometheus_client import REGISTRY, Counter
    except ImportError:
        return False

    _PREFIX = "vllm:qwen3_tool_parser_pn287_"
    # Walk REGISTRY for stale collectors with our prefix (idempotency).
    for collector in list(REGISTRY._collector_to_names):
        names = REGISTRY._collector_to_names.get(collector, [])
        if any(n.startswith(_PREFIX) for n in names):
            try:
                REGISTRY.unregister(collector)
            except (KeyError, ValueError):
                pass

    try:
        _prom_extract_total = Counter(
            name=f"{_PREFIX}extract_total",
            documentation=(
                "PN287 Qwen3CoderToolParser tool_call arguments observed "
                "via extract_tool_calls_streaming wrap. Includes valid + "
                "malformed; subtract malformed_total for clean count. "
                "Labels: model (served-model-name from request), "
                "ctx_bucket (token-count bucket: 0-5K/5-15K/15-30K/30K+)."
            ),
            labelnames=_LABEL_NAMES,
        )
        _prom_malformed_total = Counter(
            name=f"{_PREFIX}malformed_total",
            documentation=(
                "PN287 tool_call.arguments that failed json.loads — likely "
                "max_tokens truncation mid-JSON-string (club-3090 #178). "
                "Read-only observation; does NOT mutate output. Labels: "
                "model, ctx_bucket — operator queries can pivot by both "
                "to evaluate PN288 trigger criteria per §2.4 Phase A."
            ),
            labelnames=_LABEL_NAMES,
        )
        _prom_warnings_total = Counter(
            name=f"{_PREFIX}warnings_total",
            documentation=(
                "PN287 structured WARN log emissions. Deduplicated per "
                "(parser-id, tool-name) within a single request — actual "
                "count of distinct malformed events surfaced to logs. "
                "Labels: model, ctx_bucket."
            ),
            labelnames=_LABEL_NAMES,
        )
        return True
    except (ValueError, AttributeError) as exc:
        log.warning(
            "[PN287] failed to register Prometheus counters: %s. "
            "Module-global counters dict still active.", exc,
        )
        return False


def _is_enabled() -> bool:
    return os.environ.get(_ENV_FLAG, "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _make_wrapped_streaming(original_fn):
    """Build the wrapped extract_tool_calls_streaming that observes
    args-validity post-invocation. Closure over ``original_fn`` preserves
    the original method for delegation.

    Coder-parser semantics: ``prev_tool_call_arr[i]["arguments"]`` is
    "{}" until function close, then complete JSON (or the PN56 fallback
    restore, which is exactly the truncation case we want to catch) —
    so unconditional post-invocation validation is safe here. The XML
    parser needs the completeness-gated variant below.
    """
    import functools
    import json

    @functools.wraps(original_fn)
    def wrapped(self, *args, **kwargs):
        result = original_fn(self, *args, **kwargs)
        # Per-request labels for Prometheus (cheap; extracted once per
        # call regardless of how many tool entries we inspect below).
        model_label, ctx_label = _extract_request_and_ctx(args, kwargs)
        # Post-invocation: inspect accumulated tool-call args. The parser
        # stores per-tool accumulated state on `prev_tool_call_arr`.
        try:
            arr = getattr(self, "prev_tool_call_arr", None) or []
        except Exception:
            return result
        for entry in arr:
            if not isinstance(entry, dict):
                continue
            args_str = entry.get("arguments") or ""
            if not args_str or args_str == "{}":
                continue
            counters["tool_calls_total"] += 1
            if _prom_extract_total is not None:
                _prom_extract_total.labels(
                    model=model_label, ctx_bucket=ctx_label,
                    parser="qwen3_coder",
                ).inc()
            try:
                json.loads(args_str)
            except (ValueError, TypeError):
                counters["tool_calls_malformed_args"] += 1
                if _prom_malformed_total is not None:
                    _prom_malformed_total.labels(
                        model=model_label, ctx_bucket=ctx_label,
                        parser="qwen3_coder",
                    ).inc()
                # Dedup by self-identity + tool name within same request.
                seen_key = id(self), entry.get("name") or "?"
                seen_set = getattr(self, "_pn287_seen", None) or set()
                if seen_key in seen_set:
                    continue
                seen_set.add(seen_key)
                self._pn287_seen = seen_set
                counters["warnings_emitted"] += 1
                if _prom_warnings_total is not None:
                    _prom_warnings_total.labels(
                        model=model_label, ctx_bucket=ctx_label,
                        parser="qwen3_coder",
                    ).inc()
                # Keep payload preview tight to avoid log floods.
                preview = args_str[:80].replace("\n", "\\n")
                log.warning(
                    "[PN287] qwen3_coder tool_call.arguments unparseable — "
                    "name=%s len=%d preview=%r model=%s ctx_bucket=%s. "
                    "Likely max_tokens truncation mid-JSON-string "
                    "(club-3090 #178). Downstream clients should validate "
                    "before re-feeding to chat history; see "
                    "tools/bench_agentic.py defense pattern.",
                    entry.get("name") or "?", len(args_str), preview,
                    model_label, ctx_label,
                )
        return result

    return wrapped


def _make_wrapped_streaming_xml(original_fn):
    """v2 — wrapped extract_tool_calls_streaming for Qwen3XMLToolParser.

    Differs from the coder wrap because the XML parser ACCUMULATES
    ``prev_tool_call_arr[i]["arguments"]`` incrementally per delta
    (``+=`` of streamed fragments, see qwen3xml_tool_parser.py:1291 on
    pin 0.22.1rc1.dev259). Mid-stream the accumulated string is
    legitimately partial JSON; validating it per invocation would
    false-positive on every chunk. Instead:

      • An entry at index ``i`` is validated only once
        ``current_text.count("</tool_call>") > i`` — i.e. its XML
        framing has closed, so the accumulated args are final.
      • Per-instance ``_pn287_xml_validated`` index set guarantees each
        completed call is observed exactly once per stream.
      • The set resets when upstream resets parser state (empty
        ``previous_text`` marks a new streaming session — same signal
        the upstream method itself uses at qwen3xml_tool_parser.py:1238).

    Scope: corruption INSIDE completed tool calls (framing intact, args
    JSON corrupt — the club-3090 #178 MTP mode). A final call truncated
    by max_tokens never closes its framing and is deliberately out of
    scope here; that surface belongs to the PN288 serving-layer
    middleware which sees end-of-stream.
    """
    import functools
    import json

    @functools.wraps(original_fn)
    def wrapped(self, *args, **kwargs):
        result = original_fn(self, *args, **kwargs)
        try:
            previous_text = kwargs.get("previous_text")
            if previous_text is None and args:
                previous_text = args[0]
            if not previous_text:
                # New streaming session — mirror upstream's state reset.
                self._pn287_xml_validated = set()
            current_text = kwargs.get("current_text")
            if current_text is None and len(args) >= 2:
                current_text = args[1]
            current_text = current_text or ""
            inner = getattr(self, "parser", None)
            end_token = (
                getattr(inner, "tool_call_end_token", None) or "</tool_call>"
            )
            completed_calls = current_text.count(end_token)
            arr = getattr(self, "prev_tool_call_arr", None) or []
        except Exception:
            return result
        if completed_calls <= 0 or not arr:
            return result
        validated = getattr(self, "_pn287_xml_validated", None)
        if validated is None:
            validated = set()
            try:
                self._pn287_xml_validated = validated
            except Exception:
                return result
        # Fast path: every completed index already observed.
        if len(validated) >= completed_calls:
            return result
        model_label, ctx_label = _extract_request_and_ctx(args, kwargs)
        for idx, entry in enumerate(arr):
            if idx >= completed_calls or idx in validated:
                continue
            validated.add(idx)
            if not isinstance(entry, dict):
                continue
            args_str = entry.get("arguments") or ""
            if not args_str or args_str == "{}":
                continue
            counters["tool_calls_total"] += 1
            if _prom_extract_total is not None:
                _prom_extract_total.labels(
                    model=model_label, ctx_bucket=ctx_label,
                    parser="qwen3_xml",
                ).inc()
            try:
                json.loads(args_str)
            except (ValueError, TypeError):
                counters["tool_calls_malformed_args"] += 1
                if _prom_malformed_total is not None:
                    _prom_malformed_total.labels(
                        model=model_label, ctx_bucket=ctx_label,
                        parser="qwen3_xml",
                    ).inc()
                # Per-index dedup above already guarantees one
                # observation per completed call — warning is 1:1
                # with malformed for the XML wrap.
                counters["warnings_emitted"] += 1
                if _prom_warnings_total is not None:
                    _prom_warnings_total.labels(
                        model=model_label, ctx_bucket=ctx_label,
                        parser="qwen3_xml",
                    ).inc()
                preview = args_str[:80].replace("\n", "\\n")
                log.warning(
                    "[PN287] qwen3_xml tool_call.arguments unparseable on "
                    "completed call — name=%s index=%d len=%d preview=%r "
                    "model=%s ctx_bucket=%s. Arg-corruption inside closed "
                    "XML framing (club-3090 #178 MTP mode). Downstream "
                    "clients should validate before re-feeding to chat "
                    "history; see tools/bench_agentic.py defense pattern.",
                    entry.get("name") or "?", idx, len(args_str), preview,
                    model_label, ctx_label,
                )
        return result

    return wrapped


# v2 wrap targets. Per target: Prometheus parser label, class name,
# import candidates (new layout first — matches PROD pins 0.21.1rc1+ /
# 0.22.1rc1+ — then the pre-2026-05 legacy layout), wrapper factory.
def _parser_targets() -> tuple[tuple[str, str, tuple[str, ...], Any], ...]:
    return (
        (
            "qwen3_coder",
            "Qwen3CoderToolParser",
            (
                "vllm.tool_parsers.qwen3coder_tool_parser",
                "vllm.entrypoints.openai.tool_parsers.qwen3coder_tool_parser",
            ),
            _make_wrapped_streaming,
        ),
        (
            "qwen3_xml",
            "Qwen3XMLToolParser",
            (
                "vllm.tool_parsers.qwen3xml_tool_parser",
                "vllm.entrypoints.openai.tool_parsers.qwen3xml_tool_parser",
            ),
            _make_wrapped_streaming_xml,
        ),
    )


def _resolve_parser_class(
    class_name: str, candidates: tuple[str, ...], errors: list[str],
) -> Any:
    """Import the parser class from the first resolvable candidate path.
    Appends human-readable failure reasons to ``errors``. Returns None
    when no candidate resolves."""
    import importlib

    for candidate in candidates:
        try:
            module = importlib.import_module(candidate)
            return getattr(module, class_name)
        except (ImportError, AttributeError) as exc:
            errors.append(f"{candidate}: {exc}")
    return None


def apply() -> tuple[str, str]:
    """Install PN287 observer on every importable target parser class.
    Always idempotent. Never raises."""
    if not _is_enabled():
        return "skipped", (
            f"opt-in — set {_ENV_FLAG}=1 to enable qwen3 tool-parser "
            f"args-validity observer (warns when tool_call.arguments is "
            f"unparseable; club-3090 #178; v2 wraps qwen3_coder AND "
            f"qwen3_xml)"
        )

    import_errors: list[str] = []
    wrapped_now: list[str] = []
    already_installed: list[str] = []
    drift_retired: list[str] = []
    any_importable = False
    prom_ready = False

    for label, class_name, candidates, factory in _parser_targets():
        cls = _resolve_parser_class(class_name, candidates, import_errors)
        if cls is None:
            continue
        any_importable = True

        # Drift detection: if upstream adds its own validation marker,
        # self-retire for that class.
        if hasattr(cls, _UPSTREAM_DRIFT_MARKER):
            drift_retired.append(label)
            continue

        # Set up Prometheus Counter integration once we know at least
        # one wrap target exists — auto-exposed via vLLM's /metrics
        # endpoint via default REGISTRY (idempotent across re-apply).
        if not prom_ready:
            prom_ready = _setup_prometheus_counters()

        # Idempotency check — per class, own __dict__ only (the two
        # parser classes share the ToolParser base; never inherit the
        # marker).
        if cls.__dict__.get(_CLASS_MARKER, False):
            already_installed.append(label)
            continue

        original = cls.extract_tool_calls_streaming
        cls.extract_tool_calls_streaming = factory(original)
        cls._GENESIS_PN287_ORIGINAL = original  # noqa: SLF001
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
            f"`{_UPSTREAM_DRIFT_MARKER}` — PN287 self-retires; consider "
            f"flipping `lifecycle=retired` in registry"
        )

    prom_note = (
        " + Prometheus counters registered on default REGISTRY "
        "(vllm:qwen3_tool_parser_pn287_*, labels model/ctx_bucket/parser)"
        " — auto-exposed on /metrics"
        if prom_ready
        else " (prometheus_client unavailable — module-global dict only)"
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
        "PN287 v2 installed — extract_tool_calls_streaming args-validity "
        "observer [" + "; ".join(parts) + "]. Only the parser selected by "
        "--tool-call-parser ever fires; the other wrap is inert. Counters "
        "at sndr.engines.vllm.patches.tool_parsing.pn287_qwen3coder_args_"
        "validity_observer.counters" + prom_note + "."
    )


def is_applied() -> bool:
    """True if the observer is installed on at least one parser class."""
    errors: list[str] = []
    for _label, class_name, candidates, _factory in _parser_targets():
        cls = _resolve_parser_class(class_name, candidates, errors)
        if cls is not None and cls.__dict__.get(_CLASS_MARKER, False):
            return True
    return False


def revert() -> bool:
    """Revert the monkey-patch on every wrapped parser class — restore
    original ``extract_tool_calls_streaming``. Returns True if at least
    one class was reverted, False if nothing to revert.
    """
    reverted_any = False
    errors: list[str] = []
    for _label, class_name, candidates, _factory in _parser_targets():
        cls = _resolve_parser_class(class_name, candidates, errors)
        if cls is None:
            continue
        original = cls.__dict__.get("_GENESIS_PN287_ORIGINAL")
        if original is None:
            continue
        cls.extract_tool_calls_streaming = original
        delattr(cls, "_GENESIS_PN287_ORIGINAL")
        setattr(cls, _CLASS_MARKER, False)
        reverted_any = True
    return reverted_any
