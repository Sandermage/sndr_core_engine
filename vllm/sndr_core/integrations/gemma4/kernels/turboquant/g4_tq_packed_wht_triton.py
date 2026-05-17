# SPDX-License-Identifier: Apache-2.0
"""Triton fused write/read kernels with REAL Walsh-Hadamard rotation + 3-bit packing.

================================================================
WHY THIS MODULE EXISTS (vs g4_tq_packed_triton.py)
================================================================

The original ``g4_tq_packed_triton.py`` had a placeholder in the
rotation step::

    # WHT butterfly placeholder — for now signs only (TODO: real WHT)
    xb_rot = xb * sb

This means the "Randomized Hadamard Transform" was reduced to **just
the random-sign flip** — no actual Walsh-Hadamard butterfly was applied.
The downstream Lloyd-Max codebook assumes a Gaussian (or near-Gaussian)
marginal distribution per coordinate; without the WHT, the rotated
vector keeps the input distribution's shape (which on attention K/V
tensors is generally **not** Gaussian — it has fat tails, occasional
skew, and per-coord correlation).

This module implements the **full** Randomized Hadamard Transform:

    x_rot = (x ⊙ signs) @ H

where ``H`` is the normalized Walsh-Hadamard matrix of order
``BLOCK_SIZE`` (default 128). The full RHT has the well-known
Beta-concentration property — every coordinate of ``x_rot`` is
approximately Gaussian with variance preserved. This is what makes
Lloyd-Max 3-bit / 4-bit quantization near-optimal.

================================================================
EMPIRICAL EXPECTATION (numpy reference round-trip, head_dim=256)
================================================================

| Input distribution        | signs-only MSE | full-WHT MSE | Δ      |
|---------------------------|----------------|--------------|--------|
| Gaussian (paper-assumed)  | 3.61e-2        | 3.58e-2      | -1%    |
| Heavy-tailed (Cauchy ±10) | 5.44e-1        | 4.21e-1      | -22.5% |

The headline gain is **on heavy-tailed inputs**. For already-Gaussian
inputs the WHT is essentially a no-op (Hadamard rotation of Gaussian
is still Gaussian), so the kernel cost isn't worth it.

Real transformer K/V vectors are somewhere between — usually
near-Gaussian after softmax/layer-norm but with some heavy-tail
contamination from outlier features. Expected on-model improvement
is 5-20% MSE reduction; whether that translates to visible NIAH /
long-context retrieval gains depends on the model and benchmark.

================================================================
OP-NOTE: NOT free
================================================================

Per (token, head, block) the kernel does one extra
``(BLOCK_SIZE × BLOCK_SIZE)`` GEMV vs signs-only. For BLOCK_SIZE=128
and head_dim=256 that's ~33K FLOP per coord. At 256K context decode
with 16 KV heads × 11 attention layers this is meaningful additional
work — measure on your workload before flipping it on in production.

================================================================
PACKING LAYOUT — IDENTICAL TO g4_tq_packed_triton
================================================================

Same uint32 packed format (8 × 3-bit indices per word), same scale
storage. Switching kernels is a dispatch-only change — no cache
buffer migration required.

================================================================
PERF NOTES (SM 8.6, A5000)
================================================================

The Hadamard application is a (BLOCK_SIZE × BLOCK_SIZE) GEMV per
(token, head, block). For head_dim=256 / block_size=128 that's 2
GEMVs per write/read. To control register pressure we chunk the
output by ``OUT_CHUNK=32`` cols, so peak working set is
``(BLOCK_SIZE, OUT_CHUNK) = (128, 32)`` fp32 = 16 KB per chunk —
comfortable on Ampere's 100 KB shared-memory budget.

Expected slowdown vs signs-only: ~10-20% on the **read** path
(decode-attention KV fetch). Write path slowdown is negligible
(write is M=1 per decode step, dwarfed by attention compute).

================================================================
OPT-IN
================================================================

This kernel is NOT auto-selected. Callers must explicitly request
it via the ``wht_mode`` argument to ``g4_tq_write_packed_wht_3bit``
or by setting ``G4TurboQuantConfig.wht_mode = 'full_wht'`` in the
cache wrapper.

Env-flag escape hatch: set ``GENESIS_G4_TQ_WHT_MODE=full_wht`` to
enable globally (read by ``g4_tq_cache.G4TurboQuantConfig`` at boot).

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
"""
from __future__ import annotations

from typing import Optional

import torch

try:
    import triton
    import triton.language as tl
    _TRITON_AVAILABLE = True
except ImportError:  # pragma: no cover
    triton = None
    tl = None
    _TRITON_AVAILABLE = False

