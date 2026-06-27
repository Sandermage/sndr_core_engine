# SPDX-License-Identifier: Apache-2.0
"""Multi-engine Phase 1 — llama.cpp EngineAdapter registration + contract.

The llama.cpp adapter is the third concrete EngineAdapter (after vLLM +
SGLang). It is a NON-Python engine (a C++ binary in the ggml-org image) and has
NO Genesis patch stack, so the contract surface is deliberately minimal.
"""
from __future__ import annotations

from sndr.engines import get_engine, list_engines
from sndr.engines.llamacpp import DEFAULT_LLAMACPP_PIN, LlamacppEngine


class TestLlamacppEngineRegistration:
    def test_registered(self):
        assert "llama-cpp" in list_engines()

    def test_get_engine_returns_adapter(self):
        cls = get_engine("llama-cpp")
        assert cls is LlamacppEngine
        assert cls.name == "llama-cpp"

    def test_default_pin_matches_runtime_command_image(self):
        from sndr.model_configs.runtime_command import LLAMACPP_SERVER_IMAGE
        # The adapter's pin is the build tag of the launch image.
        assert DEFAULT_LLAMACPP_PIN in LLAMACPP_SERVER_IMAGE


class TestLlamacppAdapterContract:
    def _adapter(self) -> LlamacppEngine:
        # Construct without bootstrap (detect_version probes the host binary,
        # which is absent in CI — we test the no-side-effect methods).
        return LlamacppEngine.__new__(LlamacppEngine)

    def test_no_patch_stack(self):
        # Genesis patches are vLLM-only; llama.cpp runs the upstream binary.
        assert self._adapter().list_patches() == []

    def test_normalize_pin_from_image_tag(self):
        a = self._adapter()
        assert a._normalize_pin("server-cuda-b9246") == "b9246"
        assert a._normalize_pin("b9246+gabcdef1") == "b9246"

    def test_runtime_config_and_profile_none(self):
        a = self._adapter()
        assert a.get_runtime_config() is None
        assert a.get_model_profile() is None

    def test_no_pins_supported_yet(self):
        a = self._adapter()
        assert a.is_pin_supported(None) is False
        # No pin manifests ship — the lane runs the upstream binary as-is.
        assert a.list_supported_pins() == ()
