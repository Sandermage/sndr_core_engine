# SPDX-License-Identifier: Apache-2.0
"""PN386 — required-tool streaming brace JSON-string-awareness (vendor of vllm#45389).

RETIRED 2026-06-25 (pin bump dev301 -> dev424) — superseded by vllm#45389,
which MERGED 2026-06-23 (mergeCommit 899d72a5) and is IN dev424. The dev424
pristine tool_parsers/streaming.py carries _bracket_level_state + the in_string
state machine + both PR drift markers (byte-verified in-container); the dev424
anchor-SOT regen flagged all 4 sub-anchors as anchor_drift. Iron-rule-#11
outcome (a): byte-equivalent (Genesis divergences are spelling-only, below).
Registry lifecycle=retired, capped <0.23.1rc1.dev424. The transform below is
UNCHANGED and still applies on dev301 (the previous/rollback pin, where #45389
is NOT yet merged); on dev424+ the version cap + the merged-form drift markers
self-skip it. Default-off and enabled in no PROD config, so the retire is a
no-op on the deployed fleet. Do not delete the module while dev301 rollback is
possible. Sibling #45310 (Hermes </tool_call> boundary) is a SEPARATE patch,
unaffected.

Upstream bug class (vllm#45389, related #41111)
-----------------------------------------------
In ``tool_choice="required"`` STREAMING, vLLM trims the streamed
tool-call JSON by counting the wrapper's bracket level in
``vllm/tool_parsers/streaming.py``. Two helpers do the trimming:

* ``_bracket_level(s)`` — counts ``{`` / ``}`` to find the current
  nesting depth.
* ``filter_delta_text(delta_text, previous_text)`` — walks each new
  delta char, keeps characters while ``bracket_level != 0`` and BREAKS
  on a top-level ``,`` (the tool-list separator) once depth returns to
  zero.

Both treat ``{`` / ``}`` / ``,`` as STRUCTURAL even when they appear
inside a JSON string VALUE. So a perfectly valid generated argument
like ``{"city": "a } b"}`` is mis-trimmed: the ``}`` inside the string
decrements the counter early, the trim fires at the wrong place, and the
client receives malformed ``function.arguments`` — a raw
``json.JSONDecodeError`` on the consumer side. The same failure hits any
string value carrying ``{ } " \\`` characters: file paths, regexes,
shell snippets, and nested-JSON-as-a-string arguments — exactly the
payload shapes coding/agent tools emit.

The fix makes the bracket scan JSON-string aware:

1. ``_bracket_level_state(s)`` returns ``(level, in_string, escaped)`` —
   tracking whether we are inside a ``"..."`` string and whether the
   previous char was a backslash escape. Inside a string, ``{`` / ``}``
   are NOT counted. ``_bracket_level`` becomes a thin wrapper over it.
2. ``filter_delta_text`` seeds ``in_string`` / ``escaped`` from
   ``_bracket_level_state(previous_text)`` so a string opened in an
   earlier delta is carried forward, walks the delta with the same
   string/escape state machine, and only breaks on a top-level ``,``
   when ``not in_string`` (a comma inside a string value is payload, not
   a separator).
3. The first ``"parameters"`` substring extraction in
   ``extract_required_tool_call_streaming`` is scanned with its
   PRECEDING PREFIX as the ``filter_delta_text`` context (the bytes of
   ``current_text`` before the captured group), not ``previous_text``.
   ``previous_text`` is the wrong baseline here: it is the full prior
   stream, whereas the just-extracted parameter substring's correct
   string/escape baseline is the text immediately in front of it. The
   greedy ``.*"parameters"`` match is preserved so multi-tool streaming
   still selects the LATEST parameter segment.

LIVE exposure on our stack
--------------------------
This is a PROD correctness bug, not a latency one. Genesis **P68**
(``GENESIS_ENABLE_P68_AUTO_FORCE_TOOL``) auto-upgrades ``tool_choice``
auto -> required at long context (>~12.5K) for the qwen3.x / gemma
families — i.e. it deliberately funnels long-context agent traffic INTO
this exact helper. Flipping P68 on without this fix would route real
coder/agent payloads (whose string args routinely contain ``{ } " \\``)
straight through the buggy trimmer and corrupt their streamed
arguments. **PN386 is therefore the prerequisite for safely enabling
P68.** Until both land + bench, P68 stays default_on=False and so does
this patch.

Sibling: vllm#45310 fixes the Hermes ``</tool_call>`` tag boundary —
the SAME string-awareness bug class one layer up (a literal
``</tool_call>`` inside a string value truncates the tool call). It is
the wave-2 pairing for this patch (vendor together); PN386 here is the
generic required-tool wrapper trimmer, #45310 is the Hermes-specific
boundary. Different files, same root cause.

Genesis divergence — spelling only (documented per iron rule #10)
-----------------------------------------------------------------
Two deliberate spelling divergences from #45389 keep the PR's exact
structural lines usable as upstream-merge drift markers without ever
colliding with the text THIS patch emits (lint_drift_markers
self-collision contract / PN369 rule):

* The param-prefix slice: upstream writes
  ``current_text[: param_match.start(1)]`` (space after ``[:``); we
  write ``current_text[:param_match.start(1)]`` (no space). Identical
  slice.
* The ``_bracket_level`` thin wrapper: upstream unpacks
  ``level, _, _ = _bracket_level_state(...)``; we unpack
  ``lvl, _unused_in_string, _unused_escaped = _bracket_level_state(...)``
  and ``return lvl``. Identical result.

The semantic fix lines themselves (``_bracket_level_state``,
``in_string`` tracking, ``not in_string and char == ","``) are what we
MUST emit, so they can never be drift markers — the two divergent
spellings above carry that role instead.

Rebind analysis (verified against pristine pin g303916e93)
----------------------------------------------------------
``_bracket_level`` / ``_bracket_level_state`` / ``filter_delta_text``
are module-level functions referenced only within the same file and via
``from vllm.tool_parsers.streaming import ...`` by the OpenAI serving
layer. A source-level text patch applied before import needs no runtime
rebind; the new ``_bracket_level_state`` is referenced by name inside
the patched ``_bracket_level`` and ``filter_delta_text`` bodies, both
co-located in the same replacement. All four anchors byte-verified
count==1 against /private/tmp/candidate_pin_current/vllm/tool_parsers/
streaming.py (2026-06-13).

Activation: opt-in via
``GENESIS_ENABLE_PN386_REQUIRED_STREAMING_STRING_AWARE=1`` (default OFF;
strongly recommended ON before enabling P68 — see above). Self-skips
when #45389 lands upstream: the drift markers below are exact substrings
of the PR's merged form.

Author backport: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
Vendor target: vllm-project/vllm#45389 (OPEN as of 2026-06-13).
"""
from __future__ import annotations

