# SPDX-License-Identifier: Apache-2.0
"""Consolidated wiring for P64 + P61c + PN56 — all three text-patch the SAME
engine file ``tool_parsers/qwen3coder_tool_parser.py`` at DISJOINT regions
(P64 ALSO has a second, 0-match-on-pristine target ``serving.py``).

================================================================
WHY THIS MODULE EXISTS (maintainability refactor, 2026-06-20)
================================================================

P64 (qwen3coder MTP streaming early-return fix, vllm#39598), P61c
(qwen3coder deferred-commit until <function= header, club-3090#72) and
PN56 (qwen3coder XML parse fallback, vllm#41466) historically lived in
three separate wiring modules, each with its own ``TextPatcher`` and its
own ``# [Genesis wiring marker: ...]`` line, even though they patch the
same parser file at non-overlapping anchors:

  - P64  → ``qwen3coder_tool_parser.py``: remove early-return +
           unify </function> emit (TWO sub-patches). PLUS a SECOND target
           ``entrypoints/openai/chat_completion/serving.py`` carrying two
           ``required=False`` sub-patches (safety-net widen + call-site
           guard) that are RETIRED-by-design on dev259+ and 0-match a
           pristine tree (the helper they anchored on was refactored out;
           P107 carries the serving-side role now — journal 2026-06-09).
  - P61c → the commit-trigger block at the top of
           ``extract_tool_calls_streaming``. ONE sub-patch.
  - PN56 → the ``_parse_xml_function_call`` try/except parse-success
           tracking + fallback restore. ONE sub-patch.

This module collapses all three into ONE registry entry (id ``P64``, the
coder primary) with ONE ``apply_module``. P64 is the primary (co-enabled
everywhere); P61c's and PN56's enable flags become ``env_flag_aliases`` on
the merged entry so their existing YAML opt-ins keep engaging the merged
module.

================================================================
DESIGN: SEPARATE TextPatchers PER absorbed patch, EACH WITH ITS OWN MARKER
================================================================

Unlike the chunk_o (PN29+PN298) and rejection_sampler (P71+PN369)
precedents — which build ONE ``TextPatcher`` with all sub-patches and one
shared marker — this cluster keeps one ``TextPatcher`` PER absorbed patch
(P64 keeps its TWO patchers: qwen3coder + serving). Two engine facts force
this:

  1. FAILURE ISOLATION. ``TextPatcher._apply_layer5_legacy`` returns
     SKIPPED for the WHOLE patcher on the FIRST ``required=True`` anchor
     miss (text_patch.py ~524). Merging all three into one patcher would
     mean a P64 anchor drift also skips P61c's and PN56's sub-patches.

  2. NO SHARED-MARKER CROSS-SHADOWING. ``TextPatcher.apply`` Layer 2
     (text_patch.py ~345) returns IDEMPOTENT the instant ``self.marker``
     is in the file, BEFORE applying any sub-patch. If the separate
     patchers shared one marker, patcher #1 would prepend it and the rest
     would no-op their anchors. So each carries a DISTINCT marker — reused
     verbatim from each absorbed patch's ORIGINAL module.

CONSEQUENCE FOR BYTE-EQUIVALENCE (marker carve-out): ``TextPatcher.apply``
prepends one ``# [Genesis wiring marker: <marker>]`` line per successful
patcher (text_patch.py ~435). Keeping the original distinct markers, the
merged module emits the SAME marker lines on each touched file as running
the three originals separately, so the applied output is byte-identical to
P64+P61c+PN56 applied separately INCLUDING marker lines — not merely on
the patched code regions. (P64's qwen3coder marker is suffixed
``:: qwen3coder_tool_parser.py`` and its serving marker
``:: serving.py`` exactly as the original module, so each file keeps its
original single marker.) Byte-equivalence is asserted for the patched CODE
regions in any case.

serving.py STAYS BYTE-UNTOUCHED on pristine: P64's two serving sub-patches
are ``required=False`` and 0-match the dev148/dev259 pristine tree, so the
serving patcher returns SKIPPED (no_applicable_sub_patches) and never
prepends a marker — exactly the original P64 behavior. They are kept here
as a distinct patcher so a <0.23.0 rollback pin whose serving.py still
carries the old helper shape would still get them.

================================================================
PER-FEATURE GATING + VERSION-GATE REPLICATION (the critical correction)
================================================================

All three absorbed patches routed through ``should_apply(...)`` and all
three carry ``applies_to.vllm_version_range=(">=0.20.0", "<0.23.0")`` —
the qwen3coder/qwen3xml tool parsers were deleted/remapped by #45171/#45588
in the dev148-era engine, which owns streaming tool-call extraction
natively; these dev259-era wraps fight the native parser and leak tool-call
XML to content on 0.23.x.

``should_apply``'s version-only gate fires BEFORE the env-override branch
(decision.py ~585 vs ~589) and is LIVE on the rig
(``GENESIS_ENFORCE_VERSION_RANGE=1``, hardware yaml:119, composed into both
PROD configs). A naive direct env check inside this module would BYPASS the
version gate and APPLY the wraps on a >=0.23.0 pin where the files are
still present — corrupting the engine-native parser — while the standalone
originals would version-SKIP. So each per-group helper replicates BOTH the
env gate AND the version gate via
``check_version_constraints({"vllm_version_range": (">=0.20.0","<0.23.0")})``
when ``_version_enforcement_on()`` (mirrors p71_pn369's ``_pn369_enabled``).
The merged registry entry ALSO carries the identical range so
``should_apply("P64")`` version-gate-SKIPs the whole module on dev148.

================================================================

Authors:
  - P64:  Sandermage (Sander) Barzov Aleksandr — backport of
          vllm-project/vllm#39598 (kotori-yan).
  - P61c: Sandermage backport (troymroberts club-3090#72, V2 deferred).
  - PN56: Sandermage backport (ToastyTheBot, vllm-project/vllm#41466).
  - Consolidation: 2026-06-20 (maintainability refactor; runtime-neutral).
"""
from __future__ import annotations

