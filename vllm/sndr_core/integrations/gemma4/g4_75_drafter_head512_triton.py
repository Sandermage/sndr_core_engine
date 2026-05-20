# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim — G4_75 relocated.

Real implementation: vllm.sndr_core.integrations.spec_decode.g4_75_drafter_head512_triton
Shim window: one release. Remove this file after external imports migrate.
"""
from vllm.sndr_core.integrations.spec_decode.g4_75_drafter_head512_triton import *  # noqa: F401,F403
