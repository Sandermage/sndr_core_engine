# Комплексный аудит и журнал исправлений проекта

Дата: 2026-05-10  
Репозиторий: `genesis-vllm-patches`  
Фокус: синтаксис, структура `sndr_core`, пути, сетевые запросы, entrypoint, Docker/Kubernetes/systemd, согласованность CLI и конфигов.

## Краткий вывод

Проект уже перешел к более правильной модульной форме `vllm/sndr_core`, но до исправлений в текущем проходе в нем оставались реальные runtime-дефекты:

- `sndr k8s` не мог импортироваться из-за синтаксической ошибки Python.
- Docker launch мог silently продолжать запуск даже при падении `python3 -m vllm.sndr_core.apply`.
- `image_digest` валидировался, но не использовался как фактический image ref в Docker/Kubernetes.
- `sndr config new` писал пользовательские YAML в каталог, который registry не читал.
- systemd renderer генерировал некорректный service contract: Docker-style `unless-stopped`, неверный stop command, неправильный install target для user unit.
- В активных скриптах и документации оставались приватные адреса и старые model paths, которые могли закрепить неправильный контракт для пользователей.
- Старые ссылки на `apply_all` оставались в активном P103-тексте, хотя новый entrypoint уже `vllm.sndr_core.apply`.

После исправлений:

- Python AST scan по активным `.py` прошел без синтаксических ошибок.
- Shell syntax для основных скриптов запуска/проверки прошел.
- Целевой pytest по CLI/config/runtime/compat прошел.
- Активные non-archive grep-остатки старых путей теперь только исторические комментарии вида "было удалено", а не runtime defaults.

## Методика проверки

Проверялись:

- все Python-файлы под `vllm/sndr_core`, `scripts`, `tests`, `tools`, `benchmarks` через `ast.parse`;
- shell-скрипты, критичные для запуска: `scripts/fetch_models.sh`, `scripts/launch/preflight_check.sh`, `scripts/probe_max_ctx.sh`, `scripts/validate_integration.sh`;
- CLI entrypoints `python3 -m vllm.sndr_core.cli`;
- конфиг-генерация, Docker command rendering, Kubernetes manifest rendering, bootstrap scopes, service lifecycle;
- старые hardcoded paths/hosts: `/nfs/genesis`, `192.168.1.10`, `Genesis_Project`, `~/.sndr/configs`, `apply_all`;
- публичные docs/examples, чтобы они не закрепляли неправильные пути.

Внешние источники, использованные для сверки решений:

- Python lexical/f-string rules: https://docs.python.org/3/reference/lexical_analysis.html#f-strings
- systemd service restart/ExecStart/Install semantics: https://www.freedesktop.org/software/systemd/man/249/systemd.service.html
- Kubernetes image references and digest form: https://kubernetes.io/docs/concepts/containers/images/
- Kubernetes GPU resource scheduling: https://kubernetes.io/docs/tasks/manage-gpus/scheduling-gpus/
- Python packaging / console scripts / `pyproject.toml`: https://packaging.python.org/en/latest/guides/writing-pyproject-toml/

## Исправления

### 1. P0: `sndr k8s` ломался на SyntaxError

Файл: `vllm/sndr_core/cli/k8s.py`  
Текущие строки: `147-149`, `188-191`

Проблема:

В f-string expression был литерал с backslash/newline. Python это запрещает. Из-за этого импорт `vllm.sndr_core.cli` падал целиком, а вместе с ним ломались все subcommands.

Было:

```python
f"{storage_mounts if storage_mounts else '        []\n'}"
f"{storage_volumes if storage_volumes else '      []\n'}"
```

Стало:

```python
volume_mounts = storage_mounts if storage_mounts else "        []\n"
volumes = storage_volumes if storage_volumes else "      []\n"
...
f"{volume_mounts}"
...
f"{volumes}"
```

Почему так:

Логика осталась прежней, но newline больше не находится внутри f-string expression. Это соответствует Python grammar и устраняет SyntaxError.

Дополнительно исправлено в этом же файле:

- `Service.spec.ports` теперь рендерится валидно для Kubernetes: `port`, `targetPort`, `protocol`, опциональный `nodePort`;
- image для Deployment берется через `_image_ref(cfg)`, где приоритет у `kubernetes.image`, затем у `docker.effective_image_ref()`.

### 2. P0: Docker bootstrap мог скрывать падение apply step

Файл: `vllm/sndr_core/model_configs/schema.py`  
Текущие строки: `2097`, `2131`

Проблема:

Docker launch выполнял:

```bash
python3 -m vllm.sndr_core.apply 2>&1 | tail -5
```

Но внутри `bash -c` стоял только `set -e`. Без `pipefail` shell возвращал статус последней команды pipeline (`tail`), поэтому падение `python3 -m vllm.sndr_core.apply` могло маскироваться как успех.

Было:

```python
bootstrap_parts = ["set -e"]
```

Стало:

```python
bootstrap_parts = ["set -euo pipefail"]
```

Почему так:

Теперь ошибка apply step прерывает контейнерный entrypoint и не превращается в скрытый boot с непримененными патчами.

### 3. P1: `image_digest` валидировался, но не использовался

Файл: `vllm/sndr_core/model_configs/schema.py`  
Текущие строки: `239-241`, `2075`

Проблема:

`DockerConfig.image_digest` проверялся валидатором, но Docker command продолжал запускать mutable tag из `docker.image`. Это ломало смысл pinning: конфиг говорил "запусти digest", а реально запускался tag.

Было:

