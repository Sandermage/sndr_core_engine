# Глубокий аудит состояния проекта SNDR / Genesis vLLM patches

Дата аудита: 2026-05-12  
Рабочая директория: `/Users/sander/Documents/Visual Studio Code/genesis-vllm-patches`  
Режим работы: анализ и отчет. Код проекта не изменялся.

## 1. Короткий вывод

Проект находится в состоянии сильной бета-версии / pre-production. Архитектурно переход на `vllm/sndr_core` сделан в правильном направлении: код стал модульнее, patch-layer получил registry/spec/shadow validation, CLI расширен, модельные конфиги стали центральной точкой запуска. Но выпускать это как production-ready сейчас рано.

Главная причина: полный тестовый прогон не зеленый.

Фактический результат:

```text
python3 -m pytest -q
11 failed, 4726 passed, 97 skipped in 60.45s
```

Ошибки не случайные: они указывают на реальные runtime-классы проблем:

- P7b ломает torch-less импорт patch module.
- PN26 при выключенном env все равно импортирует torch-зависимый kernel.
- `sndr self-test` падает на wiring imports.
- Есть статические `F821/F822` дефекты, которые могут стать `NameError` в редких ветках.
- Один builtin config (`a5000-2x-tier-aware-example`) не проходит собственную валидацию.

Оценка готовности:

| Направление | Состояние | Оценка |
|---|---:|---:|
| Архитектура `sndr_core` | Хорошая база, но есть legacy/doc drift | 7/10 |
| Patch registry / shadow gate | Хорошо, strict shadow clean | 8/10 |
| Unit/legacy тесты | Большой объем, но full suite красный | 6/10 |
| Production launch | Есть, но требует live GPU/container validation | 5/10 |
| Installer/bootstrap/deps | Частично реализовано | 5/10 |
| K8s/Proxmox/service | CLI есть, но в основном scaffold/renderer | 4/10 |
| Security/release hygiene | Нужен отдельный hardening pass | 4/10 |

Текущий production verdict: **не выпускать как production-ready**, пока не закрыты P0/P1 ниже.

## 2. Что проверено

Структура и объем:

```text
rg --files                 -> 933 files
*.py                       -> 705
*.md                       -> 71
*.yaml / *.yml             -> 17
*.sh                       -> 62
vllm/sndr_core/integrations -> 145 py files
vllm/sndr_core/kernels      -> 31 py files
vllm/sndr_engine            -> skeleton only
```

Синтаксис:

```text
PY_AST_CHECK files=692 errors=0
JSON_CHECK files=62 errors=0
BASH_N_CHECK files=62 errors=0
```

Patch-layer:

```text
sndr patches doctor:
135 entries, 122/135 have apply_module
Validator: ERROR=0 WARNING=0 INFO=0

python3 -m vllm.sndr_core.apply.shadow --strict:
Legacy apply registrations: 132
Spec-driven entries:        135
Specs with apply_module:    122
Specs without apply_module:  13
CLEAN - no unexpected divergence
```

Registry snapshot:

```text
registry_entries: 135
tier: community=135, engine=0
lifecycle:
  experimental=85
  legacy=33
  retired=11
  research=3
  stable=2
  coordinator=1
implementation_status:
  live=115
  full=4
  partial=1
  placeholder=1
  retired=11
  research=3
```

Важно: `sndr_engine` сейчас правильно оставлен пустым skeleton:

- [vllm/sndr_engine/__init__.py](../../vllm/sndr_engine/__init__.py:45) - `engine_available()` возвращает `False`, если нет private overlay.
- [vllm/sndr_engine/LICENSE-NOTICE](../../vllm/sndr_engine/LICENSE-NOTICE:12) - явно сказано: "No patches, no kernels, no algorithms."

## 3. Главные production blockers

### P0-1. P7b ломает torch-less import safety

Файлы:

- [vllm/sndr_core/integrations/attention/gdn/p7b_gdn_dual_stream_customop.py](../../vllm/sndr_core/integrations/attention/gdn/p7b_gdn_dual_stream_customop.py:54)
- [vllm/sndr_core/kernels/gdn_dual_stream_customop.py](../../vllm/sndr_core/kernels/gdn_dual_stream_customop.py:45)

Суть:

```python
from vllm.sndr_core.kernels.gdn_dual_stream_customop import is_p7b_enabled
```

Этот импорт тянет kernel module, а там на верхнем уровне:

```python
import torch
```

На машине без torch это ломает импорт wiring module. Поэтому падают:

- `sndr self-test`
- `tests/unit/compat/test_self_test.py`
- `tests/unit/integrations/attention/gdn/test_attention_gdn_family_contract.py`
- `tests/unit/test_patch_apply_contracts.py`

Фактическая ошибка:

```text
ModuleNotFoundError: No module named 'torch'
vllm.sndr_core.integrations.attention.gdn.p7b_gdn_dual_stream_customop
```

Как исправить:

1. В `p7b_gdn_dual_stream_customop.py` не импортировать kernel module на верхнем уровне.
2. Локально проверять env через `os.environ.get("GENESIS_ENABLE_P7B")`.
3. Kernel импортировать только внутри `apply()` после env/platform gate.
4. В `kernels/gdn_dual_stream_customop.py` либо перенести `import torch` внутрь функций регистрации, либо сделать optional import:

```python
try:
    import torch
except ImportError:
    torch = None
```

5. Если torch отсутствует, `apply()` должен вернуть `("skipped", "...torch not installed...")`, а не падать.

Критерий приемки:

```text
python3 -m vllm.sndr_core.cli self-test --json
python3 -m pytest -q tests/unit/test_patch_apply_contracts.py tests/unit/compat/test_self_test.py tests/unit/integrations/attention/gdn
```

Ожидаемо: 0 fail.

### P0-2. PN26 при выключенном env импортирует torch kernel и падает

Файлы:

- [vllm/sndr_core/integrations/attention/turboquant/pn26_sparse_v_kernel.py](../../vllm/sndr_core/integrations/attention/turboquant/pn26_sparse_v_kernel.py:118)
- [vllm/sndr_core/kernels/triton_turboquant_decode_sparse_v.py](../../vllm/sndr_core/kernels/triton_turboquant_decode_sparse_v.py:190)

Суть:

В `apply()` импортируется kernel до проверки `GENESIS_ENABLE_PN26_SPARSE_V`.

```python
from vllm.sndr_core.kernels.triton_turboquant_decode_sparse_v import (
    should_apply,
    is_pn26_sparse_v_enabled,
)
```

А kernel на верхнем уровне делает:

```python
import torch
```

Тестовый контракт требует: если env disabled, `apply()` не должен падать и обязан вернуть tuple.

Фактическая ошибка:

```text
PN26: apply() raised ModuleNotFoundError: No module named 'torch'
```

Как исправить:

1. В начале `apply()` проверять env локально через `os.environ`.
2. Если env выключен, сразу вернуть:

```python
return "skipped", "opt-in: set GENESIS_ENABLE_PN26_SPARSE_V=1 ..."
```

3. Импортировать kernel только после этой проверки.
4. Обернуть kernel import в `try/except ImportError` и возвращать `skipped` или `failed` с понятной причиной.

Критерий приемки:

```text
python3 -m pytest -q tests/unit/test_patch_apply_contracts.py -k PN26
```

### P0-3. `sndr self-test` сейчас красный

Файл:

- [tests/unit/compat/test_self_test.py](../../tests/unit/compat/test_self_test.py:77)

Фактический результат:

```json
{
  "name": "wiring imports",
  "status": "fail",
  "message": "1/121 wiring modules broken: p7b_gdn_dual_stream_customop: ModuleNotFoundError: No module named 'torch'"
}
```

Это следствие P7b, но для production это самостоятельный blocker: операторская команда self-test не может быть красной в shipping repo.

Как исправить:

- Закрыть P0-1.
- После этого сделать `sndr self-test` обязательным CI gate.

### P0-4. Undefined names в apply/verify path

Файлы:

- [vllm/sndr_core/apply/orchestrator.py](../../vllm/sndr_core/apply/orchestrator.py:886)
- [vllm/sndr_core/apply/verify.py](../../vllm/sndr_core/apply/verify.py:51)

Проблемы:

```python
results = verify_live_rebinds()
```

`verify_live_rebinds` не импортирован в `orchestrator.py`.

```python
_resolve_wiring_module(wiring_module)
```

`_resolve_wiring_module` не определен и не импортирован в `verify.py`.

Также `verify.py` продолжает проверять legacy имена:

```python
patch_22_tq_prealloc
patch_31_router_softmax
patch_14_block_table
patch_28_gdn_core_attn
patch_38_tq_continuation_memory
patch_39_fla_kkt_buffer
```

После удаления `_genesis` это выглядит как недомигрированный verifier.

Как исправить:

1. В `orchestrator.py` импортировать:

```python
from vllm.sndr_core.apply.verify import verify_live_rebinds
```

лучше внутри `if verify:`, чтобы не увеличивать cold import.

