# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim — G4_71 relocated.

Real implementation: vllm.sndr_core.integrations.spec_decode.g4_71_drafter_native_attn_backend
Shim window: one release. Remove this file after external imports migrate.
"""
from vllm.sndr_core.integrations.spec_decode.g4_71_drafter_native_attn_backend import *  # noqa: F401,F403
