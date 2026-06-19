# SPDX-License-Identifier: Apache-2.0
"""Consolidated wiring for P61b + P59 + PN51 — all three text-patch the SAME
engine file ``reasoning/qwen3_reasoning_parser.py`` at DISJOINT regions.

================================================================
WHY THIS MODULE EXISTS (maintainability refactor, 2026-06-20)
================================================================

P61b (Qwen3 streaming partial-tag overlap guard, vllm#40783 slice), P59
(Qwen3 reasoning embedded tool_call recovery, vllm#39055) and PN51 (Qwen3
streaming ``enable_thinking=false`` content routing, vllm#40816/#40820)
historically lived in three separate wiring modules, each with its own
``TextPatcher`` and its own ``# [Genesis wiring marker: ...]`` line, even
though they patch the same file at non-overlapping anchors:

  - P61b → import of ``partial_tag_overlap`` + the streaming "still in
           reasoning" fallback emission. TWO sub-patches.
  - P59  → ``import re`` + the ``_EMBEDDED_TOOL_CALL_RE`` constant + the
           ``_split_embedded_tool_calls`` staticmethod + up to two
           ``</think>``-present wrap variants (C: P27-chain, D: pristine)
           + the truncated-output wrap. UP TO SIX sub-patches.
  - PN51 → the ``not self.thinking_enabled`` streaming short-circuit. ONE
           sub-patch.

This module collapses all three into ONE registry entry (id ``P61b``, the
reasoning primary) with ONE ``apply_module``. P61b is the primary because
P59 is enabled in ZERO builtin YAMLs while P61b is co-enabled everywhere
the coder primary P64 is; P59's and PN51's enable flags become
``env_flag_aliases`` on the merged entry so their existing YAML opt-ins
keep engaging the merged module.

================================================================
DESIGN: THREE SEPARATE TextPatchers, EACH WITH ITS OWN ORIGINAL MARKER
================================================================

Unlike the chunk_o (PN29+PN298) and rejection_sampler (P71+PN369)
precedents — which build ONE ``TextPatcher`` with all sub-patches and one
shared marker — this cluster MUST keep one ``TextPatcher`` PER absorbed
patch. Two engine-level facts force this:

  1. FAILURE ISOLATION. ``TextPatcher._apply_layer5_legacy`` returns
     SKIPPED for the WHOLE patcher on the FIRST ``required=True`` anchor
     miss (text_patch.py ~524). Merging all three into one patcher would
     mean a P61b anchor drift also skips P59's and PN51's sub-patches —
     a regression vs the three originals, where each failed in isolation.
     So each absorbed patch is its OWN patcher with its OWN ``apply()``.

  2. NO SHARED-MARKER CROSS-SHADOWING. ``TextPatcher.apply`` Layer 2
     (text_patch.py ~345) returns IDEMPOTENT the instant ``self.marker``
     is found in the file, BEFORE applying any sub-patch. If the three
     separate patchers shared ONE marker, patcher #1 would prepend it and
     patchers #2/#3 would see it and no-op their own anchors. So each
     patcher carries a DISTINCT marker — and we reuse each absorbed
     patch's ORIGINAL marker verbatim (re-exported below).

CONSEQUENCE FOR BYTE-EQUIVALENCE (marker carve-out — STRONGER than the
precedents): ``TextPatcher.apply`` prepends one
``# [Genesis wiring marker: <marker>]`` line per successful patcher
(text_patch.py ~435). Because we keep THREE distinct markers (one per
absorbed patch, verbatim), the merged module emits the SAME THREE marker
lines as running the three original modules separately. So on a <0.23.0
rollback pin where the file exists and the patches apply, the applied
output is byte-identical to P61b+P59+PN51 applied separately INCLUDING the
marker lines — not merely on the patched code regions. (The chunk_o /
p71_pn369 precedents accept an N-1 marker-line delta; this design has a
zero marker-line delta because it preserves the per-feature markers.)
Byte-equivalence is asserted for the patched CODE regions in any case; the
marker lines happen to coincide here too.

================================================================
PER-FEATURE GATING + VERSION-GATE REPLICATION (the critical correction)
================================================================

All three absorbed patches routed through the dispatcher's
``should_apply(...)`` and all three carry
``applies_to.vllm_version_range=(">=0.20.0", "<0.23.0")`` (the qwen3
reasoning+tool parser was restructured by #45413/#45588 in the dev148-era
engine, which owns embedded-tool-call recovery natively; these dev259-era
wraps would fight the native parser on 0.23.x).

``should_apply``'s version-only gate (``_check_version_gate``) fires
BEFORE the env-override branch (decision.py ~585 vs ~589) and is LIVE on
the rig (``GENESIS_ENFORCE_VERSION_RANGE=1``, composed from the a5000-2x
hardware yaml into both PROD configs). So a naive direct env check
(``is_enabled and not is_disabled``) inside this module would BYPASS the
version gate and APPLY the wraps on a >=0.23.0 pin where the file is still
present — corrupting the engine-native parser, the exact failure the cap
guards — while the standalone originals (routing through ``should_apply``)
would version-SKIP. The chunk_o precedent's DIRECT env check does NOT
transfer here: chunk_o's range INCLUDES the live pin, this cluster's
EXCLUDES it.

FIX (mirrors p71_pn369's ``_pn369_enabled()``): each per-group helper
replicates BOTH the env gate AND the version gate — it calls
``check_version_constraints({"vllm_version_range": (">=0.20.0","<0.23.0")})``
when ``_version_enforcement_on()``. The merged registry entry ALSO carries
``vllm_version_range=(">=0.20.0", "<0.23.0")`` (all three absorbed patches
share the identical range, so the entry-level range is correct and does
not over-gate), so ``should_apply("P61b")`` version-gate-SKIPs the whole
module on dev148 too.

================================================================
P59 REQUIRE-AT-LEAST-ONE — SCOPED TO THE P59 GROUP ONLY
================================================================

P59 is only functional when ONE of its core ``</think>``-present wrap
variants (C: P27-chain, D: pristine) actually landed; the injected helper
alone is dead code. The original P59 ``apply()`` enforced
require-at-least-one over ``_CORE_WRAP_SUB_NAMES`` and reported "failed"
otherwise. That gate is carried VERBATIM and scoped strictly to the P59
patcher's ``applied_sub_patches`` — it does NOT consider P61b's or PN51's
results. Likewise P59's ``no_applicable_sub_patches`` semantics stay local
to the P59 patcher.

================================================================

Authors:
  - P61b: Sandermage (Sander) Barzov Aleksandr — backport slice of
          vllm-project/vllm#40783 (ExtReMLapin).
  - P59:  Sandermage (Sander) Barzov Aleksandr — backport of
          vllm-project/vllm#39055 (ZenoAFfectionate).
  - PN51: Sandermage (Sander) Barzov Aleksandr — backport of
          vllm-project/vllm#40816, fixed upstream by #40820 (defensive
          overlay at the qwen3 parser layer).
  - Consolidation: 2026-06-20 (maintainability refactor; runtime-neutral).
"""
from __future__ import annotations

