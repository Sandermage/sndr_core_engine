# SPDX-License-Identifier: Apache-2.0
"""TDD for PN520 — restore the imperative Qwen3.5/3.6 GDN weight loader
(revert vllm#47058).

vLLM #47058 (merged 0.23.1rc1.dev630) replaced ``Qwen3_5Model.load_weights``
with a declarative ``WeightsMapper`` path that drops the split BF16 GDN
projection shards (``in_proj_b``/``in_proj_a`` → ``in_proj_ba`` and
``in_proj_qkv``/``in_proj_z`` → ``in_proj_qkvz``) for the Lorbus
Qwen3.6-27B-int4-AutoRound checkpoint. The Gated-DeltaNet layers are left
uninitialised — the model boots clean but degenerates (``"is is is"`` /
never-EOS). PN520 rebinds ``Qwen3_5Model.load_weights`` (class setattr) to the
pre-#47058 imperative loader with the explicit ``stacked_params_mapping``.

These are wiring/contract tests — importable, env-gated, registered, and
graceful when vllm is absent (the Mac dev box has no CUDA vllm). The runtime
behaviour (the imperative loader actually routing the BF16 ``in_proj_ba``
shards) is validated by the on-rig 27B boot-smoke, not here.
"""
from __future__ import annotations

import importlib

import pytest

_MODULE = (
    "sndr.engines.vllm.patches.model_compat.qwen3_5."
    "pn520_qwen3_5_gdn_load_weights_47058_revert"
)
_APPLY_MODULE = _MODULE
_ENV_ENABLE = "GENESIS_ENABLE_PN520_QWEN3_5_LOAD_WEIGHTS"
_ENV_DISABLE = "GENESIS_DISABLE_PN520_QWEN3_5_LOAD_WEIGHTS"


@pytest.fixture
def pn520():
    return importlib.import_module(_MODULE)


def test_module_imports_without_vllm(pn520):
    """PN520 must import on a bare box — vllm deps are imported inside
    functions, never at module scope."""
    assert hasattr(pn520, "apply")
    assert callable(pn520.apply)


def test_apply_skipped_by_default(pn520, monkeypatch):
    """Default OFF: apply() is a no-op returning ``skipped`` when the enable
    flag is unset (never touches vllm)."""
    monkeypatch.delenv(_ENV_ENABLE, raising=False)
    monkeypatch.delenv(_ENV_DISABLE, raising=False)
    status, reason = pn520.apply()
    assert status == "skipped"
    assert _ENV_ENABLE in reason


def test_disable_beats_enable(pn520, monkeypatch):
    """The explicit DISABLE flag overrides ENABLE."""
    monkeypatch.setenv(_ENV_ENABLE, "1")
    monkeypatch.setenv(_ENV_DISABLE, "1")
    status, _ = pn520.apply()
    assert status == "skipped"


def test_enabled_without_vllm_is_graceful(pn520, monkeypatch):
    """When enabled but vllm's qwen3_5 model module is absent (the dev box),
    apply() degrades to ``skipped`` — never ``failed`` — so a non-CUDA host
    can still import + dispatch the patch."""
    monkeypatch.setenv(_ENV_ENABLE, "1")
    monkeypatch.delenv(_ENV_DISABLE, raising=False)
    # reset the module-level applied latch so the vllm-probe path runs
    monkeypatch.setattr(pn520, "_APPLIED", False, raising=False)
    status, reason = pn520.apply()
    assert status in {"skipped", "applied"}
    if status == "skipped":
        assert "qwen3_5" in reason.lower() or "not found" in reason.lower()


def test_upstream_bindings_declare_qwen3_5(pn520):
    """The class-rebind drift contract must name the Qwen3_5Model target so the
    drift checker knows what this text-anchorless patch binds against."""
    bindings = pn520._upstream_bindings()
    targets = {sym for _mod, sym in bindings}
    assert "Qwen3_5Model" in targets
    assert any("qwen3_5" in mod for mod, _ in bindings)


def test_registered_in_patch_registry():
    """PN520 must be wired into the registry with a resolvable apply_module so
    the orchestrator auto-dispatches it (and completeness gates stay green)."""
    from sndr.dispatcher import PATCH_REGISTRY

    assert "PN520" in PATCH_REGISTRY, "PN520 not registered"
    meta = PATCH_REGISTRY["PN520"]
    assert meta["apply_module"] == _APPLY_MODULE
    assert meta["env_flag"] == _ENV_ENABLE
    assert meta["default_on"] is False
    assert meta["lifecycle"] == "experimental"
    assert meta.get("upstream_pr") == 47058


def test_apply_module_resolves_and_has_apply():
    """The registered apply_module imports and exposes apply()."""
    from sndr.dispatcher import PATCH_REGISTRY

    mod = importlib.import_module(PATCH_REGISTRY["PN520"]["apply_module"])
    assert callable(mod.apply)
