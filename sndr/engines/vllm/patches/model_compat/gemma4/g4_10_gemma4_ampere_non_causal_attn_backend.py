# SPDX-License-Identifier: Apache-2.0
"""G4_10 — Ampere SM 8.6 non-causal drafter enablement guard for Gemma 4.

================================================================
WHAT THIS DOES (reframed 2026-06-16 after a dev491 ground-truth study)
================================================================

G4_10 is the opt-in flag that tells G4_03 to let an EAGLE-3 / DFlash
(non-causal) drafter through on Ampere SM 8.6 + Gemma 4. When
``GENESIS_ENABLE_G4_10_GEMMA4_AMPERE_NON_CAUSAL_BACKEND=1`` is set,
``g4_03_gemma4_ampere_non_causal_drafter_guard`` stops refusing and lets
the drafter build (g4_03 lines 215-225).

The drafter's attention then runs on STOCK ``TRITON_ATTN``. No bespoke
Genesis backend or kernel is needed — verified against the dev491 pin
(``0.22.1rc1.dev491+g1033ffac2``):

  * ``TritonAttentionBackend.supports_non_causal() -> True``
    (vllm/v1/attention/backends/triton_attn.py:277-279)
  * ``TritonAttentionBackend.supports_head_size(h) -> h >= 32`` — so head_dim
    256 (sliding) AND 512 (global) both pass (triton_attn.py:347-348)
  * non-causal is a runtime metadata flag, not a kernel: stock
    ``context_attention_fwd(..., is_causal=False, ...)`` already serves it
    (triton_attn.py:686) and is production-exercised.

The drafter's per-layer routing onto ``TRITON_ATTN`` is already owned by two
shipped patches (each a disjoint head_size class):

  * ``g4_71b_drafter_sliding_triton``  — drafter head_size=256 -> TRITON_ATTN
  * ``g4_75_drafter_head512_triton``    — drafter head_size=512 -> TRITON_ATTN

So to run an EAGLE-3 / DFlash drafter on this hardware: enable G4_10 (to lift
the G4_03 refusal) together with g4_71b + g4_75 (the reroute), and pin the
draft backend explicitly via ``speculative_config.attention_backend: TRITON_ATTN``
if the proposer does not already inherit it.

================================================================
WHY THE OLD BESPOKE BACKEND/KERNEL WAS REPLACED
================================================================

The previous G4_10 registered a custom ``G4AmperetNonCausalAttentionBackend``
wrapping a hand-rolled head_dim=256 Triton kernel
(``kernels/g4_non_causal_attn_triton.py``). That path was:

  * a NO-OP on dev491 — it looked up ``getattr(AttentionBackendEnum,
    "register_backend")`` (a classmethod) but dev491's ``register_backend`` is
    a module-level decorator taking ``AttentionBackendEnum.CUSTOM`` + a dotted
    class_path (registry.py:217-269), so registration always fell to the dead
    "no register API" branch;
  * REDUNDANT — stock TRITON_ATTN already does non-causal head 256/512 (above);
  * INCOMPLETE — the kernel only handled head_dim=256 (hard-raised on 512),
    had a divide-by-zero NaN on fully-masked rows, and had no test (the
    docstring's ``test_g4_10_non_causal_attn.py`` never existed).

The bespoke backend class + kernel were deleted. Reinventing a wheel that
already turns inside dev491 (TRITON_ATTN + ``context_attention_fwd`` + PN351's
head>=512 path + the g4_71/g4_75 drafter-routing cluster) is exactly the
anti-pattern iron-rule "Search/Compare" guards against.

Lifecycle: experimental, default_on=False, conflicts_with G4_03.
References: vllm#40382 (the backend-matrix wall — now closed on dev491),
vllm#39930 (independent drafter attention-backend selection, merged 2026-04-28).
"""
from __future__ import annotations

import logging

from ._gemma4_detect import env_truthy

log = logging.getLogger("genesis.gemma4.g4_10_non_causal_enablement")

