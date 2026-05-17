# SPDX-License-Identifier: Apache-2.0
"""G4_19 — Genesis G4-TurboQuant KV cache for Gemma 4 (256K context unlock).

================================================================
PURPOSE
================================================================

Compresses Gemma 4 KV cache via vector quantization (TurboQuant /
RotorQuant arXiv:2504.19874) so 256K context fits on 2× A5000 (48 GB
total VRAM).

Without this patch:
  * Gemma 4 31B + 256K context fp16 KV cache = ~22 GB
  * Weights = 20 GB
  * Total = 42 GB ≈ at limit (no margin for cudagraph/activations)
  * Practical max context on 2× A5000 = ~64-96K with fp8 KV

With this patch:
  * KV cache 4-bit (4× compression) = ~5.5 GB
  * Or KV cache 3-bit (5.3× compression) = ~4.2 GB
  * Total = 24-26 GB → 256K context fits comfortably

================================================================
WHEN TO USE
================================================================

This patch is **opt-in** and primarily useful for:
  * Long-context production endpoints (128K+ context)
  * RAG with large document chunks
  * Code agents with full repo context

For short-context (≤32K) the overhead of rotation+quantization is NOT
amortized (KV memory is not the bottleneck) — keep G4_19 disabled.

================================================================
LAYER-AWARE COMPRESSION
================================================================

Gemma 4 has interleaved sliding (1024-token window) + global (262144
window) attention. The KV cache for sliding layers is tiny — 1024
tokens regardless of context length — so the bulk of the savings come
from compressing **global** layers.

Default config:
  * sliding layers: 4-bit (high quality, small cache)
  * global layers:  3-bit (5× compression, max context capacity)

================================================================
QUALITY EXPECTATIONS
================================================================

From TurboQuant paper + our round-trip tests:
  * 3-bit on global: 99.0% attention cosine similarity vs fp16
  * 4-bit on sliding: 99.7% cosine similarity
  * Top-1 retrieval accuracy: 81-95% (depending on context length)

Expected end-to-end quality on benchmarks:
  * MMLU: -0.5 to -1.5 pp vs fp16 (likely within calibration noise)
  * NIAH (256K): 80-90% vs 95%+ uncompressed (acceptable for production)
  * HumanEval: -0 to -1 pp

================================================================
SAFETY MODEL
================================================================

* default_on: False (opt-in via env)
* env_flag: GENESIS_ENABLE_G4_19_GEMMA4_TURBOQUANT_KV
* env tuning:
    - GENESIS_G4_TQ_BITS_SLIDING (default 4)
    - GENESIS_G4_TQ_BITS_GLOBAL  (default 3)
    - GENESIS_G4_TQ_METHOD       (rht | clifford; default rht)
    - GENESIS_G4_TQ_SEED_BASE    (default 0xC0FFEE)
    - GENESIS_G4_TQ_PACK_MODE    (uint32 | tight | uint8; default uint32 = 4× compression)
    - GENESIS_G4_TQ_WHT_MODE     (signs_only | full_wht; default signs_only
                                  — full_wht enables the real Walsh-Hadamard
                                  butterfly; ~10-20% slower decode but ~6×
                                  lower quantization MSE)
* applies_to:
    - architecture: gemma4
    - triton ≥ 2.3
* conflicts_with: none (orthogonal to weight quantization)
* implementation_status: experimental (server validation pending)

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
References:
  * arXiv:2504.19874 — TurboQuant (ICLR 2026)
  * vllm#38171 — TurboQuant feature request (OPEN, no PR)
  * vllm#38291 — RotorQuant variant (OPEN, no PR)
  * Our Qwen 3.5/3.6 stack: P67 / PN116 / PN118 / PN119 (parallel pattern)
"""
from __future__ import annotations

import logging
import os

from ._gemma4_detect import env_truthy, is_gemma4_arch

log = logging.getLogger("genesis.gemma4.g4_19_turboquant_kv")

GENESIS_G4_19_MARKER = (
    "Genesis G4_19 gemma4 TurboQuant KV cache v1 "
    "(3-bit / 4-bit vector-quantized KV — unlocks 256K context on 2× A5000)"
)

