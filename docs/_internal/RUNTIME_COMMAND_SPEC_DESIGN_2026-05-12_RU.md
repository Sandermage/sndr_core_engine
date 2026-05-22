# RuntimeCommandSpec — единый контракт для всех runtime emitters

**Дата:** 2026-05-12
**Owner:** sandermage
**Source:** PROJECT_ROADMAP_V2_REVIEW_NOTES §P1.1
**Status:** draft (design only; implementation in roadmap Phase 4.5)

---

## 0. Зачем

Runtime в V2 живет в hardware layer, но без единого объекта-контракта
каждый emitter (Docker/Compose/Quadlet/K8s/Proxmox/bare-metal systemd)
снова начнет ходить в `ModelConfig.docker`, `hardware.runtime.docker`,
`profile.sizing_override` и собирать команду по-своему. Через 3-4
emitter'а наступит дрейф:

- dry-run покажет `--shm-size 8g`, а compose YAML положит `shm_size: 4gb`;
- launcher запустит контейнер с одним IP, docs скажет другой;
- report bundle redact'нет mounts, которые launcher по факту монтирует.

Тогда невозможно одной командой ответить "что именно будет запущено".

`RuntimeCommandSpec` — frozen dataclass, который собирается **один раз**
композером, и из него каждый emitter рендерит свой формат. Это
канонический intermediate representation между layered config и
конкретным runtime.

---

## 1. Контракт

```python
from dataclasses import dataclass, field
from typing import Literal, Optional

@dataclass(frozen=True)
class MountSpec:
    source: str                     # host path
    target: str                     # container path
    mode: Literal["ro", "rw"] = "ro"
    bind: bool = True

@dataclass(frozen=True)
class PortSpec:
    host_port: int
    container_port: int
    protocol: Literal["tcp", "udp"] = "tcp"

@dataclass(frozen=True)
class DeviceSpec:
    host_path: str                  # e.g. /dev/nvidia0
    container_path: Optional[str] = None
    capabilities: list[str] = field(default_factory=list)

@dataclass(frozen=True)
class SecuritySpec:
    selinux_label_disable: bool = False
    cap_add: list[str] = field(default_factory=list)
    cap_drop: list[str] = field(default_factory=list)
    no_new_privileges: bool = True

@dataclass(frozen=True)
class RuntimeCommandSpec:
    """Canonical IR between layered V2 config and concrete runtime emitter.

    Built by `compose_runtime_command(model, hardware, profile, runtime)`
    once. Every emitter (docker, compose, quadlet, k8s, proxmox) takes
    THIS object as input and renders its format. No emitter touches
    raw `ModelConfig.docker` or `hardware.runtime.docker` directly.

    Acceptance: `--dry-run` for every runtime backend produces a
    deterministic, byte-stable text rendering derived from this spec.
    Diff between any two backends shows ONLY the format-specific
    differences (TOML vs YAML vs argv), never semantic ones.
    """
    # Identity
    runtime: Literal["docker", "podman", "compose", "quadlet",
                     "kubernetes", "proxmox", "bare-metal"]
    container_name: str

    # Image
    image: Optional[str]
    image_digest: Optional[str]     # MUST win over `image` for reproducibility

    # Resources
    env: dict[str, str]             # full final env (genesis_env + system_env merged)
    mounts: list[MountSpec]
    ports: list[PortSpec]
    devices: list[DeviceSpec]
    ulimits: dict[str, str]
    shm_size: Optional[str]
    cpu_limit: Optional[str]
    memory_limit: Optional[str]

    # Security
    security: SecuritySpec

    # Command
    command: list[str]              # argv form, e.g. ['vllm', 'serve', ...]
    working_dir: Optional[str] = None
    user: Optional[str] = None

    # Networking
    network_mode: Optional[str] = None
    extra_hosts: dict[str, str] = field(default_factory=dict)
```

