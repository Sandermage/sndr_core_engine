# SPDX-License-Identifier: Apache-2.0
"""Wiring for Patch N517 — take the init MemorySnapshot before NCCL.

================================================================
Issue
================================================================

`Worker.init_device` takes its baseline `MemorySnapshot` *after*
`init_worker_distributed_environment` (NCCL init). On an asymmetric
TP+PP topology the per-rank NCCL workspace is uneven — a PP-terminal
rank can carry ~8-9 GiB while rank 0 carries ~1-2 GiB. Measuring free
memory after NCCL means `gpu_memory_utilization` is computed against
*post-NCCL* free, so the NCCL cost is silently pushed outside the GMU
budget and the heaviest rank OOMs on init.

vllm#45517 (RFC #34303) adds an opt-in env
`VLLM_INIT_SNAPSHOT_BEFORE_NCCL`: snapshot immediately after
`set_device_index` (before NCCL), and reuse it as `self.init_snapshot`.
It also stashes the pre-NCCL free bytes for startup observability.
Default-off; the homogeneous-GPU path is unchanged.

================================================================
Value on the Genesis fleet
================================================================

Our PROD is TP=2 PP=1 — symmetric, no PP-terminal asymmetry — so the
VRAM *guard* is dormant here. The live value is OBSERVABILITY: a
`_startup_free_bytes` reading taken before NCCL allocates, logged at
init, which makes "where did my VRAM go between boot and KV alloc"
answerable. The OOM guard future-proofs any PP>1 config an operator
brings up (e.g. a 4-card 70B split across the A5000 pair + a borrowed
card). Recipe E/G: no SM gate; this is host-side memory accounting,
identical on Ampere/Ada/Hopper/Blackwell.

================================================================
Design (how this improves on a verbatim upstream copy)
================================================================

- The inserted code reads `VLLM_INIT_SNAPSHOT_BEFORE_NCCL` from
  `os.environ` directly, NOT from `vllm.envs` — the pin may not declare
  that env yet, and a `vllm.envs.VLLM_INIT_SNAPSHOT_BEFORE_NCCL`
  reference would AttributeError at import on an un-merged pin.
- Two gates compose cleanly: the Genesis dispatcher decides whether to
  INSTALL the patch (`GENESIS_ENABLE_PN517_INIT_SNAPSHOT_BEFORE_NCCL`);
  the upstream-compatible runtime env decides whether the pre-NCCL
  branch FIRES. So a launch config that already sets
  `VLLM_INIT_SNAPSHOT_BEFORE_NCCL=1` behaves identically before and
  after a future upstream merge.
- Identity guard `is not None` (never a truthiness test on the snapshot
  object) — avoids the PN96b-class "ambiguous truth value" trap.
- Both edits `required=True` in one TextPatcher → atomic: a half-applied
  state (pre-NCCL snapshot taken but never consumed, or the consume site
  referencing an undefined attribute) can never be written.

================================================================
PIN STATE (verified 2026-06-14)
================================================================

The `init_device` region is byte-identical on dev259 (PROD,
303916e93) and dev491 (candidate, 1033ffac2) — one anchor set covers
both. #45517 had not merged into either nightly. Self-skips
(required_anchor_missing) when a future pin merges it.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
Backport: vllm#45517 (RFC #34303), full credit to the upstream author.
"""
from __future__ import annotations

from sndr.engines.vllm.detection.guards import resolve_vllm_file, vllm_install_root
from sndr.kernel import (
    TextPatch,
    TextPatcher,
    TextPatchResult,
    result_to_wiring_status,
)

GENESIS_PN517_MARKER = (
    "Genesis PN517 init MemorySnapshot before NCCL (vllm#45517)"
)


# ─── Sub-patch 1: take the pre-NCCL snapshot (env-gated at runtime) ──

PN517_PART1_ANCHOR = (
    "            current_platform.check_if_supports_dtype(self.model_config.dtype)\n"
    "\n"
    "            # Initialize the distributed environment BEFORE taking\n"
    "            # memory snapshot\n"
    "            # This ensures NCCL buffers are allocated before we measure\n"
    "            # available memory\n"
)

PN517_PART1_REPLACEMENT = (
    "            current_platform.check_if_supports_dtype(self.model_config.dtype)\n"
    "\n"
    "            # [Genesis PN517 init_snapshot_before_nccl] vllm#45517 — on\n"
    "            # asymmetric TP+PP the PP-terminal rank carries far more NCCL\n"
    "            # workspace; snapshotting free memory AFTER NCCL pushes that\n"
    "            # cost outside the gpu_memory_utilization budget and OOMs the\n"
    "            # heaviest rank on init. When VLLM_INIT_SNAPSHOT_BEFORE_NCCL is\n"
    "            # set, snapshot here (pre-NCCL) and reuse it below; always\n"
    "            # stash pre-NCCL free bytes for startup observability. The\n"
    "            # os.environ read avoids a hard dependency on a vllm.envs entry\n"
    "            # this pin may lack.\n"
    "            self._genesis_pn517_snapshot = None\n"
    "            self._startup_free_bytes = None\n"
    '            if os.environ.get("VLLM_INIT_SNAPSHOT_BEFORE_NCCL", "0") in ("1", "true", "True"):\n'
    "                self._genesis_pn517_snapshot = MemorySnapshot(device=self.device)\n"
    "                self._startup_free_bytes = self._genesis_pn517_snapshot.free_memory\n"
    "                logger.info(\n"
    '                    "[Genesis PN517] pre-NCCL free memory: %s",\n'
    "                    format_gib(self._startup_free_bytes),\n"
    "                )\n"
    "\n"
    "            # Initialize the distributed environment BEFORE taking\n"
    "            # memory snapshot\n"
    "            # This ensures NCCL buffers are allocated before we measure\n"
    "            # available memory\n"
)


