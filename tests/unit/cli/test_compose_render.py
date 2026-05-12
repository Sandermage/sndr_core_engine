# SPDX-License-Identifier: Apache-2.0
"""S3.1 closure (audit P3-1, 2026-05-12): тесты для `sndr compose render`.

Покрывают:

  • Хедер содержит preset key + maintainer + usage hint.
  • yaml.safe_load result — dict с правильной топологией
    (`services.vllm-server.{image,container_name,ports,...}`).
  • genesis_env + system_env слиты в `environment` block.
  • GPU reservation присутствует с правильным count.
  • Mount substitution из host_paths применяется.
  • Hermetic — не требует docker / kubectl / реального registry,
    использует синтетический ModelConfig.
"""
from __future__ import annotations

import pytest

yaml = pytest.importorskip("yaml")

from vllm.sndr_core.cli.compose import render_compose_yaml
from vllm.sndr_core.model_configs.schema import (
    DockerConfig, HardwareSpec, ModelConfig,
)


def _make_cfg(**overrides) -> ModelConfig:
    base = dict(
        key="test-compose", title="Test Compose",
        description="d", schema_version=1, maintainer="x",
        model_path="/models/Test-7B",
        hardware=HardwareSpec(
            gpu_match_keys=["test"], n_gpus=2,
            min_vram_per_gpu_mib=24576,
        ),
        max_model_len=8192,
        gpu_memory_utilization=0.92,
        max_num_seqs=4,
        max_num_batched_tokens=4096,
        genesis_env={"GENESIS_ENABLE_P67_TQ_MULTI_QUERY_KERNEL": "1"},
        system_env={"PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"},
        docker=DockerConfig(
            image="vllm/vllm-openai:nightly",
            container_name="vllm-test",
            port=8000,
            shm_size="8g",
            network="genesis-net",
            mounts=[
                "${models_dir}:/models:ro",
                "/etc/hosts:/etc/hosts:ro",
            ],
        ),
    )
    base.update(overrides)
    return ModelConfig(**base)


class TestRenderCompose:
    def test_header_mentions_preset_key(self):
        cfg = _make_cfg()
        out = render_compose_yaml(cfg, host_paths={})
        assert "sndr compose render test-compose" in out
        assert "Maintainer: x" in out

    def test_yaml_parses(self):
        cfg = _make_cfg()
        out = render_compose_yaml(cfg, host_paths={})
        # safe_load skip-ит header comments — должен дать dict.
        parsed = yaml.safe_load(out)
        assert "services" in parsed
        assert "vllm-server" in parsed["services"]

    def test_image_and_container_name(self):
        cfg = _make_cfg()
        parsed = yaml.safe_load(render_compose_yaml(cfg, host_paths={}))
        svc = parsed["services"]["vllm-server"]
        assert svc["image"] == "vllm/vllm-openai:nightly"
        assert svc["container_name"] == "vllm-test"

    def test_port_mapping(self):
        cfg = _make_cfg()
        parsed = yaml.safe_load(render_compose_yaml(cfg, host_paths={}))
        ports = parsed["services"]["vllm-server"]["ports"]
        assert any("8000:8000" in str(p) for p in ports)

    def test_environment_combines_system_and_genesis(self):
        cfg = _make_cfg()
        parsed = yaml.safe_load(render_compose_yaml(cfg, host_paths={}))
        env = parsed["services"]["vllm-server"]["environment"]
        assert env["PYTORCH_CUDA_ALLOC_CONF"] == "expandable_segments:True"
        assert env["GENESIS_ENABLE_P67_TQ_MULTI_QUERY_KERNEL"] == "1"

    def test_volumes_substituted(self):
        cfg = _make_cfg()
        out = render_compose_yaml(cfg, host_paths={"models_dir": "/srv/models"})
        parsed = yaml.safe_load(out)
        vols = parsed["services"]["vllm-server"]["volumes"]
        joined = "\n".join(vols)
        assert "/srv/models:/models:ro" in joined
        # second mount без substitution — должен остаться как есть
        assert "/etc/hosts:/etc/hosts:ro" in joined

    def test_command_starts_with_vllm_serve(self):
        cfg = _make_cfg()
        parsed = yaml.safe_load(render_compose_yaml(cfg, host_paths={}))
        cmd = parsed["services"]["vllm-server"]["command"]
        assert cmd[0:2] == ["vllm", "serve"]
        assert cmd[2] == "/models/Test-7B"
        # tensor-parallel-size берётся из hardware.n_gpus
        i = cmd.index("--tensor-parallel-size")
        assert cmd[i + 1] == "2"

    def test_gpu_reservation_in_deploy(self):
        cfg = _make_cfg()
        parsed = yaml.safe_load(render_compose_yaml(cfg, host_paths={}))
        deploy = parsed["services"]["vllm-server"]["deploy"]
        devices = deploy["resources"]["reservations"]["devices"]
        assert devices[0]["driver"] == "nvidia"
        assert devices[0]["count"] == 2
        assert "gpu" in devices[0]["capabilities"]

    def test_network_block_external(self):
        cfg = _make_cfg()
        parsed = yaml.safe_load(render_compose_yaml(cfg, host_paths={}))
        assert parsed["networks"]["genesis-net"]["external"] is True
        assert "genesis-net" in parsed["services"]["vllm-server"]["networks"]

    def test_no_docker_block_raises(self):
        cfg = _make_cfg(docker=None)
        with pytest.raises(ValueError, match="no docker block"):
            render_compose_yaml(cfg, host_paths={})

    def test_idempotent_render(self):
        cfg = _make_cfg()
        a = render_compose_yaml(cfg, host_paths={"models_dir": "/srv/m"})
        b = render_compose_yaml(cfg, host_paths={"models_dir": "/srv/m"})
        assert a == b


