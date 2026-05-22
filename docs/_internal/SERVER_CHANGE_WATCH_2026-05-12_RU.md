# Наблюдение за изменениями на сервере v11

Дата старта: 2026-05-12, Europe/Kiev.

Сервер: `sander@192.168.1.10`  
Рабочая папка: `/home/sander/genesis-vllm-patches-v11`  
Локальный журнал: `docs/_internal/SERVER_CHANGE_WATCH_2026-05-12_RU.md`

## Правила наблюдения

- Серверные файлы не изменять.
- Не останавливать, не пересоздавать и не перезапускать существующие Docker-сервисы без отдельного разрешения.
- GPU-проверки, если понадобятся, только короткие smoke/bench без длительной нагрузки.
- Все выводы фиксировать в этот журнал: что изменилось, какие риски появились, какие ошибки допускает другой агент, как бы я сделал безопаснее.
- Если изменения выглядят опасными, сначала фиксировать проблему и рекомендацию, а не вмешиваться в код.

## Стартовый baseline

Снимок снят с сервера `2026-05-12T04:03:52+03:00`.

| Область | Состояние |
| --- | --- |
| Git branch | `dev` |
| Git commit | `f9576df` |
| Рабочее дерево | грязное, много измененных/удаленных/новых файлов; проект находится в активной миграции |
| Основной runtime контейнер | `vllm-pn95-2xa5000`, образ `vllm/vllm-openai:nightly`, порт `8101`, контейнер запущен |
| Инфраструктурные контейнеры | `genesis-aggregator`, `genesis-proxy-v2`, MCP-сервисы запущены |
| Нестабильные контейнеры baseline | `nvidia-gpu-exporter` перезапускается; `docker-sandbox-1` перезапускается |
| `sndr_core` self-test | PASS: 8/8 |
| `apply.shadow --strict` | PASS: unexpected divergence нет, known spec-only: 8 |

Результат легкой проверки server-v11:

```text
version constant: pass, version 11.0.0
compat imports: pass, 19 compat modules import cleanly
wiring imports: pass, 122 wiring modules import cleanly
schema validator: pass, all 136 entries schema-clean
lifecycle audit: pass, 136 entries, no unknown lifecycle states
categories build: pass, 136 patches -> 18 categories
predicates evaluator: pass
schema file: pass

Legacy apply registrations: 133
Spec-driven entries: 136
Specs with apply_module: 123
Specs without apply_module: 13
CLEAN: no unexpected divergence
```

## Что считать ошибками другого агента

1. Изменение серверных файлов без сохранения понятного статуса: нет `git status`, нет списка измененных файлов, нет причины изменения.
2. Перенос файлов между `sndr_core` и `sndr_engine` без обновления импортов, registry, entrypoints, тестов и документации.
3. Возврат зависимости public-core от private-engine: прямые импорты `vllm.sndr_engine` из `vllm.sndr_core` без optional boundary.
4. Добавление hardcoded путей вида `/home/sander`, `/Users/sander`, `/models`, абсолютных Docker/socket путей без config/env fallback.
5. Замена рабочих guard-команд на декоративные проверки, которые не ловят registry/import/runtime ошибки.
6. Добавление shell-установщиков с неидемпотентными `sudo`, `curl | sh`, небезопасным удалением или перезаписью пользовательских конфигов.
7. Исправление тестов через ослабление assertions вместо исправления контракта.
8. Смешивание legacy `_genesis`, `sndr_core` и `sndr_engine` без явной миграционной карты.
9. Патчи без `apply_module`, без lifecycle/status, без источника, без теста или хотя бы acceptance-сценария.
10. Изменения runtime/launcher, которые ломают текущий Docker endpoint или model config совместимость.

## Как бы я вел изменения

1. Сначала фиксировать маленький batch: одна подсистема, один контракт, один набор тестов.
2. Перед изменением делать локальный diff и список затронутых entrypoints.
3. После изменения обязательно прогонять минимум:
   - `python3 -m vllm.sndr_core.compat.cli self-test --json`
   - `python3 -m vllm.sndr_core.apply.shadow --strict`
   - AST compile измененных `.py`
   - parse измененных `.yaml`, `.json`, `.toml`
   - `bash -n` измененных `.sh`
4. Для переносов `engine -> core` сначала создавать стабильный public API в `sndr_core`, потом переносить реализацию, потом удалять старый импорт.
5. Для installer/launcher/config не добавлять новый ad-hoc слой, а сводить к единому schema-driven flow: profile -> dependency check -> runtime plan -> apply/launch.
6. Для patch registry держать один источник правды: spec/registry должен объяснять номер патча, назначение, источник, lifecycle, dependency, target, тест.
7. Для production не принимать изменения без acceptance checklist и rollback notes.

## Журнал наблюдений

### 2026-05-12 04:03 EEST, baseline

Изменений другого агента после старта наблюдения еще не зафиксировано. Снят baseline server-v11.

Текущие риски baseline:

- Рабочее дерево на сервере уже сильно грязное. Любые дальнейшие изменения нужно оценивать диффом относительно текущего состояния, иначе легко перепутать старую миграцию с новыми правками.
- `self-test` и `apply.shadow --strict` сейчас зеленые. Если после следующих изменений они станут красными, это прямой сигнал regression в registry/import/apply-layer.
- `nvidia-gpu-exporter` и `docker-sandbox-1` уже перезапускаются на baseline; не считать это новой ошибкой другого агента без дополнительной корреляции по времени.

Моя рекомендация на текущий момент:

- Не принимать крупные переносы сразу. Сначала требовать от агента список файлов, цель batch, какие entrypoints меняются, какие тесты должны пройти.
- При каждом новом изменении сравнивать `git diff --name-status`, затем читать diff только измененных файлов, затем запускать легкие guard-команды.

### 2026-05-12 04:21 EEST, heartbeat #1

Server snapshot:

- branch: `dev`
- commit: `f9576df`
- `git status --short`: 522 записи
- status hash: `b0adbb8dbded0f41bebdd5b8ac3effc3cde5fe385372b93b6e9543a7ee1c158e`
- runtime: `vllm-pn95-2xa5000` запущен на `8101`
- baseline-нестабильность сохраняется: `nvidia-gpu-exporter` и `docker-sandbox-1` перезапускаются

Файлы, измененные после baseline `2026-05-12T04:03:52+03:00`:

- `vllm/sndr_core/integrations/attention/turboquant/pn26_sparse_v_kernel.py`
- `docs/_internal/WORK_LOG_2026-05-12_RU.md`
- `tests/legacy/test_model_config_audit_rules.py`
- `tests/unit/integrations/attention/gdn/test_pn59_streaming_gdn.py`
- `.pytest_cache/...` — служебный след тестов, не считать проектной правкой

Проверки:

- `python3 -m vllm.sndr_core.compat.cli self-test --json`: PASS, 8/8.
- `python3 -m vllm.sndr_core.apply.shadow --strict`: PASS, unexpected divergence нет.
- Write-free AST parse трех измененных `.py`: PASS.
- Targeted pytest по двум новым тестовым файлам: PASS, `50 passed in 1.78s`.
- `py_compile` как проверку не использую для серверного наблюдения: она пытается писать `.pyc` в `__pycache__` и на сервере уперлась в permission denied. Для режима "не менять серверные файлы" корректнее AST parse без записи.

