# SPDX-License-Identifier: Apache-2.0
"""PN105 — revert JIT monitor + add missing V1 warmup paths.

Problem
-------
PR #40137 added a Triton JIT compilation monitor that WARNING-logs any
kernel compilation after warmup. This is purely diagnostic but surfaces
legitimate missing warmup in V1 that cause 2+ min latency spikes on first
request (and deadlocks with DP>1 where concurrent compilation contends).

Missing warmup paths (upstream issues #43009, #41865, #39287):
  - _zero_kv_blocks_kernel
  - _compute_slot_mapping_kernel
  - _copy_page_indices_kernel

Fix
---
1. Remove the JIT monitor activation (revert #40137) — ends the noise
2. Add do_not_specialize=["num_tokens"] on slot mapping kernel (#42165)
3. Warm up V1 slot mapping kernel before JIT monitor
4. Warm up KV-zero kernel before JIT monitor
"""
from __future__ import annotations

import logging

from vllm._genesis.guards import resolve_vllm_file
from vllm._genesis.wiring.text_patch import (
    TextPatch,
    TextPatcher,
    MultiFilePatchTransaction,
    result_to_wiring_status,
)

log = logging.getLogger("genesis.wiring.fix_jit_warmup")

GENESIS_MARKER = "Genesis PN105 fix JIT warmup v2"


def _make_gpu_worker_patcher():
    target = resolve_vllm_file("v1/worker/gpu_worker.py")
    if target is None:
        return None
    return TextPatcher(
        patch_name="PN105 gpu_worker",
        target_file=str(target),
        marker=GENESIS_MARKER,
        sub_patches=[
            # Remove JIT monitor activation (revert PR #40137)
            TextPatch(
                name="remove_jit_monitor",
                anchor=(
                    "        # All warmup is done \u2014 start monitoring for unexpected JIT\n"
                    '        # compilations that would cause latency spikes during inference.\n'
                    "        from vllm.triton_utils.jit_monitor import (\n"
                    "            activate as activate_triton_jit_monitor,\n"
                    "        )\n"
                    "\n"
                    "        activate_triton_jit_monitor()\n"
                ),
                replacement="",
                required=True,
            ),
            # Add warmup_v1_slot_mapping_kernel import
            TextPatch(
                name="add_warmup_import",
                anchor="from .gpu.warmup import warmup_kernels",
                replacement="from .gpu.warmup import warmup_kernels, warmup_v1_slot_mapping_kernel",
                required=True,
            ),
            # Restructure elif to else and add warmup call
            TextPatch(
                name="add_warmup_call",
                anchor=(
                    "        elif get_pp_group().is_last_rank:\n"
                    "            # V1: Warm up sampler and preallocate memory buffer"
                ),
                replacement=(
                    "        else:\n"
                    "            # PN105: V1 warmup slot mapping kernel (not covered by _dummy_run)\n"
                    "            warmup_v1_slot_mapping_kernel(self.model_runner)\n"
                    "\n"
                    "        if not self.use_v2_model_runner and get_pp_group().is_last_rank:\n"
                    "            # V1: Warm up sampler and preallocate memory buffer"
                ),
                required=True,
            ),
        ],
        upstream_drift_markers=[
            "PN105",
        ],
    )


def _make_block_table_patcher():
    target = resolve_vllm_file("v1/worker/block_table.py")
    if target is None:
        return None
    return TextPatcher(
        patch_name="PN105 block_table",
        target_file=str(target),
        marker=GENESIS_MARKER,
        sub_patches=[
            # Add do_not_specialize=["num_tokens"] to slot mapping kernel
            TextPatch(
                name="do_not_specialize",
                anchor="@triton.jit\ndef _compute_slot_mapping_kernel(",
                replacement="@triton.jit(do_not_specialize=[\"num_tokens\"])\ndef _compute_slot_mapping_kernel(",
                required=True,
            ),
        ],
        upstream_drift_markers=[
            "PN105",
        ],
    )


