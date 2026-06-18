# SPDX-License-Identifier: Apache-2.0
"""PN119 FIX-2 parity gate — MSE key dequant: scalar vs grouped-tile.

PN119 extends the GQA-grouped tensor-core decode kernel
(``_tq_grouped_decode_stage1`` in ``triton_turboquant_decode.py``) to
handle MSE-quantized keys (the Gemma ``turboquant_4bit_nc`` preset,
``key_fp8=False``) so Gemma's decode uses ``tl.dot`` tensor cores
instead of the scalar fallback.

A wrong MSE tile produces garbage output (the "SBBBB" failure mode).
Before any GPU run we PROVE — purely in numpy, no GPU/Triton needed —
that the tiled K-dequant the grouped kernel performs is *byte-for-byte
identical* in index selection and *algebraically equal* in score
contribution to the scalar reference kernel's per-token MSE branch.

Reference (scalar) math, mirrored from the pristine kernel
``_tq_decode_stage1`` MSE branch::

    mse_bit_off  = d_offs * MSE_BITS
    mse_byte_idx = mse_bit_off // 8
    mse_bit_shift = mse_bit_off % 8
    mse_mask = (1 << MSE_BITS) - 1
    raw16   = byte[idx] | (byte[idx+1] << 8)
    mse_idx = (raw16 >> mse_bit_shift) & mse_mask
    c_vals  = centroids[mse_idx]                    # [n_tok, D]
    # NORM_CORRECTION:
    c_norm_sq = sum(c_vals*c_vals, axis=1)
    c_vals   *= 1/sqrt(c_norm_sq + 1e-16)           # rsqrt, per token
    term1     = sum(q_rot * c_vals, axis=1)
    scores    = vec_norms * term1 * ATTN_SCALE

Grouped (tiled) math the kernel will perform::

    # identical mse_idx unpack, but as a [BLOCK_KV, BLOCK_D] tile
    c_vals  = centroids[mse_idx]                    # [BLOCK_KV, D]
    c_vals *= 1/sqrt(sum(c_vals*c_vals,axis=1)+1e-16)[:,None]   # if NORM
    k_float = vec_norms[:, None] * c_vals           # [BLOCK_KV, D]
    scores  = (q_rot @ k_float.T) * ATTN_SCALE      # tl.dot

Because ``vec_norms * sum(q*c) == sum(q * (vec_norms*c))``, folding
``vec_norms`` into ``k_float`` before the dot is exactly equal to the
scalar path's ``vec_norms * term1`` up to floating-point rounding.

This test verifies BOTH:
  1. Index parity (exact, integer): the tiled bit-unpack selects the
     same ``mse_idx`` / gathers the same centroids as the scalar path.
  2. Score parity (fp tolerance): the grouped score row equals the
     scalar score row within fp16 tolerance.
"""
from __future__ import annotations

import numpy as np
import pytest

# Tolerances: the grouped path casts q_rot and k_float to fp16 before
# the tl.dot, while the scalar path accumulates the dot in fp32. We
# emulate the fp16 cast in the grouped reference so the only residual
# delta is genuine fp16 rounding of the matmul, bounded by atol/rtol.
ATOL = 1e-2
RTOL = 1e-2


# ---------------------------------------------------------------------------
# Synthetic case + packing helpers (encode side — kept self-contained)
# ---------------------------------------------------------------------------


def _pack_mse_indices(idx: np.ndarray, mse_bits: int, mse_bytes: int) -> np.ndarray:
    """Bit-pack per-dim MSE indices [n_tok, D] into [n_tok, mse_bytes] uint8.

    Exactly the inverse of the kernel unpack: dim ``d`` occupies bits
    ``[d*mse_bits, d*mse_bits + mse_bits)`` little-endian across bytes.
    """
    n_tok, D = idx.shape
    packed = np.zeros((n_tok, mse_bytes), dtype=np.uint8)
    for t in range(n_tok):
        bitbuf = 0
        for d in range(D):
            bitbuf |= (int(idx[t, d]) & ((1 << mse_bits) - 1)) << (d * mse_bits)
        for b in range(mse_bytes):
            packed[t, b] = (bitbuf >> (b * 8)) & 0xFF
    return packed


