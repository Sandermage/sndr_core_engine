# SPDX-License-Identifier: Apache-2.0
"""PN518 — INCConfig hybrid INT4+FP8 AutoRound latent trap-closer.

LATENT, default-OFF diagnostic guard (vendor of OPEN vllm#46322)
===============================================================

vllm#46322 adds ``INCConfig.maybe_update_config`` so a hybrid INT4+FP8
``auto-round`` checkpoint's FP8 attention / shared-expert layers are
detected and routed to ``Fp8LinearMethod`` instead of being silently
treated as unquantized. dev424 (0.23.1rc1.dev424+g3f5a1e173) is MISSING
this method: ``INCConfig`` inherits the base no-op
(``QuantizationConfig.maybe_update_config`` at base_config.py:195), which
is invoked once per model at ``config/vllm.py:637``. Without it, the FP8
layers' ``weight_scale_inv`` siblings are never applied →
``UnquantizedLinearMethod`` is used on genuinely-FP8 weights → garbage.

Why this is LATENT (not LIVE) on our stack
===========================================

None of our checkpoints is a hybrid INT4+FP8 auto-round checkpoint:

  * 27B (Lorbus Qwen3.6-27B-int4-AutoRound) routes auto-round → INCConfig
    (override_quantization_method), but its ``extra_config`` keeps
    ``linear_attn.in_proj_{a,b}`` at **bits=16, data_type="fp"** =
    genuinely-unquantized 16-bit (NOT fp8). Those layers are correctly
    served TODAY by the existing extra_config pre-check loop in
    ``get_quant_method`` (bits>=16 → ``UnquantizedLinearMethod``). The
    46322 repro needs FP8 (8-bit float, with ``weight_scale_inv``) layers
    MIXED into an auto-round checkpoint — we run zero such checkpoints.
  * 35B is quant_method=fp8 → ``Fp8Config`` (NOT inc). Out of this path.

BUT the 27B already INSTANTIATES ``INCConfig``, so the broken path is one
``Qwen3.6-*-Hybrid-INT4-FP8`` checkpoint away from silently emitting
garbage. PN518 closes that trap NOW, default-OFF, before such a model
lands.

What PN518 actually does (LOW-RISK, non-perturbing subset)
==========================================================

PN518 injects a ``maybe_update_config`` method onto ``INCConfig`` that:

  1. Scans the checkpoint's safetensors metadata (header dtypes only, no
     tensor reads) for ``float8_e4m3fn`` weights carrying a sibling
     ``.weight_scale_inv`` — the block-scaled FP8 signature.
  2. If NONE are found (the live 27B/35B case) → returns immediately. A
     STRICT NO-OP: ``get_quant_method`` is NOT touched, so the 27B's
     bits=16 ``UnquantizedLinearMethod`` dispatch is byte-for-byte
     unchanged. ZERO perturbation to the PROD load.
  3. If FP8 layers ARE found on an auto-round checkpoint AND the running
     pin lacks a native FP8-routing ``maybe_update_config`` → emits a
     LOUD ACTIONABLE boot WARN naming the affected layers, converting
     upstream's silent-garbage into a diagnosed event (the Genesis
     PN377-style "loud boot assert" pattern). On sm_86 (Ampere) it also
     logs an INFO that FP8 execution would dispatch via the Triton
     block-scaled kernel (no Cutlass — sm_90+ only), so the operator
     knows the perf class before loading.

DELIBERATE SCOPE LIMIT vs the raw PR (iron-rule #10): PN518 does NOT
rewrite ``get_quant_method`` to construct an ``Fp8Config`` and return
``Fp8LinearMethod`` for detected layers. That full re-route is the risky
part — it touches the exact hot dispatch path the live 27B auto-round
load uses. The diagnostic detect-and-WARN is the LOW-RISK trap-closer
the design specifies: it makes the failure mode LOUD and DIAGNOSED rather
than silent, without ever altering the live dispatch. When a hybrid
INT4+FP8 checkpoint actually enters rotation, the operator flips PN518 on,
sees the WARN, and the full Fp8 routing (PN518B, or upstream #46322 once
merged) is wired with a real model to validate against.

Self-skip / safety
==================

  * SELF-SKIPS if the running pin's ``INCConfig`` already defines a
    native ``maybe_update_config`` (the post-#46322 merged form) — the
    anchor's get_quant_method def is still present but the merged form
    carries a ``def maybe_update_config`` above it, detected as a drift
    marker → patcher skips, file untouched.
  * Default-OFF (``GENESIS_ENABLE_PN518_INC_HYBRID_FP8_DETECT``),
    dispatcher-gated, ``applies_to.vllm_version_range`` (">=0.23.0",
    "<0.24.0") — the base-no-op ``maybe_update_config`` only exists on
    pins predating the native fix.
  * Idempotent via marker; the patched inc.py still compiles.

Anchor: the ``apply_vllm_mapper`` → ``get_quant_method`` boundary in
``model_executor/layers/quantization/inc/inc.py``, byte-unique (count==1)
on dev424 pristine.

Author backport: Genesis upstream sweep 2026-06-25.
Vendor target: vllm-project/vllm#46322 (open as of 2026-06-25), LATENT.
"""
from __future__ import annotations

