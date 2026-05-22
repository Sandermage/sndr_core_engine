# SNDR Core - план улучшения единых конфигов, инсталлятора и автоматизации

Дата: 2026-05-09  
Статус: план реализации, код проекта не изменялся  
Цель: сделать `sndr` не просто патчером, а управляемой системой развертывания vLLM: единый конфиг должен описывать модель, Docker/Podman/bare-metal runtime, версии зависимостей, источники пакетов, артефакты модели, preflight, установку и проверку.

## 1. Короткий вывод

Текущая архитектура уже близко подошла к правильному направлению:

- `install.sh` стал тонким bootstrap-скриптом и передает работу в `sndr install`.
- `sndr` уже имеет единый CLI: `install`, `launch`, `doctor`, `verify`, `model-config`, `memory`, `patches`, `report`, `bench-compare` и bridged compat-команды.
- `ModelConfig` уже содержит модельные параметры, Docker-блок, `deploy`, `genesis_env`, `system_env`, `reference_metrics`, `constraints`.
- `model_configs/preflight.py` уже проверяет mounts, контейнер, image presence, GPU count/VRAM, `genesis_pin`, stale compile cache.
- `known_good_images` уже появился как правильная идея для контроля digest/pin.

Главный недостающий слой: нет полноценного "deployment contract". Сейчас конфиг отвечает на вопрос "как запустить vLLM", но не отвечает полно на вопросы:

- какие системные пакеты нужны;
- какая версия Docker/Podman/containerd нужна;
- нужен ли `nvidia-container-toolkit` и какой версии;
- какая версия Python/uv/pip допустима;
- какая версия vLLM должна быть скачана, из какого источника и каким способом;
- какой Docker image допустим: tag, digest, known-good, custom build;
- какие Python-пакеты должны быть внутри container/venv;
- какие модели/ревизии надо скачать и куда;
- какие проверки обязательны до запуска;
- какие исправления installer может предложить автоматически, а какие только показать оператору.

Рекомендация: оставить `install.sh` минимальным, а весь интеллект перенести в новый слой `sndr deps` / `sndr doctor system` / `sndr install --prepare`. Единый YAML должен стать source of truth для модели, runtime, зависимостей, артефактов и политики установки.

## 2. Что проверено в этом проходе

Рабочая папка:

```text
/Users/sander/Documents/Visual Studio Code/genesis-vllm-patches
```

Проверенные локальные области:

- `install.sh`
- `pyproject.toml`
- `vllm/sndr_core/cli/install.py`
- `vllm/sndr_core/cli/launch.py`
- `vllm/sndr_core/cli/__init__.py`
- `vllm/sndr_core/model_configs/schema.py`
- `vllm/sndr_core/model_configs/preflight.py`
- `vllm/sndr_core/model_configs/host.py`
- `vllm/sndr_core/model_configs/registry.py`
- `vllm/sndr_core/model_configs/builtin/*.yaml`
- `vllm/sndr_core/compat/model_config_cli.py`
- `vllm/sndr_core/compat/preflight_checks.py`
- `vllm/sndr_core/compat/doctor.py`
- `vllm/sndr_core/compat/version_check.py`
- `vllm/sndr_core/compat/models/pull.py`
- `vllm/sndr_core/compat/image_allowlist.py`
- `scripts/launch.sh`
- `scripts/fetch_models.sh`
- `compose/docker-compose.example.yml`
- `docs/INSTALL.md`
- `docs/MODEL_CONFIG_LAUNCHER.md`
- `docs/_internal/BACKLOG_2026-05-09.md`
- `docs/upstream/PRODUCTION_ROADMAP_2026-05-09.md`

Команды, выполненные локально:

```bash
python3 -m vllm.sndr_core.cli --help
python3 -m vllm.sndr_core.cli launch --dry-run --non-interactive a5000-2x-35b-prod
python3 -m vllm.sndr_core.compat.cli model-config preflight a5000-2x-35b-prod
python3 -m vllm.sndr_core.compat.cli model-config validate a5000-2x-35b-prod
python3 -m vllm.sndr_core.cli install --dry-run --non-interactive --no-verify
python3 -m vllm.sndr_core.cli install --dry-run --non-interactive
```

Внешние источники, использованные для технического ориентира:

- vLLM Docker deployment: https://docs.vllm.ai/en/stable/deployment/docker/
- vLLM GPU installation: https://docs.vllm.ai/en/latest/getting_started/installation/gpu/
- Docker Engine Ubuntu install: https://docs.docker.com/engine/install/ubuntu/
- NVIDIA Container Toolkit install/configuration: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html
- Python supported versions: https://devguide.python.org/versions/

## 3. Фактическое состояние сейчас

### 3.1. `install.sh`

Файл: `install.sh:1-106`

Что делает сейчас:

- проверяет Python >= 3.10;
- проверяет `git`;
- клонирует или использует `$SNDR_HOME`;
- делает `pip install -e`;
- передает управление в `sndr install`.

Что не делает:

- не проверяет Docker;
- не проверяет Docker daemon;
- не проверяет Docker Compose plugin;
- не проверяет Podman;
- не проверяет `nvidia-smi`;
- не проверяет `nvidia-container-toolkit`;
- не проверяет CUDA/driver по конфигу;
- не скачивает и не pin-ит vLLM;
- не строит план установки системных пакетов;
- не предлагает добавить официальный Docker/NVIDIA apt repo;
- не работает с модельными артефактами и ревизиями HF.

Оценка: как bootstrap он правильный. Расширять его не надо. Вся логика должна жить в Python CLI, иначе снова появится сложный shell-код, который трудно тестировать.

### 3.2. `sndr install`

Файл: `vllm/sndr_core/cli/install.py`

Сильные стороны:

- `step_preflight()` уже проверяет OS, Python, `git`, `curl`, disk: `install.py:82-128`.
- `step_detect_hardware()` уже берет GPU через `nvidia-smi` и driver info через `probe_driver()`: `install.py:134-184`.
- `step_detect_vllm()` уже проверяет импортируемый vLLM: `install.py:218-244`.
- `step_runtime_caveat()` уже ловит Proxmox caveat: `install.py:250-269`.
- `step_detect_host_paths()` пишет `host.yaml`: `install.py:486-506`.
- `step_generate_launch()` генерирует launch script: `install.py:512-553`.
- smoke-test теперь прошел локально с `failed=0`: `111 applied, 23 skipped, 0 failed`.

Недостатки:

- `step_preflight()` проверяет только `git` и `curl`, но не runtime-зависимости для запуска.
- `step_detect_vllm()` сравнивает грубо по `"0.20"`: `install.py:233-235`; нужно сравнение с конкретным `cfg.vllm_pin_required`.
- `step_resolve_pin()` решает только Genesis pin, а не vLLM pin/image pin: `install.py:319-360`.
- `_match_preset()` использует `gpu_class`/`gpu_name`, которых нет в `HardwareSpec`; реальные YAML используют `gpu_match_keys`: `install.py:580-583`, `schema.py:483-485`. Из-за этого автоподбор preset может не сработать на реальном сервере.
- plugin-install step все еще ориентирован на `tools/genesis_vllm_plugin`: `install.py:429-480`, хотя canonical entry point уже живет в core wheel.
- нет режима `--config <key> --prepare`, который бы строил план установки именно под выбранный YAML.

### 3.3. `sndr launch`

Файл: `vllm/sndr_core/cli/launch.py`

Что уже хорошо:

- dry-run показывает сгенерированный script;
- live launch включает strict mounts: `launch.py:293-305`;
- проверяются `constraints`: `launch.py:320-338`;
- есть проверка image digest, если он задан в config: `launch.py:340-348`;
- Docker configs не делают host apply, патчи применяются внутри контейнера: `launch.py:350-366`.

Что нужно усилить:

- `sndr launch` не запускает полный `model_configs.preflight.preflight_all()` перед live launch; сейчас он проверяет только constraints и digest.
- Нет `--preflight-only`, `--pull`, `--prepare`, `--fix`, `--runtime`, `--check-deps`.
- Docker image digest проверяется только если digest уже есть в YAML. В builtin YAML сейчас `image_digest` не задан.
- Если Docker image отсутствует, `launch` не предлагает `docker pull`, а `preflight` отдельно сообщает об ошибке.
- Нет проверки vLLM version inside image в обычном пути запуска.
- Нет проверки Python package versions внутри контейнера.

### 3.4. `ModelConfig` и Docker schema

Файл: `vllm/sndr_core/model_configs/schema.py`

Что есть:

- `ModelConfig` содержит `model_path`, `hardware`, `vllm_pin_required`, `genesis_env`, `system_env`, `docker`, `deploy`, `constraints`: `schema.py:471-570`.
- `DockerConfig` содержит `image`, `container_name`, `port`, `shm_size`, `memory_limit`, `network`, `gpus`, `mounts`, `extra_run_flags`, `image_digest`: `schema.py:190-231`.
- `DeploymentConfig` уже описывает Docker/Podman/Kubernetes/LXC/bare-metal compatibility: `schema.py:84-137`.

Недостатки:

- нет блока системных зависимостей;
- нет блока Python/uv/pip требований;
- нет блока vLLM source/pin strategy;
- нет блока package sources;
- нет блока model artifacts;
- нет блока cache policy;
- нет host/container port split. Сейчас `_build_docker_cmd()` делает `-p {d.port}:{d.port}`: `schema.py:917`, а внутри vLLM тоже использует `--port {self.docker.port}`: `schema.py:836-837`. Для production лучше `host_port` и `container_port` отдельно.
- runtime deps `pandas==2.2.3 scipy==1.14.1 xxhash==3.5.0` зашиты прямо в renderer: `schema.py:961-963`. Это должен быть конфигурационный контракт, а не строка внутри генератора bash.
- комментарий говорит "runtime deps pinned by default", но установка идет только при `SNDR_DEV_INSTALL_RUNTIME_DEPS=1`: `schema.py:987-992`. Комментарий и поведение надо синхронизировать.

### 3.5. Builtin YAML configs

Пример: `vllm/sndr_core/model_configs/builtin/a5000-2x-35b-prod.yaml`

Что есть:

- `vllm_pin_required`: `a5000-2x-35b-prod.yaml:19`;
- `hardware`: `a5000-2x-35b-prod.yaml:23-28`;
- модельные флаги и env: `a5000-2x-35b-prod.yaml:29-142`;
- `docker.image: vllm/vllm-openai:nightly`: `a5000-2x-35b-prod.yaml:146-160`;
- reference metrics: `a5000-2x-35b-prod.yaml:164-194`.

Проблемы:

- все builtin configs используют mutable `vllm/vllm-openai:nightly`, но не задают `image_digest`;
- `vllm_pin_required` у PROD все еще `0.20.2rc1.dev9+g01d4d1ad3`, а `reference_metrics.vllm_pin` уже `0.20.2rc1.dev93+g51f22dcfd`. `model-config validate` ловит это как warning R-014;
- в config нет требований к Docker/NVIDIA runtime;
- в config нет требований к Python внутри контейнера;
- в config нет списка Python пакетов внутри container/venv;
- в config нет списка нужных моделей и revision/checksum;
- mounts уже символические, это хорошо, но preflight на локальной машине показывает, что без `host.yaml` запуск блокируется.

