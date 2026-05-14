# SPDX-License-Identifier: Apache-2.0
"""SNDR Core patcher infrastructure (canonical home).

Public API for text-patching primitives that all SNDR Core / Genesis
patches use. Migration target for the legacy `vllm/_genesis/wiring/`
infrastructure.

Contents (Stage 3 — current):
  - `text_patch` — TextPatch, TextPatcher, TextPatchResult, TextPatchFailure,
                   result_to_wiring_status (the per-file patcher).
  - `multi_file` — MultiFilePatchTransaction (atomic multi-file commits).
  - `manifest_cache` — internal manifest caching helpers used by TextPatcher.

Future (Stage 4):
  - `file_cache` — Layer 0 fast-path (was: wiring/file_cache.py).
  - `manifest` — Site Map anchor manifest (was: wiring/anchor_manifest.py).

Future (Stage 8):
  - `sub_patch` — SubPatch dataclass with per-sub drift markers.
  - `markers` — marker discovery / composition.
"""
from .multi_file import MultiFilePatchTransaction  # noqa: F401
from .text_patch import (  # noqa: F401
    TextPatch,
    TextPatchFailure,
    TextPatchResult,
    TextPatcher,
    result_to_wiring_status,
)

__all__ = [
    "MultiFilePatchTransaction",
    "TextPatch",
    "TextPatchFailure",
    "TextPatchResult",
    "TextPatcher",
    "result_to_wiring_status",
]
