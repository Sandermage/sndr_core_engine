# SPDX-License-Identifier: Apache-2.0
"""SNDR Core patches — `multimodal` family.

Engine subsystem: multimodal-aware paths (VL/vision encoder skipping for
text-only inputs, multimodal token routing, etc.).

Patches in this family:
  - pn62_text_only_vit_skip — Genesis-original. When the running model
    is multimodal (qwen3-VL, etc.) but the request contains zero image
    tokens, skip the ViT forward pass + vision-projection materialize.
    Saves ~150-300ms / request when 90%+ of traffic is text-only.
  - pn371_encoder_cache_deferred_eviction — vendor of vllm#45199
    (CLOSED unmerged 2026-06-11; fixes #38551). Ref-counted encoder
    cache: scheduler frees of entries still referenced by in-flight
    requests are deferred until the last referencing request finishes.
    Kills the whole-engine-fatal "Encoder cache miss" on Gemma-4
    vision + MTP K=3 + async scheduling. Opt-in; intended ON for the
    gemma4 composes.

Future patches expected here: vision token batching, audio-modal
skipping (when whisper-style models added).
"""

from __future__ import annotations

__all__ = [
    "pn62_text_only_vit_skip",
    "pn371_encoder_cache_deferred_eviction",
]

def __getattr__(name: str):
    """Lazy submodule loader (P0-1 fix, audit 2026-05-08).

    Eager `from . import <patch>` cascaded torch imports → torch-less
    hosts (CI / Mac dev / preflight) couldn't import the patches
    package at all. Now patches load only on attribute access.
    """
    import importlib
    if name in __all__:
        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(
        f"module {__name__!r} has no attribute {name!r}"
    )
