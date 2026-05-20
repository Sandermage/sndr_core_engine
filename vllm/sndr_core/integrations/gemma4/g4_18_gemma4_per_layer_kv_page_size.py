# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim — G4_18 relocated.

Real implementation: vllm.sndr_core.integrations.kv_cache.g4_18_per_layer_kv_page_size
Shim window: one release. Remove this file after external imports migrate.
"""
from vllm.sndr_core.integrations.kv_cache.g4_18_per_layer_kv_page_size import *  # noqa: F401,F403
