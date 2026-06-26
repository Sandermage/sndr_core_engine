# SPDX-License-Identifier: Apache-2.0
"""PN373 — parallel_tool_calls null != false (vendor of OPEN vllm#44955).

Upstream bug (vllm#44948): ``ChatCompletionRequest.parallel_tool_calls``
is declared ``bool | None = True`` (pristine
``entrypoints/openai/chat_completion/protocol.py:233`` on pin
0.22.1rc1.dev259+g303916e93), so a client sending an explicit JSON
``null`` arrives at ``maybe_filter_parallel_tool_calls`` as ``None``.
The pristine truthiness check::

    if request.parallel_tool_calls:
        return choice

treats ``None`` like ``False`` and falls through to the trim branch —
silently truncating multi-tool responses to a SINGLE call on both the
streaming path (``delta.tool_calls`` filtered to ``index == 0``,
serving.py:844) and the non-streaming path (``message.tool_calls[:1]``,
serving.py:1277). The OpenAI-documented default is ``true``, so an
explicit ``null`` must behave like the default: keep all tool calls.

Genesis impact: LiteLLM- and n8n-class clients serialize
``"parallel_tool_calls": null`` when the caller leaves the knob unset.
On our agent workloads (Qwen3.6 PROD / Gemma-4 PRODs) every truncated
parallel tool call costs a full extra agent round-trip (hundreds of ms
to seconds). PN373 vendors #44955's 1-line semantic fix
(``is not False``) and ADDS the streaming-delta unit test the upstream
PR lacks (tests/unit/integrations/serving/
test_pn373_parallel_toolcalls_null.py).

Anchor strategy
---------------
Single sub-patch in ``entrypoints/serve/utils/tool_calls_utils.py``
spanning the function docstring + the truthiness check (byte-verified
count==1 against /private/tmp/candidate_pin_current on 2026-06-11).
The file has exactly one other code path (the trim branch), left
untouched — explicit ``False`` keeps its documented trim behavior.
Anchor overlap: NONE with PN288/P107 (they patch
``entrypoints/openai/chat_completion/serving.py``; PN373 patches the
helper module the serving call sites delegate to).

Drift marker: the post-#44955 docstring wording (``parallel_tool_calls
is explicitly False``). It is a byte-substring of the PR's post-image
(gh pr diff 44955, fetched 2026-06-11) and deliberately NOT a substring
of anything PN373 writes (self-collision lint,
tools/lint_drift_markers.py). The merged CONDITION text cannot serve as
a marker — our replacement necessarily emits it. If upstream lands a
reworded variant of the fix, the anchor scan misses and PN373 skips
with anchor-drift instead — equally safe, just a less specific reason.

Gates
-----
  * ``GENESIS_ENABLE_PN373_PARALLEL_TOOLCALLS_NULL`` — install gate,
    default OFF (opt-in; candidate default-on after fleet test). The
    dispatcher consults ``should_apply("PN373")`` against the registry
    BEFORE importing this module (sndr/apply/orchestrator.py
    data-driven dispatch), so ``apply()`` does not duplicate the gate
    (PN367 convention).

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
"""
from __future__ import annotations

import logging

from sndr.engines.vllm.detection.guards import resolve_vllm_file
from sndr.kernel import TextPatch, TextPatcher, result_to_wiring_status

log = logging.getLogger("genesis.wiring.pn373_parallel_toolcalls_null")

GENESIS_PN373_MARKER = (
    "Genesis PN373 parallel_tool_calls null != false "
    "(vendor of vllm#44955) v1"
)

_TARGET_REL = "entrypoints/serve/utils/tool_calls_utils.py"

# Substring of #44955's post-image docstring — fires only when upstream
# lands the fix. NOT a substring of PN373_NEW or of the Layer-6
# idempotency marker line (proven in TestDriftMarkerHygiene).
_DRIFT_MARKERS = (
    "parallel_tool_calls is explicitly False",
)

# Pristine block at tool_calls_utils.py:22-25 (pin
# 0.22.1rc1.dev259+g303916e93, count==1 byte-verified 2026-06-11).
PN373_OLD = (
    '    """Filter to first tool call only when parallel_tool_calls '
    'is False."""\n'
    "\n"
    "    if request.parallel_tool_calls:\n"
    "        return choice\n"
)

PN373_NEW = (
    '    """Filter to first tool call only on explicit '
    "``parallel_tool_calls=False``.\n"
    "\n"
    "    [Genesis PN373] vendor of vllm#44955 (fixes vllm#44948): the\n"
    "    request field is declared ``bool | None = True``, so a client\n"
    "    sending JSON ``null`` (LiteLLM/n8n) arrives here as ``None``.\n"
    "    The pristine truthiness check treated ``None`` like ``False``\n"
    "    and silently trimmed multi-tool responses to a single call.\n"
    "    The documented default is ``True`` — only an explicit ``False``\n"
    "    may trim.\n"
    '    """\n'
    "\n"
    "    # [Genesis PN373] None (explicit null) follows the documented\n"
    "    # default (True): keep all tool calls. Only explicit False trims.\n"
    "    if request.parallel_tool_calls is not False:\n"
    "        return choice\n"
)


def _make_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(_TARGET_REL)
    if target is None:
        return None
    return TextPatcher(
        patch_name=(
            "PN373 tool_calls_utils.py — parallel_tool_calls null != "
            "false (vendor of vllm#44955)"
        ),
        target_file=str(target),
        marker=GENESIS_PN373_MARKER,
        sub_patches=[
            TextPatch(
                name="pn373_parallel_toolcalls_null_is_default",
                anchor=PN373_OLD,
                replacement=PN373_NEW,
                required=True,
            ),
        ],
        upstream_drift_markers=list(_DRIFT_MARKERS),
    )


def apply() -> tuple[str, str]:
    """Install the null-vs-false fix. Never raises.

    Env gating (GENESIS_ENABLE_PN373_PARALLEL_TOOLCALLS_NULL) is
    enforced by the dispatcher via the registry entry before this
    module is even imported.
    """
    patcher = _make_patcher()
    if patcher is None:
        return "skipped", f"PN373: {_TARGET_REL} not resolvable"

    result, failure = patcher.apply()
    status, reason = result_to_wiring_status(
        result, failure,
        applied_message=(
            "parallel_tool_calls None (explicit JSON null) now follows "
            "the documented default (keep all tool calls); only explicit "
            "False trims to the first call — both streaming deltas and "
            "full responses (vendor of vllm#44955, fixes #44948)"
        ),
        patch_name="PN373 parallel_tool_calls null fix",
    )
    if status == "failed":
        return "failed", f"PN373 sub-patch failed: {reason}"
    return status, reason


def is_applied() -> bool:
    """Filesystem-level marker check — True iff tool_calls_utils.py
    carries the PN373 marker. Cheap; used by audit / shadow CLI."""
    target = resolve_vllm_file(_TARGET_REL)
    if target is None:
        return False
    try:
        with open(target) as f:
            return GENESIS_PN373_MARKER in f.read()
    except OSError:
        return False