**Frozen invariant:** the dataclass is immutable. Emitters render but
do not modify. If a backend genuinely cannot express some field
(e.g. quadlet doesn't support arbitrary ulimits), the emitter raises
`SchemaError` rather than silently dropping the field.

---

## 2. Composer

```python
def compose_runtime_command(
    model: ModelDef,
    hardware: HardwareDef,
    profile: Optional[ProfileDef] = None,
    *,
    runtime_override: Optional[str] = None,
) -> RuntimeCommandSpec:
    """Build the canonical RuntimeCommandSpec from V2 layered config.

    This is the SINGLE place where:
    - genesis_env + system_env get merged into final env
    - container_name template gets expanded
    - mounts get resolved against `${models_dir}` / `${hf_cache}` etc.
    - vllm command argv gets assembled from sizing + capabilities
    """
    ...
```

`compose_runtime_command` is layered on top of existing `compose()`
(which produces V1 `ModelConfig`). One option: have `compose()` return
both `(ModelConfig, RuntimeCommandSpec)` to avoid double-walking the
layers. Decision deferred to Phase 4.5 implementation.

---

## 3. Emitters (every existing surface gets a target)

| Surface | Status | Emitter signature |
|---|---|---|
| Docker argv | exists | `render_docker_argv(spec: RuntimeCommandSpec) -> list[str]` |
| Docker compose YAML | exists | `render_compose_yaml(spec) -> str` |
| Podman quadlet `.container` | exists | `render_quadlet(spec) -> str` |
| Kubernetes manifest | exists | `render_k8s_manifest(spec) -> dict` |
| systemd bare-metal | planned | `render_systemd_unit(spec) -> str` |
| Proxmox LXC plan | planned | `render_proxmox_lxc(spec) -> dict` |
| dry-run text | exists | `render_dry_run(spec) -> str` |
| report bundle (redacted) | exists | `render_report_bundle(spec, redact_rules) -> dict` |
| docs example | exists | `render_docs_example(spec) -> str` |

**Acceptance:** все эти команды берут один и тот же `RuntimeCommandSpec`:

```bash
sndr launch prod-35b --dry-run --runtime docker
sndr launch prod-35b --dry-run --runtime compose
sndr launch prod-35b --dry-run --runtime quadlet
sndr launch prod-35b --dry-run --runtime kubernetes
sndr report bundle --dry-run --redact
```

Diff между outputs показывает только формат, не семантику. Если diff
показывает разные mounts/env/ports — emitter имеет bug.

---

## 4. Migration path

Phase 4.5 (Day 11-12, P1, after Phase 4 CLI work):

1. Add `runtime_command_spec.py` next to `compose.py` (model + composer).
2. Refactor existing Docker emitter to consume `RuntimeCommandSpec`.
3. Acceptance test: byte-identical output to current `--dry-run` for all
   11 V2 aliases (per evidence ledger).
4. Refactor compose/quadlet/k8s emitters one by one in subsequent commits.
5. Bench/report bundle pipelines updated to consume same IR.

Non-goal Phase 4.5: adding Proxmox/systemd emitters. Those land in Phase
8b after V2 acceptance + RuntimeCommandSpec is proven stable.

---

## 5. Risks

| # | Risk | Mitigation |
|---|---|---|
| RCS-1 | Refactor breaks existing launcher byte-equivalence | Acceptance test runs against current `--dry-run` golden output before merge |
| RCS-2 | New emitter authors bypass IR and read raw config | Import-discipline gate (rg in audit-imports): emitters MUST import `RuntimeCommandSpec`, NOT `model_configs.schema` |
| RCS-3 | IR explodes with backend-specific fields | Keep IR minimal; per-backend extensions live in dedicated wrapper structs, never as Optional[Any] in IR |
| RCS-4 | Image vs image_digest priority unclear | Composer ALWAYS prefers image_digest when both set; emitters MUST NOT re-resolve image to tag |

---

## 6. Связи

- Roadmap Phase 4.5 (new, P1).
- Mitigates: A1 (V2 composer drift), R7 (bench reproducibility — same
  IR feeds bench artefact), R3 (private paths leak — report bundle
  redacts a single IR, not N emitters).
- Implements: PROJECT_ROADMAP_V2_REVIEW_NOTES §P1.1.
