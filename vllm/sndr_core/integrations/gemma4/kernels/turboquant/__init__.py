# SPDX-License-Identifier: Apache-2.0
"""Genesis G4-TurboQuant — KV cache compression for Gemma 4.

Vector-quantization KV cache adapted from TurboQuant (arXiv:2504.19874)
+ RotorQuant variant (Mimi8298 / scrya-com proposal in vllm#38291), tuned
for Gemma 4 architecture:

  * head_dim = 256 (decomposed into 2× 128-blocks for rotor application)
  * Mixed sliding (window=1024) + global (window=262144) attention
  * GQA (uniform num_kv_heads per layer in current cyankiwi checkpoints)
  * Native vLLM v1 KV-cache integration

This package provides:

  * ``g4_tq_codebook``       — Lloyd-Max scalar quantizer codebooks
                               (3-bit, 4-bit, 5-bit per-coordinate)
  * ``g4_tq_rotor``          — Clifford-rotor + Randomized Hadamard
                               rotation matrix generator
  * ``g4_tq_reference``      — torch reference implementations
                               (for testing the Triton kernels)
  * ``g4_tq_write_triton``   — fused write kernel: rotate → quantize → pack
  * ``g4_tq_read_triton``    — fused read kernel: unpack → dequantize →
                               unrotate → attention input
  * ``g4_tq_cache``          — KVCache wrapper class for vLLM v1
                               integration

Genesis ports of this kernel family follow the same patch-discipline as
our Qwen 3.5/3.6 TurboQuant K8V4 stack (P67, PN116, PN118, PN119) but
adapted to Gemma 4's interleaved attention pattern and head_dim=256.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
"""

from .g4_tq_codebook import (
    BITS_3_LLOYD_MAX_CENTROIDS,
    BITS_4_LLOYD_MAX_CENTROIDS,
    BITS_5_LLOYD_MAX_CENTROIDS,
    get_centroids,
    lloyd_max_codebook,
)
from .g4_tq_rotor import (
    build_randomized_hadamard_seed,
    clifford_rotate_full,
    clifford_rotor_layer,
    randomized_hadamard_apply,
    randomized_hadamard_apply_blocked,
)

__all__ = [
    "BITS_3_LLOYD_MAX_CENTROIDS",
    "BITS_4_LLOYD_MAX_CENTROIDS",
    "BITS_5_LLOYD_MAX_CENTROIDS",
    "get_centroids",
    "lloyd_max_codebook",
    "build_randomized_hadamard_seed",
    "clifford_rotate_full",
    "clifford_rotor_layer",
    "randomized_hadamard_apply",
    "randomized_hadamard_apply_blocked",
]

GENESIS_G4_TQ_VERSION = "g4_tq_v1.0_genesis"