import logging
import os

from sndr.engines.vllm.detection.guards import resolve_vllm_file
from sndr.kernel import (
    TextPatch,
    TextPatcher,
    TextPatchResult,
)

log = logging.getLogger("genesis.wiring.pn518_inc_hybrid_fp8_detect")


GENESIS_PN518_MARKER = (
    "Genesis PN518 INCConfig hybrid INT4+FP8 AutoRound detect "
    "(vendor of vllm#46322, latent) v1"
)


# FP8 dtype tokens as they appear in a safetensors header's "dtype"
# field. safetensors uses "F8_E4M3"; HF/torch metadata may also surface
# "float8_e4m3fn". Match either, case-insensitively.
_FP8_DTYPE_TOKENS = ("f8_e4m3", "float8_e4m3")


def _detect_fp8_layers_from_metadata(metadata: dict) -> list[str]:
    """Return the list of weight prefixes that are block-scaled FP8.

    Pure function (no torch, no I/O) — the FP8-detection core of the
    injected ``maybe_update_config``, exposed at module level so it is
    unit-testable without a real checkpoint.

    A layer is a block-scaled FP8 layer (the vllm#46322 signature) when:
      * a key ``<prefix>.weight`` has an FP8 dtype (float8_e4m3fn), AND
      * a sibling key ``<prefix>.weight_scale_inv`` is present.

    A bare FP8 weight with no ``weight_scale_inv`` is NOT flagged (it is
    not the block-scaled scheme #46322 routes). Genuinely-unquantized
    bits=16 ``fp`` projections (the 27B's linear_attn.in_proj_{a,b}) have
    BF16/F16 dtype → never match.
    """
    if not isinstance(metadata, dict):
        return []
    keys = set(metadata.keys())
    fp8_prefixes: list[str] = []
    for key, info in metadata.items():
        if not key.endswith(".weight"):
            continue
        dtype = ""
        if isinstance(info, dict):
            dtype = str(info.get("dtype", "")).lower()
        if not any(tok in dtype for tok in _FP8_DTYPE_TOKENS):
            continue
        prefix = key[: -len(".weight")]
        if f"{prefix}.weight_scale_inv" in keys:
            fp8_prefixes.append(prefix)
    return fp8_prefixes


# ── Text patch: inject maybe_update_config onto INCConfig ────────────
#
# The anchor is the tail of apply_vllm_mapper + the get_quant_method def
# line (byte-unique on dev424). The replacement re-emits that boundary
# verbatim with a maybe_update_config method PREPENDED before
# get_quant_method — so get_quant_method's body is byte-identical and the
# live 27B dispatch is unperturbed.
PN518_ANCHOR = (
    "        if self.extra_config is not None:\n"
    "            self.extra_config = hf_to_vllm_mapper.apply_dict(self.extra_config)\n"
    "\n"
    "    def get_quant_method(self, layer: torch.nn.Module, prefix: str):\n"
)

_FP8_TOKENS_LITERAL = repr(_FP8_DTYPE_TOKENS)

