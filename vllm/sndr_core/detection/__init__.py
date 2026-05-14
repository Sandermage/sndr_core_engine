# SPDX-License-Identifier: Apache-2.0
"""SNDR Core detection — model/config/gpu/vllm-version probing.

Used by:
  - dispatcher.decision (`should_apply()` consults model_detect +
    config_detect to decide whether to apply a given patch).
  - cli.install (Stage 11 will use `gpu_detect` for hardware match
    + `vllm_detect` for nightly pin discovery).
  - patch wirings (rare — most defer to dispatcher gate).

Stage 4 (2026-05-07): re-exports canonical impls from `_genesis/` for
back-compat with test monkey-patches.
"""
from . import config_detect  # noqa: F401
from . import gpu_detect  # noqa: F401
from . import model_detect  # noqa: F401

__all__ = ["config_detect", "gpu_detect", "model_detect"]
