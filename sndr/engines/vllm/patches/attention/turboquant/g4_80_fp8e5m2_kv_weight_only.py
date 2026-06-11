# SPDX-License-Identifier: Apache-2.0
"""G4_80 — allow fp8_e5m2 KV cache for weight-only checkpoints (vllm#45040).

================================================================
PROBLEM (vllm#45040 / issue #39137, OPEN upstream as of 2026-06-11)
================================================================

The pristine ``_init_kv_cache_quant`` helper
(``vllm/model_executor/layers/attention/attention.py:158-174`` on pin
0.22.1rc1.dev259+g303916e93, byte-verified) rejects ``--kv-cache-dtype
fp8_e5m2`` for EVERY quantized checkpoint whose quant method loads KV
scales::

    if should_load_quant_weights(quant_method):
        assert isinstance(quant_method, BaseKVCacheMethod)
        if layer.kv_cache_dtype == "fp8_e5m2":
            raise ValueError(
                "fp8_e5m2 kv-cache is not supported with fp8 checkpoints.")

But weight-only checkpoints (INT4/INT8/AWQ/GPTQ in compressed-tensors
format) carry NO fp8 KV scales — they only hit this gate because
``CompressedTensorsConfig.get_quant_method`` returns
``CompressedTensorsKVCacheMethod`` for every Attention layer
(pristine ``compressed_tensors.py:205-206``), regardless of whether the
checkpoint declares a ``kv_cache_scheme``. On Ampere (SM 8.6 — our 2x
RTX A5000), ``fp8_e5m2`` is the only fp8 KV dtype the hardware runs at
all, so the gate makes fp8 KV unreachable for every weight-quantized
model — including Gemma-4-31B AWQ (compressed-tensors; the cyankiwi
checkpoint is CT, not stock awq_marlin — see the ModelDef note).

Why we care: 31B KV @200K ctx is ~9.4 GiB in bf16; fp8_e5m2 halves it
(~4.7 GiB), restoring the full 256K context path WITHOUT TurboQuant
(TQ is blocked on this pin by the mm validity gate — G4_79 saga).

================================================================
SECOND GATE — query-quant forward assert (review fix, 2026-06-11)
================================================================

Unblocking ``_init_kv_cache_quant`` is NOT sufficient: a second
pristine gate stays armed for exactly the configuration our fallback
profile pins. ``Attention.__init__`` creates ``self.query_quant`` for
ANY fp8* kv_cache_dtype whenever ``impl.supports_quant_query_input``
(pristine ``attention.py:418-435``; ``"fp8_e5m2".startswith("fp8")``),
and ``TritonAttentionImpl`` sets ``supports_quant_query_input =
current_platform.is_cuda()`` unconditionally (pristine
``triton_attn.py:502``). The FIRST forward — the boot memory-profiling
dummy run — then hits ``assert self.kv_cache_dtype in {"fp8",
"fp8_e4m3", "nvfp4"}`` (pristine ``attention.py:467``) →
AssertionError → boot-DOA. No upstream fix exists (gh search 2026-06-11:
only #45040 touches fp8_e5m2 gating, and it leaves the assert alone —
viable upstream only because their reference impls gate
``supports_quant_query_input`` on trtllm/SM100, e.g.
``flashinfer.py:1324-1328``).

Arm 2 therefore nulls ``self.query_quant`` post-``__init__`` for
fp8_e5m2 layers. This is safe and upstream-faithful in spirit:

  * ``query_quant`` is an OPTIMIZATION (quantize the query once with a
    torch op so torch.compile fuses it); forwarding an unquantized
    query is always a supported path — ``TritonAttentionImpl.forward``
    dtype-gates ``q_descale`` (``query.dtype == self.fp8_dtype``,
    pristine ``triton_attn.py:607-614``) and runs the bf16-query /
    fp8-KV combination natively.
  * ``QuantFP8`` emits e4m3 only — an "e5m2 query quant" does not
    exist on this pin, so nothing is lost by disabling it; no source
    drift-guard is needed (a future pin where e5m2 query quant works
    costs us only a disabled optimization, never correctness).

================================================================
BACKEND AUDIT for the consuming profile (verified on pristine tree)
================================================================

TRITON_ATTN is the ONLY in-pin backend serving the 31B mm model with
fp8 KV — every alternative is statically dead:

  * FLASH_ATTN: ``supported_kv_cache_dtypes`` = [auto, float16,
    bfloat16] only (``flash_attn.py:70-74``) — no fp8 at all.
  * FLASHINFER: lists fp8_e5m2 with TRUE e5m2 handling and no query
    quant sub-SM90 — but ``supports_mm_prefix()`` stays base-class
    False, and Gemma-4-31B MM is an mm-prefix LM
    (``Gemma4ModelArchConfigConvertor.is_mm_prefix_lm``;
    ``Attention.__init__`` passes ``use_mm_prefix`` into backend
    validation, ``attention.py:298,310``), so ``validate_configuration``
    rejects it: "partial multimodal token full attention not supported"
    (``backend.py:301-303``). Same gate class that birthed G4_60L/G4_79.
  * FLEX_ATTENTION: supports mm_prefix but only auto/float16/bfloat16
    KV (``flex_attention.py:86-90``).
  * TURBOQUANT: blocked on this pin (G4_79 saga).

KNOWN MASQUERADE (document, don't hide): TRITON_ATTN stores AND loads
quantized KV as ``current_platform.fp8_dtype()`` — e4m3fn on CUDA —
regardless of the e4m3/e5m2 string (store:
``triton_reshape_and_cache_flash.py:364-376``; load:
``triton_attn.py:597-602``). Selecting fp8_e5m2 on this backend
delivers 1-byte KV with e4m3 numerics and unit scales (the standard
fp8-KV configuration; e4m3 has MORE mantissa than e5m2, so accuracy is
not degraded by the masquerade). Triton emulates fp8e4m3fn casts on
pre-SM89 CUDA — first boot must confirm kernel compilation on SM 8.6
(profile boot gate). Why not plain ``--kv-cache-dtype fp8`` then (it
passes the pristine gate for CT checkpoints!): "fp8" keeps
``query_quant`` ACTIVE → the quantized-query fp8 kernel surface on
sub-SM90, the exact class behind the #44879 IMA evidence that
motivated #45038. fp8_e5m2 + arm 2 keeps the query in model dtype —
the conservative configuration.

================================================================
ADAPTATION (iron rule #10 — adapt, don't blind-copy)
================================================================

Upstream #45040 adds a ``_checkpoint_has_fp8_kv_scales(quant_method)``
predicate and qualifies the gate with it: a compressed-tensors
checkpoint stores fp8 KV scales ONLY when it declares a
``kv_cache_scheme``; weight-only ones declare none. Genuine fp8
checkpoints (and CT fp8-KV) stay rejected.

We cannot text-patch the function body cheaply here (the module is
imported very early); instead we REBIND the module-level symbol with a
wrapper that masks ``layer.kv_cache_dtype`` ("fp8_e5m2" -> "fp8") for
the duration of the original call when the predicate allows, restoring
it in ``finally``. Verified safe on the pristine pin: within
``_init_kv_cache_quant`` the ONLY read of ``layer.kv_cache_dtype`` is
the reject gate itself (attention.py:167); ``create_weights``
(``quantization/kv_cache.py:57``) never reads it. Downstream consumers
(kv-cache specs, backend validation, the query-quant creation block at
attention.py:418-435) see the restored "fp8_e5m2" — which is exactly
why arm 2 (SECOND GATE above) must then neutralize ``query_quant``:
the restored e5m2 string fails the forward assert at attention.py:467.

Note on the wrapper's extra ``quant_config.get_quant_method()`` call:
the wrapper resolves the quant method once BEFORE delegating (the
pristine body resolves it again), so the method constructor runs twice
for fp8_e5m2 layers. Side-effect-free for compressed-tensors (returns
a fresh method object); for arbitrary quant configs this is an
assumption — mitigated by the fp8_e5m2-only early-out and the
except-passthrough around the extra call.

Genesis extras over upstream:

  * BOTH import sites rebound: ``mla_attention.py:219`` imports the
    symbol BY VALUE at module level, so rebinding only
    ``attention._init_kv_cache_quant`` would leave MLA models on the
    stale gate. (Gemma-4 is not MLA; covered for correctness.)
  * Drift guard at install: the wrapper refuses to install when the
    pristine gate signature is no longer present in the original's
    source (e.g. #45040 merged at a future pin) — re-audit instead of
    silently stacking a stale wrapper (iron rule #11).
  * ``GENESIS_G4_80_FORCE_ALLOW_WITH_KV_SCHEME=1`` escape hatch: run
    fp8_e5m2 even when the checkpoint DOES declare a kv_cache_scheme.
    Rationale: the gemma-4-31b AWQ checkpoint is suspected (G4_31
    history) to carry a kv_cache_scheme hint despite being weight-only
    in practice; the first instrumented boot of the
    ``gemma4-31b-fp8e5m2-fallback`` profile discriminates. The forced
    path ignores checkpoint fp8-KV calibration scales — accuracy is
    UNVALIDATED; bench + tool-call gates required before any promotion.
  * Arm 2 — query-quant neutralizer (NOT in upstream #45040; see the
    SECOND GATE section): ``Attention.__init__`` wrap that nulls
    ``self.query_quant`` for fp8_e5m2 layers, killing the boot-DOA
    forward assert (pristine attention.py:467). Composes with G4_31's
    independent ``Attention.__init__`` wrap (each preserves and calls
    the binding it found).

Pairs with G4_31 arm 2 (vllm#45038 — sub-SM90 fp8 auto-override guard):
#45038 protects the kv-auto interim state, THIS patch provides the
escape to a working fp8_e5m2 KV (roadmap 2026-06-11 chunk-3 Theme B:
guard first, then fallback profile). Profile:
``sndr/model_configs/builtin/profile/gemma4-31b-fp8e5m2-fallback.yaml``
(attention backend TRITON_ATTN — the only viable choice; see the
BACKEND AUDIT section above).

Opt-in: ``GENESIS_ENABLE_G4_80_FP8E5M2_KV=1`` (default OFF). No-op for
any layer not requesting ``fp8_e5m2``.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
"""
from __future__ import annotations

