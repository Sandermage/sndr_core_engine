# SPDX-License-Identifier: Apache-2.0
"""Canonical vllm serve command builder for all deployment adapters.

Etap 2.1 (audit 2026-05-12): compose / quadlet / k8s previously had
independent `_container_command` functions that diverged from the canonical
`ModelConfig._build_vllm_cmd` (used by bare-metal `to_launch_script`).
Example of divergence: compose used `vllm serve <path>` (positional)
instead of `vllm serve --model <path>` and did not add `--language-model-only`.

This module is the single source of truth for argv form. Compose/Quadlet/K8s
emitters call `build_runtime_command(cfg).argv`. The bash launch script
receives the same argv via `argv_to_shell(argv)` → string list for joining.

Security note (Etap 0.4 reference): `--api-key` is NOT added to argv.
vLLM picks up `VLLM_API_KEY` from an env var, which is rendered through
compose interpolation / quadlet Environment= / k8s Secret refs.
This prevents leaking the key into process listings / docker inspect.
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .gguf_resolution import resolve_gguf_file

if TYPE_CHECKING:
    from .schema import ModelConfig


__all__ = [
    "RuntimeCommandSpec",
    "build_runtime_command",
    "build_llamacpp_argv",
    "argv_to_shell",
    "LLAMACPP_SERVER_IMAGE",
]


#: Pinned llama.cpp CUDA server image for the single-card GGUF lane. b9246 is
#: the club-3090-validated build (2026-05-20): the rolling ``:server-cuda`` tag
#: regressed at b9282 (broken lib packaging → crash loop, club-3090 #187), so we
#: pin the explicit build the same way they do. MTP (PR #22673) is native in
#: this image — no custom build, no Genesis patches (Genesis is vLLM/Qwen3-Next
#: specific). Bump only after validating a newer build.
LLAMACPP_SERVER_IMAGE = "ghcr.io/ggml-org/llama.cpp:server-cuda-b9246"


@dataclass(frozen=True)
class RuntimeCommandSpec:
    """Canonical engine invocation for a preset.

    `argv` — list of arguments. For the vLLM lane it starts with
    `["vllm", "serve", ...]`; for the llama.cpp lane it starts with
    `["llama-server", ...]`. Used uniformly by all deployment adapters. The
    `test_runtime_command_parity.py` tests guarantee that compose,
    quadlet, k8s and bare-metal emit identical argv.
    """
    argv: list[str] = field(default_factory=list)


def build_runtime_command(cfg: "ModelConfig") -> RuntimeCommandSpec:
    """Build the canonical engine argv from `ModelConfig`.

    Multi-engine dispatch (Phase 1, 2026-06-27): when `cfg.engine ==
    "llama-cpp"` the llama-server GGUF argv is built instead. The vLLM path
    below is UNCHANGED — it fires for `cfg.engine == "vllm"` (the default for
    every existing config), so vLLM presets render byte-identical argv.

    vLLM contract:
      - `argv[0:2] == ["vllm", "serve"]`.
      - `--model <path>` is passed as a named flag (NOT positional).
      - `--api-key` is NOT included (env-based — Etap 0.4).
      - All non-None / truthy ModelConfig flags are converted into
        CLI args in a deterministic order.
      - `vllm_extra_args` are appended at the end (operator override).
    """
    if getattr(cfg, "engine", "vllm") == "llama-cpp":
        return build_llamacpp_argv(cfg)

    argv: list[str] = ["vllm", "serve", "--model", cfg.model_path]

    # Identity / served name
    if cfg.served_model_name:
        argv += ["--served-model-name", cfg.served_model_name]
    if cfg.quantization:
        argv += ["--quantization", cfg.quantization]
    if cfg.kv_cache_dtype:
        argv += ["--kv-cache-dtype", cfg.kv_cache_dtype]

    # Sizing
    argv += ["--max-model-len", str(cfg.max_model_len)]
    argv += ["--gpu-memory-utilization", f"{cfg.gpu_memory_utilization}"]
    argv += ["--max-num-seqs", str(cfg.max_num_seqs)]
    argv += ["--max-num-batched-tokens", str(cfg.max_num_batched_tokens)]
    argv += ["--tensor-parallel-size", str(cfg.hardware.n_gpus)]
    argv += ["--dtype", cfg.dtype]

    # Behavior flags (alphabetic by flag name for deterministic order)
    if cfg.disable_custom_all_reduce:
        argv.append("--disable-custom-all-reduce")
    if cfg.enable_auto_tool_choice:
        argv.append("--enable-auto-tool-choice")
    if cfg.enable_chunked_prefill:
        argv.append("--enable-chunked-prefill")
    if cfg.enable_prefix_caching:
        argv.append("--enable-prefix-caching")
    if cfg.enforce_eager:
        argv.append("--enforce-eager")
    if cfg.language_model_only:
        argv.append("--language-model-only")
    if cfg.trust_remote_code:
        argv.append("--trust-remote-code")

    # Parsers
    if cfg.tool_call_parser:
        argv += ["--tool-call-parser", cfg.tool_call_parser]
    if cfg.reasoning_parser:
        argv += ["--reasoning-parser", cfg.reasoning_parser]

    # Spec decode
    if cfg.spec_decode is not None:
        argv += ["--speculative-config", cfg.spec_decode.to_vllm_arg()]

    # Endpoint
    argv += ["--host", cfg.host]
    container_port = (
        cfg.docker.effective_container_port() if cfg.docker else 8000
    )
    argv += ["--port", str(container_port)]
    # `--api-key` intentionally omitted — see Etap 0.4 (compose secret leak).

    # Offload (club-3090 #58 Path A) — validate() has already rejected hybrid-GDN
    # combinations, so it is safe here to add the flags if they are set.
    if cfg.offload is not None:
        argv.extend(cfg.offload.to_vllm_args())

    # Operator override hatch — last
    argv.extend(cfg.vllm_extra_args)
    return RuntimeCommandSpec(argv=argv)


def build_llamacpp_argv(cfg: "ModelConfig") -> RuntimeCommandSpec:
    """Build the llama-server GGUF argv for an `engine == "llama-cpp"` config.

    Renders the single-card MTP lane the club-3090 contract describes
    (models/qwen3.6-27b/llama-cpp/compose/single/unsloth-q4km/mtp.yml):

        llama-server -m <gguf-file> -ngl 99 -fa on \
          --cache-type-k q4_0 --cache-type-v q4_0 -ub 1024 -np 1 \
          --spec-type draft-mtp --spec-draft-n-max <K> -c <ctx> \
          --host 0.0.0.0 --port <port>

    Hard contract (from the club-3090 README + mtp.yml comments):
      - ``model_path`` is a single GGUF FILE, not an HF directory
        (resolve_gguf_file enforces this — a directory is a config error).
      - ``-ngl 99`` offloads all layers to the GPU; ``-fa on`` enables
        FlashAttention.
      - ``-np 1`` is MANDATORY on a single 24 GB card: ``-np > 1`` divides
        the one GPU's throughput AND auto-disables MTP AND can OOM the
        spec-context buffer. Never raise it for this lane.
      - ``--cache-type-k/-v`` come from ``cfg.kv_cache_dtype`` (q4_0 default
        — densest mainline, Ampere-fast). The vLLM KV format ``turboquant_*``
        is meaningless here, so fall back to q4_0.
      - ``-ub`` (physical microbatch) caps the per-pass activation peak; 1024
        is the cliff-survival default (lowered from 2048; see mtp.yml).
      - ``--spec-type draft-mtp`` + ``--spec-draft-n-max <K>`` engage the
        GGUF-embedded MTP drafter when the config declares an MTP spec-decode.
    """
    gguf_file = resolve_gguf_file(cfg.model_path)

    # KV cache quant: q4_0 is the single-card default. The vLLM-flavoured
    # turboquant_*/fp8_* labels carry no meaning to llama.cpp, so any value
    # that is not a recognised GGUF KV type collapses to q4_0.
    _LLAMACPP_KV_TYPES = {"q4_0", "q5_0", "q8_0", "f16", "bf16"}
    kv_type = (cfg.kv_cache_dtype or "").lower()
    if kv_type not in _LLAMACPP_KV_TYPES:
        kv_type = "q4_0"

    container_port = (
        cfg.docker.effective_container_port() if cfg.docker else 8000
    )

    argv: list[str] = [
        "llama-server",
        "-m", gguf_file,
        "-ngl", "99",          # offload all layers to GPU
        "-fa", "on",           # FlashAttention
        "--cache-type-k", kv_type,
        "--cache-type-v", kv_type,
        "-ub", "1024",         # physical microbatch — cliff-survival default
        "-np", "1",            # MANDATORY single-slot (>1 disables MTP + OOMs)
    ]

    # MTP drafter — engaged when the config declares an MTP spec-decode. The
    # GGUF must be the MTP-enabled build (unsloth/Qwen3.6-27B-MTP-GGUF). K
    # (num_speculative_tokens) maps to --spec-draft-n-max (sweet spot 2).
    spec = cfg.spec_decode
    if spec is not None and getattr(spec, "method", None) == "mtp":
        argv += ["--spec-type", "draft-mtp"]
        n_max = int(getattr(spec, "num_speculative_tokens", 0) or 0)
        if n_max > 0:
            argv += ["--spec-draft-n-max", str(n_max)]

    # Context window — the KV pool size (-c).
    argv += ["-c", str(cfg.max_model_len)]

    # Endpoint. --api-key intentionally omitted (env-based, mirrors the vLLM
    # lane's Etap 0.4 secret-leak guard).
    argv += ["--host", cfg.host, "--port", str(container_port)]

    # Operator override hatch — last (reuses the vLLM extra-args channel so a
    # llama.cpp lane can pass raw llama-server flags without a new field).
    argv.extend(cfg.vllm_extra_args)
    return RuntimeCommandSpec(argv=argv)


def argv_to_shell(argv: list[str]) -> list[str]:
    """Shell-quote each argv entry — for bash join.

    `shlex.quote` correctly escapes spaces, quotes, $, etc. Used by
    `ModelConfig._build_vllm_cmd` for backward-compat (legacy bash launch
    scripts expect the shell-quoted form).
    """
    return [shlex.quote(a) for a in argv]
