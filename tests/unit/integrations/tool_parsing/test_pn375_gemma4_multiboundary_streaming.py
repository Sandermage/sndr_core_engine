# SPDX-License-Identifier: Apache-2.0
"""TDD for PN375 — Gemma4 multi-boundary streaming deltas (vllm#44741).

Upstream issue #41967: under MTP/speculative decoding a single streamed
delta can cross multiple tool-call boundaries (e.g. close one call AND
start the next in the same delta). The pristine pin parser
(`vllm/tool_parsers/gemma4_tool_parser.py`, state-machine variant with
`buffered_delta_text`) selects ONE branch per delta, so argument
fragments on the far side of the boundary are silently dropped — the
first/next tool call loses arguments.

Upstream PR #44741 (OPEN, fetched via `gh pr diff` 2026-06-11) adds
`_extract_streaming_delta_segments`: split a multi-boundary delta on
the tool-call delimiter tokens, replay the delimiter-aligned segments
through the existing `_extract_streaming`, and merge the resulting
DeltaMessages.

PN375 vendors that design as a runtime hook (monkey-patch) with one
CRITICAL Genesis adaptation (roadmap chunk-5 Theme A caveat): the
G4_14 pad-token set (<pad>/<eos>/<bos>/turn boundaries/<unk>) is
stripped from `current_text` AND `delta_text` BEFORE the PR's
consistency check. Without that, any pad-token asymmetry introduced by
the G4_14 wrapper (or by the pads themselves landing inside a
multi-boundary delta) makes `current_text.endswith(delta_text)` fail →
permanent silent fallback to the single-pass path → the fix never
engages exactly when MTP emits pads.

Harness: the REAL pristine class source is exec'd with stub protocol
classes (exec-patched-text technique, PN373 pattern) — skipped when
the candidate pin tree is not extracted on this host.
"""
from __future__ import annotations

import ast
import json
import os

import pytest

PRISTINE_GEMMA4_PARSER = (
    "/private/tmp/candidate_pin_current/vllm/tool_parsers/gemma4_tool_parser.py"
)

requires_pristine = pytest.mark.skipif(
    not os.path.isfile(PRISTINE_GEMMA4_PARSER),
    reason="pristine candidate pin tree not extracted on this host",
)


def _wiring():
    from sndr.engines.vllm.patches.tool_parsing import (
        pn375_gemma4_multiboundary_streaming as M,
    )
    return M


# ─── stub protocol classes (duck-typed mirrors of vllm protocol) ──────────


class _DeltaFunctionCall:
    def __init__(self, name=None, arguments=None):
        self.name = name
        self.arguments = arguments

    def model_dump(self, exclude_none=False):
        data = {"name": self.name, "arguments": self.arguments}
        if exclude_none:
            data = {k: v for k, v in data.items() if v is not None}
        return data


class _DeltaToolCall:
    def __init__(self, index=None, type=None, id=None, function=None):
        self.index = index
        self.type = type
        self.id = id
        self.function = function


class _DeltaMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls if tool_calls is not None else []


class _StubBase:
    """Stand-in for vllm ToolParser base."""

    def __init__(self, tokenizer, tools=None):
        self.model_tokenizer = tokenizer
        self.tools = tools

    @property
    def vocab(self):
        return self.model_tokenizer.get_vocab()

    def adjust_request(self, request):
        return request


class _StubTokenizer:
    def get_vocab(self):
        return {"<|tool_call>": 7, "<tool_call|>": 8}


class _StubLogger:
    def debug(self, *a, **k):
        pass

    warning = info = error = exception = debug


def _find_common_prefix(a: str, b: str) -> str:
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    return a[:i]


_WANTED_FUNCS = {"_parse_gemma4_value", "_parse_gemma4_args", "_parse_gemma4_array"}
_WANTED_CONSTS = {"STRING_DELIM", "TOOL_CALL_START", "TOOL_CALL_END"}


