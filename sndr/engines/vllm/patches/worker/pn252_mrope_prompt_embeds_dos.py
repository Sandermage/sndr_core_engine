# SPDX-License-Identifier: Apache-2.0
"""Wiring for Patch N252 — M-RoPE prompt_embeds-only DoS fix.

================================================================
Issue (security — GHSA-33cg-gxv8-3p8g)
================================================================

`GpuModelRunner._init_mrope_positions` asserts that the request carries
prompt token IDs::

    assert req_state.prompt_token_ids is not None, (
        "M-RoPE requires prompt_token_ids to be available."
    )

On any M-RoPE model (Qwen2.5-VL, Qwen3-VL, and — directly relevant to
our PROD fleet — Gemma-4 26B-A4B / 31B-AWQ, which are M-RoPE and accept
`prompt_embeds`), a single `/v1/completions` request with
`prompt_embeds` set and `prompt=None` trips this assertion. An
AssertionError raised on the EngineCore execution path is unrecoverable:
the engine dies and the server stops serving every client. One crafted,
*unprivileged* request is a remote denial-of-service.

This is a host-side Python assertion — it fires identically on every GPU
generation (Ampere A5000, Ada, Hopper, Blackwell 5090). There is nothing
arch-specific to gate; the fix is a universal correctness/security guard.

================================================================
Fix (adapted from vllm#45252 / advisory GHSA-33cg-gxv8-3p8g)
================================================================

Two surgical edits to `v1/worker/gpu_model_runner.py::_init_mrope_positions`:

1. Drop the fatal `assert prompt_token_ids is not None` (keep the
   legitimate `assert supports_mrope(model)` and the `cast`).
2. At the call site, derive a *non-None* token sequence before calling
   `get_mrope_input_positions`:
     - real `prompt_token_ids` when present;
     - else dummy positional IDs `range(prompt_embeds.shape[0])` — M-RoPE
       only needs the sequence LENGTH for a passthrough modality without
       `grid_thw` (the values are placeholders; `mrope_features` already
       has the `prompt_embeds` modality filtered out so it carries no
       grids). The existing in-tree comment says as much: "prompt_embeds
       positions are treated as text positions for M-RoPE";
     - else, when BOTH are absent, a clean `ValueError`. Unlike the
       assert, a `ValueError` is surfaced as a per-request error and does
       NOT crash the engine.

How this improves on a verbatim upstream copy:
  - Integrated into the Genesis dispatcher (`should_apply`), idempotency
    marker, and build-time anchor manifest — survives the entrypoint
    `exec vllm serve` pattern and warm restarts.
  - All-or-nothing: both edits are `required=True` in one TextPatcher, so
    a half-applied state (assert removed but call site still passing a
    possibly-None `prompt_token_ids`) can never be written — the patcher
    returns SKIPPED and leaves the file pristine.
  - Documents the security context (GHSA) inline for future maintainers.

================================================================
PIN STATE (verified 2026-06-14, both pins live)
================================================================

The vulnerable function is **byte-identical** on both pins in our window:
  - dev259 (`0.22.1rc1.dev259+g303916e93`, current PROD) — `_init_mrope_positions`
  - dev491 (`0.22.1rc1.dev491+g1033ffac2`, promotion candidate)
Both still carry the fatal assert; the upstream merge of #45252 had NOT
landed in either nightly tag. So a single byte-exact anchor applies to
both — no dual-anchor split needed. When a future pin merges the fix, the
anchor (which includes the assert) stops matching and the patch self-skips
(`required_anchor_missing` → SKIPPED), leaving the merged code untouched.

================================================================
SAFETY MODEL
================================================================

- `applies_to: {}` — the patch text is installed unconditionally, but the
  patched code path is reached ONLY for M-RoPE models (`assert
  supports_mrope(model)` guards entry). On a non-M-RoPE model the edited
  lines are never executed; zero behavioral change.
- `default_on=True` is informational under the strict-opt-in dispatcher
  (Sander directive 2026-05-17): the security fix is *recommended* on, and
  the launcher engages it via `GENESIS_ENABLE_PN252_MROPE_PROMPT_EMBEDS_DOS=1`.
  Operators can A/B with `GENESIS_DISABLE_PN252_MROPE_PROMPT_EMBEDS_DOS=1`.
- Worst case on a happy-path request (prompt_token_ids present): the new
  `if` takes the first branch → identical behavior to the original code.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
Backport: vllm#45252 (security advisory GHSA-33cg-gxv8-3p8g, full credit
          to the upstream reporter/author).
"""
from __future__ import annotations