import logging
import os

from sndr.engines.vllm.detection.guards import resolve_vllm_file, vllm_install_root
from sndr.kernel import (
    TextPatch,
    TextPatcher,
    TextPatchResult,
)

log = logging.getLogger(
    "genesis.wiring.p64_p61c_pn56_qwen3coder_consolidated"
)


_PARSER_REL = "tool_parsers/qwen3coder_tool_parser.py"
_SERVING_REL = "entrypoints/openai/chat_completion/serving.py"

# Shared version window — all three absorbed patches carry the identical
# range, so a single constant drives every per-group helper AND the merged
# registry entry's applies_to.
QWEN3CODER_VLLM_VERSION_RANGE = (">=0.20.0", "<0.23.0")


# ════════════════════════════════════════════════════════════════════════
# MARKERS — each absorbed patch keeps its ORIGINAL marker verbatim (P64
# uses a per-file suffix). Re-exported under original names so existing
# tests / drift-residue coverage / operator greps keep resolving.
# ════════════════════════════════════════════════════════════════════════
GENESIS_P64_MARKER = "Genesis P64 qwen3coder MTP streaming early-return fix v7.13"
GENESIS_P61C_MARKER = "Genesis P61c qwen3coder deferred-commit (club-3090#72)"
GENESIS_PN56_MARKER = "Genesis PN56 qwen3coder XML parse fallback (vllm#41466)"


# ════════════════════════════════════════════════════════════════════════
# P64 sub-patches (VERBATIM from p64_qwen3coder_mtp_streaming.py)
# ════════════════════════════════════════════════════════════════════════
P64_QWEN3CODER_OLD = (
    "            if json_fragments:\n"
    "                combined = \"\".join(json_fragments)\n"
    "\n"
    "                if self.current_tool_index < len(self.streamed_args_for_tool):\n"
    "                    self.streamed_args_for_tool[self.current_tool_index] += combined\n"
    "                else:\n"
    "                    logger.warning(\n"
    "                        \"streamed_args_for_tool out of sync: index=%d len=%d\",\n"
    "                        self.current_tool_index,\n"
    "                        len(self.streamed_args_for_tool),\n"
    "                    )\n"
    "\n"
    "                return DeltaMessage(\n"
    "                    tool_calls=[\n"
    "                        DeltaToolCall(\n"
    "                            index=self.current_tool_index,\n"
    "                            function=DeltaFunctionCall(arguments=combined),\n"
    "                        )\n"
    "                    ]\n"
    "                )\n"
)

