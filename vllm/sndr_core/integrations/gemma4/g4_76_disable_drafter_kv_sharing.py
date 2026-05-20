# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim — G4_76 relocated.

Real implementation: vllm.sndr_core.integrations.spec_decode.g4_76_disable_drafter_kv_sharing
Shim window: one release. Remove this file after external imports migrate.
"""
from vllm.sndr_core.integrations.spec_decode.g4_76_disable_drafter_kv_sharing import *  # noqa: F401,F403