import logging

from sndr.engines.vllm.detection.guards import resolve_vllm_file
from sndr.kernel import TextPatch, TextPatcher, result_to_wiring_status

log = logging.getLogger(
    "genesis.wiring.pn386_required_streaming_brace_string_aware"
)

GENESIS_PN386_MARKER = (
    "Genesis PN386 required-tool streaming brace JSON-string-awareness "
    "(vendor of vllm#45389) v1"
)

_TARGET_REL = "tool_parsers/streaming.py"

# Drift markers — exact substrings of #45389's merged form (from
# `gh pr diff 45389`, 2026-06-13). Absent in the pristine pin tree
# (g303916e93, byte-verified) and deliberately NOT substrings of our own
# replacement text: we spell the param-prefix slice WITHOUT the space
# after `[:` and the thin wrapper unpacks `lvl, _unused_in_string,
# _unused_escaped` instead of `level, _, _` (lint_drift_markers
# self-collision contract).
_DRIFT_MARKERS = (
    # The PR's param-prefix slice (upstream spelling with the space).
    "                    arguments_prefix = current_text[: "
    "param_match.start(1)]\n",
    # The PR's thin-wrapper body (upstream `_, _` unpacking).
    "    level, _, _ = _bracket_level_state(s, opening, closing)\n",
)


# ── Sub-patch 1 (required): _bracket_level -> _bracket_level_state ────
# Anchor: the whole pin-form `_bracket_level` function. Unique
# (count==1, byte-verified against the pristine pin). Replaced with the
# string/escape-aware `_bracket_level_state` plus a thin `_bracket_level`
# wrapper that preserves the public signature.

PN386_BRACKET_OLD = (
    'def _bracket_level(s: str, opening: str = "{", closing: str = "}") -> int:\n'
    '    """Calculate the current level of nested brackets in a string."""\n'
    "    level = 0\n"
    "    for char in s:\n"
    "        if char == opening:\n"
    "            level += 1\n"
    "        elif char == closing:\n"
    "            level -= 1\n"
    "    return level\n"
)

