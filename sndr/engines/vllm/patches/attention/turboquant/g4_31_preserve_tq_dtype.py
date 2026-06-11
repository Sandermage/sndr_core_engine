# SPDX-License-Identifier: Apache-2.0
"""G4_31 — preserve operator kv_cache_dtype intent against quant-config overrides.

Two suppress arms wrap ``Attention.__init__``:

  Arm 1 (original, 2026-05-21): preserve ``turboquant_*`` kv_cache_dtype
         against the AWQ/llm-compressor ``kv_cache_scheme`` override.
  Arm 2 (v2, 2026-06-11, vllm#45038 adaptation): suppress the
         checkpoint-driven fp8 KV auto-override on sub-SM90 devices.

================================================================
ARM 1 — PROBLEM (original, pre-0.22.1 pins)
================================================================

When booting Gemma 4 AWQ-4bit with ``--kv-cache-dtype turboquant_4bit_nc
--attention-backend TURBOQUANT`` + G4_30 (multimodal unblock), the
``TurboQuantAttentionBackend`` validation rejects with::

    ValueError: Selected backend AttentionBackendEnum.TURBOQUANT is not
    valid for this configuration. Reason: ['kv_cache_dtype not supported']

The TQ backend's ``supports_kv_cache_dtype()`` accepts any ``turboquant_*``
string and rejects everything else. So at validation time, the dtype
must have already been overridden away from ``turboquant_4bit_nc``.

On the dev371-era pins, ``Attention.__init__`` showed the override path::

    kv_cache_dtype = cache_config.cache_dtype       # "turboquant_4bit_nc"
    kv_cache_scheme = getattr(quant_config, "kv_cache_scheme", None)
    if kv_cache_scheme is not None:                 # <-- AWQ sets this
        kv_cache_dtype = "fp8"                      # <-- override!
        ...

The llm-compressor / AWQ quant config carries a ``kv_cache_scheme``
hint intended for FP8 KV caches. When set, vllm hard-overrode
``kv_cache_dtype`` to "fp8" — silently discarding our CLI flag and the
operator's TurboQuant intent.

================================================================
ARM 1 — REACHABILITY AUDIT ON PIN 0.22.1rc1.dev259+g303916e93
(2026-06-11, vllm#45038 vendoring pass; pristine tree byte-verified)
================================================================

On the current pin the override block gained an ``== "auto"`` conjunct
(pristine ``attention.py:237-243``)::

    kv_cache_scheme = getattr(quant_config, "kv_cache_scheme", None)
    if kv_cache_scheme is not None and kv_cache_dtype == "auto":
        kv_cache_dtype = "fp8"
        calculate_kv_scales = False
        if cache_config is not None:
            cache_config.cache_dtype = "fp8"
            cache_config.calculate_kv_scales = False

With an explicit ``--kv-cache-dtype turboquant_4bit_nc`` the dtype is
not "auto", the conjunct is False, and the override CANNOT fire — so
Arm 1's suppression is UNREACHABLE-redundant on this pin for its
original trigger. The only other "auto" resolution site,
``resolve_kv_cache_dtype_string`` (pristine ``utils/torch_utils.py:375``),
consults ModelOpt-style ``kv_cache_quant_algo`` only — it never touches
turboquant_* dtypes either. Arm 1 is therefore dormant insurance on
0.22.1: kept per the "don't remove behavior" mandate (the parent
ModelDef pin_holds 626fa9bb where Arm 1 IS load-bearing, and a future
upstream regression of the ``== "auto"`` conjunct would silently
re-break TQ without it). Zero steady-state cost — the wrap is
init-time only.

================================================================
ARM 2 — PROBLEM (vllm#45038 / issue #44879, OPEN upstream 2026-06-11)
================================================================

The same pristine block above auto-overrides ``auto`` → ``fp8`` whenever
the checkpoint declares ``kv_cache_scheme`` — UNCONDITIONALLY on device
capability. FP8 KV attention kernels (FlashInfer) exist only on SM90+;
on sub-SM90 (our 2x RTX A5000, SM 8.6) the override arms a CUDA
illegal-memory-access crash, observed upstream under MTP speculative
decoding bursts (issue #44879 — L4/RTX 4090, compressed-tensors FP8
checkpoint). Our live exposure: the Gemma-4-31B kv-auto degraded
profile (cache_dtype "auto", AWQ compressed-tensors checkpoint, MTP
K=3, max_num_seqs=8 burst envelope).

Upstream #45038 guards the override with
``current_platform.has_device_capability(90)`` and logs a warning on
older GPUs. Adaptation here (iron rule #10 — adapt, don't copy):

  * Same trigger predicate: ``cache_dtype == "auto"`` AND
    ``kv_cache_scheme`` present AND NOT SM90+ (unknown capability is
    treated as not-SM90, byte-matching upstream's
    ``has_device_capability`` False-on-None semantics).
  * Suppression mechanism reuses Arm 1's proven scheme-clearing wrap
    (hide ``quant_config.kv_cache_scheme`` for the duration of
    ``__init__``, restore in ``finally``). This suppresses BOTH the
    local "fp8" rebind and the global late mutation of
    ``cache_config.cache_dtype`` that upstream's version also kills.
    Deliberate difference vs upstream: hiding the scheme also leaves
    ``use_per_head_quant_scales`` (pristine ``attention.py:246-248``)
    False for the call — correct here, since we refuse fp8 KV entirely
    on this device class, so per-head fp8 scale plumbing must not
    steer backend selection either.
  * Late-mutation INVARIANT log: after the wrapped ``__init__``
    returns, ``cache_config.cache_dtype`` must still equal its
    pre-call value; if any other path mutated it, we log loudly
    instead of letting the #44879 class re-arm silently.
  * Operators can still force fp8 via explicit ``--kv-cache-dtype
    fp8`` (the arm only fires on "auto"), preserving upstream's
    escape hatch.

Escape to a working fp8 KV on Ampere is the sibling patch G4_80
(vllm#45040 — fp8_e5m2 for weight-only checkpoints) + the
``gemma4-31b-fp8e5m2-fallback`` profile; Arm 2 protects the interim
kv-auto state, G4_80 provides the exit (roadmap 2026-06-11 chunk-3
Theme B sequencing: guard first, then fallback profile).

================================================================
SCOPE
================================================================

Behavior changes only when ``GENESIS_ENABLE_G4_31_TQ_DTYPE_PRESERVE=1``
(both arms share the flag — registry entry G4_31, no new id) AND:

  Arm 1: ``cache_config.cache_dtype`` starts with ``turboquant_`` and
         ``quant_config.kv_cache_scheme`` is set; or
  Arm 2: ``cache_config.cache_dtype == "auto"``, the scheme is set,
         and the device is not SM90+.

Both arms read configs from kwargs only (every in-tree caller passes
``cache_config=`` / ``quant_config=`` by keyword); positional callers
fall through to pristine behavior (fail-open by design). For non-TQ
SM90+ operators this patch is a no-op even when enabled.

================================================================
RISK
================================================================

The model's ``kv_cache_scheme`` typically controls FP8 KV calibration
metadata. By suppressing it during ``Attention.__init__``, we tell vllm
"do NOT use the model's FP8 scheme for the KV cache" — the model's own
weights quantization is unaffected. For Arm 1 the TurboQuant backend
manages its own KV quantization; for Arm 2 the KV cache simply stays
in the model dtype (bf16), trading VRAM for not crashing.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("genesis.turboquant.g4_31_tq_dtype_preserve")

GENESIS_G4_31_MARKER = (
    "Genesis G4_31 preserve operator kv_cache_dtype against AWQ "
    "kv_cache_scheme override (Attention.__init__ wrap; TQ arm + "
    "sub-SM90 fp8-auto arm per vllm#45038)"
)

_ENV_ENABLE = "GENESIS_ENABLE_G4_31_TQ_DTYPE_PRESERVE"
_APPLIED = False
_ORIGINAL_INIT = None
_DEBUG_HITS: list = []
_FP8_AUTO_HITS: list = []

# Test seam: None → query vllm's current_platform; True/False → forced.
_SM90_OVERRIDE: bool | None = None


def _env_enabled() -> bool:
    return os.environ.get(_ENV_ENABLE, "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _has_sm90() -> bool:
    """True only when the device is POSITIVELY SM90+.

    Mirrors upstream #45038's ``current_platform.has_device_capability(90)``
    semantics exactly: unknown capability (None) → False → the fp8
    auto-override is suppressed, matching the upstream guard's
    fall-through. Import or query failure is treated the same way.
    """
    if _SM90_OVERRIDE is not None:
        return _SM90_OVERRIDE
    try:
        from vllm.platforms import current_platform
        return bool(current_platform.has_device_capability(90))
    except Exception:  # noqa: BLE001 — capability unknown → not SM90
        return False


def _should_suppress_turboquant(cache_dtype, scheme) -> bool:
    """Arm 1: operator requested turboquant_* and checkpoint declares
    a kv_cache_scheme (dormant on 0.22.1 — see docstring audit)."""
    return (
        isinstance(cache_dtype, str)
        and cache_dtype.startswith("turboquant_")
        and scheme is not None
    )


def _should_suppress_fp8_auto(cache_dtype, scheme) -> bool:
    """Arm 2 (vllm#45038): checkpoint kv_cache_scheme would auto-override
    "auto" → fp8 KV, but the device has no SM90+ fp8 attention kernels
    (IMA-crash class #44879 on Ampere MTP bursts)."""
    return cache_dtype == "auto" and scheme is not None and not _has_sm90()


def _make_wrapped_init(original):
    """Build the ``Attention.__init__`` wrapper around *original*.

    Factored out of apply() so torch-less unit tests can exercise the
    suppression mechanics against fake originals.
    """

    def _wrapped_init(self, *args, **kwargs):
        cache_config = kwargs.get("cache_config")
        quant_config = kwargs.get("quant_config")
        cache_dtype = (
            getattr(cache_config, "cache_dtype", None) if cache_config else None
        )
        scheme = (
            getattr(quant_config, "kv_cache_scheme", None)
            if quant_config else None
        )

        # Diagnostic log for first 3 calls (override-path visibility).
        if len(_DEBUG_HITS) < 3:
            _DEBUG_HITS.append((kwargs.get("prefix", "?"), cache_dtype, scheme))
            log.warning(
                "[G4_31 DIAG] Attention.__init__ prefix=%s cache_dtype=%r "
                "quant_cls=%s kv_cache_scheme=%r",
                kwargs.get("prefix", "?"), cache_dtype,
                type(quant_config).__name__ if quant_config else None,
                scheme,
            )

        suppress_tq = _should_suppress_turboquant(cache_dtype, scheme)
        suppress_fp8_auto = not suppress_tq and _should_suppress_fp8_auto(
            cache_dtype, scheme
        )

        if not (suppress_tq or suppress_fp8_auto):
            return original(self, *args, **kwargs)

        if suppress_tq and len(_DEBUG_HITS) < 6:
            _DEBUG_HITS.append(kwargs.get("prefix", "?"))
            log.warning(
                "[G4_31] suppressing kv_cache_scheme override at %s: "
                "cache_dtype=%s, prior scheme=%r",
                kwargs.get("prefix", "?"), cache_dtype, scheme,
            )
        if suppress_fp8_auto and len(_FP8_AUTO_HITS) < 3:
            _FP8_AUTO_HITS.append(kwargs.get("prefix", "?"))
            log.warning(
                "[G4_31] sub-SM90 fp8 KV auto-override suppressed at %s "
                "(vllm#45038 arm): checkpoint kv_cache_scheme=%r would "
                "rebind cache_dtype 'auto' -> 'fp8', but this device has "
                "no SM90+ fp8 attention kernels (IMA-crash class #44879). "
                "KV cache stays in model dtype; force --kv-cache-dtype "
                "fp8 explicitly to override, or use the fp8_e5m2 fallback "
                "profile (G4_80).",
                kwargs.get("prefix", "?"), scheme,
            )

        try:
            quant_config.kv_cache_scheme = None
            return original(self, *args, **kwargs)
        finally:
            # Restore — keep the model's true intent visible to other code.
            try:
                quant_config.kv_cache_scheme = scheme
            except Exception:  # noqa: BLE001
                pass
            # Late-mutation INVARIANT (Arm 2): with the scheme hidden,
            # nothing inside __init__ may rebind cache_config.cache_dtype.
            # A mutation here means another override path re-armed the
            # #44879 crash class behind our back — log loudly.
            if suppress_fp8_auto and cache_config is not None:
                dtype_after = getattr(cache_config, "cache_dtype", None)
                if dtype_after != cache_dtype:
                    log.warning(
                        "[G4_31 INVARIANT] cache_config.cache_dtype mutated "
                        "%r -> %r during Attention.__init__ at %s DESPITE "
                        "the sub-SM90 suppress arm — an unguarded override "
                        "path exists on this pin; re-audit attention.py "
                        "against vllm#45038.",
                        cache_dtype, dtype_after, kwargs.get("prefix", "?"),
                    )

    return _wrapped_init


def apply() -> tuple[str, str]:
    """Install the Attention.__init__ wrap (both suppress arms)."""
    global _APPLIED, _ORIGINAL_INIT

    if not _env_enabled():
        return "skipped", (
            f"G4_31 disabled (set {_ENV_ENABLE}=1 to preserve operator "
            "kv_cache_dtype against AWQ kv_cache_scheme override: "
            "turboquant_* arm + sub-SM90 fp8-auto arm)"
        )

    if _APPLIED:
        return "applied", "G4_31 already installed (idempotent)"

    try:
        from vllm.model_executor.layers.attention.attention import Attention
    except ImportError as e:
        return "skipped", f"vllm.model_executor.layers.attention not importable: {e}"

    original = Attention.__init__
    if getattr(original, "_genesis_g4_31_wrapped", False):
        _APPLIED = True
        return "applied", "Attention.__init__ already wrapped (idempotent)"

    _ORIGINAL_INIT = original

    _wrapped_init = _make_wrapped_init(original)
    _wrapped_init._genesis_g4_31_wrapped = True
    _wrapped_init.__wrapped__ = original
    Attention.__init__ = _wrapped_init

    # Additional diagnostic: hook supports_kv_cache_dtype on TQ backend
    # to capture what dtype actually reaches the validator.
    try:
        from vllm.v1.attention.backends.turboquant_attn import (
            TurboQuantAttentionBackend,
        )
        _orig_supports = TurboQuantAttentionBackend.supports_kv_cache_dtype
        _supports_hits = []

        def _diag_supports_kv_cache_dtype(cls, kv_cache_dtype):
            result = _orig_supports.__func__(cls, kv_cache_dtype)
            if len(_supports_hits) < 5:
                _supports_hits.append((kv_cache_dtype, result))
                log.warning(
                    "[G4_31 SUPPORTS] supports_kv_cache_dtype(%r) -> %r",
                    kv_cache_dtype, result,
                )
            return result

        TurboQuantAttentionBackend.supports_kv_cache_dtype = classmethod(
            _diag_supports_kv_cache_dtype
        )
        log.info("[G4_31] diagnostic supports_kv_cache_dtype hook installed")
    except Exception as e:  # noqa: BLE001
        log.warning("[G4_31] could not hook supports_kv_cache_dtype: %r", e)

    _APPLIED = True

    log.info(
        "[G4_31] installed: Attention.__init__ now suppresses the "
        "kv_cache_scheme override for turboquant_* dtypes (arm 1, dormant "
        "on 0.22.1) and for the sub-SM90 fp8 auto-override (arm 2, "
        "vllm#45038)."
    )
    return "applied", (
        "G4_31 installed: AWQ kv_cache_scheme override suppressed for "
        "turboquant_* operator intent (arm 1) and for cache_dtype='auto' "
        "on sub-SM90 devices (arm 2, vllm#45038 — kills the #44879 "
        "fp8-KV IMA-crash landmine on Ampere)."
    )


def is_applied() -> bool:
    return _APPLIED


def revert() -> bool:
    global _APPLIED, _ORIGINAL_INIT
    if not _APPLIED or _ORIGINAL_INIT is None:
        return False
    try:
        from vllm.model_executor.layers.attention.attention import Attention
        Attention.__init__ = _ORIGINAL_INIT
        _APPLIED = False
        return True
    except ImportError:
        return False


__all__ = [
    "GENESIS_G4_31_MARKER",
    "apply",
    "is_applied",
    "revert",
]
