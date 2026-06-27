# SPDX-License-Identifier: Apache-2.0
"""llama.cpp engine adapter.

A minimal :class:`~sndr.engines.base.EngineAdapter` for llama.cpp (community
tier), registered in the engine registry. It detects the ``llama-server``
build (binary probe, or the pinned image build when the binary is not on the
host) and reports its identity. It has NO patch stack — Genesis patches are a
vLLM / Qwen3-Next overlay, and the official ``ghcr.io/ggml-org/llama.cpp``
image carries native MTP — so ``list_patches()`` is always empty.

This is the engine behind the single-card GGUF escape-hatch lane
(``presets/llamacpp-qwen3.6-27b-q4km-1x.yaml``).
"""
from sndr.engines.llamacpp.adapter import DEFAULT_LLAMACPP_PIN, LlamacppEngine

__all__ = ["LlamacppEngine", "DEFAULT_LLAMACPP_PIN"]
