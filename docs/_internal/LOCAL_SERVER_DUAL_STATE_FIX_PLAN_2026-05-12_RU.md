# Local/server dual-state аудит и план исправлений

Дата: 2026-05-12  
Локальная папка: `/Users/sander/Documents/Visual Studio Code/genesis-vllm-patches`  
Серверная папка: `sander@192.168.1.10:/home/sander/genesis-vllm-patches-v11`  
Режим: анализ и запись отчета. Кодовые файлы не изменялись.

## 1. Executive summary

Локальная и серверная версии находятся на одном git commit `f9576df`, ветка `dev`, но рабочие деревья отличаются. При этом основной runtime-код `vllm/sndr_core` синхронизирован по содержимому: 356 файлов без cache на обеих сторонах, content diff по `vllm/sndr_core` не обнаружен. Базовые guard-проверки на локальной версии проходят:

- `python3 -m vllm.sndr_core.compat.cli self-test --json`: PASS, `8/8`.
- `python3 -m vllm.sndr_core.apply.shadow --strict`: PASS, `CLEAN`.

Серверные guard-проверки по последним heartbeat также проходили стабильно. Значит, сейчас главный риск не в немедленной поломке registry/apply-layer, а в рассинхроне окружений, документации, runbook, deploy/security-автоматизации и dirty/untracked state.

Ключевые выводы:

1. **Core-код совпадает**, но проект все равно не production-ready из-за P1/P2 задач.
2. **Сервер содержит 528 dirty status entries**, локально 509. Это не нормальное release-состояние.
3. **Локально есть `vllm/sndr_engine` skeleton**, на сервере его нет. Это архитектурный policy conflict: нужно выбрать одну модель public/private boundary.
4. **На сервере есть regressions, которых локально уже нет**: hardcoded LAN IP в `benchmarks/harness/run_all.py`, старый PR template, public internal work log.
5. **На сервере есть runtime/test artifacts**, которые не должны жить в репозитории: `benchmarks/runs/*`, `.DS_Store`.
6. **На сервере отсутствует `.pre-commit-config.yaml`**, но Makefile описывает `make precommit`; это ломает заявленный workflow.
7. **Сервер удалил много public docs и probes**, которые локально еще есть. Это может быть намеренная v11-компактизация, но сейчас нет migration map: что удалено осознанно, что потеряно случайно, какие ссылки стали битые.

Итог: перед исправлением кода нужно сначала стабилизировать состояние двух деревьев. Иначе можно чинить одну сторону и снова ломать другую.

## 2. Как сравнивалось

Снимки:

- Локально:
  - commit: `f9576df`
  - branch: `dev`
  - `git status --short`: 509 записей
- Сервер:
  - commit: `f9576df`
  - branch: `dev`
  - `git status --short`: 528 записей
  - status hash: `91f5c7476927311fe016d9eb0f58e68a40c3579c6750ac84e3ad0cd89920cb1c`

Manifest comparison:

- Локально: 1091 файлов в manifest.
- Сервер: 1029 файлов в manifest.
- Только локально: 89 файлов.
- Только сервер: 27 файлов.
- Различаются по sha256: 12 файлов.

Из manifest исключались `.git`, `.pytest_cache`, `.ruff_cache`, `__pycache__`.

## 3. Что совпадает и не является текущей проблемой

### 3.1. `vllm/sndr_core`

Состояние:

- Локально: 356 файлов без cache.
- Сервер: 356 файлов без cache.
- В sha256 diff нет файлов `vllm/sndr_core/*`.

Вывод:

- Текущий `sndr_core` одинаков локально и на сервере.
- Ошибки `compose.py`, `quadlet.py`, `k8s.py`, `license.py`, `registry_metadata.py`, `doctor_logs.py`, которые были найдены в серверном наблюдении, если они не исправлены, присутствуют на обеих сторонах одинаково.
- Исправлять их нужно один раз в canonical рабочем дереве, затем синхронизировать.

### 3.2. Apply/registry guards

Локально:

```text
self-test: 8/8 pass
apply.shadow --strict: CLEAN
```

Сервер:

```text
self-test: 8/8 pass
apply.shadow --strict: CLEAN
```

Вывод:

- Нет текущего registry/apply-layer P0.
- Но эти guard-ы не ловят все ошибки deploy, docs, license payload, hardcoded paths, missing files и Kubernetes manifest correctness.

## 4. Самые важные local/server расхождения

### P1. Серверный `benchmarks/harness/run_all.py` вернул hardcoded LAN IP

Файл: `benchmarks/harness/run_all.py`

Локально:

```python
default=os.environ.get(
    "GENESIS_BENCH_ENDPOINT",
    # Default to localhost; set GENESIS_BENCH_ENDPOINT for remote rigs.
    # Audit closure 2026-05-08 (P2-1): replaced hardcoded LAN IP.
    "http://127.0.0.1:8000/v1",
)
```

Сервер:

```python
default=os.environ.get(
    "GENESIS_BENCH_ENDPOINT",
    "http://192.168.1.10:8000/v1",
)
```

Проблема:

- Серверная версия снова привязана к конкретному LAN IP.
- Это ломает переносимость, публичный community flow и запуск на другой машине.
- Это прямой regression относительно локальной версии, где hardcoded IP уже убран.

Что сделать:

1. Взять локальную версию `benchmarks/harness/run_all.py` как правильную.
2. Сервер заменить на localhost/env fallback.
3. Добавить lint/check:

```bash
rg -n "192\\.168\\.1\\.10|sander@|/home/sander" benchmarks scripts tools vllm docs
```

Решение: **серверную версию переделать по локальной**.

### P1. Серверный `.github/PULL_REQUEST_TEMPLATE.md` устарел

Файл: `.github/PULL_REQUEST_TEMPLATE.md`

Локально шаблон уже v11-aware:

- `vllm/sndr_core/integrations/<family>/<file>.py`
- iron-rule #11 retire provenance
- pin-gate
- family contracts
- docs auto sync
- no hardcoded operator paths

Серверный шаблон старый:

```md
- [ ] New patch (adds a `wiring/patch_*.py` + `dispatcher.py` registry entry)
...
- [ ] `python3 -m pytest vllm/sndr_core/tests/` — pass count: X passed / 0 failed
- [ ] `genesis verify --quick` succeeds
```

Проблема:

- Серверный PR template возвращает разработчика к старой структуре `wiring/patch_*.py` и `dispatcher.py`.
- Это противоречит v11 `sndr_core/integrations`, registry/spec, family contracts.
- Он теряет iron-rule #11, pin-gate и auto-doc checks.

Что сделать:

1. Взять локальный `.github/PULL_REQUEST_TEMPLATE.md` как canonical.
2. Серверный заменить.
3. Проверить ссылки из шаблона на реально существующие файлы.

Решение: **серверный PR template заменить локальным**.

### P1. `.pre-commit-config.yaml` есть локально, отсутствует на сервере

Файл: `.pre-commit-config.yaml`

Состояние:

- Локально есть.
- На сервере отсутствует.
- Серверный `Makefile` содержит:

```make
precommit-install:
	$(PYTHON) -m pip install pre-commit
	pre-commit install

precommit:
	pre-commit run --all-files
```

Проблема:

- `make precommit` на сервере может быть нерабочим или декоративным, потому что нет `.pre-commit-config.yaml`.
- PR template и Makefile обещают gates, но серверная версия не содержит config.

Что сделать:

1. Вернуть `.pre-commit-config.yaml` на сервер, если precommit является официальным gate.
2. Или удалить/переписать Makefile/PR template precommit claims.
3. Предпочтительно: синхронизировать локальный `.pre-commit-config.yaml` на сервер и включить в tracked state.

Решение: **восстановить pre-commit config и проверить `pre-commit run --all-files` хотя бы в offline-safe режиме**.

### P1. `vllm/sndr_engine` есть локально, отсутствует на сервере

Состояние:

Локально:

```text
vllm/sndr_engine/LICENSE-NOTICE
vllm/sndr_engine/__init__.py
vllm/sndr_engine/version.py
```

Сервер:

```text
vllm/sndr_engine: MISSING
```

При этом и локально, и на сервере есть упоминания `sndr_engine` в:

- `README.md`
- `pyproject.toml`
- `vllm/sndr_core/license.py`
- `vllm/sndr_core/bundles/_common.py`
- `vllm/sndr_core/dispatcher/decision.py`
- tests/docs

Проблема:

- Локальная и серверная версии реализуют разные policy:
  - локально: public skeleton package exists, `engine_available()` должен возвращать `False`;
  - сервер: package отсутствует, engine availability = `NO_PACKAGE`.
- Это влияет на tests и license/bundle gate.
- Docs говорят "reserved namespace, currently empty", что ближе к локальному skeleton, но сервер этому не соответствует.

Решение нужно выбрать явно:

**Вариант A — public skeleton есть.**

- Синхронизировать 3 skeleton-файла на сервер.
- `.gitignore` должен игнорировать только private subdirs, но не skeleton:

```gitignore
vllm/sndr_engine/private/
vllm/sndr_engine/patches/
vllm/sndr_engine/kernels/
!vllm/sndr_engine/__init__.py
!vllm/sndr_engine/version.py
!vllm/sndr_engine/LICENSE-NOTICE
```

Плюс: docs честно описывают reserved namespace.  
Минус: простой `import vllm.sndr_engine` больше не является proof наличия платного engine.

**Вариант B — public skeleton отсутствует.**

- Оставить серверную модель.
- Убрать из docs утверждение, что namespace существует как package.
- Все gates должны работать через entry points/license overlay, а не через package import.

Плюс: меньше риск случайно опубликовать private namespace.  
Минус: docs и локальные тесты нужно переписать под отсутствие package.

Рекомендация: для текущей стратегии лучше **вариант B**, если платного engine пока нет. Core должен знать о возможном engine через optional overlay API/entry points, но public repo не обязан поставлять `vllm.sndr_engine`.

### P1. Сервер содержит public internal work log, локально нет

Файл только на сервере:

```text
docs/WORK_LOG_2026-05-12_RU.md
```

Проблема:

- Это internal operational log, а не public docs.
- По предыдущему наблюдению в нем были server IP/internal migration notes.
- Public docs не должны хранить такие данные.

Что сделать:

1. Перенести содержимое в `docs/_internal/WORK_LOG_2026-05-12_RU.md`.
2. Удалить public `docs/WORK_LOG_2026-05-12_RU.md`.
3. Добавить docs lint:

```bash
rg -n "192\\.168\\.1\\.10|/home/sander|sander@" docs README.md
```

Решение: **удалить/перенести server-only public work log**.

### P1. Сервер содержит runtime benchmark artifacts в `benchmarks/runs`

Файлы только на сервере:

```text
benchmarks/runs/genesis_bench_quick_2026-05-11T12-15-33Z.json
benchmarks/runs/genesis_bench_quick_2026-05-11T12-15-33Z.md
...
benchmarks/runs/genesis_bench_quick_2026-05-11T18-09-35Z.json
benchmarks/runs/genesis_bench_quick_2026-05-11T18-09-35Z.md
```

Проблема:

- Это runtime outputs, не исходный код.
- Они создают шум в diff и могут содержать endpoint/model/internal rig details.
- Если их нужно хранить, им место в internal audit artifacts или в отдельном benchmark archive, но не как untracked рабочий мусор.

Что сделать:

1. Решить: сохранять как internal evidence или удалить.
2. Если сохранять:
   - перенести в `docs/_internal/bench_results/`;
   - убрать приватные endpoints;
   - добавить summary index.
3. Если не сохранять:
   - добавить `benchmarks/runs/` в `.gitignore`.

Решение: **не держать `benchmarks/runs/*` как неуправляемый server-only мусор**.

### P1. Сервер содержит `.DS_Store`

Файлы только на сервере:

```text
tools/genesis_vllm_plugin/.DS_Store
tools/genesis_vllm_plugin/genesis_v7/.DS_Store
```

Проблема:

- macOS metadata не должна быть в repo.

Что сделать:

1. Удалить `.DS_Store`.
2. Проверить `.gitignore` содержит:

```gitignore
.DS_Store
```

Решение: **удалить server-only `.DS_Store`**.

### P2. Сервер содержит root-level `generate_patches_md.py`, локально нет

Файл только на сервере:

```text
generate_patches_md.py
```

При этом есть:

```text
scripts/generate_patches_md.py
```

Проблема:

- Дублирование entrypoint сбивает operator UX.
- Есть риск, что root script устареет относительно `scripts/generate_patches_md.py`.

Что сделать:

1. Проверить, является ли root `generate_patches_md.py` wrapper.
2. Если это дубликат — удалить.
3. Если нужен back-compat wrapper — оставить минимальный wrapper, который импортирует `scripts/generate_patches_md.py`, и задокументировать.

Решение: **не держать два независимых генератора**.

## 5. Документы и тесты: server cleanup vs accidental loss

### Только локально: 80 docs-файлов

Примеры:

```text
docs/BENCHMARKS.md
docs/CLIFFS.md
docs/COMMANDS.md
docs/COMPATIBILITY.md
docs/CONFIGS.md
docs/CONFIGURATION.md
docs/COOKBOOK.md
docs/FAQ.md
docs/HARDWARE.md
docs/MODELS.md
docs/OOM_RECIPES.md
docs/QUICKSTART.md
docs/SELF_TEST.md
docs/upstream_refs/*
docs/_internal/*
```

Серверная git status показывает многие из них как `D`.

Риск:

- Если server v11 intentionally compact, удаление может быть правильным.
- Но без migration map нельзя понять:
  - какие docs заменены новыми consolidated docs;
  - какие ссылки теперь битые;
  - что нужно в public repo;
  - что нужно оставить только internal.

Что сделать:

1. Создать `docs/_internal/DOC_MIGRATION_MAP_2026-05-12_RU.md`.
2. Для каждого удаленного public doc указать:
   - `restore`;
   - `merge into docs/README.md`;
   - `move to docs/_internal`;
   - `delete intentionally`.
3. Запустить local path/link checker.

Особо важное:

- `docs/CONFIGURATION.md`, `docs/QUICKSTART.md`, `docs/INSTALL.md`, `docs/HARDWARE.md`, `docs/OOM_RECIPES.md` полезны для community. Если сервер их удаляет, README/INSTALL должны полностью закрывать эти темы.
- `docs/upstream_refs/*` могут быть тяжелым архивом и не нужны в public repo, но тогда ссылки на них нужно убрать.

### Только локально: tests/probes/bench/soak

Примеры:

```text
tests/bench/comprehensive_bench.py
tests/probes/streaming_thinking_probe.py
tests/probes/verify_new_patches_all_models.py
tests/soak/cliff2_multiturn_soak.py
tests/soak/pn40_soak_1000.py
```

Сервер их удалил.

Риск:

- Если эти tests/probes больше не поддерживаются, удаление ок.
- Если docs/Makefile/CI еще ссылаются на них, будет broken workflow.

Что сделать:

1. Проверить ссылки:

```bash
rg -n "comprehensive_bench|streaming_thinking_probe|verify_new_patches|cliff2_multiturn|pn40_soak" .
```

2. Либо восстановить файлы из локальной версии, либо удалить все ссылки.

## 6. Diff-файлы, которые требуют ручного решения

Manifest показал 12 файлов с разным содержимым:

```text
.github/PULL_REQUEST_TEMPLATE.md
SESSION_LOG_2026-05-06.md
benchmarks/harness/run_all.py
benchmarks/v7_10_validation_20260424/upstream_compare/PR_DEEP_DIVE.md
docs/_internal/audits/genesis_deep_audit_2026-05-06.md
docs/_internal/audits/genesis_post_fix_rescan_audit_2026-05-05.md
docs/_internal/audits/genesis_scripts_since_noon_audit_ru_2026-05-05.md
genesis_deep_audit_2026-05-07.md
genesis_full_project_audit_2026-05-08.md
sndr_production_readiness_audit_2026-05-08.md
sndr_repeat_deep_audit_2026-05-08.md
sndr_structure_deep_audit_2026-05-07.md
```

Решения:

- `.github/PULL_REQUEST_TEMPLATE.md`: взять локальный.
- `benchmarks/harness/run_all.py`: взять локальный.
- `SESSION_LOG_2026-05-06.md`: обе версии содержат устаревшие пути (`vllm/sndr_core/integrations/apply_all.py` или `vllm/sndr_core/patches/apply_all.py`), а реальный v11 apply-layer сейчас `vllm/sndr_core/apply/*`. Нужно исправить не копированием одной стороны, а обновлением на реальный путь.
- Audit docs с разным содержимым: не влияют на runtime, но нужно выбрать источник правды и перенести старые root-level audit files в `docs/_internal/audits/`.