import logging
import os

# Audit A-19 (2026-05-05): P59's tightly-coupled sub-patches share one
# marker and apply together — the A-19 exemption is preserved for the P59
# group. _AUDIT_A19_EXEMPT documents this intentional design.
_AUDIT_A19_EXEMPT = True  # tightly coupled subpatches (P59 group)

from sndr.engines.vllm.detection.guards import resolve_vllm_file, vllm_install_root
from sndr.kernel import (
    TextPatch,
    TextPatcher,
    TextPatchResult,
)
# Chain provider: P59 variant C's anchor is imported from P27's module so it
# stays byte-identical to P27's post-apply output by construction.
from sndr.engines.vllm.patches.reasoning.p27_reasoning_before_think import (
    _NEW_NONSTREAM_RETURN_PR35687 as _P27_NONSTREAM_RETURN_POST_APPLY,
)

log = logging.getLogger(
    "genesis.wiring.p61b_p59_pn51_qwen3_reasoning_consolidated"
)


_TARGET_REL = "reasoning/qwen3_reasoning_parser.py"

# Shared version window — all three absorbed patches carry the identical
# range, so a single constant drives every per-group helper AND the merged
# registry entry's applies_to.
QWEN3_REASONING_VLLM_VERSION_RANGE = (">=0.20.0", "<0.23.0")


