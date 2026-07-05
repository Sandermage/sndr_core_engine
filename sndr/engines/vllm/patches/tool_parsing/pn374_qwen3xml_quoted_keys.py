# SPDX-License-Identifier: Apache-2.0
"""PN374 — qwen3xml quoted parameter-name (key) sanitization.

RETIRED 2026-07-05 (lifecycle: retired, cap kept <0.23.0): #45588 DELETED
tool_parsers/qwen3xml_tool_parser.py; both PN374 anchors are GONE on pristine
dev748 and the native vllm/parser/qwen3.py json.dumps(..., ensure_ascii=False)
path escapes keys AND values, so the quoted-key corruption is structurally
impossible. Still applies on the dev259 rollback pin where the old file exists.

Problem
-------
Roadmap 2026-06-11 (50-PR sweep, chunk 4 Theme 1) mandated an audit of
``vllm/tool_parsers/qwen3xml_tool_parser.py`` for the same key/value
asymmetry the Gemma4 parser has (issue vllm#44715, fixed by the PR
#44877 quoted-key branch vendored into the G4_T1 overlays this sweep).

Audit verdict on pin 0.22.1rc1.dev259+g303916e93: the asymmetry EXISTS,
expressed in the qwen3xml tag format instead of STRING_DELIM:

* Values are SAFE — ``_convert_for_json_streaming`` escapes string
  values via ``json.dumps`` and complex values re-emit through
  literal_eval + json, so a model-emitted quote inside a value can
  never corrupt the arguments JSON.
* Keys are UNSAFE at two sites:

  1. ``_preprocess_xml_chunk`` rewrites ``<parameter=NAME>`` into
     ``<parameter name="NAME">`` with a verbatim ``([^>]+)`` capture.
     A model-emitted quoted key — ``<parameter="3">``, the direct
     analog of Gemma4's ``<|"|>3<|"|>`` string-typed key marker —
     becomes the malformed attribute ``name=""3""``, which makes the
     expat parse of the element fail: the whole parameter is silently
     dropped from the tool-call arguments.
  2. ``_extract_parameter_name``'s ``parameter=NAME`` split fallback
     returns the name verbatim, and ``_start_element`` interpolates it
     UNESCAPED into the streamed arguments JSON
     (``f'{{\"{param_name}\": '``) — any quote retained in the key
     yields invalid JSON on the client.

Fix
---
Strip surrounding whitespace and quote wrappers (``"`` / ``'``) from
the captured parameter name at both sites. This mirrors upstream PR
#44877's Gemma4 semantics (delimiters around a key are markers, never
payload) adapted to the XML-ish tag format. The ``attrs["name"]``
short-circuit in ``_extract_parameter_name`` needs no hunk: expat only
ever sees text already rewritten by site 1, and its two-line body is
textually ambiguous with ``_extract_function_name`` (anchor count==2).

Genesis-original (no upstream PR fixes qwen3xml keys as of
2026-06-11), hence no ``upstream_drift_markers`` — there is no known
upstream spelling to detect; anchor drift detection covers the rest.

Verification: both anchors byte-verified count==1 against the pristine
pin tree (/private/tmp/candidate_pin_current/vllm/tool_parsers/
qwen3xml_tool_parser.py, 2026-06-11).

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
"""
from __future__ import annotations

import logging

from sndr.engines.vllm.detection.guards import resolve_vllm_file
from sndr.env import Flags, is_enabled
from sndr.kernel import TextPatch, TextPatcher, TextPatchResult

log = logging.getLogger("genesis.wiring.pn374_qwen3xml_quoted_keys")

GENESIS_PN374_MARKER = "Genesis PN374 qwen3xml quoted parameter-name strip v1"

# Full env var name (for tests / operator docs); the canonical bare flag
# lives in sndr.env.Flags.PN374_QWEN3XML_QUOTED_KEYS.
ENV_FLAG_FULL = "GENESIS_ENABLE_PN374_QWEN3XML_QUOTED_KEYS"

_TARGET_RELPATH = "tool_parsers/qwen3xml_tool_parser.py"


# Site 1 — `_preprocess_xml_chunk`: the <parameter=NAME> rewrite.
ANCHOR_A_OLD = (
    '        # Handle <parameter=name> format -> <parameter name="name">\n'
    "        processed = re.sub("
    "r\"<parameter=([^>]+)>\", r'<parameter name=\"\\1\">', processed)\n"
)

