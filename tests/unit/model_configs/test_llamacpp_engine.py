# SPDX-License-Identifier: Apache-2.0
"""Multi-engine Phase 1 — llama.cpp single-card GGUF lane.

Covers the four load-bearing pieces of the lane:
  1. The launch dispatcher: engine=="vllm" renders the SAME vLLM argv as before
     (byte-unchanged), engine=="llama-cpp" renders the llama-server GGUF argv
     with the mandatory flags (-np 1, --spec-type draft-mtp, q4_0 KV, -ngl 99).
  2. GGUF resolution: model_path must be a single .gguf FILE, not an HF dir.
  3. The llama.cpp KV projection: reproduces the club-3090 ~22.5 GB anchor at
     131K with tp=1 / q4_0 (NOT the vLLM TP/turboquant math).
  4. The composed builtin lane preset + escape-hatch wiring.
"""
from __future__ import annotations

import pytest

from sndr.model_configs import kv_projector as kp
from sndr.model_configs.gguf_resolution import (
    gguf_variant_label,
    is_gguf_path,
    resolve_gguf_file,
)
from sndr.model_configs.registry_v2 import (
    load_alias,
    load_model,
    load_preset_def,
)
from sndr.model_configs.runtime_command import (
    LLAMACPP_SERVER_IMAGE,
    build_llamacpp_argv,
    build_runtime_command,
)
from sndr.model_configs.schema import DockerConfig, HardwareSpec, ModelConfig, SchemaError
from sndr.model_configs.schema_v2 import ModelShape
from sndr.model_configs.types import SpecDecodeConfig

_GIB = 1024 ** 3
_LANE = "llamacpp-qwen3.6-27b-q4km-1x"
_GGUF = "/models/qwen3.6-27b-gguf/unsloth-mtp-q4km/Qwen3.6-27B-Q4_K_M.gguf"


def _llamacpp_cfg(**overrides) -> ModelConfig:
    base = dict(
        key="llamacpp-test", title="t", description="d", schema_version=1,
        maintainer="m", model_path=_GGUF, engine="llama-cpp",
        kv_cache_dtype="q4_0", max_model_len=131072,
        hardware=HardwareSpec(gpu_match_keys=["rtx 3090"], n_gpus=1,
                              min_vram_per_gpu_mib=22000),
        spec_decode=SpecDecodeConfig(method="mtp", num_speculative_tokens=2),
        docker=DockerConfig(image="vllm/vllm-openai:nightly",
                            container_name="llama-cpp-qwen36-27b", port=8020),
    )
    base.update(overrides)
    return ModelConfig(**base)


# ─── 1. Launch dispatcher ───────────────────────────────────────────────────


class TestDispatcherVllmUnchanged:
    """The vLLM path is byte-unchanged: engine=="vllm" (the default) renders
    the canonical `vllm serve ...` argv exactly as before."""

    def test_default_engine_is_vllm(self):
        cfg = ModelConfig(
            key="v", title="t", description="d", schema_version=1, maintainer="m",
            model_path="/models/Qwen3.6-27B-int4-AutoRound",
        )
        assert cfg.engine == "vllm"

    @pytest.mark.parametrize("alias", [
        "prod-qwen3.6-35b-balanced",
        "prod-qwen3.6-27b-tq-k8v4",
        "qa-qwen3.6-27b-tq-1x",
    ])
    def test_vllm_preset_argv_starts_vllm_serve(self, alias):
        cfg = load_alias(alias)
        assert cfg.engine == "vllm"
        argv = build_runtime_command(cfg).argv
        assert argv[0:2] == ["vllm", "serve"]
        assert "--model" in argv
        assert "llama-server" not in argv