# ════════════════════════════════════════════════════════════════════════
# MARKERS — each absorbed patch keeps its ORIGINAL marker verbatim so the
# three separate patchers do not cross-shadow at Layer 2 AND the marker
# lines stay byte-identical to the three originals. Re-exported under the
# original names so existing tests / drift-residue coverage / operator
# greps keep resolving against this consolidated module.
# ════════════════════════════════════════════════════════════════════════
GENESIS_P61B_MARKER = "Genesis P61b Qwen3 streaming partial-tag overlap guard v7.13"
GENESIS_P59_MARKER = "Genesis P59 Qwen3 reasoning embedded tool_call recovery v7.14"
GENESIS_PN51_MARKER = (
    "Genesis PN51 Qwen3 streaming thinking-disabled content routing v7.65"
)


# ════════════════════════════════════════════════════════════════════════
# P61b sub-patches (VERBATIM from p61b_qwen3_streaming_overlap_guard.py)
# ════════════════════════════════════════════════════════════════════════
P61B_IMPORT_OLD = (
    "from vllm.entrypoints.openai.engine.protocol import DeltaMessage\n"
    "from vllm.reasoning.basic_parsers import BaseThinkingReasoningParser"
)

P61B_IMPORT_NEW = (
    "from vllm.entrypoints.openai.engine.protocol import DeltaMessage\n"
    "from vllm.reasoning.basic_parsers import BaseThinkingReasoningParser\n"
    "from vllm.tool_parsers.utils import partial_tag_overlap  # [Genesis P61b]"
)

P61B_FALLBACK_OLD = (
    "        else:\n"
    "            # No end token yet: still in reasoning phase.\n"
    "            return DeltaMessage(reasoning=delta_text)"
)

P61B_FALLBACK_NEW = (
    "        else:\n"
    "            # [Genesis P61b vllm#40783] partial-tag overlap guard:\n"
    "            # avoid emitting half-formed <tool_call> as reasoning if the\n"
    "            # tag is being assembled across multiple deltas.\n"
    "            try:\n"
    "                _p61b_overlap = partial_tag_overlap(\n"
    "                    current_text, self._tool_call_tag or \"\"\n"
    "                )\n"
    "            except Exception:\n"
    "                _p61b_overlap = 0\n"
    "            if _p61b_overlap > 0:\n"
    "                _p61b_send_len = len(delta_text) - _p61b_overlap\n"
    "                if _p61b_send_len > 0:\n"
    "                    return DeltaMessage(reasoning=delta_text[:_p61b_send_len])\n"
    "                # Hold back this delta entirely; next delta completes the tag\n"
    "                return DeltaMessage()\n"
    "            # No end token yet: still in reasoning phase.\n"
    "            return DeltaMessage(reasoning=delta_text)"
)

P61B_DRIFT_MARKERS = [
    "partial_tag_overlap(current_text",  # upstream-merged version
]


# ════════════════════════════════════════════════════════════════════════
# P59 sub-patches (VERBATIM from p59_qwen3_reasoning_tool_call_recovery.py)
# ════════════════════════════════════════════════════════════════════════
P59_UPSTREAM_DRIFT_MARKERS = [
    "def _split_embedded_tool_calls(\n        reasoning: str | None,",
    "def _collect_or_keep(match: re.Match[str]) -> str:",
]

# Sub-patch 1: add `import re` before the existing collections import.
P59_IMPORT_OLD = (
    "from collections.abc import Iterable, Sequence\n"
    "from typing import TYPE_CHECKING"
)

P59_IMPORT_NEW = (
    "import re  # [Genesis P59 vllm#39055]\n"
    "from collections.abc import Iterable, Sequence\n"
    "from typing import TYPE_CHECKING"
)

# Sub-patch 2: insert _EMBEDDED_TOOL_CALL_RE module-level constant.
P59_REGEX_OLD = (
    "if TYPE_CHECKING:\n"
    "    from vllm.entrypoints.openai.chat_completion.protocol import ChatCompletionRequest\n"
    "    from vllm.entrypoints.openai.responses.protocol import ResponsesRequest\n"
    "    from vllm.tokenizers import TokenizerLike\n"
    "\n"
    "\n"
    "class Qwen3ReasoningParser(BaseThinkingReasoningParser):"
)