Факт из локального `validate`:

```text
R-014: reference_metrics.vllm_pin (0.20.2rc1.dev93+g51f22dcfd) != vllm_pin_required (0.20.2rc1.dev9+g01d4d1ad3)
R-019: unresolved ${var} in mounts requires host.yaml
```

### 3.6. Preflight layer

Файл: `vllm/sndr_core/model_configs/preflight.py`

Что есть:

- mounts: `preflight.py:44-108`;
- container name free: `preflight.py:111-143`;
- image pulled: `preflight.py:145-164`;
- GPU count: `preflight.py:166-189`;
- GPU VRAM: `preflight.py:191-231`;
- `genesis_pin`: `preflight.py:234-263`;
- `check_vllm_pin_in_image()`: `preflight.py:265-293`;
- stale cache: `preflight.py:296-352`;
- `preflight_all()`: `preflight.py:358-388`.

Ключевой недочет:

- `check_vllm_pin_in_image()` существует, но в `preflight_all()` не запускается по умолчанию, потому что помечен как slow: `preflight.py:383-384`.

Что отсутствует:

- Docker version;
- Docker daemon status;
- Docker Compose plugin;
- NVIDIA Container Toolkit;
- `nvidia-ctk` config status;
- проверка `docker run --rm --gpus all nvidia/cuda:* nvidia-smi`;
- Python/uv/pip versions;
- `pip check`;
- package versions inside image/venv;
- `vllm --version` или import vLLM inside image/venv как обязательная проверка для launch;
- проверка image digest against `KNOWN_GOOD_IMAGES`;
- проверка доступности HF/model artifacts;
- проверка free disk именно под model/cache size, а не только 200 MiB под clone.

### 3.7. `compat.models.pull`

Файл: `vllm/sndr_core/compat/models/pull.py`

Проблемы:

- `generate_launch_script()` вручную генерирует Docker command вместо использования `ModelConfig.to_launch_script()`: `pull.py:188-288`.
- В generated script остались старые пути `vllm/_genesis`: `pull.py:264`.
- В generated script вызывается несуществующий/старый entrypoint `python3 -m vllm.sndr_core.apply_all`: `pull.py:270`.
- Default/help все еще упоминает `/nfs/genesis/models`: `pull.py:18-19`, `pull.py:303`.
- Скрипт скачивает модель через `snapshot_download`, но не связывает результат с новым unified config registry.
- Нет обязательного revision pin/checksum в config.
- Нет интеграции с `host.yaml`.

Рекомендация: эту утилиту нужно либо переписать как `sndr model pull`, либо оставить legacy wrapper, который вызывает новый `ModelArtifactResolver`.

### 3.8. `scripts/fetch_models.sh`

Файл: `scripts/fetch_models.sh`

Проблемы:

- default destination все еще `/nfs/genesis/models`: `fetch_models.sh:29`;
- env names legacy `GENESIS_MODELS_ROOT`, `GENESIS_HF_TOKEN`: `fetch_models.sh:11-14`;
- если `huggingface-cli` отсутствует, скрипт сам делает `pip install huggingface_hub`: `fetch_models.sh:47-53`; для production лучше строить plan и спрашивать confirmation;
- вывод "Next" указывает на старые `scripts/start_*.sh`, которых не должно быть в новой модели: `fetch_models.sh:91-93`;
- комментарий обещает SHA-check через LFS pointer, но фактически проверяется только наличие `.safetensors` и `config.json`: `fetch_models.sh:70-85`.

Рекомендация: заменить на `sndr model pull <config-key>` и оставить shell wrapper только как thin alias.

### 3.9. `scripts/launch.sh`

Файл: `scripts/launch.sh:1-60`

Состояние:

- полезный wrapper;
- но вызывает compat path `python3 -m vllm.sndr_core.compat.cli model-config ...`, а не новый native `sndr launch`.

Рекомендация: оставить как legacy, но перевести внутрь на `sndr launch` / `sndr model-config`, чтобы один UX был главным.

### 3.10. `docs/INSTALL.md` и `MODEL_CONFIG_LAUNCHER.md`

Проблемы:

- `docs/INSTALL.md:184-192` описывает старую архитектуру bind-mount `_genesis`, хотя v11 уже перешел на `sndr_core`;
- `docs/INSTALL.md:134-138` показывает `sndr_engine` с PN72/private content, хотя текущая стратегия - engine пустой, все существующее в core;
- `docs/MODEL_CONFIG_LAUNCHER.md:27` все еще пишет `~/.genesis/model_configs`, хотя canonical уже `~/.sndr`;
- `docs/MODEL_CONFIG_LAUNCHER.md:127-129` содержит старые hardcoded примерные mounts на `/nfs` и `_genesis`.

Рекомендация: после внедрения deployment contract переписать docs вокруг `sndr install --config`, `sndr deps plan`, `sndr launch`.

## 4. Целевая архитектура

### 4.1. Главная идея

Единый config должен стать не только launch preset, а полным контрактом:

```text
ModelConfig =
  identity
  hardware
  model serve flags
  patch env
  runtime/deployment
  system dependencies
  Python dependencies
  vLLM source/pin policy
  Docker/image policy
  model artifacts
  host paths/cache policy
  validation policy
  install actions
  benchmark/reference metrics
```

Тогда `sndr` сможет:

- объяснить, чего не хватает;
- предложить конкретный план установки;
- скачать нужный image/vLLM/model;
- проверить версии;
- построить launch script;
- отказать запуск при drift;
- дать reproducible deployment report.

### 4.2. Новый блок YAML: `runtime_requirements`

Пример:

```yaml
runtime_requirements:
  python:
    min: "3.10"
    recommended: "3.12"
    max_tested: "3.13"
    require_venv_for_bare_metal: true

  system_tools:
    git:
      required: true
      min_version: null
    curl:
      required: true
    jq:
      required: false
    uv:
      required_for: [bare_metal, nightly_wheel]
      min_version: "0.7.0"

  container:
    default_runtime: docker
    supported_runtimes: [docker, podman, bare_metal]
    docker:
      required: true
      min_version: "25.0.0"
      compose_plugin: optional
      install_source: docker_official_apt
      daemon_required: true
      rootless_supported: false
    podman:
      required: false
      min_version: "5.0.0"
      gpu_mode: cdi
    nvidia_container_toolkit:
      required_for: [docker, podman]
      min_version: "1.17.0"
      install_source: nvidia_official_repo

  gpu:
    vendor: nvidia
    min_compute_capability: [8, 6]
    min_driver_major: 580
    require_nvidia_smi: true
    require_container_gpu_probe: true
```

### 4.3. Новый блок YAML: `vllm_runtime`

Пример:

```yaml
vllm_runtime:
  mode: docker_image        # docker_image | bare_metal_wheel | bare_metal_source | custom_image
  required_version: 0.20.2rc1.dev93+g51f22dcfd
  required_commit: g51f22dcfd

  docker_image:
    repository: vllm/vllm-openai
    tag: nightly
    digest: vllm/vllm-openai@sha256:9b534fe66daf152e8ceca8a7f8e14c18105aaf6ddabc61eb17730d85b4c7c194
    known_good: true
    pull_policy: if_missing       # never | if_missing | always | digest_only
    verify_inside_image: true

  wheel:
    installer: uv
    index: https://wheels.vllm.ai/nightly/cu130
    torch_backend: cu130
    exact_url: null
    allow_pip_fallback: false

  package_versions:
    python_packages:
      vllm: "==0.20.2rc1.dev93+g51f22dcfd"
      torch: "==2.11.0"
      triton: null
      transformers: null
      flashinfer-python: null
      pandas: "==2.2.3"
      scipy: "==1.14.1"
      xxhash: "==3.5.0"
```

Почему это важно:

- vLLM docs сейчас рекомендуют официальный Docker image `vllm/vllm-openai` для deployment и указывают `--gpus all`, HF cache mount, `HF_TOKEN`, `--ipc=host` или `--shm-size`.
- vLLM docs по GPU install рекомендуют fresh environment, `uv`, Python 3.10-3.13, и отдельно предупреждают о binary compatibility CUDA/PyTorch.
- Поэтому SNDR должен фиксировать не просто "vLLM 0.20.x", а конкретную связку `vLLM + torch + CUDA variant + image digest`.

### 4.4. Новый блок YAML: `package_sources`

Пример:

```yaml
package_sources:
  docker:
    ubuntu:
      source: docker_official_apt
      allow_convenience_script: false
      reason: "Docker docs mark convenience script as test/dev only"

  nvidia_container_toolkit:
    source: nvidia_official_repo
    channel: stable
    allow_experimental: false

  python:
    preferred_env_manager: uv
    allow_pip: true
    allow_system_python_install: false

  vllm:
    channel: tested     # stable | tested | nightly | local
    allow_mutable_nightly_without_digest: false
```

Поведение:

- installer не должен молча добавлять repo;
- `sndr deps plan` должен показать команды и объяснение;
- `sndr deps apply --yes` может применить системные изменения только явно;
- на серверах без sudo должен печататься manual plan.

### 4.5. Новый блок YAML: `artifacts`

Пример:

```yaml
artifacts:
  models:
    main:
      hf_id: Qwen/Qwen3.6-35B-A3B-FP8
      revision: "<commit-or-tag>"
      local_dir: "${models_dir}/Qwen3.6-35B-A3B-FP8"
      gated: false
      expected_size_gb: 40
      required_files:
        - config.json
        - tokenizer.json
        - "*.safetensors"
      verify:
        min_safetensors: 1
        allow_size_drift_pct: 5
    drafter:
      hf_id: null
      revision: null
      local_dir: null

  caches:
    hf_cache: "${hf_cache}"
    triton_cache: "${cache_root}/triton-cache-mtp-test"
    compile_cache: "${cache_root}/compile-cache-prod-mirror-test"
    require_writable: true
```

Этим заменить ручные `fetch_models.sh` и несвязанный `compat.models.pull`.

## 5. Новые команды CLI

### 5.1. `sndr doctor system`

Назначение: полная диагностика host/runtime без запуска модели.

Проверки:

- OS/distro/kernel;
- Python version;
- `pip`, `uv`, `venv`;
- `git`, `curl`, `jq`, `bash`;
- Docker binary version;
- Docker daemon доступен;
- Docker compose plugin;
- Podman binary/version/CDI;
- NVIDIA driver;
- CUDA reported by `nvidia-smi`;
- GPU count/name/VRAM/PCIe lanes;
- `nvidia-container-toolkit`;
- `nvidia-ctk` config;
- container GPU probe;
- disk space for models/cache;
- network access to GitHub/HF/Docker Hub, если нужно.

### 5.2. `sndr deps check <config-key>`

Назначение: проверить текущую систему против конкретного YAML.

Вывод:

```text
OK      python              3.12.4 satisfies >=3.10
ERROR   docker              not installed
ERROR   nvidia-container    nvidia-ctk not found
WARN    vllm image          tag nightly is mutable, digest missing
ERROR   model main          /models/... missing
WARN    vllm pin            image has dev9, config expects dev93
```

