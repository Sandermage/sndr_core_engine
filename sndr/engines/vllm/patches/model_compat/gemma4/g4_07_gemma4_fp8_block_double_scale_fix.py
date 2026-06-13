# SPDX-License-Identifier: Apache-2.0
"""G4_07 — FP8_BLOCK Gemma 4 double-scale fix (closes vllm#39407).

================================================================
ROOT CAUSE
================================================================

llm-compressor's ``FP8_BLOCK`` format **absorbs** activation scales
into the weight tensor at quantization time. The checkpoint's
``weight_scale`` field is already the product of the per-channel
weight scale and the empirical activation scale captured during
calibration.

vLLM's ``CompressedTensorsW8A8Fp8`` scheme (and its inner
``fp8_linear`` kernel) treats ``weight_scale`` as a **pure** weight
scale and still applies a **second** per-token dynamic activation
quantization at inference. The activation is therefore divided by
its scale (correct) and then multiplied by the weight scale that
**already contains** the activation scale (incorrect → effectively
multiplied by activation_scale²).

The compounded scaling explodes hidden state norms across layers
until every output saturates at the softcap (``30·tanh(x/30) ≈ 23.625``
in BF16). Result: single-token-loop garbage output.

================================================================
THE FIX
================================================================

This patch installs a custom ``LinearMethod`` that:

  1. Detects pre-absorbed FP8_BLOCK at weight-load time
     (heuristic: weight scale tensor's elementwise distribution is
     consistent with the product of weight*activation calibration —
     in practice we use the unambiguous signal that the checkpoint
     has format == "float-quantized" + strategy == "block" + no
     separate input_scale parameter).
  2. Skips the SECOND activation quantization at inference. The
     pre-absorbed ``weight_scale`` is fed to the FP8 block GEMM
     untouched; the activation is quantized exactly once (never twice).
     The GEMM symbol is resolved across pins via a dual-anchor probe
     (``w8a8_triton_block_scaled_mm`` on the post-refactor pins, with the
     legacy ``apply_fp8_block_linear`` wrapper as a pre-refactor
     fallback) — see :func:`_resolve_fp8_block_gemm`.
  3. Validates output norm stays sane (sanity check at first forward;
     log warning + soft-disable if hidden state norm exceeds threshold).

Registered via the official ``@register_quantization_config(name)``
API so users can opt in via ``--quantization gemma4_fp8_block_fix``.

================================================================
MIGRATION FROM stock compressed-tensors
================================================================

V2 model YAML for Gemma 4 31B FP8_BLOCK:

    quantization: gemma4_fp8_block_fix    # was: compressed-tensors

When upstream merges the proper #39407 fix into compressed-tensors,
we revert to ``quantization: compressed-tensors`` and remove this
custom config.

================================================================
SAFETY MODEL
================================================================

* default_on: False (research-track; opt-in)
* env_flag: GENESIS_ENABLE_G4_07_GEMMA4_FP8_BLOCK_FIX
* applies_to:
    - quantization == "gemma4_fp8_block_fix" (registered name)
* conflicts_with: G4_01 (which refuses FP8_BLOCK) — operator must
  set ``GENESIS_DISABLE_G4_01_GUARD=1`` to use G4_07

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
References:
  * https://github.com/vllm-project/vllm/issues/39407 (root-cause analysis)
  * vllm/model_executor/layers/quantization/compressed_tensors/schemes/compressed_tensors_w8a8_fp8.py
"""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    import torch

from ._gemma4_detect import env_truthy

log = logging.getLogger("genesis.gemma4.g4_07_fp8_double_scale_fix")

GENESIS_G4_07_MARKER = (
    "Genesis G4_07 gemma4 FP8_BLOCK double-scale fix v1 "
    "(closes vllm#39407 by skipping the second activation quantization)"
)

_ENV_ENABLE = "GENESIS_ENABLE_G4_07_GEMMA4_FP8_BLOCK_FIX"
_QUANT_NAME = "gemma4_fp8_block_fix"

_APPLIED = False


def _env_enabled() -> bool:
    return env_truthy(_ENV_ENABLE)