P59_REGEX_NEW = (
    "if TYPE_CHECKING:\n"
    "    from vllm.entrypoints.openai.chat_completion.protocol import ChatCompletionRequest\n"
    "    from vllm.entrypoints.openai.responses.protocol import ResponsesRequest\n"
    "    from vllm.tokenizers import TokenizerLike\n"
    "\n"
    "\n"
    "# [Genesis P59 vllm#39055] regex for extracting nested tool_call blocks.\n"
    "_EMBEDDED_TOOL_CALL_RE = re.compile(\n"
    "    r\"<tool_call>(.*?)</tool_call>|<tool_call>.*$\",\n"
    "    re.DOTALL,\n"
    ")\n"
    "\n"
    "\n"
    "class Qwen3ReasoningParser(BaseThinkingReasoningParser):"
)

# Sub-patch 3: insert _split_embedded_tool_calls staticmethod.
P59_METHOD_OLD = (
    "    @property\n"
    "    def end_token(self) -> str:\n"
    "        \"\"\"The token that ends reasoning content.\"\"\"\n"
    "        return \"</think>\""
)

P59_METHOD_NEW = (
    "    @property\n"
    "    def end_token(self) -> str:\n"
    "        \"\"\"The token that ends reasoning content.\"\"\"\n"
    "        return \"</think>\"\n"
    "\n"
    "    @staticmethod\n"
    "    def _split_embedded_tool_calls(\n"
    "        reasoning,\n"
    "        content,\n"
    "    ):\n"
    "        \"\"\"[Genesis P59 vllm#39055] Promote tool_call XML out of reasoning.\n"
    "\n"
    "        Qwen3.5/3.6 models can emit XML tool calls before </think>. The\n"
    "        downstream tool parser only inspects content, so embedded tool\n"
    "        calls would otherwise be lost. This helper extracts well-formed\n"
    "        <tool_call>...</tool_call> blocks from reasoning and prepends\n"
    "        them to content so qwen3_coder can parse them normally.\n"
    "        \"\"\"\n"
    "        if (\n"
    "            not reasoning\n"
    "            or \"<tool_call>\" not in reasoning\n"
    "            or \"<function=\" not in reasoning\n"
    "        ):\n"
    "            return reasoning, content\n"
    "\n"
    "        extracted_blocks = []\n"
    "\n"
    "        def _collect_or_keep(match):\n"
    "            block = match.group(0)\n"
    "            if \"<function=\" not in block:\n"
    "                return block\n"
    "            extracted_blocks.append(block.strip())\n"
    "            return \"\"\n"
    "\n"
    "        remaining_reasoning = _EMBEDDED_TOOL_CALL_RE.sub(\n"
    "            _collect_or_keep, reasoning\n"
    "        )\n"
    "        remaining_reasoning = remaining_reasoning.strip() or None\n"
    "\n"
    "        if not extracted_blocks:\n"
    "            return reasoning, content\n"
    "\n"
    "        content_parts = [\"\\n\\n\".join(extracted_blocks)]\n"
    "        if content:\n"
    "            content_parts.append(content)\n"
    "        merged_content = \"\\n\\n\".join(\n"
    "            part for part in content_parts if part\n"
    "        ) or None\n"
    "        return remaining_reasoning, merged_content"
)

# Sub-patches 4C/4D: wrap the </think>-present return.
# Variant C: P27-applied layout (anchor imported from P27 so byte-identical
# to P27's post-apply output by construction).
P59_RETURN_THINK_P27_CHAIN_OLD = _P27_NONSTREAM_RETURN_POST_APPLY

_P59_P27_POST_APPLY_RETURN_LINE = "            return reasoning, content or None"

P59_RETURN_THINK_P27_CHAIN_NEW = P59_RETURN_THINK_P27_CHAIN_OLD.replace(
    _P59_P27_POST_APPLY_RETURN_LINE,
    "            # [Genesis P59 vllm#39055] extract nested tool_call from reasoning\n"
    "            return self._split_embedded_tool_calls(reasoning, content or None)",
    1,
)

_P59_P27_CHAIN_DERIVATION_OK = (
    P59_RETURN_THINK_P27_CHAIN_OLD.count(_P59_P27_POST_APPLY_RETURN_LINE) == 1
    and P59_RETURN_THINK_P27_CHAIN_NEW != P59_RETURN_THINK_P27_CHAIN_OLD
)

# Variant D: pristine layout for P27-absent deployments.
P59_RETURN_THINK_PRISTINE_OLD = (
    "        if self.end_token in model_output:\n"
    "            reasoning, _, content = model_output.partition(self.end_token)\n"
    "            return reasoning, content or None"
)

