# SPDX-License-Identifier: Apache-2.0
"""S3.2 closure (audit P3-2, 2026-05-12): тесты для `sndr quadlet render`.

Покрывают:

  • Все обязательные секции (`[Unit]`, `[Container]`, `[Service]`,
    `[Install]`).
  • Image / ContainerName / PublishPort правильные.
  • Environment line per env var (system + genesis).
  • Volume substitution через host_paths.
  • Exec= одна строка с shlex-quoted args.
  • GPU device line присутствует.
  • Идемпотентность.
"""
from __future__ import annotations

import pytest

from vllm.sndr_core.cli.quadlet import render_quadlet
from vllm.sndr_core.model_configs.schema import (
    DockerConfig, HardwareSpec, ModelConfig,
)


def _make_cfg(**overrides) -> ModelConfig:
    base = dict(
        key="test-quad", title="Test Quadlet",
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
            container_name="vllm-quad-test",
            port=8000,
            shm_size="8g",
            mounts=[
                "${models_dir}:/models:ro",
            ],
        ),
    )
    base.update(overrides)
    return ModelConfig(**base)


class TestRenderQuadlet:
    def test_all_sections_present(self):
        out = render_quadlet(_make_cfg(), host_paths={})
        for section in ("[Unit]", "[Container]", "[Service]", "[Install]"):
            assert section in out

    def test_image_and_container_lines(self):
        out = render_quadlet(_make_cfg(), host_paths={})
        assert "Image=vllm/vllm-openai:nightly" in out
        assert "ContainerName=vllm-quad-test" in out
        assert "PublishPort=8000:8000" in out

    def test_env_lines_one_per_var(self):
        out = render_quadlet(_make_cfg(), host_paths={})
        assert (
            "Environment=PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True"
            in out
        )
        assert (
            "Environment=GENESIS_ENABLE_P67_TQ_MULTI_QUERY_KERNEL=1"
            in out
        )

    def test_volume_substituted(self):
        out = render_quadlet(_make_cfg(), host_paths={"models_dir": "/srv/m"})
        assert "Volume=/srv/m:/models:ro" in out

    def test_exec_single_line_with_vllm_serve(self):
        out = render_quadlet(_make_cfg(), host_paths={})
        exec_lines = [
            line for line in out.splitlines() if line.startswith("Exec=")
        ]
        assert len(exec_lines) == 1
        assert exec_lines[0].startswith("Exec=vllm serve ")

    def test_gpu_device_line(self):
        out = render_quadlet(_make_cfg(), host_paths={})
        assert "AddDevice=nvidia.com/gpu=all" in out

    def test_shm_size_line(self):
        out = render_quadlet(_make_cfg(), host_paths={})
        assert "ShmSize=8g" in out

    def test_no_docker_raises(self):
        with pytest.raises(ValueError, match="no docker block"):
            render_quadlet(_make_cfg(docker=None), host_paths={})

    def test_idempotent(self):
        a = render_quadlet(_make_cfg(), host_paths={"models_dir": "/srv/m"})
        b = render_quadlet(_make_cfg(), host_paths={"models_dir": "/srv/m"})
        assert a == b

    def test_restart_on_failure(self):
        out = render_quadlet(_make_cfg(), host_paths={})
        assert "Restart=on-failure" in out

    def test_wanted_by_default_target(self):
        out = render_quadlet(_make_cfg(), host_paths={})
        assert "WantedBy=default.target" in out
