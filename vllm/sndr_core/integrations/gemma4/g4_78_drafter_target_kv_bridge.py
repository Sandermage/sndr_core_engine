# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim — G4_78 RETIRED.

G4_78 was an investigative drafter K/V bridge fallback. It was
superseded 2026-05-21 by the validated β'-A K=4 path:
declarative `backend_plan.drafter_kv_sharing: physical` (P1.8 A2)
implements physical kv_sharing as the production-supported drafter
contract. The bridge is not needed for the validated structured
profile and is not a supported runtime path.

Real implementation: vllm.sndr_core.integrations._retired.g4_78_drafter_target_kv_bridge
Shim window: one release. Remove this file after external imports migrate.
"""
from vllm.sndr_core.integrations._retired.g4_78_drafter_target_kv_bridge import *  # noqa: F401,F403