def _make_warmup_py_patcher():
    target = resolve_vllm_file("v1/worker/gpu/warmup.py")
    if target is None:
        return None
    return TextPatcher(
        patch_name="PN105 warmup.py",
        target_file=str(target),
        marker=GENESIS_MARKER,
        sub_patches=[
            # Append warmup_v1_slot_mapping_kernel after last torch.accelerator.synchronize()
            TextPatch(
                name="add_slot_mapping_warmup_fn",
                anchor=(
                    "    torch.accelerator.synchronize()\n"
                    "\n"
                    "\n"
                    "def warmup_kernels"
                ),
                replacement=(
                    "    torch.accelerator.synchronize()\n"
                    "\n"
                    "\n"
                    "@torch.inference_mode()\n"
                    "def warmup_v1_slot_mapping_kernel(model_runner: Any) -> None:\n"
                    '    """Warm up V1 slot mapping kernel before JIT monitor activates.\n'
                    "\n"
                    "    V1 request input preparation calls BlockTable.compute_slot_mapping().\n"
                    "    The legacy _dummy_run() path does not exercise this kernel.\n"
                    '    """\n'
                    "    block_table = model_runner.input_batch.block_table\n"
                    "    if not block_table.block_tables:\n"
                    "        return\n"
                    "    if model_runner.kv_cache_config.num_blocks <= 1:\n"
                    "        return\n"
                    "    device = model_runner.device\n"
                    "    block_table.add_row(tuple([1] for _ in block_table.block_tables), 0)\n"
                    "    block_table.commit_block_table(1)\n"
                    '    query_start_loc = torch.tensor([0, 1], dtype=torch.int32, device=device)\n'
                    '    positions = torch.zeros(1, dtype=torch.int64, device=device)\n'
                    "    try:\n"
                    "        block_table.compute_slot_mapping(1, query_start_loc, positions)\n"
                    "        torch.accelerator.synchronize()\n"
                    "    finally:\n"
                    "        block_table.clear_row(0)\n"
                    "        block_table.commit_block_table(1)\n"
                    "\n"
                    "\n"
                    "def warmup_kernels"
                ),
                required=True,
            ),
        ],
        upstream_drift_markers=[
            "PN105",
        ],
    )


def _make_kernel_warmup_patcher():
    """Add KV-zero warmup to model_executor/warmup/kernel_warmup.py."""
    target = resolve_vllm_file("model_executor/warmup/kernel_warmup.py")
    if target is None:
        return None
    return TextPatcher(
        patch_name="PN105 kernel_warmup",
        target_file=str(target),
        marker=GENESIS_MARKER,
        sub_patches=[
            # Add _warmup_zero_kv_blocks function
            TextPatch(
                name="add_kv_zero_warmup_fn",
                anchor=(
                    "def kernel_warmup(worker: \"Worker\"):"
                ),
                replacement=(
                    "def _warmup_zero_kv_blocks(worker: \"Worker\") -> None:\n"
                    '    """Warm up the Triton KV-zeroing kernel."""\n'
                    "    runner = worker.model_runner\n"
                    "    if not hasattr(runner, \"_kv_block_zeroer\"):\n"
                    "        return\n"
                    "    try:\n"
                    "        with torch.inference_mode():\n"
                    "            runner._zero_block_ids([0])\n"
                    "    except Exception:\n"
                    "        pass\n"
                    "\n"
                    "\n"
                    "def kernel_warmup(worker: \"Worker\"):"
                ),
                required=True,
            ),
            # Add call to _warmup_zero_kv_blocks at end of kernel_warmup
            TextPatch(
                name="add_kv_zero_warmup_call",
                anchor=(
                    "        create_mixed_batch=True,\n"
                    "        )\n"
                ),
                replacement=(
                    "        create_mixed_batch=True,\n"
                    "        )\n"
                    "\n"
                    "    _warmup_zero_kv_blocks(worker)\n"
                ),
                required=True,
            ),
        ],
        upstream_drift_markers=[
            "PN105",
        ],
    )


def apply():
    """Apply all PN105 patches atomically."""
    patchers = [
        _make_gpu_worker_patcher(),
        _make_block_table_patcher(),
        _make_warmup_py_patcher(),
        _make_kernel_warmup_patcher(),
    ]

    patchers = [p for p in patchers if p is not None]
    if not patchers:
        return "skipped", "PN105: no target files found"

    txn = MultiFilePatchTransaction(patchers, name="PN105 fix JIT warmup")
    status, reason = txn.apply_or_skip()

    if status == "applied":
        return "applied", (
            "PN105: removed JIT monitor activation, added do_not_specialize "
            "on slot mapping kernel, warmed up V1 slot mapping + KV-zero kernels"
        )

    if status == "skipped":
        # If skipped because already applied (marker present), return applied
        for p in patchers:
            try:
                with open(p.target_file) as f:
                    if GENESIS_MARKER in f.read():
                        return "applied", "PN105: already applied"
            except Exception:
                pass
        return "skipped", f"PN105: {reason}"

    return "failed", f"PN105: {reason}"
