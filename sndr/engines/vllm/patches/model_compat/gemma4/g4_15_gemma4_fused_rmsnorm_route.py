# SPDX-License-Identifier: Apache-2.0
"""G4_15 — fused RMSNorm Triton kernels (PARTIAL — no-op wrapper in hot path).

STATUS (audit 2026-05-17): implementation_status=partial.
The Triton kernels in ``kernels/g4_fused_rmsnorm_triton.py`` are correct
and reviewed against SGLang reference. The integration wrapper in this
file, however, **falls through to the original Gemma4Attention.forward**
because we cannot generic-monkey-patch the QKV-split + per-head norm
sequence reliably across vLLM pins. The wrapper exists to make the
kernel available to operator code that calls it directly.

**Deep integration is deferred to G4_15b** — an anchor-precise text
patch into ``vllm.model_executor.models.gemma4.Gemma4Attention.forward``
pinned to a specific vLLM SHA (currently dev371+bf610c2f5). Until that
patch lands, this file does NOT deliver the +5-10% TPS gain promised
by the kernel docstrings.

================================================================
PURPOSE (target end-state — G4_15b)
================================================================

Gemma 4's per-layer forward has at minimum **6** RMSNorm-flavor calls
(input_norm, post_attn_norm, pre_ffw_norm, post_ffw_norm, q_norm, k_norm)
plus the optional v_norm and the MoE expert-output dual-norm. On a 60-layer
model that's **360+ kernel launches per token**, each one is small and
launch-overhead-bound.

Three highest-frequency RMSNorm flavors that G4_15b will fuse via
``kernels/g4_fused_rmsnorm_triton.py``:

  1. **post-attention residual join** — was 3 kernels (rmsnorm + add +
     [optional Gemma-scalar mul]), now 1
  2. **per-head Q/K/V RMSNorm** — was 3 kernels (one per Q,K,V), now 1
     with all heads inline
  3. **MoE dual-norm reduction** (26B-A4B only) — was 5 kernels
     (3 rmsnorm + 2 add + mul), now 1

Expected gain AFTER G4_15b lands: **5-10% TPS** on Gemma 4 31B decode at
low concurrency (launch-bound regime); diminishing on prefill/large batch.

Validated in SGLang's reference at ``gemma4_fused_ops.py`` — we ported
the kernels (G4_FUSED_RMSNORM_KERNEL marker) and added SM 8.6 shared-mem
guard.

================================================================
INTEGRATION STRATEGY
================================================================

Monkey-patch ``vllm.model_executor.models.gemma4.Gemma4Attention.forward``
(and ``Gemma4MoEBlock.forward`` where applicable) at apply time:

  * Hook intercepts the per-head qkv split + 3 separate norms
  * Calls our fused ``g4_qkv_rmsnorm`` in-place instead
  * Falls through to original on shape mismatch / non-CUDA / triton-absent

We also hook ``Gemma4DecoderLayer.forward`` to fuse the post-attention
residual + scalar via ``g4_rmsnorm_residual_scalar``.

Idempotent and gated by env flag. Falls back gracefully when shape doesn't
match expected pattern.

================================================================
SAFETY MODEL
================================================================

* default_on: False (perf opt-in; default OFF until A/B validated on prod)
* env_flag: GENESIS_ENABLE_G4_15_GEMMA4_FUSED_RMSNORM
* applies_to:
    - architecture: gemma4
    - triton ≥ 2.3
    - CUDA available
* conflicts_with: none (transparent fallback when patch path doesn't match)

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
References:
  * sndr_private/research/gemma4/kernels/sglang/gemma4_fused_ops.py
  * transformers/src/transformers/models/gemma4/modeling_gemma4.py
"""
from __future__ import annotations

import logging

from ._gemma4_detect import env_truthy

log = logging.getLogger("genesis.gemma4.g4_15_fused_rmsnorm")

GENESIS_G4_15_MARKER = (
    "Genesis G4_15 gemma4 fused RMSNorm route v1 "
    "(kernel ported; hot-path wiring deferred to G4_15b — currently no-op)"
)

_ENV_ENABLE = "GENESIS_ENABLE_G4_15_GEMMA4_FUSED_RMSNORM"

_APPLIED = False
_ORIGINAL_ATTN_FORWARD = None
_ORIGINAL_DECODER_FORWARD = None


def _env_enabled() -> bool:
    return env_truthy(_ENV_ENABLE)


def _make_attn_forward_wrapper(original):
    """Wrap Gemma4Attention.forward to call fused QKV RMSNorm.

    The Gemma 4 attention forward pattern (transformers ref):

        qkv = self.qkv_proj(hidden_states)
        q, k, v = qkv.split([q_size, k_size, v_size], dim=-1)
        q = self.q_norm(q.view(..., num_heads, head_dim))
        k = self.k_norm(k.view(..., num_kv_heads, head_dim))
        v = self.v_norm(v.view(..., num_kv_heads, head_dim))
        ...

    We fuse those 3 norm calls into 1 via g4_qkv_rmsnorm.
    """
    def _g4_15_wrapped_forward(self, *args, **kwargs):
        # We cannot safely intercept the inner split-and-norm logic from
        # outside without rewriting the whole forward, so this wrapper does
        # NOT call the fused kernel — it always delegates to the original.
        # The hot-path replacement is the deep-cut anchor patch G4_15b
        # (still a roadmap item). This wrapper exists only to carry the
        # idempotency marker; it is a deliberate, honest pass-through.
        return original(self, *args, **kwargs)

    _g4_15_wrapped_forward._genesis_g4_15_wrapped = True
    _g4_15_wrapped_forward.__wrapped__ = original
    return _g4_15_wrapped_forward