2. В `verify.py` заменить legacy resolver на canonical `PatchSpec.apply_module` / registry mapping.
3. Переписать список проверок с legacy names на реальные модули `vllm.sndr_core.integrations.*`.
4. Добавить тест:

```text
python3 -m vllm.sndr_core.apply --verify-rebinds --dry-run
```

### P0-5. `a5000-2x-tier-aware-example` не проходит собственную валидацию

Файл:

- [vllm/sndr_core/model_configs/builtin/a5000-2x-tier-aware-EXAMPLE.yaml](../../vllm/sndr_core/model_configs/builtin/a5000-2x-tier-aware-EXAMPLE.yaml:56)

Команда:

```text
python3 -m vllm.sndr_core.cli model-config validate a5000-2x-tier-aware-example
```

Фактический результат:

```text
ERROR [R-011] genesis_env keys must exist in PATCH_REGISTRY
unknown keys:
  GENESIS_PN95_CONFIG_KEY
  GENESIS_PN95_TICK_EVERY
  GENESIS_PN95_DEMOTE_FREE_MIB_THRESHOLD
```

При этом эти переменные реально используются runtime:

- [vllm/sndr_core/cache/_pn95_runtime.py](../../vllm/sndr_core/cache/_pn95_runtime.py:965)
- [vllm/sndr_core/cache/_pn95_runtime.py](../../vllm/sndr_core/cache/_pn95_runtime.py:1257)
- [vllm/sndr_core/cache/_pn95_runtime.py](../../vllm/sndr_core/cache/_pn95_runtime.py:1258)

Корень проблемы:

R-011 разрешает часть tunable prefixes, но не разрешает `GENESIS_PN95_`.

Файл:

- [vllm/sndr_core/model_configs/audit_rules.py](../../vllm/sndr_core/model_configs/audit_rules.py:622)

Как исправить:

Добавить в `tunable_prefixes`:

```python
"GENESIS_PN95_",
```

или лучше разделить `genesis_env` на два класса:

- patch enable flags: должны быть в `PATCH_REGISTRY.env_flag`;
- runtime knobs: должны быть в отдельном allowlist registry.

Сейчас это production blocker для Path C / PN95 preset.

### P0-6. Статические undefined-name дефекты

Команда:

```text
python3 -m ruff check vllm/sndr_core vllm/sndr_engine tests/unit --select F,E9
```

Нашла 289 замечаний. Большинство - style/noise, но ниже реальные runtime/static defects:

| Файл | Строка | Проблема | Риск |
|---|---:|---|---|
| [vllm/sndr_core/apply/orchestrator.py](../../vllm/sndr_core/apply/orchestrator.py:886) | 886 | `verify_live_rebinds` undefined | `--verify-rebinds` упадет |
| [vllm/sndr_core/apply/verify.py](../../vllm/sndr_core/apply/verify.py:51) | 51 | `_resolve_wiring_module` undefined | verifier упадет |
| [vllm/sndr_core/cache/tier_manager.py](../../vllm/sndr_core/cache/tier_manager.py:151) | 151, 193 | `Any` не импортирован | static gate fail, future annotation risk |
| [vllm/sndr_core/cli/_io.py](../../vllm/sndr_core/cli/_io.py:56) | 56 | `NoReturn` не импортирован | static gate fail |
| [vllm/sndr_core/integrations/spec_decode/pn40_dflash_omnibus.py](../../vllm/sndr_core/integrations/spec_decode/pn40_dflash_omnibus.py:383) | 383 | `patch_N40_workload_classifier_hook` undefined | PN40 apply path может не применить sub-D |
| [vllm/sndr_core/core/text_patch.py](../../vllm/sndr_core/core/text_patch.py:591) | 591-600 | `__all__` содержит lazy attrs, которые ruff считает undefined | CI/static gate fail |
| [vllm/sndr_core/integrations/upstream_compat.py](../../vllm/sndr_core/integrations/upstream_compat.py:129) | 129, 329 | duplicate dict key `PR_40572_marlin_moe_relocation` | первая запись молча перетирается |

Как исправить:

- Для `Any`, `NoReturn` - добавить imports из `typing`.
- Для PN40 - заменить строку на:

```python
cls_status, cls_reason = pn40_workload_classifier_hook.apply()
```

- Для `upstream_compat.py` - объединить записи или переименовать ключи, например:
  - `PR_40572_marlin_moe_relocation_open_snapshot`
  - `PR_40572_marlin_moe_relocation_verified_snapshot`
