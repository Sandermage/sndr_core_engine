# SPDX-License-Identifier: Apache-2.0
"""PN387 — reject degenerate ``structured_outputs`` (vendor of vllm#45346).

LAYER 1 of 2 — the SOURCE OVERLAY (verbatim backport of PR #45346).
The companion Layer 2 is the Genesis gateway-edge guard wired in
``sndr/engines/vllm/patches/middleware/edge_guard_reject_degenerate_structured_outputs.py``
(logic in ``sndr/engines/vllm/middleware/reject_degenerate_structured_outputs.py``).
This module is the SINGLE PN387 registry entrypoint: its ``apply()`` drives
BOTH files atomically via ``MultiFilePatchTransaction``.
Both layers are gated on the SAME opt-in flag — see Activation below.

================================================================
UPSTREAM BUG (vllm#45346) — CONFIRMED INSTANCE-WIDE DoS ON OUR PROD
================================================================

A single request with ``structured_outputs={"json_object": false}`` or
``{"json": ""}`` crashes the **EngineCore** process: the request returns
500 ``EngineDeadError`` and every subsequent request fails (instance-wide
DoS — fatal on our single-instance PROD, no second replica to absorb it).

Mechanism: ``StructuredOutputsParams.__post_init__`` counts the
constraint fields with ``is not None``, so ``json_object=False``
(``False is not None`` → True) and ``json=""`` (``"" is not None`` → True)
both pass the mutual-exclusivity check — a ``StructuredOutputRequest`` is
built and dispatched to the engine. But ``get_structured_output_key`` only
returns ``JSON_OBJECT`` when ``json_object`` is *truthy*, so ``False``
falls through to ``raise ValueError("No valid structured output parameter
found")``; an empty ``json`` schema fails inside the xgrammar compiler.
Both ``ValueError``s are raised inside the EngineCore step loop, which has
NO per-request isolation, so one bad request kills the engine for everyone.

================================================================
THE FIX (this layer) — reject during request validation
================================================================

PR #45346 rejects both inputs in
``SamplingParams._validate_structured_outputs`` (called by ``verify()``,
frontend → 400), immediately next to the existing empty-grammar guard
(pristine line 888 in pin ``g303916e93``):

  • ``json`` is an empty string → ``ValueError`` (mirrors the empty-grammar
    guard's ``.strip() == ""`` shape).
  • ``json_object is False`` → ``ValueError`` (``json_object`` is a flag;
    only ``True`` selects a constraint — omit ``structured_outputs`` to
    disable structured outputs).

The bad request now fails fast at the frontend (400) and the engine keeps
serving. The deeper per-request engine-step exception isolation is a
separate, larger change and is intentionally out of scope (per the PR).

================================================================
RELEVANCE FOR GENESIS + WHY THE SECOND (EDGE) LAYER EXISTS
================================================================

Our public surface (Proxy-AI gateway + OpenAI-compatible streaming
clients) accepts user-controlled ``structured_outputs``. On a single PROD
instance, the EngineDeadError takes down ALL four model families at once.
This source overlay closes the crash at request validation. The Genesis
extra (Layer 2) adds a gateway-edge guard at the very top of
``_create_chat_completion`` so the reject becomes a clean 400 at the
gateway edge — BEFORE the request descends into the engine loop — which is
strictly defence-in-depth on top of this validation-time fix.

================================================================
SAFETY MODEL
================================================================

  • The two guards run once per request inside the existing
    ``_validate_structured_outputs`` path — same cost envelope as the
    empty-grammar / empty-choice guards already there (two cheap
    ``isinstance`` / identity checks). Bit-identical for every valid input.
  • A legitimate ``json_object=True`` request is UNAFFECTED — only the
    degenerate ``False`` selector is rejected.
  • Default OFF (``default_on=False``): this is a pure safety reject; the
    gate lets us A/B the rejection criteria (e.g. confirm no real client
    relies on the legacy ``json_object: false`` no-op shape) before
    enabling. STRONG RECOMMENDATION: enable on every single-instance PROD
    — the unguarded path is a one-request kill switch.
  • Drift markers watch the canonical upstream guard strings so the patch
    self-skips when #45346 lands in our pin. Genesis spells its drift
    markers as the upstream form (which never appears in our own emitted
    comment text — we add no new comment that quotes them) so the lint
    self-collision contract (tools/lint_drift_markers.py, PN369) holds.

Author backport: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
Original PR: vllm#45346 (Sunt-ing, OPEN as of 2026-06-13).
"""