```python
lines.append(f"  {_shell_quote(d.image)} \\")
```

Стало:

```python
def effective_image_ref(self) -> str:
    """Return the immutable image reference when a digest pin exists."""
    return self.image_digest or self.image

...
lines.append(f"  {_shell_quote(d.effective_image_ref())} \\")
```

Связанные файлы:

- `vllm/sndr_core/cli/k8s.py`, строки `100-105`, теперь Kubernetes renderer тоже использует digest-aware image ref.

Почему так:

Kubernetes и Docker поддерживают форму `repo@sha256:<digest>`. Если digest есть в config, он должен становиться фактическим runtime image reference.

### 4. P1: Shell quoting был недостаточным для путей, env и имен

Файл: `vllm/sndr_core/model_configs/schema.py`  
Текущие строки: `1936-1982`, `2047-2075`, `2187-2189`

Проблема:

Старый renderer собирал shell-команду строками и не защищал значения с пробелами, спецсимволами, кавычками, нестандартными model paths, network names, env values.

Было концептуально:

```python
f"--model {self.model_path}"
f"  --name {d.container_name} \\"
f"  -v {m} \\"
f'  -e {k}="{v}" \\'
```

Стало:

```python
def _shell_quote(value: str) -> str:
    """Quote a value so generated shell commands preserve it exactly."""
    return shlex.quote(str(value))
```

И далее:

```python
f"--model {_shell_quote(self.model_path)}"
f"  --name {_shell_quote(d.container_name)} \\"
f"  -v {_shell_quote(m)} \\"
f"  -e {k}={_shell_quote(v)} \\"
```

Почему так:

Генерируемый launcher должен быть переносимым. Пути вида `/Volumes/Models/Qwen 3.6`, API keys со спецсимволами или mount strings с двоеточиями не должны ломать shell.

### 5. P1: `sndr config new` писал не туда

Файлы:

- `vllm/sndr_core/cli/config.py`, строки `67-80`
- `vllm/sndr_core/model_configs/registry.py`, строки `25-42`

Проблема:

`sndr config new` по умолчанию писал в `~/.sndr/configs/<key>.yaml`, а registry читал `~/.sndr/model_configs/*.yaml`. Пользователь мог создать конфиг, но `sndr launch <key>` его не находил.

Было:

```python
Path.home() / ".sndr" / "configs" / f"{key}.yaml"
```

Стало:

```python
from vllm.sndr_core.paths.sndr_paths import model_configs_user_dir
out_path = model_configs_user_dir() / f"{key}.yaml"
```

Почему так:

Один canonical user-dir должен использоваться и writer'ом, и reader'ом. Registry теперь явно делегирует это `sndr_paths.model_configs_user_dir()`.

### 6. P1: systemd unit renderer был непроизводственным

Файл: `vllm/sndr_core/cli/service.py`  
Текущие строки: `89-123`

Проблемы:

- Docker-style `unless-stopped` попадал в systemd `Restart=`, где это невалидное значение.
- `ExecStop` указывал на `sndr launch <key> --uninstall`, что не является корректной командой остановки.
- User unit получал неправильный install target.
- Команда не quote'ила config key.

Было концептуально:

```ini
After=network-online.target
ExecStart=/usr/bin/env sndr launch <key>
ExecStop=/usr/bin/env sndr launch <key> --uninstall
Restart=unless-stopped
WantedBy=multi-user.target
```

Стало:

```python
_SYSTEMD_RESTART = {
    "no": "no",
    "always": "always",
    "on-failure": "on-failure",
    "unless-stopped": "always",
}
...
ExecStart=/usr/bin/env sndr launch --non-interactive {key_arg}
Restart={restart}
WantedBy={wanted_by}
```

Где `wanted_by`:

- `multi-user.target` для system unit;
- `default.target` для user unit.

Почему так:

systemd сам отправляет SIGTERM/SIGKILL сервисному процессу при stop, если не задан отдельный корректный `ExecStop`. Нельзя подменять stop на uninstall-like команду.

### 7. P1: `bootstrap apply_policy=auto-yes` не исполнялся автоматически

Файл: `vllm/sndr_core/cli/bootstrap.py`  
Текущие строки: `201-223`

Проблема:

Config мог декларировать:

```yaml
bootstrap:
  apply_policy: auto-yes
```

Но CLI все равно вел себя как dry-run, если пользователь не передал `--yes`.

Было:

```python
yes = args.yes
```

Стало:

```python
yes = args.yes
if cfg.bootstrap.apply_policy == "never":
    ...
if cfg.bootstrap.apply_policy == "auto-yes":
    yes = True
if cfg.bootstrap.apply_policy == "ask" and not yes:
    _io.warn("--yes required for apply_policy='ask' (running dry-run)")
```

Почему так:

Поведение теперь соответствует самому config contract.

### 8. P1: `bootstrap plan/apply` скрывал неподдержанные scope

Файл: `vllm/sndr_core/cli/bootstrap.py`  
Текущие строки: `103-110`, `168-172`, `216-221`

Проблема:

Y7 schema уже знает scopes `model-artifacts` и `service`, но deps planner пока не реализует их как реальные PlanItem scopes. До исправления пользователь мог получить "(no items in scope)" и подумать, что все готово.

Стало:

```python
def _unsupported_plan_scopes(s: set[str]) -> set[str]:
    unsupported: set[str] = set()
    if "model-artifacts" in s:
        unsupported.add("model-artifacts")
    if "service" in s:
        unsupported.add("service")
    return unsupported
```

Почему так:

Лучше честный warning о нереализованной части, чем ложный зеленый статус.