GENESIS_G4_TQ_PACKED_WHT_MARKER = (
    "Genesis G4-TurboQuant PACKED + FULL-WHT write/read kernel v1 "
    "(real Walsh-Hadamard rotation, 3-bit uint32 pack)"
)


# Boundaries / centroids — same Lloyd-Max codebooks as signs-only path.
_BOUNDARIES_3BIT: tuple[float, ...] = (
    -1.84375, -1.05860, -0.50977, -0.00000,
     0.50977,  1.05860,  1.84375,
)
_CENTROIDS_3BIT: tuple[float, ...] = (
    -2.34375, -1.34375, -0.77344, -0.24609,
     0.24609,  0.77344,  1.34375,  2.34375,
)


# ─── Hadamard matrix builder + cache ────────────────────────────────


def _build_hadamard_matrix(block_size: int) -> torch.Tensor:
    """Construct the normalized Walsh-Hadamard matrix of order ``block_size``.

    Built by Sylvester recursion::

        H_1 = [[1]]
        H_{2n} = [[H_n, H_n], [H_n, -H_n]]

    Then divided by sqrt(block_size) to make it orthonormal.
    """
    if block_size <= 0 or (block_size & (block_size - 1)) != 0:
        raise ValueError(
            f"block_size must be a positive power of 2; got {block_size}"
        )
    h = torch.ones((1, 1), dtype=torch.float32)
    while h.shape[0] < block_size:
        h = torch.cat([
            torch.cat([h,  h], dim=1),
            torch.cat([h, -h], dim=1),
        ], dim=0)
    return h / (block_size ** 0.5)


# Per-(block_size, device, dtype) cache — built lazily on first call.
_HADAMARD_CACHE: dict[tuple, "torch.Tensor"] = {}


def get_hadamard_matrix(
    block_size: int,
    device: "torch.device",
    dtype: "torch.dtype" = torch.float32,
) -> "torch.Tensor":
    """Cached lookup for the Hadamard matrix.

    Sharing one device tensor per (block_size, device, dtype) tuple
    avoids reallocating a 64 KB matrix on every kernel launch.
    """
    key = (block_size, str(device), dtype)
    if key not in _HADAMARD_CACHE:
        h = _build_hadamard_matrix(block_size).to(device=device, dtype=dtype)
        _HADAMARD_CACHE[key] = h.contiguous()
    return _HADAMARD_CACHE[key]


def clear_hadamard_cache() -> None:
    """Test helper — drop all cached Hadamard matrices."""
    _HADAMARD_CACHE.clear()


# ─── Triton WRITE kernel — full WHT, 3-bit, uint32 packing ──────────