from __future__ import annotations

import logging
import os

from sndr.engines.vllm.detection.guards import resolve_vllm_file, vllm_install_root
from sndr.kernel import (
    TextPatch,
    TextPatcher,
)

log = logging.getLogger("genesis.wiring.pn387_reject_degenerate_structured_outputs")

GENESIS_PN387_MARKER = (
    "Genesis PN387 reject degenerate structured_outputs (vendor of vllm#45346) v1"
)

# ── Sub-patch (required): the two degenerate-input guards ─────────────
# Anchor: the pin's empty-grammar guard `raise ValueError(...)` line plus
# the blank line and the `from vllm.v1.structured_output.backend_guidance
# import (` that immediately follow it. Byte-exact and unique in the file
# (count==1 byte-verified against /private/tmp/candidate_pin_current/vllm
# at pin g303916e93 — the grammar guard string appears only here). We
# insert the two new guards BETWEEN the grammar raise and the backend
# import (exactly where PR #45346 puts them).

PN387_GUARDS_OLD = (
    '            raise ValueError("structured_outputs.grammar cannot be an empty string")\n'
    "\n"
    "        from vllm.v1.structured_output.backend_guidance import (\n"
)

PN387_GUARDS_NEW = (
    '            raise ValueError("structured_outputs.grammar cannot be an empty string")\n'
    "        # [Genesis PN387 vendor of vllm#45346] Reject empty string json\n"
    '        # schema early to avoid engine-side crashes. `json=""` passes\n'
    "        # the `is not None` exclusivity check in __post_init__ but has\n"
    "        # no key in get_structured_output_key, so it crashes the xgrammar\n"
    "        # compiler inside the per-request-isolation-free EngineCore loop.\n"
    "        if (\n"
    "            isinstance(self.structured_outputs.json, str)\n"
    '            and self.structured_outputs.json.strip() == ""\n'
    "        ):\n"
    '            raise ValueError("structured_outputs.json cannot be an empty string")\n'
    "        # [Genesis PN387 vendor of vllm#45346] Reject json_object=False\n"
    "        # early to avoid engine-side crashes. json_object is a flag; only\n"
    "        # True selects a constraint, so False falls through to a\n"
    "        # ValueError raised inside the EngineCore step loop (EngineDead).\n"
    "        if self.structured_outputs.json_object is False:\n"
    "            raise ValueError(\n"
    '                "structured_outputs.json_object must be True if set; omit "\n'
    '                "structured_outputs to disable structured outputs"\n'
    "            )\n"
    "\n"
    "        from vllm.v1.structured_output.backend_guidance import (\n"
)

# Drift markers — exact substrings of #45346's MERGED form (from
# `gh pr diff 45346`, 2026-06-13). Absent in the pristine pin tree
# (byte-verified: both count 0). They are NOT substrings of our own
# emitted text: PR #45346 introduces these comment lines
# (`# Reject empty string json schema early...`) and raises the messages
# verbatim — our replacement re-uses the upstream *messages* (so the
# `raise ValueError("structured_outputs.json ...")` line WOULD collide)
# but our comments are differently worded, so we use the PR's comment
# lines as drift markers (those never appear in our emitted text). The
# `[Genesis PN387` banner is the defended convention entry.
_DRIFT_MARKERS = (
    # The PR's exact comment head for the empty-json guard.
    "        # Reject empty string json schema early to avoid engine-side crashes\n",
    # The PR's exact comment head for the json_object=False guard.
    "        # Reject json_object=False early to avoid engine-side crashes\n",
    # Defended convention entry (our own banner) — exempt from collision
    # lint; keeps residue coverage if the comment lines ever change.
    "[Genesis PN387",
)