### 9. P1: старый `apply_all` оставался в активном P103 описании

Файл: `vllm/sndr_core/integrations/attention/gdn/p103_fla_cliff2_chunked.py`  
Текущие строки: `18`, `399`

Проблема:

Новая структура использует:

```bash
python3 -m vllm.sndr_core.apply
```

Но P103 все еще показывал старый:

```bash
python3 -m vllm.sndr_core.apply_all
```

Стало:

```bash
python3 -m vllm.sndr_core.apply
```

Почему так:

Документация внутри патча должна соответствовать реальному entrypoint. Иначе оператор копирует несуществующую команду и получает false debug path.

### 10. P2: hardcoded `/nfs/genesis/models` убран из активных defaults

Файлы:

- `scripts/fetch_models.sh`, строка `39`
- `scripts/launch/preflight_check.sh`, строки `85-90`
- `docs/BENCHMARK_GUIDE.md`
- `docs/MODEL_CONFIG_LAUNCHER.md`
- `scripts/launch/README.md`
- `vllm/sndr_core/integrations/spec_decode/pn38_dflash_quant_drafter.py`
- `vllm/sndr_core/apply/_per_patch_dispatch.py`
- `vllm/sndr_core/dispatcher/registry.py`

Проблема:

`/nfs/genesis/models` был личным layout path, но встречался в публичных docs и wrapper scripts. Это создает плохой переносимый контракт.

Было:

```bash
DEST_ROOT="${2:-/nfs/genesis/models}"
```

Стало:

```bash
DEST_ROOT="${2:-${SNDR_MODELS_ROOT:-${GENESIS_MODELS_ROOT:-${HOME}/.cache/sndr/models}}}"
```

В preflight стало:

```bash
MODEL_DIR="${SNDR_MODEL_DIR:-${GENESIS_MODEL_DIR:-${SNDR_MODELS_ROOT:-${GENESIS_MODELS_ROOT:-${HOME}/models}}}}"
```

Почему так:

Переносимый проект не должен зависеть от домашней NFS-топологии одного стенда. Для runtime используются env-переменные и user-local defaults.

### 11. P2: hardcoded `192.168.1.10` убран из активных defaults и публичных примеров

Файлы:

- `tests/bench/comprehensive_bench.py`, строки `18-43`, `63-70`
- `tests/soak/pn40_soak_1000.py`, строки `6-22`
- `tests/soak/cliff2_multiturn_soak.py`, строки `52-57`
- `README.md`
- `docs/BENCHMARKS.md`
- `docs/BENCHMARK_GUIDE.md`
- `docs/COMMANDS.md`
- `docs/PATCHES.md`
- `scripts/validate_integration.sh`
- `vllm/sndr_core/cache/response_cache.py`
- `vllm/sndr_core/integrations/middleware/pn65_access_log.py`
- `vllm/sndr_core/apply/_per_patch_dispatch.py`
- `vllm/sndr_core/dispatcher/registry.py`

Проблема:

Приватный адрес стенда попадал в test defaults и публичные examples. Это не только не переносимо, но и опасно: чужой пользователь может запускать tests/bench и случайно стучаться не туда.

Было:

```python
ENDPOINT = os.environ.get("GENESIS_ENDPOINT", "http://192.168.1.10:8000/v1/chat/completions")
SSH_HOST = os.environ.get("GENESIS_SSH_HOST", "sander@192.168.1.10")
```

Стало:

```python
ENDPOINT = os.environ.get(
    "GENESIS_ENDPOINT", "http://127.0.0.1:8000/v1/chat/completions"
)
SSH_HOST = os.environ.get("GENESIS_SSH_HOST", "")
```

Почему так:

Default должен быть безопасным и локальным. Remote host должен задаваться явно через env/config.

### 12. P2: `~/.sndr/configs` заменен на `~/.sndr/model_configs`

Файлы:

- `vllm/sndr_core/cli/config.py`
- `vllm/sndr_core/model_configs/registry.py`

Проблема:

Старый path `~/.sndr/configs` был логически красивым, но несовместимым с registry. Для проекта важнее единый source of truth.

Текущий контракт:

```text
$SNDR_MODEL_CONFIG_DIR
$GENESIS_MODEL_CONFIG_DIR
$SNDR_HOME/model_configs
$GENESIS_HOME/model_configs
~/.sndr/model_configs
~/.genesis/model_configs only as legacy fallback
```

### 13. P2: `scripts/bench_suffix_sweep.py` больше не документирует старый homelab path

Файл: `scripts/bench_suffix_sweep.py`  
Текущие строки: `17-27`

Было:

```text
Outputs: ~/Genesis_Project/vllm_engine/suffix_sweep_<timestamp>/
cd ~/Genesis_Project/vllm_engine
```

Стало:

```text
Outputs: ~/.sndr/profiles/suffix_sweep_<timestamp>/
cd /path/to/genesis-vllm-patches
```

Почему так:

Script output должен соответствовать новой SNDR path policy.

### 14. P2: из активного публичного слоя убраны старые упоминания tooling credits

Файлы:

- `README.md`
- `docs/PATCHES.md`
- `vllm/sndr_core/dispatcher/registry.py`
- `vllm/sndr_core/integrations/scheduler/p58_async_scheduler_placeholder_fix.py`
- `vllm/sndr_core/integrations/attention/turboquant/p78_tolist_capture_guard.py`
- `vllm/sndr_core/integrations/reasoning/pn58_spec_reasoning_boundary.py`
- `vllm/sndr_core/integrations/reasoning/p59_qwen3_reasoning_tool_call_recovery.py`
- `vllm/sndr_core/integrations/attention/gdn/pn30_ds_layout_spec_decode_align.py`