- Для `text_patch.py` - либо добавить локальные proxy-assignments после `__getattr__`, либо настроить explicit ruff ignore для F822 с комментарием, почему lazy export intentional.

## 4. Состояние функций проекта

### 4.1. CLI

Реализовано:

- `sndr --version` работает: `SNDR Core 11.0.0`.
- `sndr --help` показывает единый CLI.
- Native команды есть: `install`, `launch`, `memory`, `patches`, `report`, `deps`, `model`, `upstream`, `caveats`, `doctor-system`, `config`, `service`, `tune`, `migrate`, `image`, `k8s`, `proxmox`, `bootstrap`.
- Bridged команды есть: `doctor`, `verify`, `self-test`, `model-config`, `lifecycle-audit`, `validate-schema`, `explain`, `list-models`, `categories`, `plugins`, `telemetry`, `update-channel`, `preflight`, `bench`, `recipe`, `preset`, `init`, `pull`.

Проблемы:

1. `sndr config list` не существует, хотя по UX ожидается рядом с `config diff/explain/new`.

Файл:

- [vllm/sndr_core/cli/config.py](../../vllm/sndr_core/cli/config.py:31)

Сейчас список конфигов живет в bridged `sndr model-config list`. Это работает, но UX раздвоен.

Решение:

- либо добавить `sndr config list` как тонкий alias;
- либо в `sndr config --help` явно показать: "для list/show/audit/validate используйте `sndr model-config`".

2. `sndr self-test` красный из-за P7b. Это P0.

### 4.2. Launcher

Файл:

- [vllm/sndr_core/cli/launch.py](../../vllm/sndr_core/cli/launch.py:285)

Состояние хорошее:

- `launch` использует schema renderer, а не ручную сборку флагов.
- В dry-run показывает полный bash script.
- Live launch включает strict mount validation.
- Docker configs пропускают host apply phase и применяют patches внутри контейнера.
- Есть image digest verification.

Проверка:

```text
python3 -m vllm.sndr_core.cli launch a5000-2x-35b-prod --dry-run
```

Результат: script рендерится, но предупреждает:

```text
UNRESOLVED MOUNTS:
  ${genesis_src}
  ${models_dir}
  ${plugin_src}
```

Это правильное поведение для dry-run, но production требует `~/.sndr/host.yaml`.

Что улучшить:

- Добавить `sndr host init` / `sndr config host doctor`, чтобы пользователь видел недостающие mount variables до запуска.
- Для live launch показывать конкретную команду исправления:

```yaml
paths:
  models_dir: /path/to/models
  genesis_src: /path/to/genesis-vllm-patches/vllm/sndr_core
  plugin_src: /path/to/genesis-vllm-patches/tools/genesis_vllm_plugin
```

### 4.3. Model configs

Состояние:

```text
11 total
9 working
2 tested / QA-only
10/11 validate OK
1/11 validate FAIL: a5000-2x-tier-aware-example
```

Сильные стороны:

- Есть рабочие A5000 presets.
- Есть reference metrics.
- Есть Docker blocks.
- Есть model registry.

Проблемы:

- Path C / PN95 example не проходит validate.
- Ни один builtin config сейчас не содержит `kubernetes`, `proxmox`, `bootstrap`, `service`, `package_sources`, `gpu_tuning` blocks.

Проверка:

```text
rg -n "^(kubernetes|proxmox|bootstrap|service|package_sources|gpu_tuning):" \
  vllm/sndr_core/model_configs/builtin/*.yaml
```

Результат: нет совпадений, кроме `docker:`.

Вывод:

Unified config схема уже шире, чем реальные presets. Для production нужно добавить хотя бы 1-2 полноценных reference config:

- `a5000-2x-35b-prod-full.yaml`
- `single-3090-community-full.yaml`

В них должны быть:

- `docker`
- `package_versions`
- `package_sources`
- `bootstrap`
- `service`
- `artifacts`
- `observability`
- optional `proxmox`
- optional `kubernetes`

### 4.4. Patch registry

Состояние хорошее, но production maturity неоднородная.

Факты:

- 135 entries.
- 122 имеют apply module.
- 85 experimental.
- Только 2 stable.
- `PN95` - partial.
- `PN64` - placeholder.
- `engine` tier entries отсутствуют.

Вывод:

Registry технически целостный, но его нельзя трактовать как "135 production patches". Нужно разделять:

- production-safe default bundle;
- experimental opt-in bundle;
- research/placeholder/retired только для audit/backlog.

Обязательное улучшение:

1. В `sndr patches plan --profile production` запретить:
   - `implementation_status=partial`
   - `implementation_status=placeholder`
   - `lifecycle=research`
   - `lifecycle=retired`
