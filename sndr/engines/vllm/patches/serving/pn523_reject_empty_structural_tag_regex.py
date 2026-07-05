# SPDX-License-Identifier: Apache-2.0
"""PN523 — reject empty ``structural_tag``/``regex`` (vendor of vllm#47450).

================================================================
UPSTREAM BUG (vllm#47450) — REMOTE SINGLE-REQUEST DoS, PN387 SUCCESSOR
================================================================

The merged #45346 guards (native in our pin since dev714; they are why
PN387 retired) cover ``grammar``/``json``/``json_object`` but NOT
``structural_tag``/``regex``:

  * ``structural_tag=""`` — ``StructuredOutputsParams`` counts constraint
    fields with ``is not None``, so the empty string passes the frontend
    exclusivity check (request.py keys on ``is not None``), a
    StructuredOutputRequest is built, and ``json.loads("")`` in
    ``backend_xgrammar.compile_grammar`` raises JSONDecodeError inside
    the EngineCore step loop, which has NO per-request isolation ->
    EngineDeadError. One request remotely bricks the single-instance
    PROD engine for every lane (the xgrammar tool-call path is live on
    ALL of them). This is exactly the PN387/#45346 DoS class.
  * ``regex=""`` — xgrammar tolerates ``compile_regex("")`` without
    crashing, but an empty regex provides no constraint; upstream
    rejects the degenerate request at the API layer for consistency, and
    we vendor that too so behavior is identical when #47450 merges.

================================================================
THE FIX — reject during request validation (verbatim messages)
================================================================

PR #47450 inserts both guards in
``SamplingParams._validate_structured_outputs`` immediately after the
#45346 ``json_object`` guard (frontend -> clean 400, engine keeps
serving). PN523 vendors both guards with the upstream ``ValueError``
messages VERBATIM but Genesis-reworded comments, so #47450's exact
comment lines remain usable as SELF_COLLISION-safe drift markers
(tools/lint_drift_markers.py, PN369 contract).

Layer-2 note: PN387 shipped a companion gateway-edge middleware guard.
Re-arming it with these two checks is deliberately DEFERRED (optional
defence-in-depth; the load-bearing reject is this validation-time guard,
same call depth as the native #45346 guards). Re-arm only with a
concrete edge-bypass scenario in hand.

================================================================
SAFETY MODEL
================================================================

  * Two cheap isinstance/strip checks once per request, inside the same
    validation path as the native #45346 guards. Bit-identical for every
    valid input; a legitimate non-empty ``structural_tag``/``regex`` is
    untouched.
  * default_on=True (PN252 security precedent): trivially triggerable
    remote single-request EngineDeadError on single-instance PROD. The
    env flag remains an operator OFF switch.
  * Version range: lower bound dev748 — the anchor is the #45346 close
    block byte-verified count==1 in pristine dev748 (2dfaae752, gh api,
    2026-07-05). Drift markers self-skip the patch when #47450 (or an
    equivalent) lands.
  * Same-file neighbors: P109 anchors verify()'s _validate_logprobs
    cluster + _validate_logits_processors (disjoint regions); PN389
    edits utils.py/backend_xgrammar.py/envs.py (not this file); retired
    PN387 residue impossible (its guards are native upstream text now,
    and our replacement contains no ``[Genesis PN387`` banner).

Author backport: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
Original PR: vllm#47450 (OPEN as of 2026-07-05).
"""

from __future__ import annotations

import logging
import os

from sndr.engines.vllm.detection.guards import resolve_vllm_file, vllm_install_root
from sndr.kernel import (
    TextPatch,
    TextPatcher,
)

log = logging.getLogger("genesis.wiring.pn523_reject_empty_structural_tag_regex")

GENESIS_PN523_MARKER = (
    "Genesis PN523 reject empty structural_tag/regex (vendor of vllm#47450) v1"
)

# ── Sub-patch (required): the two degenerate-input guards ─────────────
# Anchor: the close of the native #45346 json_object guard (its raise
# closer) plus the blank line and the backend_guidance import that follow.
# Byte-verified count==1 against pristine dev748 (2dfaae752, gh api
# 2026-07-05). We insert the two new guards BETWEEN the json_object raise
# and the backend import — exactly where PR #47450 puts them, in the
# PR's order (regex first, then structural_tag).

PN523_GUARDS_OLD = (
    '                "structured_outputs to disable structured outputs"\n'
    "            )\n"
    "\n"
    "        from vllm.v1.structured_output.backend_guidance import (\n"
)