Проблема:

В активном публичном тексте и source-комментариях оставались старые фразы про tooling credits. Для публичного проекта это лишний шум и плохой сигнал качества.

Было:

```text
third-party tooling-credit wording
author tooling wording
tooling-navigation wording
named tool cross-check wording
```

Стало:

```text
third-party cross-audit
Backport of vllm#40962 (OPEN)
Investigation used automated source navigation
independent CLI cross-check
```

Почему так:

Публичные комментарии должны описывать технический факт, автора/репозиторий и проверяемый источник, а не внутренний инструмент работы.

## Проверка путей и запросов

### Что проверено

Команда поиска по активным зонам:

```bash
rg -n "python3 -m vllm\\.sndr_core\\.apply_all|vllm\\.sndr_core\\.patches\\.apply_all|/nfs/genesis|192\\.168\\.1\\.10|Genesis_Project|~/.sndr/configs" \
  README.md docs scripts vllm/sndr_core pyproject.toml install.sh conftest.py \
  -g '!docs/_internal/**' -g '!docs/upstream/**' -g '!docs/reference/**' \
  -g '!scripts/_archive/**' -g '!scripts/launch/_archive/**'
```

Остались только допустимые активные совпадения:

- комментарии вида "старое значение было удалено";
- migration comments;
- тестовые redaction fixtures в `tests/unit`, которые специально проверяют удаление приватного IP из report bundles;
- архивы и historical docs вне runtime path.

### Что еще нужно сделать отдельно

Для полного публичного релиза надо решить policy по historical docs:

- либо держать `docs/upstream`, `docs/reference`, `scripts/_archive`, `scripts/launch/_archive` как архив и исключать из public package;
- либо переписать их под sanitized examples;
- либо добавить `ARCHIVE_DO_NOT_RUN.md` и CI-rule, который запрещает импорт/исполнение архивных скриптов.

Сейчас я не менял архивные скрипты, чтобы не потерять bench history и старые воспроизводимые сценарии.

## Что осталось слабым в проекте

## Дополнение: отдельный аудит patch-layer

Добавлено после дополнительного прохода по `vllm/sndr_core/integrations`, `vllm/sndr_core/dispatcher`, `vllm/sndr_core/apply` и `tests/unit/integrations`.

### Сводка по патчам

Фактическая картина:

```text
patch files under vllm/sndr_core/integrations: 145
actual patch implementation files by filename heuristic: 122
dispatcher.PATCH_REGISTRY entries: 135
registry entries with apply_module: 122/135
registry entries without apply_module: 13
unit test files under tests/unit/integrations: 46 test_*.py
name-based covered patch implementations: 54/122
name-based uncovered patch implementations: 68/122
```

Важно:

Name-based coverage это грубая метрика. Некоторые патчи могут проверяться общими tests, bundle tests или legacy tests. Но как engineering gate она показывает реальную проблему: patch-layer еще не имеет прозрачного 1:1 соответствия `patch file -> registry entry -> direct test`.

### Проверки patch-layer

Команда:

```bash
python3 -m vllm.sndr_core.cli patches doctor
```

Результат:

```text
135 entries, 122/135 have apply_module
Validator: ERROR=0  WARNING=0  INFO=0
apply_module coverage: 122/135 (13 unmapped)
```

Команда:

```bash
python3 -m vllm.sndr_core.apply.shadow --strict
```

Результат:

```text
DIVERGENT
spec_only_unexpected:
  - PN16_V6
  - SPRINT26_CG_DISPATCH_TRACE
legacy_unparseable:
  - 'Sprint 2.6 v2 — CUDA graph dispatch trace wire-in'
```

Вывод:

`patches doctor` проверяет registry metadata и проходит. Но shadow-gate, который сравнивает legacy apply loop и spec-driven registry, падает. Это нужно исправить до release/CI.

### P0/P1 замечания по patch-layer

#### PL-001: `apply.shadow --strict` сейчас красный

Файлы:

- `vllm/sndr_core/apply/shadow.py`
- `vllm/sndr_core/dispatcher/registry.py`
- `vllm/sndr_core/apply/_per_patch_dispatch.py`
- `vllm/sndr_core/integrations/middleware/pn16_v6_streaming_truncator.py`
- `vllm/sndr_core/integrations/observability/sprint26_cudagraph_dispatch_trace.py`

Суть:

`PN16_V6` и `SPRINT26_CG_DISPATCH_TRACE` имеют `apply_module` в registry, но не входят в allow-list `KNOWN_SPEC_ONLY_PATCHES`. Для `SPRINT26_CG_DISPATCH_TRACE` дополнительно legacy name не парсится в patch id:

```text
'Sprint 2.6 v2 — CUDA graph dispatch trace wire-in'
```

Что сделать:

1. Добавить `PN16_V6` и `SPRINT26_CG_DISPATCH_TRACE` в `KNOWN_SPEC_ONLY_PATCHES`, если миграционная политика действительно допускает registry-driven-only патчи.
2. Или добавить им legacy `@register_patch` entries с парсируемыми именами.
3. Для Sprint26 лучше переименовать legacy registration так, чтобы patch id извлекался стабильно, например:

```python
@register_patch("SPRINT26_CG_DISPATCH_TRACE CUDA graph dispatch trace wire-in")
```

Почему важно:

Пока это не исправлено, strict shadow gate не может быть CI-blocker'ом. Это ослабляет контроль миграции с legacy apply loop на spec-driven registry.