import inspect
import logging
import os

log = logging.getLogger("genesis.turboquant.g4_80_fp8e5m2_kv_weight_only")

GENESIS_G4_80_MARKER = (
    "Genesis G4_80 allow fp8_e5m2 KV cache for weight-only quantized "
    "checkpoints (vllm#45040 adaptation; arm 1 _init_kv_cache_quant "
    "rebind + arm 2 fp8_e5m2 query-quant neutralizer)"
)

_ENV_ENABLE = "GENESIS_ENABLE_G4_80_FP8E5M2_KV"
_ENV_FORCE_ALLOW = "GENESIS_G4_80_FORCE_ALLOW_WITH_KV_SCHEME"
_WRAPPED_ATTR = "_genesis_g4_80_wrapped"
_QQ_WRAPPED_ATTR = "_genesis_g4_80_qq_wrapped"

# Pristine gate signature (pin 0.22.1rc1.dev259+g303916e93,
# attention.py:167-168) — install refuses when either string is gone.
_GATE_CONDITION_SRC = 'if layer.kv_cache_dtype == "fp8_e5m2"'
_GATE_MESSAGE_SRC = "fp8_e5m2 kv-cache is not supported with fp8 checkpoints."

_APPLIED = False
_BYPASS_HITS: list = []
_QQ_HITS: list = []


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _force_allow() -> bool:
    return _truthy(_ENV_FORCE_ALLOW)


