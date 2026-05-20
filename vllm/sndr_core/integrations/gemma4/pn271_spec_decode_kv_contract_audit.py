# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim — PN271 relocated.

Real implementation: vllm.sndr_core.integrations.spec_decode.pn271_kv_contract_audit
(runtime guard placement, not probes/ — operator decision per Task F §11.1)
Shim window: one release. Remove this file after external imports migrate.
"""
from vllm.sndr_core.integrations.spec_decode.pn271_kv_contract_audit import *  # noqa: F401,F403
