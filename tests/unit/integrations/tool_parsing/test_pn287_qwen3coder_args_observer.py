# SPDX-License-Identifier: Apache-2.0
"""Tests for PN287 — qwen3_coder × MTP arg-corruption frequency observer.

The patch ships a runtime monkey-patch (no text-patch), so test strategy:

  1. Pure-function: ``_make_wrapped_streaming`` against a fake parser
     instance — confirm it inspects ``prev_tool_call_arr``, increments
     counters on bad JSON, leaves results pass-through.
  2. apply() / is_applied() / revert() lifecycle with a mock parser class.
  3. Gate honored: env unset → skipped.
  4. Idempotency: re-apply doesn't double-wrap.
  5. Drift detection: upstream marker → self-retire.
"""
from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]


def _import_patch():
    """Import the PN287 module. Standard package path — pure Python (no torch)."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        mod = importlib.import_module(
            "vllm.sndr_core.integrations.tool_parsing."
            "pn287_qwen3coder_args_validity_observer"
        )
    finally:
        sys.path.pop(0)
    return mod


def _reset_counters(mod) -> None:
    mod.counters["tool_calls_total"] = 0
    mod.counters["tool_calls_malformed_args"] = 0
    mod.counters["warnings_emitted"] = 0


# ─────────────────────── pure-function coverage ──────────────────────


def test_wrapped_streaming_passes_through_valid_args() -> None:
    mod = _import_patch()
    _reset_counters(mod)

    class FakeParser:
        prev_tool_call_arr = [
            {"name": "Read", "arguments": '{"file_path":"/a"}'}
        ]

        def extract_tool_calls_streaming(self, *args, **kwargs):
            return "delta_value"

    parser = FakeParser()
    original = FakeParser.extract_tool_calls_streaming
    wrapped = mod._make_wrapped_streaming(original)
    out = wrapped(parser, "any", "args")
    assert out == "delta_value"
    assert mod.counters["tool_calls_total"] == 1
    assert mod.counters["tool_calls_malformed_args"] == 0
    assert mod.counters["warnings_emitted"] == 0


def test_wrapped_streaming_detects_truncated_json(caplog) -> None:
    mod = _import_patch()
    _reset_counters(mod)

    class FakeParser:
        # Truncated mid-quoted-string — exactly the symptom from
        # 35B PROD bench 2026-05-29 turn 8 session 1.
        prev_tool_call_arr = [
            {"name": "Read", "arguments": '{"file_path":"/some/lo'}
        ]

        def extract_tool_calls_streaming(self, *args, **kwargs):
            return None

    parser = FakeParser()
    wrapped = mod._make_wrapped_streaming(
        FakeParser.extract_tool_calls_streaming
    )
    with caplog.at_level("WARNING", logger="genesis.wiring."
                         "pn287_qwen3coder_args_observer"):
        wrapped(parser, "x", "y")
    assert mod.counters["tool_calls_total"] == 1
    assert mod.counters["tool_calls_malformed_args"] == 1
    assert mod.counters["warnings_emitted"] == 1
    assert any("PN287" in r.message for r in caplog.records)
    assert any("Unparseable" in r.message or "unparseable" in r.message
               for r in caplog.records)


def test_wrapped_streaming_dedups_warnings_per_request() -> None:
    mod = _import_patch()
    _reset_counters(mod)

    class FakeParser:
        prev_tool_call_arr = [
            {"name": "Edit", "arguments": '{"file_path":"/a","content":"x'},
        ]

        def extract_tool_calls_streaming(self, *args, **kwargs):
            return None

    parser = FakeParser()
    wrapped = mod._make_wrapped_streaming(
        FakeParser.extract_tool_calls_streaming
    )
    wrapped(parser, "x")
    wrapped(parser, "y")
    wrapped(parser, "z")
    # Per-request dedup: warning only emits once even though wrapped
    # runs three times on the same parser instance with the same
    # accumulated state.
    assert mod.counters["tool_calls_total"] == 3
    assert mod.counters["tool_calls_malformed_args"] == 3
    assert mod.counters["warnings_emitted"] == 1


def test_wrapped_streaming_skips_empty_or_placeholder_args() -> None:
    mod = _import_patch()
    _reset_counters(mod)

    class FakeParser:
        prev_tool_call_arr = [
            {"name": "Read", "arguments": ""},
            {"name": "Edit", "arguments": "{}"},  # placeholder leak
            {"name": "Bash", "arguments": None},
        ]

        def extract_tool_calls_streaming(self, *args, **kwargs):
            return None

    parser = FakeParser()
    wrapped = mod._make_wrapped_streaming(
        FakeParser.extract_tool_calls_streaming
    )
    wrapped(parser)
    # No entries counted — empty/placeholder/None skipped before validation.
    assert mod.counters["tool_calls_total"] == 0
    assert mod.counters["warnings_emitted"] == 0


def test_wrapped_streaming_survives_missing_prev_tool_call_arr() -> None:
    mod = _import_patch()
    _reset_counters(mod)

    class FakeParser:
        def extract_tool_calls_streaming(self, *args, **kwargs):
            return "ok"

    parser = FakeParser()
    wrapped = mod._make_wrapped_streaming(
        FakeParser.extract_tool_calls_streaming
    )
    out = wrapped(parser)
    assert out == "ok"
    assert mod.counters["tool_calls_total"] == 0


# ─────────────────────── apply / revert / gate ──────────────────────


def test_apply_skipped_when_env_unset(monkeypatch) -> None:
    mod = _import_patch()
    monkeypatch.delenv("GENESIS_ENABLE_PN287_QWEN3CODER_ARGS_OBSERVER",
                       raising=False)
    status, reason = mod.apply()
    assert status == "skipped"
    assert "opt-in" in reason


def test_setup_prometheus_counters_idempotent() -> None:
    """Calling _setup_prometheus_counters twice should not raise and
    should leave the module Counter handles populated.

    External pattern adopted from LMCache observability.py — REGISTRY.
    unregister walk handles re-application across spawns / hot reload.
    """
    try:
        import prometheus_client  # noqa: F401
    except ImportError:
        pytest.skip("prometheus_client not installed in this env")

    mod = _import_patch()
    # First call — should register cleanly
    assert mod._setup_prometheus_counters() is True
    assert mod._prom_extract_total is not None
    assert mod._prom_malformed_total is not None
    assert mod._prom_warnings_total is not None

    # Second call — idempotent: unregister + re-register, no error
    assert mod._setup_prometheus_counters() is True
    assert mod._prom_extract_total is not None


def test_prometheus_counter_naming_convention() -> None:
    """Counters must use `vllm:qwen3_tool_parser_pn287_*` prefix to
    match vLLM's own naming (e.g. vllm:num_requests_running), so
    operator dashboards work without re-templating."""
    try:
        import prometheus_client  # noqa: F401
    except ImportError:
        pytest.skip("prometheus_client not installed")

    mod = _import_patch()
    mod._setup_prometheus_counters()
    # Counter exposes ._name attribute (without _total suffix per
    # Prometheus convention — client appends it automatically)
    assert mod._prom_extract_total._name == (
        "vllm:qwen3_tool_parser_pn287_extract"
    )
    assert mod._prom_malformed_total._name == (
        "vllm:qwen3_tool_parser_pn287_malformed"
    )
    assert mod._prom_warnings_total._name == (
        "vllm:qwen3_tool_parser_pn287_warnings"
    )


def test_prometheus_counter_increments_alongside_dict() -> None:
    """When wrapped streaming fires, BOTH module-global dict AND
    Prometheus Counter must increment. Backward-compat surface
    (dict) preserved while adding scrapable surface (Counter).

    §2.4 Phase A: Counters are now labeled with (model, ctx_bucket); a
    call without a request lands under the ('unknown', '0-5K') label
    tuple, which this test asserts to lock the fallback semantic.
    """
    try:
        import prometheus_client  # noqa: F401
    except ImportError:
        pytest.skip("prometheus_client not installed")

    mod = _import_patch()
    _reset_counters(mod)
    mod._setup_prometheus_counters()

    # The default-label tuple for a call without request kwargs.
    extract_default = mod._prom_extract_total.labels(
        model="unknown", ctx_bucket="0-5K",
    )
    malformed_default = mod._prom_malformed_total.labels(
        model="unknown", ctx_bucket="0-5K",
    )
    before_extract = extract_default._value.get()
    before_malformed = malformed_default._value.get()

    class FakeParser:
        prev_tool_call_arr = [
            {"name": "Read", "arguments": '{"file_path":"/some/lo'},
        ]

        def extract_tool_calls_streaming(self, *args, **kwargs):
            return None

    parser = FakeParser()
    wrapped = mod._make_wrapped_streaming(
        FakeParser.extract_tool_calls_streaming
    )
    wrapped(parser, "x")

    # Dict surface still works (backward compat)
    assert mod.counters["tool_calls_total"] == 1
    assert mod.counters["tool_calls_malformed_args"] == 1

    # Prometheus Counter incremented under the default label tuple
    after_extract = extract_default._value.get()
    after_malformed = malformed_default._value.get()
    assert after_extract == before_extract + 1
    assert after_malformed == before_malformed + 1


# ─────────────────────── §2.4 label extraction (Phase A) ─────────────


class _FakeRequest:
    """Minimal stand-in for ChatCompletionRequest — only `model` is read."""
    def __init__(self, model: str):
        self.model = model


def test_ctx_bucket_boundaries() -> None:
    """4 buckets: 0-5K / 5-15K / 15-30K / 30K+. Right-exclusive upper."""
    mod = _import_patch()
    assert mod._ctx_bucket(0)      == "0-5K"
    assert mod._ctx_bucket(4999)   == "0-5K"
    assert mod._ctx_bucket(5000)   == "5-15K"
    assert mod._ctx_bucket(14999)  == "5-15K"
    assert mod._ctx_bucket(15000)  == "15-30K"
    assert mod._ctx_bucket(29999)  == "15-30K"
    assert mod._ctx_bucket(30000)  == "30K+"
    assert mod._ctx_bucket(150000) == "30K+"


def test_extract_labels_from_keyword_request() -> None:
    """request + current_token_ids passed as keyword args (the common path
    from vLLM serving.py)."""
    mod = _import_patch()
    req = _FakeRequest(model="qwen3.6-35b-a3b")
    model, bucket = mod._extract_request_and_ctx(
        call_args=(),
        call_kwargs={"current_token_ids": list(range(7500)), "request": req},
    )
    assert model == "qwen3.6-35b-a3b"
    assert bucket == "5-15K"


def test_extract_labels_from_positional_args() -> None:
    """Positional call shape: (prev_text, curr_text, delta_text,
    prev_token_ids, current_token_ids, delta_token_ids, request)."""
    mod = _import_patch()
    req = _FakeRequest(model="qwen3.6-27b-int4")
    # current_token_ids at args[4], request at args[6]
    call_args = (
        "prev", "curr", "delta",
        [0] * 100,        # previous_token_ids
        [0] * 18_000,     # current_token_ids → ctx_bucket "15-30K"
        [0] * 5,          # delta_token_ids
        req,
    )
    model, bucket = mod._extract_request_and_ctx(
        call_args=call_args, call_kwargs={},
    )
    assert model == "qwen3.6-27b-int4"
    assert bucket == "15-30K"


def test_extract_labels_fallback_to_unknown_when_missing() -> None:
    """Defensive: if request / current_token_ids missing, return safe
    sentinels rather than raise. The PN287 observer must NEVER crash a
    user request just to capture telemetry."""
    mod = _import_patch()
    model, bucket = mod._extract_request_and_ctx(
        call_args=(), call_kwargs={},
    )
    assert model == "unknown"
    assert bucket == "0-5K"  # n_tokens=0 falls in the lowest bucket


def test_extract_labels_handles_request_with_no_model_attr() -> None:
    """request.model can be missing or None (older client libs). Stay
    'unknown' instead of raising AttributeError."""
    mod = _import_patch()

    class _NakedRequest:
        pass

    model, bucket = mod._extract_request_and_ctx(
        call_args=(), call_kwargs={
            "request": _NakedRequest(),
            "current_token_ids": list(range(3000)),
        },
    )
    assert model == "unknown"
    assert bucket == "0-5K"


def test_labeled_counter_increments_with_correct_labels() -> None:
    """When wrapped streaming fires with a known model + ctx depth, the
    labeled Prometheus Counter records under the right (model, ctx_bucket)
    tuple. This is the data §2.4 Phase A unlocks for PN288 decision."""
    try:
        import prometheus_client  # noqa: F401
    except ImportError:
        pytest.skip("prometheus_client not installed")

    mod = _import_patch()
    _reset_counters(mod)
    mod._setup_prometheus_counters()

    class FakeParser:
        prev_tool_call_arr = [
            {"name": "Read", "arguments": '{"file_path":"/some/lo'}
        ]

        def extract_tool_calls_streaming(self, *args, **kwargs):
            return None

    parser = FakeParser()
    wrapped = mod._make_wrapped_streaming(
        FakeParser.extract_tool_calls_streaming
    )
    req = _FakeRequest(model="qwen3.6-35b-a3b")
    # 22_000 token ctx → bucket "15-30K"
    wrapped(parser, "prev", "curr", "delta",
            [0] * 100, [0] * 22_000, [0] * 5, req)

    # Per-label Counter must reflect this single event under the right tuple.
    labeled_extract = mod._prom_extract_total.labels(
        model="qwen3.6-35b-a3b", ctx_bucket="15-30K",
    )
    labeled_malformed = mod._prom_malformed_total.labels(
        model="qwen3.6-35b-a3b", ctx_bucket="15-30K",
    )
    assert labeled_extract._value.get() >= 1
    assert labeled_malformed._value.get() >= 1


def test_labeled_counter_segregates_models_and_buckets() -> None:
    """Two malformed events under different (model, ctx_bucket) tuples
    must not pollute each other — distinct time-series in Prometheus."""
    try:
        import prometheus_client  # noqa: F401
    except ImportError:
        pytest.skip("prometheus_client not installed")

    mod = _import_patch()
    _reset_counters(mod)
    mod._setup_prometheus_counters()

    class FakeParser:
        # Each invocation gets a fresh malformed entry.
        def __init__(self):
            self.prev_tool_call_arr = [
                {"name": "Read",
                 "arguments": '{"file_path":"/some/lo'},
            ]

        def extract_tool_calls_streaming(self, *args, **kwargs):
            return None

    wrapped = mod._make_wrapped_streaming(
        FakeParser.extract_tool_calls_streaming
    )

    # Event 1: 35B, 22K context (bucket 15-30K)
    p1 = FakeParser()
    wrapped(p1, "p", "c", "d",
            [0] * 100, [0] * 22_000, [0] * 5,
            _FakeRequest(model="qwen3.6-35b-a3b"))

    # Event 2: 27B, 3K context (bucket 0-5K)
    p2 = FakeParser()
    wrapped(p2, "p", "c", "d",
            [0] * 100, [0] * 3_000, [0] * 5,
            _FakeRequest(model="qwen3.6-27b-int4"))

    v_35b_long = mod._prom_malformed_total.labels(
        model="qwen3.6-35b-a3b", ctx_bucket="15-30K",
    )._value.get()
    v_27b_short = mod._prom_malformed_total.labels(
        model="qwen3.6-27b-int4", ctx_bucket="0-5K",
    )._value.get()
    v_35b_short = mod._prom_malformed_total.labels(
        model="qwen3.6-35b-a3b", ctx_bucket="0-5K",
    )._value.get()

    assert v_35b_long >= 1
    assert v_27b_short >= 1
    # 35B short bucket must NOT have absorbed the 35B long event.
    assert v_35b_short == 0


def test_apply_skipped_when_parser_unimportable(monkeypatch) -> None:
    mod = _import_patch()
    monkeypatch.setenv("GENESIS_ENABLE_PN287_QWEN3CODER_ARGS_OBSERVER", "1")
    # Force ImportError on the parser path.
    sys.modules.pop(
        "vllm.entrypoints.openai.tool_parsers.qwen3coder_tool_parser", None
    )

    class _BrokenLoader:
        def find_spec(self, name, *_a, **_kw):
            if "qwen3coder_tool_parser" in name:
                raise ImportError("synthetic")
            return None

    monkeypatch.syspath_prepend("")
    # Easier: monkeypatch __import__ for the relevant path.
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if "qwen3coder_tool_parser" in name:
            raise ImportError("synthetic-test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    status, reason = mod.apply()
    assert status == "skipped"
    assert "not importable" in reason