# ─── Sub-patch 2: reuse the pre-NCCL snapshot when present ───────────

PN517_PART2_ANCHOR = (
    "            # take current memory snapshot\n"
    "            self.init_snapshot = init_snapshot = MemorySnapshot(device=self.device)\n"
)

PN517_PART2_REPLACEMENT = (
    "            # take current memory snapshot\n"
    "            # [Genesis PN517] reuse the pre-NCCL snapshot when it was taken\n"
    "            # (VLLM_INIT_SNAPSHOT_BEFORE_NCCL) so gpu_memory_utilization is\n"
    "            # computed against free memory BEFORE NCCL workspace alloc.\n"
    "            if getattr(self, \"_genesis_pn517_snapshot\", None) is not None:\n"
    "                self.init_snapshot = init_snapshot = self._genesis_pn517_snapshot\n"
    "            else:\n"
    "                self.init_snapshot = init_snapshot = MemorySnapshot(device=self.device)\n"
)


def _make_patcher() -> TextPatcher | None:
    target = resolve_vllm_file("v1/worker/gpu_worker.py")
    if target is None:
        return None
    return TextPatcher(
        patch_name=(
            "PN517 v1/worker/gpu_worker.py — take init MemorySnapshot before "
            "NCCL (vllm#45517)"
        ),
        target_file=str(target),
        marker=GENESIS_PN517_MARKER,
        sub_patches=[
            TextPatch(
                name="pN517_pre_nccl_snapshot",
                anchor=PN517_PART1_ANCHOR,
                replacement=PN517_PART1_REPLACEMENT,
                required=True,
            ),
            TextPatch(
                name="pN517_reuse_snapshot_at_init",
                anchor=PN517_PART2_ANCHOR,
                replacement=PN517_PART2_REPLACEMENT,
                required=True,
            ),
        ],
        upstream_drift_markers=[],
        patch_id="PN517",
    )


def apply() -> tuple[str, str]:
    """Apply PN517 — pre-NCCL init MemorySnapshot + startup observability.

    Single-file, two-sub-patch TextPatcher (both ``required=True`` →
    atomic). Never raises. Returns (status, reason).
    """
    from sndr.dispatcher import log_decision, should_apply

    decision, reason = should_apply("PN517")
    log_decision("PN517", decision, reason)
    if not decision:
        return "skipped", reason

    if vllm_install_root() is None:
        return "skipped", "vllm install root not discoverable"

    patcher = _make_patcher()
    if patcher is None:
        return "skipped", (
            "target v1/worker/gpu_worker.py not resolvable — vllm tree may "
            "differ from expected layout"
        )

    result, failure = patcher.apply()
    return result_to_wiring_status(
        result,
        failure,
        applied_message=(
            "PN517 applied: Worker.init_device now stashes pre-NCCL free "
            "memory in self._startup_free_bytes for startup observability, "
            "and — when VLLM_INIT_SNAPSHOT_BEFORE_NCCL=1 — reuses the "
            "pre-NCCL snapshot so gpu_memory_utilization is budgeted against "
            "free memory before NCCL workspace allocation (asymmetric TP+PP "
            "OOM guard). Default-off branch: homogeneous-GPU path unchanged. "
            "Host-side accounting — arch-neutral."
        ),
        patch_name="PN517 init MemorySnapshot before NCCL",
    )


# ════════════════════════════════════════════════════════════════════════
# Build-time manifest registration (P2.1 Site Map)
# ════════════════════════════════════════════════════════════════════════


def register_for_manifest(*, pristine_root) -> None:
    """Register PN517's sub-patches into the Site Map registry using the
    pristine ``gpu_worker.py`` fixture under ``pristine_root``."""
    from sndr.engines.vllm.wiring.patcher_registry import register_text_patcher

    register_text_patcher(
        "PN517",
        TextPatcher(
            patch_name="PN517 gpu_worker.py (build mode)",
            target_file=str(pristine_root / "gpu_worker.py"),
            marker=GENESIS_PN517_MARKER,
            sub_patches=[
                TextPatch(
                    name="pN517_pre_nccl_snapshot",
                    anchor=PN517_PART1_ANCHOR,
                    replacement=PN517_PART1_REPLACEMENT,
                    required=True,
                ),
                TextPatch(
                    name="pN517_reuse_snapshot_at_init",
                    anchor=PN517_PART2_ANCHOR,
                    replacement=PN517_PART2_REPLACEMENT,
                    required=True,
                ),
            ],
            upstream_drift_markers=[],
            patch_id="PN517",
        ),
    )
