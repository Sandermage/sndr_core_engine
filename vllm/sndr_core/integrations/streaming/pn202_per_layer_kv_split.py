# SPDX-License-Identifier: Apache-2.0
"""PN202 — per-layer KV tensor split (Tier 2.A enabler).

vllm's Branch-C allocation in `kv_cache_utils.py::get_kv_cache_config_from_groups`
emits `group_size` slabs, each shared by one representative layer from
every kv_cache_group. For Qwen3-Next hybrid (16 full-attn + 48 GDN):
group_size=48, 48 physical slabs, each shared by 1-2 layer names.

This sharing **blocks per-layer memory policies** (offload single
layer, evict single layer, quantize single layer differently). The
fix is mechanically trivial: emit one KVCacheTensor per layer with
shared_by=[layer_name], identical to Branch-A behavior. Total bytes
allocated is unchanged (page_size × num_blocks × num_layers either
way) — what changes is **granularity of memory operations**.

This is the Tier-2.A ENABLER for Tier-3 cold-prefix CPU offload
(PN203). Without per-layer split, demoting a single attention layer's
KV requires demoting the shared slab (which also holds Mamba state
for an unrelated layer). Per-layer split lets PN203 demote full-attn
layer N's bytes independently while keeping GDN layer N+1's state
GPU-resident.

Quality / speed impact: **zero**. The math is identical, the tensor
views downstream are identical (see Part 7 in PHASE_7_DESIGN doc).
Only the layout of `kv_cache_raw_tensors` changes from 48 distinct
keys → 65 distinct keys (one per layer); attention forward reads
its layer's tensor via `kv_caches[layer_name]` which is keyed by
layer_name anyway. `_update_hybrid_attention_mamba_layout` uses
`as_strided` on per-tensor storage — that works identically with
per-layer slabs since each slab's storage is contiguous.

Env gate: `GENESIS_ENABLE_PN202_PER_LAYER_KV_SPLIT=1` (default OFF).
"""
from __future__ import annotations

import logging
import os

from vllm.sndr_core.detection.guards import resolve_vllm_file, vllm_install_root
from vllm.sndr_core.core import TextPatch, TextPatcher

log = logging.getLogger("genesis.wiring.pn202_per_layer_kv_split")

GENESIS_MARKER = "Genesis PN202 per-layer KV tensor split"


def _enabled() -> bool:
    return os.environ.get(
        "GENESIS_ENABLE_PN202_PER_LAYER_KV_SPLIT", "0",
    ).strip().lower() in ("1", "true", "yes", "on")


# Anchor verified on vllm nightly dcacdf9a (2026-05-14).
# kv_cache_utils.py:~1303 — Branch C construction of kv_cache_tensors.
PN202_OLD = (
    "        kv_cache_tensors = []\n"
    "        for i in range(group_size):\n"
    "            shared_by = []\n"
    "            for j in range(len(kv_cache_groups)):\n"
    "                if i < len(kv_cache_groups[j].layer_names):\n"
    "                    shared_by.append(kv_cache_groups[j].layer_names[i])\n"
    "            kv_cache_tensors.append(\n"
    "                KVCacheTensor(size=page_size * num_blocks, shared_by=shared_by)\n"
    "            )\n"
)
PN202_NEW = (
    "        # [Genesis PN202] per-layer KV tensor split. Replaces Branch-C\n"
    "        # 'shared by representative layer of each group' with Branch-A\n"
    "        # semantics 'one tensor per layer'. Net bytes identical;\n"
    "        # enables per-layer policies (offload/evict/quantize) required\n"
    "        # by PN203 Tier-3 cold-prefix CPU offload.\n"
    "        kv_cache_tensors = []\n"
    "        import os as _g_pn202_os\n"
    "        _g_pn202_on = _g_pn202_os.environ.get(\n"
    "            \"GENESIS_ENABLE_PN202_PER_LAYER_KV_SPLIT\", \"0\",\n"
    "        ).strip().lower() in (\"1\", \"true\", \"yes\", \"on\")\n"
    "        if _g_pn202_on:\n"
    "            for group in kv_cache_groups:\n"
    "                for layer_name in group.layer_names:\n"
    "                    kv_cache_tensors.append(\n"
    "                        KVCacheTensor(\n"
    "                            size=page_size * num_blocks,\n"
    "                            shared_by=[layer_name],\n"
    "                        )\n"
    "                    )\n"
    "        else:\n"
    "            for i in range(group_size):\n"
    "                shared_by = []\n"
    "                for j in range(len(kv_cache_groups)):\n"
    "                    if i < len(kv_cache_groups[j].layer_names):\n"
    "                        shared_by.append(kv_cache_groups[j].layer_names[i])\n"
    "                kv_cache_tensors.append(\n"
    "                    KVCacheTensor(size=page_size * num_blocks, shared_by=shared_by)\n"
    "                )\n"
)


def _make_patcher() -> TextPatcher | None:
    if not _enabled():
        return None
    target = resolve_vllm_file("v1/core/kv_cache_utils.py")
    if target is None:
        return None
    return TextPatcher(
        patch_name="PN202 per-layer KV tensor split",
        target_file=str(target),
        marker=GENESIS_MARKER,
        sub_patches=[
            TextPatch(
                name="pn202_branch_c_per_layer",
                anchor=PN202_OLD,
                replacement=PN202_NEW,
                required=True,
            ),
        ],
        upstream_drift_markers=[
            "Genesis PN202",
            "per-layer KV tensor split",
        ],
    )


def apply() -> tuple[str, str]:
    if not _enabled():
        return "skipped", "PN202 disabled (set GENESIS_ENABLE_PN202_PER_LAYER_KV_SPLIT=1)"
    if vllm_install_root() is None:
        return "skipped", "vllm install root not discoverable"
    patcher = _make_patcher()
    if patcher is None:
        return "skipped", "target file kv_cache_utils.py not resolvable"
    if not os.path.isfile(patcher.target_file):
        return "skipped", f"target disappeared: {patcher.target_file}"
    with open(patcher.target_file) as fh:
        content = fh.read()
    if patcher.marker in content:
        return "applied", "idempotent (marker present)"
    for m in patcher.upstream_drift_markers:
        if m in content:
            return "skipped", f"drift marker {m!r} already in file"
    result, failure = patcher.apply()
    from vllm.sndr_core.core import result_to_wiring_status
    return result_to_wiring_status(
        result, failure,
        applied_message="PN202 per-layer KV split active — enables Tier-3 per-layer offload",
        patch_name=patcher.patch_name,
    )
