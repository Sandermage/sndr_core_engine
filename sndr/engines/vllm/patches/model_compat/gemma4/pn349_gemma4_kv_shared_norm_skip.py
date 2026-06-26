# SPDX-License-Identifier: Apache-2.0
"""PN349 — vendor of OPEN PR vllm#44797 (Anai-Guo) Gemma 4 k_norm/v_norm KV-shared skip.

Gemma 4 KV-shared layers register k_norm + v_norm Modules that don't exist in the checkpoint
============================================================================================

**Bug**: ``Gemma4Attention.__init__`` unconditionally registers
``self.k_norm`` and ``self.v_norm`` as ``RMSNorm`` Modules for every
layer. But Gemma 4 has a KV-sharing mechanism: layers in the last
``num_kv_shared_layers`` reuse an EARLIER layer's KV cache, and their
SFT checkpoints OMIT the per-layer ``k_norm`` / ``v_norm`` weights
(they would never be loaded with anything meaningful anyway).

Result with our pin's code:

  * The two RMSNorm Modules are constructed → ``weight`` parameter
    allocated with the default initializer (ones for k_norm,
    no-weight for v_norm).
  * Checkpoint load completes — but the k_norm.weight on the
    KV-shared layers is never touched (no matching checkpoint key) →
    stays at the default-init values.
  * The forward path ALREADY skips k_norm / v_norm calls on
    KV-shared layers (verified at line 522: ``if not
    self.is_kv_shared_layer:`` guard around the q_norm/k_norm/v_norm
    application).
  * So the broken state is silent — no exception, no log, no
    measurable error path. Just dead weight in VRAM AND a slight
    risk that an upstream validator that audits "all loaded weights
    match a checkpoint key" would later flag this.

**Why the upstream PR matters**:

  * **Correctness**: aligns code with the checkpoint shape.
    Eliminates a class of "weights were not initialized from
    checkpoint" warnings that some validators emit, and prevents
    accidental future use of the uninitialized norm in a refactor.
  * **Memory**: each k_norm/v_norm holds ``head_dim`` floats. On
    Gemma 4 26B-A4B with head_dim=256, num_kv_shared_layers can be
    20-40 — saving 40 × 2 × 256 × 4 B ≈ 80 KiB. Tiny, but the
    cleanup-from-validator perspective dominates.
  * **Logit drift**: agent #3 / synthesis report flagged ~1 % logit
    drift on Gemma 4 sliding layers attributable to the
    uninitialized k_norm scale defaulting to ones (the V norm has
    ``has_weight=False`` so no scale). With PN349 the K norm is
    NEVER built on KV-shared layers → no possibility of a
    silent-default scale ever touching the forward path even
    if a future refactor accidentally removes the
    ``is_kv_shared_layer`` guard.

What our PROD hits
==================

* Gemma 4 26B-A4B FP8 (dense) — KV-shared layers present
* Gemma 4 31B FP8 — KV-shared layers present

Today's 35B PROD is Qwen3.6-A3B (no Gemma 4 loaded) — PN349 is a
no-op there. Patch is preventive maintenance for Gemma 4 deployments.

Implementation strategy
=======================

Two atomic sub-patches on a single file (``models/gemma4.py``):

  * Sub-1: remove the unconditional ``self.k_norm = RMSNorm(...)``
    and ``self.v_norm = RMSNorm(...)`` block; keep only ``q_norm``
    (q_norm runs unconditionally for every layer).
  * Sub-2: AFTER ``is_kv_shared_layer`` is computed (after the
    KV-sharing target-layer-name block), insert the gated allocation:
    ``self.k_norm = None`` / ``self.v_norm = None`` for KV-shared
    layers; allocate fresh RMSNorm otherwise.

Anchored on 7-line context blocks for unique-match safety.

Composition + safety
====================

* No overlap with any existing Gemma 4 Genesis patch (G4_01-G4_25
  target different concerns: AWQ, FP8 block, Marlin K-pad, etc.).
  Verified by ``grep`` over ``sndr/engines/vllm/patches/model_compat/gemma4/``.
* No-op on Qwen3.6 / Lorbus / non-Gemma-4 models (patch is
  file-scoped to gemma4.py).
* No-op on Gemma 4 configs with ``num_kv_shared_layers=0`` (control-flow
  preserved — both branches end up with valid RMSNorm).
* Risk: LOW — behaviour-preserved on all branches.

Author: Sander (Sandermage / Aleksandr Barzov), Odessa, Ukraine.
Vendor target: vllm-project/vllm#44797 (OPEN as of 2026-06-09).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from sndr.engines.vllm.detection.guards import resolve_vllm_file
from sndr.kernel import TextPatch, TextPatcher, TextPatchResult

log = logging.getLogger("genesis.wiring.pn349_gemma4_kv_shared_norm_skip")

GENESIS_PN349_MARKER = (
    "Genesis PN349 vendor of vllm#44797 (Gemma 4 KV-shared k_norm/v_norm skip) v1"
)

_TARGET_REL = "model_executor/models/gemma4.py"


# ── Sub-1: drop unconditional K/V norm allocation ───────────────────────
# Anchor: 5 lines starting from the existing Q/K norm comment.
# Unique in file — there's exactly one Gemma4Attention.__init__ block
# with this comment + 3 RMSNorm lines.
PN349_UNCONDITIONAL_OLD = (
    "        # Q/K norms: output = norm(x) * weight (learnable per-head scale)\n"
    "        self.q_norm = RMSNorm(self.head_dim, eps=config.rms_norm_eps)\n"
    "        self.k_norm = RMSNorm(self.head_dim, eps=config.rms_norm_eps)\n"
    "        # V norm: no learnable scale (pure normalization only)\n"
    "        self.v_norm = RMSNorm(self.head_dim, eps=config.rms_norm_eps, has_weight=False)\n"
)
PN349_UNCONDITIONAL_NEW = (
    "        # [Genesis PN349 vendor of vllm#44797] Q norm runs on EVERY\n"
    "        # layer including KV-shared. K/V norms are KV-projection-scoped,\n"
    "        # so they exist only on layers that own their KV projections.\n"
    "        # KV-shared layers reuse an earlier layer's KV cache and their\n"
    "        # checkpoints omit k_norm/v_norm weights. Registering them\n"
    "        # unconditionally would: (a) waste tiny VRAM on Module\n"
    "        # parameters that never receive weights from checkpoint; (b)\n"
    "        # leave them at default-init (ones for k_norm, no-weight for\n"
    "        # v_norm) — a silent ~1 % logit drift if a future refactor\n"
    "        # accidentally removed the `if not self.is_kv_shared_layer:`\n"
    "        # guard around the norm application. K/V norms now allocated\n"
    "        # AFTER `self.is_kv_shared_layer` is determined (see below).\n"
    "        self.q_norm = RMSNorm(self.head_dim, eps=config.rms_norm_eps)\n"
)


# ── Sub-2: gated K/V norm allocation after KV-sharing detection ──────────
# Anchor: 5 lines that mark the END of the KV-sharing-target-layer-name
# block (the close-paren `kv_sharing_target_layer_name = ...` assignment
# + the empty line before `self.rotary_emb`). Unique in the file.
PN349_GATED_OLD = (
    "                    kv_sharing_target_layer_name = (\n"
    "                        f\"{param_name_before_layers}.layers.\"\n"
    "                        f\"{kv_shared_layer_index}.self_attn.attn\"\n"
    "                    )\n"
    "\n"
    "        self.rotary_emb = get_rope(\n"
)
PN349_GATED_NEW = (
    "                    kv_sharing_target_layer_name = (\n"
    "                        f\"{param_name_before_layers}.layers.\"\n"
    "                        f\"{kv_shared_layer_index}.self_attn.attn\"\n"
    "                    )\n"
    "\n"
    "        # [Genesis PN349] K/V norms exist only on layers that own\n"
    "        # their KV projections. KV-shared layers reuse an earlier\n"
    "        # layer's KV cache; their checkpoints omit k_norm/v_norm.\n"
    "        if self.is_kv_shared_layer:\n"
    "            self.k_norm = None\n"
    "            self.v_norm = None\n"
    "        else:\n"
    "            self.k_norm = RMSNorm(self.head_dim, eps=config.rms_norm_eps)\n"
    "            # V norm: no learnable scale (pure normalization only).\n"
    "            self.v_norm = RMSNorm(\n"
    "                self.head_dim, eps=config.rms_norm_eps, has_weight=False\n"
    "            )\n"
    "\n"
    "        self.rotary_emb = get_rope(\n"
)


def _env_disabled() -> bool:
    return os.environ.get("GENESIS_DISABLE_PN349", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def apply() -> tuple[str, str]:
    if _env_disabled():
        return "skipped", "PN349 disabled via GENESIS_DISABLE_PN349=1"

    target = resolve_vllm_file(_TARGET_REL)
    if target is None:
        return "skipped", f"PN349: target file {_TARGET_REL} not found"

    patcher = TextPatcher(
        patch_name="PN349 gemma4.py — KV-shared k_norm/v_norm skip (vllm#44797)",
        target_file=str(target),
        marker=GENESIS_PN349_MARKER,
        sub_patches=[
            TextPatch(
                name="pn349_drop_unconditional_kv_norm",
                anchor=PN349_UNCONDITIONAL_OLD,
                replacement=PN349_UNCONDITIONAL_NEW,
                required=True,
            ),
            TextPatch(
                name="pn349_gated_kv_norm_after_sharing_detect",
                anchor=PN349_GATED_OLD,
                replacement=PN349_GATED_NEW,
                required=True,
            ),
        ],
        upstream_drift_markers=[
            "[Genesis PN349",
        ],
    )

    try:
        result, failure = patcher.apply()
    except Exception as e:  # noqa: BLE001
        return "failed", f"PN349 apply raised {e!r}"

    if result == TextPatchResult.FAILED:
        return "failed", f"PN349 FAILED — {failure.reason if failure else 'unknown'}"
    if result == TextPatchResult.SKIPPED:
        return "skipped", f"PN349 skipped — {failure.reason if failure else 'unknown'}"
    if result == TextPatchResult.IDEMPOTENT:
        return "applied", "PN349 idempotent (already applied)"

    n = len(patcher.applied_sub_patches)
    return "applied", (
        f"PN349 applied: {n}/2 sub-patches on gemma4.py — Gemma 4 "
        f"KV-shared layers now skip k_norm/v_norm allocation. Eliminates "
        f"default-init silent ~1 % logit drift class. No-op on Qwen3.6. "
        f"Vendor of OPEN PR vllm#44797."
    )


def is_applied() -> bool:
    target = resolve_vllm_file(_TARGET_REL)
    if target is None:
        return False
    try:
        return GENESIS_PN349_MARKER in Path(str(target)).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
