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

# NOTE (audit #14 RETIRE): PN373 is lifecycle=retired (upstream vllm#44955
# absorbed it; version range caps below the current pin). Its anchor
# byte-verification, pristine bug-reproduction, patched-semantics and
# TextPatcher-integration classes all gated on the pristine candidate tree
# (/private/tmp/candidate_pin_current) that exists on no CI host -> they
# green-by-skipped everywhere. They are removed; the CI-runnable synthetic
# drift-marker hygiene contract below is retained.

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
        pn373_parallel_toolcalls_null as M,  # noqa: N812
    )
    return M


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