def _make_patcher() -> TextPatcher | None:
    target = resolve_vllm_file("sampling_params.py")
    if target is None:
        return None
    return TextPatcher(
        patch_name=(
            "PN387 sampling_params.py — reject degenerate structured_outputs "
            '(json="" / json_object=False) (vendor of vllm#45346)'
        ),
        target_file=str(target),
        marker=GENESIS_PN387_MARKER,
        sub_patches=[
            TextPatch(
                name="pn387_degenerate_guards",
                anchor=PN387_GUARDS_OLD,
                replacement=PN387_GUARDS_NEW,
                required=True,
            ),
        ],
        upstream_drift_markers=list(_DRIFT_MARKERS),
    )


def apply() -> tuple[str, str]:
    """Apply PN387 — reject degenerate structured_outputs. Never raises.

    This is the SINGLE registry entrypoint for both PN387 layers. It
    applies the source overlay (this module, sampling_params.py) AND the
    gateway-edge wiring (companion middleware module, serving.py) together
    via ``MultiFilePatchTransaction`` (validate-all-then-write-all), so the
    two files either both land or neither does — no half-patched state.

    Opt-in: gated through the dispatcher on
    ``GENESIS_ENABLE_PN387_REJECT_DEGENERATE_STRUCTURED_OUTPUTS``
    (default_on=False in the registry — pure safety reject, gated so the
    rejection criteria can be A/B'd before enabling on PROD).
    """
    from sndr.dispatcher import log_decision, should_apply

    decision, reason = should_apply("PN387")
    log_decision("PN387", decision, reason)
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
    # Self-skip if the upstream fix has landed in our pin (drift markers).
    # Checked on the SOURCE-OVERLAY file (the one the PR actually edits);
    # if #45346 is merged upstream we never touch either file.
    for m in patcher.upstream_drift_markers:
        if m.startswith("[Genesis"):
            continue
        if m in content:
            return (
                "skipped",
                f"upstream drift marker {m!r} present — upstream PR "
                "#45346 (or equivalent fix) appears merged (upstream_merged)",
            )

    # Build the companion gateway-edge wiring patcher (serving.py). Its
    # own apply() shares the same env flag; here we drive both in one
    # atomic transaction so the source overlay + edge guard land together.
    from sndr.engines.vllm.patches.middleware import (
        edge_guard_reject_degenerate_structured_outputs as edge,
    )
    from sndr.kernel import MultiFilePatchTransaction

    edge_patcher = edge._make_patcher()
    patchers = [patcher]
    if edge_patcher is not None and os.path.isfile(edge_patcher.target_file):
        patchers.append(edge_patcher)
    else:
        # The source overlay (Layer 1) is the load-bearing safety fix; the
        # edge guard is defence-in-depth. If serving.py is unresolvable we
        # still apply Layer 1 alone rather than skipping the DoS fix.
        log.warning(
            "PN387: gateway-edge serving.py target unresolvable — applying "
            "source overlay (Layer 1) alone; edge guard (Layer 2) skipped."
        )

    txn = MultiFilePatchTransaction(patchers, name="PN387")
    status, txn_reason = txn.apply_or_skip()
    if status != "applied":
        return status, f"{patcher.patch_name}: {txn_reason}"
    return (
        "applied",
        "PN387 applied ("
        + ("2 layers" if len(patchers) == 2 else "Layer 1 only")
        + '): _validate_structured_outputs now rejects json="" and '
        "json_object=False with a clear 400 at request validation"
        + (
            " AND a gateway-edge guard short-circuits the same inputs with a "
            "400 at the top of _create_chat_completion"
            if len(patchers) == 2
            else ""
        )
        + ", instead of an EngineDeadError that bricks the engine "
        "(vllm#45346 DoS). Bit-identical for valid inputs.",
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