P64_QWEN3CODER_NEW = (
    "            # [Genesis P64 vllm#39598] Do NOT early-return here. With MTP\n"
    "            # speculative decoding a single delta can bundle the last\n"
    "            # parameter value AND </function> together. An early return\n"
    "            # would skip the </function> block below, leaving\n"
    "            # prev_tool_call_arr with stale \"{}\" and streamed_args_for_tool\n"
    "            # without the closing \"}\". Accumulate into `combined`, let\n"
    "            # </function> path append \"}\", emit ONE return at end.\n"
    "            combined = \"\".join(json_fragments) if json_fragments else \"\"\n"
)

P64_FNEND_OLD = (
    "                if self.current_tool_index < len(self.streamed_args_for_tool):\n"
    "                    self.streamed_args_for_tool[self.current_tool_index] += \"}\"\n"
    "                else:\n"
    "                    logger.warning(\n"
    "                        \"streamed_args_for_tool out of sync: index=%d len=%d\",\n"
    "                        self.current_tool_index,\n"
    "                        len(self.streamed_args_for_tool),\n"
    "                    )\n"
    "\n"
    "                result = DeltaMessage(\n"
    "                    tool_calls=[\n"
    "                        DeltaToolCall(\n"
    "                            index=self.current_tool_index,\n"
    "                            function=DeltaFunctionCall(arguments=\"}\"),\n"
    "                        )\n"
    "                    ]\n"
    "                )\n"
    "\n"
    "                self.in_function = False\n"
    "                self.json_closed = True\n"
    "                self.accumulated_params = {}\n"
    "\n"
    "                return result\n"
)

P64_FNEND_NEW = (
    "                # [Genesis P64 vllm#39598] Append \"}\" to combined and fall\n"
    "                # through to unified emit below — no early return.\n"
    "                # [Audit A-07 fix 2026-05-05] NOTE on `self.json_closed = True`:\n"
    "                # the OLD branch set this here. NEW branch does NOT — it is set\n"
    "                # at the top of the upstream `if not self.json_closed and ...`\n"
    "                # branch above (parser line ~626 in current pin). Not a bug,\n"
    "                # just non-redundant: removing avoids double-set; runtime\n"
    "                # invariant preserved by upstream parser logic.\n"
    "                combined += \"}\"\n"
    "                self.in_function = False\n"
    "                self.accumulated_params = {}\n"
    "\n"
    "            if combined:\n"
    "                if self.current_tool_index < len(self.streamed_args_for_tool):\n"
    "                    self.streamed_args_for_tool[self.current_tool_index] += combined\n"
    "                else:\n"
    "                    logger.warning(\n"
    "                        \"streamed_args_for_tool out of sync: index=%d len=%d\",\n"
    "                        self.current_tool_index,\n"
    "                        len(self.streamed_args_for_tool),\n"
    "                    )\n"
    "\n"
    "                return DeltaMessage(\n"
    "                    tool_calls=[\n"
    "                        DeltaToolCall(\n"
    "                            index=self.current_tool_index,\n"
    "                            function=DeltaFunctionCall(arguments=combined),\n"
    "                        )\n"
    "                    ]\n"
    "                )\n"
)

# P64 serving.py sub-patches — RETIRED-by-design on dev259+ (required=False,
# 0-match on pristine). Kept for <0.23.0 rollback pins that still carry the
# old serving-layer helper shape. See P64_RETIRED_SUBS.
P64_SERVING_SHOULD_OLD = (
    "        return bool(\n"
    "            # if there is a delta message that includes tool calls which\n"
    "            # include a function that has arguments\n"
    "            output.finish_reason is not None\n"
    "            and self.enable_auto_tools\n"
    "            and self.tool_parser\n"
    "            and delta_message\n"
    "            and delta_message.tool_calls\n"
    "            and delta_message.tool_calls[0]\n"
    "            and delta_message.tool_calls[0].function\n"
    "            and delta_message.tool_calls[0].function.arguments is not None\n"
    "        )\n"
)

P64_SERVING_SHOULD_NEW = (
    "        # [Genesis P64 vllm#39598] Widen safety-net: with MTP/spec-decode\n"
    "        # the final delta before finish_reason may carry no tool_calls\n"
    "        # even though tool calls are still in progress. Caller's\n"
    "        # auto_tools_called guard (checks len(prev_tool_call_arr) > 0)\n"
    "        # prevents false positives for plain-text responses.\n"
    "        return bool(\n"
    "            output.finish_reason is not None\n"
    "            and self.enable_auto_tools\n"
    "            and self.tool_parser\n"
    "        )\n"
)