2. В README/PATCHES показывать отдельные счетчики:
   - stable
   - experimental
   - research
   - partial
   - placeholder
   - retired

### 4.5. PN95 / tier-aware cache

PN95 - самая важная новая ветка для памяти/кеша, но она не production complete.

Факт из registry:

```text
PN95 implementation_status=partial
lifecycle=experimental
```

Файл:

- [vllm/sndr_core/integrations/kv_cache/pn95_tier_aware_cache.py](../../vllm/sndr_core/integrations/kv_cache/pn95_tier_aware_cache.py:759)

В коде уже много anchors и runtime hooks:

- admit
- touch
- mamba init
- register kv_caches
- scheduler tick
- blockpool register
- demote on evict
- promote on miss
- phase5 boot check
- block pool init
- get_new_blocks materialization

Но production gaps остаются:

- validate config сейчас падает из-за `GENESIS_PN95_*` knobs.
- Нужна live GPU проверка, что все anchors применяются на текущем vLLM pin.
- Нужен soak test: long context + vision + hybrid GDN + pressure.
- Нужны метрики promote/demote bytes, latency, hit/miss, failure count.
- Нужна safety policy: при любой ошибке PN95 должен отключаться и не портить KV state.

Рекомендация:

Не включать PN95 в production presets как default-on. Держать как explicit experimental profile:

```yaml
lifecycle: experimental
requires_live_validation: true
```

### 4.6. `sndr_engine`

Состояние:

- публичный `vllm/sndr_engine` пустой skeleton;
- все текущие community patches лежат в `sndr_core`;
- registry не содержит `tier="engine"`.

Это правильное решение для текущей стратегии.

Проблема контракта:

- [pyproject-engine.toml](../../pyproject-engine.toml:80) говорит про future entry point group `sndr.engine.overlay`.
- [vllm/sndr_core/license.py](../../vllm/sndr_core/license.py:167) на практике проверяет `vllm.sndr_engine.engine_available()`, а `engine_available()` ищет `.private`.

То есть документация template и реальный code path описывают разные варианты overlay discovery.

Как исправить:

Выбрать один contract:

Вариант A, проще:

- private overlay живет внутри namespace `vllm.sndr_engine.private`;
- `engine_available()` остается как сейчас;
- убрать из `pyproject-engine.toml` обещание entry point discovery.

Вариант B, профессиональнее:

- private overlay отдельным wheel/package;
- discovery через `importlib.metadata.entry_points(group="sndr.engine.overlay")`;
- `license.py` проверяет overlay registration;
- `vllm/sndr_engine` можно оставить как reserved namespace, но не как единственный source of truth.

Рекомендация: **B**, но реализовать позже. Сейчас достаточно зафиксировать contract и не обещать оба одновременно.

## 5. Installer / bootstrap / service / k8s / Proxmox

### 5.1. Bootstrap

Файл:

- [vllm/sndr_core/cli/bootstrap.py](../../vllm/sndr_core/cli/bootstrap.py:103)

Состояние:

- CLI есть.
- `doctor`, `plan`, `apply`, `status` есть.
- Подключены `deps.inspect_host`, `plan_changes`, `apply`.

Недореализовано:

- `model-artifacts` и `service` scope явно помечены unsupported:

[vllm/sndr_core/cli/bootstrap.py](../../vllm/sndr_core/cli/bootstrap.py:103)

```python
if "model-artifacts" in s:
    unsupported.add("model-artifacts")
if "service" in s:
    unsupported.add("service")
```

Что делать:

1. Добавить planner/apply support для model artifacts:
   - HF repo id;
   - target dir;
   - required files;
   - optional SHA256 / etag / size checks;
   - gated model auth instructions.
2. Добавить service scope:
   - systemd user/system;
   - docker compose;
   - podman quadlet;
   - status/logs/healthcheck.
3. Добавить `--dry-run --json` как стабильный contract для UI/automation.

### 5.2. Service CLI

Файл:

- [vllm/sndr_core/cli/service.py](../../vllm/sndr_core/cli/service.py:192)

Состояние:

- systemd реализован частично.
- docker_compose/podman_quadlet фактически не генерируются.
- kubernetes/bare_metal возвращают инструкции/noop.

Проблемные места:

```python
backend=docker_compose - Genesis does NOT generate compose files
```

Это честно, но не production complete.

Что нужно:

- `sndr service install` должен генерировать compose/quadlet/systemd artifacts.
- `start/stop/status/logs` должны использовать backend-native commands:
  - `docker compose up/down/logs`;
  - `podman systemd/quadlet`;
  - `systemctl`;
  - `kubectl`.
- Для systemd добавить sandboxing:
  - `NoNewPrivileges=true`
  - `ProtectSystem=strict` где возможно
  - `PrivateTmp=true`
  - явные `EnvironmentFile`
  - не хранить API keys в unit file.

### 5.3. Kubernetes

Файл:

- [vllm/sndr_core/cli/k8s.py](../../vllm/sndr_core/cli/k8s.py:128)

Состояние:

- renderer есть.
- apply/status/logs/delete есть.

Недостатки:

- Не используется structured YAML emitter, строки собираются вручную.
- Нет Secret для API key.
- Нет PVC/hostPath policy.
- Нет node selector / tolerations / runtimeClass validation.
- Нет readiness timeout/status parsing.
- Нет GPU operator/device-plugin detection.
- В builtin configs нет `kubernetes:` blocks.

Что делать:

- Генерировать YAML через structured dict + `yaml.safe_dump`.
- Добавить `Secret` для API key.
- Добавить `resources.requests`.
- Добавить `nodeSelector` / `runtimeClassName` / `tolerations`.
- Добавить `sndr k8s doctor`.
- Добавить минимум один sample config с `kubernetes:`.

### 5.4. Proxmox

Файл:

- [vllm/sndr_core/cli/proxmox.py](../../vllm/sndr_core/cli/proxmox.py:162)

Состояние:

- doctor/inventory/render/status есть.
- render печатает `pct`/`qm` команды.

Недостатки:

- Нет PVE API mode.
- Нет генерации полного LXC config.
- GPU passthrough выводится как ручная инструкция.
- В LXC docker path есть небезопасная рекомендация:

[vllm/sndr_core/cli/proxmox.py](../../vllm/sndr_core/cli/proxmox.py:197)

```text
curl -fsSL https://get.docker.com | sh
```

Для production лучше не pipe shell from internet.

Что делать:

- Перейти на distro packages / Docker apt repo с keyring и pinning.
- Добавить PVE API backend.
- Добавить `proxmox apply --yes` только после dry-run diff.
- Добавить `proxmox doctor` проверки:
  - IOMMU;
  - NVIDIA devices;
  - driver branch;
  - container nesting;
  - cgroup2;
  - `/dev/nvidia*`;
  - kernel/PVE caveats.

## 6. Hardcoded paths и устаревшие ссылки

Активный код стал лучше: большинство путей вынесено в config/host detection. Но следы старой `_genesis` структуры и локальных путей еще есть.

Критичные активные места:

| Файл | Строка | Проблема |
|---|---:|---|
| [conftest.py](../../conftest.py:5) | 5-14 | docstring говорит про `vllm._genesis.*`, хотя `_genesis` удален |
| [vllm/sndr_core/__init__.py](../../vllm/sndr_core/__init__.py:24) | 24-26 | docstring все еще описывает Stage 1 skeleton / `_genesis` |
| [vllm/sndr_core/version.py](../../vllm/sndr_core/version.py:6) | 6-18 | говорит, что `_genesis` станет shim, хотя v11 shim удален |
| [vllm/sndr_core/locations/project_paths.py](../../vllm/sndr_core/locations/project_paths.py:117) | 117 | описывает legacy fallback `_genesis/wiring` |
| [docs/INSTALL.md](../../docs/INSTALL.md:356) | 356 | все еще предлагает symlink `vllm/_genesis` |
| [docs/MODEL_CONFIG_LAUNCHER.md](../../docs/MODEL_CONFIG_LAUNCHER.md:253) | 253 | mount на `/usr/local/.../vllm/_genesis` |
| [tests/legacy/test_runtime_rebind_verification.py](../../tests/legacy/test_runtime_rebind_verification.py:31) | 31 | ожидает old `vllm/_genesis/patches/apply_all.py`, поэтому skip |

Что делать:

1. Разделить docs на:
   - current docs;
   - historical docs under `docs/archive/`.
2. В current docs запретить новые `_genesis` refs, кроме явно помеченных historical sections.
3. CI grep gate:

```text
rg "vllm\\._genesis|vllm/_genesis|192\\.168\\.1\\.10|/home/sander|/nfs/genesis" \
  README.md docs scripts vllm/sndr_core tests
```

4. Для исключений использовать allowlist file, а не ручную память.

## 7. Release hygiene

Состояние git:

```text
git status --short | wc -l -> 503
```