#### PL-002: `PN95` обозначен как partial, но технически очень широкий

Файлы:

- `vllm/sndr_core/dispatcher/registry.py`
- `vllm/sndr_core/integrations/kv_cache/pn95_tier_aware_cache.py`
- `vllm/sndr_core/cache/_pn95_runtime.py`

Суть:

Registry честно помечает:

```text
implementation_status: partial
```

При этом файл PN95 содержит много anchors: admit, touch, KV manager init, register_kv_caches, scheduler tick, blockpool register, demote-on-evict, promote-on-miss, boot-check expansion, block metadata, virtual block materialization.

Риск:

Частичная реализация в KV cache layer опаснее обычного opt-in patch: она касается memory manager, eviction, Mamba SSM exclusion и virtual blocks. Ошибка здесь может проявиться только на long-context/live GPU workload.

Что сделать:

1. Запретить включение PN95 в production presets, пока статус `partial`.
2. Добавить direct tests для каждого anchor group:
   - anchor present;
   - replacement syntax;
   - idempotency;
   - env-disabled no-op;
   - `exclude_mamba_ssm=True` guard;
   - virtual block materialization disabled by default.
3. Добавить live soak на hybrid-GDN с PN95 disabled/enabled:
   - 50K/100K context;
   - multimodal prompt if applicable;
   - prefix-cache on/off;
   - Mamba state integrity check.
4. До реального GPU↔CPU movement не рекламировать PN95 как offload solution; в docs писать “instrumentation/readiness layer”.

#### PL-003: `PN64` является placeholder

Файл:

- `vllm/sndr_core/dispatcher/registry.py`

Суть:

`PN64` имеет:

```text
implementation_status: placeholder
title: Marlin MoE per-SM tuning placeholder for SM 12.0
```

Риск:

Патч виден в registry как patch id и env flag, но реального эмпирического sm_120 tuning нет. Это может запутать владельцев RTX 5090/Blackwell: включат флаг и будут ожидать производственного эффекта.

Что сделать:

1. Оставить default-off.
2. В `sndr patches list`/`explain` явно подсвечивать `placeholder` красным/предупреждением.
3. Не включать в model configs.
4. Перевести в `docs/_internal/backlog` до появления реального sweep:
   - shape matrix;
   - tokens/s;
   - correctness;
   - memory;
   - comparison Hopper-copy vs measured Blackwell values.

#### PL-004: 128/135 registry entries не имеют explicit `implementation_status`

Файл:

- `vllm/sndr_core/dispatcher/registry.py`

Суть:

Счетчик:

```text
implementation_status:
  <unset>: 128
  full: 4
  partial: 1
  placeholder: 1
  retired: 1
```

Риск:

Проект уже ввел поле `implementation_status`, но почти весь registry его не заполняет. Значит CLI/production policy не может надежно отличать:

- production-safe full patch;
- research patch;
- marker-only;
- retired;
- placeholder;
- partial.

Что сделать:

1. Обязать explicit `implementation_status` для всех registry entries.
2. Добавить CI rule: unset статус = warning сейчас, error перед release.
3. Для production presets запретить `partial`, `placeholder`, `marker_only`, `research`, `retired`.

### Неполные / исследовательские / retired entries

По registry:

| Patch | Статус | Lifecycle | Что делать |
|---|---|---|---|
| `PN95` | `partial` | `experimental` | Не включать в prod; довести до live memory movement или оставить как instrumentation. |
| `PN64` | `placeholder` | `experimental` | Держать в backlog до реального sm_120 sweep. |
| `P82` | inferred research | `research` | Оставить research-only; не включать по умолчанию. |
| `P83` | inferred research | `research` | Оставить как disproven/downstream symptom artifact; не включать в prod. |
| `PN26b` | inferred research | `research` | Нужны benchmark + correctness gates перед продвижением. |
| `P61` | inferred retired | `retired` | Оставить как historical alias или удалить после migration window. |
| `P63` | inferred retired | `retired` | Не включать; гипотеза disproven. |
| `P8` | inferred retired | `retired` | Удалить из активных presets. |
| `PN13` | inferred retired | `retired` | Оставить только как historical note. |
| `PN78` | `retired` | `retired` | Не должен попадать в configs. |

### Direct-test coverage gaps

Ниже список patch implementation files, для которых прямой `tests/unit/integrations/**/test_<patch_id>*.py` не найден простым name-based анализом. Это не приговор, но это хороший backlog для доведения качества.

#### Attention / Flash

- `P100`: `vllm/sndr_core/integrations/attention/flash/p100_flashinfer_full_cg_specdec.py`

#### Attention / GDN

- `P28`: `vllm/sndr_core/integrations/attention/gdn/p28_gdn_core_attn.py`
- `P39A`: `vllm/sndr_core/integrations/attention/gdn/p39a_fla_kkt_buffer.py`
- `P46`: `vllm/sndr_core/integrations/attention/gdn/p46_gdn_gating_buffers.py`
- `P60`: `vllm/sndr_core/integrations/attention/gdn/p60_gdn_ngram_state_recovery.py`
- `P60B`: `vllm/sndr_core/integrations/attention/gdn/p60b_gdn_ngram_triton_kernel.py`
- `P63`: `vllm/sndr_core/integrations/attention/gdn/p63_mtp_gdn_state_recovery.py`
- `P7B`: `vllm/sndr_core/integrations/attention/gdn/p7b_gdn_dual_stream_customop.py`
- `PN11`: `vllm/sndr_core/integrations/attention/gdn/pn11_gdn_a_b_contiguous.py`
- `PN29`: `vllm/sndr_core/integrations/attention/gdn/pn29_gdn_chunk_o_scale_fold.py`
- `PN30`: `vllm/sndr_core/integrations/attention/gdn/pn30_ds_layout_spec_decode_align.py`
- `PN32`: `vllm/sndr_core/integrations/attention/gdn/pn32_gdn_chunked_prefill.py`

