# Полный аудит проекта Genesis / SNDR Core

Дата: 2026-05-09  
Репозиторий: `/Users/sander/Documents/Visual Studio Code/genesis-vllm-patches`  
Режим: только аудит и план. Исходный код проекта не изменялся. Создан только этот Markdown-отчет.

## 1. Краткий вывод

Проект сейчас находится в переходном состоянии: старая структура `vllm/_genesis` уже удаляется, новая структура `vllm/sndr_core` создана и по объему стала основным ядром, но переход еще не завершен. В коде уже есть правильное направление: единая схема `ModelConfig`, CLI `sndr`, отдельные подсистемы для install/launch/deps/service/k8s/proxmox/tune, публичный `core` и задел под приватный `engine`.

При этом текущее состояние нельзя считать production-ready. Есть критическая синтаксическая ошибка, из-за которой импорт основного CLI ломается. Есть незавершенная регистрация новых файлов в git, противоречия между документацией и фактическим кодом, несогласованные пути пользовательских конфигов, не полностью реализованные bootstrap/deploy/runtime сценарии, заглушки в Kubernetes/Proxmox/service, а также большое количество устаревших ссылок на `vllm/_genesis`, `~/.genesis` и старые команды.

Главная техническая проблема не в идее структуры, а в незавершенной интеграции: много хороших модулей уже написано, но часть из них пока живет как отдельные острова. Нужно довести проект до единого контракта: `sndr config -> sndr deps -> sndr install/bootstrap -> sndr launch -> sndr service/deploy -> sndr report`.

## 2. Что проверялось

Проверялись:

- структура репозитория и git-состояние;
- новый пакет `vllm/sndr_core`;
- граница `vllm/sndr_engine`;
- CLI и точки входа;
- схема model config и builtin/community конфиги;
- install/bootstrap/deps/launch/service/k8s/proxmox/tune;
- registry/dispatcher патчей;
- shell-скрипты и старые wrappers;
- документация, внутренние планы, roadmap/backlog/audit-файлы;
- синтаксис Python/TOML/JSON/YAML;
- текущие симптомы тестов;
- хардкод путей, IP, старых имен и legacy-ссылок.

## 3. Текущее состояние реализации

### 3.1. Новый `sndr_core`

Реализовано:

- пакет `vllm/sndr_core`;
- CLI entrypoint в `pyproject.toml`: `sndr = vllm.sndr_core.cli:cli_main`;
- legacy alias: `genesis = vllm.sndr_core.compat.cli:main`;
- plugin entrypoint для vLLM: `vllm.general_plugins = genesis_v7 = vllm.sndr_core.plugin:register`;
- крупная схема `ModelConfig`;
- builtin model configs;
- registry патчей;
- install/launch/deps/service/tune/k8s/proxmox/bootstrap/config/model commands;
- compatibility layer для старой логики;
- split между публичным `sndr_core` и будущим приватным `sndr_engine`.

Оценка: направление правильное. Архитектура стала ближе к профессиональному пакету, чем старая монолитная `_genesis`-структура. Но переход не завершен, и сейчас проект ломается на уровне базового импорта CLI.

### 3.2. Публичный core и приватный engine

Текущая идея корректная:

- `sndr_core` должен быть бесплатным публичным ядром;
- `sndr_engine` должен быть приватным overlay для платных патчей/утилит;
- `core` должен знать, что engine может существовать, но не зависеть от него жестко;
- при отсутствии engine публичная версия должна работать полностью.

Проблема: `vllm/sndr_engine/` сейчас игнорируется `.gitignore:86`, поэтому даже публичный skeleton engine не попадет в репозиторий. Если документация и код ожидают наличие безопасной пустой оболочки, ее нужно либо:

- хранить в публичном репозитории как skeleton, игнорируя только приватные подпапки/файлы;
- либо полностью убрать ожидания наличия `vllm/sndr_engine` из публичной поставки и использовать безопасный dynamic import.

Сейчас граница задумана правильно, но оформлена не до конца.

## 4. Критические ошибки

### P0. Основной CLI сейчас не импортируется

Файл: `vllm/sndr_core/cli/k8s.py:175-179`

Проблемный участок:

```python
f"        volumeMounts:\n"
f"{storage_mounts if storage_mounts else '        []\n'}"
f"      volumes:\n"
f"{storage_volumes if storage_volumes else '      []\n'}"
)
```