import logging

from sndr.engines.vllm.detection.guards import resolve_vllm_file, vllm_install_root
from sndr.kernel import (
    TextPatch,
    TextPatcher,
    TextPatchResult,
    result_to_wiring_status,
)

log = logging.getLogger("genesis.wiring.pN252_mrope_prompt_embeds_dos")

GENESIS_PN252_MARKER = (
    "Genesis PN252 M-RoPE prompt_embeds-only DoS fix "
    "(vllm#45252 / GHSA-33cg-gxv8-3p8g)"
)


# ─── Sub-patch 1: drop the fatal prompt_token_ids assert ────────────
#
# Anchored on the supports_mrope assert + the prompt_token_ids assert +
# the cast, as one bundle. The bundle is UNIQUE: the sibling
# `_init_xdrope_positions` also asserts `prompt_token_ids is not None`,
# but with the XD-RoPE message and a `cast(SupportsXDRoPE, ...)` placed
# BEFORE its assert, so this exact envelope matches only the M-RoPE site.

PN252_PART1_ANCHOR = (
    '        assert supports_mrope(model), "M-RoPE support is not implemented."\n'
    "        assert req_state.prompt_token_ids is not None, (\n"
    '            "M-RoPE requires prompt_token_ids to be available."\n'
    "        )\n"
    "        mrope_model = cast(SupportsMRoPE, model)\n"
)

PN252_PART1_REPLACEMENT = (
    "        # [Genesis PN252 mrope_prompt_embeds_dos] GHSA-33cg-gxv8-3p8g —\n"
    "        # a prompt_embeds-only request (prompt=None) MUST NOT crash the\n"
    "        # engine. The original `assert prompt_token_ids is not None` was a\n"
    "        # remote DoS: one crafted /v1/completions with prompt_embeds set\n"
    "        # and prompt=None tripped it and took EngineCore down. Drop the\n"
    "        # fatal assert; a safe non-None token sequence is derived at the\n"
    "        # call site below. vllm#45252 / advisory GHSA-33cg-gxv8-3p8g.\n"
    '        assert supports_mrope(model), "M-RoPE support is not implemented."\n'
    "        mrope_model = cast(SupportsMRoPE, model)\n"
)


# ─── Sub-patch 2: derive a non-None token sequence at the call site ──

PN252_PART2_ANCHOR = (
    "        mrope_features = [\n"
    '            f for f in req_state.mm_features if f.modality != "prompt_embeds"\n'
    "        ]\n"
    "        req_state.mrope_positions, req_state.mrope_position_delta = (\n"
    "            mrope_model.get_mrope_input_positions(\n"
    "                req_state.prompt_token_ids,\n"
    "                mrope_features,\n"
    "            )\n"
    "        )\n"
)

PN252_PART2_REPLACEMENT = (
    "        mrope_features = [\n"
    '            f for f in req_state.mm_features if f.modality != "prompt_embeds"\n'
    "        ]\n"
    "        # [Genesis PN252] derive a non-None token sequence for M-RoPE:\n"
    "        # real prompt token IDs when present, else dummy positional IDs\n"
    "        # sized from prompt_embeds (M-RoPE only needs the LENGTH for a\n"
    "        # passthrough modality without grid_thw — values are placeholders,\n"
    "        # the filtered mrope_features carry no grids). A clean ValueError —\n"
    "        # surfaced per-request, never an engine crash — fires only when\n"
    "        # BOTH token IDs and prompt_embeds are absent.\n"
    "        if req_state.prompt_token_ids is not None:\n"
    "            mrope_input_tokens = req_state.prompt_token_ids\n"
    "        elif req_state.prompt_embeds is not None:\n"
    "            mrope_input_tokens = list(range(req_state.prompt_embeds.shape[0]))\n"
    "        else:\n"
    "            raise ValueError(\n"
    '                "M-RoPE requires either prompt_token_ids or prompt_embeds."\n'
    "            )\n"
    "        req_state.mrope_positions, req_state.mrope_position_delta = (\n"
    "            mrope_model.get_mrope_input_positions(\n"
    "                mrope_input_tokens,\n"
    "                mrope_features,\n"
    "            )\n"
    "        )\n"
)