P64_SERVING_CALLSITE_OLD = (
    "                        if should_check and tool_parser and auto_tools_called:\n"
    "                            latest_delta_len = 0\n"
    "                            if (\n"
    "                                isinstance(\n"
    "                                    delta_message.tool_calls[0].function,\n"
    "                                    DeltaFunctionCall,\n"
    "                                )\n"
    "                            ) and isinstance(\n"
    "                                delta_message.tool_calls[0].function.arguments, str\n"
    "                            ):\n"
)

P64_SERVING_CALLSITE_NEW = (
    "                        if should_check and tool_parser and auto_tools_called:\n"
    "                            latest_delta_len = 0\n"
    "                            # [Genesis P64 call-site guard] _should_check\n"
    "                            # fires on finish_reason alone; tool_calls may\n"
    "                            # be [] on the final delta — guard before [0].\n"
    "                            if (\n"
    "                                delta_message.tool_calls\n"
    "                                and isinstance(\n"
    "                                    delta_message.tool_calls[0].function,\n"
    "                                    DeltaFunctionCall,\n"
    "                                )\n"
    "                            ) and isinstance(\n"
    "                                delta_message.tool_calls[0].function.arguments, str\n"
    "                            ):\n"
)

# Preflight KNOWN_OPTIONAL_RETIRED convention (*_RETIRED_SUBS): the two
# optional serving-side subs are retired-by-design on dev259 (the helper
# they anchored on was refactored out; P107 carries the serving-side role
# now). Zero anchor matches on a pristine tree is the documented steady
# state, NOT drift — tools/pin_preflight.py reads this attr.
P64_RETIRED_SUBS = ("p64_safety_net_widen", "p64_callsite_guard")

P64_DRIFT_MARKERS = [
    "[Genesis P64 vllm#39598]",
]


# ════════════════════════════════════════════════════════════════════════
# P61c sub-patch (VERBATIM from p61c_qwen3coder_deferred_commit.py)
# ════════════════════════════════════════════════════════════════════════
P61C_ANCHOR_OLD = (
    "            if (\n"
    "                self.tool_call_start_token_id in delta_token_ids\n"
    "                or self.tool_call_start_token in delta_text\n"
    "            ):\n"
    "                self.is_tool_call_started = True\n"
    "                # Return any content before the tool call\n"
    "                if self.tool_call_start_token in delta_text:\n"
    "                    content_before = delta_text[\n"
    "                        : delta_text.index(self.tool_call_start_token)\n"
    "                    ]\n"
    "                    if content_before:\n"
    "                        return DeltaMessage(content=content_before)\n"
    "                return None\n"
)

P61C_ANCHOR_NEW = (
    "            # [Genesis P61c club-3090#72] Defer commit until <function=\n"
    "            # header follows the <tool_call> token within a 64-char slack\n"
    "            # window. Guards against the model emitting <tool_call> (as\n"
    "            # special token OR string) in narrative reasoning without an\n"
    "            # actual tool-call header — a case that flips\n"
    "            # is_tool_call_started=True permanently and silently drops\n"
    "            # all subsequent content via the serving layer's\n"
    "            # `if delta_message is None: continue` path. Three paths:\n"
    "            #   A) token-id present but tag string not in current_text\n"
    "            #      (tokenizer edge case) → emit content, don't commit\n"
    "            #   B) <function= confirmed in slack → original commit path\n"
    "            #   C) no <function= yet → emit content, never silently drop\n"
    "            if (\n"
    "                self.tool_call_start_token_id in delta_token_ids\n"
    "                or self.tool_call_start_token in delta_text\n"
    "            ):\n"
    "                _tc_idx = current_text.find(self.tool_call_start_token)\n"
    "                if _tc_idx == -1:\n"
    "                    # Path A: token-id-only, conservative emit-as-content\n"
    "                    return DeltaMessage(content=delta_text or None)\n"
    "                _slack_end = (\n"
    "                    _tc_idx + len(self.tool_call_start_token) + 64\n"
    "                )\n"
    '                if "<function=" in current_text[_tc_idx:_slack_end]:\n'
    "                    # Path B: real tool call confirmed; original commit\n"
    "                    self.is_tool_call_started = True\n"
    "                    if self.tool_call_start_token in delta_text:\n"
    "                        content_before = delta_text[\n"
    "                            : delta_text.index(self.tool_call_start_token)\n"
    "                        ]\n"
    "                        if content_before:\n"
    "                            return DeltaMessage(content=content_before)\n"
    "                    return None\n"
    "                # Path C: <function= not yet present; emit delta as\n"
    "                # content. If <function= eventually arrives within slack\n"
    "                # we'll commit then; otherwise we've correctly streamed\n"
    "                # the prose containing literal <tool_call> mention.\n"
    "                return DeltaMessage(content=delta_text or None)\n"
)

