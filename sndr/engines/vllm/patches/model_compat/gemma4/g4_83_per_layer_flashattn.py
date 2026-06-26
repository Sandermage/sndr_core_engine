# SPDX-License-Identifier: Apache-2.0
"""G4_83 — per-layer attention backend for Gemma 4 on Ampere (#38891 backport).

================================================================
WHAT IT FIXES
================================================================

Gemma 4 has heterogeneous head dims: sliding-window layers use
``head_dim=256`` (FlashAttention-capable, head_size<=256) while
full-attention layers use ``global_head_dim=512`` (exceeds FA's kernel
limit). vLLM's ``Gemma4Config.verify_and_update_config`` handles this by:

  * if FA4 is available AND max_head_dim<=512 -> use FA4 for all layers
  * else (backend is None) -> FORCE ``TRITON_ATTN`` for ALL layers

**FA4 is Hopper/Blackwell only.** On Ampere (SM 8.6) the first branch is
always false, so every Gemma 4 layer is forced onto TRITON_ATTN — a
~5-11x attention tax (vllm#38887) on the ~80% of layers (head_dim=256)
that COULD run FlashAttention. This is the dominant TPOT cost of our
Gemma-4-31B (measured 11.9ms decode TPOT).

This patch backports the fix of vllm **PR #38891** (OPEN upstream):
undo the global TRITON_ATTN force on Ampere so each ``Attention`` layer
picks its own backend via the per-head_size ``get_attn_backend()``
selector — sliding-window (256) layers auto-select FlashAttention,
full-attention (512) layers fall back to Triton.

================================================================
WHY THIS IS SAFE WITH OUR kv_sharing CONTRACT
================================================================

Our spec-decode kv_sharing contract (G4_71b/G4_75 drafter override +
G4_69 skip-list [58,59]) requires the kv_sharing layers to stay on a
matching native backend. That is preserved independently:

  * Layer 59 (full_attention, head_dim=512) stays on Triton anyway
    (FlashAttention rejects head_size>256).
  * Layer 58 (sliding, head_dim=256) is held on Triton by the G4_69
    per-layer override (skip-list) regardless of this patch.
  * Drafter[0..2] are held on Triton NHD bf16 by G4_71b/G4_75.

So this patch ONLY changes the ~48 sliding target layers that do NOT
participate in kv_sharing — those go Triton -> FlashAttention.

Validated on the rig (2026-06-21, Gemma-4-31B-AWQ, 2x A5000):
correctness intact (7x6 -> "42", no mixed-backend corruption), drafter
kv_sharing contract intact (G4_71b/G4_75 logs unchanged), decode TPOT
11.9ms -> ~10.9ms median over 3 runs (-8.5%), TPS 65 -> ~70 (+8%).

================================================================
SAFETY MODEL
================================================================

* env_flag: GENESIS_ENABLE_G4_83_GEMMA4_PER_LAYER_BACKEND
* mechanism: only undoes a backend the engine itself force-set to
  TRITON_ATTN when the user did NOT request a backend (``was_none``).
  An explicit operator ``--attention-backend`` is never touched.
* applies_to: architecture gemma4, Ampere (no FA4). No-op where FA4 is
  available (Hopper+) since the force branch is not taken there.
* superseded_by: vllm#38891 when it merges + lands in our pin.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
References:
  * vllm PR #38891 (per-layer Gemma4 backend), issue #38887
  * vllm/model_executor/models/config.py — Gemma4Config force branch
  * Our G4_69 / G4_71b / G4_75 (kv_sharing contract, preserved)
"""
from __future__ import annotations

import logging

from ._gemma4_detect import env_truthy, is_gemma4_arch

log = logging.getLogger("genesis.gemma4.g4_83_per_layer_backend")

GENESIS_G4_83_MARKER = (
    "Genesis G4_83 gemma4 per-layer attention backend v1 (#38891 backport; "
    "undo Ampere TRITON_ATTN force -> sliding-256 layers use FlashAttention)"
)

_ENV_ENABLE = "GENESIS_ENABLE_G4_83_GEMMA4_PER_LAYER_BACKEND"

_APPLIED = False
_ORIGINAL_VERIFY = None


def _env_enabled() -> bool:
    return env_truthy(_ENV_ENABLE)


def _triton_backend_enum():
    """Return AttentionBackendEnum.TRITON_ATTN or None if unavailable."""
    try:
        from vllm.v1.attention.backends.registry import AttentionBackendEnum
        return AttentionBackendEnum.TRITON_ATTN
    except Exception:  # noqa: BLE001
        return None