def _resolve_kv_cache_method_cls():
    """The compressed-tensors KV-cache method class, or None when vllm
    (or the CT integration) is not importable."""
    try:
        from vllm.model_executor.layers.quantization.compressed_tensors.compressed_tensors import (  # noqa: E501
            CompressedTensorsKVCacheMethod,
        )
        return CompressedTensorsKVCacheMethod
    except Exception:  # noqa: BLE001
        return None


def _checkpoint_has_fp8_kv_scales(quant_method, kv_cache_method_cls=None) -> bool:
    """Whether the checkpoint behind this KV-cache method stores fp8 KV
    scales (upstream #45040 predicate, class injectable for tests).

    Conservative contract: when the compressed-tensors class cannot be
    resolved, return True — the gate must never be widened blindly.
    """
    cls = kv_cache_method_cls or _resolve_kv_cache_method_cls()
    if cls is None:
        return True
    if isinstance(quant_method, cls):
        return getattr(
            quant_method.quant_config, "kv_cache_scheme", None
        ) is not None
    return True


def _gate_signature_present(original) -> bool:
    """Drift guard: True when *original*'s source still carries the
    pristine reject-gate shape this wrapper compensates for."""
    try:
        src = inspect.getsource(original)
    except (OSError, TypeError):
        return False
    return _GATE_CONDITION_SRC in src and _GATE_MESSAGE_SRC in src