def _fp16(x: np.ndarray) -> np.ndarray:
    return x.astype(np.float16).astype(np.float32)


# ---------------------------------------------------------------------------
# Scalar reference: per-token unpack (mirrors _tq_decode_stage1 MSE branch)
# ---------------------------------------------------------------------------


def _scalar_unpack_idx(
    packed: np.ndarray, D: int, mse_bits: int
) -> np.ndarray:
    """Reproduce the scalar kernel's per-token mse_idx unpack.

    Scalar kernel (lines 243-247, 335-347)::
        mse_bit_off  = d_offs * MSE_BITS
        mse_byte_idx = mse_bit_off // 8
        mse_bit_shift = mse_bit_off % 8
        mse_mask = (1 << MSE_BITS) - 1
        raw0  = byte[byte_idx]; raw1 = byte[byte_idx + 1]
        raw16 = raw0 | (raw1 << 8)
        idx   = (raw16 >> bit_shift) & mask
    Note the kernel always reads byte_idx and byte_idx+1; a token only
    has mse_bytes bytes, so byte_idx+1 may read one byte past the data.
    We replicate that by treating out-of-range as 0 (matches Triton
    masked load `other=0` against d_mask / kv_mask).
    """
    n_tok = packed.shape[0]
    mse_bytes = packed.shape[1]
    d_offs = np.arange(D)
    mse_bit_off = d_offs * mse_bits
    byte_idx = mse_bit_off // 8
    bit_shift = mse_bit_off % 8
    mask = (1 << mse_bits) - 1
    out = np.zeros((n_tok, D), dtype=np.int64)
    for t in range(n_tok):
        for d in range(D):
            bi = int(byte_idx[d])
            raw0 = int(packed[t, bi]) if bi < mse_bytes else 0
            raw1 = int(packed[t, bi + 1]) if (bi + 1) < mse_bytes else 0
            raw16 = raw0 | (raw1 << 8)
            out[t, d] = (raw16 >> int(bit_shift[d])) & mask
    return out


def _scalar_scores(
    q_rot: np.ndarray,
    packed: np.ndarray,
    vec_norms: np.ndarray,
    centroids: np.ndarray,
    D: int,
    mse_bits: int,
    attn_scale: float,
    norm_correction: bool,
):
    """Scalar reference: returns (mse_idx, c_vals_after_norm, scores[H, n_tok])."""
    idx = _scalar_unpack_idx(packed, D, mse_bits)
    c_vals = centroids[idx].astype(np.float32)  # [n_tok, D]
    if norm_correction:
        c_norm_sq = np.sum(c_vals * c_vals, axis=1)
        c_inv = 1.0 / np.sqrt(c_norm_sq + 1e-16)
        c_vals = c_vals * c_inv[:, None]
    # term1[H, n_tok] = sum over D of q_rot[H,D] * c_vals[tok,D]
    term1 = q_rot @ c_vals.T  # [H, n_tok], fp32 accumulation
    scores = vec_norms[None, :] * term1 * attn_scale
    return idx, c_vals, scores


# ---------------------------------------------------------------------------
# Grouped reference: tiled unpack (what the kernel MSE branch will do)
# ---------------------------------------------------------------------------