# ─── Etap 0.4 — secret-leak prevention ──────────────────────────────────


class TestApiKeyNotLeaked:
    """Etap 0.4 (audit 2026-05-12): API key никогда не должен попасть
    в rendered compose как literal value. Compose interpolation
    `${VLLM_API_KEY:?...}` подтянет его из shell env / .env во время
    `docker compose up`.

    Раньше `cfg.api_key` шёл в две места:
      • `service.environment.VLLM_API_KEY=<literal>` — теперь interpolation.
      • `service.command: ["--api-key", <literal>]` — теперь убрано
        (vLLM подхватывает из env var).
    """

    SECRET = "super-secret-token-NEVER-LEAK-ME"

    def _cfg_with_key(self):
        cfg = _make_cfg()
        cfg.api_key = self.SECRET
        return cfg

    def test_literal_secret_not_in_yaml(self):
        out = render_compose_yaml(self._cfg_with_key(), host_paths={})
        assert self.SECRET not in out, (
            "API key literal found in rendered YAML — Etap 0.4 fix regression"
        )

    def test_env_uses_compose_interpolation(self):
        parsed = yaml.safe_load(
            render_compose_yaml(self._cfg_with_key(), host_paths={})
        )
        env = parsed["services"]["vllm-server"]["environment"]
        assert "VLLM_API_KEY" in env
        # Значение — interpolation reference, не literal
        assert env["VLLM_API_KEY"].startswith("${VLLM_API_KEY")
        assert self.SECRET not in env["VLLM_API_KEY"]

    def test_api_key_not_in_command(self):
        parsed = yaml.safe_load(
            render_compose_yaml(self._cfg_with_key(), host_paths={})
        )
        cmd = parsed["services"]["vllm-server"]["command"]
        assert "--api-key" not in cmd
        assert self.SECRET not in " ".join(cmd)

    def test_header_documents_secret_flow(self):
        out = render_compose_yaml(self._cfg_with_key(), host_paths={})
        # Header должен подсказать operator'у как передать ключ
        assert "VLLM_API_KEY" in out.split("services:")[0]
        # Mention `.env` или shell env
        header = out.split("services:")[0]
        assert ".env" in header or "shell env" in header.lower()


class TestTempdirPermissions:
    """Etap 0.4: defense-in-depth — `/tmp/sndr-compose/` всегда `0o700`,
    rendered YAML — `0o600`, даже если directory уже существовала."""

    def test_tempdir_chmod_0o700(self, monkeypatch, tmp_path):
        from vllm.sndr_core.cli import compose as C
        # Подменяем tempfile.gettempdir, чтобы тест не трогал реальный /tmp
        monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
        # Pre-create dir с broad mode — fix должен изменить на 0o700
        precreated = tmp_path / "sndr-compose"
        precreated.mkdir(mode=0o755)
        cfg = _make_cfg()
        cfg.api_key = "leak-test"
        path = C._write_temp_compose(cfg)
        assert path.is_file()
        assert (precreated.stat().st_mode & 0o777) == 0o700
        assert (path.stat().st_mode & 0o777) == 0o600
        # File не должен содержать literal API key
        assert "leak-test" not in path.read_text()
