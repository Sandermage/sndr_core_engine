# SPDX-License-Identifier: Apache-2.0
"""PN386 — required-tool streaming brace JSON-string-awareness (vendor of vllm#45389).

Contract pinned here (TDD, written before the implementation):
  1. Patcher carries THREE required sub-patches on
     ``tool_parsers/streaming.py``:
       a. ``_bracket_level`` -> ``_bracket_level_state`` (string/escape
          tracking) + a thin ``_bracket_level`` wrapper.
       b. ``filter_delta_text`` seeds string/escape state from
          ``_bracket_level_state(previous_text)`` and carries it through
          the char loop (braces inside string values are NOT counted).
       c. ``filter_delta_text`` only breaks on a top-level ``,`` when
          ``not in_string``.
       d. The param-extraction site uses the substring's PREFIX as the
          ``filter_delta_text`` context, not ``previous_text``.
  2. apply() on the pin-form (g303916e93) installs all three and the
     module still compiles + the patched helper round-trips brace/quote/
     backslash payloads through ``json.loads`` (the upstream regression).
  3. Second apply() is idempotent (marker short-circuit).
  4. apply() on #45389's merged form self-skips via drift markers
     (reason: upstream_merged) without touching the file.
  5. Drift markers do not collide with PN386's own replacement text or
     its wiring marker line (tools/lint_drift_markers.py contract) AND
     at least one marker is an exact substring of the merged form.
  6. Anchors are unique and drift markers absent in the pristine pin
     tree (opportunistic — skipped when the pin tree is not present).
  7. The module documents the P68 prerequisite relationship and the
     sibling #45310 (Hermes boundary) pairing, and references the
     registry env flag
     GENESIS_ENABLE_PN386_REQUIRED_STREAMING_STRING_AWARE.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

# Unit tests patch fresh tmp files; the Layer-0 apply cache must never
# satisfy apply() from a previous run's state (same as PN378's tests).
os.environ.setdefault("GENESIS_NO_PATCH_CACHE", "1")

from sndr.engines.vllm.patches.tool_parsing import (  # noqa: E402
    pn386_required_streaming_brace_string_aware as m,
)

# ── Fake target ──────────────────────────────────────────────────────
# Pin-form (g303916e93): a byte-faithful copy of the anchor regions of
# vllm/tool_parsers/streaming.py. The fixture is assembled FROM the
# module's own anchor constants so each anchor is guaranteed to byte-
# match exactly what the patcher searches for (the param-extraction
# anchor carries its real 16-space nesting indent, so it is wrapped in
# a deep `if`-block to stay valid Python while keeping the bytes
# identical). A top-level `_param_extract_site` exposes the patched
# param block for the behavioral test. `import re` (stdlib) stands in
# for the real `import regex as re` so the fixture runs locally without
# the `regex` package; PN386 touches none of the regex-only features.

PIN_STREAMING = (
    "# fake vllm/tool_parsers/streaming.py (pin g303916e93 form)\n"
    "import re\n"
    "\n"
    "\n"
    + m.PN386_BRACKET_OLD
    + "\n"
    "\n"
    "def filter_delta_text(\n"
    "    delta_text: str,\n"
    "    previous_text: str,\n"
    ") -> tuple[str, bool]:\n"
    '    """Trim trailing tool-list delimiters from required-tool streaming text."""\n'
    + m.PN386_FILTER_OLD
    + "            passed_zero = bracket_level == 0\n"
    '        elif char == "}":\n'
    "            bracket_level -= 1\n"
    "            passed_zero = bracket_level == 0\n"
    "\n"
    + m.PN386_BREAK_OLD
    + "    return updated_delta, passed_zero\n"
    "\n"
    "\n"
    "def _param_extract_site(current_text, previous_text):\n"
    "    # Mirror of extract_required_tool_call_streaming's param block.\n"
    "    # The real anchor lives at 16-space indent (deep inside the\n"
    "    # function); reproduce that nesting verbatim so the patcher\n"
    "    # anchor byte-matches, then return the trimmed arguments.\n"
    "    if True:\n"
    "        if True:\n"
    "            if True:\n"
    + m.PN386_PARAM_OLD
    + "    return arguments\n"
)

# #45389 merged form — the upstream PR's exact structural lines. PN386
# must self-skip on this. Both drift markers (the spaced param-prefix
# slice and the `level, _, _ = _bracket_level_state(...)` thin-wrapper
# body) are spliced in so the patcher's Layer-3 self-skip fires.
MERGED_STREAMING = (
    PIN_STREAMING.replace(
        "    bracket_level = _bracket_level(previous_text)\n",
        "    bracket_level, in_string, escaped = _bracket_level_state("
        "previous_text)\n",
    )
    .replace(
        '            if char == ",":\n                break\n',
        '            if not in_string and char == ",":\n                break\n',
    )
    # Splice both exact upstream drift-marker lines so self-skip fires on
    # either. The thin-wrapper body replaces the pin's plain `return
    # level` scan; the spaced param-prefix slice is appended in the param
    # site. We keep the form byte-exact to the PR's `gh pr diff` output.
    .replace(
        '    return level\n',
        "    level, _, _ = _bracket_level_state(s, opening, closing)\n"
        "    return level\n",
    )
    .replace(
        "            arguments, _ = filter_delta_text(arguments, previous_text)\n",
        "            arguments_prefix = current_text[: param_match.start(1)]\n"
        "            arguments, _ = filter_delta_text(arguments, arguments_prefix)\n",
    )
    .replace("(pin g303916e93 form)", "(post-vllm#45389 merged form)")
)

PIN_TREE = Path("/private/tmp/candidate_pin_current/vllm/tool_parsers")

ENV_FLAG = "GENESIS_ENABLE_PN386_REQUIRED_STREAMING_STRING_AWARE"


# ── Helpers ──────────────────────────────────────────────────────────


def _install_fake(tmp_path, monkeypatch, streaming_text):
    target = tmp_path / "streaming.py"
    target.write_text(streaming_text, encoding="utf-8")
    monkeypatch.setattr(m, "resolve_vllm_file", lambda rel: str(target))
    # apply() is dispatcher-gated (opt-in env flag, registry-driven);
    # force the gate open for unit tests of the patch mechanics.
    import sndr.dispatcher as dispatcher
    monkeypatch.setattr(
        dispatcher, "should_apply", lambda pid: (True, "test override")
    )
    return target


def _load_patched_module(target_path: Path):
    """Import the patched fake streaming.py as a throwaway module so the
    rewritten helpers can be exercised behaviorally."""
    spec = importlib.util.spec_from_file_location(
        "pn386_fake_streaming", str(target_path)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Patcher shape ────────────────────────────────────────────────────


class TestPatcherShape:
    def test_patcher_has_three_required_subs(self, tmp_path, monkeypatch):
        _install_fake(tmp_path, monkeypatch, PIN_STREAMING)
        patcher = m._make_patcher()
        assert patcher is not None
        by_name = {sp.name: sp for sp in patcher.sub_patches}
        assert set(by_name) == {
            "pn386_bracket_level_state",
            "pn386_filter_delta_string_aware",
            "pn386_filter_delta_break_guard",
            "pn386_param_extract_prefix",
        }
        for sp in patcher.sub_patches:
            assert sp.required is True

    def test_patcher_none_when_target_missing(self, monkeypatch):
        monkeypatch.setattr(m, "resolve_vllm_file", lambda rel: None)
        assert m._make_patcher() is None

    def test_module_documents_p68_prereq_and_45310_pairing(self):
        doc = m.__doc__ or ""
        assert "45389" in doc
        assert "P68" in doc
        assert "45310" in doc

    def test_module_references_registry_env_flag(self):
        src = Path(m.__file__).read_text(encoding="utf-8")
        assert ENV_FLAG in src


# ── Apply semantics ──────────────────────────────────────────────────


class TestApply:
    def test_apply_pin_form_installs_all_subs(self, tmp_path, monkeypatch):
        target = _install_fake(tmp_path, monkeypatch, PIN_STREAMING)
        status, reason = m.apply()
        assert status == "applied", reason

        out = target.read_text(encoding="utf-8")
        # The string/escape-aware state helper now exists and the break
        # guard is string-aware.
        assert "_bracket_level_state" in out
        assert "in_string" in out
        assert 'if not in_string and char == ","' in out
        # Param extraction now uses the substring's prefix, not
        # previous_text.
        assert "param_match.start(1)" in out
        # File still compiles after the splice.
        compile(out, str(target), "exec")

    def test_patched_helper_handles_braces_in_string(
        self, tmp_path, monkeypatch
    ):
        """Behavioral parity with upstream
        test_streaming_output_valid_with_braces_in_string: a city value
        containing brace / quote / backslash characters must round-trip
        through json.loads after streaming reassembly via the patched
        filter_delta_text + param extraction."""
        target = _install_fake(tmp_path, monkeypatch, PIN_STREAMING)
        status, reason = m.apply()
        assert status == "applied", reason
        patched = _load_patched_module(target)

        for city in ["a { b", "a } b", "a }} b", 'a " } b', r"a \ } b"]:
            output = [
                {"name": "get_current_weather", "parameters": {"city": city}}
            ]
            output_json = json.dumps(output)
            # Stream the JSON one char at a time, reassembling the way the
            # required-tool streaming path does: name segment is emitted
            # once, then arguments are the prefix-trimmed parameter body.
            combined = _collect_required_streaming(patched, output_json, 1)
            assert json.loads(combined) == output, (
                f"city={city!r}: reassembled={combined!r}"
            )

    def test_unpatched_helper_corrupts_braces_in_string(
        self, tmp_path, monkeypatch
    ):
        """Negative control: the PIN-form (unpatched) helper DOES corrupt
        a brace-in-string payload — proves the test exercises the bug the
        patch fixes (mirrors the upstream source-revert regression)."""
        target = tmp_path / "streaming.py"
        target.write_text(PIN_STREAMING, encoding="utf-8")
        pin_mod = _load_patched_module(target)
        # 'a } b' closes the wrapper bracket early in the unpatched
        # counter -> truncated/corrupted arguments -> json.loads fails.
        output_json = json.dumps(
            [{"name": "get_current_weather", "parameters": {"city": "a } b"}}]
        )
        combined = _collect_required_streaming(pin_mod, output_json, 1)
        with pytest.raises((json.JSONDecodeError, AssertionError)):
            assert json.loads(combined) == json.loads(output_json)

    def test_second_apply_is_idempotent(self, tmp_path, monkeypatch):
        _install_fake(tmp_path, monkeypatch, PIN_STREAMING)
        first_status, first_reason = m.apply()
        assert first_status == "applied", first_reason
        second_status, second_reason = m.apply()
        assert second_status == "skipped"
        assert "already applied" in second_reason

    def test_self_skips_on_45389_merged_form(self, tmp_path, monkeypatch):
        target = _install_fake(tmp_path, monkeypatch, MERGED_STREAMING)
        status, reason = m.apply()
        assert status == "skipped"
        assert "upstream_merged" in reason
        assert target.read_text(encoding="utf-8") == MERGED_STREAMING

    def test_apply_skips_when_gate_closed(self, tmp_path, monkeypatch):
        target = tmp_path / "streaming.py"
        target.write_text(PIN_STREAMING, encoding="utf-8")
        monkeypatch.setattr(m, "resolve_vllm_file", lambda rel: str(target))
        import sndr.dispatcher as dispatcher
        monkeypatch.setattr(
            dispatcher, "should_apply", lambda pid: (False, "opt-in: env unset")
        )
        monkeypatch.delenv(ENV_FLAG, raising=False)
        status, _reason = m.apply()
        assert status == "skipped"
        assert target.read_text(encoding="utf-8") == PIN_STREAMING

    def test_apply_skips_when_target_missing(self, monkeypatch):
        monkeypatch.setattr(m, "resolve_vllm_file", lambda rel: None)
        import sndr.dispatcher as dispatcher
        monkeypatch.setattr(
            dispatcher, "should_apply", lambda pid: (True, "test override")
        )
        status, _reason = m.apply()
        assert status == "skipped"


# ── Lint contract (tools/lint_drift_markers.py) ──────────────────────


class TestDriftMarkerSelfCollision:
    def test_markers_not_substring_of_own_emitted_text(
        self, tmp_path, monkeypatch
    ):
        _install_fake(tmp_path, monkeypatch, PIN_STREAMING)
        patcher = m._make_patcher()
        marker_line = f"# [Genesis wiring marker: {patcher.marker}]\n"
        assert patcher.upstream_drift_markers, "drift markers must exist"
        for dm in patcher.upstream_drift_markers:
            if dm.startswith("[Genesis"):
                continue
            for sp in patcher.sub_patches:
                assert dm not in sp.replacement, (
                    f"drift marker {dm!r} collides with {sp.name} "
                    "replacement — would false-fire Layer 3 (PN369 class)"
                )
            assert dm not in marker_line

    def test_markers_match_45389_merged_form(self, tmp_path, monkeypatch):
        _install_fake(tmp_path, monkeypatch, PIN_STREAMING)
        patcher = m._make_patcher()
        assert any(
            dm in MERGED_STREAMING for dm in patcher.upstream_drift_markers
        )


# ── Pristine pin invariants (opportunistic) ──────────────────────────


@pytest.mark.skipif(
    not (PIN_TREE / "streaming.py").is_file(),
    reason="pristine pin tree not present on this machine",
)
class TestAnchorsAgainstPristinePin:
    # Anchor (old, new) pairs built straight from the module constants —
    # independent of resolve_vllm_file (which would point at the locally
    # installed vllm, not the pristine pin tree under test here).
    ANCHOR_PAIRS = (
        ("pn386_bracket_level_state", "PN386_BRACKET_OLD", "PN386_BRACKET_NEW"),
        (
            "pn386_filter_delta_string_aware",
            "PN386_FILTER_OLD",
            "PN386_FILTER_NEW",
        ),
        ("pn386_filter_delta_break_guard", "PN386_BREAK_OLD", "PN386_BREAK_NEW"),
        ("pn386_param_extract_prefix", "PN386_PARAM_OLD", "PN386_PARAM_NEW"),
    )

    def test_anchors_unique_and_replacement_markers_absent(self):
        src = (PIN_TREE / "streaming.py").read_text(encoding="utf-8")
        for name, old_attr, new_attr in self.ANCHOR_PAIRS:
            old = getattr(m, old_attr)
            new = getattr(m, new_attr)
            assert src.count(old) == 1, name
            assert new not in src, name
        for dm in m._DRIFT_MARKERS:
            assert dm not in src

    def test_fixture_anchor_regions_byte_match_pristine(self):
        src = (PIN_TREE / "streaming.py").read_text(encoding="utf-8")
        for _name, old_attr, _new_attr in self.ANCHOR_PAIRS:
            old = getattr(m, old_attr)
            assert old in src, old_attr
            assert old in PIN_STREAMING, old_attr


# ── Streaming reassembly helper (mirrors upstream test harness) ──────


def _collect_required_streaming(mod, output_json: str, delta_len: int) -> str:
    """Reassemble a streamed required-tool tool-call from `output_json`
    the way the server path does, using the loaded module's
    `_param_extract_site` (which wraps the patched-or-pin param block).
    Returns the full JSON list string for the caller to json.loads.

    Mirrors `_collect_required_tool_streaming_json` from upstream's
    tests/tool_use/test_tool_choice_required.py for a single-tool stream:
    the name is fixed, then the parameter body is trimmed once the
    `"parameters"` marker has streamed in. No inner assertion — the
    caller's json.loads is what proves correctness vs corruption (the
    negative-control test relies on this surfacing the bug)."""
    import json as _json

    output = _json.loads(output_json)
    name = output[0]["name"]

    previous_text = ""
    args = ""
    for i in range(0, len(output_json), delta_len):
        delta_text = output_json[i : i + delta_len]
        current_text = previous_text + delta_text
        # `_param_extract_site` returns "" until "parameters" appears,
        # then the (prefix- or previous_text-) trimmed arguments body.
        extracted = mod._param_extract_site(current_text, previous_text)
        if extracted:
            args = extracted
        previous_text = current_text

    return '[{"name": "%s", "parameters": %s}]' % (name, args)