def _make_wrapped_init_kv_cache_quant(original, kv_cache_method_cls=None):
    """Build the ``_init_kv_cache_quant`` wrapper around *original*."""

    def _wrapped(layer, quant_config, prefix):
        if (
            getattr(layer, "kv_cache_dtype", None) != "fp8_e5m2"
            or quant_config is None
        ):
            return original(layer, quant_config, prefix)

        try:
            quant_method = quant_config.get_quant_method(layer, prefix=prefix)
        except Exception:  # noqa: BLE001 — never break init; fall through
            return original(layer, quant_config, prefix)

        has_scales = _checkpoint_has_fp8_kv_scales(
            quant_method, kv_cache_method_cls
        )
        forced = has_scales and _force_allow()
        if has_scales and not forced:
            # Genuine fp8(-KV) checkpoint — keep the upstream rejection.
            return original(layer, quant_config, prefix)

        if len(_BYPASS_HITS) < 3:
            _BYPASS_HITS.append(prefix)
            log.warning(
                "[G4_80] fp8_e5m2 KV cache allowed at %s: %s "
                "(vllm#45040; quant_method=%s). Masking kv_cache_dtype "
                "for the pristine reject gate only — restored after "
                "_init_kv_cache_quant.",
                prefix,
                "FORCED past declared kv_cache_scheme via "
                f"{_ENV_FORCE_ALLOW}=1 — checkpoint fp8-KV calibration "
                "scales are ignored, accuracy UNVALIDATED"
                if forced
                else "checkpoint is weight-only (no kv_cache_scheme -> "
                "no fp8 KV scales)",
                type(quant_method).__name__,
            )

        # Mask the dtype so the pristine gate passes; nothing else in
        # the pristine body reads layer.kv_cache_dtype (verified
        # attention.py:121-174 on pin 0.22.1rc1.dev259+g303916e93).
        layer.kv_cache_dtype = "fp8"
        try:
            return original(layer, quant_config, prefix)
        finally:
            layer.kv_cache_dtype = "fp8_e5m2"

    _wrapped._genesis_g4_80_wrapped = True
    _wrapped.__wrapped__ = original
    return _wrapped


