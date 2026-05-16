# SPDX-License-Identifier: Apache-2.0
"""Phase 1 V2 schema tests — ModelDef / HardwareDef / ProfileDef /
PatchManifest validators + edge cases.

See PROJECT_ROADMAP_V2_2026-05-12_RU.md § 4 for the schema spec.
"""
from __future__ import annotations

import pytest

from vllm.sndr_core.model_configs.schema import HardwareSpec, SchemaError, SpecDecodeConfig
from vllm.sndr_core.model_configs.schema_v2 import (
    HardwareDef,
    HardwareSizing,
    ModelCapabilities,
    ModelDef,
    ModelRequires,
    ModelVersions,
    PatchAnchor,
    PatchCompatibility,
    PatchManifest,
    PatchTargetFile,
    PatchesDelta,
    ProfileDef,
    ProfilePromotion,
    ProfileVersionsOverride,
    RuntimeBareMetalBlock,
    RuntimeBlock,
    RuntimeDockerBlock,
)


# ─── Builders ────────────────────────────────────────────────────────────


def _make_model(**kw) -> ModelDef:
    base = dict(
        schema_version=2, kind="model", id="qwen3.6-test",
        title="Test", maintainer="x", last_validated="2026-05-12",
        license="apache-2.0", model_path="/m",
    )
    base.update(kw)
    return ModelDef(**base)


def _make_hardware(**kw) -> HardwareDef:
    base = dict(
        schema_version=2, kind="hardware", id="a5000-2x-test",
        title="T", maintainer="x",
        hardware=HardwareSpec(
            gpu_match_keys=["rtx a5000"], n_gpus=2,
            min_vram_per_gpu_mib=24000,
        ),
        runtime=RuntimeBlock(
            default="docker", supported=["docker"],
            docker=RuntimeDockerBlock(image="vllm:test"),
        ),
    )
    base.update(kw)
    return HardwareDef(**base)


def _make_profile(**kw) -> ProfileDef:
    base = dict(
        schema_version=2, kind="profile", id="wave9-test",
        parent_model="qwen3.6-test", maintainer="x",
    )
    base.update(kw)
    return ProfileDef(**base)


def _make_patch_manifest(**kw) -> PatchManifest:
    # Phase 5: patch ids follow the P-code uppercase convention
    # (`PN999`, `P107`, etc.). _check_patch_id() rejects lowercase.
    base = dict(
        schema_version=2, kind="patch", id="PN999",
        namespace="community/test", title="t", maintainer="x",
        version="1.0.0", license="apache-2.0",
        entry_points={"apply": "patch:apply"},
    )
    base.update(kw)
    return PatchManifest(**base)


# ─── ModelDef ────────────────────────────────────────────────────────────


class TestModelDef:
    def test_minimal_valid(self):
        _make_model().validate()  # no raise

    def test_wrong_schema_version_rejected(self):
        with pytest.raises(SchemaError, match="schema_version"):
            _make_model(schema_version=1).validate()

    def test_wrong_kind_rejected(self):
        with pytest.raises(SchemaError, match="kind"):
            _make_model(kind="hardware").validate()

    @pytest.mark.parametrize("bad_id", ["", "BAD_ID", "Has Spaces", "_leading"])
    def test_id_rejects_invalid(self, bad_id):
        with pytest.raises(SchemaError, match="model.id"):
            _make_model(id=bad_id).validate()

    @pytest.mark.parametrize("ok_id", ["qwen3.6-35b-a3b-fp8", "model-1", "q"])
    def test_id_accepts_kebab_dotted(self, ok_id):
        _make_model(id=ok_id).validate()

    def test_missing_model_path_rejected(self):
        with pytest.raises(SchemaError, match="model_path"):
            _make_model(model_path="").validate()

    def test_patches_dict_must_be_str(self):
        with pytest.raises(SchemaError, match="patches"):
            _make_model(patches={"K": 1}).validate()

    def test_capabilities_validates_spec_decode(self):
        bad = ModelCapabilities(
            attention_arch="dense",
            spec_decode=SpecDecodeConfig(method="dflash", num_speculative_tokens=4),
            # dflash requires model path; SpecDecodeConfig.validate enforces
        )
        with pytest.raises(SchemaError):
            _make_model(capabilities=bad).validate()


class TestModelRequires:
    def test_default_minimums(self):
        ModelRequires().validate()  # min_gpu_count=1, min_total_vram_mib=0

    def test_negative_vram_rejected(self):
        with pytest.raises(SchemaError, match="min_total_vram_mib"):
            ModelRequires(min_total_vram_mib=-1).validate()

    def test_zero_gpu_count_rejected(self):
        with pytest.raises(SchemaError, match="min_gpu_count"):
            ModelRequires(min_gpu_count=0).validate()


# ─── HardwareDef ─────────────────────────────────────────────────────────


