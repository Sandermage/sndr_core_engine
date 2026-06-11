# SPDX-License-Identifier: Apache-2.0
"""TDD for PN374 — qwen3xml quoted parameter-name (key) sanitization.

Roadmap 2026-06-11 (PR sweep, chunk 4 Theme 1): audit qwen3_xml for the
same key/value asymmetry Gemma4 has (vllm#44715 / PR #44877). Audit
verdict on pin 0.22.1rc1.dev259+g303916e93 — the asymmetry EXISTS:

* Values are safe: ``_convert_for_json_streaming`` routes string values
  through ``json.dumps`` (escaped), and deferred complex values go
  through literal_eval + json re-emit.
* Keys are unsafe twice:
  1. ``_preprocess_xml_chunk`` rewrites ``<parameter=NAME>`` to
     ``<parameter name="NAME">`` with a verbatim capture ``([^>]+)`` —
     a model-emitted quoted key ``<parameter="3">`` becomes the
     malformed attribute ``name=""3""`` and kills the expat parse of
     the whole element (parameter silently lost).
  2. ``_extract_parameter_name``'s ``parameter=NAME`` split fallback
     returns the name verbatim, and ``_start_element`` interpolates it
     UNESCAPED into the arguments JSON (``f'{{"{param_name}": '``) —
     a quote inside the key emits invalid JSON to the client.

PN374 strips quote wrappers (and surrounding whitespace) from the
captured parameter name at both sites — the exact analog of the Gemma4
quoted-key strip (#44877), adapted to the qwen3xml tag format.
"""
from __future__ import annotations

import re

import pytest


def _wiring():
    from sndr.engines.vllm.patches.tool_parsing import (
        pn374_qwen3xml_quoted_keys as M,
    )
    return M


# ─── anchor / replacement content contracts ────────────────────────────────


def test_anchor_a_targets_preprocess_regex():
    M = _wiring()
    assert '<parameter=([^>]+)>' in M.ANCHOR_A_OLD
    assert 'name="\\1"' in M.ANCHOR_A_OLD


def test_replacement_a_strips_quote_wrappers():
    M = _wiring()
    assert "PN374" in M.ANCHOR_A_NEW
    assert "strip" in M.ANCHOR_A_NEW
    # The verbatim back-reference form must be GONE from the replacement
    # (the captured name is now sanitized through a callable).
    assert 'r\'<parameter name="\\1">\'' not in M.ANCHOR_A_NEW


def test_anchor_b_targets_extract_parameter_name_fallback():
    M = _wiring()
    assert 'name.split("=", 1)' in M.ANCHOR_B_OLD
    assert 'parts[0] == "parameter"' in M.ANCHOR_B_OLD


def test_replacement_b_strips_quote_wrappers():
    M = _wiring()
    assert "PN374" in M.ANCHOR_B_NEW
    assert "return parts[1]" not in M.ANCHOR_B_NEW.replace(
        "return parts[1].strip", ""
    )


# ─── synthetic end-to-end (no vllm install needed) ─────────────────────────

_SYNTHETIC_HEADER = "import re\n\n\nclass _Parser:\n"

_SYNTHETIC_PREPROCESS = (
    "    def preprocess(self, chunk):\n"
    "        processed = chunk\n"
)

_SYNTHETIC_PREPROCESS_TAIL = "        return processed\n"

_SYNTHETIC_EXTRACT = (
    "    def extract(self, name, attrs):\n"
    '        if attrs and "name" in attrs:\n'
    '            return attrs["name"]\n'
)

_SYNTHETIC_EXTRACT_TAIL = "        return None\n"


def _make_synthetic_root(tmp_path):
    """Build a fake vllm root holding a parser file with both anchors."""
    M = _wiring()
    root = tmp_path / "vllm"
    (root / "tool_parsers").mkdir(parents=True)
    source = (
        _SYNTHETIC_HEADER
        + _SYNTHETIC_PREPROCESS
        + M.ANCHOR_A_OLD
        + _SYNTHETIC_PREPROCESS_TAIL
        + "\n"
        + _SYNTHETIC_EXTRACT
        + M.ANCHOR_B_OLD
        + _SYNTHETIC_EXTRACT_TAIL
    )
    (root / "tool_parsers" / "qwen3xml_tool_parser.py").write_text(source)
    return root