def _tiled_unpack_idx(packed: np.ndarray, D: int, mse_bits: int) -> np.ndarray:
    """Reproduce the GROUPED kernel's tiled [BLOCK_KV, BLOCK_D] unpack.

    Vectorized over the token axis (the tile dim). Index arithmetic is
    identical to the scalar path; the ONLY difference is that the whole
    [n_tok, D] tile is computed at once (as the kernel does with
    slot_bases[:, None] + mse_byte_idx[None, :]), not token-by-token.
    """
    n_tok, mse_bytes = packed.shape
    d_offs = np.arange(D)
    mse_bit_off = d_offs * mse_bits
    byte_idx = mse_bit_off // 8  # [D]
    bit_shift = mse_bit_off % 8  # [D]
    mask = (1 << mse_bits) - 1
    # Gather raw0 = packed[:, byte_idx], raw1 = packed[:, byte_idx+1]
    # with out-of-range -> 0 (Triton masked load other=0).
    raw0 = np.zeros((n_tok, D), dtype=np.int64)
    raw1 = np.zeros((n_tok, D), dtype=np.int64)
    in0 = byte_idx < mse_bytes
    in1 = (byte_idx + 1) < mse_bytes
    raw0[:, in0] = packed[:, byte_idx[in0]].astype(np.int64)
    raw1[:, in1] = packed[:, (byte_idx + 1)[in1]].astype(np.int64)
    raw16 = raw0 | (raw1 << 8)
    idx = (raw16 >> bit_shift[None, :]) & mask
    return idx


def _grouped_scores(
    q_rot: np.ndarray,
    packed: np.ndarray,
    vec_norms: np.ndarray,
    centroids: np.ndarray,
    D: int,
    mse_bits: int,
    attn_scale: float,
    norm_correction: bool,
):
    """Grouped reference: build k_float tile then dot. Emulates the fp16
    cast of q_rot/k_float that the kernel's tl.dot performs.

    Returns (mse_idx, k_float, scores[H, n_tok]).
    """
    idx = _tiled_unpack_idx(packed, D, mse_bits)
    c_vals = centroids[idx].astype(np.float32)  # [n_tok, D]
    if norm_correction:
        c_norm_sq = np.sum(c_vals * c_vals, axis=1)
        c_inv = 1.0 / np.sqrt(c_norm_sq + 1e-16)
        c_vals = c_vals * c_inv[:, None]
    # k_float = vec_norms[:, None] * c_vals  -> [n_tok, D]
    k_float = vec_norms[:, None] * c_vals
    # scores = tl.dot(q_rot.fp16, k_float.T.fp16) in fp16 inputs.
    scores = (_fp16(q_rot) @ _fp16(k_float).T) * attn_scale  # [H, n_tok]
    return idx, k_float, scores


# ---------------------------------------------------------------------------
# Fixtures / case builder
# ---------------------------------------------------------------------------


def _build_case(seed=0, D=64, n_tok=20, n_centroids=16, H=4, attn_scale=None):
    rng = np.random.default_rng(seed)
    mse_bits = int(np.log2(n_centroids))
    assert (1 << mse_bits) == n_centroids
    mse_bytes = (D * mse_bits + 7) // 8
    if attn_scale is None:
        attn_scale = 1.0 / np.sqrt(D)
    # Random codebook (the per-dim scalar centroid values).
    centroids = rng.standard_normal(n_centroids).astype(np.float32)
    # Random per-(token, dim) centroid indices.
    idx = rng.integers(0, n_centroids, size=(n_tok, D), dtype=np.int64)
    packed = _pack_mse_indices(idx, mse_bits, mse_bytes)
    # Per-token key norms (the scalar path stores these as fp16; emulate).
    vec_norms = _fp16(np.abs(rng.standard_normal(n_tok).astype(np.float32)) + 0.1)
    # Rotated queries for H q-heads in one GQA group.
    q_rot = rng.standard_normal((H, D)).astype(np.float32)
    return dict(
        D=D, n_tok=n_tok, n_centroids=n_centroids, H=H, mse_bits=mse_bits,
        mse_bytes=mse_bytes, attn_scale=attn_scale, centroids=centroids,
        idx_true=idx, packed=packed, vec_norms=vec_norms, q_rot=q_rot,
    )