P61C_DRIFT_MARKERS = [
    "[Genesis P61c",
]


# ════════════════════════════════════════════════════════════════════════
# PN56 sub-patch (VERBATIM from pn56_qwen3coder_xml_fallback.py)
# ════════════════════════════════════════════════════════════════════════
PN56_ANCHOR_A_OLD = (
    "                if func_content_end != -1:\n"
    "                    func_content = tool_text[func_start:func_content_end]\n"
    "                    try:\n"
    "                        parsed_tool = self._parse_xml_function_call(\n"
    "                            func_content,\n"
    "                        )\n"
    "                        if parsed_tool and self.current_tool_index < len(\n"
    "                            self.prev_tool_call_arr\n"
    "                        ):\n"
    "                            self.prev_tool_call_arr[self.current_tool_index][\n"
    "                                \"arguments\"\n"
    "                            ] = parsed_tool.function.arguments\n"
    "                    except Exception:\n"
    "                        logger.debug(\n"
    "                            \"Failed to parse tool call during streaming: %s\",\n"
    "                            tool_text,\n"
    "                            exc_info=True,\n"
    "                        )"
)

PN56_ANCHOR_A_NEW = (
    "                if func_content_end != -1:\n"
    "                    func_content = tool_text[func_start:func_content_end]\n"
    "                    # [Genesis PN56 vllm#41466] Track parse success to know\n"
    "                    # if fallback below should fire (else \"{}\" placeholder leaks).\n"
    "                    _pn56_parse_succeeded = False\n"
    "                    try:\n"
    "                        parsed_tool = self._parse_xml_function_call(\n"
    "                            func_content,\n"
    "                        )\n"
    "                        if parsed_tool and self.current_tool_index < len(\n"
    "                            self.prev_tool_call_arr\n"
    "                        ):\n"
    "                            self.prev_tool_call_arr[self.current_tool_index][\n"
    "                                \"arguments\"\n"
    "                            ] = parsed_tool.function.arguments\n"
    "                            _pn56_parse_succeeded = True\n"
    "                    except Exception:\n"
    "                        logger.debug(\n"
    "                            \"Failed to parse tool call during streaming: %s\",\n"
    "                            tool_text,\n"
    "                            exc_info=True,\n"
    "                        )\n"
    "                    # [Genesis PN56 vllm#41466] When parse failed, prev_tool_call_arr\n"
    "                    # still has \"{}\" placeholder. Restore from incrementally\n"
    "                    # streamed args + closing brace so serving layer remainder\n"
    "                    # check produces correct output instead of double-emit \"{}\".\n"
    "                    if (\n"
    "                        not _pn56_parse_succeeded\n"
    "                        and self.current_tool_index < len(self.prev_tool_call_arr)\n"
    "                        and self.current_tool_index < len(self.streamed_args_for_tool)\n"
    "                    ):\n"
    "                        # [Audit A-14 fix 2026-05-05] Guard against double `}}`\n"
    "                        # if streamed_args already ends with closing brace\n"
    "                        # (P64 may have written it, or a prior partial close).\n"
    "                        _pn56_streamed = self.streamed_args_for_tool[\n"
    "                            self.current_tool_index\n"
    "                        ]\n"
    "                        _pn56_suffix = \"\" if _pn56_streamed.rstrip().endswith(\"}\") else \"}\"\n"
    "                        self.prev_tool_call_arr[self.current_tool_index][\n"
    "                            \"arguments\"\n"
    "                        ] = _pn56_streamed + _pn56_suffix"
)

PN56_DRIFT_MARKERS = [
    "[Genesis PN56",
]