P59_RETURN_THINK_PRISTINE_NEW = (
    "        if self.end_token in model_output:\n"
    "            reasoning, _, content = model_output.partition(self.end_token)\n"
    "            # [Genesis P59 vllm#39055] extract nested tool_call from reasoning\n"
    "            return self._split_embedded_tool_calls(reasoning, content or None)"
)

# Require-at-least-one set — the patch is only functional when ONE of the
# core </think>-present wrap variants landed; the helper alone is dead code.
_P59_CORE_WRAP_SUB_NAMES = (
    "p59_wrap_think_return_p27_chain",
    "p59_wrap_think_return_pristine",
)

# Sub-patch 5: wrap the truncated-output return.
P59_RETURN_TRUNC_OLD = (
    "        # Thinking enabled but no </think>: output was truncated.\n"
    "        # Everything generated so far is reasoning.\n"
    "        return model_output, None"
)

P59_RETURN_TRUNC_NEW = (
    "        # Thinking enabled but no </think>: output was truncated.\n"
    "        # Everything generated so far is reasoning.\n"
    "        # [Genesis P59 vllm#39055] still try to extract embedded tool_call\n"
    "        return self._split_embedded_tool_calls(model_output, None)"
)


# ════════════════════════════════════════════════════════════════════════
# PN51 sub-patch (VERBATIM from pn51_qwen3_streaming_thinking_disabled.py)
# ════════════════════════════════════════════════════════════════════════
PN51_ANCHOR_OLD = (
    "        prompt_is_reasoning_end and routes deltas as content without\n"
    "        calling this method.\n"
    "        \"\"\"\n"
    "        # Strip <think> from delta if present (old template / edge case\n"
    "        # where the model generates <think> itself)."
)

PN51_ANCHOR_NEW = (
    "        prompt_is_reasoning_end and routes deltas as content without\n"
    "        calling this method.\n"
    "        \"\"\"\n"
    "        # [Genesis PN51 vllm#40816] Streaming counterpart to the\n"
    "        # non-streaming `not self.thinking_enabled` short-circuit. When\n"
    "        # the parser was constructed with thinking disabled and no\n"
    "        # </think> token has appeared, all generated tokens are content\n"
    "        # (the prompt has the empty <think>\\n\\n</think>\\n\\n block\n"
    "        # pre-baked, so the serving-layer detection that should have\n"
    "        # bypassed this method missed; we recover here defensively).\n"
    "        if (\n"
    "            not self.thinking_enabled\n"
    "            and self.end_token_id not in current_token_ids\n"
    "        ):\n"
    "            if not delta_text:\n"
    "                return None\n"
    "            return DeltaMessage(content=delta_text)\n"
    "        # Strip <think> from delta if present (old template / edge case\n"
    "        # where the model generates <think> itself)."
)

PN51_DRIFT_MARKERS = [
    "if not self.thinking_enabled and self.end_token_id not in current_token_ids",
]


# ─── Bare env-flag names (no GENESIS_ENABLE_/SNDR_ENABLE_ prefix) ──────────
_P61B_FLAG = "P61B_STREAMING_OVERLAP"
_P59_FLAG = "P59_QWEN3_TOOL_RECOVERY"
_PN51_FLAG = "PN51_QWEN3_STREAMING_THINKING_DISABLED"

# Back-compat re-exports of the original anchor names some unit tests read
# directly (the standalone modules used these bare names).
IMPORT_OLD = P59_IMPORT_OLD
IMPORT_NEW = P59_IMPORT_NEW
REGEX_OLD = P59_REGEX_OLD
REGEX_NEW = P59_REGEX_NEW
METHOD_OLD = P59_METHOD_OLD
METHOD_NEW = P59_METHOD_NEW
RETURN_THINK_P27_CHAIN_OLD = P59_RETURN_THINK_P27_CHAIN_OLD
RETURN_THINK_P27_CHAIN_NEW = P59_RETURN_THINK_P27_CHAIN_NEW
RETURN_THINK_PRISTINE_OLD = P59_RETURN_THINK_PRISTINE_OLD
RETURN_THINK_PRISTINE_NEW = P59_RETURN_THINK_PRISTINE_NEW
RETURN_TRUNC_OLD = P59_RETURN_TRUNC_OLD
RETURN_TRUNC_NEW = P59_RETURN_TRUNC_NEW
UPSTREAM_DRIFT_MARKERS = P59_UPSTREAM_DRIFT_MARKERS
_P27_CHAIN_DERIVATION_OK = _P59_P27_CHAIN_DERIVATION_OK
_CORE_WRAP_SUB_NAMES = _P59_CORE_WRAP_SUB_NAMES
# PN51 anchor re-exports.
ANCHOR_OLD = PN51_ANCHOR_OLD
ANCHOR_NEW = PN51_ANCHOR_NEW