def _install_gemma4_attention_subclass(attn_cls):
    """Try to wire the fused-QKV-RMSNorm forward onto Gemma4Attention.

    Returns True ONLY when the fused kernel is actually engaged in the
    hot path. On every current vLLM pin this returns False: replacing the
    forward requires anchor-precise positions for the post-rotary
    query/key/value states that we cannot reach by wrapping the public
    ``forward`` from outside. The deep-cut anchor patch (G4_15b) is still
    a roadmap item, so we do NOT install a forward that merely delegates
    to the original — that would deliver nothing while masquerading as an
    active fusion. We refuse here so apply() can report the honest
    no-op status.
    """
    # The fused kernel (g4_qkv_rmsnorm) ships in
    # kernels/g4_fused_rmsnorm_triton.py and is reviewed against the SGLang
    # reference, but it is not wired into the attention forward yet. Until
    # the deep-cut anchor patch G4_15b lands, the fusion does not engage on
    # any pin, so we refuse to install and let apply() report a clean no-op.
    return False


def apply() -> tuple[str, str]:
    """Install fused-RMSNorm route on Gemma4Attention + Gemma4DecoderLayer."""
    global _APPLIED, _ORIGINAL_ATTN_FORWARD

    if not _env_enabled():
        return "skipped", (
            f"G4_15 disabled (set {_ENV_ENABLE}=1 once the deep-cut anchor "
            "patch G4_15b wires the fused Gemma 4 RMSNorm kernel into the "
            "attention hot path)"
        )

    if _APPLIED:
        return "applied", "G4_15 already installed (idempotent)"

    try:
        from vllm.model_executor.models import gemma4 as _g4_mod
    except ImportError as e:
        return "skipped", f"vllm.model_executor.models.gemma4 not importable: {e}"

    # Verify Triton is healthy before attempting the install.
    try:
        from .kernels.g4_fused_rmsnorm_triton import _TRITON_AVAILABLE
    except ImportError as e:
        return "skipped", f"g4_fused_rmsnorm_triton not importable: {e}"
    if not _TRITON_AVAILABLE:
        return "skipped", "triton not available — install triton>=2.3"

    attn_cls = (
        getattr(_g4_mod, "Gemma4Attention", None)
        or getattr(_g4_mod, "Gemma4TextAttention", None)
    )
    if attn_cls is None:
        return "skipped", "Gemma4Attention class not found in this vLLM pin"

    original_forward = attn_cls.forward
    if getattr(original_forward, "_genesis_g4_15_wrapped", False):
        _APPLIED = True
        return "applied", "G4_15 already wrapped (idempotent)"
    _ORIGINAL_ATTN_FORWARD = original_forward

    # The fused kernel is not wired into the hot path on any current pin
    # (the helper refuses to install a forward that only delegates to the
    # original). Report the honest no-op status — never a false "applied",
    # and never a TPS claim the patch does not deliver.
    if not _install_gemma4_attention_subclass(attn_cls):
        return "skipped", (
            "fused QKV-RMSNorm kernel not wired on this pin — falls through "
            "to upstream; no-op, no TPS delta. RIG FOLLOW-UP: land the "
            "deep-cut anchor patch G4_15b (anchor-precise text patch into "
            "Gemma4Attention.forward post-rotary q/k/v states) and re-validate "
            "with genesis_bench_suite.py before claiming a TPS win."
        )

    # Reachable only once G4_15b actually engages the kernel; the install
    # helper returns True and this honest "applied" reports the live fusion.
    _APPLIED = True
    log.info(
        "[G4_15] installed: Gemma 4 attention forward routes Q/K/V RMSNorm "
        "through the fused Triton kernel."
    )
    return "applied", (
        "G4_15 installed: Gemma 4 RMSNorm calls routed through fused Triton "
        "kernel. Validate the TPS effect via genesis_bench_suite.py before "
        "promotion."
    )


def is_applied() -> bool:
    return _APPLIED


def revert() -> bool:
    global _APPLIED, _ORIGINAL_ATTN_FORWARD
    if not _APPLIED or _ORIGINAL_ATTN_FORWARD is None:
        return False
    try:
        from vllm.model_executor.models import gemma4 as _g4_mod
        attn_cls = (
            getattr(_g4_mod, "Gemma4Attention", None)
            or getattr(_g4_mod, "Gemma4TextAttention", None)
        )
        if attn_cls is None:
            return False
        attn_cls.forward = _ORIGINAL_ATTN_FORWARD  # type: ignore[assignment]
    except ImportError:
        return False
    _APPLIED = False
    _ORIGINAL_ATTN_FORWARD = None
    return True


__all__ = ["GENESIS_G4_15_MARKER", "apply", "is_applied", "revert"]