class TestDispatcherLlamacppRenders:
    """engine=="llama-cpp" routes to the llama-server GGUF argv."""

    def test_argv_is_llama_server(self):
        argv = build_runtime_command(_llamacpp_cfg()).argv
        assert argv[0] == "llama-server"
        assert "vllm" not in argv and "serve" not in argv

    def test_argv_has_mandatory_single_card_flags(self):
        argv = build_llamacpp_argv(_llamacpp_cfg()).argv
        # -np 1 is MANDATORY (>1 disables MTP + OOMs the spec-context buffer).
        assert argv[argv.index("-np") + 1] == "1"
        # All layers on GPU + FlashAttention.
        assert argv[argv.index("-ngl") + 1] == "99"
        assert argv[argv.index("-fa") + 1] == "on"
        # q4_0 KV (densest mainline, Ampere-fast).
        assert argv[argv.index("--cache-type-k") + 1] == "q4_0"
        assert argv[argv.index("--cache-type-v") + 1] == "q4_0"
        # -ub cliff-survival microbatch.
        assert argv[argv.index("-ub") + 1] == "1024"

    def test_argv_renders_mtp_drafter(self):
        argv = build_llamacpp_argv(_llamacpp_cfg()).argv
        assert argv[argv.index("--spec-type") + 1] == "draft-mtp"
        assert argv[argv.index("--spec-draft-n-max") + 1] == "2"

    def test_argv_carries_model_file_ctx_port(self):
        argv = build_llamacpp_argv(_llamacpp_cfg()).argv
        assert argv[argv.index("-m") + 1] == _GGUF
        assert argv[argv.index("-c") + 1] == "131072"
        assert argv[argv.index("--port") + 1] == "8020"

    def test_non_mtp_omits_spec_flags(self):
        cfg = _llamacpp_cfg(spec_decode=None)
        argv = build_llamacpp_argv(cfg).argv
        assert "--spec-type" not in argv

    def test_unknown_kv_dtype_falls_back_to_q4_0(self):
        # A vLLM-flavoured KV label is meaningless to llama.cpp → q4_0.
        cfg = _llamacpp_cfg(kv_cache_dtype="turboquant_k8v4")
        argv = build_llamacpp_argv(cfg).argv
        assert argv[argv.index("--cache-type-k") + 1] == "q4_0"

    def test_launch_script_renders_pinned_image_and_no_apply(self):
        script = _llamacpp_cfg().to_launch_script(strict_mounts=False)
        assert LLAMACPP_SERVER_IMAGE in script
        assert "llama-server" in script
        # NO Genesis apply step (llama.cpp has no patch stack).
        assert "python3 -m sndr.apply" not in script
        # vLLM image must NOT appear (the lane overrides it).
        assert "vllm/vllm-openai" not in script


# ─── 2. GGUF resolution ─────────────────────────────────────────────────────


class TestGgufResolution:
    def test_resolve_accepts_gguf_file(self):
        assert resolve_gguf_file(_GGUF) == _GGUF

    def test_resolve_rejects_directory(self):
        # The vLLM HF-directory convention is wrong for llama.cpp.
        with pytest.raises(SchemaError, match="single .gguf FILE"):
            resolve_gguf_file("/models/Qwen3.6-27B-int4-AutoRound")

    def test_resolve_rejects_empty(self):
        with pytest.raises(SchemaError):
            resolve_gguf_file("")

    def test_is_gguf_path(self):
        assert is_gguf_path(_GGUF) is True
        assert is_gguf_path("/models/Qwen3.6-27B-int4-AutoRound") is False
        assert is_gguf_path("/models/x.GGUF") is True  # case-insensitive

    def test_variant_label(self):
        assert gguf_variant_label(_GGUF) == "Qwen3.6-27B-Q4_K_M"
        assert gguf_variant_label("/models/dir") == ""

    def test_dispatcher_rejects_dir_model_path(self):
        cfg = _llamacpp_cfg(model_path="/models/Qwen3.6-27B-int4-AutoRound")
        with pytest.raises(SchemaError, match="single .gguf FILE"):
            build_runtime_command(cfg)


# ─── 3. llama.cpp KV projection ─────────────────────────────────────────────


def _gguf_shape() -> ModelShape:
    """27B GGUF shape — Q4_K_M ~17 GB, 48 hidden layers, 4 KV heads, head_dim 128."""
    return ModelShape(
        num_hidden_layers=48, num_attention_layers=12, num_recurrent_layers=36,
        hidden_size=4096, num_attention_heads=40, num_kv_heads=4, head_dim=128,
        weight_bits=4, weights_total_gib=17.0, mtp_num_layers=1,
    )