# ════════════════════════════════════════════════════════════════════════
# Version-gate-replicating per-group enable helpers.
# Each absorbed patch routed through should_apply (which version-gates), so
# each helper replicates BOTH the env gate AND the <0.23.0 version gate.
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
        {"vllm_version_range": QWEN3_REASONING_VLLM_VERSION_RANGE}
    )
    return v_ok


def _p61b_enabled() -> bool:
    return _env_on(_P61B_FLAG) and _version_ok()


def _p59_enabled() -> bool:
    return _env_on(_P59_FLAG) and _version_ok()


def _pn51_enabled() -> bool:
    return _env_on(_PN51_FLAG) and _version_ok()


# ════════════════════════════════════════════════════════════════════════
# Per-group TextPatcher factories — ONE patcher per absorbed patch, each
# with its OWN marker (failure isolation + no Layer-2 cross-shadowing).
# The bundle (bundles/reasoning_qwen3.py) calls these factories directly.
# ════════════════════════════════════════════════════════════════════════
def _make_p61b_patcher_for_target(target_file: str) -> TextPatcher:
    return TextPatcher(
        patch_name="P61b Qwen3 streaming overlap guard",
        target_file=target_file,
        marker=GENESIS_P61B_MARKER,
        sub_patches=[
            TextPatch(name="p61b_import", anchor=P61B_IMPORT_OLD,
                      replacement=P61B_IMPORT_NEW, required=True),
            TextPatch(name="p61b_overlap_guard", anchor=P61B_FALLBACK_OLD,
                      replacement=P61B_FALLBACK_NEW, required=True),
        ],
        upstream_drift_markers=list(P61B_DRIFT_MARKERS),
    )


def _make_p59_patcher_for_target(target_file: str) -> TextPatcher:
    """Build the P59 patcher (up to 6 sub-patches). Split out so unit
    tests can exercise the REAL sub-patch layout against synthetic files."""
    sub_patches = [
        TextPatch(name="p59_import_re", anchor=P59_IMPORT_OLD,
                  replacement=P59_IMPORT_NEW, required=True),
        TextPatch(name="p59_module_regex", anchor=P59_REGEX_OLD,
                  replacement=P59_REGEX_NEW, required=True),
        TextPatch(name="p59_helper_method", anchor=P59_METHOD_OLD,
                  replacement=P59_METHOD_NEW, required=True),
    ]
    # Variants C/D for the </think>-present return — required=False so
    # whichever file state is present wins; apply() then enforces that at
    # least one of them actually landed (_P59_CORE_WRAP_SUB_NAMES gate).
    if _P59_P27_CHAIN_DERIVATION_OK:
        sub_patches.append(
            TextPatch(name="p59_wrap_think_return_p27_chain",
                      anchor=P59_RETURN_THINK_P27_CHAIN_OLD,
                      replacement=P59_RETURN_THINK_P27_CHAIN_NEW,
                      required=False)
        )
    else:
        # P27's injected text changed shape — fail loud via the apply()
        # gate on post-P27 files rather than ship a no-op replacement.
        log.warning(
            "[P59] P27 chain derivation failed — P27's injected return "
            "shape changed; variant C dropped. Re-derive "
            "P59_RETURN_THINK_P27_CHAIN_* against the current P27 module."
        )
    sub_patches.extend([
        TextPatch(name="p59_wrap_think_return_pristine",
                  anchor=P59_RETURN_THINK_PRISTINE_OLD,
                  replacement=P59_RETURN_THINK_PRISTINE_NEW, required=False),
        TextPatch(name="p59_wrap_trunc_return",
                  anchor=P59_RETURN_TRUNC_OLD,
                  replacement=P59_RETURN_TRUNC_NEW, required=False),
    ])
    return TextPatcher(
        patch_name="P59 Qwen3 reasoning embedded tool_call recovery",
        target_file=target_file,
        marker=GENESIS_P59_MARKER,
        sub_patches=sub_patches,
        upstream_drift_markers=list(P59_UPSTREAM_DRIFT_MARKERS),
    )