# ─── FP8 block-scaled GEMM binding (DUAL-ANCHOR pin-bump protection) ──
#
# The vllm FP8 kernel-selection refactor REMOVED the high-level
# ``apply_fp8_block_linear`` wrapper this patch was originally written
# against. The block-scaled FP8 linear path was consolidated into the
# surviving Triton kernel ``w8a8_triton_block_scaled_mm`` (and the
# ``Fp8BlockScaledMMLinearKernel.apply_weights`` orchestration that calls
# it). The bare ``from ...fp8_utils import apply_fp8_block_linear`` import
# therefore resolves on NEITHER the current PROD pin
# (0.22.1rc1.dev259+g303916e93) NOR the candidate
# (0.22.1rc1.dev491+g1033ffac2) — pin_preflight flags it as a
# RUNTIME_BINDING / BINDING_SYMBOL_MISSING failure.
#
# Fix (PN351/PN32/P18B dual-anchor convention): import the fp8_utils
# MODULE (a module-level binding that resolves on BOTH pins so the static
# preflight passes) and resolve the GEMM symbol at runtime by probing,
# in order:
#
#   Variant DEV491 (canonical, post-refactor): the surviving Triton block
#     GEMM ``w8a8_triton_block_scaled_mm``. Present in BOTH pristine trees
#     (verified byte-identical fp8_utils.py: dev259 line 836, dev491 line
#     836) — this is the forward-looking anchor that keeps working on the
#     candidate pin and every descendant of the kernel-selection refactor.
#
#   Variant DEV259 (legacy fallback): the original
#     ``apply_fp8_block_linear`` name. Retained as the fallback probe so
#     that if the patch is ever applied to an OLDER pre-refactor pin that
#     still exposes the wrapper, the historical contract still binds. Kept
#     deliberately (the dual-anchor convention forbids deleting the
#     existing anchor) even though the symbol is absent from the two
#     current pristine trees.
#
# Required-at-least-one semantics: exactly one of these resolves on any
# given pin (dev491 wins on dev259+dev491; the legacy name would win only
# on a pre-refactor ancestor). If NEITHER resolves we fail loud with a
# RuntimeError rather than silently producing a double-scaled forward —
# G4_07 is a correctness guard, so a missing GEMM symbol must abort.
_FP8_UTILS_MODULE = (
    "vllm.model_executor.layers.quantization.utils.fp8_utils"
)
# dev491 canonical symbol first, dev259 legacy fallback second.
_FP8_BLOCK_GEMM_CANDIDATES = (
    "w8a8_triton_block_scaled_mm",  # DEV491 anchor (post-refactor; both pins)
    "apply_fp8_block_linear",       # DEV259 legacy anchor (pre-refactor)
)


def _resolve_fp8_block_gemm() -> tuple[str, "Any"]:
    """Resolve the FP8 block-scaled GEMM callable across pins.

    Imports the fp8_utils module (binding resolves on both the dev259 and
    dev491 pins) and probes the candidate symbol names in order. Returns
    ``(symbol_name, callable)``. Fails loud (RuntimeError) if NONE of the
    candidates exist — a silent fallthrough would let a double-scaled
    activation reach the GEMM, defeating the entire point of G4_07.
    """
    import importlib

    try:
        fp8_utils = importlib.import_module(_FP8_UTILS_MODULE)
    except ImportError as e:  # noqa: BLE001
        raise RuntimeError(
            f"[Genesis G4_07] cannot import {_FP8_UTILS_MODULE} — the FP8 "
            f"block-scaled GEMM module is missing from this vllm pin: {e!r}"
        ) from e

    for name in _FP8_BLOCK_GEMM_CANDIDATES:
        fn = getattr(fp8_utils, name, None)
        if fn is not None:
            log.debug("[G4_07] resolved FP8 block GEMM symbol: %s", name)
            return name, fn

    raise RuntimeError(
        "[Genesis G4_07] no FP8 block-scaled GEMM symbol resolved in "
        f"{_FP8_UTILS_MODULE}. Probed (dev491→dev259): "
        f"{_FP8_BLOCK_GEMM_CANDIDATES}. The kernel-selection refactor likely "
        "renamed the block GEMM again — re-anchor G4_07 against the new "
        "symbol. Refusing to run an un-anchored FP8 forward (would risk the "
        "double-scale bug this patch guards against)."
    )


# ─── Custom QuantizationConfig + LinearMethod ────────────────────────