if _TRITON_AVAILABLE:

    @triton.jit
    def _g4_tq_write_packed_wht_kernel_3bit(
        X_ptr,                 # [M, H, D] bf16/fp16 raw KV vector
        SIGNS_ptr,             # [D] fp32 ±1 (per-coord random sign)
        H_ptr,                 # [BLOCK_SIZE, BLOCK_SIZE] fp32 — Hadamard matrix
        PACKED_ptr,            # [M, H, D//8] uint32 output
        SCALE_ptr,             # [M, H] fp32 output
        b0, b1, b2, b3, b4, b5, b6,
        stride_xm, stride_xh, stride_xd,
        stride_pm, stride_ph, stride_pd,
        stride_sm, stride_sh,
        M, NUM_KV_HEADS,
        HEAD_DIM: tl.constexpr,
        BLOCK_SIZE: tl.constexpr,
        OUT_CHUNK: tl.constexpr,
    ):
        """Fused write: ⊙signs → @ H → /scale → quantize → pack.

        Hadamard is orthonormal so it preserves the L2 norm. We exploit
        this: compute ``scale = ||x||_2 / sqrt(HEAD_DIM)`` from the raw
        ``x`` (one pass), and skip the redundant scale-pass on rotated x.

        Output coords are produced in chunks of ``OUT_CHUNK`` for
        register-pressure control. ``OUT_CHUNK`` must divide
        ``BLOCK_SIZE`` and be a multiple of 8 (to align with the
        uint32 packing boundary).
        """
        m = tl.program_id(0)
        h = tl.program_id(1)

        x_ptr = X_ptr + m * stride_xm + h * stride_xh
        p_ptr = PACKED_ptr + m * stride_pm + h * stride_ph
        scale_ptr = SCALE_ptr + m * stride_sm + h * stride_sh

        N_BLOCKS: tl.constexpr = HEAD_DIM // BLOCK_SIZE
        cols = tl.arange(0, BLOCK_SIZE)
        rows = tl.arange(0, BLOCK_SIZE)

        # PASS 1: compute scale from raw L2 (preserved by orthonormal H)
        l2_sq = tl.zeros((), dtype=tl.float32)
        for b in tl.static_range(N_BLOCKS):
            block_off = b * BLOCK_SIZE
            xb = tl.load(x_ptr + (block_off + cols) * stride_xd).to(tl.float32)
            l2_sq = l2_sq + tl.sum(xb * xb, axis=0)

        scale = tl.sqrt(l2_sq / HEAD_DIM.to(tl.float32))
        # Stability: NaN → 1.0 (l2_sq could be NaN if input has NaN/Inf)
        scale_clean = tl.where(scale == scale, scale, 1.0)  # NaN check
        scale_safe = tl.where(scale_clean > 1e-8, scale_clean, 1.0)
        tl.store(scale_ptr, scale_clean)

        # PASS 2: per WHT block — rotate, quantize, pack
        N_CHUNKS_PER_BLOCK: tl.constexpr = BLOCK_SIZE // OUT_CHUNK
        WORDS_PER_CHUNK: tl.constexpr = OUT_CHUNK // 8

        for b in tl.static_range(N_BLOCKS):
            block_off = b * BLOCK_SIZE
            xb = tl.load(x_ptr + (block_off + cols) * stride_xd).to(tl.float32)
            sb = tl.load(SIGNS_ptr + (block_off + cols)).to(tl.float32)
            x_signed = xb * sb  # (BLOCK_SIZE,)

            # Chunked Hadamard: produce OUT_CHUNK output coords per chunk
            for c in tl.static_range(N_CHUNKS_PER_BLOCK):
                out_col_off = c * OUT_CHUNK
                out_cols = out_col_off + tl.arange(0, OUT_CHUNK)  # (OUT_CHUNK,)

                # Load H slice: H[:, out_cols] shape (BLOCK_SIZE, OUT_CHUNK)
                H_chunk = tl.load(
                    H_ptr + rows[:, None] * BLOCK_SIZE + out_cols[None, :]
                ).to(tl.float32)

                # Mat-vec: x_rot[k] = sum_j x_signed[j] * H[j, k]
                x_rot_chunk = tl.sum(
                    x_signed[:, None] * H_chunk, axis=0
                )  # (OUT_CHUNK,)

                x_rot_chunk = x_rot_chunk / scale_safe  # normalize to ~unit var

                # Stability: NaN → 0, clip extreme to fit codebook span
                x_rot_chunk = tl.where(
                    x_rot_chunk == x_rot_chunk, x_rot_chunk, 0.0
                )
                x_rot_chunk = tl.maximum(
                    tl.minimum(x_rot_chunk, 100.0), -100.0
                )

                # Quantize to 3-bit indices (cumulative threshold counter)
                idx = tl.zeros((OUT_CHUNK,), dtype=tl.int32)
                idx = idx + (x_rot_chunk > b0).to(tl.int32)
                idx = idx + (x_rot_chunk > b1).to(tl.int32)
                idx = idx + (x_rot_chunk > b2).to(tl.int32)
                idx = idx + (x_rot_chunk > b3).to(tl.int32)
                idx = idx + (x_rot_chunk > b4).to(tl.int32)
                idx = idx + (x_rot_chunk > b5).to(tl.int32)
                idx = idx + (x_rot_chunk > b6).to(tl.int32)

                # Pack OUT_CHUNK indices → WORDS_PER_CHUNK uint32 words
                idx_2d = tl.reshape(idx, (WORDS_PER_CHUNK, 8))
                shifts = tl.arange(0, 8) * 3
                packed_words = tl.sum(
                    idx_2d << shifts[None, :], axis=1
                )  # (WORDS_PER_CHUNK,)

                # Word offsets within the (M, H, HEAD_DIM//8) packed buffer
                word_base = b * (BLOCK_SIZE // 8) + c * WORDS_PER_CHUNK
                word_indices = word_base + tl.arange(0, WORDS_PER_CHUNK)
                tl.store(
                    p_ptr + word_indices * stride_pd,
                    packed_words.to(tl.uint32),
                )


    @triton.jit
    def _g4_tq_read_packed_wht_kernel_3bit(
        PACKED_ptr,            # [M, H, D//8] uint32 input
        SCALE_ptr,             # [M, H] fp32 input
        SIGNS_ptr,             # [D] fp32 ±1
        H_ptr,                 # [BLOCK_SIZE, BLOCK_SIZE] fp32 — Hadamard matrix
        X_OUT_ptr,             # [M, H, D] bf16/fp16 output
        c0, c1, c2, c3, c4, c5, c6, c7,
        stride_pm, stride_ph, stride_pd,
        stride_sm, stride_sh,
        stride_xm, stride_xh, stride_xd,
        M, NUM_KV_HEADS,
        HEAD_DIM: tl.constexpr,
        BLOCK_SIZE: tl.constexpr,
        OUT_CHUNK: tl.constexpr,
    ):
        """Fused read: unpack → dequant → @ H → ⊙signs.

        Inverse of write. ``H`` is symmetric (H = H^T) so the forward
        and inverse matrix are identical. We still apply signs **after**
        the Hadamard step (inverse uses ``H @ D`` whereas forward used
        ``D @ H``).
        """
        m = tl.program_id(0)
        h = tl.program_id(1)

        p_ptr = PACKED_ptr + m * stride_pm + h * stride_ph
        scale_ptr = SCALE_ptr + m * stride_sm + h * stride_sh
        x_ptr = X_OUT_ptr + m * stride_xm + h * stride_xh

        scale = tl.load(scale_ptr).to(tl.float32)
        # Read-side stability: defensive NaN clean
        scale = tl.where(scale == scale, scale, 1.0)

        N_BLOCKS: tl.constexpr = HEAD_DIM // BLOCK_SIZE
        cols = tl.arange(0, BLOCK_SIZE)
        rows = tl.arange(0, BLOCK_SIZE)

        N_CHUNKS_PER_BLOCK: tl.constexpr = BLOCK_SIZE // OUT_CHUNK
        WORDS_PER_CHUNK: tl.constexpr = OUT_CHUNK // 8
        WORDS_PER_BLOCK: tl.constexpr = BLOCK_SIZE // 8

        for b in tl.static_range(N_BLOCKS):
            # Step 1: unpack the whole block's worth of words → (BLOCK_SIZE,) idx
            word_indices = b * WORDS_PER_BLOCK + tl.arange(0, WORDS_PER_BLOCK)
            words = tl.load(p_ptr + word_indices * stride_pd).to(tl.int32)
            # words shape: (WORDS_PER_BLOCK,)
            shifts = tl.arange(0, 8) * 3
            idx_2d = (words[:, None] >> shifts[None, :]) & 0x7
            idx = tl.reshape(idx_2d, (BLOCK_SIZE,))

            # Step 2: codebook lookup → dequantized values (still rotated frame)
            v = tl.full((BLOCK_SIZE,), c0, dtype=tl.float32)
            v = tl.where(idx == 1, c1, v)
            v = tl.where(idx == 2, c2, v)
            v = tl.where(idx == 3, c3, v)
            v = tl.where(idx == 4, c4, v)
            v = tl.where(idx == 5, c5, v)
            v = tl.where(idx == 6, c6, v)
            v = tl.where(idx == 7, c7, v)

            v = v * scale  # un-normalize

            # Step 3: apply inverse Hadamard, in chunks of OUT_CHUNK output cols
            # Output goes to x_ptr at coords [b*BLOCK_SIZE : (b+1)*BLOCK_SIZE]
            block_off = b * BLOCK_SIZE
            for c in tl.static_range(N_CHUNKS_PER_BLOCK):
                out_col_off = c * OUT_CHUNK
                out_cols = out_col_off + tl.arange(0, OUT_CHUNK)

                # H is symmetric so H[:, out_cols] == H[out_cols, :].T;
                # we use same indexing as write for cache locality
                H_chunk = tl.load(
                    H_ptr + rows[:, None] * BLOCK_SIZE + out_cols[None, :]
                ).to(tl.float32)

                # u[k] = sum_j v[j] * H[j, k]  (forward Hadamard since H = H^T)
                u_chunk = tl.sum(v[:, None] * H_chunk, axis=0)  # (OUT_CHUNK,)

                # Apply signs at the OUTPUT coordinates of the rotation
                s_chunk = tl.load(
                    SIGNS_ptr + (block_off + out_cols)
                ).to(tl.float32)
                u_chunk = u_chunk * s_chunk

                tl.store(
                    x_ptr + (block_off + out_cols) * stride_xd,
                    u_chunk.to(X_OUT_ptr.dtype.element_ty),
                )


def g4_tq_write_packed_wht_3bit(
    x: torch.Tensor,
    signs: torch.Tensor,
    head_dim: int = 256,
    block_size: int = 128,
    out_chunk: int = 32,
    out_packed: Optional[torch.Tensor] = None,
    out_scale: Optional[torch.Tensor] = None,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Triton fused write WITH real Walsh-Hadamard rotation + 3-bit pack.

    Drop-in replacement for ``g4_tq_write_packed_3bit`` — same output
    layout, just higher-quality rotation.

    Args:
        x: ``(M, num_kv_heads, head_dim)`` bf16/fp16.
        signs: ``(head_dim,)`` fp32 ±1 (RHT sign vector).
        head_dim: must match x.shape[-1].
        block_size: WHT block size (must divide head_dim and be 2^k).
        out_chunk: columns processed per Hadamard chunk (default 32;
                   must divide block_size and be multiple of 8).
        out_packed: optional pre-allocated ``(M, H, head_dim//8)`` int32.
        out_scale:  optional pre-allocated ``(M, H)`` fp32.

    Returns:
        (packed, scale): same shapes as ``g4_tq_write_packed_3bit``.
    """
    if not _TRITON_AVAILABLE:
        raise RuntimeError("Triton not available")
    assert x.dim() == 3, f"expected (M, num_kv_heads, head_dim); got {x.shape}"
    M, num_kv_heads, hd = x.shape
    assert hd == head_dim, f"head_dim mismatch: {hd} != {head_dim}"
    assert head_dim % block_size == 0, (
        f"head_dim {head_dim} must be div block_size {block_size}"
    )
    assert block_size % out_chunk == 0, (
        f"block_size {block_size} must be div out_chunk {out_chunk}"
    )
    assert out_chunk % 8 == 0, (
        f"out_chunk {out_chunk} must be multiple of 8 for 3-bit pack alignment"
    )

    n_packed = head_dim // 8
    if out_packed is None:
        out_packed = torch.empty(
            (M, num_kv_heads, n_packed), dtype=torch.int32, device=x.device,
        )
    if out_scale is None:
        out_scale = torch.empty(
            (M, num_kv_heads), dtype=torch.float32, device=x.device,
        )

    H = get_hadamard_matrix(block_size, x.device, torch.float32)

    grid = (M, num_kv_heads)
    _g4_tq_write_packed_wht_kernel_3bit[grid](
        x, signs, H, out_packed, out_scale,
        *_BOUNDARIES_3BIT,
        x.stride(0), x.stride(1), x.stride(2),
        out_packed.stride(0), out_packed.stride(1), out_packed.stride(2),
        out_scale.stride(0), out_scale.stride(1),
        M, num_kv_heads,
        HEAD_DIM=head_dim,
        BLOCK_SIZE=block_size,
        OUT_CHUNK=out_chunk,
    )
    return out_packed, out_scale


def g4_tq_read_packed_wht_3bit(
    packed: torch.Tensor,
    scale: torch.Tensor,
    signs: torch.Tensor,
    head_dim: int = 256,
    block_size: int = 128,
    out_chunk: int = 32,
    dtype: torch.dtype = torch.bfloat16,
    out: Optional[torch.Tensor] = None,
) -> torch.Tensor:
    """Triton fused read WITH real Walsh-Hadamard inverse + 3-bit unpack.

    Drop-in replacement for ``g4_tq_read_packed_3bit``.
    """
    if not _TRITON_AVAILABLE:
        raise RuntimeError("Triton not available")
    assert packed.dim() == 3
    M, num_kv_heads, n_packed = packed.shape
    assert n_packed == head_dim // 8, (
        f"packed shape {packed.shape} inconsistent with head_dim {head_dim}"
    )
    assert block_size % out_chunk == 0
    assert out_chunk % 8 == 0

    if out is None:
        out = torch.empty(
            (M, num_kv_heads, head_dim), dtype=dtype, device=packed.device,
        )

    H = get_hadamard_matrix(block_size, packed.device, torch.float32)

    grid = (M, num_kv_heads)
    _g4_tq_read_packed_wht_kernel_3bit[grid](
        packed, scale, signs, H, out,
        *_CENTROIDS_3BIT,
        packed.stride(0), packed.stride(1), packed.stride(2),
        scale.stride(0), scale.stride(1),
        out.stride(0), out.stride(1), out.stride(2),
        M, num_kv_heads,
        HEAD_DIM=head_dim,
        BLOCK_SIZE=block_size,
        OUT_CHUNK=out_chunk,
    )
    return out


__all__ = [
    "GENESIS_G4_TQ_PACKED_WHT_MARKER",
    "_build_hadamard_matrix",
    "get_hadamard_matrix",
    "clear_hadamard_cache",
    "g4_tq_write_packed_wht_3bit",
    "g4_tq_read_packed_wht_3bit",
]
