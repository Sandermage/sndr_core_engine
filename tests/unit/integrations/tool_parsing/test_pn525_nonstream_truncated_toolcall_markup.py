# SPDX-License-Identifier: Apache-2.0
"""PN525 — drop incomplete tool-call markup in non-streaming (vllm#47562).

Contract pinned here (TDD, written before the implementation).

Upstream bug (vllm#47562, fixes issue #47137): in the shared
``DelegatingParser._extract_tool_calls`` (vllm/parser/abstract_parser.py)
the auto-tool-choice else-branch ("no complete tool calls") returns the
RAW ``content`` instead of the tool parser's cleaned
``tool_call_info.content``. When generation truncates inside a
``<tool_call>`` opener (max_tokens or a stop string), the non-streaming
path hands the client raw incomplete markup ("<tool_call>\\n<function")
while the streaming path correctly drops it — client-visible garbage +
stream/non-stream divergence on the path ALL our engine tool parsers
share (qwen3_xml on 35B/27B, gemma4 on the G4 lanes; tool calls are a
7/7-gated first-class capability per lane).

PN525 vendors the #47562 fix with Genesis-worded comments and a
byte-divergent code shape (``cleaned if cleaned else None`` instead of
upstream's ``tool_call_info.content or None``) so the PR's exact comment
head AND code line stay usable as SELF_COLLISION-safe drift markers.

Sub-contracts:
  1. One required sub-patch anchored on the 3-line else-branch
     (``else:`` + ``# No tool calls.`` + ``return None, content``) —
     byte-verified count==1 in pristine dev748 (2dfaae752, gh api;
     '# No tool calls.' count==1, fix ABSENT).
  2. The patched branch, executed as real Python, ports the #47562
     matrix: truncated-opener cases return None content (parity with
     streaming), content-before-opener is preserved, and the
     tool_call_info-is-None fallback returns raw content unchanged.
  3. The tools_called promotion branch is untouched (complete tool
     calls still promote — upstream's third test).
  4. Idempotent second apply; drift-marker self-skip on the merged
     form; gate-closed no-op; patched file compiles.
  5. Same-file hygiene: PN66/PN392 anchor parse_delta (disjoint
     function, grep-verified).
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("GENESIS_NO_PATCH_CACHE", "1")

from sndr.engines.vllm.patches.tool_parsing import (  # noqa: E402
    pn525_nonstream_truncated_toolcall_markup as overlay,
)

# ── Fixture: pin-form anchor region (byte-faithful, dev748 2dfaae752) ─

PIN_ABSTRACT_PARSER = (
    "# fake parser/abstract_parser.py (pin 2dfaae752 form)\n"
    "class DelegatingParser:\n"
    "    def _extract_tool_calls(self, content, request, is_auto_tool_choice):\n"
    "        tool_calls = []\n"
    "        if is_auto_tool_choice:\n"
    "            tool_call_info = self.extract_tool_calls(\n"
    '                content if content is not None else "",\n'
    "                request=request,\n"
    "            )\n"
    "            if tool_call_info is not None and tool_call_info.tools_called:\n"
    "                tool_calls.extend(tool_call_info.tool_calls)\n"
    "                content = tool_call_info.content\n"
    '                if content and content.strip() == "":\n'
    "                    content = None\n"
    "            else:\n"
    "                # No tool calls.\n"
    "                return None, content\n"
    "\n"
    "        return tool_calls, content\n"
)

# #47562 merged form (exact hunk from `gh pr diff 47562`, 2026-07-05).
MERGED_ABSTRACT_PARSER = PIN_ABSTRACT_PARSER.replace(
    "            else:\n"
    "                # No tool calls.\n"
    "                return None, content\n",
    "            else:\n"
    "                # No complete tool calls: return the tool parser's content,\n"
    "                # which drops incomplete tool-call markup (e.g. a\n"
    "                # <tool_call> opener truncated by max_tokens or a stop\n"
    "                # string), so the non-streaming path matches streaming.\n"
    "                if tool_call_info is not None:\n"
    "                    return None, tool_call_info.content or None\n"
    "                return None, content\n",
).replace("(pin 2dfaae752 form)", "(post-vllm#47562 merged form)")


def _install(tmp_path, monkeypatch, text):
    target = tmp_path / "abstract_parser.py"
    target.write_text(text, encoding="utf-8")
    monkeypatch.setattr(overlay, "resolve_vllm_file", lambda rel: str(target))
    monkeypatch.setattr(overlay, "vllm_install_root", lambda: str(tmp_path))
    from sndr import dispatcher
    monkeypatch.setattr(
        dispatcher, "should_apply", lambda pid: (True, "test override")
    )
    return target


def _run_extract(patched_source: str, *, raw_content, tool_call_info):
    """Execute the patched _extract_tool_calls against a stub parser —
    the #47562 behavior at the level executable without a vLLM install."""
    ns: dict = {}
    exec(  # noqa: S102 - test-only execution of the patched module text
        compile(patched_source, "<pn525-patched>", "exec"), ns
    )
    parser = ns["DelegatingParser"]()
    parser.extract_tool_calls = lambda content, request=None: tool_call_info
    return parser._extract_tool_calls(raw_content, None, True)


