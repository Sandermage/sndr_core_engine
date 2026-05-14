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
SNDR_CORE_VERSION = "11.0.0"

# Back-compat alias. Tests + telemetry historically used `GENESIS_VERSION`.
GENESIS_VERSION = SNDR_CORE_VERSION

# PR38 cleanup (2026-05-08): tests migrated from `vllm/_genesis/__version__`
# to `vllm.sndr_core.version` import `__version__` (matches PEP 8 dunder
# convention) — alias to SNDR_CORE_VERSION.
__version__ = SNDR_CORE_VERSION

__all__ = ["SNDR_CORE_VERSION", "GENESIS_VERSION", "__version__"]