def _make_patcher() -> TextPatcher | None:
    target = resolve_vllm_file("v1/worker/gpu_model_runner.py")
    if target is None:
        return None
    return TextPatcher(
        patch_name=(
            "PN252 v1/worker/gpu_model_runner.py — M-RoPE prompt_embeds-only "
            "DoS fix (vllm#45252 / GHSA-33cg-gxv8-3p8g)"
        ),
        target_file=str(target),
        marker=GENESIS_PN252_MARKER,
        sub_patches=[
            TextPatch(
                name="pN252_drop_fatal_prompt_token_ids_assert",
                anchor=PN252_PART1_ANCHOR,
                replacement=PN252_PART1_REPLACEMENT,
                required=True,
            ),
            TextPatch(
                name="pN252_derive_non_none_token_sequence",
                anchor=PN252_PART2_ANCHOR,
                replacement=PN252_PART2_REPLACEMENT,
                required=True,
            ),
        ],
        # No patcher-level drift marker: an upstream merge of #45252 rewrites
        # the asserted block, so PART1's anchor stops matching and the whole
        # (all-required) patcher returns SKIPPED — the merged code is left
        # untouched. The ValueError string is our own residue and must NOT be
        # used as a merge signal (it would self-collide).
        upstream_drift_markers=[],
        patch_id="PN252",
    )


def apply() -> tuple[str, str]:
    """Apply PN252 — fix the M-RoPE prompt_embeds-only DoS.

    Single-file, two-sub-patch TextPatcher (both ``required=True`` →
    atomic all-or-nothing). Never raises. Returns (status, reason).
    """
    from sndr.dispatcher import log_decision, should_apply

    decision, reason = should_apply("PN252")
    log_decision("PN252", decision, reason)
    if not decision:
        return "skipped", reason

    if vllm_install_root() is None:
        return "skipped", "vllm install root not discoverable"

    patcher = _make_patcher()
    if patcher is None:
        return "skipped", (
            "target v1/worker/gpu_model_runner.py not resolvable — vllm "
            "tree may differ from expected layout"
        )

    result, failure = patcher.apply()
    return result_to_wiring_status(
        result,
        failure,
        applied_message=(
            "PN252 applied: M-RoPE prompt_embeds-only DoS closed "
            "(GHSA-33cg-gxv8-3p8g). _init_mrope_positions no longer asserts "
            "on prompt_token_ids; a prompt_embeds-only request now derives "
            "dummy positional IDs from prompt_embeds length instead of "
            "crashing EngineCore. Relevant on every M-RoPE model the fleet "
            "serves (Gemma-4 26B/31B AWQ accept prompt_embeds). Host-side "
            "fix — identical on Ampere/Ada/Hopper/Blackwell."
        ),
        patch_name="PN252 M-RoPE prompt_embeds-only DoS fix",
    )


# ════════════════════════════════════════════════════════════════════════
# Build-time manifest registration (P2.1 Site Map)
# ════════════════════════════════════════════════════════════════════════
#
# Enrolls PN252's two sub-patches into the anchor-offset manifest at BUILD
# TIME (scripts/build_anchor_manifest.py), pointed at a pristine fixture so
# it works without a live vllm install. Runtime apply() is unaffected.


def register_for_manifest(*, pristine_root) -> None:
    """Register PN252's sub-patches into the Site Map registry using the
    pristine ``gpu_model_runner.py`` fixture under ``pristine_root``."""
    from sndr.engines.vllm.wiring.patcher_registry import register_text_patcher

    register_text_patcher(
        "PN252",
        TextPatcher(
            patch_name="PN252 gpu_model_runner.py (build mode)",
            target_file=str(pristine_root / "gpu_model_runner.py"),
            marker=GENESIS_PN252_MARKER,
            sub_patches=[
                TextPatch(
                    name="pN252_drop_fatal_prompt_token_ids_assert",
                    anchor=PN252_PART1_ANCHOR,
                    replacement=PN252_PART1_REPLACEMENT,
                    required=True,
                ),
                TextPatch(
                    name="pN252_derive_non_none_token_sequence",
                    anchor=PN252_PART2_ANCHOR,
                    replacement=PN252_PART2_REPLACEMENT,
                    required=True,
                ),
            ],
            upstream_drift_markers=[],
            patch_id="PN252",
        ),
    )