#### Attention / TurboQuant

- `P101`: `vllm/sndr_core/integrations/attention/turboquant/p101_tq_continuation_slicing.py`
- `P22`: `vllm/sndr_core/integrations/attention/turboquant/p22_tq_prealloc.py`
- `P26`: `vllm/sndr_core/integrations/attention/turboquant/p26_prefill_output.py`
- `P40`: `vllm/sndr_core/integrations/attention/turboquant/p40_tq_grouped_decode.py`
- `P44`: `vllm/sndr_core/integrations/attention/turboquant/p44_tq_mixed_attn_out.py`
- `P65`: `vllm/sndr_core/integrations/attention/turboquant/p65_turboquant_spec_cg_downgrade.py`
- `P67B`: `vllm/sndr_core/integrations/attention/turboquant/p67b_spec_verify_routing.py`
- `P78`: `vllm/sndr_core/integrations/attention/turboquant/p78_tolist_capture_guard.py`
- `P98`: `vllm/sndr_core/integrations/attention/turboquant/p98_tq_workspace_revert.py`
- `P99`: `vllm/sndr_core/integrations/attention/turboquant/p99_workspace_manager_memoize.py`
- `PN31`: `vllm/sndr_core/integrations/attention/turboquant/pn31_fa_varlen_persistent_out.py`
- `PN34`: `vllm/sndr_core/integrations/attention/turboquant/pn34_workspace_lock_runtime_relax.py`

#### Compile Safety / Kernels / Memory

- `P66`: `vllm/sndr_core/integrations/compile_safety/p66_cudagraph_size_divisibility_filter.py`
- `PN13`: `vllm/sndr_core/integrations/compile_safety/pn13_cuda_graph_lambda_arity.py`
- `P36`: `vllm/sndr_core/integrations/kernels/p36_tq_shared_decode_buffers.py`
- `PN12`: `vllm/sndr_core/integrations/kernels/pn12_ffn_intermediate_pool.py`
- `PN28`: `vllm/sndr_core/integrations/kernels/pn28_merge_attn_states_nan_guard.py`
- `P5B`: `vllm/sndr_core/integrations/memory/p5b_page_size_pad_smaller.py`
- `PN78`: `vllm/sndr_core/integrations/memory/pn78_post_warmup_cache_release.py`

#### KV Cache

- `P14`: `vllm/sndr_core/integrations/kv_cache/p14_block_table.py`
- `P83`: `vllm/sndr_core/integrations/kv_cache/p83_mtp_keep_last_cached_block.py`
- `P85`: `vllm/sndr_core/integrations/kv_cache/p85_hybrid_fine_shadow_prefix_cache.py`
- `PN95`: `vllm/sndr_core/integrations/kv_cache/pn95_tier_aware_cache.py`

#### MoE / Quantization

- `P24`: `vllm/sndr_core/integrations/moe/p24_moe_tune.py`
- `P31`: `vllm/sndr_core/integrations/moe/p31_router_softmax.py`
- `P37`: `vllm/sndr_core/integrations/moe/p37_moe_intermediate_cache.py`
- `PN27`: `vllm/sndr_core/integrations/moe/pn27_revert_pluggable_moe.py`
- `P81`: `vllm/sndr_core/integrations/quantization/p81_fp8_block_scaled_m_le_8.py`
- `P91`: `vllm/sndr_core/integrations/quantization/p91_autoround_row_group_cdiv.py`
- `PN77`: `vllm/sndr_core/integrations/quantization/pn77_fp8_lm_head.py`

#### Reasoning / Scheduler / Serving

- `P27`: `vllm/sndr_core/integrations/reasoning/p27_reasoning_before_think.py`
- `P61B`: `vllm/sndr_core/integrations/reasoning/p61b_qwen3_streaming_overlap_guard.py`
- `P34`: `vllm/sndr_core/integrations/scheduler/p34_mamba_deadlock_guard.py`
- `P4`: `vllm/sndr_core/integrations/scheduler/p4_tq_hybrid.py`
- `P74`: `vllm/sndr_core/integrations/scheduler/p74_chunk_clamp.py`
- `P79C`: `vllm/sndr_core/integrations/scheduler/p79c_stale_spec_token_cleanup.py`
- `P79D`: `vllm/sndr_core/integrations/scheduler/p79d_preempt_async_discard.py`
- `P84`: `vllm/sndr_core/integrations/scheduler/p84_hash_block_size_override.py`
- `P62`: `vllm/sndr_core/integrations/serving/p62_structured_output_spec_decode_timing.py`
- `P68`: `vllm/sndr_core/integrations/serving/p68_69_long_ctx_tool_adherence.py`

#### Spec Decode / DFlash / Tool Parsing / Worker

