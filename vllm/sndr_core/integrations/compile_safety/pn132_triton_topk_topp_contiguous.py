# SPDX-License-Identifier: Apache-2.0
"""PN132 — Triton top-k/top-p contiguous logits fix (backport vllm#42739).

================================================================
ПРОБЛЕМА
================================================================

PR #42739 (OPEN, 2026-05-15) фиксит correctness bug в
`apply_top_k_top_p_triton()` для случая non-contiguous logits.

Triton kernel `apply_top_k_top_p` вычисляет row pointer как
`base + row_id * VOCAB_SIZE` — это предполагает contiguous
row-major layout. Если `logits` — это non-contiguous view
(например после `index_select` или slicing), kernel читает
WRONG memory и выдаёт garbage scores.

Импакт:
  - Молчаливая correctness регрессия (нет error, просто wrong top-k mask)
  - Affects ANY caller через `apply_top_k_top_p_triton()` если
    upstream slicing создаёт non-contiguous view

Применимо к нам?
  - У нас VLLM_USE_FLASHINFER_SAMPLER=1 → top-k/top-p
    использует FlashInfer path, не Triton
  - НО fallback на Triton возможен (если FlashInfer не поддерживает
    конкретную combo top-k + top-p + temperature)
  - Defense-in-depth — применяем

================================================================
FIX
================================================================

3-line addition в apply_top_k_top_p_triton:

    if not logits.is_contiguous():
        logits = logits.contiguous()

PN132 backport через text-patch на функцию (3 lines insertion
после assert dtype, перед batch_size unpacking).

================================================================
COMPOSITION
================================================================

  - Safe with VLLM_USE_FLASHINFER_SAMPLER=1 (наш default) —
    Triton path не используется обычно
  - Стэкаются с другими top-k/top-p patches (никаких нет у нас)
  - Auto-skip когда upstream lands (drift marker)
  - Idempotent через text-patch marker

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
        "[PN132] installed: apply_top_k_top_p_triton теперь guarantee "
        "logits contiguous перед Triton kernel. Backport vllm#42739."
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
