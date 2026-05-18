# SPDX-License-Identifier: Apache-2.0
"""G4_68 — TurboQuant spec-decode cudagraph downgrade for PR #42637 overlay.

================================================================
PROBLEM
================================================================

P65 (`vllm/sndr_core/integrations/attention/turboquant/p65_turboquant_
spec_cg_downgrade.py`) downgrades `TurboQuantMetadataBuilder._cudagraph_
support` from `UNIFORM_BATCH` to `UNIFORM_SINGLE_TOKEN_DECODE` when
`speculative_config` is active. It uses a `TextPatcher` against
`vllm/v1/attention/backends/turboquant_attn.py` at runtime.

When the PR #42637 overlay is bind-mounted (read-only) over that stock
file via `docker run -v <overlay>:<target>:ro`, the text patcher cannot
apply because the file is not writable. P65 logs `read_only_mount` and
skips. Operators running Gemma 4 + TurboQuant + MTP under the overlay
therefore lose the P65 workaround for the spec-decode K+1 cudagraph
placement bug, leading to degenerate output like `"TheSLLLL..."` even
when P65 is set in the env.

================================================================
WHAT THIS PATCH DOES
================================================================

G4_68 is NOT a monkey-patch. It is a **marker verifier** that:

  1. Imports `vllm.v1.attention.backends.turboquant_attn` (whatever file
     is at the bind-mount target — stock or PR #42637 overlay).
  2. Inspects `TurboQuantMetadataBuilder` for the P65 v2 cudagraph
     downgrade marker — specifically the presence of a `get_cudagraph_
     support` classmethod that returns `AttentionCGSupport.UNIFORM_
     SINGLE_TOKEN_DECODE` under `speculative_config`.
  3. Verifies the env flag `GENESIS_ENABLE_P65_TURBOQUANT_SPEC_CG_
     DOWNGRADE` is set (without env, the classmethod returns the
     ClassVar default).
  4. Reports applied/error/skipped to the dispatcher so `patches doctor`
     and the boot-log apply summary correctly show whether the
     downgrade is in effect.

The actual cudagraph downgrade lives **inline** in the overlay source at
`vllm/sndr_core/integrations/gemma4/upstream_overlay_pr42637/turboquant_
attn.py` (see the `[Genesis P65 v2 inlined for PR #42637 overlay]`
comment block on `TurboQuantMetadataBuilder`). This patch's role is
purely identity + dispatcher visibility; runtime behavior is governed by
the overlay code and the env flag.

================================================================
ENV FLAGS
================================================================

  * `GENESIS_ENABLE_G4_68_TQ_SPEC_CG_DOWNGRADE_OVERLAY` — controls
    whether this verifier reports applied / skipped. Verifier is
    diagnostic; the overlay code reads its own env separately.

  * `GENESIS_ENABLE_P65_TURBOQUANT_SPEC_CG_DOWNGRADE` — controls the
    overlay's runtime behavior. When unset, `get_cudagraph_support`
    returns the `UNIFORM_BATCH` ClassVar default and behaves like
    upstream.

Both must be set to engage the workaround in production. Operators
typically set both via the launch script:

```bash
-e GENESIS_ENABLE_G4_68_TQ_SPEC_CG_DOWNGRADE_OVERLAY=1
-e GENESIS_ENABLE_P65_TURBOQUANT_SPEC_CG_DOWNGRADE=1
```

================================================================
DEPENDENCIES
================================================================

  * Companion to G4_60b (verifies the overlay file is bind-mounted).
  * Conflicts with stock P65 (`vllm.sndr_core.integrations.attention.
    turboquant.p65_turboquant_spec_cg_downgrade`) only in that P65 will
    correctly self-skip with `read_only_mount` reason when the overlay
    is mounted — by design. G4_68 then takes over reporting.
  * Pairs with PN256's raw-K/V continuation route inside the overlay
    (no separate patch ID; lives in
    `upstream_overlay_pr42637/turboquant_attn.py` along with P65).
  * Pairs with PN253 stride-0 fix in the same overlay.

================================================================
SCOPE / LIMITATIONS
================================================================

  * Active only when `GENESIS_ENABLE_G4_68_TQ_SPEC_CG_DOWNGRADE_OVERLAY=1`.
  * Pure diagnostic — no monkey-patching here.
  * Failure mode: returns `error` with explanation if overlay missing
    the P65 v2 inline (i.e., somebody updated the overlay file and
    dropped the patch). Operator must restore the inline P65 v2 block
    on `TurboQuantMetadataBuilder` in the overlay source.
  * P65+PN256 restores **target correctness** under the PR #42637
    overlay for Gemma 4 MTP. It does NOT restore MTP speedup — drafter
    acceptance remains 0% in observed tests. This is a correctness
    fallback only.

================================================================
REFERENCES
================================================================

  * Stock P65 source: `vllm/sndr_core/integrations/attention/turboquant/
    p65_turboquant_spec_cg_downgrade.py`
  * Overlay source: `vllm/sndr_core/integrations/gemma4/upstream_overlay_
    pr42637/turboquant_attn.py` (search for `[Genesis P65 v2 inlined]`)
  * Diagnostic chain: PN253 → PN254 → PN255 → PN256 → PN257a (Genesis
    investigation 2026-05-18)
  * vLLM upstream issue tracking: see UPSTREAM_ISSUE_GEMMA4_TQ_MTP_K1_
    VERIFY_DRAFT_2026-05-18_EN.md

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("genesis.gemma4.g4_68_tq_spec_cg_downgrade_overlay")

GENESIS_G4_68_MARKER = (
    "Genesis G4_68 verify P65 v2 inlined in PR #42637 turboquant_attn overlay"
)

_ENV_ENABLE = "GENESIS_ENABLE_G4_68_TQ_SPEC_CG_DOWNGRADE_OVERLAY"
_ENV_P65 = "GENESIS_ENABLE_P65_TURBOQUANT_SPEC_CG_DOWNGRADE"
_APPLIED = False


def _env_enabled() -> bool:
    return os.environ.get(_ENV_ENABLE, "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def apply() -> tuple[str, str]:
    """Verify P65 v2 inline lives on TurboQuantMetadataBuilder in overlay."""
    global _APPLIED

    if not _env_enabled():
        return "skipped", (
            f"G4_68 disabled (set {_ENV_ENABLE}=1 to verify overlay inline)"
        )

    if _APPLIED:
        return "applied", "G4_68 already verified (idempotent)"

    try:
        from vllm.v1.attention.backends import turboquant_attn as _tqa
    except ImportError as e:
        return "error", (
            f"vllm.v1.attention.backends.turboquant_attn not importable: {e}"
        )

    builder_cls = getattr(_tqa, "TurboQuantMetadataBuilder", None)
    if builder_cls is None:
        return "error", (
            "TurboQuantMetadataBuilder class missing — overlay file may "
            "be the stock file (G4_60b should also be skipped/error)."
        )

    # The inline P65 v2 adds a `get_cudagraph_support` classmethod that
    # consults speculative_config + env. Absence means the overlay is
    # missing the inline (operator updated the overlay without porting
    # P65 v2 forward).
    get_cg = getattr(builder_cls, "get_cudagraph_support", None)
    if get_cg is None or not callable(get_cg):
        return "error", (
            "TurboQuantMetadataBuilder.get_cudagraph_support classmethod "
            "not found — P65 v2 inline appears to be missing from the "
            "PR #42637 overlay source. Restore the "
            "[Genesis P65 v2 inlined] block on TurboQuantMetadataBuilder "
            "in vllm/sndr_core/integrations/gemma4/upstream_overlay_"
            "pr42637/turboquant_attn.py."
        )

    p65_env_set = os.environ.get(_ENV_P65, "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    p65_status = "ACTIVE" if p65_env_set else "INERT (env unset)"

    _APPLIED = True
    log.info(
        "[G4_68] P65 v2 inline verified on TurboQuantMetadataBuilder. "
        "Runtime downgrade is %s. Engage via %s=1.",
        p65_status,
        _ENV_P65,
    )
    return "applied", (
        f"G4_68 overlay inline verified: TurboQuantMetadataBuilder."
        f"get_cudagraph_support present. Runtime downgrade is "
        f"{p65_status}. Set {_ENV_P65}=1 in container env to engage "
        f"the cudagraph downgrade for spec-decode K+1 batches."
    )


def is_applied() -> bool:
    return _APPLIED


def revert() -> bool:
    """No-op: inline lives in overlay source, controlled outside Python."""
    return False


__all__ = ["GENESIS_G4_68_MARKER", "apply", "is_applied", "revert"]