def install_fp8e5m2_weight_only_gate(
    attention_mod, mla_mod=None, kv_cache_method_cls=None
) -> bool:
    """Rebind ``_init_kv_cache_quant`` on *attention_mod* (and
    *mla_mod*'s by-value import) with the weight-only-aware wrapper.

    Returns True when (re)bound by this call, False when already
    wrapped (idempotent) or when the drift guard refused.
    """
    original = getattr(attention_mod, "_init_kv_cache_quant", None)
    if original is None:
        log.warning(
            "[G4_80] _init_kv_cache_quant not found on %r — not installed.",
            attention_mod,
        )
        return False
    if getattr(original, _WRAPPED_ATTR, False):
        return False
    if not _gate_signature_present(original):
        log.warning(
            "[G4_80] pristine fp8_e5m2 reject-gate signature NOT found in "
            "_init_kv_cache_quant source — upstream moved or merged "
            "vllm#45040; refusing to install. Re-audit the patch against "
            "this pin (iron rule #11).",
        )
        return False

    wrapped = _make_wrapped_init_kv_cache_quant(original, kv_cache_method_cls)
    attention_mod._init_kv_cache_quant = wrapped
    if mla_mod is not None:
        mla_original = getattr(mla_mod, "_init_kv_cache_quant", None)
        if mla_original is original:
            mla_mod._init_kv_cache_quant = wrapped
        elif mla_original is not None and not getattr(
            mla_original, _WRAPPED_ATTR, False
        ):
            # Diverged by-value import — wrap it on its own original.
            mla_mod._init_kv_cache_quant = _make_wrapped_init_kv_cache_quant(
                mla_original, kv_cache_method_cls
            )
    return True


def revert_fp8e5m2_weight_only_gate(attention_mod, mla_mod=None) -> bool:
    """Undo :func:`install_fp8e5m2_weight_only_gate` (test / rollback)."""
    reverted = False
    for target in (attention_mod, mla_mod):
        if target is None:
            continue
        fn = getattr(target, "_init_kv_cache_quant", None)
        if fn is not None and getattr(fn, _WRAPPED_ATTR, False):
            target._init_kv_cache_quant = fn.__wrapped__
            reverted = True
    return reverted