def _build_parser_class():
    """Exec the pristine Gemma4ToolParser with stub protocol objects."""
    import re

    source = open(PRISTINE_GEMMA4_PARSER, encoding="utf-8").read()
    tree = ast.parse(source, filename=PRISTINE_GEMMA4_PARSER)
    selected: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in _WANTED_FUNCS:
            selected.append(node)
        elif isinstance(node, ast.ClassDef) and node.name == "Gemma4ToolParser":
            selected.append(node)
        elif isinstance(node, ast.Assign):
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if names & _WANTED_CONSTS:
                selected.append(node)
    assert any(isinstance(n, ast.ClassDef) for n in selected), (
        "pristine file drifted: Gemma4ToolParser class not found"
    )
    module = ast.Module(body=selected, type_ignores=[])
    namespace: dict = {
        "json": json,
        "re": re,
        "logger": _StubLogger(),
        "make_tool_call_id": lambda: "chatcmpl-tool-test",
        "find_common_prefix": _find_common_prefix,
        "ToolParser": _StubBase,
        "Tool": object,
        "TokenizerLike": object,
        "ChatCompletionRequest": type("ChatCompletionRequest", (), {}),
        "ResponsesRequest": type("ResponsesRequest", (), {}),
        "DeltaFunctionCall": _DeltaFunctionCall,
        "DeltaMessage": _DeltaMessage,
        "DeltaToolCall": _DeltaToolCall,
        "ExtractedToolCallInformation": type(
            "ExtractedToolCallInformation", (), {}
        ),
        "FunctionCall": type("FunctionCall", (), {}),
        "ToolCall": type("ToolCall", (), {}),
        "Sequence": object,
    }
    exec(  # noqa: S102
        compile(module, PRISTINE_GEMMA4_PARSER, "exec"), namespace
    )
    return namespace["Gemma4ToolParser"]


def _fresh_parser(install: bool = True):
    cls = _build_parser_class()
    if install:
        M = _wiring()
        bound, reason = M.install_on_class(cls)
        assert bound, reason
    return cls(_StubTokenizer())


def _simulate_streaming(parser, chunks):
    results = []
    previous_text = ""
    for chunk in chunks:
        current_text = previous_text + chunk
        delta = parser.extract_tool_calls_streaming(
            previous_text, current_text, chunk, [], [], [], None
        )
        results.append(delta)
        previous_text = current_text
    return results


def _fn_get(fn, key):
    if fn is None:
        return None
    if isinstance(fn, dict):
        return fn.get(key)
    return getattr(fn, key, None)


def _collect_args_by_index(results):
    out: dict[int, str] = {}
    for delta in results:
        if delta is not None and delta.tool_calls:
            for tc in delta.tool_calls:
                arg = _fn_get(tc.function, "arguments")
                if arg:
                    out[tc.index] = out.get(tc.index, "") + arg
    return out


def _collect_content(results):
    return "".join(
        delta.content for delta in results if delta is not None and delta.content
    )


# ─── upstream PR #44741 regression matrix (ported) ─────────────────────────


@requires_pristine
@pytest.mark.parametrize(
    ("chunks", "crossing_result_index", "expected_args_by_index"),
    [
        (
            [
                "<|tool_call>",
                "call:getStationInfo{",
                (
                    'location:<|"|>Milano<|"|>}'
                    "<tool_call|><|tool_call>call:getStationInfo{"
                ),
                'location:<|"|>Piacenza<|"|>}',
                "<tool_call|>",
            ],
            2,
            {0: {"location": "Milano"}, 1: {"location": "Piacenza"}},
        ),
        (
            [
                "<|tool_call>",
                "call:first{x:1",
                "}<tool_call|><|tool_call>call:second{y:2}<tool_call|>",
            ],
            2,
            {0: {"x": 1}, 1: {"y": 2}},
        ),
        (
            [
                (
                    "<|tool_call>call:first{x:1}<tool_call|>"
                    "<|tool_call>call:second{y:2}<tool_call|>"
                ),
            ],
            0,
            {0: {"x": 1}, 1: {"y": 2}},
        ),
    ],
)
def test_streaming_mtp_chunk_with_multiple_tool_boundaries(
    chunks, crossing_result_index, expected_args_by_index
):
    """A speculative/MTP-sized delta can include multiple boundaries."""
    parser = _fresh_parser()
    results = _simulate_streaming(parser, chunks)
    crossing_delta = results[crossing_result_index]
    assert crossing_delta is not None
    assert {tc.index for tc in crossing_delta.tool_calls} == {0, 1}

    args_by_index = _collect_args_by_index(results)
    assert set(args_by_index) == set(expected_args_by_index)
    for index, expected_args in expected_args_by_index.items():
        assert json.loads(args_by_index[index]) == expected_args


