# SPDX-License-Identifier: Apache-2.0
"""SNDR Core — canonical infrastructure for vllm patcher (community tier).

Public-facing brand: "Genesis (powered by SNDR Core)".

This package is the canonical home for:
  - Patcher infrastructure (TextPatcher, MultiFilePatchTransaction, manifest)
  - Upstream backports (community-tier patches; keep "Genesis" marker prefix)
  - Centralized engine paths + env flag registry
  - CLI installer + first-run launcher

Sander-original kernels and advanced features live in `vllm.sndr_engine/`
(commercial tier) — separate pip-installable package.

Brand decision (Sander 2026-05-07, Q2 mixed):
  - Backport patches (from upstream PR vllm/SGLang/llama.cpp) keep
    `Genesis ` marker prefix + `GENESIS_ENABLE_*` env vars. They are
    community-tier work, retain community branding.
  - Sander-original patches use `SNDR ` marker prefix + `SNDR_ENABLE_*`
    env vars. These are the canonical brand for new Sander-IP work.
  - Patcher Layer-1 marker check recognizes BOTH prefixes (text_patch.py).

Migration status (started 2026-05-07, etap 1):
  Stage 1 (CURRENT) — skeleton only. All code still lives in vllm/_genesis/.
  Stages 2-13      — progressive migration; modules move INTO sndr_core/.
  Final            — vllm/_genesis/ becomes thin forward-alias of sndr_core.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
"""
from .version import SNDR_CORE_VERSION, GENESIS_VERSION  # noqa: F401
from . import brand  # noqa: F401
from . import env  # noqa: F401
from . import locations  # noqa: F401  (renamed from `paths` 2026-05-11 — audit P-01 P-02)
from . import detection  # noqa: F401  (Stage 4)
# `runtime`, `integrations`, `bundles`, `cli` are loaded lazily via __getattr__.
#
# (1) Torch-less import contract: `runtime.prealloc` imports torch at module
#     top-level. CLI / schema validator / doctor / registry audit / pre-commit
#     must work in environments without torch — eager `from . import runtime`
#     would break them. The legacy `vllm/_genesis/__init__.py` documents the
#     same trap (v7 G-002 fix).
#
# (2) Circular-import contract: `integrations` and `bundles` import back into
#     `vllm._genesis.wiring` (forward shims) — eager init at this point
#     would create a cycle with sndr_core still initializing.
from .env import (  # noqa: F401
    Flags, is_enabled, is_disabled, is_legacy_active, is_meta_flag,
)
from .locations import (  # noqa: F401  (renamed from `paths` 2026-05-11)
    vllm_targets,
    resolve_vllm_file,
    vllm_install_root,
)


def __getattr__(name: str):
    """Lazy-load `runtime`, `integrations`, `bundles`, `cli`.

    `runtime` is lazy to keep torch out of the cold-import path.
    `integrations` / `bundles` / `cli` are lazy to avoid circular imports
    with vllm._genesis.wiring (which loads forward shims on init).

    Back-compat aliases (`patches` → `integrations`, `paths` → `locations`)
    are kept for one major version to ease the transition.
    """
    if name in ("runtime", "integrations", "bundles", "cli"):
        import importlib
        return importlib.import_module(f"vllm.sndr_core.{name}")
    # Back-compat aliases: old `patches`/`paths` names still resolve to the
    # new modules (transition path; can be removed in a future major).
    if name == "patches":
        import importlib
        return importlib.import_module("vllm.sndr_core.integrations")
    if name == "paths":
        import importlib
        return importlib.import_module("vllm.sndr_core.locations")
    raise AttributeError(f"module 'vllm.sndr_core' has no attribute {name!r}")

__version__ = SNDR_CORE_VERSION

__all__ = [
    "SNDR_CORE_VERSION",
    "GENESIS_VERSION",
    "brand",
    "env",
    "locations",
    "detection",
    "runtime",
    "integrations",
    "bundles",
    "Flags",
    "is_enabled",
    "is_disabled",
    "is_legacy_active",
    "is_meta_flag",
    "engine_targets",
    "resolve_vllm_file",
    "vllm_install_root",
]