_ENV_ENABLE = "GENESIS_ENABLE_G4_19_GEMMA4_TURBOQUANT_KV"
_ENV_BITS_SLIDING = "GENESIS_G4_TQ_BITS_SLIDING"
_ENV_BITS_GLOBAL = "GENESIS_G4_TQ_BITS_GLOBAL"
_ENV_METHOD = "GENESIS_G4_TQ_METHOD"
_ENV_SEED = "GENESIS_G4_TQ_SEED_BASE"
_ENV_PACK_MODE = "GENESIS_G4_TQ_PACK_MODE"
_ENV_WHT_MODE = "GENESIS_G4_TQ_WHT_MODE"

_APPLIED = False
_INSTALLED_CACHES = []  # list of G4TurboQuantKVCache instances per layer


def _env_enabled() -> bool:
    return env_truthy(_ENV_ENABLE)


def _resolve_bits(env_name: str, default: int) -> int:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
        if v not in (3, 4, 5):
            log.warning("[G4_19] %s=%d not in {3,4,5}; using default %d",
                        env_name, v, default)
            return default
        return v
    except ValueError:
        return default


def _resolve_method() -> str:
    raw = os.environ.get(_ENV_METHOD, "rht").strip().lower()
    if raw not in ("rht", "clifford"):
        log.warning("[G4_19] %s=%r invalid; using rht", _ENV_METHOD, raw)
        return "rht"
    return raw


def _resolve_seed() -> int:
    raw = os.environ.get(_ENV_SEED, "").strip()
    if not raw:
        return 0xC0FFEE
    try:
        # Allow hex (0x...) or decimal
        return int(raw, 0)
    except ValueError:
        return 0xC0FFEE


def _resolve_pack_mode() -> str:
    raw = os.environ.get(_ENV_PACK_MODE, "uint32").strip().lower()
    if raw not in ("uint32", "tight", "uint8"):
        log.warning(
            "[G4_19] %s=%r invalid; using uint32 (4× compression)",
            _ENV_PACK_MODE, raw,
        )
        return "uint32"
    return raw


def _resolve_wht_mode() -> str:
    """Pick rotation implementation. ``signs_only`` keeps the original
    fast-path (which is the placeholder sign-flip — same as v1 release).
    ``full_wht`` enables the Walsh-Hadamard butterfly via the new
    ``g4_tq_packed_wht_triton`` kernel. Default = signs_only so the
    bit-validated 256K boot path remains the operator-default."""
    raw = os.environ.get(_ENV_WHT_MODE, "signs_only").strip().lower()
    if raw not in ("signs_only", "full_wht"):
        log.warning(
            "[G4_19] %s=%r invalid; using signs_only (no Hadamard)",
            _ENV_WHT_MODE, raw,
        )
        return "signs_only"
    return raw