Что сделал другой агент:

- Добавил/подготовил PN26 torch-less env-gate: `_pn26_env_enabled()` проверяет `GENESIS_ENABLE_PN26_SPARSE_V` до импорта kernel-модуля.
- Добавил/подготовил тесты для model config audit rules, R-018/R-019 и PN59 streaming GDN.
- Добавил server-side work log `docs/_internal/WORK_LOG_2026-05-12_RU.md`.

Ошибки и риски:

- [P1] `vllm/sndr_core/integrations/attention/turboquant/pn26_sparse_v_kernel.py`, `tests/legacy/test_model_config_audit_rules.py`, `tests/unit/integrations/attention/gdn/test_pn59_streaming_gdn.py` — файлы находятся в статусе `??`, то есть не отслеживаются git. Это опасно: важная PN26-правка и тесты могут быть потеряны, не попадут в diff/review/commit и не участвуют в обычной проверке миграции.
- [P2] `vllm/sndr_core/integrations/attention/turboquant/pn26_sparse_v_kernel.py:221` — log text все еще ссылается на старый путь `vllm._genesis.kernels...collect_skip_stats()`. После миграции в `sndr_core` это вводит оператора в заблуждение при debug-инструкциях.
- [P2] `vllm/sndr_core/integrations/attention/turboquant/pn26_sparse_v_kernel.py:198-205` и `:231-254` против `:321-325` — runtime-сообщение говорит, что dispatcher "routes when seq_len >= min_ctx" и использует `BLASST λ=a/L`, но текущий lean dispatcher всегда вызывает sparse kernel при enabled env, а adaptive scale при `_baked_scale > 0` фактически заменяется fixed threshold. Это несоответствие документации и реального поведения.
- [P2] `vllm/sndr_core/integrations/attention/turboquant/pn26_sparse_v_kernel.py:229` — `int(os.environ.get("GENESIS_PN26_SPARSE_V_LOG_EVERY", "500"))` без validation. Неверное значение env (`abc`, `0`, отрицательное) может сломать `apply()` или привести к некорректной периодике логов.
- [P2] `tests/unit/integrations/attention/gdn/test_pn59_streaming_gdn.py:17` — top-level `import torch`. Для torch-less CI/Mac-dev это превращает весь тестовый модуль в import failure. Если цель проекта сохранять torch-optional проверки, нужен `torch = pytest.importorskip("torch")` либо перенос импорта внутрь тестов с skip.
- [P3] `docs/_internal/WORK_LOG_2026-05-12_RU.md:28` — указано `5291 passed / 0 failed`, но рядом нет команды, commit/time и лога прогона. Для такого заявления нужен воспроизводимый контекст; иначе это выглядит как недоказанный статус, особенно на фоне прежнего full pytest red в server-v11.

Как бы я сделал:

- Сначала перевел бы эти три untracked файла в нормальный review-state: явно показать `git status --short -- <files>`, затем либо добавить в commit batch, либо перенести в отдельный patch-set. До этого считать изменения не закрепленными.
- В PN26 поправил бы сообщения и комментарии под фактический lean v2: "enabled env routes through sparse-V wrapper with fixed threshold; BLASST adaptive scale is not active in lean path".
- Для `GENESIS_PN26_SPARSE_V_LOG_EVERY` добавил бы helper:
  - parse int через `try/except`;
  - minimum `1`;
  - при invalid value логировать warning и использовать `500`.
- В PN59-тесте заменил бы top-level torch import на `pytest.importorskip("torch")`, чтобы тесты корректно пропускались в torch-less окружении.
- В work log требовал бы формат: команда, дата, commit, окружение, итог. Без этого строка `5291 passed / 0 failed` не должна использоваться как production-доказательство.

Решение:

- Текущий batch можно продолжать проверять, потому что guard-команды зеленые и targeted tests проходят.
- Перед принятием обязательно исправить untracked-state и PN26 текстовые несоответствия; это не P0 runtime crash, но это плохой engineering hygiene и риск потери изменений.

### 2026-05-12 04:36 EEST, heartbeat #2

Server snapshot:

- branch: `dev`
- commit: `f9576df`
- `git status --short`: 526 записей
- status hash: `fba84ab70484a636eed7d0ffcfcbce6d4d34d5a6c9e2fa6f06b152a58ed74163`
- runtime: `vllm-pn95-2xa5000` запущен на `8101`
- baseline-нестабильность сохраняется: `nvidia-gpu-exporter` и `docker-sandbox-1` перезапускаются

Файлы, измененные после heartbeat #1:

- `scripts/check_no_legacy_imports.sh`
- `Makefile`
- `vllm/sndr_core/license.py`
- `docs/security/TRUST_ANCHOR_CEREMONY.md`
- `tests/unit/test_trust_anchor_not_placeholder.py`
- `vllm/sndr_core/dispatcher/registry_metadata.py`
- `tests/unit/test_trust_anchor_generator.py`
- `vllm/sndr_core/dispatcher/spec.py`
- `tests/unit/dispatcher/test_spec_metadata_enrichment.py`
- `docs/_internal/WORK_LOG_2026-05-12_RU.md`

Проверки:

- `python3 -m vllm.sndr_core.compat.cli self-test --json`: PASS, 8/8.
- `python3 -m vllm.sndr_core.apply.shadow --strict`: PASS, unexpected divergence нет.
- AST parse измененных `.py`: PASS, 6 файлов.
- `bash -n scripts/check_no_legacy_imports.sh`: PASS.
- Targeted pytest trust/spec tests: PASS, `54 passed in 2.51s`.
- `tests/unit/test_license.py`: PASS, `24 passed, 1 skipped in 0.13s`.

Что сделал другой агент:

- Добавил `scripts/check_no_legacy_imports.sh` и Makefile-target `audit-legacy-imports`.
- Добавил Ed25519 trust anchor в `vllm/sndr_core/license.py` и ceremony-документ.
- Добавил тесты для trust anchor и генератора ключей.
- Добавил `dispatcher/registry_metadata.py` как metadata-overlay для `implementation_status`, `test_status`, `production_default`.
- Расширил `dispatcher/spec.py` под category/source/implementation_status inference.

Ошибки и риски:

- [P1] Все новые batch-файлы находятся в статусе `??`: `Makefile`, `scripts/check_no_legacy_imports.sh`, `scripts/generate_trust_anchor.py`, `vllm/sndr_core/license.py`, `vllm/sndr_core/dispatcher/spec.py`, `vllm/sndr_core/dispatcher/registry_metadata.py`, новые тесты и docs. Это главный операционный риск: изменения выглядят как "сделано", но git их не отслеживает, они могут не попасть в review/commit и исчезнуть при sync.
- [P1] `docs/_internal/WORK_LOG_2026-05-12_RU.md:91-93` и `scripts/generate_trust_anchor.py:172-176` — private key был показан в stdout сессии. Для production root-of-trust это слабое место: терминальные логи, shell history, recorder/scrollback или внешний агент могли сохранить private key. Если этот ключ реально должен быть production, его надо считать потенциально скомпрометированным и перегенерировать offline без вывода private key в общий stdout.
- [P1] `vllm/sndr_core/license.py:319-350` — после успешной подписи payload почти не валидируется. Отсутствующие или строковые `expires_at`, отсутствующий `customer_id`, отсутствующий `issued_at`, отсутствующий `engine_major` не блокируют токен. Докстринг выше описывает payload как `{customer_id, issued_at, expires_at, engine_major}`, значит runtime должен проверять обязательные поля и типы. Сейчас подписанный payload без срока действия может стать бессрочным.
- [P1] `vllm/sndr_core/dispatcher/registry_metadata.py:172-195` — `lifecycle=stable` автоматически превращается в `implementation_status=full` и `production_default=eligible`, даже если `test_status=none`. Work log показывает `production_default: eligible=120`, `test_status: none=91`. Это завышает production-готовность и может открыть патчи без тестового покрытия. Нужна более строгая политика: `eligible` только при `test_status != none` или explicit override.
- [P2] `docs/security/TRUST_ANCHOR_CEREMONY.md:74-85` и `:90` — документация ссылается на `verify_token`, но в `vllm/sndr_core/license.py` такой публичной функции нет. Реальная функция `_verify_signed_token` private. Документ нельзя оставлять как operational playbook с несуществующим API.
- [P2] `vllm/sndr_core/license.py:12-14` — верхний docstring говорит, что legacy non-empty string accepted with warning. Реальный код `:459-482` принимает legacy key только при `SNDR_ALLOW_LEGACY_LICENSE_KEYS=1`; иначе возвращает `BAD_SIGNATURE`. Документация устарела и может ввести оператора в ошибку.
- [P2] `scripts/generate_trust_anchor.py:179-182` — даже при `--out` private key уже напечатан строками `172-176`. Для production режим с `--out` должен по умолчанию не печатать private key, либо требовать явный `--print-private`.
- [P2] `scripts/check_no_legacy_imports.sh:78` — gate ловит только `vllm.sndr_core.patches.` с точкой в конце. Импорты вида `from vllm.sndr_core import patches` или `import vllm.sndr_core.patches as patches` не будут пойманы. Для реального CI-gate нужен AST/grep pattern шире.
- [P2] `scripts/check_no_legacy_imports.sh:54` — сканируются только `*.py`, `*.sh`, `*.md`; JSON/YAML/TOML, workflow files и generated docs не проверяются. Для запрета legacy namespace в активном проекте этого недостаточно, особенно при миграции registry/schema/config.
- [P3] `Makefile:28` — help ссылается на `docs/CONTRIBUTING.md`, который в текущем diff удален. Это мелкая, но видимая несостыковка operator UX.

Как бы я сделал:

- Сначала закрепил batch в git-aware state: явно решить, какие из `??` должны стать tracked, а какие временные. Без этого нельзя считать работу завершенной.
- Trust anchor:
  - считать ключ, показанный в stdout, dev/test ключом;
  - для production сделать новый offline ceremony;
  - поменять generator: `--out` не печатает private key по умолчанию, `--print-private` только явным флагом;
  - добавить тест: `--out --quiet` не содержит private key в stdout.
- License payload validation:
  - после JSON decode требовать `customer_id: str`, `issued_at: int|float`, `expires_at: int|float`, `engine_major: int`;
  - reject missing/non-numeric `expires_at`, expired token, future `issued_at` с разумным skew;
  - добавить unit tests для missing/invalid fields.
- Registry metadata:
  - не выводить `production_default=eligible` только из lifecycle;
  - использовать правило `stable + test_status != none -> eligible`, иначе `blocked` или `review_required`;
  - explicit overrides оставить, но сделать их audited list.
- Legacy import gate:
  - заменить regex-grep на маленький Python AST scanner для imports;
  - дополнительно grep для config/docs по `vllm._genesis` и `vllm.sndr_core.patches`;
  - добавить CI test на негативные fixtures.

Решение:

- Guard-проверки зеленые, batch не ломает текущий dispatcher/apply-layer.
- Принимать как production нельзя до исправления P1: untracked-state, trust-anchor stdout exposure, строгая validation license payload, и завышенный `production_default=eligible`.

### 2026-05-12 04:51 EEST, heartbeat #3

Server snapshot:

- branch: `dev`
- commit: `f9576df`
- `git status --short`: 527 записей
- status hash: `d1972080d594ff298eb8b54638e5d79817c4d2a62ae1cac346d0da2ac19a7922`
- runtime: `vllm-pn95-2xa5000` запущен на `8101`
- baseline-нестабильность сохраняется: `nvidia-gpu-exporter` и `docker-sandbox-1` перезапускаются

Файлы, измененные после heartbeat #2:

- `scripts/launch/README.md`
- `docs/INSTALL.md`
- `docs/CONTRIBUTING.md`
- `docs/WORK_LOG_2026-05-12_RU.md`
- `docs/_internal/WORK_LOG_2026-05-12_RU.md`
- `vllm/sndr_core/cli/doctor_logs.py`
- `vllm/sndr_core/cli/doctor_system.py`
- `tests/unit/cli/test_doctor_logs.py`
- `vllm/sndr_core/model_configs/schema.py`
- `tests/unit/model_configs/test_compatibility_matrix.py`

Проверки:

- `python3 -m vllm.sndr_core.compat.cli self-test --json`: PASS, 8/8.
- `python3 -m vllm.sndr_core.apply.shadow --strict`: PASS, unexpected divergence нет.
- AST parse измененных `.py`: PASS, 5 файлов.
- Targeted pytest: PASS, `46 passed in 0.20s`.
- `python3 -m vllm.sndr_core.cli doctor-system --logs --logs-hours 1 --json`: exit `2`, потому что log forensics нашел restarting containers (`nvidia-gpu-exporter`, `docker-sandbox-1`). Это совпадает с baseline, но новая команда теперь будет краснить host readiness на этих контейнерах.
- Builtin model config registry smoke: `a5000-2x-27b-dflash-true.yaml` теперь пропускается loader'ом из-за `COMPAT-001`; `list_keys()` возвращает 10 ключей без этого DFlash preset.

Что сделал другой агент:

- Добавил host log forensics: `doctor-system --logs`, парсинг OOM/Xid/restarting containers/journalctl.
- Добавил CompatibilityMatrix в `model_configs/schema.py` с правилами `COMPAT-001..004`.
- Обновил install/contributing/launch docs.
- Добавил публичный `docs/WORK_LOG_2026-05-12_RU.md` параллельно внутреннему `docs/_internal/WORK_LOG_2026-05-12_RU.md`.

Ошибки и риски:

- [P0] `vllm/sndr_core/model_configs/schema.py:1606-1623`, `:1685-1689` ломает существующий builtin config `vllm/sndr_core/model_configs/builtin/a5000-2x-27b-dflash-true.yaml:60-63` + `:91-97`. Правило `COMPAT-001` запрещает `spec_decode.method='dflash'` при `GENESIS_ENABLE_PN59_STREAMING_GDN=1`, а именно так устроен DFlash preset. Loader теперь пишет `skipping builtin/a5000-2x-27b-dflash-true.yaml — schema error` и этот preset исчезает из `list_keys()`. Это реальный functional regression, targeted tests его не покрыли.
- [P1] `vllm/sndr_core/model_configs/schema.py:1637-1638` и `:1691-1696` используют `GENESIS_ENABLE_P98_LONG_CTX_LOCK`, которого нет в registry/builtin. Реальный env-флаг P98 — `GENESIS_ENABLE_P98` (`vllm/sndr_core/dispatcher/registry.py:2286`, builtin YAML, `audit_rules.py`). Из-за этого `COMPAT-002` будет постоянно предупреждать даже когда P98 реально включен.
- [P1] Новые code/test files снова в статусе `??`: `vllm/sndr_core/cli/doctor_logs.py`, `doctor_system.py`, `model_configs/schema.py`, `tests/unit/cli/test_doctor_logs.py`, `tests/unit/model_configs/test_compatibility_matrix.py`, `docs/WORK_LOG_2026-05-12_RU.md`. Это повторяет риск прошлого heartbeat: функционально важные изменения не закреплены git-tracking.
- [P1] `docs/WORK_LOG_2026-05-12_RU.md:9`, `:33-51`, `:136` дублирует внутренний work log в публичной `docs/` и содержит серверный IP `192.168.1.10`, операционные детали и internal migration notes. Такой журнал должен оставаться только в `docs/_internal/`; в public docs это лишняя утечка инфраструктурного контекста.
- [P2] `vllm/sndr_core/cli/doctor_logs.py:191-193`, `:173-175`, `:275-282` — `_read_dmesg()` сначала вызывает `dmesg --ctime`, но timestamp parser умеет только uptime-формат `[12345.678]`. Для ctime-строк `timestamp_seconds_ago=None`, а `_filter_within_window()` включает `None` всегда. Итог: `--logs-hours` фактически не фильтрует OOM/Xid события при успешном `--ctime`.
- [P2] `vllm/sndr_core/cli/doctor_logs.py:132-139` и `:377-382` — любой restarting container делает `has_fatal_signals=True`. На текущем сервере это сразу краснит `doctor-system --logs`, хотя проблемные контейнеры baseline не относятся к vLLM runtime. Нужен allowlist/denylist или режим `--logs-container-prefix vllm|genesis`, иначе host readiness будет шумным.
- [P2] `docs/CONTRIBUTING.md:320` — снова жестко вшит `ssh sander@192.168.1.10`. Для public docs нужно `ssh <user>@<host>` или ссылка на host config.
- [P2] `docs/INSTALL.md:348`, `:511-516` — hardcoded `/home/sander/...`, `User=sander`, `ExecStart=/home/sander/run-genesis.sh` в install guide. Для community install это нужно заменить на placeholders/env (`$USER`, `$GENESIS_HOME`, `$VLLM_DIR`) или явно пометить как example.
- [P2] `scripts/launch/README.md:146-147` ссылается на `snapshot_pre_arm.sh` и `nsight_profile_capture.sh`, которые в текущем diff удалены. Документация указывает на несуществующие utility scripts.
- [P2] `scripts/launch/README.md:112-113` говорит, что bare-metal script symlinks Genesis `_genesis`, хотя v11 canonical namespace — `vllm.sndr_core`. Это противоречит строкам `10-12` того же файла.
- [P3] `docs/INSTALL.md:573` продолжает рекламировать `_genesis` back-compat как troubleshooting path. Если цель v11 — убрать верхние зависимости и legacy-пути, public install docs должны вести только через `sndr_core`, а `_genesis` оставить в migration appendix.

Как бы я сделал:

- Для CompatibilityMatrix:
  - поменять `COMPAT-001` с hard forbidden на более точное правило: проверять реальную модель/архитектуру, а не `PN59` env как единственный сигнал; либо сделать exception для `a5000-2x-27b-dflash-true` до эмпирической проверки;
  - добавить тест "all builtin configs load and validate" и отдельный test, что `a5000-2x-27b-dflash-true` остается в `list_keys()`;
  - заменить `GENESIS_ENABLE_P98_LONG_CTX_LOCK` на `GENESIS_ENABLE_P98` в schema/tests/docs.
- Для doctor logs:
  - либо читать `dmesg` без `--ctime` для корректного uptime-window, либо парсить ctime в epoch;
  - добавить контейнерный filter: по умолчанию считать fatal только контейнеры с именами `vllm*`, `genesis*`, либо дать `--logs-all-containers`;
  - tests должны покрывать ctime-window и unrelated restarting container.
- Для docs:
  - убрать public `docs/WORK_LOG_2026-05-12_RU.md` или перенести его только в `_internal`;
  - заменить `sander@192.168.1.10` и `/home/sander/...` на placeholders;
  - обновить `scripts/launch/README.md` под фактический набор файлов после удаления utility scripts.
- Для git hygiene:
  - до следующего batch закрепить новые файлы как tracked или явно удалить временные; иначе дальнейший audit будет путать "новую работу" и "неучтенный мусор".

Решение:

- Этот batch нельзя принимать без правок: есть P0 regression по builtin DFlash preset и P1 mismatch P98 env.
- Guard-команды зеленые, но они не ловят model config registry regression. Нужно добавить отдельный gate для загрузки всех builtin configs.

### 2026-05-12 05:06 EEST, heartbeat #4

Server snapshot:

- branch: `dev`
- commit: `f9576df`
- `git status --short`: 527 записей
- status hash: `d1972080d594ff298eb8b54638e5d79817c4d2a62ae1cac346d0da2ac19a7922`
- runtime: `vllm-pn95-2xa5000` запущен; baseline restart-loop сохраняется для `nvidia-gpu-exporter` и `docker-sandbox-1`

Важно: status hash не изменился, но изменились mtimes и содержимое untracked-файлов. Это ожидаемо, потому что hash строится по `git status --short`, а не по содержимому `??` файлов. Пока новые файлы не tracked, такой контроль не ловит правки внутри них.

Файлы, измененные после heartbeat #3:

- `vllm/sndr_core/cli/compose.py`
- `vllm/sndr_core/cli/quadlet.py`
- `vllm/sndr_core/cli/k8s.py`
- `vllm/sndr_core/cli/__init__.py`
- `vllm/sndr_core/model_configs/schema.py`
- `tests/unit/cli/test_compose_render.py`
- `tests/unit/cli/test_quadlet_render.py`
- `tests/unit/cli/test_k8s_render.py`
- `tests/unit/model_configs/test_compatibility_matrix.py`
- `docs/_internal/WORK_LOG_2026-05-12_RU.md`

Что сделал другой агент:

- Добавил CLI-команды `compose`, `quadlet`, `k8s` в `vllm.sndr_core.cli`.
- Добавил генераторы Docker Compose, Podman Quadlet и Kubernetes manifests из модельных профилей.
- Расширил schema/config слой новыми runtime-полями для deploy/render.
- Добавил unit-тесты render-path для compose/quadlet/k8s.
- Исправил предыдущий P0 по `COMPAT-001`: `a5000-2x-27b-dflash-true` снова присутствует в builtin registry, DFlash + streaming GDN больше не блокируется глобально.

Проверки:

- `python3 -m vllm.sndr_core.compat.cli self-test --json`: PASS, 8/8.
- `python3 -m vllm.sndr_core.apply.shadow --strict`: PASS, `CLEAN`.
- AST parse новых Python-файлов: PASS.
- Targeted pytest: PASS, `53 passed in 0.26s`.
- CLI registration smoke: `compose`, `quadlet`, `k8s` отображаются в `python3 -m vllm.sndr_core.cli --help`.
- Builtin registry smoke: `list_keys()` возвращает 11 builtin профилей, включая `a5000-2x-27b-dflash-true` и `a5000-2x-27b-int4-tq-k8v4-dflash`.
- Render smoke для `a5000-2x-35b-prod`: Compose YAML парсится как dict, Quadlet render выполняется, K8s для этого профиля ожидаемо не рендерится из-за отсутствия `k8s` блока.

Ошибки и риски:

- [P1] Новая deploy-функциональность остается untracked: `vllm/sndr_core/cli/compose.py`, `quadlet.py`, `k8s.py`, `schema.py`, `tests/unit/cli/*`, `tests/unit/model_configs/test_compatibility_matrix.py`. Последствие: diff-review и status hash не видят содержимое этих файлов. Как бы я сделал: либо сразу добавить эти файлы в staging/commit после ревью, либо для watch-режима дополнительно считать sha256 содержимого всех `??` файлов.
- [P1] `vllm/sndr_core/cli/compose.py:226-229`, `:301-309` — Compose render может утекать API key в предсказуемый `/tmp`. Код добавляет `VLLM_API_KEY` в `environment`, затем `compose up` пишет полный YAML в фиксированный путь вида `/tmp/sndr-compose/docker-compose.<key>.yml`. Как бы я сделал: не писать секреты в generated compose, использовать `.env`/Docker secrets, создавать tempdir с mode `0700`, либо передавать `--env-file`.
- [P2] `vllm/sndr_core/cli/compose.py:141-185` расходится с canonical command builder из `vllm/sndr_core/model_configs/schema.py:2260-2287`. Compose/Quadlet строят `["vllm", "serve", cfg.model_path]` и не добавляют `--language-model-only`, хотя canonical path использует `vllm serve --model <path>` и учитывает `language_model_only`. Последствие: один и тот же профиль может запускаться по-разному через launcher и через deploy render. Как бы я сделал: вынести единый command builder и использовать его во всех runtime adapters.
- [P2] `vllm/sndr_core/cli/compose.py:120-138` — symbolic mounts резолвятся ручной заменой `${key}` и silently оставляют нерешенные placeholders. В `schema.py` уже есть строгая логика symbolic mount validation/resolution. Как бы я сделал: использовать один resolver из schema/env слоя, а не локальный string replacement.
- [P2] `vllm/sndr_core/cli/quadlet.py:164-166` — `Environment={k}={v}` и `Exec=...` формируются без escaping/quoting. Значения с пробелами, кавычками, переводами строк или спецсимволами могут сломать unit-файл. Как бы я сделал: генерировать environment file с ограниченными правами, валидировать env keys, экранировать значения по правилам systemd/quadlet.
- [P2] `vllm/sndr_core/cli/k8s.py:126-142`, `:191-243` — Kubernetes YAML строится строковой конкатенацией через f-string/`repr`, без централизованной YAML-валидации имен, label keys, mount paths и значений. Как бы я сделал: строить Python dict-объекты и выводить через `yaml.safe_dump_all`, плюс валидировать DNS-1123 names, absolute mountPath, PVC size, secret names.
- [P2] `vllm/sndr_core/model_configs/schema.py:415-447` — новые k8s/deploy-поля почти не валидируются: `node_selector`, `pvc`, `pvc_size_gib`, `secret_mounts`, resource keys, абсолютность mount paths. Последствие: ошибки попадут в cluster/runtime вместо `model config validate`.
- [P2] `vllm/sndr_core/cli/k8s.py:377-383` — `k8s delete` удаляет deployment/service/configmap, но не удаляет PVC, которые создает `_pvc_yaml()`. Это может быть deliberate data-preserve, но тогда нужно явно написать в help/docs и добавить `--delete-pvc`.

Как бы я сделал:

- Ввести единый `RuntimeCommandSpec`: одна функция строит `vllm serve` argv для bare-metal, compose, quadlet и k8s.
- Вынести mount resolution в один строгий resolver и запретить unresolved `${...}` до render/apply.
- Перевести deploy emitters на dict + `yaml.safe_dump_all`; string templates оставить только для systemd/quadlet после escaping.
- Сделать secret handling отдельным слоем: Docker secrets/env-file/K8s Secret refs, без записи ключей в `/tmp`.
- Добавить negative tests: invalid DNS name, unresolved mount placeholder, env value with newline, PVC delete policy, missing `--language-model-only`.

Решение:

- Направление правильное: единые модельные профили начинают управлять Compose/Quadlet/K8s.
- Предыдущий P0 по DFlash preset исправлен.
- Принимать deploy-ветку как production-ready нельзя до исправления P1/P2 по secrets, command parity, mount resolver, YAML emitter и schema validation.

### 2026-05-12 05:21 EEST, heartbeat #5

Server snapshot:

- branch: `dev`
- commit: `f9576df`
- `git status --short`: 528 записей
- status hash: `91f5c7476927311fe016d9eb0f58e68a40c3579c6750ac84e3ad0cd89920cb1c`
- runtime: `vllm-pn95-2xa5000` продолжает работать; baseline restart-loop сохраняется для `nvidia-gpu-exporter` и `docker-sandbox-1`

Файлы, измененные после heartbeat #4:

- `docs/upstream/UPSTREAM_WATCHLIST.yaml`
- `docs/_internal/research/upstream_42102_dflash_independent_kv_groups_plan_2026-05-12.md`
- `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md`
- `docs/_internal/WORK_LOG_2026-05-12_RU.md`

Что сделал другой агент:

- Добавил upstream watchlist entry для `vllm#42102` как DFlash + quantized target KV backport candidate.
- Создал research/backport plan для #42102 с PN94/PN95b и retire candidates PN38/PN40.
- Создал PN96 A/B bench plan для 35B PROD с gated execution и downtime warning.
- Обновил внутренний work log, где заявлено закрытие S4.1/S5.1/S5.2 и commit-ready state.

Проверки:

- `python3 -m vllm.sndr_core.compat.cli self-test --json`: PASS, 8/8.
- `python3 -m vllm.sndr_core.apply.shadow --strict`: PASS, `CLEAN`.
- `docs/upstream/UPSTREAM_WATCHLIST.yaml`: YAML parse PASS, root keys `watch`, `__sentinel__`; `watch` содержит 17 entries; sentinel `complete`.
- `python3 scripts/audit_upstream_status.py --skip-network --json`: PASS, возвращает 57 registry-driven patch rows.
- GPU bench не запускался; Docker не перезапускался.

Ошибки и риски:

- [P1] `docs/upstream/UPSTREAM_WATCHLIST.yaml:19-26` утверждает, что `tools/check_upstream_drift.py` читает этот YAML и эмитит WARN/PORT_CANDIDATE/RETIRE_CANDIDATE/DRIFT. Фактический `tools/check_upstream_drift.py:304-380` вообще не загружает `UPSTREAM_WATCHLIST.yaml`: он проверяет anchors и `UPSTREAM_MARKERS`. `Makefile:51-55` для `audit-upstream` вызывает `scripts/audit_upstream_status.py`, а `scripts/audit_upstream_status.py:75-78` читает только `vllm/sndr_core/dispatcher/registry.py`. Последствие: новый watchlist не является рабочей автоматизацией, а только документом; `vllm#42102` не будет пойман `make audit-upstream`.
- [P1] `docs/_internal/research/upstream_42102_dflash_independent_kv_groups_plan_2026-05-12.md:83` говорит, что trigger придет через `make audit-upstream`, но текущая команда не читает watchlist и не знает про `vllm#42102`, если номер не записан в patch registry. Последствие: backport trigger для PN94/PN95b пропускается автоматически.
- [P2] `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md:21`, `:41`, `:57-58` ссылается на `scripts/launch/snapshot_pre_arm.sh` и `scripts/launch/start_35b_fp8_PROD.sh`, которых в текущем v11 tree нет (`find scripts/launch` показывает только `README.md` и `preflight_check.sh`). Последствие: plan ready-to-execute фактически не исполняется без ручной реконструкции команд.
- [P2] `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md:34`, `:52` использует `tools/run_stress.py`, которого в tree нет. Есть `tools/soak.sh`, `tools/openai_smoke.py`, `tools/genesis_bench_suite.py`, но указанного stress runner нет. Последствие: Phase A/C ломаются.
- [P2] `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md:40-45`, `:57-60`, `:88-89` содержит destructive/runtime-mutating команды (`docker stop`, restart, `rm -rf` cache). Сам файл правильно пишет, что нужен explicit go-ahead, но если его скопировать как runbook без дополнительного guard, он легко нарушит запрет не останавливать production. Нужен явный header `DO NOT RUN WITHOUT OPERATOR APPROVAL` и dry-run/snapshot substitute.
- [P2] `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md:16`, `:82` требует обновить `tests/integration/baselines/35b_v11_wave9.json`, но текущая heartbeat-инструкция запрещает изменять серверные tracked файлы. Это нормально как будущий план, но work log не должен формулировать S5.1 как закрытый implementation item.
- [P2] `docs/_internal/WORK_LOG_2026-05-12_RU.md` заявляет final state `commit-ready`, `P0/P1 closed` и `Server: 5413 passed / 0 failed`, но текущий repo остается с 528 dirty status entries и новые automation docs не wired в actual scripts. Последствие: статус завышен; для release/commit readiness нужен отдельный gate по tracked/untracked state и watchlist integration.
- [P3] `docs/upstream/UPSTREAM_WATCHLIST.yaml:1-218` новый файл остается `??`. Для public upstream automation data это хуже, чем для временного internal plan: пока файл untracked, CI и docs checks не гарантируют его наличие.

Как бы я сделал:

- Для watchlist:
  - добавить `scripts/audit_upstream_watchlist.py` или расширить `scripts/audit_upstream_status.py` так, чтобы он читал `docs/upstream/UPSTREAM_WATCHLIST.yaml`;
  - валидировать schema: root `watch`, allowed `action`, allowed `status`, `upstream` format (`vllm#N` или `owner/repo#N`), non-empty `since`, sentinel;
  - `make audit-upstream` должен объединять registry audit + watchlist audit и отдельно показывать `PORT_CANDIDATE` для `action=port`.
- Для #42102:
  - пока автоматизация не подключена, добавить временный registry/meta item или CI check, который явно проверяет `vllm#42102`;
  - не писать в плане, что trigger работает через `make audit-upstream`, пока это не реализовано.
- Для PN96 plan:
  - заменить удаленные `snapshot_pre_arm.sh` и `start_35b_fp8_PROD.sh` на v11 canonical launcher/model-config команды;
  - заменить `tools/run_stress.py` на существующий `tools/soak.sh` или добавить stress tool отдельным PR;
  - вынести destructive steps в отдельный `operator-only` блок с явным `--i-understand-downtime`/manual confirmation.
- Для readiness:
  - не использовать `commit-ready` до проверки `git status`, tracked state, docs automation wiring и runnable runbooks.

Решение:

- Guard-проверки зеленые, runtime не сломан.
- Новые документы полезны как направление, но содержат P1 рассинхрон: watchlist описан как автоматизация, но фактически не подключен к `make audit-upstream`.
- PN96 plan пока нельзя считать ready-to-execute: в нем есть ссылки на отсутствующие v11 scripts/tools.

### 2026-05-12 05:36 EEST, heartbeat #6

Server snapshot:

- branch: `dev`
- commit: `f9576df`
- `git status --short`: 528 записей
- status hash: `91f5c7476927311fe016d9eb0f58e68a40c3579c6750ac84e3ad0cd89920cb1c`
- runtime: `vllm-pn95-2xa5000` продолжает работать; baseline restart-loop сохраняется для `nvidia-gpu-exporter` и `docker-sandbox-1`

Файлы, измененные после heartbeat #5:

- Новых файлов по mtime после `2026-05-12 05:21:09` не найдено.
- `git status` и status hash не изменились.

Проверки:

- `python3 -m vllm.sndr_core.compat.cli self-test --json`: PASS, 8/8.
- `python3 -m vllm.sndr_core.apply.shadow --strict`: PASS, `CLEAN`.
- GPU bench не запускался; Docker не перезапускался.

Ошибки и риски:

- Новых regressions не обнаружено.
- Открытыми остаются риски из heartbeat #5:
  - `docs/upstream/UPSTREAM_WATCHLIST.yaml` пока не подключен к `make audit-upstream`;
  - `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md` содержит ссылки на отсутствующие v11 scripts/tools;
  - dirty/untracked state остается большим и снижает надежность snapshot-аудита.

Решение:

- Новых действий от другого агента нет.
- Наблюдение продолжать; при следующем изменении снова проверять только relevant diff/файлы.

### 2026-05-12 05:51 EEST, heartbeat #7

Server snapshot:

- branch: `dev`
- commit: `f9576df`
- `git status --short`: 528 записей
- status hash: `91f5c7476927311fe016d9eb0f58e68a40c3579c6750ac84e3ad0cd89920cb1c`
- runtime: `vllm-pn95-2xa5000` продолжает работать; baseline restart-loop сохраняется для `nvidia-gpu-exporter` и `docker-sandbox-1`

Файлы, измененные после heartbeat #6:

- Новых файлов по mtime после `2026-05-12 05:36:04` не найдено.
- `git status` и status hash не изменились.

Проверки:

- `python3 -m vllm.sndr_core.compat.cli self-test --json`: PASS, 8/8.
- `python3 -m vllm.sndr_core.apply.shadow --strict`: PASS, `CLEAN`.
- GPU bench не запускался; Docker не перезапускался.

Ошибки и риски:

- Новых regressions не обнаружено.
- Открытыми остаются риски из heartbeat #5:
  - `docs/upstream/UPSTREAM_WATCHLIST.yaml` пока не подключен к `make audit-upstream`;
  - `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md` содержит ссылки на отсутствующие v11 scripts/tools;
  - dirty/untracked state остается большим и снижает надежность snapshot-аудита.

Решение:

- Новых действий от другого агента нет.
- Наблюдение продолжать.

### 2026-05-12 06:06 EEST, heartbeat #8

Server snapshot:

- branch: `dev`
- commit: `f9576df`
- `git status --short`: 528 записей
- status hash: `91f5c7476927311fe016d9eb0f58e68a40c3579c6750ac84e3ad0cd89920cb1c`
- runtime: `vllm-pn95-2xa5000` продолжает работать; baseline restart-loop сохраняется для `nvidia-gpu-exporter` и `docker-sandbox-1`

Файлы, измененные после heartbeat #7:

- Новых файлов по mtime после `2026-05-12 05:51:07` не найдено.
- `git status` и status hash не изменились.

Проверки:

- `python3 -m vllm.sndr_core.compat.cli self-test --json`: PASS, 8/8.
- `python3 -m vllm.sndr_core.apply.shadow --strict`: PASS, `CLEAN`.
- GPU bench не запускался; Docker не перезапускался.

Ошибки и риски:

- Новых regressions не обнаружено.
- Открытыми остаются риски из heartbeat #5:
  - `docs/upstream/UPSTREAM_WATCHLIST.yaml` пока не подключен к `make audit-upstream`;
  - `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md` содержит ссылки на отсутствующие v11 scripts/tools;
  - dirty/untracked state остается большим и снижает надежность snapshot-аудита.

Решение:

- Новых действий от другого агента нет.
- Наблюдение продолжать.

### 2026-05-12 06:21 EEST, heartbeat #9

Server snapshot:

- branch: `dev`
- commit: `f9576df`
- `git status --short`: 528 записей
- status hash: `91f5c7476927311fe016d9eb0f58e68a40c3579c6750ac84e3ad0cd89920cb1c`
- runtime: `vllm-pn95-2xa5000` продолжает работать; baseline restart-loop сохраняется для `nvidia-gpu-exporter` и `docker-sandbox-1`

Файлы, измененные после heartbeat #8:

- Новых файлов по mtime после `2026-05-12 06:06:10` не найдено.
- `git status` и status hash не изменились.

Проверки:

- `python3 -m vllm.sndr_core.compat.cli self-test --json`: PASS, 8/8.
- `python3 -m vllm.sndr_core.apply.shadow --strict`: PASS, `CLEAN`.
- GPU bench не запускался; Docker не перезапускался.

Ошибки и риски:

- Новых regressions не обнаружено.
- Открытыми остаются риски из heartbeat #5:
  - `docs/upstream/UPSTREAM_WATCHLIST.yaml` пока не подключен к `make audit-upstream`;
  - `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md` содержит ссылки на отсутствующие v11 scripts/tools;
  - dirty/untracked state остается большим и снижает надежность snapshot-аудита.

Решение:

- Новых действий от другого агента нет.
- Наблюдение продолжать.

### 2026-05-12 06:36 EEST, heartbeat #10

Server snapshot:

- branch: `dev`
- commit: `f9576df`
- `git status --short`: 528 записей
- status hash: `91f5c7476927311fe016d9eb0f58e68a40c3579c6750ac84e3ad0cd89920cb1c`
- runtime: `vllm-pn95-2xa5000` продолжает работать; baseline restart-loop сохраняется для `nvidia-gpu-exporter` и `docker-sandbox-1`

Файлы, измененные после heartbeat #9:

- Новых файлов по mtime после `2026-05-12 06:21:11` не найдено.
- `git status` и status hash не изменились.

Проверки:

- `python3 -m vllm.sndr_core.compat.cli self-test --json`: PASS, 8/8.
- `python3 -m vllm.sndr_core.apply.shadow --strict`: PASS, `CLEAN`.
- GPU bench не запускался; Docker не перезапускался.

Ошибки и риски:

- Новых regressions не обнаружено.
- Открытыми остаются риски из heartbeat #5:
  - `docs/upstream/UPSTREAM_WATCHLIST.yaml` пока не подключен к `make audit-upstream`;
  - `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md` содержит ссылки на отсутствующие v11 scripts/tools;
  - dirty/untracked state остается большим и снижает надежность snapshot-аудита.

Решение:

- Новых действий от другого агента нет.
- Наблюдение продолжать.

### 2026-05-12 06:51 EEST, heartbeat #11

Server snapshot:

- branch: `dev`
- commit: `f9576df`
- `git status --short`: 528 записей
- status hash: `91f5c7476927311fe016d9eb0f58e68a40c3579c6750ac84e3ad0cd89920cb1c`
- runtime: `vllm-pn95-2xa5000` продолжает работать; baseline restart-loop сохраняется для `nvidia-gpu-exporter` и `docker-sandbox-1`

Файлы, измененные после heartbeat #10:

- Новых файлов по mtime после `2026-05-12 06:36:07` не найдено.
- `git status` и status hash не изменились.

Проверки:

- `python3 -m vllm.sndr_core.compat.cli self-test --json`: PASS, 8/8.
- `python3 -m vllm.sndr_core.apply.shadow --strict`: PASS, `CLEAN`.
- GPU bench не запускался; Docker не перезапускался.

Ошибки и риски:

- Новых regressions не обнаружено.
- Открытыми остаются риски из heartbeat #5:
  - `docs/upstream/UPSTREAM_WATCHLIST.yaml` пока не подключен к `make audit-upstream`;
  - `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md` содержит ссылки на отсутствующие v11 scripts/tools;
  - dirty/untracked state остается большим и снижает надежность snapshot-аудита.

Решение:

- Новых действий от другого агента нет.
- Наблюдение продолжать.

### 2026-05-12 07:06 EEST, heartbeat #12

Server snapshot:

- branch: `dev`
- commit: `f9576df`
- `git status --short`: 528 записей
- status hash: `91f5c7476927311fe016d9eb0f58e68a40c3579c6750ac84e3ad0cd89920cb1c`
- runtime: `vllm-pn95-2xa5000` продолжает работать; baseline restart-loop сохраняется для `nvidia-gpu-exporter` и `docker-sandbox-1`

Файлы, измененные после heartbeat #11:

- Новых файлов по mtime после `2026-05-12 06:51:07` не найдено.
- `git status` и status hash не изменились.

Проверки:

- `python3 -m vllm.sndr_core.compat.cli self-test --json`: PASS, 8/8.
- `python3 -m vllm.sndr_core.apply.shadow --strict`: PASS, `CLEAN`.
- GPU bench не запускался; Docker не перезапускался.

Ошибки и риски:

- Новых regressions не обнаружено.
- Открытыми остаются риски из heartbeat #5:
  - `docs/upstream/UPSTREAM_WATCHLIST.yaml` пока не подключен к `make audit-upstream`;
  - `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md` содержит ссылки на отсутствующие v11 scripts/tools;
  - dirty/untracked state остается большим и снижает надежность snapshot-аудита.

Решение:

- Новых действий от другого агента нет.
- Наблюдение продолжать.

### 2026-05-12 07:21 EEST, heartbeat #13

Server snapshot:

- branch: `dev`
- commit: `f9576df`
- `git status --short`: 528 записей
- status hash: `91f5c7476927311fe016d9eb0f58e68a40c3579c6750ac84e3ad0cd89920cb1c`
- runtime: `vllm-pn95-2xa5000` продолжает работать; baseline restart-loop сохраняется для `nvidia-gpu-exporter` и `docker-sandbox-1`

Файлы, измененные после heartbeat #12:

- Новых файлов по mtime после `2026-05-12 07:06:04` не найдено.
- `git status` и status hash не изменились.

Проверки:

- `python3 -m vllm.sndr_core.compat.cli self-test --json`: PASS, 8/8.
- `python3 -m vllm.sndr_core.apply.shadow --strict`: PASS, `CLEAN`.
- GPU bench не запускался; Docker не перезапускался.

Ошибки и риски:

- Новых regressions не обнаружено.
- Открытыми остаются риски из heartbeat #5:
  - `docs/upstream/UPSTREAM_WATCHLIST.yaml` пока не подключен к `make audit-upstream`;
  - `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md` содержит ссылки на отсутствующие v11 scripts/tools;
  - dirty/untracked state остается большим и снижает надежность snapshot-аудита.

Решение:

- Новых действий от другого агента нет.
- Наблюдение продолжать.

### 2026-05-12 07:36 EEST, heartbeat #14

Server snapshot:

- branch: `dev`
- commit: `f9576df`
- `git status --short`: 528 записей
- status hash: `91f5c7476927311fe016d9eb0f58e68a40c3579c6750ac84e3ad0cd89920cb1c`
- runtime: `vllm-pn95-2xa5000` продолжает работать; baseline restart-loop сохраняется для `nvidia-gpu-exporter` и `docker-sandbox-1`

Файлы, измененные после heartbeat #13:

- Новых файлов по mtime после `2026-05-12 07:21:06` не найдено.
- `git status` и status hash не изменились.

Проверки:

- `python3 -m vllm.sndr_core.compat.cli self-test --json`: PASS, 8/8.
- `python3 -m vllm.sndr_core.apply.shadow --strict`: PASS, `CLEAN`.
- GPU bench не запускался; Docker не перезапускался.

Ошибки и риски:

- Новых regressions не обнаружено.
- Открытыми остаются риски из heartbeat #5:
  - `docs/upstream/UPSTREAM_WATCHLIST.yaml` пока не подключен к `make audit-upstream`;
  - `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md` содержит ссылки на отсутствующие v11 scripts/tools;
  - dirty/untracked state остается большим и снижает надежность snapshot-аудита.

Решение:

- Новых действий от другого агента нет.
- Наблюдение продолжать.

### 2026-05-12 07:51 EEST, heartbeat #15

Server snapshot:

- branch: `dev`
- commit: `f9576df`
- `git status --short`: 528 записей
- status hash: `91f5c7476927311fe016d9eb0f58e68a40c3579c6750ac84e3ad0cd89920cb1c`
- runtime: `vllm-pn95-2xa5000` продолжает работать; baseline restart-loop сохраняется для `nvidia-gpu-exporter` и `docker-sandbox-1`

Файлы, измененные после heartbeat #14:

- Новых файлов по mtime после `2026-05-12 07:36:06` не найдено.
- `git status` и status hash не изменились.

Проверки:

- `python3 -m vllm.sndr_core.compat.cli self-test --json`: PASS, 8/8.
- `python3 -m vllm.sndr_core.apply.shadow --strict`: PASS, `CLEAN`.
- GPU bench не запускался; Docker не перезапускался.

Ошибки и риски:

- Новых regressions не обнаружено.
- Открытыми остаются риски из heartbeat #5:
  - `docs/upstream/UPSTREAM_WATCHLIST.yaml` пока не подключен к `make audit-upstream`;
  - `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md` содержит ссылки на отсутствующие v11 scripts/tools;
  - dirty/untracked state остается большим и снижает надежность snapshot-аудита.

Решение:

- Новых действий от другого агента нет.
- Наблюдение продолжать.

### 2026-05-12 08:06 EEST, heartbeat #16

Server snapshot:

- branch: `dev`
- commit: `f9576df`
- `git status --short`: 528 записей
- status hash: `91f5c7476927311fe016d9eb0f58e68a40c3579c6750ac84e3ad0cd89920cb1c`
- runtime: `vllm-pn95-2xa5000` продолжает работать; baseline restart-loop сохраняется для `nvidia-gpu-exporter` и `docker-sandbox-1`

Файлы, измененные после heartbeat #15:

- Новых файлов по mtime после `2026-05-12 07:51:04` не найдено.
- `git status` и status hash не изменились.

Проверки:

- `python3 -m vllm.sndr_core.compat.cli self-test --json`: PASS, 8/8.
- `python3 -m vllm.sndr_core.apply.shadow --strict`: PASS, `CLEAN`.
- GPU bench не запускался; Docker не перезапускался.

Ошибки и риски:

- Новых regressions не обнаружено.
- Открытыми остаются риски из heartbeat #5:
  - `docs/upstream/UPSTREAM_WATCHLIST.yaml` пока не подключен к `make audit-upstream`;
  - `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md` содержит ссылки на отсутствующие v11 scripts/tools;
  - dirty/untracked state остается большим и снижает надежность snapshot-аудита.

Решение:

- Новых действий от другого агента нет.
- Наблюдение продолжать.

### 2026-05-12 08:21 EEST, heartbeat #17

Server snapshot:

- branch: `dev`
- commit: `f9576df`
- `git status --short`: 528 записей
- status hash: `91f5c7476927311fe016d9eb0f58e68a40c3579c6750ac84e3ad0cd89920cb1c`
- runtime: `vllm-pn95-2xa5000` продолжает работать; baseline restart-loop сохраняется для `nvidia-gpu-exporter` и `docker-sandbox-1`

Файлы, измененные после heartbeat #16:

- Новых файлов по mtime после `2026-05-12 08:06:07` не найдено.
- `git status` и status hash не изменились.

Проверки:

- `python3 -m vllm.sndr_core.compat.cli self-test --json`: PASS, 8/8.
- `python3 -m vllm.sndr_core.apply.shadow --strict`: PASS, `CLEAN`.
- GPU bench не запускался; Docker не перезапускался.

Ошибки и риски:

- Новых regressions не обнаружено.
- Открытыми остаются риски из heartbeat #5:
  - `docs/upstream/UPSTREAM_WATCHLIST.yaml` пока не подключен к `make audit-upstream`;
  - `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md` содержит ссылки на отсутствующие v11 scripts/tools;
  - dirty/untracked state остается большим и снижает надежность snapshot-аудита.

Решение:

- Новых действий от другого агента нет.
- Наблюдение продолжать.

## Шаблон следующих записей

```text
### YYYY-MM-DD HH:MM EEST

Измененные файлы:
- ...

Что сделал другой агент:
- ...

Проверки:
- ...

Ошибки/риски:
- [P0/P1/P2/P3] файл:строка — проблема, последствие.

Как бы я сделал:
- ...

Решение:
- принять / просить переделать / откатить / проверить дополнительно.
```

## Команды наблюдения

Безопасные команды, которые можно выполнять периодически:

```bash
ssh sander@192.168.1.10 'cd /home/sander/genesis-vllm-patches-v11 && date -Is && git rev-parse --short HEAD && git branch --show-current && git status --short'
ssh sander@192.168.1.10 'cd /home/sander/genesis-vllm-patches-v11 && python3 -m vllm.sndr_core.compat.cli self-test --json'
ssh sander@192.168.1.10 'cd /home/sander/genesis-vllm-patches-v11 && python3 -m vllm.sndr_core.apply.shadow --strict'
ssh sander@192.168.1.10 'docker ps --format "{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}"'
```