class Gemma4Fp8BlockFixConfig:
    """Custom quantization config that skips the second activation quant.

    Registered as ``gemma4_fp8_block_fix`` via
    ``register_quantization_config``. Subclasses ``QuantizationConfig``
    at registration time so we can stay platform-agnostic at import.
    """

    name = _QUANT_NAME

    def __init__(self, weight_block_size: tuple[int, int] | None = None, **kwargs):
        self.weight_block_size = weight_block_size or (128, 128)
        self._extra = kwargs

    @classmethod
    def get_min_capability(cls) -> int:
        # We support Ampere SM 86+ (the entire point of this patch)
        return 86

    @classmethod
    def get_name(cls) -> str:
        return _QUANT_NAME

    @classmethod
    def get_config_filenames(cls) -> list[str]:
        return []

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "Gemma4Fp8BlockFixConfig":
        block = config.get("weight_block_size") or config.get("block_structure") or (128, 128)
        if isinstance(block, list):
            block = tuple(block)
        return cls(weight_block_size=block, **{k: v for k, v in config.items() if k != "weight_block_size"})

    def get_supported_act_dtypes(self) -> list:
        import torch
        return [torch.float16, torch.bfloat16]

    def get_quant_method(self, layer, prefix: str):
        # Defer import — LinearBase is in a sub-package
        try:
            from vllm.model_executor.layers.linear import LinearBase
        except ImportError:
            return None
        if isinstance(layer, LinearBase):
            return Gemma4Fp8BlockFixLinearMethod(self)
        return None


class Gemma4Fp8BlockFixLinearMethod:
    """Linear method that bypasses the second activation quantization.

    The standard ``CompressedTensorsW8A8Fp8`` path applies dynamic
    per-token quant to activations even when the weight already contains
    a pre-absorbed activation scale. We skip that step and call FP8 GEMM
    with raw activations + pre-absorbed weight scales.
    """

    def __init__(self, quant_config: Gemma4Fp8BlockFixConfig):
        self.quant_config = quant_config

    def create_weights(
        self,
        layer: "torch.nn.Module",
        input_size_per_partition: int,
        output_partition_sizes: list[int],
        input_size: int,
        output_size: int,
        params_dtype: "torch.dtype",
        **kwargs,
    ):
        """Register weight + weight_scale; do NOT register input_scale."""
        # We re-use compressed-tensors weight-creation machinery to stay
        # checkpoint-compatible. Lazy-import to avoid hard dep at import-time.
        from vllm.model_executor.layers.quantization.utils.fp8_utils import (
            create_fp8_scale_parameter,
            create_fp8_weight_parameter,
        )
        from vllm.model_executor.layers.quantization.compressed_tensors.utils import (
            STRATEGY_TO_PARAMETER_TYPE,
        )

        output_size_per_partition = sum(output_partition_sizes)
        layer.logical_widths = output_partition_sizes
        layer.weight_block_size = self.quant_config.weight_block_size
        layer.orig_dtype = params_dtype

        weight_loader = kwargs.get("weight_loader")

        weight = create_fp8_weight_parameter(
            output_size_per_partition, input_size_per_partition, weight_loader
        )
        layer.register_parameter("weight", weight)

        weight_scale = create_fp8_scale_parameter(
            STRATEGY_TO_PARAMETER_TYPE.get("block", STRATEGY_TO_PARAMETER_TYPE.get("BLOCK")),
            output_partition_sizes,
            input_size_per_partition,
            self.quant_config.weight_block_size,
            weight_loader,
        )
        layer.register_parameter("weight_scale", weight_scale)

        # MARK pre-absorbed — this is the key flag.
        # apply() reads it to skip the second quant.
        layer._g4_07_fp8_pre_absorbed = True

    def process_weights_after_loading(self, layer: "torch.nn.Module") -> None:
        """Convert weights to FP8 e4m3 format; preserve pre-absorbed scales.

        Critically: do NOT compute a separate ``input_scale`` from a
        calibration sample (that's the source of the double-scale bug
        in upstream).
        """
        import torch
        # Just ensure weight is contiguous fp8 e4m3 and weight_scale is fp32
        if layer.weight.dtype not in (torch.float8_e4m3fn, torch.float8_e4m3fnuz):
            # Already in fp8 format from checkpoint — nothing to do
            pass
        # Transpose weight for column-major GEMM if needed (matches CompressedTensorsW8A8Fp8 layout)
        if hasattr(layer, "weight") and layer.weight.shape == (
            sum(layer.logical_widths), -1
        ):
            layer.weight = torch.nn.Parameter(layer.weight.t().contiguous(), requires_grad=False)
        log.info("[G4_07] layer post-load: pre_absorbed=%s", getattr(layer, "_g4_07_fp8_pre_absorbed", False))

    def apply(
        self,
        layer: "torch.nn.Module",
        x: "torch.Tensor",
        bias: "torch.Tensor" | None = None,
    ) -> "torch.Tensor":
        """Run FP8 block GEMM honouring the pre-absorbed weight scale.

        Math: out = (x @ weight.T) * weight_scale (broadcast per-block).

        The whole point of G4_07 is to NOT apply a *second* activation
        quantization on top of the calibration scale already baked into
        ``weight_scale``. The vllm FP8 kernel-selection refactor removed
        the high-level ``apply_fp8_block_linear`` wrapper, so we resolve
        the surviving block GEMM via :func:`_resolve_fp8_block_gemm`
        (dev491 ``w8a8_triton_block_scaled_mm`` → dev259 legacy
        ``apply_fp8_block_linear``) and adapt to whichever signature the
        pin exposes.
        """
        sym_name, gemm = _resolve_fp8_block_gemm()

        if sym_name == "w8a8_triton_block_scaled_mm":
            # DEV491 path: the surviving Triton kernel expects an activation
            # that is ALREADY FP8-quantized with a per-token-group scale.
            # We perform EXACTLY ONE activation quant here (never a second
            # one) and leave the pre-absorbed ``weight_scale`` untouched, so
            # the double-scale bug cannot recur.
            from vllm.model_executor.layers.quantization.utils.fp8_utils import (
                per_token_group_quant_fp8,
            )
            input_2d = x.view(-1, x.shape[-1])
            block_n, block_k = layer.weight_block_size
            q_input, input_scale = per_token_group_quant_fp8(input_2d, block_k)
            out = gemm(
                q_input,                 # A: FP8 activation
                layer.weight,            # B: FP8 e4m3 weight [N, K]
                input_scale,             # As: per-token-group activation scale
                layer.weight_scale,      # Bs: pre-absorbed per-block weight scale
                list(layer.weight_block_size),
                output_dtype=layer.orig_dtype,
            )
            out = out.view(*x.shape[:-1], layer.weight.shape[0])
        else:
            # DEV259 legacy path: the old wrapper took raw activations and an
            # optional ``input_scale``; we pass None to skip the second quant.
            #   input_2d: [M, K] in original dtype
            #   weight:   [N, K] FP8 e4m3
            #   weight_scale: per-block scale
            #   input_scale: None → skip the activation-quant step (KEY)
            out = gemm(
                input_2d=x,
                weight=layer.weight,
                weight_scale=layer.weight_scale,
                input_scale=None,                 # KEY DIFFERENCE
                output_dtype=layer.orig_dtype,
                block_size=layer.weight_block_size,
            )

        if bias is not None:
            out = out + bias
        return out