def _info(*, tools_called, content, tool_calls=()):
    return SimpleNamespace(
        tools_called=tools_called, content=content, tool_calls=list(tool_calls)
    )


class TestPatcherShape:
    def test_single_required_subpatch(self, tmp_path, monkeypatch):
        _install(tmp_path, monkeypatch, PIN_ABSTRACT_PARSER)
        patcher = overlay._make_patcher()
        assert patcher is not None
        by_name = {sp.name: sp for sp in patcher.sub_patches}
        assert set(by_name) == {"pn525_no_toolcall_cleaned_content"}
        assert by_name["pn525_no_toolcall_cleaned_content"].required is True

    def test_patcher_none_when_target_missing(self, monkeypatch):
        monkeypatch.setattr(overlay, "resolve_vllm_file", lambda rel: None)
        assert overlay._make_patcher() is None


class TestApply:
    def test_apply_rewrites_else_branch(self, tmp_path, monkeypatch):
        target = _install(tmp_path, monkeypatch, PIN_ABSTRACT_PARSER)
        status, reason = overlay.apply()
        assert status == "applied", reason
        out = target.read_text(encoding="utf-8")
        assert "tool_call_info is not None" in out
        # The raw-content fallback is preserved.
        assert out.count("return None, content") == 1
        compile(out, str(target), "exec")

    def test_second_apply_idempotent(self, tmp_path, monkeypatch):
        _install(tmp_path, monkeypatch, PIN_ABSTRACT_PARSER)
        first, first_reason = overlay.apply()
        assert first == "applied", first_reason
        second, second_reason = overlay.apply()
        assert second == "skipped"
        assert "already applied" in second_reason

    def test_self_skips_on_merged_form(self, tmp_path, monkeypatch):
        target = _install(tmp_path, monkeypatch, MERGED_ABSTRACT_PARSER)
        status, reason = overlay.apply()
        assert status == "skipped"
        assert "upstream" in reason.lower()
        assert target.read_text(encoding="utf-8") == MERGED_ABSTRACT_PARSER

    def test_apply_skips_when_gate_closed(self, tmp_path, monkeypatch):
        target = tmp_path / "abstract_parser.py"
        target.write_text(PIN_ABSTRACT_PARSER, encoding="utf-8")
        monkeypatch.setattr(overlay, "resolve_vllm_file", lambda rel: str(target))
        monkeypatch.setattr(overlay, "vllm_install_root", lambda: str(tmp_path))
        from sndr import dispatcher
        monkeypatch.setattr(
            dispatcher, "should_apply", lambda pid: (False, "gate closed")
        )
        status, _reason = overlay.apply()
        assert status == "skipped"
        assert target.read_text(encoding="utf-8") == PIN_ABSTRACT_PARSER