### 5.3. `sndr deps plan <config-key>`

Назначение: не менять систему, а построить план установки.

Пример вывода:

```text
Plan for a5000-2x-35b-prod:

1. Add Docker official apt repository
2. Install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
3. Add NVIDIA Container Toolkit stable repository
4. Install nvidia-container-toolkit
5. Run nvidia-ctk runtime configure --runtime=docker
6. Restart Docker daemon
7. Pull vllm/vllm-openai@sha256:...
8. Verify vLLM version inside image
9. Download Qwen/Qwen3.6-35B-A3B-FP8 revision ...
10. Write/update ~/.sndr/host.yaml
```

### 5.4. `sndr deps apply <config-key>`

Назначение: применить план установки.

Правила безопасности:

- по умолчанию только dry-run;
- системные изменения требуют `--yes` и явного подтверждения;
- sudo-команды показывать до выполнения;
- нельзя использовать `curl | bash` для production;
- official repositories only;
- все изменения писать в install report.

### 5.5. `sndr image inspect <config-key>`

Проверки:

- image pulled;
- RepoDigest совпадает с YAML;
- digest есть в `KNOWN_GOOD_IMAGES`;
- внутри image:
  - `python --version`;
  - `python -c "import vllm; print(vllm.__version__)"`;
  - `python -c "import torch; print(torch.__version__, torch.version.cuda)"`;
  - `python -m pip check`;
  - импорт `vllm.sndr_core`;
  - `python3 -m vllm.sndr_core.apply --dry-run`.

### 5.6. `sndr model pull <config-key>`

Заменяет:

- `scripts/fetch_models.sh`;
- `python3 -m vllm.sndr_core.compat.models.pull`.

Функции:

- читает `artifacts.models`;
- проверяет HF token для gated models;
- скачивает exact revision;
- проверяет expected files;
- пишет путь в `host.yaml`;
- не генерирует свой legacy launch script, а использует `ModelConfig`.

### 5.7. `sndr install --config <key> --prepare`

Новый основной UX:

```bash
sndr install --config a5000-2x-35b-prod --prepare
```

Шаги:

1. Прочитать config.
2. Проверить schema/audit.
3. Собрать system inventory.
4. Сравнить с `runtime_requirements`.
5. Показать dependency plan.
6. Спросить подтверждение на install actions.
7. Скачать/проверить Docker image или создать venv.
8. Скачать/проверить модель.
9. Обновить `~/.sndr/host.yaml`.
10. Выполнить image/venv preflight.
11. Сгенерировать launch script.
12. Напечатать next command.

## 6. Новый внутренний слой кода

Предлагаемая структура:

```text
vllm/sndr_core/deps/
  __init__.py
  spec.py              # dataclasses: ToolRequirement, PackageRequirement, RuntimeRequirement
  inventory.py         # system inventory: OS, tools, Docker, NVIDIA, Python
  checkers.py          # pure checks: actual vs requirement
  planners.py          # CheckResult -> InstallPlan
  installers.py        # optional apply actions, explicit confirmation only
  sources.py           # package source metadata: Docker apt, NVIDIA repo, vLLM wheels
  docker.py            # image inspect/pull/digest/vllm-in-image
  python_env.py        # venv/uv/pip inspect
  models.py            # HF artifact resolver/downloader/verifier
  report.py            # markdown/json support bundle
```

Ключевые типы:

```python
@dataclass
class CheckResult:
    id: str
    severity: Literal["ok", "info", "warning", "error"]
    component: str
    expected: str | None
    actual: str | None
    message: str
    remediation: str | None
    fix: FixAction | None

@dataclass
class FixAction:
    id: str
    title: str
    commands: list[list[str]]
    requires_sudo: bool
    destructive: bool
    official_source_url: str | None
```

Важно: `checkers.py` должен быть чистым и тестируемым. Он не должен ничего устанавливать. Установка только через `installers.py` после подтверждения.

## 7. Политика версий и источников

### 7.1. Docker

Правильная политика:

- для production не использовать mutable tag без digest;
- `nightly` допустим только если:
  - digest закреплен;
  - digest есть в `KNOWN_GOOD_IMAGES`;
  - `vllm_pin_required` совпадает с версией внутри image;
  - reference metrics сняты именно на этом digest.

Что сделать:

- добавить `image_digest` во все stable builtin configs;
- добавить audit rule: stable config with docker image must set digest;
- `sndr launch` должен блокировать stable config, если image digest отсутствует и strict mode включен;
- `sndr image resolve` может помогать получить digest после pull:

```bash
docker image inspect vllm/vllm-openai:nightly --format '{{json .RepoDigests}}'
```

### 7.2. vLLM

vLLM docs сейчас указывают:

- для Docker: официальный image `vllm/vllm-openai`;
- для GPU Python install: Linux, Python 3.10-3.13;
- рекомендуют fresh environment;
- рекомендуют `uv`;
- предупреждают о binary compatibility CUDA/PyTorch;
- для nightly wheels указывают `wheels.vllm.ai/nightly` и говорят, что `pip` с extra-index для nightly проблемен, а `uv` предпочтительнее.

SNDR policy:

- Docker production: image digest + known-good.
- Bare-metal production: `uv venv --python 3.12` + exact vLLM wheel URL или exact commit index.
- Bare-metal dev: допускается source install, но помечается как dev.
- Никакого "latest" без записи в report.

### 7.3. Docker repository

Docker docs указывают, что Docker Engine можно ставить разными способами, но apt repository является нормальным обновляемым путем, а convenience script рекомендуется только для testing/dev. Поэтому installer должен:

- распознать Ubuntu/Debian;
- если Docker отсутствует или distro package старый, предложить Docker official apt repo;
- не запускать convenience script в production;
- сохранять решение в report.

### 7.4. NVIDIA Container Toolkit

NVIDIA docs указывают:

- использовать production repo для apt/dnf/zypper;
- для Docker выполнить `nvidia-ctk runtime configure --runtime=docker`;
- после этого restart Docker daemon;
- rootless mode имеет отдельные команды;
- для Podman NVIDIA рекомендует CDI.

SNDR должен проверять:

- `nvidia-container-toolkit` installed;
- `nvidia-ctk` available;
- Docker runtime configured;
- `docker run --rm --gpus all ... nvidia-smi` works;
- Podman CDI devices exist, если runtime=podman.

### 7.5. Python

Python devguide показывает:

- Python 3.10 и 3.11 уже в security mode;
- Python 3.12 тоже security;
- Python 3.13/3.14 в bugfix.

Для SNDR:

- `requires-python >=3.10` можно оставить как минимум;
- production recommendation - Python 3.12, потому что vLLM docs используют `uv venv --python 3.12`;
- installer должен предупреждать, если Python 3.10 используется для нового bare-metal deployment: работает, но это нижняя граница.

## 8. Конкретные P0/P1 задачи

### P0.1. Синхронизировать vLLM pin в stable YAML

Файлы:

- `vllm/sndr_core/model_configs/builtin/a5000-2x-35b-prod.yaml`
- `vllm/sndr_core/model_configs/builtin/a5000-2x-27b-int4-tq-k8v4.yaml`

Проблема:

- `vllm_pin_required` старый dev9;
- `reference_metrics.vllm_pin` новый dev93.

Что сделать:

- если текущий production baseline действительно dev93, поднять `vllm_pin_required` до `0.20.2rc1.dev93+g51f22dcfd`;
- если dev9 остается supported, split configs на `*-legacy-dev9` и `*-prod-dev93`.

Критерий:

```bash
python3 -m vllm.sndr_core.compat.cli model-config validate a5000-2x-35b-prod
```

не должен выдавать R-014.

### P0.2. Добавить `image_digest` в stable builtin configs

Файлы:

- все `vllm/sndr_core/model_configs/builtin/*.yaml` со `lifecycle: stable`.

Что сделать:

- взять digest из known-good image или server inspect;
- добавить `docker.image_digest`;
- связать с `KNOWN_GOOD_IMAGES`.

Критерий:

- `sndr launch --strict-image always <key>` проходит только с правильным digest;
- mutable `nightly` без digest блокируется для stable config.

### P0.3. Включить проверку vLLM pin inside image

Файл:

- `vllm/sndr_core/model_configs/preflight.py`

Что сделать:

- оставить fast preflight быстрым;
- добавить `full=True` или `--full`, где запускается `check_vllm_pin_in_image()`;
- `sndr launch` для live production config должен запускать full image check хотя бы один раз после pull.

Критерий:

```bash
sndr model-config preflight a5000-2x-35b-prod --full
```

показывает actual vLLM version inside image.

### P0.4. Исправить `_match_preset()` на `gpu_match_keys`

Файл:

- `vllm/sndr_core/cli/install.py:556-592`

Сейчас:

```python
gpu_field = (getattr(hw, "gpu_class", "") or getattr(hw, "gpu_name", "")).lower()
```

Нужно:

```python
keys = [k.lower() for k in getattr(hw, "gpu_match_keys", [])]
if not any(gpu_class.lower() in k or k in gpu_name.lower() for k in keys):
    continue
```

Для этого `step_detect_hardware()` должен передавать и `gpu_name`, и `gpu_class_hint`.

### P0.5. Переписать `compat.models.pull`

Файл:

- `vllm/sndr_core/compat/models/pull.py`

Что сделать:

- убрать ручную генерацию Docker script;
- убрать `_genesis`;
- убрать `apply_all`;
- использовать `ModelConfig` и `host.yaml`;
- интегрировать с новым `artifacts.models`.

### P0.6. Перевести `fetch_models.sh` в thin wrapper

Файл:

- `scripts/fetch_models.sh`

Что сделать:

- canonical command: `sndr model pull`;
- shell script только вызывает Python CLI;
- убрать `/nfs/genesis/models` как default;
- заменить `GENESIS_*` на `SNDR_*` с legacy alias;
- убрать обещание SHA-check, пока нет реального SHA-check.

### P0.7. Разделить `host_port` и `container_port`

Файлы:

- `vllm/sndr_core/model_configs/schema.py`
- builtin YAML configs.

Зачем:

- Docker host port может быть 8001/8002, а vLLM внутри контейнера почти всегда 8000;
- Kubernetes/Podman/Compose тоже хотят явную семантику.

Предложение:

```yaml
docker:
  host_port: 8000
  container_port: 8000
```

Backward compatibility:

- если есть старое `port`, трактовать как оба значения.

### P0.8. Вынести hardcoded runtime deps из renderer

Файл:

- `vllm/sndr_core/model_configs/schema.py:961-963`

Что сделать:

- перенести `pandas/scipy/xxhash` в `vllm_runtime.package_versions.python_packages`;
- renderer не должен знать версии пакетов;
- install/image builder должен ставить пакеты на этапе build/preparation.

## 9. P1 задачи: полноценная автоматизация

### P1.1. `deps` package

Создать `vllm/sndr_core/deps/` с pure checkers и install planners.

Минимальный набор checks:

- `check_python()`
- `check_tool("git")`
- `check_docker_binary()`
- `check_docker_daemon()`
- `check_docker_compose_plugin()`
- `check_nvidia_smi()`
- `check_nvidia_driver()`
- `check_nvidia_container_toolkit()`
- `check_docker_gpu_probe()`
- `check_image_digest()`
- `check_vllm_inside_image()`
- `check_python_packages_inside_image()`
- `check_model_artifacts()`
- `check_cache_dirs()`
- `check_host_yaml()`

### P1.2. `sndr deps check/plan/apply`

Добавить native subcommands в `vllm/sndr_core/cli/__init__.py`.

Не через compat. Новый слой должен быть core API.

### P1.3. `sndr install --config`

Сейчас installer выбирает workload и пытается matched preset. Нужно добавить прямой production path:

```bash
sndr install --config a5000-2x-35b-prod --prepare
```

Если `--config` задан, installer:

- не спрашивает workload;
- не делает heuristic preset matching;
- строит dependency plan именно под config.

### P1.4. `sndr launch --preflight`

Новый live launch path:

```text
resolve config
validate schema/audit
load host.yaml
run deps check fast
run model_config preflight full enough
verify image digest
verify vLLM pin inside image if needed
render script
exec
```

### P1.5. Install reports

Каждый `sndr install --prepare` должен писать:

```text
~/.sndr/reports/install-YYYYMMDD-HHMMSS.json
~/.sndr/reports/install-YYYYMMDD-HHMMSS.md
```

Содержимое:

- host inventory;
- selected config;
- versions expected/actual;
- package sources;
- commands executed;
- image digest;
- model artifacts;
- final launch command.

## 10. P2 задачи: образ и reproducibility

### P2.1. Custom image builder

Добавить:

```bash
sndr image build <config-key>
```

Идея:

- base `vllm/vllm-openai@sha256:...`;
- install `vllm-sndr-core` wheel;
- install package requirements from config;
- run import smoke;
- label image:
  - `org.opencontainers.image.source`;
  - `sndr.core.version`;
  - `sndr.config.key`;
  - `sndr.vllm.version`;
  - `sndr.genesis.pin`.

Так production не будет зависеть от bind mount `${genesis_src}`.

### P2.2. SBOM и provenance

Уже есть `scripts/generate_sbom.py`. Нужно:

- wire into release/image build;
- сохранять SBOM path в report;
- для known-good image хранить digest + SBOM + bench result.

### P2.3. Lockfile для Python deps

Добавить:

- `requirements-runtime.lock`;
- `requirements-dev.lock`;
- возможно `uv.lock` для bare-metal mode.

Но source of truth для конкретного deployment все равно должен быть config.

## 11. P3 задачи: community и UX

### P3.1. Community config wizard

Команда:

```bash
sndr config new --from-detect
```

Собирает:

- GPU;
- VRAM;
- driver;
- Docker/NVIDIA toolkit;
- paths;
- выбранную модель;
- желаемый runtime.

Создает user config в `~/.sndr/model_configs/`.

### P3.2. `sndr config doctor`

Проверяет все configs:

- stable configs have digest;
- stable configs have matching vLLM pin/reference;
- runtime requirements valid;
- artifacts block present;
- no legacy `_genesis`;
- no hardcoded operator paths.

### P3.3. Migration tool

Команда:

```bash
sndr migrate v11-runtime-contract
```

Функции:

- обновляет user configs schema_version;
- переносит `port` в `host_port/container_port`;
- добавляет пустой `runtime_requirements`;
- предупреждает о legacy paths.

## 12. Security policy

Что обязательно:

- никакого silent install системных пакетов;
- никакого `curl | bash` в production apply;
- official repositories only;
- GPG key paths явные;
- все sudo-команды показывать до выполнения;
- image digest required for stable;
- known-good image allowlist;
- `pip check`/`uv pip check`;
- SBOM for release/image;
- install report;
- no mutable nightly without digest;
- HF token не логировать;
- API key не писать в публичный report без redaction.

## 13. Как это должно выглядеть для пользователя

### Fresh server path

```bash
curl -sSL https://raw.githubusercontent.com/Sandermage/genesis-vllm-patches/main/install.sh | bash
sndr install --config a5000-2x-35b-prod --prepare
sndr launch a5000-2x-35b-prod
```

### Проверка без установки

```bash
sndr deps check a5000-2x-35b-prod
sndr deps plan a5000-2x-35b-prod
```

### Bare-metal vLLM

```bash
sndr install --config a5000-2x-35b-prod --runtime bare_metal --prepare
sndr launch a5000-2x-35b-prod --runtime bare_metal
```

### Docker image pinned

```bash
sndr image pull a5000-2x-35b-prod
sndr image inspect a5000-2x-35b-prod
sndr launch a5000-2x-35b-prod --strict-image always
```

## 14. Acceptance criteria

Проект можно считать готовым по этому направлению, когда:

1. Stable configs имеют `image_digest`.
2. `vllm_pin_required` совпадает с `reference_metrics.vllm_pin`.
3. `sndr deps check <stable-key>` дает полный список host/container/version checks.
4. `sndr deps plan <stable-key>` строит понятный план установки без изменения системы.
5. `sndr deps apply <stable-key> --yes` может подготовить чистый Ubuntu server.
6. `sndr install --config <key> --prepare` скачивает/проверяет image/model/cache.
7. `sndr launch <key>` перед запуском выполняет обязательный preflight.
8. `compat.models.pull` больше не генерирует legacy `_genesis/apply_all` scripts.
9. `scripts/fetch_models.sh` не содержит `/nfs/genesis/models` как default и не обещает несуществующий SHA-check.
10. Docs не содержат старую архитектуру `_genesis` как current path.
11. В CI есть unit tests для deps checkers и fake subprocess inventory.
12. На сервере с GPU есть integration smoke:
    - Docker absent;
    - Docker present, no NVIDIA toolkit;
    - image missing;
    - image digest mismatch;
    - vLLM pin mismatch;
    - model missing;
    - clean production path.

## 15. Рекомендованный порядок внедрения

### Sprint A - закрыть текущие расхождения

1. Синхронизировать `vllm_pin_required` с reference metrics.
2. Добавить `image_digest` в stable configs.
3. Включить full image/vLLM pin check в preflight mode.
4. Исправить `_match_preset()` на `gpu_match_keys`.
5. Переписать `compat.models.pull` или пометить legacy и отключить генерацию launch script.
6. Обновить `fetch_models.sh` как thin wrapper.

### Sprint B - dependency contract

1. Добавить dataclasses для `runtime_requirements`.
2. Добавить YAML parse/dump backward-compatible.
3. Добавить audit rules для stable configs.
4. Добавить `deps.inventory` и `deps.checkers`.
5. Добавить `sndr deps check`.

### Sprint C - install planner

1. Добавить `deps.plan`.
2. Добавить official package source registry.
3. Добавить `sndr deps plan`.
4. Добавить install report.
5. Добавить осторожный `sndr deps apply --yes`.

### Sprint D - unified installer

1. Добавить `sndr install --config`.
2. Добавить model artifact resolver.
3. Добавить image pull/inspect.
4. Обновить `host.yaml`.
5. Связать prepare + launch.

### Sprint E - production hardening

1. Custom image builder.
2. SBOM in release.
3. Known-good image promotion workflow.
4. GPU server integration tests.
5. Docs rewrite around new workflow.

### Sprint F - Kubernetes/k8s и Proxmox как first-class runtimes

1. Довести `--runtime kubernetes` от manifest-preview до полноценного workflow.
2. Добавить `sndr k8s doctor/render/apply/status/logs/report/delete`.
3. Добавить поддержку MicroK8s/single-node k8s как community path из club-3090.
4. Довести `--runtime lxc_proxmox` от skeleton до real renderer/doctor.
5. Добавить Proxmox VE API inventory: nodes, CT/VM, storage, bridge, GPU passthrough, kernel, driver, container config.
6. Добавить report bundle для Proxmox/k8s, чтобы пользователь мог приложить один архив в issue.

### Sprint G - universal bootstrap, community configs и tuning profiles

1. Добавить единый bootstrap workflow для bare metal, VM, LXC/systemd-nspawn/container и cloud images.
2. Добавить команды `sndr bootstrap doctor/plan/apply/status/report`.
3. Разделить системные зависимости, Python/vLLM зависимости, runtime зависимости и model artifacts.
4. Добавить community config registry: поиск, валидация, установка, экспорт и provenance.
5. Добавить model tuning profiles: параметры vLLM, memory/KV/cache, quantization, speculative/MTP, DFlash/PFlash/TurboQuant.
6. Добавить GPU tuning profiles: power limit, persistence mode, clocks, topology, kernel/runtime capabilities.
7. Запретить опасные tuning-действия без явного `--apply`/`--yes` и без capability check.

## 16. Итоговая рекомендация

Да, единый конфиг должен включать Docker/runtime/system/Python/vLLM/model requirements. Это правильное направление, потому что основная ценность SNDR для пользователей будет не только в патчах, а в том, что система сама объясняет:

- какая модель подойдет;
- что нужно установить;
- какая версия vLLM совместима;
- какой Docker image протестирован;
- какие пути и cache нужны;
- почему запуск заблокирован;
- как исправить окружение.

Самое важное архитектурное правило: `core` не должен зависеть от `engine`, а installer/launcher не должны зависеть от приватного кода. `engine` может добавлять свои configs/patches/runtime blocks отдельным overlay-пакетом, но public `sndr_core` обязан уметь валидировать отсутствие engine и работать полностью сам.

На текущем этапе не надо зашивать все в shell. Shell должен запускать Python CLI. Вся логика проверки версий, источников пакетов, Docker/NVIDIA runtime, vLLM image, model artifacts и reports должна быть в тестируемом Python-коде.

## 17. Дополнение: Kubernetes/k8s и Proxmox VE/LXC

После отдельного поиска по проекту видно:

- В `vllm/sndr_core/compat/model_config_cli.py` уже есть `--runtime kubernetes`, но это минимальный renderer `Deployment + Service + ConfigMap`, без полноценного doctor/apply/status/report workflow.
- В `vllm/sndr_core/compat/model_config_cli.py` уже есть `--runtime lxc_proxmox`, но он прямо помечен как skeleton/manual guide.
- В документации и README уже есть ссылки на club-3090: microk8s/k8s упоминался как ручной путь, а Proxmox VE LXC обсуждался через caveat kernel/uvloop и workaround `bare_metal`.

Это надо сделать отдельным направлением, потому что для пользователей с домашними GPU-серверами Proxmox и Kubernetes часто важнее, чем "чистый Docker". Если SNDR сможет нормально диагностировать Proxmox/k8s и выдавать готовый план, это станет сильной utility-фичей.

### 17.1. Kubernetes/k8s: что именно добавить

Под `k8` в контексте клуба почти наверняка имеется в виду `k8s`/Kubernetes, включая MicroK8s single-node setups.

Сейчас в коде есть:

- `model_config_cli.py:187-195` - runtime branch `kubernetes`;
- `model_config_cli.py:326-524` - renderer Kubernetes manifest;
- renderer создает `ConfigMap`, `Deployment`, `Service`;
- GPU requests/limits уже используют `nvidia.com/gpu`;
- readinessProbe уже есть;
- comments уже упоминают HostPath/PVC, NVIDIA device plugin и single-node limitations.