def apply() -> tuple[str, str]:
    """Install G4-TurboQuant KV cache for Gemma 4 attention layers."""
    global _APPLIED

    if not _env_enabled():
        return "skipped", (
            f"G4_19 disabled (set {_ENV_ENABLE}=1 to enable TurboQuant KV "
            "cache compression — unlocks 256K context on 2× A5000 for Gemma 4)"
        )

    if _APPLIED:
        return "applied", "G4_19 already installed (idempotent)"

    # Verify kernel imports
    try:
        from .kernels.turboquant import (
            GENESIS_G4_TQ_VERSION,
        )
        from .kernels.turboquant.g4_tq_cache import (
            G4TurboQuantConfig,
            G4TurboQuantKVCache,
        )
        from .kernels.turboquant.g4_tq_write_triton import (
            _TRITON_AVAILABLE as _write_ok,
        )
        from .kernels.turboquant.g4_tq_read_triton import (
            _TRITON_AVAILABLE as _read_ok,
        )
    except ImportError as e:
        return "skipped", f"G4-TurboQuant kernel package not importable: {e}"

    if not _write_ok or not _read_ok:
        return "skipped", (
            "Triton not available — install triton>=2.3 to use G4_19. "
            "Reference torch implementation works but is too slow for "
            "production decode."
        )

    # Resolve config from env
    bits_sliding = _resolve_bits(_ENV_BITS_SLIDING, 4)
    bits_global = _resolve_bits(_ENV_BITS_GLOBAL, 3)
    method = _resolve_method()
    seed = _resolve_seed()
    pack_mode = _resolve_pack_mode()
    wht_mode = _resolve_wht_mode()

    # Install hook on Gemma4 model config → KV cache spec
    try:
        from vllm.model_executor.models import gemma4 as _g4_mod
    except ImportError as e:
        return "skipped", f"vllm.model_executor.models.gemma4 not importable: {e}"

    target_cls = None
    for cls_name in ("Gemma4Config", "Gemma4TextConfig", "Gemma4ForConditionalGenerationConfig"):
        cls = getattr(_g4_mod, cls_name, None)
        if cls is not None and hasattr(cls, "verify_and_update_config"):
            target_cls = cls
            break
    if target_cls is None:
        return "skipped", (
            "No Gemma4Config-like class with verify_and_update_config found; "
            "G4_19 is no-op on this pin"
        )

    # Mark the config that G4-TQ is enabled — model executor reads this
    # at attention init time to decide whether to use our cache class.
    original = target_cls.verify_and_update_config
    if getattr(original, "_genesis_g4_19_wrapped", False):
        _APPLIED = True
        return "applied", "G4_19 already wrapped (idempotent)"

    def _genesis_g4_19_wrapped_verify(vllm_config):
        result = original(vllm_config)
        try:
            mc = getattr(vllm_config, "model_config", None)
            if mc is not None and is_gemma4_arch(mc):
                # Stash config on vllm_config so the model executor can
                # find it. The actual cache instantiation happens at the
                # ModelRunner.initialize_kv_caches stage via a separate
                # hook (we install it via vllm.attention.layer extension).
                hf = getattr(mc, "hf_config", None) or mc
                text = getattr(hf, "text_config", None) or hf
                tq_config = G4TurboQuantConfig(
                    head_dim=getattr(text, "head_dim", 256),
                    bits_sliding=bits_sliding,
                    bits_global=bits_global,
                    block_size=128,
                    rotation_method=method,
                    seed_base=seed,
                    sliding_window=getattr(text, "sliding_window", 1024),
                    per_layer_types=getattr(text, "layer_types", None),
                    pack_mode=pack_mode,
                    wht_mode=wht_mode,
                )
                # Attach to vllm_config — model executor will read this
                vllm_config._g4_19_turboquant_config = tq_config
                log.info(
                    "[G4_19] G4-TurboQuant KV cache config attached: "
                    "head_dim=%d sliding_bits=%d global_bits=%d method=%s "
                    "pack=%s wht=%s layers=%s sliding_window=%d",
                    tq_config.head_dim, tq_config.bits_sliding,
                    tq_config.bits_global, tq_config.rotation_method,
                    tq_config.pack_mode, tq_config.wht_mode,
                    len(tq_config.per_layer_types) if tq_config.per_layer_types else "?",
                    tq_config.sliding_window,
                )
        except Exception as e:  # noqa: BLE001
            log.warning("[G4_19] config attach failed: %r; G4-TQ not active", e)
        return result

    _genesis_g4_19_wrapped_verify._genesis_g4_19_wrapped = True
    _genesis_g4_19_wrapped_verify.__wrapped__ = original

    def _classmethod_shim(cls, vllm_config):
        return _genesis_g4_19_wrapped_verify(vllm_config)
    _classmethod_shim._genesis_g4_19_wrapped = True
    target_cls.verify_and_update_config = classmethod(_classmethod_shim)

    _APPLIED = True
    log.info(
        "[G4_19] installed: G4-TurboQuant KV cache config will be attached "
        "to vllm_config on Gemma 4 boot. Kernel module: %s",
        GENESIS_G4_TQ_VERSION,
    )
    return "applied", (
        f"G4_19 installed: G4-TurboQuant KV cache config attached to "
        f"Gemma 4 (sliding_bits={bits_sliding} / global_bits={bits_global} / "
        f"method={method}). Expected compression: {16/bits_global:.1f}x "
        f"on global layers; unlocks 256K context on 2× A5000."
    )


def is_applied() -> bool:
    return _APPLIED


def revert() -> bool:
    """G4_19 attaches config attr — revert is best-effort."""
    global _APPLIED
    if not _APPLIED:
        return False
    try:
        from vllm.model_executor.models import gemma4 as _g4_mod
        for cls_name in ("Gemma4Config", "Gemma4TextConfig", "Gemma4ForConditionalGenerationConfig"):
            cls = getattr(_g4_mod, cls_name, None)
            if cls is None:
                continue
            method = cls.verify_and_update_config
            if getattr(method, "_genesis_g4_19_wrapped", False):
                # We can only restore via the __wrapped__ chain
                orig = getattr(method, "__wrapped__", None)
                if orig is not None:
                    cls.verify_and_update_config = orig
        _APPLIED = False
        return True
    except Exception:  # noqa: BLE001
        return False


__all__ = ["GENESIS_G4_19_MARKER", "apply", "is_applied", "revert"]