- `P70`: `vllm/sndr_core/integrations/spec_decode/p70_auto_strict_ngram.py`
- `P75`: `vllm/sndr_core/integrations/spec_decode/p75_suffix_decoding_enable.py`
- `P86`: `vllm/sndr_core/integrations/spec_decode/p86_ngram_batch_propose_linear.py`
- `PN21`: `vllm/sndr_core/integrations/spec_decode/pn21_dflash_swa_support.py`
- `PN22`: `vllm/sndr_core/integrations/spec_decode/pn22_local_argmax_tp.py`
- `PN23`: `vllm/sndr_core/integrations/spec_decode/pn23_dflash_combine_hidden_dtype.py`
- `PN38`: `vllm/sndr_core/integrations/spec_decode/pn38_dflash_quant_drafter.py`
- `PN40`: `vllm/sndr_core/integrations/spec_decode/pn40_dflash_omnibus.py`
- `PN40`: `vllm/sndr_core/integrations/spec_decode/pn40_workload_classifier_hook.py`
- `P64`: `vllm/sndr_core/integrations/tool_parsing/p64_qwen3coder_mtp_streaming.py`
- `P72`: `vllm/sndr_core/integrations/worker/p72_profile_run_cap.py`
- `P79B`: `vllm/sndr_core/integrations/worker/p79b_async_proposer_sync.py`
- `PN24`: `vllm/sndr_core/integrations/worker/pn24_dflash_aux_layer_indexing.py`
- `PN33`: `vllm/sndr_core/integrations/worker/pn33_spec_decode_warmup_k.py`
- `PN35`: `vllm/sndr_core/integrations/worker/pn35_inputs_embeds_optional.py`

### Особенно важные patch clusters для следующего прохода

#### DFlash cluster

Файлы:

- `pn21_dflash_swa_support.py`
- `pn22_local_argmax_tp.py`
- `pn23_dflash_combine_hidden_dtype.py`
- `pn24_dflash_aux_layer_indexing.py`
- `pn38_dflash_quant_drafter.py`
- `pn40_dflash_omnibus.py`

Почему важно:

Это отдельная технологическая линия. Сейчас прямых canonical tests по большинству этих файлов нет. Для DFlash нужен минимум:

- anchor tests;
- registry tests;
- compose/conflict tests между PN21/PN23/PN24/PN38/PN40;
- dry-run apply on pristine qwen3_dflash fixture;
- live boot test на DFlash profile.

#### TurboQuant core cluster

Файлы:

- `p22_tq_prealloc.py`
- `p26_prefill_output.py`
- `p40_tq_grouped_decode.py`
- `p44_tq_mixed_attn_out.py`
- `p65_turboquant_spec_cg_downgrade.py`
- `p67b_spec_verify_routing.py`
- `p78_tolist_capture_guard.py`
- `p98_tq_workspace_revert.py`
- `p99_workspace_manager_memoize.py`
- `p101_tq_continuation_slicing.py`

Почему важно:

Это центральная ценность проекта для A5000/3090/4090-class setups. Часть покрыта indirect tests, но не хватает прямого 1:1 patch test map и live A/B на:

- TQ on/off;
- MTP on/off;
- cudagraph modes;
- long-context prefill;
- continuation/decode path;
- prefix-cache interactions.

#### GDN / Streaming-GDN cluster

Файлы:

- `p28_gdn_core_attn.py`
- `p39a_fla_kkt_buffer.py`
- `p46_gdn_gating_buffers.py`
- `p60_gdn_ngram_state_recovery.py`
- `p60b_gdn_ngram_triton_kernel.py`
- `p63_mtp_gdn_state_recovery.py`
- `pn29_gdn_chunk_o_scale_fold.py`
- `pn30_ds_layout_spec_decode_align.py`
- `pn32_gdn_chunked_prefill.py`
- `pn59_streaming_gdn.py`
- `pn79_inplace_ssm_state.py`

Почему важно:

GDN линия самая чувствительная к memory layout и shape drift. Уже есть хорошие tests для PN59/PN79/P103/PN50/PN54, но старшие foundational patches не все закрыты direct tests. Нужен отдельный `gdn_composability_matrix` как CI target.

### Что добавить в CI

1. `python3 -m vllm.sndr_core.apply.shadow --strict` как обязательный gate после исправления PL-001.
2. `python3 -m vllm.sndr_core.cli patches doctor` как быстрый metadata gate.
3. Test coverage gate:

```text
Every patch with apply_module and implementation_status in {full, partial}
must have either:
  - direct tests/unit/integrations/**/test_<patch_id>*.py
  - or explicit registry field test_coverage: indirect/manual/research
```

4. Production preset gate:

```text
No production config may enable implementation_status in:
  partial, placeholder, marker_only, research, retired
```

5. Live optional gate for GPU runner:

```text
SNDR_LIVE_VLLM_ROOT=<path> pytest tests/unit/integrations -m live_apply
```

### Patch-layer test result

Команда:

```bash
python3 -m pytest -q tests/unit/integrations
```

Результат:

```text
663 passed, 10 skipped in 2.62s
```

Skips:

- нет локального `vllm install root` для live apply checks;
- нет некоторых committed pristine fixtures;
- CUDA/GPU-specific checks не активируются на текущем host context.

Вывод:

Patch-layer не “пустой”: тестов много и они проходят. Но качество еще не production-complete, потому что:

- coverage не 1:1;
- shadow strict красный;
- implementation_status почти везде unset;
- часть важных технологических clusters не имеет прямых canonical tests;
- live apply на реальном vLLM tree/GPU не проверялся в этом проходе.

### 1. `vllm/sndr_core` и `pyproject.toml` сейчас untracked

`git status` показывает `?? vllm/sndr_core/` и `?? pyproject.toml`. Это критично для release hygiene: пока директория не добавлена в git, diff/review не показывает изменения нормально.

Рекомендация:

```bash
git add pyproject.toml vllm/sndr_core tests/unit docs/_internal/PROJECT_FIX_AUDIT_2026-05-10_RU.md
```

