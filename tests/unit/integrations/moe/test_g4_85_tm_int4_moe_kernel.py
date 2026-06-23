# SPDX-License-Identifier: Apache-2.0
"""Tests for G4_85 — TurboMind int4 grouped-MoE kernel (LIVE-target re-wire).

G4_85 was an orphan: not in PATCH_REGISTRY, no Flags constant, and it
monkey-patched the WRONG class (``moe_wna16.MoeWNA16Method``) so nothing
ever loaded or fired it. This suite pins the rewire:

  - registered in PATCH_REGISTRY with default_on False (must NOT change
    any PROD config behavior unless GENESIS_ENABLE_G4_85=1),
  - GENESIS_ENABLE_G4_85 resolves in env.py Flags (1:1 registry contract),
  - the module imports torch-less,
  - apply() honors the (status, reason) tuple contract and is a clean
    no-op "skipped" when the flag is OFF or torch/vllm is absent (fail-open),
  - it now targets CompressedTensorsWNA16MoEMethod (the LIVE method), not
    the old moe_wna16.MoeWNA16Method.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest

MOD = "sndr.engines.vllm.patches.moe.g4_85_tm_int4_moe_kernel"
_REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def g4_85():
    return importlib.import_module(MOD)


@pytest.fixture(autouse=True)
def _flag_off(monkeypatch):
    """Default state: flag OFF (mirrors PROD where default_on=False)."""
    monkeypatch.delenv("GENESIS_ENABLE_G4_85", raising=False)
    yield


class TestRegistryEntry:
    def test_g4_85_in_registry_default_off(self):
        from sndr.dispatcher.registry import PATCH_REGISTRY

        assert "G4_85" in PATCH_REGISTRY, "G4_85 must be registered"
        meta = PATCH_REGISTRY["G4_85"]
        assert meta["default_on"] is False, (
            "G4_85 MUST be default_on=False — it must not change PROD "
            "behavior unless GENESIS_ENABLE_G4_85=1 is set explicitly"
        )
        assert meta["env_flag"] == "GENESIS_ENABLE_G4_85"
        assert meta["family"] == "moe"
        assert meta["lifecycle"] == "experimental"
        assert meta["apply_module"] == MOD

    def test_g4_85_env_flag_resolves_in_flags(self):
        """The registry env_flag (prefix-stripped) must have a Flags constant —
        otherwise is_enabled(Flags.X) would AttributeError at runtime."""
        from sndr.env import Flags, known_flags

        # GENESIS_ENABLE_G4_85 -> stripped "G4_85".
        assert "G4_85" in known_flags()
        assert getattr(Flags, "G4_85") == "G4_85"


class TestModuleContract:
    def test_module_imports_torch_less(self, g4_85):
        # No top-level `import torch` — torch is imported lazily in apply().
        src = Path(g4_85.__file__).read_text()
        for line in src.splitlines():
            assert not line.startswith(("import torch", "from torch")), (
                "G4_85 has a top-level torch import — breaks torch-less "
                f"collection: {line!r}"
            )

    def test_apply_is_callable_and_marker_present(self, g4_85):
        for fn in ("apply", "is_applied", "revert"):
            assert callable(getattr(g4_85, fn))
        assert "G4_85" in g4_85.GENESIS_G4_85_MARKER

    def test_targets_live_compressed_tensors_class(self, g4_85):
        """The rewire targets CompressedTensorsWNA16MoEMethod (the LIVE method),
        NOT the old orphaned moe_wna16.MoeWNA16Method."""
        src = Path(g4_85.__file__).read_text()
        assert "CompressedTensorsWNA16MoEMethod" in src
        assert "compressed_tensors_moe" in src
        # The old wrong target must no longer be the patch site.
        assert "MoeWNA16Method.apply" not in src


class TestApplyContractNoOp:
    def test_apply_returns_status_reason_tuple(self, g4_85):
        status, reason = g4_85.apply()
        assert status in ("skipped", "failed", "applied")
        assert isinstance(reason, str) and reason

    def test_apply_is_skipped_when_flag_off(self, g4_85):
        """Flag OFF -> clean no-op "skipped"; nothing patched (fail-open,
        default_on=False preserved)."""
        status, reason = g4_85.apply()
        assert status == "skipped"
        assert "GENESIS_ENABLE_G4_85" in reason
        assert g4_85.is_applied() is False

    def test_apply_no_crash_when_flag_on_but_runtime_absent(self, g4_85, monkeypatch):
        """Flag ON but torch/vllm absent on the host -> clean skip (runtime
        gap), never a crash, never a live patch. This is the fail-open
        contract that makes a possibly-wrong offline weight-attr guess safe
        pending a live A/B."""
        monkeypatch.setenv("GENESIS_ENABLE_G4_85", "1")
        status, reason = g4_85.apply()
        # On this torch-less / vllm-stub host the resolve raises ImportError
        # naming vllm -> classified as a runtime-gap skip.
        assert status in ("skipped", "failed")
        if status == "skipped":
            assert "runtime not present" in reason or "MoE layers" in reason
        assert g4_85.is_applied() is False


class TestDispatcherSyncAllowList:
    def test_g4_85_in_known_registry_only_allow_list(self):
        """G4_85 is spec-driven (wired via apply_module, no legacy
        apply_patch_* function) so it must be in the dispatcher-sync
        allow-list — same as G4_83/G4_84."""
        sync_test = (
            _REPO_ROOT / "tests" / "unit" / "infra"
            / "test_apply_all_dispatcher_sync.py"
        )
        text = sync_test.read_text()
        assert '"G4_85"' in text, (
            "G4_85 must be added to _KNOWN_REGISTRY_ONLY in "
            "test_apply_all_dispatcher_sync.py (spec-driven, no apply_patch_*)"
        )
