# SPDX-License-Identifier: Apache-2.0
"""PN134 — torch.compile fullgraph patch для PyTorch 2.11 (backport vllm#42686).

================================================================
ПРОБЛЕМА
================================================================

vLLM issue #27828 + pytorch/pytorch#176994: Inductor materialization
heuristic в PyTorch 2.11 не реализует useful intermediate tensors
которые reused несколько раз. Результат:

  - residual в fused_add_rms_norm пересчитывается каждый раз
  - cascade re-computation через весь модель
  - Inflated compile cache + slower forward (для torch.compile mode)

Fix landed в PyTorch 2.12 (https://github.com/pytorch/pytorch/pull/176994).
PR #42686 backports simplified version для 2.11.

Применимо к нам?
  - Мы НА PyTorch 2.11 → ИДЕАЛЬНО применимо
  - VLLM_USE_AOT_COMPILE=True (наш default)
  - torch.compile активен на всех 41 модель layers
  - Без fix — потенциально лишние recompute операции

================================================================
FIX
================================================================

Monkey-patches `torch._inductor.ir.StorageBox.should_realize_on_reuse`
с size-aware cost model:

    total_read_bytes = sum read_bytes
    output_bytes = numel * dtype_itemsize

    if total_read_bytes * (users - 1) >= output_bytes * (1 + users):
        return True  # materialize

Это означает: tensor реализуется когда чтение его n раз дороже
чем 1× write + n× read. Включает special cases:
  - heavy ops (exp, sigmoid) на CPU → realize
  - large inner_fn → realize

PN134 backport через runtime monkey-patch на StorageBox.

================================================================
EXPECTED IMPACT
================================================================

  - Inductor compile cache hit rate ↑
  - First-prefill forward latency: -2..-8 ms (less recompute)
  - Memory pressure ↓ (cached intermediates)
  - Boot time: slight increase (cache warming) → амортизируется

================================================================
SAFETY
================================================================

  - Только PyTorch 2.11 (2.12+ имеет fix native, 2.10- не поддерживает)
  - Idempotent (флаг на StorageBox class)
  - Auto-skip когда torch != 2.11

Author: Sandermage 2026-05-15. Backport vllm#42686 (OPEN).
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("genesis.wiring.pn134_torch_compile_fullgraph_211")

GENESIS_PN134_MARKER = "Genesis PN134 torch.compile fullgraph 2.11 patch v1 (vllm#42686)"
_ENV_ENABLE = "GENESIS_ENABLE_PN134_TORCH_COMPILE_FULLGRAPH_211"
_ENV_DISABLE = "GENESIS_DISABLE_PN134_TORCH_COMPILE_FULLGRAPH_211"

_APPLIED = False
_ORIGINAL_FN: object = None


def _env_enabled() -> bool:
    if os.environ.get(_ENV_DISABLE, "").strip().lower() in ("1", "true", "yes", "on"):
        return False
    val = os.environ.get(_ENV_ENABLE, "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _is_torch_211() -> bool:
    """Check if running PyTorch 2.11."""
    try:
        import torch
        ver = torch.__version__.split("+")[0]
        major, minor = ver.split(".")[:2]
        return int(major) == 2 and int(minor) == 11
    except Exception as e:
        log.warning("[PN134] torch version detection failed: %s", e)
        return False


def _patched_should_realize_on_reuse(self, users: int) -> bool:
    """Size-aware materialization heuristic backport.

    Decides if a reused tensor should be realized (materialized) vs
    inlined for re-computation. Original 2.11 heuristic is too
    conservative for cases like residual in fused_add_rms_norm.
    """
    from torch._inductor import config
    from torch._inductor.ir import Pointwise, Reduction, is_cpu
    from torch._inductor.virtualized import V

    if users > 1 and isinstance(self.data, (Pointwise, Reduction)):
        if is_cpu(self.data):
            opcount = self.data.inner_fn_opcount()
            heavy_ops = ["exp", "sigmoid"]
            if any(x in opcount.used_ops for x in heavy_ops):
                return True
        if self.has_large_inner_fn():
            return True
        # Size-aware cost model
        total_read_bytes = sum(
            V.graph.get_dep_size_hint(dep) for dep in self.get_reads()
        )
        output_bytes = (
            V.graph.sizevars.optimization_hint(self.data.get_numel(), fallback=0)
            * self.data.dtype.itemsize
        )
        if total_read_bytes > 0 and output_bytes > 0:
            return total_read_bytes * (users - 1) >= output_bytes * (1 + users)
        return self.num_reads() > config.realize_reads_threshold
    return False


def apply() -> tuple[str, str]:
    """Monkey-patch StorageBox.should_realize_on_reuse для PyTorch 2.11."""
    global _APPLIED, _ORIGINAL_FN

    if not _env_enabled():
        return "skipped", (
            f"PN134 disabled (set {_ENV_ENABLE}=1 — backport vllm#42686 "
            f"torch.compile materialization heuristic fix для 2.11; "
            f"closes vLLM issue #27828)"
        )

    if _APPLIED:
        return "applied", "PN134 already installed (idempotent)"

    if not _is_torch_211():
        try:
            import torch
            return "skipped", (
                f"PN134 only для torch 2.11 (running {torch.__version__}); "
                f"2.12+ has native fix, 2.10- doesn't need it"
            )
        except ImportError:
            return "skipped", "torch not importable"

    try:
        from torch._inductor.ir import StorageBox
    except ImportError as e:
        return "skipped", f"torch._inductor.ir.StorageBox not importable: {e}"

    if hasattr(StorageBox, "_genesis_pn134_wrapped"):
        _APPLIED = True
        return "applied", "PN134 StorageBox already wrapped (idempotent)"

    _ORIGINAL_FN = StorageBox.should_realize_on_reuse
    StorageBox.should_realize_on_reuse = _patched_should_realize_on_reuse
    StorageBox._genesis_pn134_wrapped = True
    _APPLIED = True

    log.info(
        "[PN134] installed: StorageBox.should_realize_on_reuse "
        "теперь использует size-aware cost model (backport "
        "pytorch#176994 для torch 2.11). Inductor compilation "
        "должен realize чаще shared intermediates."
    )
    return "applied", (
        "PN134 installed: torch.compile fullgraph materialization "
        "heuristic patched на PyTorch 2.11 (vllm#42686 backport). "
        "Expected: -2..-8 ms prefill, lower inductor compile cache "
        "miss rate. Auto-skip когда torch != 2.11."
    )


def is_applied() -> bool:
    return _APPLIED


def revert() -> bool:
    global _APPLIED, _ORIGINAL_FN
    if not _APPLIED or _ORIGINAL_FN is None:
        return False
    try:
        from torch._inductor.ir import StorageBox
        StorageBox.should_realize_on_reuse = _ORIGINAL_FN  # type: ignore[assignment]
        delattr(StorageBox, "_genesis_pn134_wrapped")
        _APPLIED = False
        return True
    except (ImportError, AttributeError):
        return False