ANCHOR_A_NEW = (
    '        # Handle <parameter=name> format -> <parameter name="name">\n'
    "        # [Genesis PN374] Strip quote wrappers the model may emit\n"
    "        # around a parameter name (e.g. <parameter=\"3\"> to mark a\n"
    "        # numeric-looking key as a string). Values are JSON-escaped\n"
    "        # downstream but keys are interpolated verbatim into the\n"
    "        # arguments JSON, and an unstripped quoted key first kills\n"
    "        # the expat parse (name=\"\"3\"\") so the parameter is lost.\n"
    "        # Same bug class as the Gemma4 quoted key (vllm#44715).\n"
    "        processed = re.sub(\n"
    '            r"<parameter=([^>]+)>",\n'
    "            lambda _pn374_m: '<parameter name=\"{}\">'.format(\n"
    "                _pn374_m.group(1).strip().strip(\"'\\\"\")\n"
    "            ),\n"
    "            processed,\n"
    "        )\n"
)

# Site 2 — `_extract_parameter_name`: the parameter=NAME split fallback.
ANCHOR_B_OLD = (
    '        if "=" in name:\n'
    '            parts = name.split("=", 1)\n'
    '            if len(parts) == 2 and parts[0] == "parameter":\n'
    "                return parts[1]\n"
)

ANCHOR_B_NEW = (
    '        if "=" in name:\n'
    '            parts = name.split("=", 1)\n'
    '            if len(parts) == 2 and parts[0] == "parameter":\n'
    "                # [Genesis PN374] Strip quote wrappers from the raw\n"
    "                # element-name fallback path too (see preprocess\n"
    "                # hunk); the name is interpolated unescaped into\n"
    "                # the streamed arguments JSON by _start_element.\n"
    "                return parts[1].strip().strip(\"'\\\"\")\n"
)


def _make_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(_TARGET_RELPATH)
    if target is None:
        return None
    return TextPatcher(
        patch_name="PN374 qwen3xml quoted parameter-name strip",
        target_file=target,
        marker=GENESIS_PN374_MARKER,
        sub_patches=[
            TextPatch(
                name="pn374_preprocess_param_name",
                anchor=ANCHOR_A_OLD,
                replacement=ANCHOR_A_NEW,
                required=True,
            ),
            TextPatch(
                name="pn374_extract_param_name_fallback",
                anchor=ANCHOR_B_OLD,
                replacement=ANCHOR_B_NEW,
                required=True,
            ),
        ],
    )


def apply() -> tuple[str, str]:
    """Apply PN374 wiring. Never raises."""
    if not is_enabled(Flags.PN374_QWEN3XML_QUOTED_KEYS):
        return "skipped", (
            f"PN374 disabled (set {ENV_FLAG_FULL}=1 to strip quote "
            "wrappers from qwen3xml parameter names — Gemma4 #44715 "
            "bug-class analog)"
        )
    patcher = _make_patcher()
    if patcher is None:
        return "skipped", f"{_TARGET_RELPATH} not found in vllm install"
    result, failure = patcher.apply()
    if result == TextPatchResult.APPLIED:
        return "applied", (
            "PN374 applied: qwen3xml parameter names are stripped of "
            "quote wrappers before XML attr rewrite + JSON interpolation"
        )
    if result == TextPatchResult.IDEMPOTENT:
        return "applied", "already applied this image layer (idempotent)"
    if result == TextPatchResult.SKIPPED:
        msg = failure.reason if failure else "anchor not found"
        return "skipped", f"{msg} — likely upstream reshaped the parser"
    return "failed", failure.reason if failure else "unknown failure"


def is_applied() -> bool:
    patcher = _make_patcher()
    if patcher is None:
        return False
    try:
        target = patcher.target_file
        with open(target, encoding="utf-8") as fh:
            return GENESIS_PN374_MARKER in fh.read()
    except OSError:
        return False


__all__ = [
    "GENESIS_PN374_MARKER",
    "ENV_FLAG_FULL",
    "ANCHOR_A_OLD",
    "ANCHOR_A_NEW",
    "ANCHOR_B_OLD",
    "ANCHOR_B_NEW",
    "apply",
    "is_applied",
]
