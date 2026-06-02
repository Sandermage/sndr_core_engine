# SPDX-License-Identifier: Apache-2.0
"""SNDR Core version metadata.

Single source of truth for the SNDR Core package version.
GENESIS_VERSION is preserved as alias for back-compat — any code that
reads `from vllm._genesis.__version__ import GENESIS_VERSION` continues
to work after the migration completes (vllm/_genesis becomes forward shim).

Versioning:
  v7.x — pre-refactor (Genesis branding, monolithic dispatcher + apply_all).
  v8.0 — SNDR Core skeleton, structural refactor.
  v8.x — bundle pattern, per-sub drift, interactive installer, tests
         centralization, sndr_engine commercial tier.
  v9.0 — sndr_paths.py path consolidation (single source of truth for
         SNDR-internal paths).
  v10.0 — hard flip: every impl file physically moved from
          `vllm/_genesis/` into `vllm/sndr_core/`. Legacy paths remain
          as sys.modules redirects (same module object → monkey-patches
          still propagate, 327 test contracts preserved).
"""

# v10.0.0 (2026-05-07): hard flip — every implementation file moved into
# `vllm/sndr_core/`. Legacy `vllm/_genesis/` is now thin alias layer (210
# redirect files, 25 legitimate __init__.py packages). 2425 pytest pass,
# 0 functional regressions vs v9.0.0 baseline.
# v11.0.0 (2026-05-08): PR38 cleanup release. `vllm/_genesis/` shim
# layer removed entirely. All implementation lives at
# `vllm/sndr_core/`; tests migrated to `tests/legacy/` (with import
# rewrites) and `tests/unit/integrations/<family>/` for new-style canonical
# layout. 2500 pytest pass / 0 fail / 79 skip on dev (CPU-only).
# v11.1.0 (2026-06-02): Phase 6 closeout — P3.1 pn118 v2 md5+full-file
# PoC (workspace.py scope, companion to original pn118, default OFF),
# P3.3 PersistentBufferRegistry (registration-only — allocator-level
# routing deferred to v11.2.0+ pending bench validation; CUDA-graph
# safety + storage-ownership integration on legacy allocators required
# the conservative scope). Operator docs Phase 10 V1-sunset closeout
# (CONFIGS V2-workflow + TROUBLESHOOTING R-002/R-009 V1-sunset-aware +
# RELEASE_POLICY Wave 10 annotation). Registry: 236 → 237 entries.
# v11.2.0 (2026-06-03): P3.1 multi-file md5 conversion fully closed via
# sibling-PoC pattern. 3 more v2 patches landed (PN118_V2_MD5_TURBOQUANT_
# ATTN + PN79_V2_MD5_CHUNK + PN79_V2_MD5_CHUNK_DELTA_H). pn118 multi-file
# converted (2 sibling patches for 2 files); pn79 partial conversion
# (2/4 files — gdn_linear_attn.py + olmo_hybrid.py are upstream-drifted
# out of existence, gdn split into model-specific files under gdn/).
# Strong empirical case for md5+full-file pattern: pn79 silently partial-
# applies on current pin (only 3/7 chunk.py anchors + 3/4 chunk_delta_h.py
# anchors match upstream). md5 pattern documents this drift transparently.
# Registry: 237 → 240 entries. All default OFF; opt-in for A/B validation.
SNDR_CORE_VERSION = "11.2.0"

# Back-compat alias. Tests + telemetry historically used `GENESIS_VERSION`.
GENESIS_VERSION = SNDR_CORE_VERSION

# PR38 cleanup (2026-05-08): tests migrated from `vllm/_genesis/__version__`
# to `vllm.sndr_core.version` import `__version__` (matches PEP 8 dunder
# convention) — alias to SNDR_CORE_VERSION.
__version__ = SNDR_CORE_VERSION

__all__ = ["SNDR_CORE_VERSION", "GENESIS_VERSION", "__version__"]
