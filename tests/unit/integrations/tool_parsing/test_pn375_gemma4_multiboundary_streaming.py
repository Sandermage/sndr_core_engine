# SPDX-License-Identifier: Apache-2.0
"""TDD for PN375 — Gemma4 multi-boundary streaming deltas (vllm#44741).

Upstream issue #41967: under MTP/speculative decoding a single streamed
delta can cross multiple tool-call boundaries (e.g. close one call AND
start the next in the same delta). The pre-refactor pin parser
(`vllm/tool_parsers/gemma4_tool_parser.py`, state-machine variant with
`buffered_delta_text`) selected ONE branch per delta, so argument
fragments on the far side of the boundary were silently dropped — the
first/next tool call lost arguments. PN375 vendors PR #44741's
`_extract_streaming_delta_segments` design as a runtime monkey-patch on
`Gemma4ToolParser`, with the G4_14 pad-token set stripped from both
`current_text` and `delta_text` before the consistency check.

═══════════════════════════════════════════════════════════════════════
RETIRED behavioral block (audit #14 full drain, 2026-07-06)
═══════════════════════════════════════════════════════════════════════
The exec-based #44741 regression matrix (multi-boundary corpus, pad
asymmetry, buffered-boundary, G4_14 combined) execed the REAL pristine
`Gemma4ToolParser` source, gated on the macOS-only pristine candidate-pin
tree — absent on every CI host AND on the Linux rig. It executed on NO host
(permanent green-by-skip).

More than dead-by-path: at the CURRENT pin dev748 (2dfaae752) the upstream
gemma4 tool-parsing stack was REFACTORED — there is no ``Gemma4ToolParser``
class anywhere in the tree; ``tool_parsers/gemma4_tool_parser.py`` is gone,
replaced by ``tool_parsers/gemma4_engine_tool_parser.py``
(``Gemma4EngineToolParser(Gemma4ParserToolAdapter)``, delegating to
``parser/gemma4.py``). PN375's ``_find_gemma4_parser_class()`` therefore
resolves None at dev748 and the patch SELF-SKIPS at runtime. The exec
matrix could not run even against a live rig pristine tree — its subject
class no longer exists. The regression matrix was therefore retired rather
than re-homed onto a phantom path: PN375 is a retire-eligible patch pending
the upstream #44741-absorption / G4_T1-supersession check (a holistic
patch-retirement task, not a test-hygiene edit). Retiring the dead exec
matrix keeps this file honest; the CI-runnable lifecycle/self-skip
contracts below stay and are in fact the ONLY PN375 behavior that still
matters on dev748 — that it self-skips cleanly on the refactored stack.
"""
from __future__ import annotations


def _wiring():
    from sndr.engines.vllm.patches.tool_parsing import (
        pn375_gemma4_multiboundary_streaming as M,  # noqa: N812
    )
    return M


# ─── variant self-skip + lifecycle (CI-runnable, no pristine source) ────────


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
    """On the refactored dev748 stack ``_find_gemma4_parser_class`` returns
    None (the old ``Gemma4ToolParser`` is gone) — PN375 must self-skip."""
    M = _wiring()
    monkeypatch.setenv(M.ENV_FLAG_FULL, "1")
    monkeypatch.setattr(M, "_find_gemma4_parser_class", lambda: None)
    status, reason = M.apply()
    assert status == "skipped"
    assert "no gemma4" in reason.lower() or "not found" in reason.lower()