def _exec_parser(path):
    namespace: dict = {}
    exec(compile(path.read_text(), str(path), "exec"), namespace)  # noqa: S102
    return namespace["_Parser"]()


@pytest.fixture()
def applied_parser(tmp_path, monkeypatch):
    M = _wiring()
    root = _make_synthetic_root(tmp_path)
    import sndr.engines.vllm.detection.guards as guards
    monkeypatch.setattr(guards, "vllm_install_root", lambda: str(root))
    monkeypatch.setenv(M.ENV_FLAG_FULL, "1")
    status, reason = M.apply()
    assert status == "applied", reason
    return _exec_parser(root / "tool_parsers" / "qwen3xml_tool_parser.py")


def test_quoted_key_is_stripped_in_preprocess(applied_parser):
    out = applied_parser.preprocess('<parameter="3">')
    assert out == '<parameter name="3">'


def test_single_quoted_key_is_stripped_in_preprocess(applied_parser):
    out = applied_parser.preprocess("<parameter='loc'>")
    assert out == '<parameter name="loc">'


def test_bare_key_unchanged_in_preprocess(applied_parser):
    out = applied_parser.preprocess("<parameter=location>")
    assert out == '<parameter name="location">'


def test_whitespace_wrapped_key_is_stripped(applied_parser):
    out = applied_parser.preprocess('<parameter= "3" >')
    assert out == '<parameter name="3">'


def test_extract_fallback_strips_quotes(applied_parser):
    assert applied_parser.extract('parameter="3"', {}) == "3"
    assert applied_parser.extract("parameter=loc", {}) == "loc"


def test_attrs_path_untouched(applied_parser):
    """attrs are produced by expat from hunk-A-preprocessed text, so the
    attrs short-circuit needs no hunk (and its anchor is ambiguous —
    `_extract_function_name` shares the same two lines)."""
    assert applied_parser.extract("parameter", {"name": "x"}) == "x"


def test_unpatched_preprocess_demonstrates_bug(tmp_path):
    """Document the pristine failure mode the patch removes."""
    root = _make_synthetic_root(tmp_path)
    parser = _exec_parser(root / "tool_parsers" / "qwen3xml_tool_parser.py")
    out = parser.preprocess('<parameter="3">')
    # Verbatim capture keeps the quotes — malformed XML attribute.
    assert out == '<parameter name=""3"">'


def test_idempotent_second_apply(tmp_path, monkeypatch):
    M = _wiring()
    root = _make_synthetic_root(tmp_path)
    import sndr.engines.vllm.detection.guards as guards
    monkeypatch.setattr(guards, "vllm_install_root", lambda: str(root))
    monkeypatch.setenv(M.ENV_FLAG_FULL, "1")
    status1, _ = M.apply()
    status2, reason2 = M.apply()
    assert status1 == "applied"
    assert status2 == "applied"
    assert "idempotent" in reason2


def test_env_flag_default_off(tmp_path, monkeypatch):
    M = _wiring()
    root = _make_synthetic_root(tmp_path)
    import sndr.engines.vllm.detection.guards as guards
    monkeypatch.setattr(guards, "vllm_install_root", lambda: str(root))
    monkeypatch.delenv(M.ENV_FLAG_FULL, raising=False)
    status, reason = M.apply()
    assert status == "skipped"
    assert M.ENV_FLAG_FULL in reason


def test_no_drift_marker_self_collision(tmp_path, monkeypatch):
    """Self-collision rule: no upstream_drift_marker may be a substring
    of the patcher's own emitted text (lint_drift_markers contract)."""
    import importlib.util
    from pathlib import Path

    M = _wiring()
    root = _make_synthetic_root(tmp_path)
    import sndr.engines.vllm.detection.guards as guards
    monkeypatch.setattr(guards, "vllm_install_root", lambda: str(root))
    patcher = M._make_patcher()
    assert patcher is not None

    repo_root = Path(__file__).resolve().parents[4]
    spec = importlib.util.spec_from_file_location(
        "lint_drift_markers", repo_root / "tools" / "lint_drift_markers.py"
    )
    lint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lint)
    assert lint.collisions_for_patcher(patcher) == []


def test_anchors_match_module_regex_semantics():
    """The sanitizing replacement must keep matching what upstream's
    verbatim regex matched (same capture envelope, [^>]+)."""
    M = _wiring()
    pattern = re.compile(r"<parameter=([^>]+)>")
    assert pattern.search('<parameter="3">').group(1) == '"3"'