class TestHardwareDef:
    def test_minimal_valid(self):
        _make_hardware().validate()

    def test_runtime_default_must_be_supported(self):
        rt = RuntimeBlock(default="podman", supported=["docker"],
                            docker=RuntimeDockerBlock(image="x"))
        with pytest.raises(SchemaError, match="not in runtime.supported"):
            _make_hardware(runtime=rt).validate()

    def test_runtime_unknown_value_rejected(self):
        rt = RuntimeBlock(default="kubernetes", supported=["kubernetes"])
        with pytest.raises(SchemaError, match="runtime.default"):
            _make_hardware(runtime=rt).validate()

    def test_docker_required_when_supported(self):
        rt = RuntimeBlock(default="docker", supported=["docker"], docker=None)
        # Schema is permissive when docker block is None even if "docker"
        # is supported — the composer flags missing block when picked.
        # Validate alone should pass to allow lazy block authoring.
        _make_hardware(runtime=rt).validate()

    def test_sizing_validates_max_model_len(self):
        bad = HardwareSizing(max_model_len=0)
        with pytest.raises(SchemaError, match="max_model_len"):
            _make_hardware(sizing=bad).validate()

    @pytest.mark.parametrize("util", [0.0, -0.1, 1.5])
    def test_sizing_gmu_out_of_range(self, util):
        bad = HardwareSizing(gpu_memory_utilization=util)
        with pytest.raises(SchemaError, match="gpu_memory_utilization"):
            _make_hardware(sizing=bad).validate()


# ─── ProfileDef + PatchesDelta ──────────────────────────────────────────


class TestPatchesDelta:
    def test_empty_delta_validates(self):
        PatchesDelta().validate()

    def test_overlap_enable_disable_rejected(self):
        d = PatchesDelta(enable={"K": "1"}, disable=["K"])
        with pytest.raises(SchemaError, match="BOTH enable and disable"):
            d.validate()

    def test_disable_non_string_rejected(self):
        d = PatchesDelta(disable=[123])  # type: ignore[list-item]
        with pytest.raises(SchemaError, match="disable"):
            d.validate()

    def test_enable_non_string_value_rejected(self):
        d = PatchesDelta(enable={"K": 42})  # type: ignore[dict-item]
        with pytest.raises(SchemaError, match="enable"):
            d.validate()


class TestProfileDef:
    def test_minimal_valid(self):
        _make_profile().validate()

    def test_missing_parent_model_rejected(self):
        with pytest.raises(SchemaError, match="parent_model"):
            _make_profile(parent_model="").validate()

    def test_status_must_be_allowed(self):
        # Pytest can't trigger Literal at runtime; test our manual check.
        p = _make_profile()
        p.status = "bogus"  # type: ignore[assignment]
        with pytest.raises(SchemaError, match="status"):
            p.validate()

    def test_promote_target_optional(self):
        p = _make_profile(promotion=ProfilePromotion(
            validation_required=["x"], promote_to="qwen3.6-test",
        ))
        p.validate()

    def test_versions_override_optional(self):
        p = _make_profile(versions_override=ProfileVersionsOverride(
            vllm_pin_required="x.y.z",
        ))
        p.validate()


# ─── PatchManifest (community SDK) ──────────────────────────────────────


class TestPatchManifest:
    def test_minimal_valid(self):
        _make_patch_manifest().validate()

    def test_namespace_must_be_community_or_core(self):
        with pytest.raises(SchemaError, match="namespace"):
            _make_patch_manifest(namespace="random/path").validate()

    @pytest.mark.parametrize("ver", ["1.0.0", "0.1.5", "2.3.4-rc1", "1.0.0+build5"])
    def test_semver_accepted(self, ver):
        _make_patch_manifest(version=ver).validate()

    @pytest.mark.parametrize("bad_ver", ["v1", "1.0", "abc", "1.0.0.0"])
    def test_semver_rejected(self, bad_ver):
        with pytest.raises(SchemaError, match="semver"):
            _make_patch_manifest(version=bad_ver).validate()

    def test_default_on_requires_env_flag(self):
        with pytest.raises(SchemaError, match="env_flag"):
            _make_patch_manifest(default_on=True, env_flag=None).validate()

    def test_text_patch_requires_target_files(self):
        with pytest.raises(SchemaError, match="target_files"):
            _make_patch_manifest(type="text_patch", target_files=[]).validate()

    def test_runtime_hook_requires_apply_entry_point(self):
        with pytest.raises(SchemaError, match="entry_points.apply"):
            _make_patch_manifest(entry_points={}).validate()

    def test_anchor_dataclass_holds(self):
        a = PatchAnchor(
            id="anchor_1", context_before="def foo():",
            context_after="    return x",
            operation="wrap_return", what_we_do="wrap return",
        )
        assert a.id == "anchor_1"

    def test_target_file_smoke(self):
        tf = PatchTargetFile(
            path="vllm/v1/test.py", target_module="vllm.v1.test",
        )
        assert tf.path == "vllm/v1/test.py"
        assert tf.anchors == []

    # Supplement §4 (no-stub policy)

    def test_default_publish_state_is_draft(self):
        m = _make_patch_manifest()
        assert m.publish_state == "draft"
        assert m.is_release_eligible() is False

    def test_published_is_release_eligible(self):
        m = _make_patch_manifest(publish_state="published")
        m.validate()
        assert m.is_release_eligible() is True

    def test_draft_default_on_rejected(self):
        """default_on=True patch must be published — auto-running draft
        is the exact anti-pattern supplement §4 forbids."""
        with pytest.raises(SchemaError, match="publish_state"):
            _make_patch_manifest(
                default_on=True, env_flag="GENESIS_X",
                publish_state="draft",
            ).validate()

    def test_published_default_on_accepted(self):
        _make_patch_manifest(
            default_on=True, env_flag="GENESIS_X",
            publish_state="published",
        ).validate()

    def test_implementation_status_uses_new_axis(self):
        """Old axis (scaffold/partial/full/research) is gone; new axis is
        readiness (experimental/beta/stable/deprecated/disabled)."""
        m = _make_patch_manifest(implementation_status="beta")
        m.validate()
        assert m.implementation_status == "beta"