@requires_pristine
def test_streaming_mtp_chunk_merges_same_index_argument_segments():
    """Segment replay must not emit duplicate index entries per chunk."""
    parser = _fresh_parser()
    chunks = [
        "<|tool_call>",
        "call:write_file{",
        'path:<|"|>src/main.rs<|"|>}<tool_call|>',
    ]
    results = _simulate_streaming(parser, chunks)
    for delta in results:
        if delta is not None and delta.tool_calls:
            indexes = [tc.index for tc in delta.tool_calls]
            assert len(indexes) == len(set(indexes))

    args_by_index = _collect_args_by_index(results)
    assert set(args_by_index) == {0}
    assert json.loads(args_by_index[0]) == {"path": "src/main.rs"}


@requires_pristine
def test_streaming_mtp_chunk_crossing_buffered_tool_call_boundary():
    """Segment replay must still run when buffering completes a delimiter."""
    parser = _fresh_parser()
    chunks = [
        "<|tool_call>",
        "call:getStationInfo{",
        'location:<|"|>Milano<|"|>}<',
        'tool_call|><|tool_call>call:getStationInfo{location:<|"|>Piacenza<|"|>}<',
        "tool_call|>",
    ]
    results = _simulate_streaming(parser, chunks)
    args_by_index = _collect_args_by_index(results)

    assert set(args_by_index) == {0, 1}
    assert json.loads(args_by_index[0]) == {"location": "Milano"}
    assert json.loads(args_by_index[1]) == {"location": "Piacenza"}


@requires_pristine
def test_single_boundary_path_unchanged():
    """Ordinary deltas keep using the pristine single-pass path."""
    parser = _fresh_parser()
    chunks = [
        "<|tool_call>",
        "call:get_weather{",
        'location:<|"|>Paris',
        ', France<|"|>}',
        "<tool_call|>",
    ]
    results = _simulate_streaming(parser, chunks)
    args_by_index = _collect_args_by_index(results)
    assert json.loads(args_by_index[0]) == {"location": "Paris, France"}


# ─── pristine bug reproduction (retire detector) ───────────────────────────


@requires_pristine
def test_pristine_parser_loses_args_on_multiboundary_delta():
    """Documents the #41967 failure on the UNPATCHED pin parser.

    If this starts failing after a pin bump, upstream merged #44741 (or
    an equivalent) and PN375 is retire-eligible — deep-diff first (iron
    rule #11).
    """
    parser = _fresh_parser(install=False)
    chunks = [
        "<|tool_call>",
        "call:first{x:1",
        "}<tool_call|><|tool_call>call:second{y:2}<tool_call|>",
    ]
    results = _simulate_streaming(parser, chunks)
    args_by_index = _collect_args_by_index(results)
    parsed = {
        idx: json.loads(args) if args else None
        for idx, args in args_by_index.items()
    }
    assert parsed != {0: {"x": 1}, 1: {"y": 2}}, (
        "pristine pin parser handled the multi-boundary delta — upstream "
        "fix likely merged; PN375 retire candidate"
    )


# ─── G4_14 pad-token combined regression (roadmap caveat) ─────────────────


def _g4_14_style_wrapper(cls):
    """Replicate G4_14's streaming wrapper: strip the control-token set
    from the FIRST positional argument (previous_text in this pin's
    signature) before delegating."""
    from sndr.engines.vllm.patches.model_compat.gemma4 import (
        g4_14_gemma4_tool_call_parser_pad_token as g4_14,
    )

    original = cls.extract_tool_calls_streaming

    def _wrapped(self, first_text, *args, **kwargs):
        stripped = (
            g4_14._strip_control_tokens(first_text)
            if isinstance(first_text, str)
            else first_text
        )
        return original(self, stripped, *args, **kwargs)

    cls.extract_tool_calls_streaming = _wrapped
    return cls


