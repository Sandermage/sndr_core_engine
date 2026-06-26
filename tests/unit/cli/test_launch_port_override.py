# SPDX-License-Identifier: Apache-2.0
"""B8 — `_maybe_override_port` must not mutate the shared config object.

`sndr launch --port N` applies a port override before rendering. The
config object can come from a process-cached registry; mutating it in
place leaks the override into every subsequent caller in the same
process. The override must operate on a deep copy and return it.
"""
from __future__ import annotations

from sndr.cli.legacy import launch as L
from sndr.model_configs.schema import ModelConfig, HardwareSpec
from sndr.model_configs.types.docker import DockerConfig


def _cfg_with_docker(port: int = 8000) -> ModelConfig:
    return ModelConfig(
        key="test-cfg",
        title="Test",
        description="test",
        schema_version=1,
        maintainer="tests",
        model_path="/models/test",
        hardware=HardwareSpec(
            gpu_match_keys=["rtx a5000"], n_gpus=1,
            min_vram_per_gpu_mib=24000,
        ),
        docker=DockerConfig(image="img:tag", container_name="c", port=port),
    )


def test_override_none_returns_same_object():
    cfg = _cfg_with_docker(8000)
    out = L._maybe_override_port(cfg, None)
    # No override → no copy needed; same object is fine and cheap.
    assert out is cfg
    assert cfg.docker.port == 8000


def test_override_does_not_mutate_original():
    cfg = _cfg_with_docker(8000)
    out = L._maybe_override_port(cfg, 9001)
    # Original config object must be untouched (no cross-caller leak).
    assert cfg.docker.port == 8000, "original config docker.port was mutated"
    # Returned config carries the override.
    assert out is not cfg
    assert out.docker.port == 9001


def test_override_sets_top_level_port_when_present():
    cfg = _cfg_with_docker(8000)
    # ModelConfig has no top-level `port`, but DockerConfig.port must flip.
    out = L._maybe_override_port(cfg, 9100)
    assert out.docker.port == 9100
    assert cfg.docker.port == 8000
