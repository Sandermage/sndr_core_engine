# SPDX-License-Identifier: Apache-2.0
"""TDD for PN373 — parallel_tool_calls null != false (vendor of vllm#44955).

Upstream bug (vllm#44948): ``ChatCompletionRequest.parallel_tool_calls``
is declared ``bool | None = True`` (pristine
``entrypoints/openai/chat_completion/protocol.py:233``), so a client
sending an explicit JSON ``null`` (LiteLLM, n8n) arrives at
``maybe_filter_parallel_tool_calls`` as ``None``. The pristine
truthiness check ``if request.parallel_tool_calls:`` treats ``None``
like ``False`` and silently trims multi-tool responses to a single
call. The documented default is ``True`` — explicit ``null`` must
behave like the default. Fix: ``is not False``.

Test strategy:
  1. Anchor byte-verification against the pristine candidate tree
     (/private/tmp/candidate_pin_current) — count==1.
  2. Behavior tests exec'ing the real file content with stub protocol
     classes — including the STREAMING-DELTA case upstream's PR lacks
     (roadmap: a null client value must NOT truncate multi-tool-calls
     in the streaming delta path).
  3. Pristine bug reproduction — proves the harness detects the bug;
     if this starts failing after a pin bump, upstream merged #44955
     and PN373 is retire-eligible.
  4. TextPatcher integration on a temp tree: APPLIED → IDEMPOTENT →
     upstream-merged SKIP.
  5. Self-collision lint mirror (tools/lint_drift_markers.py contract):
     drift markers must not be substrings of our own emitted text.
"""
from __future__ import annotations

import ast
import os
import sys
import types
from types import SimpleNamespace

import pytest


PRISTINE_TOOL_CALLS_UTILS = (
    "/private/tmp/candidate_pin_current/vllm/entrypoints/serve/utils/"
    "tool_calls_utils.py"
)

requires_pristine = pytest.mark.skipif(
    not os.path.isfile(PRISTINE_TOOL_CALLS_UTILS),
    reason="pristine candidate pin tree not extracted on this host",
)

# Post-image of vllm#44955 (gh pr diff 44955, fetched 2026-06-11) — the
# docstring line as it will read once the PR merges. The drift marker
# must be a substring of THIS text (so the patch self-skips when the
# fix lands upstream) while NOT being a substring of anything PN373
# itself writes (self-collision lint).
UPSTREAM_44955_MERGED_DOCSTRING = (
    '    """Filter to first tool call only when parallel_tool_calls is '
    'explicitly False."""\n'
)
UPSTREAM_44955_MERGED_CONDITION = (
    "    if request.parallel_tool_calls is not False:\n"
)


def _pn373():
    from sndr.engines.vllm.patches.serving import (
        pn373_parallel_toolcalls_null as M,
    )
    return M


def _pristine_src() -> str:
    with open(PRISTINE_TOOL_CALLS_UTILS) as f:
        return f.read()


def _patched_src() -> str:
    M = _pn373()
    src = _pristine_src()
    assert M.PN373_OLD in src
    return src.replace(M.PN373_OLD, M.PN373_NEW)


# ─── Stub-protocol exec harness ───────────────────────────────────────
#
# tool_calls_utils.py imports three protocol classes from
# vllm.entrypoints.openai.chat_completion.protocol. vllm is not
# importable on the dev host (and we must not depend on it), so the
# import chain is satisfied with stub modules registered in
# sys.modules for the duration of the exec, then restored.

_PROTO_CHAIN = (
    "vllm",
    "vllm.entrypoints",
    "vllm.entrypoints.openai",
    "vllm.entrypoints.openai.chat_completion",
    "vllm.entrypoints.openai.chat_completion.protocol",
)


class _StubChatCompletionRequest:
    def __init__(self, parallel_tool_calls):
        self.parallel_tool_calls = parallel_tool_calls


class _StubChatCompletionResponseChoice:
    def __init__(self, message):
        self.message = message


class _StubChatCompletionResponseStreamChoice:
    def __init__(self, delta):
        self.delta = delta


def _exec_tool_calls_utils(src: str) -> dict:
    """Exec tool_calls_utils.py source against stub protocol classes;
    returns the resulting namespace (function + classes)."""
    saved = {name: sys.modules.get(name) for name in _PROTO_CHAIN}
    try:
        parent = None
        for name in _PROTO_CHAIN:
            mod = types.ModuleType(name)
            mod.__path__ = []  # mark as package so submodule import works
            sys.modules[name] = mod
            if parent is not None:
                setattr(parent, name.rsplit(".", 1)[1], mod)
            parent = mod
        proto = sys.modules[_PROTO_CHAIN[-1]]
        proto.ChatCompletionRequest = _StubChatCompletionRequest
        proto.ChatCompletionResponseChoice = _StubChatCompletionResponseChoice
        proto.ChatCompletionResponseStreamChoice = (
            _StubChatCompletionResponseStreamChoice
        )
        ns: dict = {}
        exec(compile(src, "tool_calls_utils_under_test.py", "exec"), ns)
        return ns
    finally:
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