# ─── Bare env-flag names (no GENESIS_ENABLE_/SNDR_ENABLE_ prefix) ──────────
_P64_FLAG = "P64_QWEN3CODER_MTP_STREAMING"
_P61C_FLAG = "P61C_QWEN3CODER_DEFERRED_COMMIT"
_PN56_FLAG = "PN56_QWEN3CODER_XML_FALLBACK"

# Back-compat re-exports of the original anchor names some unit tests read
# directly (the standalone modules used these bare names).
# P61c anchors (standalone P61c module exported ANCHOR_OLD/ANCHOR_NEW).
ANCHOR_OLD = P61C_ANCHOR_OLD
ANCHOR_NEW = P61C_ANCHOR_NEW
# PN56 anchors (standalone PN56 module exported ANCHOR_A_OLD/ANCHOR_A_NEW).
ANCHOR_A_OLD = PN56_ANCHOR_A_OLD
ANCHOR_A_NEW = PN56_ANCHOR_A_NEW
# P64 anchors (standalone P64 module exported these bare names — read by the
# legacy v7.14/15 audit test).
QWEN3CODER_OLD = P64_QWEN3CODER_OLD
QWEN3CODER_NEW = P64_QWEN3CODER_NEW
QWEN3COD_FNEND_OLD = P64_FNEND_OLD
QWEN3COD_FNEND_NEW = P64_FNEND_NEW
SERVING_SHOULD_OLD = P64_SERVING_SHOULD_OLD
SERVING_SHOULD_NEW = P64_SERVING_SHOULD_NEW
SERVING_CALLSITE_OLD = P64_SERVING_CALLSITE_OLD
SERVING_CALLSITE_NEW = P64_SERVING_CALLSITE_NEW


# ════════════════════════════════════════════════════════════════════════
# Version-gate-replicating per-group enable helpers.
# ════════════════════════════════════════════════════════════════════════
def _env_on(bare_flag: str) -> bool:
    from sndr.env import is_disabled, is_enabled

    return is_enabled(bare_flag) and not is_disabled(bare_flag)


def _version_ok() -> bool:
    """True iff the running engine is in the <0.23.0 window OR version
    enforcement is OFF. Replicates should_apply's version-only gate
    (decision.py::_check_version_gate) which fires before the env branch."""
    from sndr.dispatcher.decision import _version_enforcement_on

    if not _version_enforcement_on():
        return True
    from sndr.compat.version_check import check_version_constraints

    v_ok, _ = check_version_constraints(
        {"vllm_version_range": QWEN3CODER_VLLM_VERSION_RANGE}
    )
    return v_ok


def _p64_enabled() -> bool:
    return _env_on(_P64_FLAG) and _version_ok()


def _p61c_enabled() -> bool:
    return _env_on(_P61C_FLAG) and _version_ok()


def _pn56_enabled() -> bool:
    return _env_on(_PN56_FLAG) and _version_ok()


# ════════════════════════════════════════════════════════════════════════
# Per-group TextPatcher factories — bundles/tool_parsing_qwen3coder.py calls
# these directly (P64 keeps its TWO factories: qwen3cod + serving).
# ════════════════════════════════════════════════════════════════════════
def _make_p64_qwen3cod_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(_PARSER_REL)
    if target is None:
        return None
    return TextPatcher(
        patch_name="P64 qwen3coder_tool_parser.py — MTP streaming early-return removal",
        target_file=str(target),
        marker=GENESIS_P64_MARKER + " :: qwen3coder_tool_parser.py",
        sub_patches=[
            TextPatch(name="p64_remove_early_return", anchor=P64_QWEN3CODER_OLD,
                      replacement=P64_QWEN3CODER_NEW, required=True),
            TextPatch(name="p64_unify_emit_at_fnend", anchor=P64_FNEND_OLD,
                      replacement=P64_FNEND_NEW, required=True),
        ],
        upstream_drift_markers=list(P64_DRIFT_MARKERS),
    )


def _make_p64_serving_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(_SERVING_REL)
    if target is None:
        return None
    return TextPatcher(
        patch_name="P64 serving.py — MTP safety-net + call-site guard",
        target_file=str(target),
        marker=GENESIS_P64_MARKER + " :: serving.py",
        sub_patches=[
            # RETIRED-by-design on dev259+ (required=False, 0-match pristine).
            TextPatch(name="p64_safety_net_widen", anchor=P64_SERVING_SHOULD_OLD,
                      replacement=P64_SERVING_SHOULD_NEW, required=False),
            TextPatch(name="p64_callsite_guard", anchor=P64_SERVING_CALLSITE_OLD,
                      replacement=P64_SERVING_CALLSITE_NEW, required=False),
        ],
        upstream_drift_markers=list(P64_DRIFT_MARKERS),
    )