Ошибка:

```text
SyntaxError: f-string expression part cannot include a backslash
```

Причина: внутри выражения f-string используется строковый литерал с `\n`. Это запрещено синтаксисом Python.

Последствие:

- `import vllm.sndr_core.cli` падает;
- `sndr` как entrypoint ломается;
- команды `sndr install`, `sndr launch`, `sndr config`, `sndr deps`, `sndr service`, `sndr k8s` не могут стабильно работать;
- тесты CLI падают не из-за бизнес-логики, а из-за синтаксиса.

Дополнительная причина усиления проблемы: `vllm/sndr_core/cli/__init__.py:49-67` делает eager import всех native CLI модулей, включая `k8s`. Поэтому одна ошибка в optional-команде ломает весь CLI.

Что сделать:

1. Исправить генерацию YAML в `k8s.py`, вынеся fallback-строки из f-string expression.
2. Переделать регистрацию native subcommands на lazy import.
3. Гарантировать, что `sndr --help`, `sndr config`, `sndr launch` не зависят от исправности `k8s`, `proxmox` или других optional-команд.

### P0. Текущие тесты CLI фактически красные

Проверка:

```bash
python3 -m pytest -q tests/unit/cli/test_c10_c11_c12.py
```

Результат:

```text
19 failed in 0.24s
```

Причина всех падений: тот же `SyntaxError` в `vllm/sndr_core/cli/k8s.py:179`.

Противоречие документации:

- `README.md:45` заявляет `2994 passed / 0 failed / 94 skipped`;
- `docs/_internal/INTEGRATED_PLAN_2026-05-09.md:8-10` заявляет зеленый pytest;
- `docs/upstream/PRODUCTION_ROADMAP_2026-05-09.md:10-12` заявляет зеленый pytest.

Фактическое состояние локального дерева этому не соответствует.

Что сделать:

1. Исправить P0 syntax bug.
2. Запустить минимальный gate:
   - AST parse всех Python файлов;
   - `python -m pytest tests/unit/cli/test_c10_c11_c12.py`;
   - `python -c "import vllm.sndr_core.cli"`;
   - `sndr --help`.
3. После этого обновлять README/roadmap только фактическими результатами.

### P0. Новая ключевая структура не отслеживается git

Факты:

- `pyproject.toml` сейчас untracked;
- `vllm/sndr_core/` сейчас untracked;
- `vllm/sndr_engine/` игнорируется `.gitignore`;
- `git ls-files vllm/sndr_core vllm/sndr_engine` возвращает пустой список.

Последствие:

- публичная сборка не воспроизводима;
- package metadata может не попасть в репозиторий;
- entrypoint `sndr` может не существовать после clone/install;
- невозможно говорить о production release, пока основной код не зарегистрирован в VCS.

Что сделать:

1. Добавить `pyproject.toml` и `vllm/sndr_core/**` в git.
2. Решить политику для `vllm/sndr_engine`:
   - публичный skeleton отслеживается;
   - приватные реализации игнорируются;
   - или engine полностью отсутствует из public repo и импортируется только как optional namespace.
3. Добавить CI-проверку, что release-critical файлы не untracked.

## 5. Высокие риски и функциональные баги

### P1. `sndr config new` пишет не туда, где registry ищет конфиги

Файлы:

- `vllm/sndr_core/cli/config.py:68-79`;
- `vllm/sndr_core/cli/config.py:367-368`;
- `vllm/sndr_core/model_configs/registry.py:53-59`.

Сейчас CLI config пишет новые конфиги в:

```text
~/.sndr/configs/<key>.yaml
```

Registry ищет пользовательские model configs в:

```text
~/.sndr/model_configs
```

Последствие: пользователь создает конфиг командой `sndr config new`, но `sndr launch <key>` через registry может его не найти.

Что сделать:

1. Выбрать один canonical path.
2. Рекомендованный вариант:
   - model configs: `~/.sndr/model_configs`;
   - runtime config: `~/.sndr/config.yaml`;
   - host paths: `~/.sndr/host.yaml`;
   - generated compose/manifests: `~/.sndr/generated`.
3. Ввести migration warning для `~/.sndr/configs`.

### P1. `service` генерирует некорректный systemd unit

Файл: `vllm/sndr_core/cli/service.py:88-112`

Проблемы:

- `ExecStart=/usr/bin/env sndr launch <key>` допустим;
- `ExecStop=/usr/bin/env sndr launch <key> --uninstall` некорректен, потому что `sndr launch` не имеет `--uninstall`;
- для system-level unit используется `WantedBy=default.target`, хотя обычно нужен `multi-user.target`;
- schema допускает `restart: unless-stopped`, но systemd не поддерживает Docker-style значение `unless-stopped`.

Последствие: `sndr service install/start/stop` может создать unit, который не остановится или не включится корректно.

Что сделать:

1. Ввести отдельный backend contract:
   - bare-metal systemd;
   - docker;
   - docker compose;
   - podman quadlet;
   - kubernetes;
   - proxmox.
2. Для systemd:
   - `ExecStart=sndr launch <key> --runtime bare`;
   - `ExecStop` либо отсутствует, либо вызывает корректный stop command;
   - `Restart` маппится в systemd-совместимые значения;
   - `WantedBy=multi-user.target` для system unit.
3. Добавить unit render tests.

### P1. `bootstrap apply_policy: auto-yes` не работает как описано

Файл: `vllm/sndr_core/cli/bootstrap.py:185-198`

Документация в коде говорит, что `auto-yes` должен запускать apply без `--yes`. Фактически в `run_apply` передается:

```python
yes=args.yes
```

То есть `auto-yes` не превращается в `yes=True`.

Последствие: конфигурация обещает автоматический apply, но команда остается dry-run/blocked без явного `--yes`.

Что сделать:

1. Четко разделить политики:
   - `never`: запрет apply;
   - `manual`: требуется `--yes`;
   - `auto-yes`: разрешить apply без CLI `--yes`;
   - `unsafe`: разрешить опасные действия только при отдельном флаге.
2. Покрыть тестами `bootstrap apply`.

### P1. Bootstrap scopes частично no-op

Файл: `vllm/sndr_core/cli/bootstrap.py:87-100`

Проблема:

- `model-artifacts` маппится в `model`, но planners не создают `PlanItem.scope == "model"`;
- `service` вообще не маппится;
- `kubernetes` и `proxmox` не интегрированы в общий bootstrap план.

Последствие: пользователь может включить scope в YAML, но реальных действий не будет.

Что сделать:

1. Согласовать scope enum между schema, bootstrap и planners.
2. Для каждого scope дать:
   - checker;
   - planner;
   - installer/apply;
   - dry-run output;
   - тест.

### P1. Kubernetes поддержка пока scaffold, не production deploy

Файлы:

- `vllm/sndr_core/cli/k8s.py`;
- `vllm/sndr_core/model_configs/schema.py:319-391`.

Проблемы:

- текущий `k8s.py` синтаксически ломает CLI;
- default namespace в schema: `genesis`, а не `sndr`;
- image digest может использоваться как standalone image, если `image_digest` содержит только `sha256:...`;
- storage реализован через `hostPath`, что подходит только для single-node/dev, но не для нормального multi-node Kubernetes;
- нет PVC/NFS/Ceph/S3/local-path abstraction;
- нет Secret для HF/API ключей;
- нет securityContext, nodeSelector, tolerations, affinity;
- нет Helm/Kustomize output;
- нет проверки GPU operator / NVIDIA runtime class;
- нет полноценного lifecycle: apply/delete/status/logs с безопасными подтверждениями и namespace handling.

Что сделать:

1. Сначала починить syntax/import.
2. Разделить profiles:
   - `microk8s`;
   - `k3s`;
   - `vanilla`;
   - `proxmox-k8s`;
   - `cloud`.
3. Ввести render-only режим как стабильный baseline.
4. Добавить `sndr k8s doctor`, который проверяет:
   - `kubectl`;
   - context;
   - namespace;
   - GPU resources;
   - runtimeClass;
   - storageClass;
   - pull secrets;
   - service exposure.

### P1. Proxmox поддержка пока read-only helper, не полноценная интеграция

Файлы:

- `vllm/sndr_core/cli/proxmox.py`;
- `vllm/sndr_core/model_configs/schema.py:393-459`.

Реализовано:

- `doctor`;
- `inventory`;
- `render`;
- `status`;
- базовые команды-шаблоны для LXC/VM.

Проблемы:

- в docstring указано, что PVE API пока не используется;
- нет реального `apply`;
- нет проверки IOMMU/VFIO/PCI passthrough;
- нет проверки cgroups/devices для LXC;
- нет проверки NVIDIA driver/runtime внутри guest/container;
- жестко зашиты:
  - `/var/lib/vz/template/cache/ubuntu-24.04-standard.tar.gz`;
  - `local-lvm:64`;
  - `vmbr0`;
  - memory `65536`;
  - cores `8`;
  - `/opt/sndr-venv`;
  - Docker install через `curl -fsSL https://get.docker.com | sh`.

Последний пункт конфликтует с общей политикой безопасности deps installer, где `curl | bash` запрещается.

Что сделать:

1. Оставить текущий Proxmox как `render/doctor` preview.
2. Добавить PVE API mode:
   - token auth;
   - node/storage/network discovery;
   - LXC/VM create/update;
   - dry-run diff;
   - explicit apply.
3. Поддержать три режима:
   - host install;
   - VM install;
   - LXC install.
4. Добавить вывод инвентаризации GPU, driver, kernel, IOMMU, runtime, storage, network.

### P1. Docker image digest проверяется, но запуск идет по tag

Файл: `vllm/sndr_core/model_configs/schema.py`

Проблема:

- `_verify_image_digest` в launcher проверяет digest;
- `_build_docker_cmd` использует `d.image`, а не canonical `image@sha256:...`.

Последствие: если tag был перетянут позже, можно проверить один digest, а запустить другой образ по tag.

Что сделать:

1. В schema ввести canonical resolved image ref.
2. Если задан digest, запускать:

```text
repo/image@sha256:<digest>
```

3. В отчете dry-run явно показывать:
   - declared tag;
   - resolved digest;
   - exact image ref used for launch.

### P1. Launcher не запускает полный preflight перед live launch

Файл: `vllm/sndr_core/cli/launch.py`

Хорошо реализовано:

- dry-run;
- constraints check;
- unresolved mount diagnostics;
- docker launch path;
- container bootstrap apply;
- digest verification.

Недостаток: перед live launch нет единого `preflight_all()` как обязательного gate.

Что сделать:

1. Перед live launch выполнять:
   - model artifacts check;
   - mounts check;
   - docker/runtime check;
   - GPU count/VRAM check;
   - package version check;
   - config schema validation;
   - patch dependency/conflict check.
2. Добавить флаг:
   - `--preflight-only`;
   - `--skip-preflight`;
   - `--strict`.

## 6. Средние проблемы и технический долг

### P2. В дереве много generated/cache файлов

Факты:

- найдено 107 директорий `__pycache__`;
- найдено 1380 файлов `.pyc`;
- внутри `vllm/sndr_core` найдено около 570 generated/cache файлов.

Даже если они игнорируются git, они мешают аудиту, поиску и релизной чистоте.

Что сделать:

1. Очистить generated cache перед релизом.
2. Добавить make/task:

```text
sndr dev clean
```

3. В CI проверять, что release artifact не содержит `.pyc`, `__pycache__`, `.DS_Store`.

### P2. Документация массово содержит старые команды и пути

Примеры:

- `README.md:267`, `README.md:299`, `README.md:614` используют `genesis preflight`;
- `README.md:677` рекомендует `python3 -m vllm.sndr_core.patches.apply_all`, но такого модуля нет;
- `docs/INSTALL.md:356`, `docs/INSTALL.md:366` все еще говорят про `vllm/_genesis`;
- `docs/INSTALL.md:416`, `docs/INSTALL.md:477`, `docs/INSTALL.md:554` используют несуществующий `vllm.sndr_core.patches.apply_all`;
- `docs/MODEL_CONFIG_LAUNCHER.md:27` говорит про `~/.genesis/model_configs`;
- `docs/MODEL_CONFIG_LAUNCHER.md:129` монтирует `vllm/_genesis`;
- `scripts/launch.sh:11-12` советует `genesis model-config new` и `~/.genesis/model_configs`.

Что сделать:

1. Ввести canonical public docs:
   - `docs/QUICKSTART.md`;
   - `docs/INSTALL.md`;
   - `docs/CONFIGS.md`;
   - `docs/LAUNCH.md`;
   - `docs/DEPLOY.md`;
   - `docs/TROUBLESHOOTING.md`.
2. Все legacy docs перенести в:

```text
docs/archive/
```

3. Добавить CI grep gate на запрещенные live references:
   - `vllm/_genesis`;
   - `~/.genesis`;
   - `genesis preflight`;
   - `vllm.sndr_core.patches.apply_all`;
   - private IP defaults.