def _make_wrapped_attention_init(original):
    """Build the ``Attention.__init__`` wrapper for arm 2 (query-quant
    neutralizer). Factored out for torch-less unit tests."""

    def _wrapped(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if (
            getattr(self, "kv_cache_dtype", None) == "fp8_e5m2"
            and getattr(self, "query_quant", None) is not None
        ):
            self.query_quant = None
            if len(_QQ_HITS) < 3:
                _QQ_HITS.append(getattr(self, "layer_name", "?"))
                log.warning(
                    "[G4_80] query_quant neutralized at %s (arm 2): "
                    "impl.supports_quant_query_input created an e4m3 "
                    "QuantFP8 query quantizer for kv_cache_dtype="
                    "fp8_e5m2, but Attention.forward asserts "
                    "kv_cache_dtype in {fp8, fp8_e4m3, nvfp4} (pristine "
                    "attention.py:467) — boot-DOA on the first "
                    "memory-profiling forward. Query stays in model "
                    "dtype; attention impls handle unquantized queries "
                    "natively (q_descale is dtype-gated).",
                    getattr(self, "layer_name", "?"),
                )
        return result

    _wrapped._genesis_g4_80_qq_wrapped = True
    _wrapped.__wrapped__ = original
    return _wrapped


def install_query_quant_guard(attention_cls) -> bool:
    """Arm 2: wrap ``attention_cls.__init__`` so fp8_e5m2 layers drop
    their ``query_quant`` (e4m3-only optimization whose forward path
    asserts against e5m2 — see module docstring, SECOND GATE section).

    Returns True when wrapped by this call, False when already wrapped
    (idempotent).
    """
    original = attention_cls.__init__
    if getattr(original, _QQ_WRAPPED_ATTR, False):
        return False
    attention_cls.__init__ = _make_wrapped_attention_init(original)
    return True


def revert_query_quant_guard(attention_cls) -> bool:
    """Undo :func:`install_query_quant_guard` (test / rollback)."""
    fn = attention_cls.__init__
    if getattr(fn, _QQ_WRAPPED_ATTR, False):
        attention_cls.__init__ = fn.__wrapped__
        return True
    return False


def apply() -> tuple[str, str]:
    """Apply G4_80. Never raises."""
    global _APPLIED

    decision: bool | None = None
    reason = ""
    try:
        from sndr.dispatcher import log_decision, should_apply

        decision, reason = should_apply("G4_80")
        if "unknown patch_id" in reason:
            # Registry entry not landed yet (dedicated registry pass owns
            # it) — fall back to the bare env gate below.
            decision = None
        else:
            log_decision("G4_80", decision, reason)
    except Exception:  # noqa: BLE001 — dispatcher import must never crash apply
        decision = None
    if decision is None:
        if not _truthy(_ENV_ENABLE):
            return "skipped", (
                f"G4_80 disabled (set {_ENV_ENABLE}=1 to allow fp8_e5m2 "
                "KV cache for weight-only quantized checkpoints, "
                "vllm#45040)"
            )
    elif not decision:
        return "skipped", reason

    if _APPLIED:
        return "applied", "G4_80 already installed (idempotent)"

    try:
        from vllm.model_executor.layers.attention import attention as attention_mod
    except ImportError as e:
        log.warning(
            "[G4_80] vllm attention module import failed (%s) — fp8_e5m2 "
            "weight-only unblock NOT installed; --kv-cache-dtype fp8_e5m2 "
            "will still be rejected for compressed-tensors checkpoints.", e,
        )
        return "failed", f"vllm attention module import failed: {e}"

    mla_mod = None
    try:
        from vllm.model_executor.layers.attention import (
            mla_attention as mla_mod,  # noqa: F811
        )
    except ImportError:
        pass  # MLA module optional — Attention path is the one we serve.

    if not install_fp8e5m2_weight_only_gate(attention_mod, mla_mod):
        if getattr(
            getattr(attention_mod, "_init_kv_cache_quant", None),
            _WRAPPED_ATTR, False,
        ):
            # Gate already wrapped — still make sure arm 2 is in place
            # (both arms are required for a successful fp8_e5m2 boot).
            attention_cls = getattr(attention_mod, "Attention", None)
            if attention_cls is not None:
                install_query_quant_guard(attention_cls)
            _APPLIED = True
            return "applied", "idempotent (G4_80 wrapper already installed)"
        return "failed", (
            "pristine fp8_e5m2 reject-gate signature not found — upstream "
            "drift (vllm#45040 merged?); G4_80 refused to install, re-audit"
        )

    # Arm 2: neutralize the e4m3-only query-quant optimization for
    # fp8_e5m2 layers — without it the FIRST forward (boot memory
    # profiling) dies on the pristine assert at attention.py:467
    # whenever the selected impl sets supports_quant_query_input
    # (TritonAttentionImpl: unconditionally True on CUDA).
    attention_cls = getattr(attention_mod, "Attention", None)
    if attention_cls is None:
        revert_fp8e5m2_weight_only_gate(attention_mod, mla_mod)
        return "failed", (
            "Attention class not found on the attention module — cannot "
            "install the query-quant arm; gate rebind rolled back "
            "(fp8_e5m2 without it is boot-DOA on the forward assert)"
        )
    install_query_quant_guard(attention_cls)

    _APPLIED = True
    log.info(
        "[G4_80] installed: arm 1 = _init_kv_cache_quant rebind "
        "(attention + mla_attention import sites; fp8_e5m2 KV allowed "
        "for weight-only compressed-tensors checkpoints, fp8(-KV) "
        "checkpoints stay rejected, vllm#45040); arm 2 = query_quant "
        "neutralizer for fp8_e5m2 layers (kills the forward assert at "
        "pristine attention.py:467 — no upstream fix exists)."
    )
    return "applied", (
        "fp8_e5m2 KV reject gate predicate-qualified per vllm#45040 "
        "(arm 1) and e4m3-only query-quant disabled for fp8_e5m2 "
        "layers (arm 2, forward-assert boot-DOA fix)"
    )


def is_applied() -> bool:
    return _APPLIED


__all__ = [
    "GENESIS_G4_80_MARKER",
    "apply",
    "is_applied",
    "install_fp8e5m2_weight_only_gate",
    "revert_fp8e5m2_weight_only_gate",
    "install_query_quant_guard",
    "revert_query_quant_guard",
]