def _make_p61c_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(_PARSER_REL)
    if target is None:
        return None
    return TextPatcher(
        patch_name="P61c qwen3coder deferred-commit (club-3090#72)",
        target_file=str(target),
        marker=GENESIS_P61C_MARKER,
        sub_patches=[TextPatch(
            name="p61c_deferred_commit",
            anchor=P61C_ANCHOR_OLD,
            replacement=P61C_ANCHOR_NEW,
            required=True,
        )],
        upstream_drift_markers=list(P61C_DRIFT_MARKERS),
    )


def _make_pn56_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(_PARSER_REL)
    if target is None:
        return None
    return TextPatcher(
        patch_name="PN56 qwen3coder XML fallback (vllm#41466)",
        target_file=str(target),
        marker=GENESIS_PN56_MARKER,
        sub_patches=[TextPatch(
            name="pn56_xml_fallback",
            anchor=PN56_ANCHOR_A_OLD,
            replacement=PN56_ANCHOR_A_NEW,
            required=True,
        )],
        upstream_drift_markers=list(PN56_DRIFT_MARKERS),
    )

def _make_patcher() -> TextPatcher | None:
    """Drift-tool / static entry point: ONE TextPatcher carrying ALL the
    PARSER-file sub-patches UNCONDITIONALLY (P64's 2 + P61c's 1 + PN56's 1).

    ``tools/check_upstream_drift.py`` builds the patcher from this function
    and verifies every PARSER-file anchor is present-and-unique in the
    pristine tree. Covers only the qwen3coder_tool_parser.py target; P64's
    serving.py subs are required=False/0-match-on-pristine (retired-by-design)
    so the drift tool does NOT scan them (they would report not-found on
    pristine, which is the documented steady state). The marker here is
    cosmetic for the anchor scan (pristine has no markers); live apply() uses
    distinct per-feature markers.
    """
    target = resolve_vllm_file(_PARSER_REL)
    if target is None:
        return None
    return TextPatcher(
        patch_name=(
            "P64+P61c+PN56 tool_parsers/qwen3coder_tool_parser.py — MTP "
            "streaming early-return removal (vllm#39598) + deferred-commit "
            "(club-3090#72) + XML parse fallback (vllm#41466)"
        ),
        target_file=str(target),
        marker=GENESIS_P64_MARKER + " :: qwen3coder_tool_parser.py",
        sub_patches=[
            TextPatch(name="p64_remove_early_return", anchor=P64_QWEN3CODER_OLD,
                      replacement=P64_QWEN3CODER_NEW, required=True),
            TextPatch(name="p64_unify_emit_at_fnend", anchor=P64_FNEND_OLD,
                      replacement=P64_FNEND_NEW, required=True),
            TextPatch(name="p61c_deferred_commit", anchor=P61C_ANCHOR_OLD,
                      replacement=P61C_ANCHOR_NEW, required=True),
            TextPatch(name="pn56_xml_fallback", anchor=PN56_ANCHOR_A_OLD,
                      replacement=PN56_ANCHOR_A_NEW, required=True),
        ],
        upstream_drift_markers=[
            *P64_DRIFT_MARKERS,
            *P61C_DRIFT_MARKERS,
            *PN56_DRIFT_MARKERS,
        ],
    )


def _apply_patcher(patcher, group_label, *, allow_no_subs=False):
    """Apply one per-group patcher. Returns (status, reason, applied_subs).

    ``allow_no_subs=True`` (P64 serving) treats SKIPPED/no_applicable_sub_
    patches as a clean no-op rather than a feature skip — the serving subs
    are retired-by-design and 0-match pristine."""
    if patcher is None:
        return "skipped", f"{group_label}: target file not found", []
    result, failure = patcher.apply()
    if result == TextPatchResult.APPLIED:
        return "applied", f"{group_label} applied", list(patcher.applied_sub_patches)
    if result == TextPatchResult.IDEMPOTENT:
        return "applied", f"{group_label} idempotent (marker present)", []
    if result == TextPatchResult.SKIPPED:
        reason = failure.reason if failure else "anchor not found"
        if allow_no_subs and reason == "no_applicable_sub_patches":
            return "noop", f"{group_label}: no applicable sub-patches (retired-by-design)", []
        detail = f" ({failure.detail})" if (failure and failure.detail) else ""
        return "skipped", f"{group_label}: {reason}{detail}", []
    return "failed", (
        f"{group_label}: {failure.reason if failure else 'unknown failure'}"
    ), []