### P2. Хардкод путей и адресов еще остался

Активные примеры:

- `scripts/fetch_models.sh:39`: `/nfs/genesis/models`;
- `scripts/launch/preflight_check.sh:85`: `/nfs/genesis/models`;
- `scripts/launch/preflight_check.sh:97-99`: `${HOME}/Genesis_Project/...`;
- `scripts/launch/preflight_check.sh:114`: `${HOME}/genesis-vllm-patches`;
- `scripts/launch/preflight_check.sh:149-152`: docker network `genesis-vllm-patches_default`;
- `tests/soak/pn40_soak_1000.py:6,22`: `http://192.168.1.10:8000/v1/chat/completions`;
- `tests/bench/comprehensive_bench.py:18,40,43`: `192.168.1.10`, `sander@192.168.1.10`;
- `vllm/sndr_core/cli/proxmox.py`: hardcoded Proxmox paths/resources;
- `README.md:605`, `README.md:611`, `README.md:615`, `README.md:650`: private examples.

Часть private values допустима в tests/examples, но они должны быть явно помечены как examples и не должны быть runtime defaults.

Что сделать:

1. Runtime defaults брать из:
   - `SNDR_HOME`;
   - `SNDR_MODEL_CONFIG_DIR`;
   - `SNDR_MODELS_ROOT`;
   - `~/.sndr/host.yaml`;
   - model config.
2. Все private IP/paths сделать example-only.
3. Для bench/soak добавить обязательный `--base-url` или env `SNDR_BENCH_BASE_URL`.

### P2. Registry патчей есть, но metadata неполная

Фактическая картина registry:

- всего registry entries: 135;
- все entries сейчас `community`;
- lifecycle:
  - experimental: 93;
  - legacy: 33;
  - retired: 5;
  - research: 3;
  - coordinator: 1;
- `implementation_status` явно отсутствует у 128 entries;
- apply module есть примерно у 122 entries.

Отдельные проблемные статусы:

- `P82`: research;
- `P83`: research;
- `PN95`: partial;
- `PN26b`: research, без apply module;
- `PN64`: placeholder, без apply module.

Оценка: перенос платных/приватных патчей в public core в целом соответствует текущей стратегии. Но registry должен стать строгим контрактом, а не описательной таблицей.

Что сделать:

1. Для каждого patch spec сделать обязательными:
   - id;
   - title;
   - tier;
   - lifecycle;
   - implementation_status;
   - apply_module;
   - dependencies;
   - conflicts;
   - risk;
   - test coverage;
   - upstream PR/issue link, если есть.
2. Добавить CI:
   - no missing implementation_status;
   - no live patch without apply_module;
   - no community patch importing `sndr_engine`;
   - no duplicate IDs;
   - no retired patch in default apply set.

### P2. `_per_patch_dispatch.py` остается структурным долгом

Сейчас часть логики патчей все еще выглядит как большой legacy-dispatch слой. Это мешает:

- тестируемости;
- dependency/conflict resolution;
- переносу core/engine;
- включению/отключению patch packs;
- объяснимому dry-run.

Что сделать:

1. Перейти на spec-driven dispatch.
2. Каждый patch module должен иметь:
   - `spec`;
   - `probe()`;
   - `apply()`;
   - `rollback` или explicit no-rollback;
   - `tests`;
   - `risk notes`.
3. Центральный dispatcher только строит graph и вызывает модули.

### P2. `license.py` пока не готов к production trust model

Файл: `vllm/sndr_core/license.py`

Проблемы:

- trust anchor пока placeholder zero key;
- при импорте логируется предупреждение;
- реальный Ed25519 public key ceremony не завершен;
- legacy unsigned key path доступен только через `SNDR_ALLOW_LEGACY_LICENSE_KEYS=1`, что нормально для тестов, но не для production.

Что сделать:

1. Сгенерировать реальный Ed25519 signing key offline.
2. В public core хранить только public verify key.
3. В release pipeline подписывать:
   - engine wheel;
   - patch manifest;
   - license token schema;
   - SBOM/provenance.
4. Добавить `sndr license verify --offline`.

## 7. Оценка структуры проекта

### Что сделано хорошо