## 7. Shared code/design issues, найденные ранее и актуальные для обеих сторон

Поскольку `vllm/sndr_core` совпадает локально и на сервере, эти пункты относятся к обеим версиям.

### P1. License payload validation

Файл: `vllm/sndr_core/license.py`

Проблема:

- Signed payload с missing/string `expires_at`, missing `customer_id`, `issued_at`, `engine_major` может не блокироваться строго.

Что сделать:

- Ввести строгий contract:

```python
required = {
    "customer_id": str,
    "issued_at": (int, float),
    "expires_at": (int, float),
    "engine_major": int,
}
for key, expected in required.items():
    if key not in payload or not isinstance(payload[key], expected):
        return LicenseStatus(False, "BAD_PAYLOAD", f"invalid {key}")
```

Acceptance:

- valid token passes;
- missing `expires_at` fails;
- string `expires_at` fails;
- expired token fails;
- wrong `engine_major` fails.

### P1. Trust anchor private key exposure

Файлы:

- `scripts/generate_trust_anchor.py`
- `docs/security/TRUST_ANCHOR_CEREMONY.md`

Проблема:

- Key generation выводил private key в stdout.
- Для production это надо считать compromised.

Что сделать:

- Production key сгенерировать offline.
- `--out` не печатает private key.
- Private key печатается только через явный `--print-private`.

### P1. `production_default=eligible` завышается без test coverage

Файл:

- `vllm/sndr_core/dispatcher/registry_metadata.py`

Проблема:

- `stable` может стать `eligible`, даже если `test_status=none`.

Что сделать:

- `eligible` только при `stable + test_status != none` или explicit audited override.

### P1. Compose secret leak

Файл:

- `vllm/sndr_core/cli/compose.py`

Проблема:

- Literal `VLLM_API_KEY` может попасть в `/tmp/sndr-compose/docker-compose.<key>.yml`.

Что сделать:

- Секреты только через `.env`/Docker secrets/env-file.
- Temp dir mode `0700`.
- Rendered compose не должен содержать literal key.

### P2. Deploy command builder divergence

Файлы:

- `vllm/sndr_core/cli/compose.py`
- `vllm/sndr_core/cli/quadlet.py`
- `vllm/sndr_core/cli/k8s.py`
- `vllm/sndr_core/model_configs/schema.py`

Проблема:

- Разные адаптеры могут генерировать разные `vllm serve` команды.

Что сделать:

- Единый `RuntimeCommandSpec` и parity tests.

### P2. Mount resolver divergence

Файл:

- `vllm/sndr_core/cli/compose.py`

Проблема:

- `_resolve_mount()` вручную заменяет `${...}` и может оставить unresolved placeholders.

Что сделать:

- Использовать один strict resolver из schema/env слоя.

### P2. Quadlet escaping

Файл:

- `vllm/sndr_core/cli/quadlet.py`

Проблема:

- `Environment={k}={v}` и `Exec=...` недостаточно безопасны для пробелов, кавычек, newline.

Что сделать:

- Environment file или systemd-safe quoting.

### P2. K8s YAML emitter и validation

Файлы:

- `vllm/sndr_core/cli/k8s.py`
- `vllm/sndr_core/model_configs/schema.py`

Проблема:

- YAML собирается f-string/`repr`.
- Недостаточная validation `node_selector`, `pvc`, `secret_mounts`, names, sizes, mount paths.

Что сделать:

- Dict objects + `yaml.safe_dump_all`.
- DNS-1123 validation.
- Negative tests.

### P2. `doctor_logs` шумит unrelated containers и неверно фильтрует `dmesg --ctime`

Файл:

- `vllm/sndr_core/cli/doctor_logs.py`

Проблема:

- `nvidia-gpu-exporter`/`docker-sandbox-1` restart-loop делают host readiness красным.
- `--logs-hours` не фильтрует `dmesg --ctime` корректно.

Что сделать:

- Container prefix filters.
- Parse ctime или читать uptime-format.
- Unknown timestamp не включать автоматически в strict window.

### P2. `UPSTREAM_WATCHLIST.yaml` не подключен к automation

Файлы:

- `docs/upstream/UPSTREAM_WATCHLIST.yaml`
- `Makefile`
- `scripts/audit_upstream_status.py`
- `tools/check_upstream_drift.py`