Чего не хватает:

- нет `sndr k8s doctor`;
- нет `sndr k8s apply`;
- нет `sndr k8s status`;
- нет `sndr k8s logs`;
- нет `sndr k8s report`;
- нет namespace management;
- нет проверки `kubectl`;
- нет проверки текущего context;
- нет проверки NVIDIA device plugin;
- нет проверки `nvidia.com/gpu` в allocatable resources;
- нет проверки container runtime (`containerd`, `cri-o`, Docker shim через cri-dockerd);
- нет проверки RuntimeClass;
- нет проверки PVC/StorageClass/HostPath;
- нет imagePullSecret/private registry flow;
- нет Helm chart;
- нет разделения single-node HostPath и multi-node PVC;
- нет политики обновления image digest в k8s;
- нет автоматического вывода событий pod (`kubectl describe pod`, events, logs).

### 17.2. Новый YAML-блок `kubernetes`

Добавить в `ModelConfig` отдельный блок:

```yaml
kubernetes:
  enabled: true
  flavor: microk8s              # generic | microk8s | kubeadm | k3s | rke2
  namespace: sndr
  name: vllm-a5000-35b-prod

  image:
    repository: vllm/vllm-openai
    tag: nightly
    digest: vllm/vllm-openai@sha256:...
    pull_policy: IfNotPresent
    image_pull_secret: null

  gpu:
    resource_name: nvidia.com/gpu
    count: 2
    require_device_plugin: true
    runtime_class_name: nvidia

  storage:
    mode: hostPath              # hostPath | pvc | nfs
    models:
      host_path: ${models_dir}
      pvc: null
      mount_path: /models
      read_only: true
    hf_cache:
      host_path: ${hf_cache}
      pvc: null
      mount_path: /root/.cache/huggingface
    triton_cache:
      host_path: ${cache_root}/triton-cache-mtp-test
      pvc: null
      mount_path: /root/.triton/cache
    compile_cache:
      host_path: ${cache_root}/compile-cache-prod-mirror-test
      pvc: null
      mount_path: /root/.cache/vllm/torch_compile_cache

  service:
    type: ClusterIP             # ClusterIP | NodePort | LoadBalancer
    port: 8000
    node_port: null
    ingress:
      enabled: false
      host: null
      tls_secret: null

  pod:
    shm:
      mode: emptyDirMemory
      size_limit: 8Gi
    node_selector: {}
    tolerations: []
    affinity: {}
    security_context:
      run_as_user: 0
      privileged: false
      ipc_lock: false
    resources:
      cpu_request: "4"
      memory_request: 32Gi
      memory_limit: 64Gi

  probes:
    readiness_initial_delay_seconds: 180
    liveness_enabled: false
```

Почему отдельный блок лучше, чем post-process Docker:

- Kubernetes требует другой модели storage, networking, security, resources и lifecycle.
- `docker.mounts` не может корректно описать PVC/StorageClass/RuntimeClass.
- Для single-node MicroK8s можно использовать HostPath, но для нормального кластера нужен PVC/NFS/Ceph.
- `--gpus all` не существует в k8s; там используется resource `nvidia.com/gpu`.

### 17.3. Новые команды для k8s

Добавить native CLI:

```bash
sndr k8s doctor <config-key>
sndr k8s render <config-key> --output manifest.yaml
sndr k8s apply <config-key>
sndr k8s status <config-key>
sndr k8s logs <config-key> --follow
sndr k8s report <config-key>
sndr k8s delete <config-key>
```

`sndr k8s doctor` должен проверять:

- `kubectl` установлен;
- текущий context выбран;
- cluster доступен;
- namespace существует или может быть создан;
- node count;
- GPU nodes;
- `nvidia.com/gpu` есть в `kubectl get nodes -o json`;
- NVIDIA device plugin DaemonSet установлен;
- RuntimeClass `nvidia` существует, если config требует;
- StorageClass/PVC/HostPath доступны;
- image pull возможен;
- secret для HF token/API key создан;
- service port не конфликтует;
- pod security constraints не блокируют root/IPC/shm;
- MicroK8s addons: `dns`, `hostpath-storage`, `gpu` или equivalent.

`sndr k8s report` должен собирать:

```bash
kubectl version
kubectl config current-context
kubectl get nodes -o wide
kubectl describe nodes
kubectl get runtimeclass
kubectl get pods -n <ns> -o wide
kubectl describe pod -n <ns> <pod>
kubectl logs -n <ns> <pod> --tail=300
kubectl get events -n <ns> --sort-by=.lastTimestamp
kubectl get pvc -n <ns>
kubectl get svc -n <ns>
```

Секреты должны редактироваться/redact перед записью в report.

### 17.4. Kubernetes/MicroK8s production policy

Минимально поддержать 3 режима:

1. `microk8s-single-node`
   - HostPath storage;
   - MicroK8s GPU addon;
   - один pod на один GPU-server;
   - удобно для домашнего сервера.

2. `generic-single-node`
   - kubeadm/k3s/rke2;
   - HostPath или local-path provisioner;
   - NVIDIA device plugin;
   - подходит для self-hosted GPU box.

3. `generic-multinode`
   - PVC/NFS/Ceph;
   - image registry/pull secret;
   - nodeSelector/taints/tolerations;
   - строгий digest;
   - без naive HPA, потому что vLLM stateful и GPU-bound.

Что важно:

- Не обещать autoscaling на старте. Для vLLM один pod = один engine instance. HPA без routing/cache strategy легко ломает latency и memory profile.
- Для multi-instance позже нужен routing layer: LiteLLM/Open WebUI/proxy или собственный SNDR router.
- Для long-context моделей readiness delay должен быть большим: cold compile/cache может занимать минуты.

### 17.5. Helm chart

После renderer лучше добавить Helm chart:

```text
charts/sndr-vllm/
  Chart.yaml
  values.yaml
  templates/deployment.yaml
  templates/service.yaml
  templates/configmap.yaml
  templates/secret.yaml
  templates/pvc.yaml
  templates/ingress.yaml
  templates/runtimeclass-check-job.yaml
```

Команды:

```bash
sndr k8s render <key> --format helm-values
sndr k8s helm-install <key>
```

Зачем:

- manifest renderer хорош для старта;
- Helm нужен для повторяемого production deployment;
- community сможет присылать values для MicroK8s/k3s/Proxmox clusters.

### 17.6. Proxmox VE: что сделать first-class

Сейчас Proxmox поддержка в проекте - это caveat:

- installer detect Proxmox и переключает на `--bare-metal`;
- `lxc_proxmox` renderer выводит skeleton;
- в комментариях указана проблема с kernel 6.17.x и Docker image/uvloop inside LXC.

Нужно сделать не "предупреждение", а полноценный runtime profile.

Добавить команды:

```bash
sndr proxmox doctor
sndr proxmox inventory
sndr proxmox render-lxc <config-key>
sndr proxmox render-vm <config-key>
sndr proxmox apply-lxc <config-key> --ctid <id>
sndr proxmox status --ctid <id>
sndr proxmox report --ctid <id>
```

Первый этап можно сделать без API, через local host команды:

- `pveversion -v`;
- `uname -a`;
- `pct list`;
- `qm list`;
- `pvesm status`;
- `ip link`;
- `ls -l /dev/nvidia*`;
- `nvidia-smi`;
- `/etc/pve/lxc/<ctid>.conf`;
- `/etc/pve/qemu-server/<vmid>.conf`;
- `journalctl -u pveproxy -u pvedaemon`;
- `docker info`, если Docker внутри LXC/VM.

Второй этап - Proxmox API:

- URL `https://host:8006/api2/json`;
- token id/secret через env или `~/.sndr/proxmox.yaml`;
- inventory nodes/storage/networks/CT/VM;
- read-only doctor по умолчанию;
- apply только с явным `--yes`.

### 17.7. Новый YAML-блок `proxmox`

Пример:

```yaml
proxmox:
  enabled: true
  mode: lxc                 # lxc | vm | bare_metal_host
  api:
    url: https://pve.local:8006/api2/json
    token_env: SNDR_PROXMOX_TOKEN
    verify_tls: true

  target:
    node: genesis-a2
    ctid: 200
    storage: local-zfs
    bridge: vmbr0
    cores: 16
    memory_mb: 65536
    rootfs_gb: 120
    privileged: true
    nesting: true

  gpu_passthrough:
    mode: bind_devices       # bind_devices | pci_passthrough_vm | host_bare_metal
    devices:
      - /dev/nvidia0
      - /dev/nvidia1
      - /dev/nvidiactl
      - /dev/nvidia-uvm
      - /dev/nvidia-uvm-tools
    cgroup_allow:
      - "c 195:* rwm"
      - "c 234:* rwm"
      - "c 235:* rwm"

  runtime:
    preferred: bare_metal_venv
    docker_inside_lxc: discouraged
    reason: "club-3090/Proxmox LXC uvloop/kernel caveat"

  reports:
    include_pct_config: true
    include_journal: true
    redact_tokens: true
```

### 17.8. Proxmox doctor: обязательные проверки

`sndr proxmox doctor` должен выводить таблицу:

```text
HOST
  pveversion:        8.x
  kernel:            6.x-pve
  iommu:             enabled/disabled
  nvidia driver:     580.126.09
  cuda:              13.0
  gpu visible host:  2x RTX A5000

LXC/VM
  ctid/vmid:         200
  privileged:        yes/no
  nesting:           yes/no
  nvidia devices:    present/missing
  cgroup rules:      ok/missing
  docker runtime:    ok/missing/risky
  venv runtime:      ok/missing

STORAGE
  models path:       exists/free space
  hf cache:          exists/free space
  compile cache:     exists/free space

NETWORK
  bridge:            vmbr0
  port 8000:         free/used

RECOMMENDATION
  preferred runtime: bare_metal_venv inside LXC or full VM
  avoid: docker inside LXC on known-bad kernel unless explicitly tested
```

### 17.9. Proxmox deployment modes

Поддержать 3 режима:

1. `proxmox_host_bare_metal`
   - vLLM запускается прямо на Proxmox host;
   - быстрее всего, но менее изолировано;
   - подходит для личного сервера.

2. `proxmox_lxc_bare_metal_venv`
   - LXC с GPU bind devices;
   - внутри LXC Python venv + vLLM;
   - recommended workaround для Docker/uvloop caveat;
   - лучший баланс isolation/простоты.

3. `proxmox_vm_gpu_passthrough`
   - полноценная VM с PCI passthrough;
   - тяжелее, но чище для Docker/k8s;
   - рекомендовать, если нужен Kubernetes или Docker без LXC footguns.

Docker inside LXC оставить как `experimental/risky`, а не default.

### 17.10. Proxmox + Kubernetes

Отдельный полезный сценарий:

```text
Proxmox VM(s) -> MicroK8s/k3s -> SNDR k8s deployment
```

Для этого добавить в roadmap:

- `sndr proxmox render-vm --for microk8s`;
- cloud-init template для Ubuntu 24.04 VM;
- optional install of MicroK8s/k3s;
- GPU passthrough checklist;
- `sndr k8s doctor` после VM boot.

Не стоит начинать с Kubernetes inside LXC как default. Это возможно, но комбинация "LXC + container runtime + NVIDIA + vLLM + long context" дает слишком много переменных. Более профессиональный путь:

- LXC для bare-metal venv;
- VM для Docker/k8s.

### 17.11. Что добавить в acceptance criteria

Новые критерии готовности:

1. `sndr k8s doctor <key>` показывает cluster, node GPU resources, storage и image readiness.
2. `sndr k8s render <key>` генерирует валидный manifest без ручной правки для MicroK8s single-node.
3. `sndr k8s apply <key>` создает namespace, secrets, configmap, deployment, service.
4. `sndr k8s status <key>` показывает pod phase, readiness, GPU allocation, last events.
5. `sndr k8s report <key>` собирает redact bundle.
6. `sndr proxmox doctor` работает на PVE host и внутри LXC/VM.
7. `sndr proxmox render-lxc <key>` генерирует конкретный LXC config snippet с GPU devices/cgroups.
8. `sndr proxmox report --ctid <id>` собирает PVE/LXC/NVIDIA/Docker/venv diagnostics.
9. Документация явно разделяет:
   - Proxmox host bare-metal;
   - Proxmox LXC + venv;
   - Proxmox VM + Docker;
   - Proxmox VM + Kubernetes/MicroK8s.

### 17.12. Почему это стоит делать

Для public core это сильная ценность:

- пользователи клуба и домашние GPU-серверы часто сидят на Proxmox;
- Kubernetes/MicroK8s дает нормальный путь для тех, кто хочет service/restart/logs/monitoring без ручных scripts;
- Proxmox doctor/report позволит быстро разбирать issue без 20 уточняющих вопросов;
- `sndr` станет не просто launcher, а operator toolkit для vLLM deployments.

## 18. Дополнение: universal bootstrap, community configs и tuning как часть единого конфига

Важное уточнение: Proxmox/k8s - это только часть картины. Проекту нужен общий слой установки и настройки, который одинаково понимает:

- чистую систему;
- VM;
- LXC;
- Docker/Podman container;
- systemd-nspawn/rootless container;
- Proxmox host/VM/LXC;
- Kubernetes/MicroK8s/k3s;
- уже существующий рабочий сервер, где нельзя ломать окружение.

Цель: пользователь запускает одну утилиту, получает понятный план, подтверждает установку, получает готовую систему, после чего может подкрутить YAML-конфиг и перезапустить сервис без ручного переписывания scripts.

### 18.1. Новый слой `sndr bootstrap`

Добавить отдельный top-level workflow:

```bash
sndr bootstrap doctor
sndr bootstrap doctor --config <key>
sndr bootstrap plan --config <key>
sndr bootstrap apply --config <key>
sndr bootstrap status --config <key>
sndr bootstrap report --config <key>
sndr bootstrap rollback --last
```

Разница между `deps`, `install`, `launch` и `bootstrap`:

- `deps` проверяет и планирует зависимости;
- `install` готовит конкретный runtime/model/image;
- `launch` запускает уже подготовленный профиль;
- `bootstrap` объединяет system prepare + deps + runtime + model + service registration.

`bootstrap` не должен быть просто shell wrapper. Это должен быть Python workflow с шагами, state-файлом и отчетом.

### 18.2. Что должен определять bootstrap

На старте `sndr bootstrap doctor` должен построить inventory:

```text
HOST
  os:                  Ubuntu 24.04 / Debian / Fedora / Arch / unknown
  kernel:              6.x
  virtualization:      bare_metal | vm | lxc | docker | podman | systemd-nspawn | wsl | unknown
  init:                systemd | openrc | container
  package_manager:     apt | dnf | pacman | zypper | none
  sudo:                available/missing

GPU
  nvidia-smi:          present/missing
  driver:              580.126.09
  cuda_runtime:        13.0
  gpu_count:           2
  gpu_names:           RTX A5000
  nvlink/topology:     detected/unknown

PYTHON
  system python:       3.12.x
  uv:                  present/missing
  venv path:           /opt/sndr/venvs/<profile>

CONTAINER RUNTIME
  docker:              present/missing
  podman:              present/missing
  nvidia toolkit:      present/missing
  cdi devices:         present/missing

MODEL STORAGE
  models_dir:          exists/missing/free space
  hf_cache:            exists/missing/free space
  compile_cache:       exists/missing/free space

SERVICE
  port:                free/used
  systemd:             available/missing
  user service:        possible/impossible
```

Это inventory должно быть сериализуемым в JSON, чтобы tests могли проверять логику без реального GPU.

### 18.3. Единый config-driven install

Добавить в YAML блок `bootstrap`:

```yaml
bootstrap:
  enabled: true
  mode: auto                  # auto | bare_metal | vm | lxc | container | k8s | proxmox
  apply_policy: ask           # ask | plan_only | yes
  privilege:
    require_sudo: true
    allow_root: false
    allow_container_root: true

  os:
    supported:
      - ubuntu: "24.04"
      - ubuntu: "22.04"
      - debian: "12"
    package_sources:
      docker: official_repo
      nvidia_container_toolkit: official_repo
      python: system_or_uv
    allow_add_repositories: ask
    allow_kernel_changes: false

  python:
    manager: uv               # uv | venv | conda
    version: "3.12"
    venv_path: ${runtime_root}/venvs/${config_key}
    requirements_lock: ${project_root}/requirements/sndr-${vllm_pin}.lock

  runtime:
    preferred: docker         # docker | podman | bare_metal_venv | k8s
    fallback: bare_metal_venv
    install_missing: true

  service:
    manager: systemd          # systemd | docker_compose | k8s | none
    name: sndr-${config_key}
    restart: on-failure
    user: sndr
    working_dir: ${project_root}

  artifacts:
    models:
      ensure_present: true
      source: huggingface
      allow_download: ask
    docker_image:
      ensure_present: true
      require_digest: true
    caches:
      create_dirs: true
      check_free_space_gb: 80
```

Пользовательский workflow:

```bash
sndr bootstrap plan --config a5000-2x-35b-fp8-dflash
sndr bootstrap apply --config a5000-2x-35b-fp8-dflash
sndr launch a5000-2x-35b-fp8-dflash
```

После этого пользователь редактирует YAML и делает:

```bash
sndr service restart a5000-2x-35b-fp8-dflash
sndr status a5000-2x-35b-fp8-dflash
```

### 18.4. Установка внутри VM/container/LXC

Нужно явно разделить, что можно установить внутри окружения, а что должно ставиться на host.

Внутри VM можно устанавливать почти все:

- Python/uv/venv;
- Docker/Podman;
- NVIDIA container toolkit, если GPU passthrough корректный;
- vLLM image или bare-metal vLLM;
- systemd service;
- model/cache dirs.

Внутри LXC можно устанавливать:

- Python/uv/venv;
- bare-metal vLLM runtime;
- model/cache dirs;
- user/systemd service, если systemd доступен;
- Docker только как optional/risky mode.

Внутри Docker/Podman container нельзя надежно ставить host-level зависимости:

- NVIDIA kernel driver;
- NVIDIA container toolkit на host;
- Docker daemon;
- kernel modules;
- cgroup host rules.

Поэтому `bootstrap` должен уметь говорить:

```text
BLOCKED: NVIDIA driver is missing, but current environment is docker container.
Run this command on the host:
  sndr bootstrap apply --scope host-gpu-runtime
Then rerun inside the container:
  sndr bootstrap apply --scope app-runtime
```

Это критично, потому что иначе installer будет делать вид, что "установил все", но GPU внутри контейнера все равно не появится.

### 18.5. Scopes вместо одного опасного apply

Добавить scopes:

```bash
sndr bootstrap apply --scope os-packages
sndr bootstrap apply --scope gpu-runtime
sndr bootstrap apply --scope python-runtime
sndr bootstrap apply --scope container-runtime
sndr bootstrap apply --scope model-artifacts
sndr bootstrap apply --scope service
sndr bootstrap apply --scope all
```

Каждый scope должен иметь:

- check;
- plan;
- apply;
- verify;
- rollback note, если настоящий rollback невозможен.

Пример:

```text
STEP gpu-runtime
  check:    nvidia-smi missing
  plan:     install NVIDIA driver 580 from official Ubuntu repository
  risk:     requires reboot
  action:   blocked until --yes --allow-reboot-plan
```

### 18.6. Community config registry

Комьюнити-конфиги должны стать отдельным продуктовым слоем, а не папкой с случайными YAML.

Предложенная структура:

```text
configs/
  stable/
    a5000-2x-35b-fp8-dflash.yaml
  community/
    index.yaml
    models/
      qwen/
      gemma/
      nemotron/
    hardware/
      rtx3090/
      rtx4090/
      a5000/
      a6000/
      l40s/
    runtimes/
      docker/
      podman/
      microk8s/
      proxmox-lxc/
      proxmox-vm/
    tuning/
      memory/
      kv-cache/
      quantization/
      speculative/
```

Команды:

```bash
sndr config list
sndr config search qwen --gpu rtx3090 --runtime docker
sndr config show <community-key>
sndr config validate <path>
sndr config install <community-key>
sndr config export <local-key> --for-community
sndr config diff <stable-key> <community-key>
sndr config report <community-key>
```

Обязательные поля community config:

```yaml
metadata:
  key: community.qwen3.30b.rtx3090x2.int4
  title: Qwen 30B on 2x RTX 3090 INT4
  author: github-user
  source_url: https://github.com/...
  license: MIT
  created_at: "2026-05-09"
  updated_at: "2026-05-09"
  tested:
    status: community_reported     # official | community_reported | experimental | broken
    by: github-user
    date: "2026-05-09"
    hardware: 2x RTX 3090 24GB
    driver: "580.x"
    vllm_pin: "<sha/tag>"
  provenance:
    based_on: stable.a5000-2x-35b-prod
    upstream_prs: []
    related_issues: []
```

Правило качества: community config не должен считаться stable, пока нет:

- полного `sndr doctor` report;
- версии vLLM/image;
- GPU/driver/kernel данных;
- команды запуска;
- минимального benchmark;
- known failures.

### 18.7. Model config как единый контракт

Единый конфиг должен описывать не только команду запуска, а полный контракт модели:

```yaml
model:
  id: Qwen/Qwen3-...
  local_path: ${models_dir}/qwen/...
  trust_remote_code: true
  tokenizer_mode: auto
  dtype: auto
  max_model_len: 32768

engine_args:
  tensor_parallel_size: 2
  gpu_memory_utilization: 0.90
  max_num_seqs: 16
  max_num_batched_tokens: 8192
  enable_chunked_prefill: true
  enforce_eager: false

memory:
  kv_cache_dtype: auto
  swap_space_gb: 0
  cpu_offload_gb: 0
  prefill_policy: auto
  compile_cache: ${cache_root}/compile-cache-${config_key}

features:
  mtp:
    enabled: true
    mode: auto
  dflash:
    enabled: true
    policy: safe
  pflash:
    enabled: false
  turboquant:
    enabled: false
    profile: null
```