- Появился отдельный `sndr_core` вместо старого `_genesis`.
- Появилась модель публичного core и будущего private engine.
- Есть `pyproject.toml`, packaging metadata и entrypoints.
- `ModelConfig` стал центральным объектом.
- Builtin configs уже загружаются registry.
- Есть совместимость через `compat`, что снижает риск резкого слома старых команд.
- Появились отдельные подсистемы:
  - `cli`;
  - `deps`;
  - `model_configs`;
  - `patches`;
  - `runtime`;
  - `configs`;
  - `utils`;
  - `kernels`.

### Что структурно слабо

1. Слишком много команд импортируются eager.
2. CLI, schema, docs и scripts не имеют одного source of truth.
3. Старые scripts еще живут рядом с новой CLI-архитектурой и создают две параллельные системы.
4. Docs утверждают, что часть задач выполнена, но код это не подтверждает.
5. Deploy layers пока неравномерны:
   - Docker лучше всего связан с launcher;
   - systemd частично;
   - Kubernetes scaffold;
   - Proxmox scaffold;
   - Podman/Quadlet почти не реализован.
6. Engine boundary концептуально есть, но физически не оформлен как стабильный public/private contract.

### Рекомендуемая целевая структура

```text
vllm/
  sndr_core/
    cli/
      main.py
      commands/
        config.py
        deps.py
        install.py
        launch.py
        service.py
        k8s.py
        proxmox.py
        tune.py
        report.py
    config/
      schema.py
      registry.py
      renderers/
      validators/
    deploy/
      docker/
      compose/
      systemd/
      podman/
      kubernetes/
      proxmox/
    deps/
      checkers.py
      planners.py
      installers.py
      sources.py
    patches/
      registry.py
      dispatcher.py
      packs/
        attention/
        kv_cache/
        spec_decode/
        scheduler/
        quantization/
    runtime/
    security/
    observability/
    compat/

  sndr_engine/              # optional private overlay
    __init__.py             # public skeleton only, if tracked
    private/                # ignored / private repo
```

Важно: `sndr_core` не должен импортировать private engine на top-level. Только optional discovery.

## 8. Что реализовано из планов и что забыто

### Реализовано частично

Из внутренних планов уже начато:

- единый `sndr` CLI;
- unified model config schema;
- builtin/community model config registry;
- package/deps config sections;
- bootstrap scopes;
- Docker launch path;
- digest verification;
- Proxmox/K8s config sections;
- GPU tuning schema;
- service schema;
- engine/core split;
- license skeleton.

### Еще не доведено до рабочего состояния

- `sndr` CLI не импортируется из-за `k8s.py`;
- `sndr config new` и registry используют разные директории;
- `deps plan` не покрывает весь `bootstrap.scopes`;
- `install.sh` зависит от broken CLI;
- Proxmox/K8s/service еще не production backends;
- `model artifacts` не стали полноценной частью config-driven flow;
- package sources есть в schema, но не полностью участвуют в planners;
- GPU tuning не применяет все поля schema;
- docs не синхронизированы с новой структурой;
- старые scripts не переведены в wrappers вокруг `sndr`;
- patch metadata неполная;
- CI/release gates не оформлены как строгие блокеры.

## 9. Оценка production readiness

| Область | Состояние | Оценка |
|---|---:|---|
| Python syntax/import | CLI сейчас падает | Не готово |
| Packaging | pyproject есть, но untracked | Не готово |
| Public/private split | идея правильная, оформление неполное | Частично |
| ModelConfig schema | сильная база, много секций | Хорошо, но нужна интеграция |
| Builtin configs | загружаются, registry работает | Хорошо |
| Launcher | Docker path сильный, но preflight неполный | Частично |
| Installer | полезный wizard, но зависит от broken CLI | Частично |
| Deps/bootstrap | хорошая база, scopes неполные | Частично |
| Service/systemd | есть renderer, есть ошибки | Не готово |
| Kubernetes | scaffold + syntax bug | Не готово |
| Proxmox | read-only/render scaffold | Не готово |
| Patch registry | большой объем, metadata неполная | Частично |
| Docs | много stale/contradictions | Не готово |
| Security/license | skeleton без real trust anchor | Не готово |
| CI/release gates | нужны строгие проверки | Не готово |

Итог: проект имеет хорошую техническую базу, но сейчас это alpha/integration-stage, не production release.

## 10. Что нужно сделать в первую очередь

### Этап 0. Стабилизация дерева

