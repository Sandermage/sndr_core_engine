# SPDX-License-Identifier: Apache-2.0
"""PN132 — Triton top-k/top-p contiguous logits fix (backport vllm#42739).

================================================================
PROBLEM
================================================================

PR #42739 (OPEN, 2026-05-15) fixes a correctness bug in
`apply_top_k_top_p_triton()` for non-contiguous logits.

The Triton kernel `apply_top_k_top_p` computes the row pointer as
`base + row_id * VOCAB_SIZE`, which assumes a contiguous row-major
layout. If `logits` is a non-contiguous view (e.g. after
`index_select` or slicing), the kernel reads WRONG memory and
returns garbage scores.

Impact:
  - Silent correctness regression (no error — just wrong top-k mask)
  - Affects ANY caller of `apply_top_k_top_p_triton()` when
    upstream slicing produces a non-contiguous view

Applicable to us?
  - We run VLLM_USE_FLASHINFER_SAMPLER=1, so top-k/top-p normally
    uses the FlashInfer path, not Triton.
  - BUT fallback to Triton is possible (when FlashInfer cannot
    handle a specific top-k + top-p + temperature combo).
  - Defense-in-depth — apply.

================================================================
FIX
================================================================

3-line addition in apply_top_k_top_p_triton:

    if not logits.is_contiguous():
        logits = logits.contiguous()

PN132 backports via text-patch on the function (3-line insertion
after the dtype assert, before batch_size unpacking).

================================================================
COMPOSITION
================================================================

  - Safe with VLLM_USE_FLASHINFER_SAMPLER=1 (our default) —
    the Triton path is usually unused.
  - Stacks with other top-k/top-p patches (none on our side).
  - Auto-skip when upstream lands (drift marker).
  - Idempotent via the text-patch marker.

Author: Sandermage 2026-05-15. Backport vllm#42739 (OPEN).
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("genesis.wiring.pn132_triton_topk_topp_contiguous")

GENESIS_PN132_MARKER = "Genesis PN132 Triton top-k/top-p contiguous fix v1 (vllm#42739)"
_ENV_ENABLE = "GENESIS_ENABLE_PN132_TOPK_TOPP_CONTIGUOUS"
_ENV_DISABLE = "GENESIS_DISABLE_PN132_TOPK_TOPP_CONTIGUOUS"

_APPLIED = False
_ORIGINAL_FN: object = None


def _env_enabled() -> bool:
    if os.environ.get(_ENV_DISABLE, "").strip().lower() in ("1", "true", "yes", "on"):
        return False
    val = os.environ.get(_ENV_ENABLE, "").strip().lower()
    return val in ("1", "true", "yes", "on")


def apply() -> tuple[str, str]:
    """Wraps apply_top_k_top_p_triton to ensure logits.is_contiguous()."""
    global _APPLIED, _ORIGINAL_FN

    if not _env_enabled():
        return "skipped", (
            f"PN132 disabled (set {_ENV_ENABLE}=1 — backport vllm#42739 "
            f"correctness fix: ensure logits contiguous before Triton "
            f"top-k/top-p kernel. Defense-in-depth on FlashInfer-default "
            f"path; fires only on Triton fallback)"
        )

    if _APPLIED:
        return "applied", "PN132 already installed (idempotent)"

    try:
        from vllm.v1.sample.ops import topk_topp_triton as _mod
    except ImportError as e:
        return "skipped", f"topk_topp_triton not importable: {e}"

    if not hasattr(_mod, "apply_top_k_top_p_triton"):
        return "skipped", "apply_top_k_top_p_triton function not found"

    original = _mod.apply_top_k_top_p_triton
    if getattr(original, "_genesis_pn132_wrapped", False):
        _APPLIED = True
        return "applied", "PN132 already wrapped (idempotent)"

    _ORIGINAL_FN = original

    def _genesis_pn132_wrapped_topk_topp(logits, k, p):
        """Original apply_top_k_top_p_triton + contiguous guarantee.

        PR #42739: Triton kernel computes row_ptr = base + row * VOCAB
        which assumes contiguous row-major layout. If logits is a
        non-contiguous view (from index_select/slicing), the kernel
        reads garbage memory.
        """
        import torch
        if isinstance(logits, torch.Tensor) and not logits.is_contiguous():
            log.debug(
                "[PN132] non-contiguous logits detected (shape=%s, "
                "strides=%s) — making contiguous before Triton kernel",
                logits.shape, logits.stride(),
            )
            logits = logits.contiguous()
        return original(logits, k, p)

    _genesis_pn132_wrapped_topk_topp._genesis_pn132_wrapped = True
    _genesis_pn132_wrapped_topk_topp._genesis_pn132_original = original

    _mod.apply_top_k_top_p_triton = _genesis_pn132_wrapped_topk_topp
    _APPLIED = True

    log.info(
        "[PN132] installed: apply_top_k_top_p_triton now guarantees "
        "contiguous logits before the Triton kernel. Backport vllm#42739."
    )
    return "applied", (
        "PN132 installed: Triton top-k/top-p contiguous fix wired "
        "(vllm#42739 backport). Correctness fix on non-contiguous "
        "logits views. No-op when FlashInfer sampler active."
    )


def is_applied() -> bool:
    return _APPLIED


def revert() -> bool:
    global _APPLIED, _ORIGINAL_FN
    if not _APPLIED or _ORIGINAL_FN is None:
        return False
    try:
        from vllm.v1.sample.ops import topk_topp_triton as _mod
        _mod.apply_top_k_top_p_triton = _ORIGINAL_FN  # type: ignore[assignment]
        _APPLIED = False
        return True
    except ImportError:
        return False
