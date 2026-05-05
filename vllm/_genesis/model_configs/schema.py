# SPDX-License-Identifier: Apache-2.0
"""ModelConfig schema — comprehensive, YAML-backed, validatable.

Every field needed to reproduce + verify a Genesis launch lives here.
No "stuff scattered across launch scripts" — schema is the contract.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Optional


SCHEMA_VERSION_CURRENT = 1


class SchemaError(ValueError):
    """Raised when a ModelConfig (or sub-component) fails validation."""


# ─── Sub-components ───────────────────────────────────────────────────


@dataclass
class HardwareSpec:
    """GPU + system requirements for the config to apply cleanly."""
    gpu_match_keys: list[str]   # ['rtx a5000', 'a100']
    n_gpus: int
    min_vram_per_gpu_mib: int
    cuda_capability_min: Optional[tuple[int, int]] = None  # (8, 6) for Ampere

    def validate(self) -> None:
        if not self.gpu_match_keys:
            raise SchemaError("HardwareSpec.gpu_match_keys must be non-empty")
        if self.n_gpus < 1:
            raise SchemaError(
                f"HardwareSpec.n_gpus must be >= 1 (got {self.n_gpus})"
            )
        if self.min_vram_per_gpu_mib < 1:
            raise SchemaError(
                "HardwareSpec.min_vram_per_gpu_mib must be > 0"
            )


@dataclass
class SpecDecodeConfig:
    """Speculative decoding setup."""
    method: str  # 'mtp' / 'eagle' / 'ngram' / 'dflash'
    num_speculative_tokens: int

    def validate(self) -> None:
        valid_methods = {"mtp", "eagle", "ngram", "dflash"}
        if self.method not in valid_methods:
            raise SchemaError(
                f"SpecDecodeConfig.method must be one of {valid_methods}, "
                f"got '{self.method}'"
            )
        if self.num_speculative_tokens < 1:
            raise SchemaError(
                "SpecDecodeConfig.num_speculative_tokens must be >= 1"
            )

    def to_vllm_arg(self) -> str:
        """Format for --speculative-config flag."""
        return json.dumps({
            "method": self.method,
            "num_speculative_tokens": self.num_speculative_tokens,
        })


@dataclass
class DockerConfig:
    """Docker container setup."""
    image: str
    container_name: str
    port: int
    shm_size: str = "8g"
    memory_limit: Optional[str] = None  # '64g'
    network: Optional[str] = None
    gpus: str = "all"
    mounts: list[str] = field(default_factory=list)
    extra_run_flags: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not self.image:
            raise SchemaError("DockerConfig.image required")
        if not self.container_name:
            raise SchemaError("DockerConfig.container_name required")


@dataclass
class ReferenceMetrics:
    """Empirically-measured baseline for `verify` to compare against."""
    measured_at: str  # ISO-8601
    bench_method: str
    long_gen_sustained_tps: float
    long_gen_mean_lat_s: float
    short_gen_tps: float
    tool_call_score: str  # '10/10'
    stability_mean_s: float
    stability_cv_pct: float
    concurrent_4_total_s: float
    vram_used_mib_per_gpu: list[int]
    vram_total_mib: int
    genesis_pin: str
    vllm_pin: str


@dataclass
class VerifyTolerances:
    """Acceptable drift before `verify` returns failure."""
    tps_drop_pct_max: float = 5.0       # fail if drop >5%
    tool_call_min: str = "9/10"          # fail if <9/10
    stability_cv_pct_max: float = 6.0    # fail if jitter doubles
    vram_increase_mib_max: int = 2000    # fail if VRAM grew >2 GB

    def validate(self) -> None:
        if self.tps_drop_pct_max < 0:
            raise SchemaError(
                "VerifyTolerances.tps_drop_pct_max must be >= 0"
            )
        if self.stability_cv_pct_max < 0:
            raise SchemaError(
                "VerifyTolerances.stability_cv_pct_max must be >= 0"
            )


# ─── Top-level ModelConfig ────────────────────────────────────────────


@dataclass
class ModelConfig:
    """Complete launch + verify contract for one (model × hw × workload)."""
    # Identity
    key: str                                  # kebab-case stable id
    title: str                                # human-readable
    description: str                          # 1-2 sentences
    schema_version: int                       # bump on breaking changes
    maintainer: str                           # github user
    model_path: str                           # /models/...

    # Hardware (required)
    hardware: HardwareSpec = field(default_factory=lambda: HardwareSpec(
        gpu_match_keys=[], n_gpus=0, min_vram_per_gpu_mib=0,
    ))

    # Provenance
    last_validated: Optional[str] = None      # ISO date
    genesis_pin: Optional[str] = None         # commit SHA
    vllm_pin_required: Optional[str] = None   # exact match check

    # Model
    served_model_name: Optional[str] = None
    quantization: Optional[str] = None
    kv_cache_dtype: Optional[str] = None

    # vLLM serve flags (canonical)
    max_model_len: int = 32768
    gpu_memory_utilization: float = 0.90
    max_num_seqs: int = 2
    max_num_batched_tokens: int = 4096
    enable_chunked_prefill: bool = True
    dtype: str = "float16"
    enforce_eager: bool = False
    disable_custom_all_reduce: bool = True
    language_model_only: bool = True
    trust_remote_code: bool = True

    # Structured output
    enable_auto_tool_choice: bool = True
    tool_call_parser: Optional[str] = None
    reasoning_parser: Optional[str] = None

    # Spec decode
    spec_decode: Optional[SpecDecodeConfig] = None

    # Genesis env (P*, PN*, GENESIS_*)
    genesis_env: dict[str, str] = field(default_factory=dict)

    # System env (PYTORCH_*, VLLM_*, NCCL_*, OMP_*, CUDA_*, TRITON_*)
    system_env: dict[str, str] = field(default_factory=dict)

    # Extra vLLM flags not covered by canonical fields
    vllm_extra_args: list[str] = field(default_factory=list)

    # Docker (if absent, render as bare-metal launch)
    docker: Optional[DockerConfig] = None

    # API
    api_key: str = "genesis-local"
    host: str = "0.0.0.0"

    # Reference + tolerances
    reference_metrics: Optional[ReferenceMetrics] = None
    verify_tolerances: VerifyTolerances = field(
        default_factory=VerifyTolerances)

    # Provenance + notes
    verified_on: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    workload_tag: Optional[str] = None  # 'balanced' / 'long_context' / ...
    lifecycle: str = "stable"  # 'experimental' / 'stable' / 'deprecated'

    # ── Validation + audit ──

    def validate(self) -> None:
        """Hard schema check — raises SchemaError on any violation."""
        if not self.key:
            raise SchemaError("ModelConfig.key required")
        if self.schema_version != SCHEMA_VERSION_CURRENT:
            raise SchemaError(
                f"ModelConfig.schema_version must be {SCHEMA_VERSION_CURRENT} "
                f"(got {self.schema_version})"
            )
        if not re.match(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$", self.key):
            raise SchemaError(
                f"ModelConfig.key must be kebab-case "
                f"(lowercase letters/digits/hyphens), got '{self.key}'"
            )
        if not self.title or not self.description or not self.maintainer:
            raise SchemaError(
                "ModelConfig requires title, description, maintainer"
            )
        if not self.model_path:
            raise SchemaError("ModelConfig.model_path required")
        if self.lifecycle not in ("experimental", "stable", "deprecated"):
            raise SchemaError(
                f"ModelConfig.lifecycle must be one of experimental/stable/"
                f"deprecated (got '{self.lifecycle}')"
            )

        self.hardware.validate()
        if self.spec_decode is not None:
            self.spec_decode.validate()
        if self.docker is not None:
            self.docker.validate()
        self.verify_tolerances.validate()

    def audit(self) -> list[str]:
        """Soft warnings for risky-but-not-invalid configurations.

        Examples: TQ k8v4 + hybrid model without P98, --enable-prefix-
        caching on hybrid GDN, etc. Operator can choose to ignore.
        """
        warnings: list[str] = []
        # TQ k8v4 + hybrid GDN model needs P98 (vs vllm#40941 lock).
        # Hybrid GDN models: 27B Lorbus int4, NOT 35B-A3B-FP8 (dense MoE).
        # Detection: PN59_STREAMING_GDN=1 in env is the canonical signal —
        # operator only enables PN59 on hybrid models.
        if self.kv_cache_dtype == "turboquant_k8v4":
            pn59_on = self.genesis_env.get(
                "GENESIS_ENABLE_PN59_STREAMING_GDN") == "1"
            int4_lorbus = "int4" in self.model_path.lower() and \
                "AutoRound" in self.model_path
            if (pn59_on or int4_lorbus) and \
                    "GENESIS_ENABLE_P98" not in self.genesis_env:
                warnings.append(
                    "P98 should be enabled for TQ k8v4 + hybrid GDN model "
                    "(WorkspaceManager fix vs vllm#40941). "
                    "Add GENESIS_ENABLE_P98=1 to genesis_env."
                )
        # Reference metrics expected for stable lifecycle
        if self.lifecycle == "stable" and self.reference_metrics is None:
            warnings.append(
                "stable lifecycle should have reference_metrics — "
                "operators can't run `verify` without baseline values."
            )
        return warnings

    # ── Render ──

    def to_launch_script(self) -> str:
        """Render this config as an executable bash launch script.

        Output is either docker-based (if self.docker set) or bare-metal
        depending on the config. Either way: env vars exported, vllm
        serve called with all flags."""
        lines = [
            "#!/usr/bin/env bash",
            "# Generated by Genesis model_config:",
            f"#   key:           {self.key}",
            f"#   title:         {self.title}",
            f"#   maintainer:    {self.maintainer}",
            f"#   schema_v:      {self.schema_version}",
        ]
        if self.last_validated:
            lines.append(f"#   last_validated: {self.last_validated}")
        if self.genesis_pin:
            lines.append(f"#   genesis_pin:   {self.genesis_pin}")
        if self.vllm_pin_required:
            lines.append(f"#   vllm_pin:      {self.vllm_pin_required}")
        if self.reference_metrics:
            rm = self.reference_metrics
            lines.append(
                f"#   reference:     {rm.long_gen_sustained_tps:.1f} TPS "
                f"sustained / {rm.tool_call_score} tool / "
                f"CV {rm.stability_cv_pct:.2f}% / "
                f"VRAM {rm.vram_total_mib} MiB"
            )
        for note in self.notes:
            lines.append(f"#   note: {note}")
        lines.extend(["", "set -euo pipefail", ""])

        # System env
        if self.system_env:
            lines.append("# System env")
            for k, v in sorted(self.system_env.items()):
                lines.append(f'export {k}={_shell_quote(v)}')
            lines.append("")

        # Genesis env
        if self.genesis_env:
            lines.append("# Genesis patcher env")
            for k, v in sorted(self.genesis_env.items()):
                lines.append(f'export {k}={_shell_quote(v)}')
            lines.append("")

        # Build vllm serve cmd
        cmd_parts = self._build_vllm_cmd()

        # Docker or bare-metal launch
        if self.docker:
            lines.append("# Docker launch")
            docker_cmd = self._build_docker_cmd(cmd_parts)
            lines.append(docker_cmd)
        else:
            lines.append("# Bare-metal launch")
            lines.append("exec " + " \\\n  ".join(cmd_parts))

        return "\n".join(lines) + "\n"

    def _build_vllm_cmd(self) -> list[str]:
        """vllm serve command parts (without exec/docker prefix)."""
        parts = [
            "vllm serve",
            f"--model {self.model_path}",
            f"--tensor-parallel-size {self.hardware.n_gpus}",
            f"--gpu-memory-utilization {self.gpu_memory_utilization}",
            f"--max-model-len {self.max_model_len}",
            f"--max-num-seqs {self.max_num_seqs}",
            f"--max-num-batched-tokens {self.max_num_batched_tokens}",
            f"--dtype {self.dtype}",
        ]
        if self.kv_cache_dtype:
            parts.append(f"--kv-cache-dtype {self.kv_cache_dtype}")
        if self.quantization:
            parts.append(f"--quantization {self.quantization}")
        if self.served_model_name:
            parts.append(f"--served-model-name {self.served_model_name}")
        if self.tool_call_parser:
            parts.append(f"--tool-call-parser {self.tool_call_parser}")
        if self.reasoning_parser:
            parts.append(f"--reasoning-parser {self.reasoning_parser}")
        if self.enable_chunked_prefill:
            parts.append("--enable-chunked-prefill")
        if self.enforce_eager:
            parts.append("--enforce-eager")
        if self.disable_custom_all_reduce:
            parts.append("--disable-custom-all-reduce")
        if self.language_model_only:
            parts.append("--language-model-only")
        if self.trust_remote_code:
            parts.append("--trust-remote-code")
        if self.enable_auto_tool_choice:
            parts.append("--enable-auto-tool-choice")
        parts.append(f"--api-key {self.api_key}")
        parts.append(f"--host {self.host}")
        if self.docker:
            parts.append(f"--port {self.docker.port}")
        if self.spec_decode:
            parts.append(
                f"--speculative-config '{self.spec_decode.to_vllm_arg()}'"
            )
        for extra in self.vllm_extra_args:
            parts.append(extra)
        return parts

    def _build_docker_cmd(self, vllm_parts: list[str]) -> str:
        """Render docker run command embedding the vllm serve."""
        d = self.docker
        lines = [
            f"docker rm -f {d.container_name} 2>/dev/null || true",
            "",
            "docker run -d \\",
            f"  --name {d.container_name} \\",
            "  --entrypoint /bin/bash \\",
            f"  --gpus {d.gpus} \\",
            f"  --shm-size={d.shm_size} \\",
        ]
        if d.memory_limit:
            lines.append(f"  --memory={d.memory_limit} \\")
        if d.network:
            lines.append(f"  --network {d.network} \\")
        lines.append(f"  -p {d.port}:{d.port} \\")
        for m in d.mounts:
            lines.append(f"  -v {m} \\")
        for f in d.extra_run_flags:
            lines.append(f"  {f} \\")
        # Env vars
        for k, v in sorted(self.system_env.items()):
            lines.append(f'  -e {k}={_shell_quote(v)} \\')
        for k, v in sorted(self.genesis_env.items()):
            lines.append(f"  -e {k}={v} \\")
        # Image + cmd
        lines.append(f"  {d.image} \\")
        # Bash -c with apply_all + exec vllm serve
        cmd = " ".join(vllm_parts)
        lines.append(
            f"  -c 'set -e; "
            f"python3 -m vllm._genesis.patches.apply_all 2>&1 | tail -5; "
            f"exec {cmd}'"
        )
        return "\n".join(lines)


# ─── YAML I/O ─────────────────────────────────────────────────────────


def dump_yaml(cfg: ModelConfig) -> str:
    """Serialize ModelConfig → YAML string."""
    import yaml
    cfg.validate()
    d = _to_plain_dict(cfg)
    return yaml.safe_dump(d, sort_keys=False, allow_unicode=True,
                          default_flow_style=False)


def load_yaml(text: str) -> ModelConfig:
    """Parse YAML string → ModelConfig with full validation."""
    import yaml
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise SchemaError("YAML must be a mapping at top level")
    return _from_plain_dict(raw)


def validate(cfg: ModelConfig) -> ModelConfig:
    """Validate ModelConfig in-place; raise SchemaError on issues.
    Returns the validated config for chainable use."""
    cfg.validate()
    return cfg


# ─── Internal helpers ─────────────────────────────────────────────────


def _shell_quote(value: str) -> str:
    """Conservative shell quoting for env-var values."""
    if not value or any(c in value for c in (' ', '"', "'", '$', '`', '\\')):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def _to_plain_dict(cfg: ModelConfig) -> dict:
    return asdict(cfg)


def _from_plain_dict(d: dict) -> ModelConfig:
    """Reconstruct ModelConfig from plain dict (post-YAML-load)."""
    known = {f.name for f in fields(ModelConfig)}
    unknown = set(d.keys()) - known
    if unknown:
        raise SchemaError(
            f"unknown field(s) in ModelConfig YAML: {sorted(unknown)}. "
            f"Known: {sorted(known)}"
        )

    # Sub-component reconstruction
    if "hardware" in d and isinstance(d["hardware"], dict):
        d["hardware"] = HardwareSpec(**d["hardware"])
    if "spec_decode" in d and isinstance(d["spec_decode"], dict):
        d["spec_decode"] = SpecDecodeConfig(**d["spec_decode"])
    if "docker" in d and isinstance(d["docker"], dict):
        d["docker"] = DockerConfig(**d["docker"])
    if "reference_metrics" in d and isinstance(d["reference_metrics"], dict):
        d["reference_metrics"] = ReferenceMetrics(**d["reference_metrics"])
    if "verify_tolerances" in d and isinstance(d["verify_tolerances"], dict):
        d["verify_tolerances"] = VerifyTolerances(**d["verify_tolerances"])

    cfg = ModelConfig(**d)
    cfg.validate()
    return cfg