def _two_call_stream_choice():
    """A streaming choice carrying deltas for TWO tool calls (index 0+1)."""
    delta = SimpleNamespace(tool_calls=[
        SimpleNamespace(index=0, id="call_0"),
        SimpleNamespace(index=1, id="call_1"),
    ])
    return _StubChatCompletionResponseStreamChoice(delta)


def _two_call_full_choice():
    message = SimpleNamespace(tool_calls=[
        SimpleNamespace(id="call_0"),
        SimpleNamespace(id="call_1"),
    ])
    return _StubChatCompletionResponseChoice(message)


# ─── 1. Anchor byte-verification (iron rule #11) ──────────────────────


@requires_pristine
class TestAnchorAgainstPristine:
    def test_anchor_count_exactly_one(self):
        M = _pn373()
        assert _pristine_src().count(M.PN373_OLD) == 1

    def test_replacement_absent_from_pristine(self):
        M = _pn373()
        assert M.PN373_NEW not in _pristine_src()

    def test_drift_markers_absent_from_pristine(self):
        """Markers must fire only on the post-#44955 merged form —
        present in pristine means the marker can never gate anything."""
        M = _pn373()
        src = _pristine_src()
        for marker in M._DRIFT_MARKERS:
            assert marker not in src

    def test_patched_source_is_valid_python(self):
        ast.parse(_patched_src())


# ─── 2. Pristine bug reproduction (upstream #44948) ───────────────────


@requires_pristine
class TestPristineBugReproduction:
    """Documents the bug PN373 fixes. If these start FAILING after a
    pin bump, upstream merged #44955 — PN373 is retire-eligible."""

    def test_null_truncates_streaming_deltas_on_pristine(self):
        ns = _exec_tool_calls_utils(_pristine_src())
        choice = _two_call_stream_choice()
        request = _StubChatCompletionRequest(parallel_tool_calls=None)
        out = ns["maybe_filter_parallel_tool_calls"](choice, request)
        assert [tc.id for tc in out.delta.tool_calls] == ["call_0"]

    def test_null_truncates_full_response_on_pristine(self):
        ns = _exec_tool_calls_utils(_pristine_src())
        choice = _two_call_full_choice()
        request = _StubChatCompletionRequest(parallel_tool_calls=None)
        out = ns["maybe_filter_parallel_tool_calls"](choice, request)
        assert [tc.id for tc in out.message.tool_calls] == ["call_0"]


# ─── 3. Patched semantics (the unit tests upstream #44955 lacks) ──────


@requires_pristine
class TestPatchedSemantics:
    def test_null_keeps_all_streaming_deltas(self):
        """THE roadmap-mandated test: an explicit-null client value
        (None) must NOT truncate multi-tool-call streaming deltas."""
        ns = _exec_tool_calls_utils(_patched_src())
        choice = _two_call_stream_choice()
        request = _StubChatCompletionRequest(parallel_tool_calls=None)
        out = ns["maybe_filter_parallel_tool_calls"](choice, request)
        assert [tc.id for tc in out.delta.tool_calls] == ["call_0", "call_1"]

    def test_null_keeps_all_full_response_tool_calls(self):
        ns = _exec_tool_calls_utils(_patched_src())
        choice = _two_call_full_choice()
        request = _StubChatCompletionRequest(parallel_tool_calls=None)
        out = ns["maybe_filter_parallel_tool_calls"](choice, request)
        assert [tc.id for tc in out.message.tool_calls] == ["call_0", "call_1"]

    def test_true_keeps_all_streaming_deltas(self):
        ns = _exec_tool_calls_utils(_patched_src())
        choice = _two_call_stream_choice()
        request = _StubChatCompletionRequest(parallel_tool_calls=True)
        out = ns["maybe_filter_parallel_tool_calls"](choice, request)
        assert [tc.id for tc in out.delta.tool_calls] == ["call_0", "call_1"]

    def test_explicit_false_still_trims_streaming_deltas(self):
        """Behavior preservation: the only documented trim trigger."""
        ns = _exec_tool_calls_utils(_patched_src())
        choice = _two_call_stream_choice()
        request = _StubChatCompletionRequest(parallel_tool_calls=False)
        out = ns["maybe_filter_parallel_tool_calls"](choice, request)
        assert [tc.id for tc in out.delta.tool_calls] == ["call_0"]

    def test_explicit_false_still_trims_full_response(self):
        ns = _exec_tool_calls_utils(_patched_src())
        choice = _two_call_full_choice()
        request = _StubChatCompletionRequest(parallel_tool_calls=False)
        out = ns["maybe_filter_parallel_tool_calls"](choice, request)
        assert [tc.id for tc in out.message.tool_calls] == ["call_0"]


