# SPDX-License-Identifier: Apache-2.0
"""PN352B — route the Marlin MoE topk=8 reduce through the Genesis Triton kernel.

A/B 2026-06-15 (PROD 35B, dev491): BUILT + VALIDATED, default OFF. Numerics
BIT-IDENTICAL to ops.moe_sum (max_abs_diff=0.0 @ M=4/8/16). Stable — crash-test
passed, kernel fires, DEFEATS the parked-PN352 stream race (Marlin-site override
runs inside the FULL-capture apply). Perf clean decode-TPOT n=125: 4.725 vs
4.776 ms = -1.07%, Welch p=0.38 NOT SIGNIFICANT (the reduce isn't the latency-
bound bottleneck at tiny M=8). Kept default OFF as a working superset of the
broken parked PN352; candidate for a MULTI-CONC A/B (larger M). Code targets the
concrete ``MarlinExperts`` class (the docstring's "MarlinExpertsBase" mentions
are conceptual; ``moe_sum`` lives on ``MarlinExperts(LoRAExpertsMixin,
MarlinExpertsBase)``).

The original PN352 text-patched ``fused_moe.py::fused_experts_impl`` — but the
FP8 Marlin MoE path (the live Qwen3.6-35B decode) NEVER executes that site:
``MarlinExpertsBase`` returns ``TopKWeightAndReduceNoOP`` for the modular
finalize and does its OWN reduction via ``self.moe_sum`` (marlin_moe.py:487,959
→ :996 ``ops.moe_sum``). And ``_moe_C.moe_sum`` has fast paths only for topk
2/3/4; Qwen3.6-A3B routes 8 experts/token, so it falls through to the generic
``at::sum_out`` TensorIterator reduce — a serial, launch-heavy reduction fired
40×/forward on the decode critical path.

PN352B monkey-patches ``MarlinExpertsBase.moe_sum`` (the RIGHT site, PN96b
style) to route topk∉{2,3,4} through the verified ``moe_sum_topk`` Triton kernel
(``kernels_legacy/pn352_moe_sum_topk``), falling back to ``ops.moe_sum`` on any
failure.

Why this avoids the parked-PN352 stream race
---------------------------------------------
The parked text-patch launched the Triton kernel on the bare current stream at
the fused_moe.py site, racing the engine's producer/consumer streams. Here the
override runs INSIDE ``apply()`` which, under the 35B's FULL_AND_PIECEWISE
cudagraph, executes on the capture/replay stream — so the Triton launch is
captured into the graph on the correct stream (no cross-stream race). To keep
capture clean we PRE-WARM the kernel at install for the decode shapes
([M,8,hidden] for M∈{4,8}, fp16) so it never JIT-compiles during graph capture,
and we swallow any kernel exception to fall back — a serial-reduction swap can
never crash the engine.

This is the LATENCY-bound stack's one remaining non-regressing single-stream
lever: it removes a serial fixed-latency reduction without touching parallelism,
occupancy, or batch — structurally outside the regression class (num_warps↓,
splits↓, K↓, tiny-M-extra-work). Est −1..3% decode TPOT, helps ALL variants
incl. temp=0 (code/tool_call). Numerics: fp32 accumulate, same tolerance class
as the upstream topk 2/3/4 CUDA kernels (not bit-identical — different reduction
order); numeric-gate vs ops.moe_sum on a held-out shape before trusting.

Opt-in: GENESIS_ENABLE_PN352B_MARLIN_MOE_SUM=1 (default OFF, A/B pending).
GENESIS_DISABLE_PN352B=1 force-reverts.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("genesis.wiring.pn352b_marlin_moe_sum")

_ENV_ENABLE = "GENESIS_ENABLE_PN352B_MARLIN_MOE_SUM"
_ENV_DISABLE = "GENESIS_DISABLE_PN352B"
_MARKER_ATTR = "_genesis_pn352b_marlin"


def _env_enabled() -> bool:
    if os.environ.get(_ENV_DISABLE, "").strip().lower() in ("1", "true", "yes", "on"):
        return False
    return os.environ.get(_ENV_ENABLE, "").strip().lower() in ("1", "true", "yes", "on")


def _prewarm(moe_sum_topk) -> str:
    """JIT the Triton kernel for the decode shapes so it never compiles during
    cudagraph capture. Best-effort; returns a status string."""
    try:
        import torch

        if not torch.cuda.is_available():
            return "prewarm skipped (no CUDA at install)"
        # Qwen3.6-35B-A3B: hidden_size=2048, topk=8. Decode M = max_num_seqs ×
        # (MTP K+1) ∈ {4, 8}. BLOCK is a function of hidden only, so any M warms
        # the (TOPK=8, BLOCK) binary that all decode M reuse.
        warmed = 0
        for m in (4, 8):
            x = torch.randn(m, 8, 2048, device="cuda", dtype=torch.float16)
            o = torch.empty(m, 2048, device="cuda", dtype=torch.float16)
            if moe_sum_topk(x, o):
                warmed += 1
        torch.cuda.synchronize()
        return f"prewarm OK ({warmed}/2 shapes JIT'd)"
    except Exception as e:  # never fail install on a prewarm hiccup
        return f"prewarm best-effort failed ({e!r}) — kernel JITs on first call"


def apply() -> tuple[str, str]:
    """Monkey-patch MarlinExpertsBase.moe_sum for topk∉{2,3,4}. Never raises."""
    if not _env_enabled():
        return "skipped", (
            f"PN352B disabled (set {_ENV_ENABLE}=1 to route the Marlin MoE "
            f"topk=8 reduce through the Genesis Triton kernel — A/B pending)"
        )
    try:
        from vllm.model_executor.layers.fused_moe.experts.marlin_moe import (
            MarlinExperts,
        )
    except Exception as e:
        return "skipped", f"PN352B: MarlinExpertsBase not importable ({e!r})"

    orig = MarlinExperts.moe_sum
    if getattr(orig, _MARKER_ATTR, False):
        return "applied", "PN352B already installed (idempotent)."

    try:
        from sndr.engines.vllm.kernels_legacy.pn352_moe_sum_topk import (
            moe_sum_topk,
        )
    except Exception as e:
        return "skipped", f"PN352B: moe_sum_topk kernel not importable ({e!r})"

    def _wrapped(self, input, output) -> None:  # noqa: ANN001
        # input: [num_tokens, topk, hidden]; output: [num_tokens, hidden].
        try:
            if input.dim() == 3 and input.size(1) not in (2, 3, 4):
                if moe_sum_topk(input, output):
                    return
        except Exception:
            pass  # any failure -> upstream reduce; a reduction swap never crashes
        orig(self, input, output)

    setattr(_wrapped, _MARKER_ATTR, True)
    MarlinExperts.moe_sum = _wrapped

    prewarm = _prewarm(moe_sum_topk)
    return "applied", (
        "PN352B applied: MarlinExpertsBase.moe_sum now routes topk∉{2,3,4} "
        f"through the Genesis Triton kernel. {prewarm}. Fallback to ops.moe_sum "
        "on any failure. Numeric-gate vs ops.moe_sum + crash-watch before trust."
    )


def is_applied() -> bool:
    try:
        from vllm.model_executor.layers.fused_moe.experts.marlin_moe import (
            MarlinExperts,
        )
        return getattr(MarlinExperts.moe_sum, _MARKER_ATTR, False)
    except Exception:
        return False