class TestLlamacppProjection:
    def test_reproduces_club3090_anchor_at_131k(self):
        """weights ~17.0 + KV ~5.0 + overhead ~0.5 = ~22.5 GB on 24 GB."""
        p = kp.project_llamacpp_from_shape(
            _gguf_shape(), preset_id="27b", ctx=131072, vram_gib=24.0, mtp=True,
        )
        assert abs(p.weights_gib - 17.0) < 0.01
        assert abs(p.kv_pool_requested_gib - 5.0) < 0.2, p.kv_pool_requested_gib
        assert abs(p.total_gib - 22.5) < 0.3, p.total_gib
        assert p.verdict == "PASS"
        # llama.cpp lane invariants — single card, q4_0.
        assert p.tp == 1
        assert p.max_num_seqs == 1
        assert p.kv_format == "q4_0"
        # No vLLM-only components.
        assert p.recurrent_state_gib == 0.0
        assert p.cudagraph_overhead_gib == 0.0

    def test_200k_walls_as_tight(self):
        """262K boots-not-fills on 24 GB (club-3090 CLIFFS.md); 200K already
        exceeds the pre-allocated budget → TIGHT (would OOM at load)."""
        p = kp.project_llamacpp_from_shape(
            _gguf_shape(), preset_id="27b", ctx=200000, vram_gib=24.0, mtp=True,
        )
        assert p.verdict == "TIGHT"
        assert p.headroom_gib < 0

    def test_uses_llamacpp_math_not_vllm(self):
        """The project() dispatch must route a llama-cpp preset to the GGUF
        projection (tp=1, q4_0), NOT the vLLM TP/turboquant math."""
        cfg = load_alias(_LANE)
        model = load_model("qwen3.6-27b-gguf-q4km-mtp")
        rig = kp.ProjectorRig(vram_gib_per_card=24.0, gpu_count=1)
        p = kp.project(cfg, rig, shape=model.capabilities.shape)
        assert p.tp == 1
        assert p.kv_format == "q4_0"
        assert p.verdict == "PASS"

    def test_weights_fallback_when_no_total_declared(self):
        shape = ModelShape(
            num_hidden_layers=48, num_kv_heads=4, head_dim=128,
        )  # no weights_total_gib
        gib = kp.llamacpp_weights_gib(shape)
        assert gib == kp._LLAMACPP_Q4KM_WEIGHTS_GIB


# ─── 4. Composed builtin lane preset + escape hatch ─────────────────────────


class TestLlamacppLanePreset:
    def test_lane_composes_to_llamacpp_engine(self):
        cfg = load_alias(_LANE)
        assert cfg.engine == "llama-cpp"
        assert cfg.model_path.endswith(".gguf")
        assert cfg.max_model_len == 131072

    def test_lane_renders_llamacpp_command(self):
        cfg = load_alias(_LANE)
        argv = build_runtime_command(cfg).argv
        assert argv[0] == "llama-server"
        assert argv[argv.index("-np") + 1] == "1"

    def test_card_declares_engine(self):
        pd = load_preset_def(_LANE)
        assert pd.card is not None
        assert pd.card.engine == "llama-cpp"

    def test_escape_hatch_points_at_lane(self):
        """The 2× vLLM 27B preset (which a single-card rig cannot run) falls
        back to the llama.cpp lane — the real launchable escape hatch."""
        pd = load_preset_def("prod-qwen3.6-27b-tq-k8v4")
        assert pd.card.fallback_preset == _LANE

    def test_lane_fits_single_card_via_escape_hatch(self):
        """End-to-end: on a single 24GB card the 2× preset triggers the escape
        hatch, and the llama.cpp fallback it points at actually fits."""
        from sndr.cli.wizard.launch_wizard import (
            build_catalog,
            escape_hatch_for,
        )
        from sndr.model_configs.preflight_fit import rig_from_fake_spec
        from sndr.model_configs.registry_v2 import list_presets

        rig = rig_from_fake_spec("RTX 3090:24576:8.6")
        cat = build_catalog(
            rig, preset_ids=list_presets(),
            card_loader=load_preset_def, cfg_loader=load_alias,
        )
        two_x = next(c for c in cat.candidates
                     if c.preset_id == "prod-qwen3.6-27b-tq-k8v4")
        hatch = escape_hatch_for(two_x, rig)
        assert hatch.triggered
        assert hatch.fallback_preset == _LANE
        lane = next(c for c in cat.candidates if c.preset_id == _LANE)
        assert lane.can_run is True