# ─── 4. TextPatcher integration on a temp tree ────────────────────────


@requires_pristine
class TestTextPatcherIntegration:
    @pytest.fixture()
    def temp_tree(self, tmp_path, monkeypatch):
        """A writable copy of the pristine target inside a synthetic
        vllm root; guards.vllm_install_root redirected at it."""
        monkeypatch.setenv("GENESIS_NO_PATCH_CACHE", "1")
        target = tmp_path / "entrypoints" / "serve" / "utils"
        target.mkdir(parents=True)
        (target / "tool_calls_utils.py").write_text(_pristine_src())
        import sndr.engines.vllm.detection.guards as guards
        monkeypatch.setattr(
            guards, "vllm_install_root", lambda: str(tmp_path)
        )
        return tmp_path

    def _target(self, tree):
        return tree / "entrypoints" / "serve" / "utils" / "tool_calls_utils.py"

    def test_apply_then_idempotent(self, temp_tree):
        M = _pn373()
        status, reason = M.apply()
        assert status == "applied", reason
        content = self._target(temp_tree).read_text()
        assert M.GENESIS_PN373_MARKER in content
        assert "if request.parallel_tool_calls is not False:" in content
        assert M.PN373_OLD not in content
        ast.parse(content)
        assert M.is_applied() is True
        # Second run must be a marker-idempotent skip, not a re-patch.
        status2, reason2 = M.apply()
        assert status2 == "skipped"
        assert "already applied" in reason2

    def test_upstream_merged_form_skips(self, temp_tree):
        """Simulate the post-#44955 tree (next pin bump): PN373 must
        self-skip via its drift marker, not fail on anchor drift."""
        M = _pn373()
        merged = _pristine_src().replace(
            '    """Filter to first tool call only when '
            'parallel_tool_calls is False."""\n',
            UPSTREAM_44955_MERGED_DOCSTRING,
        ).replace(
            "    if request.parallel_tool_calls:\n",
            UPSTREAM_44955_MERGED_CONDITION,
        )
        assert merged != _pristine_src()
        self._target(temp_tree).write_text(merged)
        status, reason = M.apply()
        assert status == "skipped"
        assert "upstream_merged" in reason

    def test_missing_target_skips(self, temp_tree):
        M = _pn373()
        self._target(temp_tree).unlink()
        status, reason = M.apply()
        assert status == "skipped"
        assert M.is_applied() is False


# ─── 5. Drift-marker hygiene (lint_drift_markers.py mirror) ───────────


class TestDriftMarkerHygiene:
    def test_markers_not_in_own_replacement(self):
        """Self-collision class (PN369 false-skip): a marker the patch
        itself emits would read as 'upstream merged' on next boot."""
        M = _pn373()
        for marker in M._DRIFT_MARKERS:
            assert marker not in M.PN373_NEW

    def test_markers_not_in_idempotency_marker_line(self):
        M = _pn373()
        marker_line = f"# [Genesis wiring marker: {M.GENESIS_PN373_MARKER}]\n"
        for marker in M._DRIFT_MARKERS:
            assert marker not in marker_line

    def test_markers_fire_on_upstream_merged_form(self):
        """Each marker must be a substring of #44955's post-image so the
        skip actually triggers when the fix lands."""
        M = _pn373()
        merged_text = (
            UPSTREAM_44955_MERGED_DOCSTRING + UPSTREAM_44955_MERGED_CONDITION
        )
        for marker in M._DRIFT_MARKERS:
            assert marker in merged_text

    def test_anchor_not_substring_of_replacement(self):
        """A replacement containing its own anchor would double-patch
        on a marker-less re-apply."""
        M = _pn373()
        assert M.PN373_OLD not in M.PN373_NEW

    def test_module_references_env_flag(self):
        """Family-contract invariant: registry env_flag referenced in
        the module source."""
        import inspect
        M = _pn373()
        src = inspect.getsource(M)
        assert "GENESIS_ENABLE_PN373_PARALLEL_TOOLCALLS_NULL" in src
