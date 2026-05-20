# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim — G4_06 relocated.

Real implementation: vllm.sndr_core.integrations.kv_cache.g4_06_kv_proj_v_head_size_zero
Shim window: one release. Remove this file after external imports migrate.
"""
from vllm.sndr_core.integrations.kv_cache.g4_06_kv_proj_v_head_size_zero import *  # noqa: F401,F403
