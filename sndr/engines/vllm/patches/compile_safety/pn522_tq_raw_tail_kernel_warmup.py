# SPDX-License-Identifier: Apache-2.0
"""PN522 — pre-capture warmup of the PN521 raw-bf16-tail spec-verify kernel.

PN521 routes the INT4 non-pow2-GQA 27B's MTP K+1 spec-verify through the custom
P67 split-M kernel with ``use_raw_tail=1`` (a distinct Triton specialization:
``USE_RAW_TAIL=1``, ``KP1_PAD=next_pow2(K_PLUS_1)``, ``K_PLUS_1``, ``BLOCK_QH``,
``BLOCK_D``, ...). NO existing warmup (PN126 dummy_run, PN128 spec-decode helper,
G4_62 TQ-decode, PN130) compiles THAT variant, so it JIT-compiles on the FIRST
real MTP verify request — confirmed live via the vLLM jit_monitor warning
"Triton kernel JIT compilation during inference:
``_build_kernel.<locals>.cutlass_genesis_p67_v17_split_m``" and a first-request
latency spike (~4-8 TPS vs ~77 steady).

PN522 wraps ``vllm.model_executor.warmup.kernel_warmup`` (same hook G4_62 uses)
and, for each unique TurboQuant attention-layer geometry, calls
``call_p67_attention(use_raw_tail=1)`` once with synthetic ``prior_seq_len=0``
inputs. prior=0 leaves the compressed-cache loop empty (the kv_cache is never
read -> no OOB risk) while the raw-tail phase over the K+1 chunk is exercised;
the compiled Triton variant is identical to the prior>0 runtime case (the loop
bound is a runtime value, not a constexpr), so the first real request hits the
JIT cache instead of paying the compile.

Gated on the SAME predicate PN521 uses (GENESIS_ENABLE_PN521_TQ_RAW_TAIL_VERIFY
AND non-pow-2 GQA), so pow-2-GQA models (FP8 35B) never run it — bit-exact no-op.
Bit-exact by construction: it only pre-compiles the already-validated kernel with
dummy zeros; the throwaway output is discarded and no live cache is touched.

Author: Sandermage (Sander) Barzov Aleksandr.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("genesis.wiring.pn522_tq_raw_tail_kernel_warmup")

_ENV_ENABLE = "GENESIS_ENABLE_PN522_TQ_RAW_TAIL_WARMUP"
_PN521_ENV = "GENESIS_ENABLE_PN521_TQ_RAW_TAIL_VERIFY"
_APPLIED = False
_ORIGINAL_KERNEL_WARMUP = None


def _truthy(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "yes", "on")


def _env_enabled() -> bool:
    return _truthy(os.environ.get(_ENV_ENABLE, ""))


def _pn521_enabled() -> bool:
    return _truthy(os.environ.get(_PN521_ENV, ""))


def _is_non_pow2(n: int) -> bool:
    return n >= 2 and (n & (n - 1)) != 0


def _resolve_k1(worker) -> int:
    """K_PLUS_1 = num_speculative_tokens + 1 (the MTP verify chunk width).

    The speculative_config lives on different objects across vLLM builds — try
    the worker, its model_runner, and the process-global vllm_config."""
    candidates = []
    for obj, attr in (
        (worker, "vllm_config"),
        (getattr(worker, "model_runner", None), "vllm_config"),
    ):
        if obj is not None:
            candidates.append(getattr(obj, attr, None))
    try:
        from vllm.config import get_current_vllm_config
        candidates.append(get_current_vllm_config())
    except Exception:  # noqa: BLE001
        pass
    for vc in candidates:
        spec = getattr(vc, "speculative_config", None) if vc is not None else None
        n = getattr(spec, "num_speculative_tokens", None) if spec is not None else None
        if n:
            return int(n) + 1
    return 0


def _iter_turboquant_attention_layers(model):
    from vllm.model_executor.layers.attention import Attention
    from vllm.v1.attention.backends.turboquant_attn import (
        TurboQuantAttentionImpl,
    )

    for layer in model.modules():
        if not isinstance(layer, Attention):
            continue
        if not getattr(layer, "kv_cache_dtype", "").startswith("turboquant_"):
            continue
        if not isinstance(layer.impl, TurboQuantAttentionImpl):
            continue
        yield layer, layer.impl


def _warmup_raw_tail_layer(impl, *, device, k1: int, batch: int, block_size: int,
                           model_dtype) -> bool:
    """Compile the raw-tail kernel variant for this layer's geometry.

    prior_seq_len=0 (seq_lens=k1) => the compressed loop is empty and the
    kv_cache is never dereferenced; only the raw-tail phase runs. Returns True
    on a successful compile-launch."""
    import torch

    from sndr.engines.vllm.kernels_legacy.p67_multi_query_kernel import (
        call_p67_attention,
    )

    hq = impl.num_heads
    hk = impl.num_kv_heads
    d = impl.head_size
    if hk <= 0 or hq % hk != 0 or not _is_non_pow2(hq // hk):
        return False

    kps = impl.tq_config.key_packed_size
    val_data_bytes = getattr(impl.tq_config, "value_data_bytes", d // 2)
    slot_bytes = kps + val_data_bytes + 4

    q = torch.zeros((batch, k1, hq, d), dtype=model_dtype, device=device)
    k_chunk = torch.zeros((batch, k1, hk, d), dtype=model_dtype, device=device)
    v_chunk = torch.zeros((batch, k1, hk, d), dtype=model_dtype, device=device)
    # prior_seq_len = seq_lens - k1 = 0 -> compressed loop empty -> kv_cache
    # never read; a minimal valid-shaped cache is enough.
    seq_lens = torch.full((batch,), k1, dtype=torch.int32, device=device)
    kv_cache = torch.zeros((2, block_size, slot_bytes), dtype=torch.uint8,
                           device=device)
    block_table = torch.zeros((batch, 1), dtype=torch.int32, device=device)

    call_p67_attention(
        q, kv_cache, block_table, seq_lens, k_chunk, v_chunk,
        scale=impl.scale, block_size=block_size, kps=kps,
        val_data_bytes=val_data_bytes, use_raw_tail=1,
    )
    return True


def raw_tail_kernel_warmup(worker) -> None:
    import torch

    k1 = _resolve_k1(worker)
    model = worker.get_model()
    device = worker.model_runner.device
    model_dtype = worker.model_runner.dtype
    try:
        block_size = worker.cache_config.block_size
    except Exception:  # noqa: BLE001
        block_size = 16
    batch = max(1, int(getattr(worker.scheduler_config, "max_num_seqs", 1)))
    n_layers = sum(1 for _ in _iter_turboquant_attention_layers(model))
    log.info("[PN522] warmup entered: k1=%d batch=%d block_size=%d TQ_layers=%d",
             k1, batch, block_size, n_layers)
    if k1 < 2:
        log.warning("[PN522] no MTP verify chunk (k1=%d); skipping raw-tail warmup "
                    "(the first request will pay the JIT compile).", k1)
        return

    seen: set[tuple] = set()
    n = 0
    with torch.inference_mode():
        for _layer, impl in _iter_turboquant_attention_layers(model):
            key = (impl.num_heads, impl.num_kv_heads, impl.head_size, k1, batch,
                   block_size)
            if key in seen:
                continue
            seen.add(key)
            try:
                if _warmup_raw_tail_layer(
                    impl, device=device, k1=k1, batch=batch,
                    block_size=block_size, model_dtype=model_dtype,
                ):
                    n += 1
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "[PN522] raw-tail warmup for a TQ layer failed: %r "
                    "(continuing; first request may pay the JIT compile)", e,
                )
    if n:
        try:
            torch.cuda.synchronize()
        except Exception:  # noqa: BLE001
            pass
        log.info("[PN522] pre-compiled %d raw-tail kernel variant(s) at K1=%d "
                 "(non-pow2-GQA); first MTP verify request avoids the JIT spike.",
                 n, k1)


def apply() -> tuple[str, str]:
    """Wrap kernel_warmup to pre-compile the PN521 raw-tail kernel."""
    global _APPLIED, _ORIGINAL_KERNEL_WARMUP

    if not _env_enabled():
        return "skipped", (
            f"PN522 disabled (set {_ENV_ENABLE}=1 to pre-compile the PN521 "
            "raw-tail spec-verify kernel before serving)"
        )
    if not _pn521_enabled():
        return "skipped", (
            "PN522 no-op: PN521 raw-tail verify is not enabled "
            f"({_PN521_ENV}!=1) — nothing to warm."
        )
    if _APPLIED:
        return "applied", "PN522 already installed (idempotent)"

    # Wrap Worker.compile_or_warm_up_model at the CLASS level (the reliable hook
    # PN126/PN128 use). The module-level vllm.model_executor.warmup.kernel_warmup
    # is imported-by-reference before Genesis patches apply, so reassigning it is
    # bypassed — the class-method wrap is not.
    try:
        from vllm.v1.worker.gpu_worker import Worker
    except ImportError as e:
        return "skipped", f"V1 Worker not importable: {e}"
    if not hasattr(Worker, "compile_or_warm_up_model"):
        return "skipped", "Worker.compile_or_warm_up_model not found"

    original = Worker.compile_or_warm_up_model
    if getattr(original, "_genesis_pn522_wrapped", False):
        _APPLIED = True
        return "applied", "Worker.compile_or_warm_up_model already wrapped (idempotent)"
    _ORIGINAL_KERNEL_WARMUP = original

    def _wrapped_compile(self):
        result = original(self)
        try:
            raw_tail_kernel_warmup(self)  # `self` is the Worker
        except Exception as e:  # noqa: BLE001
            log.warning("[PN522] raw_tail_kernel_warmup failed: %r (continuing; "
                        "first request may pay JIT compile cost)", e)
        return result

    _wrapped_compile._genesis_pn522_wrapped = True  # type: ignore[attr-defined]
    Worker.compile_or_warm_up_model = _wrapped_compile
    _APPLIED = True
    return "applied", (
        "PN522 installed: Worker.compile_or_warm_up_model now pre-compiles the "
        "PN521 raw-tail spec-verify kernel (non-pow2-GQA) before serving — "
        "removes the first-request JIT latency spike."
    )