# The injected method is FULLY SELF-CONTAINED (inline metadata read +
# inline FP8 detection) so the patched inc.py needs no module-tail
# helpers and no sndr import at runtime. get_quant_method's def line is
# re-emitted verbatim below the new method -> its body is byte-identical
# -> the live 27B dispatch is unperturbed.
PN518_REPLACE = (
    "        if self.extra_config is not None:\n"
    "            self.extra_config = hf_to_vllm_mapper.apply_dict(self.extra_config)\n"
    "\n"
    "    # [Genesis PN518 vendor of vllm#46322 -- latent INT4+FP8 detect] dev424\n"
    "    # INCConfig is MISSING maybe_update_config (inherits the base no-op), so a\n"
    "    # hybrid INT4+FP8 auto-round checkpoint's FP8 attention/shared-expert\n"
    "    # layers would be SILENTLY treated as unquantized -> garbage. This\n"
    "    # diagnostic guard detects such layers and emits a LOUD boot WARN instead\n"
    "    # of silent corruption. STRICT NO-OP when no FP8 layers are present (the\n"
    "    # live 27B keeps linear_attn.in_proj_{a,b} at bits=16 = unquantized, NOT\n"
    "    # fp8; the 35B is quant_method=fp8 not inc) -> get_quant_method is never\n"
    "    # touched and the live dispatch is byte-for-byte unchanged.\n"
    "    def maybe_update_config(self, model_name, hf_config=None, revision=None):\n"
    "        import json as _g_json\n"
    "        import logging as _g_logging\n"
    "        import os as _g_os\n"
    "        import struct as _g_struct\n"
    "\n"
    '        _g_log = _g_logging.getLogger("genesis.runtime.pn518_inc_fp8_detect")\n'
    "        _g_fp8_tokens = " + _FP8_TOKENS_LITERAL + "\n"
    "        try:\n"
    "            _g_meta = {}\n"
    "            if model_name and _g_os.path.isdir(model_name):\n"
    "                for _g_fn in sorted(_g_os.listdir(model_name)):\n"
    '                    if not _g_fn.endswith(".safetensors"):\n'
    "                        continue\n"
    "                    try:\n"
    '                        with open(_g_os.path.join(model_name, _g_fn), "rb") as _g_fh:\n'
    "                            _g_hlen = _g_struct.unpack('<Q', _g_fh.read(8))[0]\n"
    "                            _g_hdr = _g_json.loads(_g_fh.read(_g_hlen))\n"
    "                    except Exception:\n"
    "                        continue\n"
    "                    for _g_tn, _g_ti in _g_hdr.items():\n"
    '                        if _g_tn == "__metadata__" or not isinstance(_g_ti, dict):\n'
    "                            continue\n"
    '                        _g_meta[_g_tn] = str(_g_ti.get("dtype", ""))\n'
    "            _g_keys = set(_g_meta)\n"
    "            _g_fp8 = []\n"
    "            for _g_k, _g_dt in _g_meta.items():\n"
    '                if not _g_k.endswith(".weight"):\n'
    "                    continue\n"
    "                if not any(_g_t in _g_dt.lower() for _g_t in _g_fp8_tokens):\n"
    "                    continue\n"
    '                _g_pref = _g_k[: -len(".weight")]\n'
    '                if _g_pref + ".weight_scale_inv" in _g_keys:\n'
    "                    _g_fp8.append(_g_pref)\n"
    "        except Exception as _g_e:  # never block model load on a scan error\n"
    '            _g_log.debug("[Genesis PN518] FP8 scan skipped (%r) -- no-op", _g_e)\n'
    "            return\n"
    "        if not _g_fp8:\n"
    "            # No block-scaled FP8 layers -> strict no-op (the live 27B/35B\n"
    "            # path). Do NOT perturb get_quant_method.\n"
    "            return\n"
    "        _g_log.warning(\n"
    '            "[Genesis PN518] DETECTED %d block-scaled FP8 layer(s) in an "\n'
    '            "auto-round checkpoint (e.g. %s) but this vLLM pin lacks a native "\n'
    '            "INCConfig.maybe_update_config (vllm#46322 not merged). These FP8 "\n'
    '            "attention/shared-expert layers will be served as UNQUANTIZED -> "\n'
    '            "GARBAGE output. Enable upstream #46322 / Genesis full FP8 routing, "\n'
    '            "or do not load a hybrid INT4+FP8 auto-round checkpoint on this pin.",\n'
    "            len(_g_fp8),\n"
    '            ", ".join(_g_fp8[:3]),\n'
    "        )\n"
    "        try:\n"
    "            import torch as _g_torch\n"
    "            if _g_torch.cuda.is_available():\n"
    "                _g_cap = _g_torch.cuda.get_device_capability()\n"
    "                if _g_cap < (9, 0):\n"
    "                    _g_log.info(\n"
    '                        "[Genesis PN518] sm_%d%d: FP8 execution would dispatch "\n'
    '                        "via the Triton block-scaled kernel (no Cutlass block-FP8 "\n'
    '                        "below sm_90).",\n'
    "                        _g_cap[0], _g_cap[1],\n"
    "                    )\n"
    "        except Exception:  # arch note is best-effort only\n"
    "            pass\n"
    "\n"
    "    def get_quant_method(self, layer: torch.nn.Module, prefix: str):\n"
)