Это не проблема сама по себе во время активной разработки, но для release это blocker: невозможно понять, какие изменения входят в выпуск, какие являются generated/cache, а какие случайно попали.

Найдены generated artifacts:

- `.DS_Store`
- `.pytest_cache`
- `.ruff_cache`
- много `__pycache__`
- `tools/genesis_vllm_plugin/.DS_Store`
- `vllm/.DS_Store`
- `docs/.DS_Store`

Что делать перед любым release:

1. Очистить generated files.
2. Проверить `.gitignore`.
3. Разделить commit series:
   - migration `_genesis -> sndr_core`;
   - CLI/config;
   - docs;
   - tests;
   - generated charts/docs.
4. Прогнать:

```text
python3 -m pytest -q
python3 -m vllm.sndr_core.cli self-test
python3 -m vllm.sndr_core.cli patches doctor
python3 -m vllm.sndr_core.apply.shadow --strict
python3 -m ruff check vllm/sndr_core vllm/sndr_engine --select F,E9
```

## 8. Security posture

### 8.1. License trust anchor

Файл:

- [vllm/sndr_core/license.py](../../vllm/sndr_core/license.py:58)

Сейчас:

```python
_TRUST_ANCHOR_PUBKEY_B64URL = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
```

Это placeholder zero-key. Код честно предупреждает, что signed tokens будут rejected.

Вывод:

- Для текущего public/core проекта это допустимо.
- Для платного/private engine это не production-ready.

Перед private engine:

1. Провести offline key ceremony.
2. Сгенерировать Ed25519 keypair.
3. Вшить public key в release.
4. Убрать legacy unsigned keys из production path.
5. Добавить token revocation/rotation story.

### 8.2. Installer/security

Проблемы:

- В README/install docs есть `curl | bash` quickstart.
- Proxmox renderer предлагает `curl get.docker.com | sh`.
- K8s ConfigMap хранит все env, включая потенциально чувствительные значения.

Что делать:

- В quickstart оставить `curl | bash` как convenience, но рядом дать safer install:

```text
git clone ...
cd ...
./install.sh --dry-run
./install.sh
```

- Для Proxmox/Docker использовать distro repo + keyring + apt pinning.
- Для API keys использовать Secret / env file с правами `0600`.

## 9. Документы и планы: что реализовано, что нет

Реализовано:

- `sndr_core` canonical package.
- `sndr_engine` skeleton.
- `pyproject.toml` для core.
- `pyproject-engine.toml` template.
- CLI entrypoint `sndr`.
- Registry/spec/shadow patch layer.
- Model configs.
- Partial unified config blocks in schema/CLI.
- Deps/doctor-system inventory.
- Report bundle CLI.
- Basic image digest check.
- Trust-anchor skeleton.

Не доведено:

- Full test suite green.
- Torch-less import contract для всех apply modules.
- PN95 config validation.
- PN95 production validation.
- K8s/Proxmox/service full implementation.
- Model artifact download + verification as first-class bootstrap scope.
- Private engine overlay contract.
- Docs cleanup after `_genesis` removal.
- Release hygiene / clean worktree.
- Static `ruff F/E9` gate.
- Live GPU Docker validation in CI or remote runner.

## 10. Приоритетный план исправлений

### P0 - обязательно до любого release

1. Исправить P7b torch-less import.
2. Исправить PN26 env-disabled import.
3. Исправить `verify_live_rebinds` / `_resolve_wiring_module`.
4. Исправить PN40 undefined variable.
5. Исправить `Any`, `NoReturn` imports.
6. Исправить `a5000-2x-tier-aware-example` validation.
7. Прогнать полный `pytest`.
8. Прогнать `sndr self-test`.

Exit criteria:

```text
python3 -m pytest -q
# 0 failed

python3 -m vllm.sndr_core.cli self-test
# Summary: all pass

python3 -m ruff check vllm/sndr_core vllm/sndr_engine --select F,E9
# 0 critical runtime/static errors
```

### P1 - перед public beta release

1. Очистить generated files.
2. Обновить current docs под `sndr_core`, перенести старые `_genesis` инструкции в archive.
3. Добавить `sndr config list` alias.
4. Вынести runtime tunable env registry отдельно от patch env flags.
5. Добавить production profile gate для patches.
6. Обновить README/PATCHES counters по lifecycle/status.
7. Проверить `pyproject.toml` wheel contents через clean venv.

### P2 - production launch readiness

1. Проверить на remote GPU сервере:
   - Docker run;
   - patch apply inside container;
   - `vllm serve`;
   - `/v1/models`;
   - chat completion;
   - tool-call streaming;
   - memory stability;
   - restart/relaunch idempotency.
