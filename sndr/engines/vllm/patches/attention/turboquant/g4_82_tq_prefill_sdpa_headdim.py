# SPDX-License-Identifier: Apache-2.0
"""G4_82 — TQ prefill SDPA fallback for head_dim > 256 (Ampere FA2 cap).

================================================================
PROBLEM
================================================================

Native vllm ``TurboQuantAttentionImpl`` (``v1/attention/backends/
turboquant_attn.py``) routes EVERY non-decode-kernel attention compute —
first-chunk prefill, per-request continuation, and the cached-context
continuation — through one private method, ``_flash_attn_varlen``, which
calls FlashAttention-2's ``flash_attn_varlen_func`` UNCONDITIONALLY
(turboquant_attn.py:311/322, the only two FA2 call sites in the file;
the three callers are at :580 first-chunk prefill, :644 per-request
first-chunk, :826 cached continuation).

FA2 caps ``head_dim`` at 256 on Ampere/Ada — there is no SM 8.x kernel
for 512 (vllm#38887). On a model with interleaved attention this is
fatal for the wide tier:

  Gemma-4-31B: sliding layers ``head_dim=256`` (FA2 OK) BUT global
  layers ``head_dim=512`` (FA2 -> RuntimeError "FlashAttention forward
  only supports head dimension at most 256").

Observed live (2026-06-16, dev491, 31B-tq-mtp boot): the engine boots,
but the FIRST user request crashes the worker on the global-layer
prefill. With async-scheduling on, the worker exception is masked as a
scheduler ``KeyError: req_id_to_index`` (core.py:578 batch-queue
desync); ``--no-async-scheduling`` unmasks the true error.

The pr42637 overlay turboquant_attn.py had this fallback
(``_can_use_flash_prefill`` + ``_sdpa_causal_prefill``), but that
overlay snapshot is now stale on dev491 (its sibling overlays
``kv_cache_utils.py`` / ``single_type_kv_cache_manager.py`` lack
dev491-added symbols ``get_kv_cache_capacity`` /
``register_all_kvcache_specs`` — boot ImportError). Re-mounting the
overlay set is not viable; this patch ports ONLY the head_dim>256
fallback onto the otherwise-native dev491 backend.

================================================================
FIX
================================================================

Monkey-patch ``TurboQuantAttentionImpl._flash_attn_varlen`` (runtime
hook, no TextPatcher — the method body drifts across pins but its
signature is stable). The wrapper dispatches on ``self.head_size``:

  * ``head_size <= 256`` -> original FA2 fast path, byte-for-byte
    unchanged (the sliding tier and every <=256 model are untouched).
  * ``head_size > 256``  -> per-sequence torch SDPA over the varlen
    batch. SDPA's math/efficient backend supports any head_dim; for
    head_dim=512 PyTorch auto-selects a non-flash kernel.

PROVABLE EQUIVALENCE TO FA2 (iron rule #11):

The wrapper receives the IDENTICAL ``(q, k, v, cu_seqlens_q,
cu_seqlens_k)`` that FA2 would receive, and reproduces FA2's exact
``causal=True`` masking, so the result is numerically equivalent (up to
backend rounding) for all three call sites:

  * q_len == k_len (sites :580 first-chunk, :644 per-request): FA2
    causal with equal seqlens is a plain lower-triangular mask
    -> SDPA ``is_causal=True``.
  * q_len <  k_len (site :826 cached continuation): FA2 causal with
    seqlen_q < seqlen_k aligns BOTTOM-RIGHT (the last query attends to
    the last key) -> offset mask ``k_pos <= q_pos`` where
    ``q_pos = arange(q_len) + (k_len - q_len)``. We do not need to know
    what ``k`` physically contains — matching FA2's mask on the same
    inputs yields the same output.

GQA is forwarded natively: ``enable_gqa=(num_kv_heads < num_q_heads)``,
exactly as FA2 accepts grouped k/v.

================================================================
SCOPE / COST
================================================================

Per-sequence SDPA over the varlen batch needs the per-request
boundaries on CPU, so the wrapper does one ``cu_seqlens.tolist()``
GPU->CPU sync per call when it fires. This is acceptable: the head_dim>
256 path is FIRST-CHUNK PREFILL (prompt processing), which runs eager
(not cudagraph-captured) and off the sustained-decode hot path. The
<=256 fast path adds ZERO sync (it never reaches the loop). On the 31B,
~1 sync per global-512 layer per prefill step — invisible against the
GDN/Mamba prefill compute that dominates 31B TTFT.

The decode hot path is unaffected: decode goes through the TQ triton
decode kernel (``triton_turboquant_decode_attention``), never FA2, and
the triton kernel already handles head_dim=512.

================================================================
RELATIONSHIPS
================================================================

  * **G4_81** (TQ multi-query DIRECT decode routing) — wraps
    ``.forward`` and routes uniform K+1 spec-verify DECODE batches
    through the decode kernel; it EXPLICITLY leaves first-chunk prefill
    (``max_seq_len <= max_query_len``) to the flash path (g4_81 line
    296-297). G4_82 is the complementary piece: it makes that flash
    path not crash on head_dim=512. Both wrap different methods of the
    same class — independent, compose cleanly (apply order irrelevant).
  * **G4_69 / G4_31 / G4_79 / G4_60a** — 31B boot-gate companions
    (skip-layers native backend, dtype preserve, mm-prefix unblock,
    sliding spec). G4_82 is the runtime-compute companion they enable.
  * **P67/P67b** — Qwen-family multi-query technique; orthogonal
    (Qwen head_dim=128, never hits the FA2 cap).

================================================================
PATCH CHECKLIST (verify on every pin bump)
================================================================

  1. ``TurboQuantAttentionImpl._flash_attn_varlen`` keyword signature
     unchanged: (q, k, v, cu_seqlens_q, cu_seqlens_k, max_seqlen_q,
     max_seqlen_k). The wrapper forwards all kwargs to the original.
  2. ``flash_attn_varlen_func`` remains called ONLY inside
     ``_flash_attn_varlen`` (grep the pin's backend file — if a new
     FA2 call site appears outside the method, it is NOT covered).
  3. ``self.head_size`` is the real model head_dim (set in __init__,
     turboquant_attn.py:266) — the per-layer dispatch key.
  4. PyTorch SDPA still falls back to a non-flash backend for
     head_dim>256 (true since the memory-efficient/math backends have
     no 256 cap; the math backend is the universal guarantee).

Opt-in: ``GENESIS_ENABLE_G4_82_TQ_PREFILL_SDPA_HEADDIM=1`` (default
OFF). Required by the Gemma-4-31B TQ profile; a no-op (FA2 fast path
only) for every model whose attention head_dim is <= 256.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("genesis.turboquant.g4_82_tq_prefill_sdpa_headdim")

GENESIS_G4_82_MARKER = (
    "Genesis G4_82 TurboQuantAttentionImpl._flash_attn_varlen head_dim>256 "
    "per-sequence SDPA fallback (Ampere FA2 256-cap, vllm#38887)"
)

_ENV_ENABLE = "GENESIS_ENABLE_G4_82_TQ_PREFILL_SDPA_HEADDIM"
_WRAP_ATTR = "_genesis_g4_82_wrapped"

# FA2 head_dim ceiling on SM 8.x (Ampere/Ada). 256 is OK; 512 crashes.
_FA2_HEAD_DIM_CAP = 256

_APPLIED = False
_ORIGINAL_FLASH_VARLEN = None


def _env_enabled() -> bool:
    return os.environ.get(_ENV_ENABLE, "").strip().lower() in (
        "1", "true", "yes", "on",
    )


# ─── SDPA varlen fallback ─────────────────────────────────────────────


def _sdpa_varlen(self, q, k, v, cu_seqlens_q, cu_seqlens_k):
    """Per-sequence causal SDPA over a varlen batch, reproducing FA2's
    ``flash_attn_varlen_func(..., causal=True)`` semantics for any
    head_dim.

    q : (total_q, num_q_heads,  head_dim)
    k : (total_k, num_kv_heads, head_dim)
    v : (total_k, num_kv_heads, head_dim)
    Returns (total_q, num_q_heads, head_dim) — same layout/dtype FA2
    returns, so the caller's downstream is identical.
    """
    import torch
    import torch.nn.functional as F

    # One GPU->CPU sync per call (head_dim>256 prefill only — off the
    # decode hot path). Boundaries describe per-request q / k spans.
    cu_q = cu_seqlens_q.tolist()
    cu_k = cu_seqlens_k.tolist()
    enable_gqa = k.shape[1] < q.shape[1]

    outs = []
    for i in range(len(cu_q) - 1):
        qs, qe = cu_q[i], cu_q[i + 1]
        ks, ke = cu_k[i], cu_k[i + 1]
        q_len = qe - qs
        k_len = ke - ks
        if q_len <= 0:
            continue
        # (len, heads, dim) -> (1, heads, len, dim)
        qi = q[qs:qe].transpose(0, 1).unsqueeze(0)
        ki = k[ks:ke].transpose(0, 1).unsqueeze(0)
        vi = v[ks:ke].transpose(0, 1).unsqueeze(0)
        if q_len == k_len:
            out = F.scaled_dot_product_attention(
                qi, ki, vi,
                is_causal=True,
                scale=self.scale,
                enable_gqa=enable_gqa,
            )
        else:
            # FA2 bottom-right causal alignment for seqlen_q < seqlen_k.
            device = q.device
            q_pos = torch.arange(q_len, device=device).unsqueeze(1) + (
                k_len - q_len
            )
            k_pos = torch.arange(k_len, device=device).unsqueeze(0)
            mask = k_pos <= q_pos  # bool: True = attend
            out = F.scaled_dot_product_attention(
                qi, ki, vi,
                attn_mask=mask,
                scale=self.scale,
                enable_gqa=enable_gqa,
            )
        # (1, heads, len, dim) -> (len, heads, dim)
        outs.append(out[0].transpose(0, 1))

    if not outs:
        # Degenerate batch (no positive-length request) — return an
        # empty tensor matching FA2's output shape contract.
        return q[:0]
    return torch.cat(outs, dim=0)


# ─── apply / revert ───────────────────────────────────────────────────


def apply() -> tuple[str, str]:
    """Wrap TurboQuantAttentionImpl._flash_attn_varlen with the
    head_dim>256 SDPA fallback."""
    global _APPLIED, _ORIGINAL_FLASH_VARLEN

    if not _env_enabled():
        return "skipped", (
            f"G4_82 disabled (set {_ENV_ENABLE}=1 to enable TQ prefill SDPA "
            "fallback for head_dim>256 — required by the Gemma-4-31B TQ "
            "profile, no-op for head_dim<=256 models)"
        )

    if _APPLIED:
        return "applied", "G4_82 already installed (idempotent)"

    try:
        from vllm.v1.attention.backends.turboquant_attn import (
            TurboQuantAttentionImpl,
        )
    except ImportError as e:
        return "skipped", (
            f"vllm.v1.attention.backends.turboquant_attn not importable: {e}"
        )

    original = TurboQuantAttentionImpl._flash_attn_varlen
    if getattr(original, _WRAP_ATTR, False):
        _APPLIED = True
        return "applied", "G4_82 already wrapped (idempotent)"
    _ORIGINAL_FLASH_VARLEN = original

    def _wrapped_flash_attn_varlen(
        self,
        q,
        k,
        v,
        cu_seqlens_q,
        cu_seqlens_k,
        max_seqlen_q,
        max_seqlen_k,
    ):
        """Dispatch on head_size: FA2 fast path for <=256, per-sequence
        SDPA for >256 (which FA2 cannot serve on Ampere)."""
        if getattr(self, "head_size", 0) > _FA2_HEAD_DIM_CAP:
            return _sdpa_varlen(self, q, k, v, cu_seqlens_q, cu_seqlens_k)
        return original(
            self, q, k, v, cu_seqlens_q, cu_seqlens_k,
            max_seqlen_q, max_seqlen_k,
        )

    setattr(_wrapped_flash_attn_varlen, _WRAP_ATTR, True)
    TurboQuantAttentionImpl._flash_attn_varlen = (  # type: ignore[method-assign]
        _wrapped_flash_attn_varlen
    )

    _APPLIED = True
    log.info(
        "[G4_82] TurboQuantAttentionImpl._flash_attn_varlen wrapped — "
        "head_dim>%d attention compute now routes to per-sequence SDPA "
        "(FA2 fast path preserved for head_dim<=%d).",
        _FA2_HEAD_DIM_CAP, _FA2_HEAD_DIM_CAP,
    )
    return "applied", (
        "G4_82 installed: TQ prefill/continuation on head_dim>256 layers "
        "(Gemma-4-31B global tier) falls back to SDPA instead of crashing "
        "FA2; head_dim<=256 layers keep the FA2 fast path."
    )


def is_applied() -> bool:
    return _APPLIED


def revert() -> bool:
    """Best-effort revert (test isolation only)."""
    global _APPLIED, _ORIGINAL_FLASH_VARLEN
    if not _APPLIED or _ORIGINAL_FLASH_VARLEN is None:
        return False
    try:
        from vllm.v1.attention.backends.turboquant_attn import (
            TurboQuantAttentionImpl,
        )

        TurboQuantAttentionImpl._flash_attn_varlen = (  # type: ignore[method-assign]
            _ORIGINAL_FLASH_VARLEN
        )
    except Exception:  # noqa: BLE001
        return False
    _APPLIED = False
    _ORIGINAL_FLASH_VARLEN = None
    return True


__all__ = [
    "GENESIS_G4_82_MARKER",
    "apply",
    "is_applied",
    "revert",
]
