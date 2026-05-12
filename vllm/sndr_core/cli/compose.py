# SPDX-License-Identifier: Apache-2.0
"""S3.1 (UNIFIED_CONFIG plan 2026-05-09; audit P3-1 closure 2026-05-12):
`sndr compose render/up/down/logs` — docker-compose renderer и thin
wrapper над `docker compose` CLI.

Зачем
-----
Раньше Genesis генерировал ТОЛЬКО bash launch-script через
`ModelConfig.to_launch_script()`. Community feedback (issue X-COMPOSE):
operator'ы интегрируют Genesis в существующий compose stack и хотят
получить готовый `docker-compose.yml` со всеми патчами и env'ами,
а не вручную переводить bash script в compose.

`sndr compose render <preset>` — обратимый renderer:

  • Берёт ModelConfig из registry.
  • Эмитит `docker-compose.yml` с правильным image, container_name,
    ports, environment (genesis_env + system_env + патчевые knobs),
    volumes (mounts с host.yaml resolution), command (vllm serve
    flags). Использует yaml.safe_dump для корректной escapes
    (избегаем string concatenation footguns).
  • Идемпотентно: повторный render с тем же input даёт тот же output.

`sndr compose up/down/logs` — тонкая обёртка над `docker compose -f
<rendered> up/down/logs`, для удобства operator'а. Если operator
интегрирует output в свой stack — этими командами можно не пользоваться.

Test contract — `tests/unit/cli/test_compose_render.py`:

  • Render canonical 27B PROD config → результат содержит ожидаемые
    image / container / ports / env / volumes / command.
  • yaml.safe_load(render) returns dict (proves it's parseable).
  • Hermetic: не требует docker installed.
  • render --output путь записывает файл с тем же содержимым.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from . import _io


__all__ = [
    "add_argparser", "render_compose_yaml",
    "run_compose_render", "run_compose_up",
    "run_compose_down", "run_compose_logs",
]


def add_argparser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "compose",
        help="docker-compose renderer + thin wrapper (audit P3-1).",
        description=(
            "Render а preset как готовый docker-compose.yml, или "
            "запустить/остановить/получить логи через docker compose. "
            "Альтернатива `sndr launch` для operator'ов, интегрирующих "
            "Genesis в существующий compose stack."
        ),
    )
    sub = p.add_subparsers(dest="compose_cmd", required=True)

    # render
    p_render = sub.add_parser(
        "render", help="Render preset → docker-compose.yml на stdout/файл",
    )
    p_render.add_argument("config", help="preset key")
    p_render.add_argument(
        "-o", "--output", default=None,
        help="Записать в файл вместо stdout.",
    )
    p_render.set_defaults(func=run_compose_render)

    # up
    p_up = sub.add_parser("up", help="docker compose up -d (renders inline)")
    p_up.add_argument("config", help="preset key")
    p_up.add_argument(
        "--detach", "-d", action="store_true", default=True,
        help="detached mode (default true)",
    )
    p_up.set_defaults(func=run_compose_up)

    # down
    p_down = sub.add_parser("down", help="docker compose down")
    p_down.add_argument("config", help="preset key")
    p_down.set_defaults(func=run_compose_down)

    # logs
    p_logs = sub.add_parser("logs", help="docker compose logs -f")
    p_logs.add_argument("config", help="preset key")
    p_logs.add_argument(
        "-n", "--lines", default="100",
        help="how many lines to tail (default 100)",
    )
    p_logs.add_argument(
        "-f", "--follow", action="store_true",
        help="follow log output",
    )
    p_logs.set_defaults(func=run_compose_logs)


def _resolve(key: str):
    from vllm.sndr_core.model_configs.registry import get
    cfg = get(key)
    if cfg is None:
        _io.error(f"unknown preset key {key!r}")
        return None
    return cfg


# ──── Render ───────────────────────────────────────────────────────────


def _load_host_paths() -> dict[str, str]:
    """Читает host.yaml для resolve mount paths. Не падает если файла нет."""
    try:
        from vllm.sndr_core.model_configs.host import load_host_config
        hc = load_host_config()
        if hc is None:
            return {}
        return hc.symbolic_mounts or {}
    except Exception:
        return {}


def _resolve_mount(mount_spec: str, host_paths: dict[str, str]) -> str:
    """Применяет host.yaml substitution к `${var}:/container_path:mode`."""
    out = mount_spec
    for var, path in host_paths.items():
        out = out.replace(f"${{{var}}}", path)
        out = out.replace(f"${var}", path)
    return out


def _container_command(cfg) -> list[str]:
    """Реконструирует `vllm serve …` команду из ModelConfig.

    Использует ту же логику что `ModelConfig.to_launch_script` —
    но возвращает список аргументов (для compose command:).
    """
    args: list[str] = ["vllm", "serve", cfg.model_path]
    if cfg.served_model_name:
        args += ["--served-model-name", cfg.served_model_name]
    if cfg.quantization:
        args += ["--quantization", cfg.quantization]
    if cfg.kv_cache_dtype:
        args += ["--kv-cache-dtype", cfg.kv_cache_dtype]
    args += ["--max-model-len", str(cfg.max_model_len)]
    args += ["--gpu-memory-utilization", f"{cfg.gpu_memory_utilization:.2f}"]
    args += ["--max-num-seqs", str(cfg.max_num_seqs)]
    args += ["--max-num-batched-tokens", str(cfg.max_num_batched_tokens)]
    args += ["--tensor-parallel-size", str(cfg.hardware.n_gpus)]
    args += ["--dtype", cfg.dtype]
    if cfg.enable_chunked_prefill:
        args.append("--enable-chunked-prefill")
    if cfg.enforce_eager:
        args.append("--enforce-eager")
    if cfg.disable_custom_all_reduce:
        args.append("--disable-custom-all-reduce")
    if cfg.trust_remote_code:
        args.append("--trust-remote-code")
    if cfg.tool_call_parser:
        args += ["--tool-call-parser", cfg.tool_call_parser]
    if cfg.reasoning_parser:
        args += ["--reasoning-parser", cfg.reasoning_parser]
    if cfg.enable_auto_tool_choice:
        args.append("--enable-auto-tool-choice")
    if cfg.spec_decode is not None:
        args += ["--speculative-config", cfg.spec_decode.to_vllm_arg()]
    # Etap 0.4 (audit 2026-05-12): `--api-key` НЕ добавляется в command —
    # vLLM подхватывает ключ из env var `VLLM_API_KEY`, который рендерится
    # через compose interpolation (см. `render_compose_yaml`). Раньше
    # `--api-key <literal>` утекало в process listing / docker inspect.
    args += ["--host", cfg.host]
    args += [
        "--port",
        str(cfg.docker.effective_container_port() if cfg.docker else 8000),
    ]
    if cfg.vllm_extra_args:
        args.extend(cfg.vllm_extra_args)
    return args


def render_compose_yaml(cfg, host_paths: Optional[dict[str, str]] = None) -> str:
    """Рендерит ModelConfig в docker-compose.yml.

    Args:
        cfg: ModelConfig из registry.
        host_paths: optional substitution table для `${var}` в mounts.
            None → попытка прочитать host.yaml.
    """
    try:
        import yaml
    except ImportError as e:
        raise RuntimeError(
            "compose render requires `pyyaml` — `pip install pyyaml`"
        ) from e

    if host_paths is None:
        host_paths = _load_host_paths()

    docker = cfg.docker
    if docker is None:
        raise ValueError(
            f"preset {cfg.key!r} has no docker block — compose "
            "requires a container image / name / port. Add a "
            "DockerConfig to the model_config YAML."
        )

    container_name = docker.container_name or f"sndr-{cfg.key}"
    image = docker.effective_image_ref()
    host_port = docker.effective_host_port()
    container_port = docker.effective_container_port()

    # Environment: combine system_env, genesis_env. Все values как
    # строки — compose требует string-valued env vars.
    env: dict[str, str] = {}
    for k, v in cfg.system_env.items():
        env[str(k)] = str(v)
    for k, v in cfg.genesis_env.items():
        env[str(k)] = str(v)
    # Etap 0.4 (audit 2026-05-12): VLLM_API_KEY рендерится как compose
    # interpolation reference `${VLLM_API_KEY:?...}`, а не literal value.
    # Docker Compose разрешит его из shell env / `.env` файла в момент
    # `compose up`. Литерал в YAML больше не появляется → нет утечки
    # ключа через файл в /tmp.
    if cfg.api_key:
        env.setdefault(
            "VLLM_API_KEY",
            "${VLLM_API_KEY:?VLLM_API_KEY env required — "
            "export in shell or .env file before `docker compose up`}",
        )

    volumes_resolved = [
        _resolve_mount(m, host_paths)
        for m in (docker.mounts or [])
    ]

    service: dict[str, Any] = {
        "image": image,
        "container_name": container_name,
        "restart": "unless-stopped",
        "ports": [f"{host_port}:{container_port}"],
        "environment": env,
        "command": _container_command(cfg),
    }
    if volumes_resolved:
        service["volumes"] = volumes_resolved
    if docker.shm_size:
        service["shm_size"] = docker.shm_size
    if docker.network:
        service["networks"] = [docker.network]
    # GPU access — Docker Compose Spec deploy.resources.reservations.devices.
    service["deploy"] = {
        "resources": {
            "reservations": {
                "devices": [{
                    "driver": "nvidia",
                    "count": cfg.hardware.n_gpus,
                    "capabilities": ["gpu"],
                }],
            },
        },
    }

    compose: dict[str, Any] = {
        "services": {"vllm-server": service},
    }
    if docker.network:
        compose["networks"] = {docker.network: {"external": True}}

    header = (
        f"# Generated by `sndr compose render {cfg.key}` — "
        f"DO NOT edit by hand.\n"
        f"# Re-run `sndr compose render {cfg.key}` to refresh.\n"
        f"# Source preset: {cfg.key} ({cfg.title})\n"
        f"# Maintainer: {cfg.maintainer}\n"
        f"#\n"
        f"# Secrets (Etap 0.4 hardening): VLLM_API_KEY НЕ записан в YAML.\n"
        f"# Вместо литерала используется `${{VLLM_API_KEY:?...}}` — compose\n"
        f"# подтянет значение из shell env или `.env` файла рядом с этим YAML.\n"
        f"# Запуск:\n"
        f"#   VLLM_API_KEY=mykey docker compose -f docker-compose.yml up -d\n"
        f"# ИЛИ положить `VLLM_API_KEY=mykey` в `.env` (chmod 0600!)\n"
        f"#\n"
        f"# Usage через sndr:\n"
        f"#   sndr compose up {cfg.key}      # equivalent to docker compose up -d\n"
        f"#   sndr compose logs {cfg.key} -f\n"
        f"#   sndr compose down {cfg.key}\n"
        f"#\n"
    )
    body = yaml.safe_dump(compose, sort_keys=False, default_flow_style=False)
    return header + body


def run_compose_render(args: argparse.Namespace) -> int:
    cfg = _resolve(args.config)
    if cfg is None:
        return 2
    out = render_compose_yaml(cfg)
    if args.output:
        Path(args.output).write_text(out)
        _io.info(f"wrote {args.output} ({len(out)} bytes)")
    else:
        print(out)
    return 0


# ──── docker compose wrappers ─────────────────────────────────────────


def _write_temp_compose(cfg) -> Path:
    """Рендерит compose в temp dir и возвращает путь.

    Etap 0.4 (audit 2026-05-12): tempdir всегда `0o700` — даже если он
    уже существует (mkdir(mode=...) не меняет mode existing dir).
    rendered YAML — `0o600`. Defense-in-depth на multi-user host'е.
    """
    import os
    import tempfile
    out = render_compose_yaml(cfg)
    tmpdir = Path(tempfile.gettempdir()) / "sndr-compose"
    tmpdir.mkdir(parents=True, exist_ok=True)
    os.chmod(tmpdir, 0o700)
    path = tmpdir / f"docker-compose.{cfg.key}.yml"
    path.write_text(out)
    os.chmod(path, 0o600)
    return path


def _docker_compose(*args, dry_run: bool = False) -> int:
    if shutil.which("docker") is None:
        _io.error("docker not on PATH")
        return 1
    cmd = ["docker", "compose"] + list(args)
    if dry_run:
        _io.info(f"[dry-run] {' '.join(cmd)}")
        return 0
    r = subprocess.run(cmd)
    return r.returncode


def run_compose_up(args: argparse.Namespace) -> int:
    cfg = _resolve(args.config)
    if cfg is None:
        return 2
    path = _write_temp_compose(cfg)
    _io.info(f"using compose file: {path}")
    return _docker_compose("-f", str(path), "up", "-d")


def run_compose_down(args: argparse.Namespace) -> int:
    cfg = _resolve(args.config)
    if cfg is None:
        return 2
    path = _write_temp_compose(cfg)
    return _docker_compose("-f", str(path), "down")


def run_compose_logs(args: argparse.Namespace) -> int:
    cfg = _resolve(args.config)
    if cfg is None:
        return 2
    path = _write_temp_compose(cfg)
    extra = ["--tail", args.lines]
    if args.follow:
        extra.append("-f")
    return _docker_compose("-f", str(path), "logs", *extra)