1. Исправить `vllm/sndr_core/cli/k8s.py:179`.
2. Сделать lazy import CLI-команд.
3. Добавить `pyproject.toml` и `vllm/sndr_core/**` в git.
4. Решить политику `vllm/sndr_engine`:
   - public skeleton tracked;
   - private code ignored;
   - core optional-import only.
5. Очистить `.pyc`, `__pycache__`, `.DS_Store`.
6. Запустить минимальный gate:

```bash
python3 -m py_compile $(git ls-files '*.py')
python3 -c 'import vllm.sndr_core.cli'
python3 -m pytest -q tests/unit/cli/test_c10_c11_c12.py
```

### Этап 1. Единый config contract

1. Выбрать canonical paths:

```text
~/.sndr/model_configs
~/.sndr/host.yaml
~/.sndr/config.yaml
~/.sndr/generated
~/.sndr/cache
```

2. Исправить `sndr config new`, registry и docs под один путь.
3. Добавить `sndr config doctor`.
4. Добавить `sndr config migrate` из:
   - `~/.genesis`;
   - `~/.sndr/configs`;
   - old scripts.
5. Ввести schema version migration.

### Этап 2. Installer/deps/bootstrap

1. Сделать `sndr install` thin UX поверх:
   - `sndr deps check`;
   - `sndr deps plan`;
   - `sndr bootstrap plan`;
   - `sndr bootstrap apply`.
2. Реализовать `sndr deps install`.
3. Package sources реально использовать в planners.
4. Добавить проверки:
   - Python version;
   - pip/uv;
   - Docker/Podman;
   - NVIDIA driver;
   - NVIDIA container toolkit;
   - CUDA compatibility;
   - vLLM version or image digest;
   - disk space;
   - model path/artifacts;
   - network access;
   - permissions.
5. Для каждого действия сделать dry-run и apply mode.

### Этап 3. Launcher и runtime

1. Перед live launch запускать strict preflight.
2. Поддержать:
   - `--runtime bare`;
   - `--runtime docker`;
   - `--runtime compose`;
   - `--runtime podman`;
   - `--runtime k8s`;
   - `--runtime proxmox`.
3. Добавить:
   - `--preflight-only`;
   - `--prepare`;
   - `--pull`;
   - `--override key=value`;
   - `--strict`;
   - `--explain`.
4. Shell command rendering перевести на `shlex.quote` или list-based subprocess.
5. Docker image запускать по digest, если digest задан.

### Этап 4. Deploy backends

1. `service`:
   - исправить systemd unit;
   - отдельные backends для docker/compose/podman/systemd;
   - tests на render.
2. `k8s`:
   - исправить syntax;
   - render Deployment/Service/ConfigMap/Secret/PVC;
   - namespace handling;
   - GPU/runtime checks;
   - Helm/Kustomize mode.
3. `proxmox`:
   - PVE API mode;
   - LXC/VM/host profiles;
   - IOMMU/VFIO/GPU passthrough checks;
   - NVIDIA runtime checks внутри guest;
   - dry-run diff/apply.

### Этап 5. Patch system

1. Перевести patch dispatch на spec-driven graph.
2. Для каждого patch сделать явный metadata contract.
3. Разделить:
   - community patch pack;
   - experimental patch pack;
   - local private overlay;
   - future engine pack.
4. Добавить:
   - dependency resolver;
   - conflict resolver;
   - capability probes;
   - apply contract tests;
   - rollback/no-rollback declaration.
5. Обновить `docs/PATCHES.md` из registry автоматически.

### Этап 6. Security/release

1. Реальный Ed25519 trust anchor.
2. Подписанные manifests.
3. SBOM.
4. Release provenance.
5. No `curl | bash` as only install path.
6. Secret redaction в report/logs.
7. CI checks:
   - no private paths;
   - no stale `_genesis`;
   - no broken docs commands;
   - no untracked release files;
   - no syntax/import failures.

## 11. Улучшения утилит и автоматизации

### Unified config должен управлять не только vLLM

Нужно расширить config так, чтобы один YAML описывал:

- модель;
- quantization;
- tensor parallel;
- max context;
- KV cache/offload;
- Docker image/tag/digest;
- runtime backend;
- required Python version;
- required vLLM version/commit/image;
- required CUDA/driver range;
- required OS packages;
- required Python packages;
- model artifacts;
- HF/cache paths;
- GPU tuning;
- service/deploy settings;
- observability;
- benchmark profile;
- rollback policy.