def _make_patcher() -> TextPatcher | None:
    target = resolve_vllm_file("model_executor/layers/quantization/inc/inc.py")
    if target is None:
        return None
    return TextPatcher(
        patch_name=(
            "PN518 inc/inc.py — INCConfig.maybe_update_config hybrid "
            "INT4+FP8 detect-and-WARN guard (vendor of vllm#46322, latent)"
        ),
        target_file=str(target),
        marker=GENESIS_PN518_MARKER,
        sub_patches=[
            TextPatch(
                name="pn518_inject_maybe_update_config",
                anchor=PN518_ANCHOR,
                replacement=PN518_REPLACE,
                required=True,
            ),
        ],
        upstream_drift_markers=[
            "[Genesis PN518",
            # Post-#46322 merged form: INCConfig already defines the
            # method natively -> our injection is obsolete, skip cleanly.
            "    def maybe_update_config(self",
        ],
    )


def apply() -> tuple[str, str]:
    """Apply PN518 — inject the INCConfig FP8 detect-and-WARN guard."""
    from sndr.dispatcher import log_decision, should_apply

    decision, reason = should_apply("PN518")
    log_decision("PN518", decision, reason)
    if not decision:
        return "skipped", reason

    patcher = _make_patcher()
    if patcher is None:
        return "skipped", "inc/inc.py not found (no INC quantization build)"
    if not os.path.isfile(patcher.target_file):
        return "skipped", f"target disappeared: {patcher.target_file}"

    # Standard TextPatcher path: Layer 2 marker idempotency, Layer 3
    # upstream-drift self-skip (native maybe_update_config -> obsolete),
    # required-anchor splice + marker prepend. The injected method is
    # fully self-contained (inline metadata read + FP8 detection) so no
    # module-tail helpers / no sndr import at runtime are needed.
    result, failure = patcher.apply()

    if result == TextPatchResult.IDEMPOTENT:
        return "applied", "PN518 already applied (idempotent)"
    if result == TextPatchResult.SKIPPED:
        reason = failure.reason if failure else "anchor drift / not eligible"
        detail = f" ({failure.detail})" if (failure and failure.detail) else ""
        return "skipped", f"PN518: {reason}{detail}"
    if result == TextPatchResult.FAILED:
        return "failed", (
            f"PN518: {failure.reason if failure else 'unknown'} "
            f"({failure.detail if failure else ''})"
        )

    # APPLIED — defensively verify the patched file still compiles.
    try:
        with open(patcher.target_file) as f:
            compile(f.read(), patcher.target_file, "exec")
    except SyntaxError as e:
        return "failed", f"PN518 produced invalid Python: {e!r}"

    return (
        "applied",
        "PN518 applied: INCConfig.maybe_update_config injected — scans "
        "safetensors metadata for block-scaled FP8 layers on auto-round "
        "checkpoints and emits a loud boot WARN (+ sm_86 Triton-fallback INFO) "
        "if any are found on a pin lacking native FP8 routing. STRICT NO-OP "
        "when no FP8 layers present (the live 27B/35B path) — get_quant_method "
        "untouched. Latent trap-closer for hybrid INT4+FP8 (vllm#46322).",
    )


def is_applied() -> bool:
    patcher = _make_patcher()
    if patcher is None:
        return False
    try:
        with open(patcher.target_file) as f:
            return GENESIS_PN518_MARKER in f.read()
    except Exception:
        return False


def revert() -> tuple[str, str]:
    return (
        "skipped",
        "PN518 text-patch revert not supported in-place; redeploy a fresh "
        "container or `git checkout` inc/inc.py",
    )