def apply() -> tuple[str, str]:
    """Install per-layer backend override via Gemma4Config wrapper."""
    global _APPLIED, _ORIGINAL_VERIFY

    if not _env_enabled():
        return "skipped", (
            f"G4_83 disabled (set {_ENV_ENABLE}=1 to allow per-layer attention "
            "backend on Gemma 4 — sliding-256 layers use FlashAttention instead "
            "of the forced TRITON_ATTN; ~8% TPOT on Ampere, kv_sharing preserved)"
        )

    if _APPLIED:
        return "applied", "G4_83 already installed (idempotent)"

    # verify_and_update_config moved gemma4 -> config across pins; search both.
    _candidate_modules: list[tuple[str, object]] = []
    try:
        from vllm.model_executor.models import config as _g4_cfg_mod
        _candidate_modules.append(("vllm.model_executor.models.config", _g4_cfg_mod))
    except ImportError:
        pass
    try:
        from vllm.model_executor.models import gemma4 as _g4_legacy_mod
        _candidate_modules.append(("vllm.model_executor.models.gemma4", _g4_legacy_mod))
    except ImportError:
        pass

    if not _candidate_modules:
        return "skipped", (
            "Neither vllm.model_executor.models.config nor .gemma4 importable; "
            "G4_83 is no-op on this pin"
        )

    target_cls = None
    for cls_name in (
        "Gemma4Config", "Gemma4TextConfig", "Gemma4ForConditionalGenerationConfig",
    ):
        for _mod_name, mod in _candidate_modules:
            cls = getattr(mod, cls_name, None)
            if cls is not None and hasattr(cls, "verify_and_update_config"):
                target_cls = cls
                break
        if target_cls is not None:
            break
    if target_cls is None:
        return "skipped", (
            "No Gemma4Config-like class with verify_and_update_config found; "
            "G4_83 is no-op on this pin"
        )

    original = target_cls.verify_and_update_config
    if getattr(original, "_genesis_g4_83_wrapped", False):
        _APPLIED = True
        return "applied", "G4_83 already wrapped (idempotent)"
    _ORIGINAL_VERIFY = original

    triton_enum = _triton_backend_enum()

    def _genesis_g4_83_wrapped_verify(vllm_config):
        # Snapshot the user's backend choice BEFORE the original runs so we
        # only undo an engine-applied force, never an explicit operator choice.
        ac = getattr(vllm_config, "attention_config", None)
        was_none = ac is not None and getattr(ac, "backend", "sentinel") is None

        result = original(vllm_config)

        try:
            mc = getattr(vllm_config, "model_config", None)
            if (
                ac is not None
                and mc is not None
                and is_gemma4_arch(mc)
                and was_none
                and triton_enum is not None
                and getattr(ac, "backend", None) == triton_enum
            ):
                # The original force-set TRITON_ATTN globally (Ampere, no FA4).
                # Undo it -> per-layer get_attn_backend(): sliding-256 picks
                # FlashAttention, global-512 falls back to Triton. The G4_69
                # skip-list + G4_71b/G4_75 keep kv_sharing layers on Triton.
                ac.backend = None
                ac._genesis_g4_83_per_layer = True
                log.warning(
                    "[G4_83] undid global TRITON_ATTN force -> per-layer backend "
                    "(sliding-256 -> FlashAttention, global-512 -> Triton). "
                    "kv_sharing layers stay on Triton via G4_69/G4_71b."
                )
        except Exception as e:  # noqa: BLE001
            log.warning("[G4_83] per-layer restore failed: %r; leaving as-is", e)
        return result

    _genesis_g4_83_wrapped_verify._genesis_g4_83_wrapped = True
    _genesis_g4_83_wrapped_verify.__wrapped__ = original

    def _classmethod_shim(cls, vllm_config):
        return _genesis_g4_83_wrapped_verify(vllm_config)
    _classmethod_shim._genesis_g4_83_wrapped = True
    target_cls.verify_and_update_config = classmethod(_classmethod_shim)
    _APPLIED = True
    log.info(
        "[G4_83] installed: Gemma 4 per-layer attention backend (sliding->FA)."
    )
    return "applied", (
        "G4_83 installed: Gemma 4 sliding-256 layers now use FlashAttention "
        "instead of forced TRITON_ATTN (#38891 backport). ~8% TPOT on Ampere; "
        "kv_sharing contract preserved via G4_69/G4_71b/G4_75."
    )


def is_applied() -> bool:
    return _APPLIED


def revert() -> bool:
    global _APPLIED, _ORIGINAL_VERIFY
    if not _APPLIED or _ORIGINAL_VERIFY is None:
        return False
    _modules = []
    try:
        from vllm.model_executor.models import config as _m
        _modules.append(_m)
    except ImportError:
        pass
    try:
        from vllm.model_executor.models import gemma4 as _m
        _modules.append(_m)
    except ImportError:
        pass
    for _g4_mod in _modules:
        for cls_name in (
            "Gemma4Config", "Gemma4TextConfig", "Gemma4ForConditionalGenerationConfig",
        ):
            cls = getattr(_g4_mod, cls_name, None)
            if cls is not None and getattr(
                cls.verify_and_update_config, "_genesis_g4_83_wrapped", False
            ):
                cls.verify_and_update_config = _ORIGINAL_VERIFY  # type: ignore[assignment]
                _APPLIED = False
                return True
    return False


__all__ = ["GENESIS_G4_83_MARKER", "apply", "is_applied", "revert"]