Если фича поддерживается vLLM, ядром, патчами core или приватным engine, она должна быть описана в config schema. Если runtime не поддерживает фичу, preflight должен показать:

```text
FEATURE dflash.enabled=true
  requested: yes
  available: no
  reason: patch provider not installed
  fix: install engine overlay or set features.dflash.enabled=false
```

### 18.8. GPU tuning profiles

GPU tuning тоже должен быть в YAML, но применяться строго через capability check.

Пример:

```yaml
gpu_tuning:
  enabled: true
  apply_policy: ask              # ask | plan_only | yes
  profile: a5000-safe-throughput

  nvidia_smi:
    persistence_mode: true
    power_limit_watts: 220
    lock_gpu_clocks: null        # [min,max], only if supported
    lock_memory_clocks: null     # [min,max], only if supported
    compute_mode: default

  topology:
    require_peer_access: false
    prefer_same_numa_node: true
    check_pcie_width: true

  linux:
    ulimits:
      memlock: unlimited
      nofile: 1048576
    shm_size: 8g
    hugepages: disabled
    transparent_hugepages: madvise

  vllm:
    gpu_memory_utilization: 0.90
    max_num_batched_tokens: 8192
    max_num_seqs: 16
    cudagraph_capture_sizes: auto
```

Правила безопасности:

- Не делать overclock/undervolt как default.
- Не менять power limit без проверки допустимого диапазона из `nvidia-smi -q`.
- Не менять clocks, если GPU/driver это не поддерживает.
- Не менять kernel/sysctl параметры без `--yes`.
- Все изменения писать в report.
- Для system-level изменений создавать `sndr tuning revert-plan`.

### 18.9. Tuning providers

Чтобы core не зависел от приватного engine, tuning должен идти через provider registry:

```text
sndr_core.tuning.providers
  nvidia_smi.py
  linux_limits.py
  docker_runtime.py
  vllm_args.py
  core_patches.py

sndr_engine.tuning.providers
  turboquant.py
  dflash.py
  pflash.py
  custom_kernels.py
```

Core знает только контракт:

```text
provider.name
provider.version
provider.capabilities()
provider.plan(config, inventory)
provider.apply(plan)
provider.verify()
```

Если `sndr_engine` не установлен, core просто пишет:

```text
engine providers: not installed
private tuning profiles: unavailable
public config remains valid
```

Так сохраняется правильная модульность: public core не ломается без приватного engine.

### 18.10. Community model tuning workflow

Для комьюнити нужен простой путь:

```bash
sndr tune baseline --config <key>
sndr bench run --config <key> --profile short
sndr tune suggest --config <key>
sndr config export <key> --with-bench --for-community
```

Минимальный benchmark bundle:

```text
hardware.json
driver.json
runtime.json
model_config.yaml
launch_command.txt
metrics.json
logs_redacted.txt
known_failures.md
```

Метрики:

- cold start time;
- time to first token;
- decode tokens/sec;
- prefill tokens/sec;
- VRAM allocated/reserved;
- max stable context;
- OOM boundary;
- error rate;
- exact vLLM commit/image digest.

Это позволит собирать реальные community profiles для RTX 3090/4090/A5000/A6000/L40S и быстро понимать, какие настройки работают.

### 18.11. Service lifecycle

После bootstrap пользователь должен управлять сервисом одной утилитой:

```bash
sndr service install <config-key>
sndr service start <config-key>
sndr service stop <config-key>
sndr service restart <config-key>
sndr service status <config-key>
sndr service logs <config-key>
sndr service uninstall <config-key>
```

Backends:

- systemd user service;
- systemd system service;
- Docker Compose;
- Podman Quadlet;
- Kubernetes Deployment;
- Proxmox LXC/VM helper.

Config должен выбирать backend:

```yaml
service:
  backend: systemd
  user: sndr
  env_file: ${runtime_root}/env/${config_key}.env
  logs:
    backend: journald
    tail_lines: 300
```

### 18.12. Что добавить в acceptance criteria

1. `sndr bootstrap doctor` корректно различает bare metal, VM, LXC, Docker, Podman, Proxmox, k8s node.
2. `sndr bootstrap plan --config <key>` не меняет систему и показывает все действия.
3. `sndr bootstrap apply --config <key>` умеет подготовить чистую Ubuntu VM до состояния "можно запускать vLLM".
4. Внутри container/LXC installer не обещает установить host-level GPU dependencies, а выдает host-side action plan.
5. `sndr config search/install/validate/export` работает для community configs.
6. Community config не проходит stable validation без provenance, tested metadata и benchmark/report bundle.
7. `gpu_tuning` применяется только после capability check.
8. `sndr tuning plan` показывает разницу между requested/current/effective settings.
9. `sndr tuning apply` пишет revert-plan.
10. `sndr service restart <key>` перезапускает профиль после ручного изменения YAML.

### 18.13. Практический приоритет

Внедрять лучше в таком порядке:

1. `bootstrap doctor` и inventory JSON.
2. `bootstrap plan` без apply.
3. `service install/start/status/logs` для systemd и Docker Compose.
4. Community config schema + validation.
5. Community config search/install/export.
6. GPU tuning plan без apply.
7. GPU tuning apply для безопасных действий: persistence mode, ulimits, shm, vLLM args.
8. Advanced GPU tuning: power limit/clocks только после whitelist и manual confirmation.
9. Provider registry для engine tuning.
10. Bench/report bundle для community profiles.

Это даст проекту правильный профессиональный вид: не просто "патчер", а воспроизводимый deployment/tuning toolkit для vLLM на домашних и рабочих GPU-серверах.

## 19. Дополнительные идеи из club-3090, которые стоит доработать и реализовать в SNDR

После повторного просмотра `noonghunna/club-3090` видно, что там ценность не только в отдельных compose-файлах. Главная ценность - это практический слой эксплуатации: issue templates, paste-ready reports, benchmark culture, power sweeps, KV math, engine comparisons, runtime caveats и быстрый feedback loop от реальных RTX 3090/4090/5090 пользователей.

Репозиторий `club-3090` на 2026-05-09:

- публичный Apache-2.0 проект;
- ориентирован на RTX 3090 и похожие consumer GPU;
- содержит vLLM, llama.cpp, SGLang recipes;
- имеет свежие bench/issues по Qwen3.6, Gemma 4, DFlash, MTP, TurboQuant, Proxmox, MicroK8s, WSL2, power caps и nightly regressions;
- уже использует structured rig reports и GitHub issue templates.

SNDR стоит взять не "скрипты как есть", а паттерны и превратить их в типизированные команды, JSON reports, YAML profiles и CI-проверяемые модули.

### 19.1. Regression watch для vLLM/nightly pins