def apply() -> tuple[str, str]:
    """Apply P64 + P61c + PN56 (consolidated) — each feature independently
    operator-gated (env + replicated version gate) and applied by its OWN
    TextPatcher (failure isolation + distinct marker). P64 keeps its two
    patchers (parser + serving); serving stays byte-untouched on pristine."""
    p64_on = _p64_enabled()
    p61c_on = _p61c_enabled()
    pn56_on = _pn56_enabled()

    if not (p64_on or p61c_on or pn56_on):
        return "skipped", (
            "P64+P61c+PN56 all default OFF (or version-gated on this pin) — "
            "set GENESIS_ENABLE_P64_QWEN3CODER_MTP_STREAMING=1 (MTP "
            "early-return fix), GENESIS_ENABLE_P61C_QWEN3CODER_DEFERRED_"
            "COMMIT=1 (deferred-commit) and/or "
            "GENESIS_ENABLE_PN56_QWEN3CODER_XML_FALLBACK=1 (XML parse "
            "fallback) to engage. In-window pins only. Each flag "
            "independently gates its own sub-patches."
        )

    if vllm_install_root() is None:
        return "skipped", "vllm install root not discoverable"

    if resolve_vllm_file(_PARSER_REL) is None:
        return "skipped", "qwen3coder_tool_parser.py not found"

    statuses: list[str] = []
    failures: list[str] = []
    engaged: list[str] = []

    # P64 group — TWO patchers (parser + serving). serving is allow_no_subs.
    if p64_on:
        st, reason, _ = _apply_patcher(
            _make_p64_qwen3cod_patcher(), "P64 parser early-return fix"
        )
        statuses.append(st)
        if st == "failed":
            failures.append(reason)
        elif st in ("applied",):
            engaged.append("P64 parser early-return fix")
        st_s, reason_s, _ = _apply_patcher(
            _make_p64_serving_patcher(), "P64 serving safety-net",
            allow_no_subs=True,
        )
        statuses.append(st_s)
        if st_s == "failed":
            failures.append(reason_s)
        elif st_s == "applied":
            engaged.append("P64 serving safety-net")

    # P61c group.
    if p61c_on:
        st, reason, _ = _apply_patcher(
            _make_p61c_patcher(), "P61c deferred-commit"
        )
        statuses.append(st)
        if st == "failed":
            failures.append(reason)
        elif st == "applied":
            engaged.append("P61c deferred-commit")

    # PN56 group.
    if pn56_on:
        st, reason, _ = _apply_patcher(
            _make_pn56_patcher(), "PN56 XML parse fallback"
        )
        statuses.append(st)
        if st == "failed":
            failures.append(reason)
        elif st == "applied":
            engaged.append("PN56 XML parse fallback")

    if failures:
        return "failed", "; ".join(failures)
    if "applied" in statuses:
        return "applied", (
            "P64+P61c+PN56 consolidated installed ("
            + ", ".join(engaged or ["none"])
            + ") in qwen3coder_tool_parser.py (serving.py byte-untouched on "
            "pristine — retired serving subs 0-match by design). Each "
            "feature carries its own marker; apply set byte-equivalent to "
            "the three originals."
        )
    return "skipped", "P64+P61c+PN56: every enabled group skipped (anchor drift or upstream merge)"


def is_applied() -> bool:
    """Best-effort idempotency probe — True iff the three PARSER-file
    markers (P64 qwen3coder, P61c, PN56) are all present in the parser
    file. The serving marker is intentionally NOT required (serving subs
    are retired-by-design and 0-match pristine)."""
    target = resolve_vllm_file(_PARSER_REL)
    if target is None:
        return False
    try:
        with open(str(target), "r", encoding="utf-8", errors="ignore") as fh:
            content = fh.read()
    except OSError:
        return False
    return all(
        m in content
        for m in (
            GENESIS_P64_MARKER + " :: qwen3coder_tool_parser.py",
            GENESIS_P61C_MARKER,
            GENESIS_PN56_MARKER,
        )
    )