def _make_pn51_patcher_for_target(target_file: str) -> TextPatcher:
    return TextPatcher(
        patch_name="PN51 Qwen3 streaming thinking-disabled routing",
        target_file=target_file,
        marker=GENESIS_PN51_MARKER,
        sub_patches=[
            TextPatch(name="pn51_thinking_disabled_streaming_short_circuit",
                      anchor=PN51_ANCHOR_OLD, replacement=PN51_ANCHOR_NEW,
                      required=True),
        ],
        upstream_drift_markers=list(PN51_DRIFT_MARKERS),
    )


# Bundle-facing factory aliases: bundles/reasoning_qwen3.py calls these
# (one factory per absorbed patch — preserves the original bundle layout).
def _make_p61b_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(_TARGET_REL)
    return None if target is None else _make_p61b_patcher_for_target(str(target))


def _make_p59_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(_TARGET_REL)
    return None if target is None else _make_p59_patcher_for_target(str(target))


def _make_pn51_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(_TARGET_REL)
    return None if target is None else _make_pn51_patcher_for_target(str(target))

# Back-compat: the P59 standalone module exposed `_make_patcher_for_target`.
_make_patcher_for_target = _make_p59_patcher_for_target


def _make_patcher() -> TextPatcher | None:
    """Drift-tool / static entry point: ONE TextPatcher carrying ALL
    sub-patches UNCONDITIONALLY (P61b's 2 + P59's up-to-6 + PN51's 1).

    ``tools/check_upstream_drift.py`` builds the patcher from this function
    and verifies every sub-patch anchor is present-and-unique in the
    pristine tree. All anchors MUST be declared here regardless of runtime
    env gating so the static drift check covers all three features. The
    marker here is cosmetic for the anchor scan (pristine tree has no
    markers); the live apply() uses three distinct per-feature markers.
    """
    target = resolve_vllm_file(_TARGET_REL)
    if target is None:
        return None
    p59 = _make_p59_patcher_for_target(str(target))
    return TextPatcher(
        patch_name=(
            "P61b+P59+PN51 reasoning/qwen3_reasoning_parser.py — streaming "
            "overlap guard (vllm#40783) + embedded tool_call recovery "
            "(vllm#39055) + thinking-disabled content routing (vllm#40816)"
        ),
        target_file=str(target),
        marker=GENESIS_P61B_MARKER,
        sub_patches=[
            TextPatch(name="p61b_import", anchor=P61B_IMPORT_OLD,
                      replacement=P61B_IMPORT_NEW, required=True),
            TextPatch(name="p61b_overlap_guard", anchor=P61B_FALLBACK_OLD,
                      replacement=P61B_FALLBACK_NEW, required=True),
            *p59.sub_patches,
            TextPatch(name="pn51_thinking_disabled_streaming_short_circuit",
                      anchor=PN51_ANCHOR_OLD, replacement=PN51_ANCHOR_NEW,
                      required=True),
        ],
        upstream_drift_markers=[
            *P61B_DRIFT_MARKERS,
            *P59_UPSTREAM_DRIFT_MARKERS,
            *PN51_DRIFT_MARKERS,
        ],
    )


def _apply_one(
    make_patcher, group_label: str
) -> tuple[str, str, list[str]]:
    """Apply one per-group patcher. Returns (status, reason, applied_subs)."""
    patcher = make_patcher()
    if patcher is None:
        return "skipped", f"{group_label}: qwen3_reasoning_parser.py not found", []
    result, failure = patcher.apply()
    if result == TextPatchResult.APPLIED:
        return "applied", f"{group_label} applied", list(patcher.applied_sub_patches)
    if result == TextPatchResult.IDEMPOTENT:
        return "applied", f"{group_label} idempotent (marker present)", []
    if result == TextPatchResult.SKIPPED:
        msg = failure.reason if failure else "anchor not found"
        detail = f" ({failure.detail})" if (failure and failure.detail) else ""
        return "skipped", f"{group_label}: {msg}{detail}", []
    return "failed", (
        f"{group_label}: {failure.reason if failure else 'unknown failure'}"
    ), []