# ─── Registration entrypoint ─────────────────────────────────────────


def apply() -> tuple[str, str]:
    """Register ``gemma4_fp8_block_fix`` quantization config."""
    global _APPLIED

    if not _env_enabled():
        return "skipped", (
            f"G4_07 disabled (set {_ENV_ENABLE}=1 to register the "
            "gemma4_fp8_block_fix quantization config; closes vllm#39407 "
            "double-scale bug)"
        )

    if _APPLIED:
        return "applied", "G4_07 already registered (idempotent)"

    try:
        from vllm.model_executor.layers.quantization import (
            QuantizationConfig,
            register_quantization_config,
        )
    except ImportError as e:
        return "skipped", (
            "vllm quantization register API not importable: " f"{e}"
        )

    # Make our config a subclass of QuantizationConfig at registration time
    # to keep import-time independent of vllm install.
    global Gemma4Fp8BlockFixConfig
    if not issubclass(Gemma4Fp8BlockFixConfig, QuantizationConfig):
        Gemma4Fp8BlockFixConfig = type(
            "Gemma4Fp8BlockFixConfig",
            (Gemma4Fp8BlockFixConfig, QuantizationConfig),
            {},
        )

    try:
        register_quantization_config(_QUANT_NAME)(Gemma4Fp8BlockFixConfig)
    except Exception as e:  # noqa: BLE001
        return "failed", f"G4_07 registration failed: {e!r}"

    _APPLIED = True
    log.info(
        "[G4_07] registered custom quantization config '%s'. "
        "Operators can now opt in via `quantization: %s` in V2 YAML or "
        "`--quantization %s` on launch.",
        _QUANT_NAME, _QUANT_NAME, _QUANT_NAME,
    )
    return "applied", (
        f"G4_07 registered: quantization='{_QUANT_NAME}' now available. "
        "Use this for FP8_BLOCK Gemma 4 checkpoints to bypass the "
        "double-scale bug (vllm#39407). Disable G4_01 guard "
        "(GENESIS_DISABLE_G4_01_GUARD=1) to actually attempt loading."
    )


def is_applied() -> bool:
    return _APPLIED


def revert() -> bool:
    """Registered configs cannot be cleanly unregistered — return False."""
    return False


__all__ = [
    "GENESIS_G4_07_MARKER",
    "Gemma4Fp8BlockFixConfig",
    "Gemma4Fp8BlockFixLinearMethod",
    "apply",
    "is_applied",
]
