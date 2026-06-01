# SPDX-License-Identifier: Apache-2.0
"""Genesis model_configs — vetted, reproducible launch configurations.

A model_config is the **single source of truth** for one (model × hw ×
workload) combination. It captures EVERYTHING needed to:

  1. Launch the model (vLLM args + Genesis env + system env + Docker)
  2. Verify it works (`reference_metrics` + `verify_tolerances`)
  3. Track provenance (`verified_on`, `last_validated`, pin info)

Layout:
    builtin/    — ships with the patcher; modified only via PR review
    community/  — community-contributed verified configs
    user/       — operator's local configs (loaded if present, gitignored)

Use (V1 path, deprecated during Phase 9 freeze):
    from vllm.sndr_core.model_configs import load_all, get
    configs = load_all()
    cfg = get('a5000-2x-35b-prod')  # V1 key; emits DeprecationWarning
    print(cfg.to_launch_script())

Use (V2 path, recommended — V1 sunset in progress 2026-06-01):
    from vllm.sndr_core.model_configs.registry_v2 import load_alias
    cfg = load_alias('prod-qwen3.6-35b-balanced')  # V2 preset alias
    print(cfg.to_launch_script())

CLI: `python3 -m vllm.sndr_core.compat.model_config_cli list/show/render/launch/verify`
"""
from .schema import (
    ModelConfig,
    ReferenceMetrics,
    VerifyTolerances,
    HardwareSpec,
    SpecDecodeConfig,
    DockerConfig,
    SchemaError,
    load_yaml,
    dump_yaml,
    validate,
)
from .registry import load_all, get, list_keys

__all__ = [
    "ModelConfig", "ReferenceMetrics", "VerifyTolerances",
    "HardwareSpec", "SpecDecodeConfig", "DockerConfig",
    "SchemaError", "load_yaml", "dump_yaml", "validate",
    "load_all", "get", "list_keys",
]