2. Добавить `GENESIS_INTEGRATION_ENDPOINT` pipeline.
3. Добавить long context smoke:
   - 27B INT4 TQ k8v4;
   - 35B FP8 DFlash;
   - Gemma community config when ready.
4. Добавить soak:
   - 1h;
   - 8h;
   - memory leak check;
   - CV/TPS regression thresholds.

### P3 - automation and installer maturity

1. Реализовать bootstrap scopes:
   - model-artifacts;
   - service;
   - container-runtime;
   - gpu-runtime.
2. Добавить host profile manager:
   - `sndr host detect`;
   - `sndr host init`;
   - `sndr host doctor`;
   - `sndr host edit`.
3. Добавить community config workflow:
   - schema validation;
   - benchmark metadata;
   - hardware tags;
   - config signing/checksum.
4. Сделать Proxmox support полноценным:
   - PVE API;
   - LXC/VM templates;
   - GPU passthrough doctor;
   - generated config diff.
5. Сделать K8s support полноценным:
   - YAML safe dump;
   - Secret;
   - PVC;
   - runtimeClass;
   - nodeSelector;
   - health/status.

## 11. Рекомендуемая структура проекта

Текущая структура в целом правильная:

```text
vllm/sndr_core/
  apply/
  bundles/
  cache/
  cli/
  compat/
  core/
  deps/
  detection/
  dispatcher/
  integrations/
  kernels/
  locations/
  model_configs/
  runtime/
  schemas/
  wiring/

vllm/sndr_engine/
  skeleton only
```

Что улучшить:

1. `compat/` постепенно сжимать. Все новые команды должны быть native `cli/*`.
2. `wiring/` оставить только generic patching helpers; patch implementations уже правильно в `integrations/`.
3. `locations/` сделать единственной точкой путей. Убрать старые mentions `sndr_paths.py` и `_genesis`.
4. `dispatcher/registry.py` оставить data-only, но вынести большие группы в generated registry chunks или YAML/JSON source, если файл станет плохо поддерживать.
5. `tests/legacy` либо перевести в canonical tests, либо явно пометить как historical compatibility suite.
6. `docs/upstream` и `docs/_internal` не смешивать с current user docs.

Целевая структура для core/engine:

```text
sndr_core:
  public CLI
  model configs
  community patches
  launcher
  installer/bootstrap
  diagnostics
  public plugin API

sndr_engine:
  empty in public repo
  private overlay in separate repo/wheel
  no hard dependency from core
  core detects it only by explicit overlay contract
```

## 12. Конкретный checklist для следующего исправляющего прохода

1. P7b:
   - убрать top-level kernel import;
   - сделать lazy torch import;
   - добавить regression test на import без torch.
2. PN26:
   - env check до kernel import;
   - catch ImportError;
   - test `apply()` with env disabled.
3. Verify path:
   - импортировать `verify_live_rebinds`;
   - заменить `_resolve_wiring_module`;
   - обновить legacy module names.
4. Static defects:
   - `Any`;
   - `NoReturn`;
   - PN40 undefined;
   - duplicate upstream key;
   - text_patch lazy export policy.
5. Model config:
   - разрешить `GENESIS_PN95_` knobs;
   - решить R-010 pin для `a5000-2x-tier-aware-example`.
6. CLI:
   - добавить `sndr config list`;
   - добавить `sndr host doctor/init`.
7. Docs:
   - убрать active `_genesis` instructions;
   - current install docs привести к `sndr_core`.
8. Release hygiene:
   - удалить cache artifacts;
   - проверить clean wheel install;
   - зафиксировать миграцию отдельным commit.
9. Live validation:
   - прогнать remote Docker/GPU tests;
   - сохранить logs/reports;
   - добавить результаты в release notes.

## 13. Итог

Проект стал существенно лучше структурно: `sndr_core` выглядит как правильная основа, `sndr_engine` сейчас не загрязнен public кодом, registry/shadow слой дает хороший контроль, CLI и model configs уже дают реальную ценность.

Но текущее состояние еще не production. Минимальная граница production-ready:

- полный `pytest` зеленый;
- `sndr self-test` зеленый;
- no critical `ruff F821/F822`;
- все builtin configs validate OK;
- live Docker/GPU запуск проверен;
- current docs не ведут пользователя в `_genesis`;
- release tree очищен от generated artifacts.

После закрытия P0 проект можно считать готовым к public beta. После P1/P2 - к аккуратному production preview для ограниченного круга пользователей.