PN523_GUARDS_NEW = (
    '                "structured_outputs to disable structured outputs"\n'
    "            )\n"
    "        # [Genesis PN523 vendor of vllm#47450] Reject empty-string regex\n"
    "        # during request validation. xgrammar's compile_regex('') does not\n"
    "        # crash, but an empty regex constrains nothing — bounce the\n"
    "        # degenerate request at the API layer (mirrors the empty-grammar/\n"
    "        # empty-json guards above; upstream message kept verbatim).\n"
    "        if (\n"
    "            isinstance(self.structured_outputs.regex, str)\n"
    '            and self.structured_outputs.regex.strip() == ""\n'
    "        ):\n"
    '            raise ValueError("structured_outputs.regex cannot be an empty string")\n'
    "        # [Genesis PN523 vendor of vllm#47450] Reject empty-string\n"
    "        # structural_tag during request validation. The frontend keys\n"
    "        # constraints on `is not None`, so '' slips through to\n"
    "        # json.loads('') in backend_xgrammar.compile_grammar ->\n"
    "        # JSONDecodeError inside the per-request-isolation-free EngineCore\n"
    "        # loop (EngineDeadError: one request bricks the single-instance\n"
    "        # engine — the PN387/#45346 DoS class).\n"
    "        if (\n"
    "            isinstance(self.structured_outputs.structural_tag, str)\n"
    '            and self.structured_outputs.structural_tag.strip() == ""\n'
    "        ):\n"
    "            raise ValueError(\n"
    '                "structured_outputs.structural_tag cannot be an empty string"\n'
    "            )\n"
    "\n"
    "        from vllm.v1.structured_output.backend_guidance import (\n"
)

# Drift markers — #47450's exact inserted comment lines (from
# `gh pr diff 47450`, 2026-07-05). Byte-verified absent in pristine dev748
# (both count 0). Our replacement re-uses the upstream ValueError
# *messages* verbatim (those lines WOULD collide) but rewords the
# comments, so the PR's comment heads never appear in our emitted text —
# SELF_COLLISION-safe (PN369). The `[Genesis PN523` banner is the defended
# convention entry.
_DRIFT_MARKERS = (
    # The PR's exact comment head for the empty-regex guard.
    '        # Reject empty string regex early. xgrammar tolerates compile_regex("")\n',
    # The PR's exact comment head for the empty-structural_tag guard.
    "        # Reject empty string structural_tag early to avoid engine-side crashes.\n",
    # Defended convention entry (our own banner) — residue coverage if the
    # upstream comment lines are ever reworded on merge.
    "[Genesis PN523",
)


def _make_patcher() -> TextPatcher | None:
    target = resolve_vllm_file("sampling_params.py")
    if target is None:
        return None
    return TextPatcher(
        patch_name=(
            "PN523 sampling_params.py — reject empty structural_tag/regex "
            "(vendor of vllm#47450)"
        ),
        target_file=str(target),
        marker=GENESIS_PN523_MARKER,
        sub_patches=[
            TextPatch(
                name="pn523_empty_structural_tag_regex_guards",
                anchor=PN523_GUARDS_OLD,
                replacement=PN523_GUARDS_NEW,
                required=True,
            ),
        ],
        upstream_drift_markers=list(_DRIFT_MARKERS),
    )


def apply() -> tuple[str, str]:  # noqa: PLR0911 - dispatcher early-return cascade: distinct skip/self-retire reasons per gate
    """Apply PN523 — reject empty structural_tag/regex. Never raises.

    Gated through the dispatcher on
    ``GENESIS_ENABLE_PN523_REJECT_EMPTY_STRUCTURAL_TAG_REGEX``
    (default_on=True in the registry — remote single-request DoS guard;
    the flag is an operator OFF switch, PN252 precedent).
    """
    from sndr.dispatcher import log_decision, should_apply

    decision, reason = should_apply("PN523")
    log_decision("PN523", decision, reason)
    if not decision:
        return "skipped", reason

    if vllm_install_root() is None:
        return "skipped", "vllm install root not discoverable"

    patcher = _make_patcher()
    if patcher is None:
        return "skipped", "vllm/sampling_params.py not found"

    if not os.path.isfile(patcher.target_file):
        return "skipped", f"target disappeared: {patcher.target_file}"
    with open(patcher.target_file, encoding="utf-8") as f:
        content = f.read()
    if patcher.marker in content:
        return "skipped", f"{patcher.patch_name}: already applied (marker present)"
    # Self-skip once the upstream fix lands in our pin (drift markers).
    for m in patcher.upstream_drift_markers:
        if m.startswith("[Genesis"):
            continue
        if m in content:
            return (
                "skipped",
                f"upstream drift marker {m!r} present — upstream PR "
                "#47450 (or equivalent fix) appears merged (upstream_merged)",
            )

    try:
        result, failure = patcher.apply()
    except Exception as e:  # noqa: BLE001 - dispatcher contract: never raise
        return "failed", f"PN523 apply raised {e!r}"

    from sndr.kernel import TextPatchResult

    if result == TextPatchResult.FAILED:
        return "failed", f"PN523: {failure.reason if failure else 'unknown'}"
    if result == TextPatchResult.SKIPPED:
        return "skipped", f"PN523: {failure.reason if failure else 'unknown'}"
    if result == TextPatchResult.IDEMPOTENT:
        return "applied", "PN523 already applied (idempotent)"

    return (
        "applied",
        "PN523 applied: _validate_structured_outputs now rejects "
        'structural_tag="" and regex="" with a clean 400 at request '
        "validation (upstream #47450 messages verbatim), instead of "
        'json.loads("") raising inside EngineCore (EngineDeadError DoS). '
        "Bit-identical for valid inputs.",
    )


def is_applied() -> bool:
    """Return True iff our marker is present in the target file."""
    if vllm_install_root() is None:
        return False
    patcher = _make_patcher()
    if patcher is None:
        return False
    try:
        with open(patcher.target_file, encoding="utf-8") as f:
            return patcher.marker in f.read()
    except OSError:
        return False