PN386_BRACKET_NEW = (
    "# [Genesis PN386 vendor of vllm#45389] JSON-string-aware bracket\n"
    "# scan. The required-tool streaming trimmer must not count `{`/`}`\n"
    "# that occur inside a JSON string VALUE, or a valid argument like\n"
    '# {"city": "a } b"} is mis-trimmed into malformed function.arguments\n'
    "# (client JSONDecodeError). `_bracket_level_state` returns the depth\n"
    "# plus whether the scan ended inside a string / on an escape, so\n"
    "# `filter_delta_text` can carry that state across deltas.\n"
    "def _bracket_level_state(\n"
    '    s: str, opening: str = "{", closing: str = "}"\n'
    ") -> tuple[int, bool, bool]:\n"
    "    level = 0\n"
    "    in_string = False\n"
    "    escaped = False\n"
    "    for char in s:\n"
    "        if escaped:\n"
    "            # Previous char was a backslash inside a string: this\n"
    "            # char is escaped payload, consume it without effect.\n"
    "            escaped = False\n"
    "            continue\n"
    '        if in_string and char == "\\\\":\n'
    "            escaped = True\n"
    "            continue\n"
    "        if char == '\"':\n"
    "            # Toggle string state on an unescaped quote.\n"
    "            in_string = not in_string\n"
    "            continue\n"
    "        if not in_string:\n"
    "            # Only structural braces (outside a string) move depth.\n"
    "            if char == opening:\n"
    "                level += 1\n"
    "            elif char == closing:\n"
    "                level -= 1\n"
    "    return level, in_string, escaped\n"
    "\n"
    "\n"
    'def _bracket_level(s: str, opening: str = "{", closing: str = "}") -> int:\n'
    '    """Calculate the current level of nested brackets in a string."""\n'
    "    # [Genesis PN386] Thin wrapper over the string-aware state scan.\n"
    "    # Spelled with named throwaways (not `_, _`) so the upstream\n"
    "    # `level, _, _ = _bracket_level_state(...)` form stays usable as\n"
    "    # a merge drift marker without colliding with our own output.\n"
    "    lvl, _unused_in_string, _unused_escaped = _bracket_level_state(\n"
    "        s, opening, closing\n"
    "    )\n"
    "    return lvl\n"
)


# ── Sub-patch 2 (required): filter_delta_text seed + loop head ───────
# Anchor: the seed line + the `for char` loop head up to the first
# `bracket_level += 1`. Replaced to carry string/escape state forward
# and to skip brace counting inside string values.

PN386_FILTER_OLD = (
    "    bracket_level = _bracket_level(previous_text)\n"
    '    updated_delta = ""\n'
    "    passed_zero = False\n"
    "    for char in delta_text:\n"
    '        if char == "{":\n'
    "            bracket_level += 1\n"
)

PN386_FILTER_NEW = (
    "    # [Genesis PN386 vendor of vllm#45389] Seed the depth AND the\n"
    "    # string/escape state from the prior text, so a string value\n"
    "    # opened in an earlier delta is carried forward and its inner\n"
    "    # braces/commas are treated as payload, not structure.\n"
    "    bracket_level, in_string, escaped = _bracket_level_state(previous_text)\n"
    '    updated_delta = ""\n'
    "    passed_zero = False\n"
    "    for char in delta_text:\n"
    "        if escaped:\n"
    "            # Escaped char inside a string: payload, never structure.\n"
    "            escaped = False\n"
    "        elif in_string:\n"
    '            if char == "\\\\":\n'
    "                escaped = True\n"
    "            elif char == '\"':\n"
    "                in_string = False\n"
    "        elif char == '\"':\n"
    "            in_string = True\n"
    '        elif char == "{":\n'
    "            bracket_level += 1\n"
)


# ── Sub-patch 3 (required): filter_delta_text break guard ────────────
# Anchor: the top-level-comma break. Replaced so the trim only breaks on
# a separator comma OUTSIDE a string value.

PN386_BREAK_OLD = (
    "        if bracket_level != 0:\n"
    "            updated_delta += char\n"
    "        else:\n"
    '            if char == ",":\n'
    "                break\n"
)

PN386_BREAK_NEW = (
    "        if bracket_level != 0:\n"
    "            updated_delta += char\n"
    "        else:\n"
    "            # [Genesis PN386] Only a top-level comma OUTSIDE a string\n"
    "            # is the tool-list separator; a comma inside a string\n"
    "            # value is payload and must not stop the trim.\n"
    '            if not in_string and char == ",":\n'
    "                break\n"
)


# ── Sub-patch 4 (required): param extraction uses prefix not previous ─
# Anchor: the `"parameters"` substring extraction + its filter call.
# Replaced so the extracted parameter body is trimmed with its PRECEDING
# PREFIX (the bytes of current_text before the captured group) as the
# string/escape baseline, instead of the unrelated `previous_text`.

