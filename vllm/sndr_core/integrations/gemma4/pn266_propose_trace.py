# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim — PN266 relocated.

Real implementation: vllm.sndr_core.integrations.spec_decode.probes.pn266_propose_trace
Shim window: one release. Remove this file after external imports migrate.
"""
from vllm.sndr_core.integrations.spec_decode.probes.pn266_propose_trace import *  # noqa: F401,F403