Источник: [club-3090#106](https://github.com/noonghunna/club-3090/issues/106) - vLLM nightly `0.20.2rc1.dev148+g0c2e9d489` падает во время CUDA graph capture / torch.compile, workaround - downgrade до `0.20.1`.

Идея для SNDR:

```bash
sndr upstream watch
sndr upstream check-vllm-pin <config-key>
sndr upstream known-bad add --vllm <sha/tag> --reason "<text>"
sndr upstream known-good promote --config <key> --vllm <sha/tag>
```

В config добавить:

```yaml
upstream:
  vllm:
    required_pin: "0.20.1"
    allowed_pins:
      - "0.20.1"
      - "0.20.2rc1.dev9+g01d4d1ad3"
    blocked_pins:
      - pin: "0.20.2rc1.dev148+g0c2e9d489"
        reason: "CUDA graph capture / torch.compile stream capture crash"
        source: "https://github.com/noonghunna/club-3090/issues/106"
```

Preflight должен блокировать known-bad vLLM pin, если config включает GDN/MTP/cudagraph profile, и предлагать конкретный downgrade.

### 19.2. Power-cap autotuning как нормальная фича

Источник: [club-3090#83](https://github.com/noonghunna/club-3090/pull/83) и `scripts/power-cap-sweep.sh`. В club-3090 это большой bash-скрипт, который делает sweep power limit, запускает bench, собирает TPS/W, clocks, temps, throttle, P-state и ищет efficiency knee.

Для SNDR это надо превратить в:

```bash
sndr tune power plan --config <key>
sndr tune power sweep --config <key> --mode decode-single
sndr tune power sweep --config <key> --mode decode-concurrent --concurrency auto
sndr tune power sweep --config <key> --mode prefill-heavy
sndr tune power apply --profile <generated-profile>
sndr tune power report --last
```

В config:

```yaml
gpu_tuning:
  power_sweep:
    enabled: true
    modes:
      - decode-single
      - decode-concurrent
      - prefill-heavy
    step_watts: 10
    bench_runs: 3
    choose_policy: best_tps_per_watt_within_5_percent_peak
    apply_selected_cap: ask
```

Профессиональное отличие SNDR от club-3090:

- не писать только `/tmp/power-cap-summary.md`;
- сохранять `results/power_sweeps/<timestamp>/metrics.json`;
- генерировать YAML tuning profile;
- уметь rollback power limit;
- разделять decode и prefill profiles;
- не применять `nvidia-smi -pl` без capability/range check.

### 19.3. KV/memory calculator как `sndr memory explain`

Источник: `club-3090/tools/kv-calc.py` и issues по OOM/cliffs: [#35](https://github.com/noonghunna/club-3090/issues/35), [#47](https://github.com/noonghunna/club-3090/issues/47), [#58](https://github.com/noonghunna/club-3090/issues/58), [#60](https://github.com/noonghunna/club-3090/issues/60).

В club-3090 калькулятор уже считает per-card budget: weights, KV pool, GDN activation peak, cudagraph/workspace overhead, PASS/TIGHT/FAIL.

Для SNDR:

```bash
sndr memory explain <config-key>
sndr memory fit <model-id> --gpu rtx3090 --count 1
sndr memory fit <model-id> --gpu rtx3090 --count 2 --runtime docker
sndr memory suggest --config <key> --target-context 180000
```

Вывод должен быть не только markdown, а структурный:

```text
MODEL WEIGHTS        17.7 GiB total / 8.9 GiB per TP rank
KV CACHE             5.8 GiB per GPU at 48,960 tokens
GDN ACTIVATION PEAK  0.8 GiB estimated
CUDA GRAPH           0.05 GiB estimated
FREE HEADROOM        0.6 GiB
VERDICT              TIGHT
SUGGESTIONS
  - reduce max_model_len: 262144 -> 188000
  - reduce gpu_memory_utilization: 0.96 -> 0.93 if desktop session is active
  - switch turboquant_3bit_nc -> fp8_e5m2 on 20GB Ampere
```

Это должно стать частью `sndr bootstrap plan`, чтобы пользователь до запуска понимал, почему config может не влезть.

### 19.4. Engine-agnostic harness

Источник: [club-3090#87](https://github.com/noonghunna/club-3090/issues/87). Там зафиксирована правильная проблема: verify/soak scripts были привязаны к vLLM Docker container, а людям нужны llama.cpp host builds, non-Docker builds и разные engines.

Для SNDR:

```bash
sndr verify endpoint --url http://localhost:8000/v1 --model <name>
sndr verify engine --config <key>
sndr soak run --config <key>
sndr bench run --config <key>
sndr report bundle --config <key>
```

Архитектура:

```text
sndr_core/harness/
  endpoint.py          # OpenAI-compatible HTTP checks
  engines/
    vllm.py
    llamacpp.py
    sglang.py
  probes/
    structured_output.py
    long_context.py
    tool_calling.py
    spec_decode.py
    memory_soak.py
```

Правило: базовый verify должен работать по HTTP без знания Docker/container. Engine-specific checks должны быть plugin layer, а не hardcoded path.

### 19.5. Report bundle нового уровня

Источник: `club-3090/scripts/report.sh` и issue templates `numbers-from-your-rig.yml`. Там хорошая практика: пользователь прикладывает не слова, а стандартизированный report с OS/kernel/GPU/driver/power/PCIe/NVLink/logs/bench.

Для SNDR надо сделать:

```bash
sndr report bundle --config <key>
sndr report bundle --scope system,gpu,runtime,model,logs,bench
sndr report redact <bundle>
sndr report print --markdown <bundle>
```

Report должен собирать:

- OS/kernel/init/virtualization;
- CPU/RAM/swap;
- GPU names/VRAM/driver/CUDA/VBIOS/power caps/persistence;
- PCIe lanes/gen/NVLink/topology;
- Docker/Podman/k8s/Proxmox runtime;
- exact vLLM pin/image digest;
- model id/local path/config hash;
- active SNDR patches/providers;
- service logs;
- benchmark summary;
- memory explain output;
- redaction of users, hostnames, paths, HF/API tokens.

Это должно быть главным требованием для community configs: нет report bundle - config не может быть promoted.

### 19.6. Residency instrumentation для memory cliffs

Источник: `club-3090/tools/residency-instrument/instrument.py`. Это observational instrumentation через `sitecustomize.py`, который пишет CSV по request/engine/worker boundaries: allocated/reserved/free, KV blocks, Genesis pools, MTP resident bytes, FlashInfer workspace, CUDA graph memory, fragmentation.

Для SNDR:

```bash
sndr trace memory start --config <key>
sndr trace memory stop
sndr trace memory summarize <csv>
sndr trace memory compare before.csv after.csv
```

В config:

```yaml
observability:
  memory_trace:
    enabled: false
    mode: sitecustomize
    output_dir: ${runtime_root}/traces/${config_key}
    include_cuda_memory: true
    include_kv_blocks: true
    include_patch_pools: true
```

Это критично для доказательства качества патчей: не просто "стало лучше", а видно, какой pool растет, где fragmentation, где cudagraph private memory.

### 19.7. Compose/import converter

Источник: в club-3090 много compose variants:

- Qwen3.6 dual/turbo/nvlink/dflash/noviz;
- Gemma 4 MTP/DFlash;
- bounded-thinking;
- long-text/long-vision/tools-text;
- llama.cpp/SGLang alternatives.

Для SNDR нужен importer:

```bash
sndr import compose path/to/docker-compose.yml --out config.yaml
sndr import club3090 issue 104
sndr import club3090 repo --model qwen3.6-27b
sndr config normalize <config>
sndr config explain <config>
```

Importer должен вытаскивать:

- image/tag/digest;
- model mount;
- command args;
- env vars;
- ports;
- GPU devices;
- cache mounts;
- patch mounts;
- runtime caveats from comments.

Это позволит быстро переводить community compose в единый SNDR YAML без ручной работы.

### 19.8. Hardware profile database

Источник: `club-3090/docs/HARDWARE.md`, issues [#103](https://github.com/noonghunna/club-3090/issues/103), [#104](https://github.com/noonghunna/club-3090/issues/104), [#105](https://github.com/noonghunna/club-3090/issues/105), [#95](https://github.com/noonghunna/club-3090/issues/95), [#93](https://github.com/noonghunna/club-3090/issues/93), [#71](https://github.com/noonghunna/club-3090/issues/71).

Сделать локальную базу:

```text
vllm/sndr_core/hardware/profiles/
  rtx3090.yaml
  rtx4090.yaml
  rtx5090.yaml
  a5000.yaml
  a6000.yaml
  l40s.yaml
```

Поля:

```yaml
gpu:
  canonical_name: RTX 3090
  vram_gb: 24
  sm: "8.6"
  memory_bandwidth_gb_s: 936
  default_power_watts: 350
  recommended_power:
    decode_single_air: 290
    decode_single_water: 330
    prefill_heavy: 250
  known_caveats:
    - display_attached_reduces_usable_vram
    - nvlink_optional
    - pcie_x8_may_reduce_tp_scaling
```

`sndr doctor` должен сверять фактический rig с profile:

- power cap сильно ниже default;
- negotiated PCIe lanes ниже GPU max;
- NVLink установлен/нет;
- persistence mode off;
- driver ниже required;
- desktop session eats VRAM;
- GPU count не совпадает с config.

### 19.9. Runtime caveat registry

Источник: `club-3090/docs/CONTAINER_RUNTIMES.md`, [#49](https://github.com/noonghunna/club-3090/issues/49), [#99](https://github.com/noonghunna/club-3090/pull/99), [#84](https://github.com/noonghunna/club-3090/pull/84).

Сделать в SNDR:

```yaml
runtime_caveats:
  - id: proxmox-docker-uvloop-617
    match:
      virtualization: proxmox
      runtime: docker
      kernel: "6.17.*"
    severity: warn
    recommendation: bare_metal_venv
    source: "https://github.com/noonghunna/club-3090/issues/49"
```

CLI:

```bash
sndr caveats list
sndr caveats check --config <key>
sndr caveats explain proxmox-docker-uvloop-617
```

Это лучше, чем размазывать caveats по README/install.sh.

### 19.10. Config override policy

Источник: [club-3090#79](https://github.com/noonghunna/club-3090/pull/79) - env override для `MAX_MODEL_LEN` и `GPU_MEMORY_UTILIZATION`; [#84](https://github.com/noonghunna/club-3090/pull/84) - `PYTORCH_CUDA_ALLOC_CONF`; [#99](https://github.com/noonghunna/club-3090/pull/99) - `VLLM_ENFORCE_EAGER`.

Для SNDR:

```bash
sndr config override <key> max_model_len=90000
sndr config override <key> gpu_memory_utilization=0.90
sndr config override <key> enforce_eager=true
sndr config render-env <key>
```

В YAML:

```yaml
overrides:
  allow_env:
    - MAX_MODEL_LEN
    - GPU_MEMORY_UTILIZATION
    - VLLM_ENFORCE_EAGER
    - PYTORCH_CUDA_ALLOC_CONF
  safe_ranges:
    max_model_len: [8192, 320000]
    gpu_memory_utilization: [0.70, 0.98]
```

Тогда пользователь не редактирует compose/scripts, а меняет config или env поверх config с validation.

### 19.11. CPU/container resource checks

Источник: [club-3090#90](https://github.com/noonghunna/club-3090/issues/90) - llama.cpp container выглядел ограниченным одним CPU core.

Для SNDR doctor:

- проверять cgroup CPU quota;
- проверять cpuset;
- проверять Docker Compose `cpus`, `cpu_quota`, `cpuset`;
- проверять thread flags для llama.cpp/SGLang/vLLM;
- показывать effective CPU threads.

CLI:

```bash
sndr doctor cpu
sndr doctor container-resources
```

Вывод:

```text
CPU quota: 100000/100000 = 1 core effective
Host threads: 16
Container visible threads: 16
Effective allowed threads: 1
Fix: remove cpu_quota or set service.deploy.resources / --cpus
```

### 19.12. One-click templates без привязки к RunPod

Источник: [club-3090#3](https://github.com/noonghunna/club-3090/pull/3) - RunPod template. Идея правильная: один клик для 1x/2x3090 с Genesis/marlin patches.

Для SNDR не стоит ограничиваться RunPod:

```bash
sndr template render runpod --config <key>
sndr template render docker-compose --config <key>
sndr template render systemd --config <key>
sndr template render proxmox-cloudinit --config <key>
sndr template render k8s --config <key>
sndr template render terraform --provider runpod --config <key>
```

Ценность: тот же model config порождает разные deployment targets.

### 19.13. Gemma 4 integration track

Источник: [club-3090#103](https://github.com/noonghunna/club-3090/issues/103), [#81](https://github.com/noonghunna/club-3090/pull/81), [#68](https://github.com/noonghunna/club-3090/pull/68), [#89](https://github.com/noonghunna/club-3090/issues/89).

Идея:

- отдельные Gemma 4 configs;
- MTP/DFlash variants;
- INT8/AWQ/NVFP4/fp8 KV experiments;
- parser/tool-call profile;
- strict model support matrix.

Для SNDR:

```text
configs/community/models/gemma4/
  gemma4-31b-awq-2x3090-mtp.yaml
  gemma4-31b-awq-2x3090-dflash.yaml
  gemma4-31b-5090-laptop-wsl2.yaml
```

И отдельный doctor:

```bash
sndr model doctor gemma4 --config <key>
```

Проверять:

- tokenizer/chat template;
- tool parser support;
- DFlash drafter compatibility;
- KV dtype compatibility;
- memory fit;
- known upstream PR dependency.

### 19.14. Issue/discussion import pipeline

club-3090 issues часто содержат ценные данные в markdown report. Это надо собирать автоматически.

Команды:

```bash
sndr community import-issue noonghunna/club-3090#104
sndr community import-issue noonghunna/club-3090#105
sndr community import-repo noonghunna/club-3090 --issues --benches
sndr community summarize --model qwen3.6 --gpu rtx3090
```

Extractor должен парсить:

- OS/kernel;
- CPU/RAM;
- GPU names/VRAM/driver;
- power caps;
- PCIe lanes;
- NVLink/topology;
- model/config;
- TPS;
- max context;
- failure text;
- workaround.

Результат:

```text
community_data/
  club-3090/
    issues/104.json
    issues/105.json
    hardware_matrix.csv
    benchmark_matrix.csv
    known_failures.yaml
```

Это можно использовать для docs, config recommendations и automatic warnings.

### 19.15. Приоритет внедрения этих идей

1. `sndr report bundle` - самая быстрая и полезная победа.
2. `sndr memory explain` - сразу уменьшит количество OOM/issues.
3. `sndr upstream known-good/known-bad` - защитит от vLLM nightly regressions.
4. `sndr config override` - заменит ручное редактирование YAML/compose.
5. `sndr doctor hardware` - PCIe/NVLink/power/driver/topology.
6. `sndr tune power sweep` - сильная community-фича и реальная оптимизация.
7. `sndr import compose` - мост из club-3090 в SNDR configs.
8. `sndr verify endpoint` - engine-agnostic harness.
9. `sndr trace memory` - advanced mode для разработки патчей.
10. `sndr community import-issue` - долгосрочная база знаний.

Главная мысль: club-3090 дает сырые реальные данные и быстрые recipes. SNDR должен стать слоем, который превращает эти данные в воспроизводимые configs, typed checks, reports, tuning profiles и production workflow.