# ---------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("norm_correction", [False, True])
@pytest.mark.parametrize(
    "D,n_centroids", [(64, 16), (64, 8), (128, 16), (256, 16)]
)
def test_index_unpack_exact_parity(D, n_centroids, norm_correction):
    """The tiled unpack must select EXACTLY the same centroid indices as
    the scalar per-token unpack — and both must match ground truth."""
    c = _build_case(D=D, n_centroids=n_centroids)
    scalar_idx = _scalar_unpack_idx(c["packed"], D, c["mse_bits"])
    tiled_idx = _tiled_unpack_idx(c["packed"], D, c["mse_bits"])
    # Tiled == scalar (byte-for-byte integer parity)
    assert np.array_equal(tiled_idx, scalar_idx), "tiled vs scalar idx mismatch"
    # Both == ground-truth packed indices (round-trip correctness)
    assert np.array_equal(tiled_idx, c["idx_true"]), "unpack != original idx"


@pytest.mark.parametrize("norm_correction", [False, True])
@pytest.mark.parametrize(
    "D,n_centroids", [(64, 16), (64, 8), (128, 16), (256, 16)]
)
def test_centroid_gather_parity(D, n_centroids, norm_correction):
    """Same indices => same gathered centroids; norm-correction identical."""
    c = _build_case(D=D, n_centroids=n_centroids)
    _, c_scalar, _ = _scalar_scores(
        c["q_rot"], c["packed"], c["vec_norms"], c["centroids"], D,
        c["mse_bits"], c["attn_scale"], norm_correction,
    )
    _, k_float, _ = _grouped_scores(
        c["q_rot"], c["packed"], c["vec_norms"], c["centroids"], D,
        c["mse_bits"], c["attn_scale"], norm_correction,
    )
    # k_float = vec_norms * c_vals; recover c_vals and compare to scalar.
    c_grouped = k_float / c["vec_norms"][:, None]
    assert np.allclose(c_grouped, c_scalar, atol=1e-6, rtol=1e-6), (
        "centroid tile (post-norm) differs between scalar and grouped"
    )


@pytest.mark.parametrize("norm_correction", [False, True])
@pytest.mark.parametrize(
    "D,n_centroids,H", [(64, 16, 2), (64, 16, 4), (128, 16, 4), (256, 16, 8)]
)
def test_score_parity_fp16(D, n_centroids, H, norm_correction):
    """The grouped tl.dot score row equals the scalar score row within
    fp16 tolerance — this is the gate against garbage output."""
    c = _build_case(D=D, n_centroids=n_centroids, H=H)
    _, _, scalar_scores = _scalar_scores(
        c["q_rot"], c["packed"], c["vec_norms"], c["centroids"], D,
        c["mse_bits"], c["attn_scale"], norm_correction,
    )
    _, _, grouped_scores = _grouped_scores(
        c["q_rot"], c["packed"], c["vec_norms"], c["centroids"], D,
        c["mse_bits"], c["attn_scale"], norm_correction,
    )
    assert scalar_scores.shape == grouped_scores.shape == (H, c["n_tok"])
    np.testing.assert_allclose(
        grouped_scores, scalar_scores, atol=ATOL, rtol=RTOL,
        err_msg="grouped MSE scores diverge from scalar reference",
    )


def test_algebraic_fold_identity():
    """vec_norms * sum(q*c) == sum(q * (vec_norms*c)) — the identity that
    lets us fold vec_norms into k_float before the dot. Exact in fp64."""
    rng = np.random.default_rng(7)
    D, n_tok, H = 64, 12, 3
    q = rng.standard_normal((H, D))
    c_vals = rng.standard_normal((n_tok, D))
    vn = np.abs(rng.standard_normal(n_tok)) + 0.1
    lhs = vn[None, :] * (q @ c_vals.T)            # scalar: vec_norms * term1
    rhs = q @ (vn[:, None] * c_vals).T            # grouped: fold then dot
    np.testing.assert_allclose(lhs, rhs, atol=1e-12, rtol=1e-12)