@requires_pristine
def test_combined_multiboundary_pad_g4_14_active():
    """Roadmap regression: multi-boundary + <pad> + G4_14 active (MTP
    chunks). Both tool calls must arrive complete and no pad token may
    leak into content or arguments."""
    cls = _build_parser_class()
    M = _wiring()
    bound, reason = M.install_on_class(cls)
    assert bound, reason
    _g4_14_style_wrapper(cls)
    parser = cls(_StubTokenizer())

    chunks = [
        "<|tool_call>",
        "call:first{x:1",
        "}<tool_call|><pad><|tool_call>call:second{y:2}<tool_call|><eos>",
    ]
    results = _simulate_streaming(parser, chunks)
    args_by_index = _collect_args_by_index(results)
    assert set(args_by_index) == {0, 1}
    assert json.loads(args_by_index[0]) == {"x": 1}
    assert json.loads(args_by_index[1]) == {"y": 2}

    content = _collect_content(results)
    assert "<pad>" not in content
    assert "<eos>" not in content
    for args in args_by_index.values():
        assert "<pad>" not in args


@requires_pristine
def test_pad_asymmetry_does_not_disable_segment_replay():
    """The CRITICAL caveat: if a wrapper (G4_14 class) strips pads from
    current_text while delta_text still carries them, the PR #44741
    consistency check `current_text.endswith(delta_text)` fails and the
    fix silently degrades to the single-pass path. PN375 strips the
    G4_14 pad set from BOTH before the check, so the replay must still
    engage and deliver both tool calls in the crossing delta."""
    parser = _fresh_parser()
    # Seed the parser state through the normal streaming path first.
    _simulate_streaming(parser, ["<|tool_call>", "call:first{x:1"])

    previous_text = "<|tool_call>call:first{x:1"
    delta_raw = "}<tool_call|><pad><|tool_call>call:second{y:2}<tool_call|>"
    # current_text as a pad-stripping wrapper would hand it over (pads
    # removed), while the delta still carries the pad.
    current_stripped = (previous_text + delta_raw).replace("<pad>", "")

    delta = parser._extract_streaming(
        previous_text=previous_text,
        current_text=current_stripped,
        delta_text=delta_raw,
    )
    assert delta is not None
    indices = {tc.index for tc in delta.tool_calls}
    assert indices == {0, 1}, (
        "segment replay fell back to the single-pass path — pad "
        "asymmetry silently disabled the #44741 fix"
    )


# ─── variant self-skip + lifecycle ─────────────────────────────────────────


def test_install_skips_v2_overlay_variant():
    """The G4_T1 v2 overlay (accumulated-text rescan, PR #42237) is
    structurally immune — PN375 must self-skip on its signature."""
    M = _wiring()

    class _V2Like:
        def extract_tool_calls_streaming(self, *a, **k):
            return None

        def _extract_streaming(self, current_text):
            return None

    bound, reason = M.install_on_class(_V2Like)
    assert not bound
    assert "variant" in reason or "signature" in reason


def test_install_skips_class_without_extract_streaming():
    M = _wiring()

    class _Alien:
        pass

    bound, reason = M.install_on_class(_Alien)
    assert not bound


@requires_pristine
def test_install_idempotent():
    M = _wiring()
    cls = _build_parser_class()
    bound1, _ = M.install_on_class(cls)
    bound2, reason2 = M.install_on_class(cls)
    assert bound1 and bound2
    assert "idempotent" in reason2
    # No recursive wrapping: the attached segments method must reference
    # the ORIGINAL _extract_streaming, not itself.
    parser = cls(_StubTokenizer())
    results = _simulate_streaming(
        parser,
        ["<|tool_call>call:first{x:1}<tool_call|>"
         "<|tool_call>call:second{y:2}<tool_call|>"],
    )
    args_by_index = _collect_args_by_index(results)
    assert json.loads(args_by_index[0]) == {"x": 1}
    assert json.loads(args_by_index[1]) == {"y": 2}


def test_apply_env_flag_default_off(monkeypatch):
    M = _wiring()
    monkeypatch.delenv(M.ENV_FLAG_FULL, raising=False)
    monkeypatch.delenv(
        M.ENV_FLAG_FULL.replace("GENESIS_", "SNDR_"), raising=False
    )
    status, reason = M.apply()
    assert status == "skipped"
    assert M.ENV_FLAG_FULL in reason


def test_apply_no_vllm_skips(monkeypatch):
    M = _wiring()
    monkeypatch.setenv(M.ENV_FLAG_FULL, "1")
    monkeypatch.setattr(M, "_find_gemma4_parser_class", lambda: None)
    status, reason = M.apply()
    assert status == "skipped"
    assert "no gemma4" in reason.lower() or "not found" in reason.lower()