class TestPortedUpstreamMatrix:
    """Port of the #47562 TestTruncatedToolOpenerStreamParity cases at the
    executable-branch level: the parser's cleaned content (which drops the
    truncated opener) must reach the client in non-streaming too."""

    @pytest.fixture
    def patched(self, tmp_path, monkeypatch):
        target = _install(tmp_path, monkeypatch, PIN_ABSTRACT_PARSER)
        status, reason = overlay.apply()
        assert status == "applied", reason
        return target.read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "raw",
        [
            "<tool_call>",
            "<tool_call>\n",
            "<tool_call>\n<",
            "<tool_call>\n<function",
        ],
    )
    def test_truncated_opener_dropped(self, patched, raw):
        # The engine tool parser saw the opener, promoted nothing, and
        # cleaned the markup out of its content ('' here). Pre-patch the
        # client received `raw`; post-patch it must receive None.
        tool_calls, content = _run_extract(
            patched,
            raw_content=raw,
            tool_call_info=_info(tools_called=False, content=""),
        )
        assert tool_calls is None
        assert content is None

    def test_content_before_truncated_opener_preserved(self, patched):
        tool_calls, content = _run_extract(
            patched,
            raw_content="Checking the weather. <tool_call>\n<function",
            tool_call_info=_info(
                tools_called=False, content="Checking the weather. "
            ),
        )
        assert tool_calls is None
        assert content == "Checking the weather. "

    def test_no_info_falls_back_to_raw_content(self, patched):
        # Parser returned no result object at all — original behavior
        # (raw content passthrough) must be preserved byte-for-byte.
        tool_calls, content = _run_extract(
            patched,
            raw_content="plain answer",
            tool_call_info=None,
        )
        assert tool_calls is None
        assert content == "plain answer"

    def test_complete_tool_call_still_promoted(self, patched):
        # Upstream's sanity case: the tools_called branch is untouched.
        call = SimpleNamespace(name="get_weather")
        tool_calls, content = _run_extract(
            patched,
            raw_content="<tool_call>...</tool_call>",
            tool_call_info=_info(
                tools_called=True, content="", tool_calls=[call]
            ),
        )
        assert tool_calls == [call]
        # Upstream asserts `not content` (the tools_called branch maps a
        # whitespace-only content to None but passes '' through).
        assert not content


class TestDriftMarkers:
    def test_markers_not_substring_of_own_emitted_text(
        self, tmp_path, monkeypatch
    ):
        _install(tmp_path, monkeypatch, PIN_ABSTRACT_PARSER)
        patcher = overlay._make_patcher()
        for dm in patcher.upstream_drift_markers:
            if dm.startswith("[Genesis"):
                continue
            for sp in patcher.sub_patches:
                assert dm not in sp.replacement, (
                    f"drift marker {dm!r} collides with {sp.name} replacement "
                    "— would false-fire (PN369 class)"
                )

    def test_markers_fire_on_merged_form(self):
        non_banner = [
            dm for dm in overlay._DRIFT_MARKERS if not dm.startswith("[Genesis")
        ]
        assert non_banner
        assert any(dm in MERGED_ABSTRACT_PARSER for dm in non_banner)


class TestWiring:
    def test_registry_entry(self):
        from sndr.dispatcher.registry import PATCH_REGISTRY
        body = PATCH_REGISTRY["PN525"]
        assert body["family"] == "tool_parsing"
        assert body["env_flag"] == (
            "GENESIS_ENABLE_PN525_NONSTREAM_TOOLCALL_MARKUP_DROP"
        )
        # Client-visible corruption on the shared path every tool lane
        # uses -> default_on (work-order verdict).
        assert body["default_on"] is True
        assert body["upstream_pr"] == 47562
        assert body["upstream_issue"] == 47137
        assert body["upstream_pr_relationship"] == "backport"
        assert body["apply_module"] == (
            "sndr.engines.vllm.patches.tool_parsing."
            "pn525_nonstream_truncated_toolcall_markup"
        )

    def test_env_flag_attribute(self):
        from sndr.env import Flags
        assert (
            Flags.PN525_NONSTREAM_TOOLCALL_MARKUP_DROP
            == "PN525_NONSTREAM_TOOLCALL_MARKUP_DROP"
        )


# TestPristinePinInvariants RETIRED (audit #14 full drain, 2026-07-06): it
# byte-checked the anchor against the macOS-only pristine candidate-pin
# tree — empty on CI, absent on the Linux rig — so it executed on NO host
# (permanent green-by-skip). PN525 is
# not recorded in the committed anchor_sot manifest (90/329 gap, audit
# #6/#21), so the byte-check cannot be migrated onto it. The anchor +
# ported-upstream-matrix + drift-marker + wiring contracts stay covered in CI
# by the synthetic classes above.