Перед commit обязательно проверить, что в staged нет случайных cache/generated files.

### 2. Engine/Core split еще не закрыт организационно

Текущая логика правильная по направлению:

- `sndr_core` должен быть публичным, самодостаточным, без hard dependency на private engine;
- `sndr_engine` должен быть пустым/отдельным private layer;
- core может знать, что engine существует, но не должен падать без него.

Что нужно доделать:

- ввести явный `engine_loader` с контрактом `optional import`;
- сделать `sndr doctor engine` с понятным статусом: `not installed`, `installed`, `version mismatch`;
- запретить core imports из engine через CI-rule;
- все приватные патчи переносить только в private package/registry, а public registry оставлять стабильным.

### 3. Kubernetes CLI пока renderer, не production operator

Исправлены синтаксис, image ref и Service YAML, но это еще не полноценный Kubernetes deployment layer.

Нужно:

- добавить тест snapshot manifests;
- поддержать PVC вместо `hostPath` для generic clusters;
- добавить secrets для API keys вместо ConfigMap;
- добавить namespace creation;
- добавить probes с configurable path/timeouts;
- добавить `imagePullSecrets`;
- добавить GPU runtime class discovery;
- добавить dry-run server validation: `kubectl apply --dry-run=server -f -`.

### 4. Bootstrap пока не закрывает artifacts/service

Сейчас это честно подсвечивается warning'ом, но функционал не реализован.

Нужно:

- `model-artifacts`: pull/checksum/required_files/min_total_gib/HF revision pin;
- `service`: systemd/docker compose/k8s/proxmox lifecycle integration;
- rollback для partial installs;
- machine-readable plan output с exact commands и risk level.

### 5. Proxmox support пока schema-level

В `ProxmoxConfig` уже есть полезная модель, но нет полноценной интеграции:

- нет PVE API client;
- нет detection LXC/VM/host capabilities;
- нет GPU passthrough verification;
- нет renderer для LXC/VM setup;
- нет safe install inside guest.

Рекомендация:

Сделать `sndr proxmox doctor` первым этапом, без destructive apply:

```text
host -> pve version/kernel/iommu/nvidia
vm/lxc -> nvidia-smi/cuda/docker/python/vllm
network -> endpoint reachability
storage -> model dir/cache mounts
```

### 6. Security posture требует отдельного hardening pass

Исправлено:

- shell quoting;
- digest-aware image ref;
- local defaults вместо private remote defaults.

Осталось:

- вынести API keys из ConfigMap в Secret для Kubernetes;
- добавить strict allowlist env vars для generated launch scripts;
- добавить secret redaction к каждому report/log bundle;
- включить SBOM generation в release workflow;
- добавить `pip install --require-hashes` для production install path;
- запретить `curl|bash`, если config явно не разрешил third-party source.

## Проверки

Выполнено:

```bash
python3 - <<'PY'
import ast, pathlib, sys
roots = ['vllm/sndr_core', 'scripts', 'tests', 'tools', 'benchmarks']
...
PY
```

Результат:

```text
PY_AST_CHECK count=646 errors=0
```

Shell syntax:

```bash
bash -n scripts/fetch_models.sh
bash -n scripts/launch/preflight_check.sh
bash -n scripts/probe_max_ctx.sh
bash -n scripts/validate_integration.sh
```

Результат: без ошибок.

Целевой pytest:

```bash
python3 -m pytest -q \
  tests/unit/cli/test_c10_c11_c12.py \
  tests/unit/cli/test_phase6_clis.py \
  tests/unit/model_configs/test_image_digest.py \
  tests/unit/runtime/test_redact.py \
  tests/unit/compat/test_recipes.py
```

Финальный результат:

```text
116 passed in 1.93s
```

Дополнительный post-cleanup pytest после удаления старых tooling-credit строк:

```bash
python3 -m pytest -q \
  tests/unit/model_configs \
  tests/unit/cli \
  tests/unit/runtime/test_redact.py \
  tests/unit/compat/test_recipes.py
```

Финальный результат:

```text
377 passed in 5.51s
```

Расширенный pytest после финальных правок:

```bash
python3 -m pytest -q \
  tests/unit/model_configs \
  tests/unit/deps \
  tests/unit/cli \
  tests/unit/runtime/test_redact.py \
  tests/unit/test_kv_calc.py \
  tests/unit/compat/test_recipes.py \
  tests/unit/compat/test_models_registry.py \
  tests/unit/compat/test_image_allowlist.py
```

Финальный результат:

```text
474 passed in 8.57s
```

## Итоговая оценка качества

Текущее состояние после исправлений:

- для local CLI/config layer: ближе к production-ready;
- для Docker launcher: существенно надежнее, но требует image build/install contract;
- для Kubernetes/Proxmox/bootstrap: хороший каркас, но не полноценный production backend;
- для документации: публичный слой стал чище, но архивы требуют policy;
- для core/engine split: архитектурное направление верное, но enforcement через CI еще нужен.

Главный следующий шаг:

Сделать release gate, который не позволит повторно внести старые path/request ошибки:

```bash
rg -n "192\\.168\\.1\\.10|/nfs/genesis|Genesis_Project|apply_all|~/.sndr/configs" \
  README.md docs scripts vllm/sndr_core \
  -g '!docs/_internal/**' -g '!docs/upstream/**' \
  -g '!docs/reference/**' -g '!scripts/_archive/**' \
  -g '!scripts/launch/_archive/**'
```

И добавить это как CI job `portable-paths`.