Проблема:

- YAML описан как автоматизация, но `make audit-upstream` его не читает.

Что сделать:

- Добавить `scripts/audit_upstream_watchlist.py` или расширить `scripts/audit_upstream_status.py`.
- `make audit-upstream` должен запускать registry audit + watchlist audit.

### P2. PN96 bench plan не исполним

Файл:

- `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md`

Проблема:

- Ссылается на отсутствующие `snapshot_pre_arm.sh`, `start_35b_fp8_PROD.sh`, `tools/run_stress.py`.
- Содержит destructive commands, требующие отдельного go-ahead.

Что сделать:

- Обновить под v11 canonical launcher/model-config flow.
- Заменить stress runner существующим инструментом или добавить новый.
- Пометить destructive steps как operator-only.

## 8. Что исправлять в каком порядке

### Этап 1. Свести local/server state

1. Выбрать canonical source:
   - для `sndr_core`: любая сторона, они совпадают;
   - для `benchmarks/harness/run_all.py`: локальная;
   - для `.github/PULL_REQUEST_TEMPLATE.md`: локальная;
   - для `sndr_engine`: принять policy A или B;
   - для docs deletion: сделать migration map.
2. Убрать server-only мусор:
   - `.DS_Store`;
   - `benchmarks/runs/*` или перенести в internal archive;
   - public `docs/WORK_LOG_2026-05-12_RU.md`.
3. Восстановить `.pre-commit-config.yaml` на сервер или убрать precommit promises.

Acceptance:

```bash
git status --short
git ls-files --others --exclude-standard
```

Каждый файл должен иметь решение: track, delete, move internal, generated-ignore.

### Этап 2. Закрыть hardcoded/private leakage

1. `benchmarks/harness/run_all.py`: убрать `192.168.1.10`.
2. Public docs: убрать `sander@`, `/home/sander`, `User=sander`.
3. Work logs только в `_internal`.

Acceptance:

```bash
rg -n "192\\.168\\.1\\.10|/home/sander|User=sander|sander@" README.md docs scripts tools benchmarks vllm
```

### Этап 3. Security/license

1. Trust anchor safe generation.
2. License payload strict validation.
3. Docs/security sync.

Acceptance:

```bash
python3 -m pytest tests/unit/test_license.py tests/unit/test_trust_anchor_generator.py -q
```

### Этап 4. Deploy correctness

1. Secure compose secrets.
2. Unified command builder.
3. Unified mount resolver.
4. Quadlet escaping.
5. K8s safe emitter + validation + PVC delete policy.

Acceptance:

```bash
python3 -m pytest tests/unit/cli/test_compose_render.py tests/unit/cli/test_quadlet_render.py tests/unit/cli/test_k8s_render.py -q
```

### Этап 5. Automation/docs gates

1. Watchlist audit подключить к `make audit-upstream`.
2. PN96 plan переписать под реальные v11 tools.
3. Markdown local path checker.
4. Docs migration map.

Acceptance:

```bash
make audit-upstream-offline
make docs-check
```

## 9. Итоговое решение

Локальная и серверная версии не конфликтуют по основному `sndr_core`, но конфликтуют по обвязке проекта: docs, PR workflow, engine boundary, benchmark harness, generated/runtime artifacts и internal/public разделение. Поэтому исправления надо делать не как "скопировать все с сервера" или "скопировать все локально", а как selective merge:

- `sndr_core`: сохранить текущий общий вариант и исправлять найденные shared P1/P2.
- `benchmarks/harness/run_all.py`: локальная версия правильнее.
- `.github/PULL_REQUEST_TEMPLATE.md`: локальная версия правильнее.
- `.pre-commit-config.yaml`: локальный файл нужен серверу, если сохраняется precommit workflow.
- `docs/WORK_LOG_2026-05-12_RU.md`: server-only public file убрать/перенести.
- `benchmarks/runs/*`, `.DS_Store`: server-only artifacts убрать или переместить internal.
- `sndr_engine`: принять явную policy. Без этого local/server будут постоянно расходиться и тесты будут давать разные expectations.

После этого можно переходить к коду: license, trust anchor, deploy emitters, doctor logs, watchlist automation, PN96 plan.