GENESIS_G4_10_MARKER = (
    "Genesis G4_10 gemma4 ampere non-causal drafter enablement guard v2 "
    "(stock TRITON_ATTN does the job; bespoke kernel retired 2026-06-16)"
)

_ENV_ENABLE = "GENESIS_ENABLE_G4_10_GEMMA4_AMPERE_NON_CAUSAL_BACKEND"

_APPLIED = False


def _env_enabled() -> bool:
    return env_truthy(_ENV_ENABLE)


def apply() -> tuple[str, str]:
    """Enablement marker: lift G4_03's refusal + confirm TRITON_ATTN is capable.

    Registers no bespoke backend. The drafter runs on stock TRITON_ATTN, routed
    per-layer by g4_71b (head=256) + g4_75 (head=512). apply() best-effort
    verifies the stock backend really supports non-causal on this pin so a
    misconfigured (too-old) pin fails LOUD rather than silently mis-routing.
    """
    global _APPLIED

    if not _env_enabled():
        return "skipped", (
            f"G4_10 disabled (set {_ENV_ENABLE}=1 to lift the G4_03 refusal and "
            "run an EAGLE-3 / DFlash drafter on stock TRITON_ATTN; pair with "
            "g4_71b + g4_75 for the per-layer drafter routing)"
        )

    if _APPLIED:
        return "applied", "G4_10 enablement already active (idempotent)"

    # Verify the premise on the live pin: stock TRITON_ATTN must support
    # non-causal + head 256/512. If a too-old pin lacks this, fail LOUD — the
    # drafter would otherwise hit a hard ValueError at backend validation.
    try:
        from vllm.v1.attention.backends.triton_attn import (
            TritonAttentionBackend as _T,
        )
    except ImportError as e:
        log.warning(
            "[G4_10] enabled but vllm TritonAttentionBackend not importable on "
            "this pin (%s); cannot confirm the non-causal drafter path. Ensure "
            "the drafter is routed to a non-causal-capable backend.", e,
        )
        return "skipped", (
            "TritonAttentionBackend not importable on this pin; G4_10 enablement "
            "cannot confirm the TRITON_ATTN non-causal path"
        )

    non_causal_ok = bool(getattr(_T, "supports_non_causal", lambda: False)())
    head256_ok = bool(getattr(_T, "supports_head_size", lambda *_: False)(256))
    head512_ok = bool(getattr(_T, "supports_head_size", lambda *_: False)(512))
    if not (non_causal_ok and head256_ok and head512_ok):
        log.error(
            "[G4_10] enabled but stock TRITON_ATTN on this pin does NOT cover the "
            "non-causal drafter path (non_causal=%s, head256=%s, head512=%s). The "
            "EAGLE-3/DFlash drafter would crash at backend validation. Pin too old "
            "for this enablement — keep G4_03 refusing or upgrade the pin.",
            non_causal_ok, head256_ok, head512_ok,
        )
        return "partial", (
            "stock TRITON_ATTN on this pin lacks non-causal/head 256/512 support "
            f"(non_causal={non_causal_ok}, head256={head256_ok}, head512={head512_ok})"
        )

    _APPLIED = True
    log.info(
        "[G4_10] enabled: G4_03 will let the EAGLE-3 / DFlash drafter through; it "
        "runs on stock TRITON_ATTN (non-causal head 256/512 confirmed). Per-layer "
        "drafter routing owned by g4_71b (256) + g4_75 (512)."
    )
    return "applied", (
        "G4_10 enablement active: EAGLE-3 / DFlash drafter permitted on Ampere "
        "SM 8.6 + Gemma 4 via stock TRITON_ATTN (non-causal head 256/512 verified). "
        "Routing: g4_71b + g4_75. No bespoke Genesis backend/kernel."
    )


def is_applied() -> bool:
    return _APPLIED


def revert() -> bool:
    """Enablement is a config gate (read by G4_03 at drafter build); nothing
    to unwind at runtime."""
    global _APPLIED
    _APPLIED = False
    return True


__all__ = [
    "GENESIS_G4_10_MARKER",
    "apply",
    "is_applied",
    "revert",
]
