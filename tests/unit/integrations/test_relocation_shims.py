# SPDX-License-Identifier: Apache-2.0
"""Verify relocation shims keep old import paths working.

Plan reference: sndr_private/planning/audits/RELOCATION_DESIGN_2026-05-21_RU.md §4.6
Created: Phase 3 bucket 1 (2026-05-21) — probes relocation from
integrations/gemma4/ to integrations/spec_decode/probes/.

Shim window: one release. Remove this file together with the shim
files themselves once external imports have migrated.

Invariants enforced:
  1. Old import path still resolves to a module (the shim).
  2. New import path resolves to a module (the real implementation).
  3. Old and new modules expose the same canonical attributes
     (apply, is_applied, should_apply when present) by identity.
  4. For registered patches: registry's apply_module points at the
     NEW path, never at the shim.
"""
from __future__ import annotations

import importlib

import pytest

# (old_path, new_path) — extend as later buckets land.
PROBE_RELOCATIONS = [
    # Bucket 1: probes → spec_decode/probes/
    (
        "vllm.sndr_core.integrations.gemma4.pn241_mtp_trace",
        "vllm.sndr_core.integrations.spec_decode.probes.pn241_mtp_trace",
    ),
    (
        "vllm.sndr_core.integrations.gemma4.pn248_acceptance_trace",
        "vllm.sndr_core.integrations.spec_decode.probes.pn248_acceptance_trace",
    ),
    (
        "vllm.sndr_core.integrations.gemma4.pn258_oracle_acceptance",
        "vllm.sndr_core.integrations.spec_decode.probes.pn258_oracle_acceptance",
    ),
    (
        "vllm.sndr_core.integrations.gemma4.pn262_flash_attn_drafter_trace",
        "vllm.sndr_core.integrations.spec_decode.probes.pn262_flash_attn_drafter_trace",
    ),
    (
        "vllm.sndr_core.integrations.gemma4.pn262b_kv_alloc_trace",
        "vllm.sndr_core.integrations.spec_decode.probes.pn262b_kv_alloc_trace",
    ),
    (
        "vllm.sndr_core.integrations.gemma4.pn266_propose_trace",
        "vllm.sndr_core.integrations.spec_decode.probes.pn266_propose_trace",
    ),
    (
        "vllm.sndr_core.integrations.gemma4.pn267_kv_bridge_trace",
        "vllm.sndr_core.integrations.spec_decode.probes.pn267_kv_bridge_trace",
    ),
    (
        "vllm.sndr_core.integrations.gemma4.pn268_drafter_blocks_origin",
        "vllm.sndr_core.integrations.spec_decode.probes.pn268_drafter_blocks_origin",
    ),
    (
        "vllm.sndr_core.integrations.gemma4.pn269_a0_block_table_trace",
        "vllm.sndr_core.integrations.spec_decode.probes.pn269_a0_block_table_trace",
    ),
    (
        "vllm.sndr_core.integrations.gemma4.pn270_drafter_kv_proj_audit",
        "vllm.sndr_core.integrations.spec_decode.probes.pn270_drafter_kv_proj_audit",
    ),
    (
        "vllm.sndr_core.integrations.gemma4.pn271_spec_decode_kv_contract_audit",
        "vllm.sndr_core.integrations.spec_decode.pn271_kv_contract_audit",
    ),
    # Bucket 2: KV-cache → kv_cache/
    (
        "vllm.sndr_core.integrations.gemma4.g4_06_gemma4_kv_proj_v_head_size_zero",
        "vllm.sndr_core.integrations.kv_cache.g4_06_kv_proj_v_head_size_zero",
    ),
    (
        "vllm.sndr_core.integrations.gemma4.g4_18_gemma4_per_layer_kv_page_size",
        "vllm.sndr_core.integrations.kv_cache.g4_18_per_layer_kv_page_size",
    ),
]

CANONICAL_ATTRS = ("apply", "is_applied", "should_apply")

# Registered probe IDs (have PATCH_REGISTRY entries that must point at NEW path).
REGISTERED_AFTER_BUCKET_1 = {
    "PN262": "vllm.sndr_core.integrations.spec_decode.probes.pn262_flash_attn_drafter_trace",
    "PN262B": "vllm.sndr_core.integrations.spec_decode.probes.pn262b_kv_alloc_trace",
}

# Bucket 2: KV-cache patches with PATCH_REGISTRY entries that must point at NEW path.
REGISTERED_AFTER_BUCKET_2 = {
    "G4_06": "vllm.sndr_core.integrations.kv_cache.g4_06_kv_proj_v_head_size_zero",
    "G4_18": "vllm.sndr_core.integrations.kv_cache.g4_18_per_layer_kv_page_size",
}

ALL_REGISTERED = {**REGISTERED_AFTER_BUCKET_1, **REGISTERED_AFTER_BUCKET_2}


@pytest.mark.parametrize("old_path,new_path", PROBE_RELOCATIONS)
def test_old_import_path_resolves(old_path, new_path):
    """Old import path must continue to resolve during the shim window."""
    old_mod = importlib.import_module(old_path)
    new_mod = importlib.import_module(new_path)
    for attr in CANONICAL_ATTRS:
        if hasattr(new_mod, attr):
            assert hasattr(old_mod, attr), (
                f"shim {old_path} is missing attribute {attr!r} "
                f"present on real module {new_path}"
            )
            assert getattr(old_mod, attr) is getattr(new_mod, attr), (
                f"shim drift: {old_path}.{attr} is not the same object "
                f"as {new_path}.{attr}"
            )


@pytest.mark.parametrize("patch_id,expected_path", ALL_REGISTERED.items())
def test_registry_uses_new_path(patch_id, expected_path):
    """Registry's apply_module must point at the new path, not the shim."""
    from vllm.sndr_core.dispatcher.registry import PATCH_REGISTRY
    spec = PATCH_REGISTRY[patch_id]
    assert spec["apply_module"] == expected_path, (
        f"{patch_id}: registry apply_module={spec['apply_module']!r}, "
        f"expected {expected_path!r}"
    )