def apply() -> tuple[str, str]:
    """Apply P61b + P59 + PN51 (consolidated) — each feature independently
    operator-gated (env + replicated version gate) and applied by its OWN
    TextPatcher (failure isolation + distinct marker). The applied set is
    byte-identical to running the three original modules separately,
    INCLUDING the per-feature marker lines."""
    p61b_on = _p61b_enabled()
    p59_on = _p59_enabled()
    pn51_on = _pn51_enabled()

    if not (p61b_on or p59_on or pn51_on):
        return "skipped", (
            "P61b+P59+PN51 all default OFF (or version-gated on this pin) — "
            "set GENESIS_ENABLE_P61B_STREAMING_OVERLAP=1 (overlap guard), "
            "GENESIS_ENABLE_P59_QWEN3_TOOL_RECOVERY=1 (embedded tool_call "
            "recovery) and/or "
            "GENESIS_ENABLE_PN51_QWEN3_STREAMING_THINKING_DISABLED=1 "
            "(thinking-disabled routing, in-window pins only) to engage. "
            "Each flag independently gates its own sub-patches."
        )

    if vllm_install_root() is None:
        return "skipped", "vllm install root not discoverable"

    target = resolve_vllm_file(_TARGET_REL)
    if target is None:
        return "skipped", "qwen3_reasoning_parser.py not found"

    statuses: list[str] = []
    failures: list[str] = []
    engaged: list[str] = []

    # P61b group.
    if p61b_on:
        st, reason, _ = _apply_one(_make_p61b_patcher, "P61b overlap guard")
        statuses.append(st)
        if st == "failed":
            failures.append(reason)
        else:
            engaged.append("P61b overlap guard")

    # P59 group — require-at-least-one wrap gate scoped HERE only.
    if p59_on:
        patcher = _make_p59_patcher()
        if patcher is None:
            statuses.append("skipped")
        else:
            result, failure = patcher.apply()
            if result == TextPatchResult.APPLIED:
                applied = list(patcher.applied_sub_patches)
                if not set(applied).intersection(_P59_CORE_WRAP_SUB_NAMES):
                    failures.append(
                        "P59 anchors partially applied but NO core "
                        "</think>-present wrap variant matched (applied: "
                        + (", ".join(applied) or "none")
                        + ") — helper injected as dead code. Re-anchor "
                        "variants C/D against the current pin (and check "
                        "P27 apply order) before serving traffic."
                    )
                    statuses.append("failed")
                else:
                    statuses.append("applied")
                    engaged.append(
                        f"P59 embedded tool_call recovery ({len(applied)} subs)"
                    )
            elif result == TextPatchResult.IDEMPOTENT:
                statuses.append("applied")
                engaged.append("P59 embedded tool_call recovery (idempotent)")
            elif result == TextPatchResult.SKIPPED:
                msg = failure.reason if failure else "anchor not found"
                statuses.append("skipped")
            else:
                statuses.append("failed")
                failures.append(
                    f"P59: {failure.reason if failure else 'unknown failure'}"
                )

    # PN51 group.
    if pn51_on:
        st, reason, _ = _apply_one(_make_pn51_patcher, "PN51 thinking-disabled routing")
        statuses.append(st)
        if st == "failed":
            failures.append(reason)
        else:
            engaged.append("PN51 thinking-disabled routing")

    if failures:
        return "failed", "; ".join(failures)
    if "applied" in statuses:
        return "applied", (
            "P61b+P59+PN51 consolidated installed ("
            + ", ".join(engaged or ["none"])
            + ") in qwen3_reasoning_parser.py. Each feature carries its own "
            "marker; apply set byte-equivalent to the three originals."
        )
    return "skipped", "P61b+P59+PN51: every enabled group skipped (anchor drift or upstream merge)"


def is_applied() -> bool:
    """Best-effort idempotency probe — True iff ALL THREE per-feature
    markers are present in the target file (full consolidation applied)."""
    target = resolve_vllm_file(_TARGET_REL)
    if target is None:
        return False
    try:
        with open(str(target), "r", encoding="utf-8", errors="ignore") as fh:
            content = fh.read()
    except OSError:
        return False
    return all(
        m in content
        for m in (GENESIS_P61B_MARKER, GENESIS_P59_MARKER, GENESIS_PN51_MARKER)
    )