### Installer должен стать проверяющей и применяющей системой

Ожидаемый flow:

```text
sndr install --config <model.yaml>
  -> detect host
  -> check OS/GPU/driver/runtime
  -> compare required versions
  -> propose package sources
  -> install missing dependencies
  -> pull vLLM/image/model artifacts
  -> render launch/deploy files
  -> run smoke test
  -> produce report
```

### Community configs

Нужно сделать:

- `sndr config list --community`;
- `sndr config validate`;
- `sndr config submit-template`;
- `sndr config benchmark-report`;
- `sndr config explain <key>`.

Для community configs нужны поля:

- GPU model;
- VRAM;
- driver;
- CUDA;
- vLLM version/image;
- model exact id/revision;
- expected TPS/TTFT/VRAM;
- known caveats;
- author/source;
- last validated date.

## 12. Что сделать с верхними папками выше `vllm/sndr*`

Цель: в публичном репозитории выше `vllm/sndr_core` должно остаться только то, что реально нужно пользователю и release pipeline.

Рекомендация:

- `install.sh` оставить как thin bootstrap;
- `scripts/` сократить до wrappers вокруг `sndr`;
- старые launch/preflight scripts либо перенести в `docs/archive`, либо переписать на `sndr deps/launch`;
- `docs/_internal` оставить для планов, но не смешивать с public docs;
- старые audit/roadmap файлы пометить historical;
- generated reports держать в `docs/_internal/audits/`;
- public docs генерировать/проверять из актуальных CLI-команд.

Не должно быть runtime-зависимости от верхних папок. После установки wheel/package проект должен работать без исходного checkout, кроме явно dev-mode сценариев.

## 13. Рекомендация по core/engine прямо сейчас

С учетом текущей стратегии лучше:

1. Все уже опубликованные патчи и публичные улучшения оставить в `sndr_core`.
2. `sndr_engine` сейчас держать пустым optional overlay.
3. В core оставить:
   - config;
   - launcher;
   - installer;
   - patcher;
   - public patch packs;
   - community configs;
   - diagnostics/reporting;
   - deploy/render helpers.
4. В engine позже переносить только новые приватные разработки:
   - закрытые kernels;
   - коммерческие patch packs;
   - private benchmark/tuning logic;
   - signed licensed modules;
   - private integrations.
5. Не шифровать публичный core: доверие сообщества важнее.
6. Для engine использовать не "обфускацию как безопасность", а:
   - отдельный private repo;
   - signed wheels;
   - license verification;
   - минимальный public API;
   - server-side release control.

## 14. Итоговая оценка качества

Кодовая база стала заметно взрослее по идее: есть движение к package-first, config-first и deploy-aware инструменту. Но качество реализации сейчас неровное:

- сильная часть: schema, registry, Docker launch path, идея core/engine, builtin configs;
- слабая часть: завершенность интеграции, CLI import safety, docs truthfulness, deploy backends, git/release hygiene;
- главный риск: документация и планы опережают фактический код;
- главный приоритет: восстановить базовую исполняемость `sndr`, затем привести все команды к единому config/deps/launch contract.

Проекту сейчас требуется не добавление новых фич в первую очередь, а стабилизация основания. После исправления P0/P1 проблем можно продолжать развитие Proxmox/K8s/community configs/installer automation. До этого любые новые возможности будут усиливать несогласованность.

## 15. Минимальный список задач для следующего спринта

1. Исправить `k8s.py` syntax bug.
2. Сделать lazy imports для CLI modules.
3. Синхронизировать `sndr config new` и registry path.
4. Добавить `pyproject.toml` и `vllm/sndr_core/**` в git.
5. Решить tracking policy для `vllm/sndr_engine`.
6. Исправить `service.py` systemd renderer.
7. Исправить `bootstrap.py` apply policy/scopes.
8. Убрать или переписать stale docs references.
9. Перевести legacy scripts на wrappers вокруг `sndr`.
10. Добавить CI gates:
    - Python syntax;
    - CLI import;
    - docs stale grep;
    - registry metadata;
    - no private runtime defaults;
    - no generated cache in release.
11. Сделать `sndr doctor` как единый пользовательский вход для диагностики.
12. Сделать `sndr report` как единый artifact для issue/bug reports.
13. Сформировать public release checklist.