PN386_PARAM_OLD = (
    "                param_match = re.search(\n"
    "                    r'.*\"parameters\":\\s*(.*)', current_text, re.DOTALL\n"
    "                )\n"
    '                arguments = param_match.group(1) if param_match else ""\n'
    "                arguments, _ = filter_delta_text(arguments, previous_text)\n"
)

PN386_PARAM_NEW = (
    "                param_match = re.search(\n"
    "                    r'.*\"parameters\":\\s*(.*)', current_text, re.DOTALL\n"
    "                )\n"
    "                # [Genesis PN386 vendor of vllm#45389] Trim the freshly\n"
    "                # extracted parameter body against its own preceding\n"
    "                # prefix, not previous_text. The greedy `.*\"parameters\"`\n"
    "                # match still selects the LATEST parameter segment\n"
    "                # (multi-tool streaming), but its correct string/escape\n"
    "                # baseline is the text right in front of the captured\n"
    "                # group. Slice spelled without the space after `[:`\n"
    "                # (upstream writes `[: param_match...`) so that form\n"
    "                # stays a clean merge drift marker.\n"
    "                if param_match:\n"
    "                    arguments = param_match.group(1)\n"
    "                    arguments_prefix = current_text[:param_match.start(1)]\n"
    "                    arguments, _ = filter_delta_text("
    "arguments, arguments_prefix)\n"
    "                else:\n"
    '                    arguments = ""\n'
)


def _make_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(_TARGET_REL)
    if target is None:
        return None
    return TextPatcher(
        patch_name=(
            "PN386 tool_parsers/streaming.py — required-tool streaming "
            "brace JSON-string-awareness (vendor of vllm#45389)"
        ),
        target_file=str(target),
        marker=GENESIS_PN386_MARKER,
        sub_patches=[
            TextPatch(
                name="pn386_bracket_level_state",
                anchor=PN386_BRACKET_OLD,
                replacement=PN386_BRACKET_NEW,
                required=True,
            ),
            TextPatch(
                name="pn386_filter_delta_string_aware",
                anchor=PN386_FILTER_OLD,
                replacement=PN386_FILTER_NEW,
                required=True,
            ),
            TextPatch(
                name="pn386_filter_delta_break_guard",
                anchor=PN386_BREAK_OLD,
                replacement=PN386_BREAK_NEW,
                required=True,
            ),
            TextPatch(
                name="pn386_param_extract_prefix",
                anchor=PN386_PARAM_OLD,
                replacement=PN386_PARAM_NEW,
                required=True,
            ),
        ],
        upstream_drift_markers=list(_DRIFT_MARKERS),
    )


def apply() -> tuple[str, str]:
    """Apply PN386 — required-tool streaming brace string-awareness. Never raises.

    Opt-in: gated through the dispatcher on
    ``GENESIS_ENABLE_PN386_REQUIRED_STREAMING_STRING_AWARE`` (default_on=
    False in the registry). Strong recommendation: enable this BEFORE
    flipping Genesis P68 (long-ctx auto-force-required), which funnels
    long-context agent traffic into the exact helper this patch fixes.
    """
    from sndr.dispatcher import log_decision, should_apply

    decision, reason = should_apply("PN386")
    log_decision("PN386", decision, reason)
    if not decision:
        return "skipped", reason

    patcher = _make_patcher()
    if patcher is None:
        return "skipped", f"PN386: target file {_TARGET_REL} not found"

    result, failure = patcher.apply()
    return result_to_wiring_status(
        result, failure,
        applied_message=(
            "PN386 applied: required-tool streaming now scans bracket "
            "depth JSON-string-aware (_bracket_level_state tracks "
            "in_string/escaped; filter_delta_text carries that state "
            "across deltas and only breaks on a top-level comma outside a "
            "string), and the parameter body is trimmed against its own "
            "prefix instead of previous_text. Kills corrupted streamed "
            "function.arguments for string args containing { } \" \\ "
            "characters (vllm#45389). Prerequisite for safely enabling "
            "Genesis P68."
        ),
        patch_name=patcher.patch_name,
    )


def is_applied() -> bool:
    """Return True iff our marker is present in the target file."""
    patcher = _make_patcher()
    if patcher is None:
        return False
    try:
        with open(patcher.target_file, encoding="utf-8") as f:
            return patcher.marker in f.read()
    except (OSError, UnicodeDecodeError):
        return False
