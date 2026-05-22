# Server v11: очередь исправлений и незакрытых задач

Дата: 2026-05-12  
Локальная база: `/Users/sander/Documents/Visual Studio Code/genesis-vllm-patches`  
Серверная база: `sander@192.168.1.10:/home/sander/genesis-vllm-patches-v11`  
Источник: `docs/_internal/SERVER_CHANGE_WATCH_2026-05-12_RU.md` + актуальный read-only snapshot сервера.

## Текущее состояние

Последний проверенный серверный snapshot:

- Время сервера: `2026-05-12T13:05:28+03:00`.
- Branch: `dev`.
- Commit: `f9576df`.
- `git status --short`: `528` записей.
- Status hash: `91f5c7476927311fe016d9eb0f58e68a40c3579c6750ac84e3ad0cd89920cb1c`.
- Новых mtimes после heartbeat #17 (`2026-05-12 08:21:09`) не найдено.
- `python3 -m vllm.sndr_core.compat.cli self-test --json`: ранее стабильно PASS `8/8`.
- `python3 -m vllm.sndr_core.apply.shadow --strict`: ранее стабильно `CLEAN`.
- Runtime `vllm-pn95-2xa5000` работал на `8101`.
- Baseline-инфраструктура: `nvidia-gpu-exporter` и `docker-sandbox-1` перезапускаются; это отдельный infrastructure issue, не regression v11 patch-layer.

Главный вывод: apply/registry guard зеленый, но проект нельзя считать production-ready или commit-ready, пока не закрыты P1/P2 ниже. Основной риск не в немедленном падении `sndr_core`, а в незафиксированном dirty-state, недостоверных документах/runbook, слабом deploy/security слое и завышенной оценке production-готовности патчей.

## Что уже закрыто

1. **COMPAT-001 regression по DFlash preset исправлен.**
   - Ранее `a5000-2x-27b-dflash-true` исчезал из registry из-за слишком широкого запрета DFlash + PN59.
   - После исправления registry smoke снова видел `a5000-2x-27b-dflash-true` и `a5000-2x-27b-int4-tq-k8v4-dflash`.
   - Что еще нужно: добавить постоянный test-gate `all builtin configs load and validate`, чтобы такая ошибка не повторялась.

2. **Базовый apply-layer остается зеленым.**
   - `compat self-test` и `apply.shadow --strict` не показывали новых regressions.
   - Ограничение: эти проверки не ловят все ошибки model config registry, deploy render, docs/runbook и secrets.

## P0

На момент последнего snapshot новых P0 runtime-crash не зафиксировано. Единственный P0 из наблюдений, DFlash preset regression, был исправлен. Ниже идут P1/P2, которые блокируют production/release.

## P1: исправить первым

### P1-1. Грязное и незафиксированное серверное дерево

Файлы/область:

- Весь server repo `/home/sander/genesis-vllm-patches-v11`.
- `git status --short`: 528 записей.
- Многие новые файлы в статусе `??`: `vllm/sndr_core/`, `tests/unit/`, `scripts/audit_upstream_status.py`, `docs/upstream/UPSTREAM_WATCHLIST.yaml`, `Makefile`, `pyproject.toml`, lock-файлы, security docs, deploy CLI и др.

Проблема:

- Большая часть новой v11-структуры не tracked.
- `git status --short | sha256sum` не ловит изменения содержимого `??` файлов, если список путей не меняется.
- Нельзя надежно сказать, что именно изменилось после каждого шага.

Что сделать:

1. Разделить server diff на логические batches:
   - core runtime/dispatcher;
   - model configs/schema;
   - deploy CLI;
   - security/license;
   - docs/runbooks;
   - tests;
   - legacy removal.
2. Для каждого batch сделать отдельный diff review.
3. Удалить временные мусорные файлы или явно включить нужные файлы в tracked state.
4. До commit-ready ввести проверку:
   - нет неизвестных `??`, кроме явно разрешенных generated/cache dirs;
   - нет случайных public internal logs;
   - status snapshot включает content hash для untracked файлов.

Acceptance:

```bash
git status --short
git ls-files --others --exclude-standard
```

Результат должен быть объяснимым: каждый `M/D/??` либо входит в release batch, либо удален/перенесен.

### P1-2. Trust anchor private key был выведен в stdout

Файлы/строки по журналу:

- `scripts/generate_trust_anchor.py:172-176`
- `scripts/generate_trust_anchor.py:179-182`
- `docs/_internal/WORK_LOG_2026-05-12_RU.md:91-93`

Проблема:

- Private key был напечатан в terminal/stdout.
- Если этот ключ планировался как production root-of-trust, его надо считать скомпрометированным.
- Даже режим `--out` не должен печатать private key без явного флага.

Что сделать:

1. Считать текущий ключ dev/test-only.
2. Для production сгенерировать новый ключ offline.
3. Изменить generator:
   - `--out` пишет private key только в файл с mode `0600`;
   - stdout содержит только public key/fingerprint;
   - печать private key разрешена только через явный `--print-private`.
4. Добавить тест: `--out` не содержит private key в stdout.
5. В `docs/security/TRUST_ANCHOR_CEREMONY.md` описать безопасную процедуру.

Acceptance:

```bash
python3 scripts/generate_trust_anchor.py --out /tmp/key.txt
test "$(stat -c %a /tmp/key.txt)" = "600"
python3 scripts/generate_trust_anchor.py --out /tmp/key.txt | grep -i "private" && exit 1 || true
```

### P1-3. License token payload слабо валидируется

Файлы/строки по журналу:

- `vllm/sndr_core/license.py:319-350`
- `vllm/sndr_core/license.py:459-482`
- `vllm/sndr_core/license.py:12-14`

Проблема:

- После успешной подписи payload почти не валидируется.
- Missing/string `expires_at`, missing `customer_id`, `issued_at`, `engine_major` могут не блокировать токен.
- Докстринг говорит одно, runtime делает другое: legacy key принимается только при `SNDR_ALLOW_LEGACY_LICENSE_KEYS=1`.

Что сделать:

1. Ввести строгий payload contract:
   - `customer_id: str`, non-empty;
   - `issued_at: int|float`;
   - `expires_at: int|float`;
   - `engine_major: int`;
   - optional `features: list[str]`.
2. Reject:
   - missing required fields;
   - non-numeric `expires_at`;
   - expired token;
   - future `issued_at` beyond допустимый skew;
   - wrong `engine_major`.
3. Обновить docstring и security docs под фактический legacy behavior.
4. Добавить negative unit tests.

Минимальный proposed contract:

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

- signed token without `expires_at` fails;
- signed token with string `expires_at` fails;
- expired token fails;
- valid token passes;
- legacy token behavior documented and tested.

### P1-4. Registry metadata завышает production readiness

Файлы/строки по журналу:

- `vllm/sndr_core/dispatcher/registry_metadata.py:172-195`
- Work log: `production_default: eligible=120`, `test_status: none=91`

Проблема:

- `lifecycle=stable` автоматически превращается в `implementation_status=full` и `production_default=eligible`, даже если `test_status=none`.
- Это дает ложное ощущение production-ready для патчей без тестов.

Что сделать:

1. Изменить policy:
   - `production_default=eligible` только если `lifecycle=stable` и `test_status != none`;
   - если `test_status=none`, статус `review_required` или `blocked`;
   - explicit override разрешен только через audited allowlist с причиной.
2. Добавить unit tests на стабильный патч без тестов.
3. В docs/PATCHES или auto-docs явно показывать `test_status=none`.

Acceptance:

```text
stable + test_status=none -> not eligible
stable + test_status=unit|integration -> eligible
explicit override -> eligible only with reason
```

### P1-5. Upstream watchlist не подключен к реальной автоматизации

Файлы/строки:

- `docs/upstream/UPSTREAM_WATCHLIST.yaml:19-26`
- `Makefile:51-55`
- `tools/check_upstream_drift.py:304-380`
- `scripts/audit_upstream_status.py:75-78`
- `docs/_internal/research/upstream_42102_dflash_independent_kv_groups_plan_2026-05-12.md:83`

Проблема:

- YAML говорит, что `tools/check_upstream_drift.py` читает `UPSTREAM_WATCHLIST.yaml`.
- Фактически `tools/check_upstream_drift.py` проверяет anchors/markers и не загружает этот YAML.
- `make audit-upstream` вызывает `scripts/audit_upstream_status.py`, который читает registry, а не watchlist.
- В итоге `vllm#42102` не будет автоматически отмечен как port candidate после merge.

Что сделать:

1. Добавить `scripts/audit_upstream_watchlist.py` или расширить `scripts/audit_upstream_status.py`.
2. Валидировать schema watchlist:
   - root `watch`;
   - `upstream` format: `vllm#N` или `owner/repo#N`;
   - `status`: `open|merged|closed`;
   - `action`: `drift-check|a-b-test|retire|watch|port|cookbook`;
   - `since` required;
   - sentinel `complete`.
3. `make audit-upstream` должен запускать registry audit + watchlist audit.
4. Для `action=port` и upstream `merged` выдавать `PORT_CANDIDATE`.
5. Добавить offline mode и fixture tests.

Acceptance:

```bash
python3 scripts/audit_upstream_watchlist.py --skip-network --json
make audit-upstream-offline
```

Ожидаемо: watchlist parsed, `vllm#42102` присутствует в отчете, sentinel checked.

### P1-6. Deploy Compose может утекать API key в `/tmp`

Файлы/строки:

- `vllm/sndr_core/cli/compose.py:226-229`
- `vllm/sndr_core/cli/compose.py:301-309`

Проблема:

- `VLLM_API_KEY` добавляется в generated environment.
- `compose up` пишет полный YAML в предсказуемый путь `/tmp/sndr-compose/docker-compose.<key>.yml`.
- Секрет может остаться в temp artifact.

Что сделать:

1. Не сохранять API key в generated compose YAML.
2. Использовать:
   - `.env` file с mode `0600`;
   - Docker secrets;
   - `--env-file`;
   - или runtime-only env injection без записи на диск.
3. Tempdir создавать через secure temp с mode `0700`.
4. Добавить тест, что rendered compose не содержит raw `VLLM_API_KEY`.

Acceptance:

```bash
python3 -m vllm.sndr_core.cli compose render <profile> | grep VLLM_API_KEY && exit 1 || true
```

Или ключ допускается только как `${VLLM_API_KEY}` reference, не literal secret.

## P2: исправить до production

### P2-1. Deploy command builder расходится между launcher/compose/quadlet/k8s

Файлы/строки:

- `vllm/sndr_core/cli/compose.py:141-185`
- `vllm/sndr_core/model_configs/schema.py:2260-2287`

Проблема:

- Compose/Quadlet строят команду отдельно.
- Canonical schema builder использует `vllm serve --model <path>` и учитывает `--language-model-only`.
- Deploy builder может пропустить `language_model_only=True` и дать другой runtime behavior.

Что сделать:

1. Ввести единый `RuntimeCommandSpec`.
2. Все runtime adapters должны использовать один builder:
   - bare-metal launcher;
   - compose;
   - quadlet;
   - k8s.
3. Добавить parity tests: один профиль -> одинаковый argv по всем адаптерам.

Acceptance:

- профиль с `language_model_only=True` везде содержит `--language-model-only`;
- профиль с model path везде использует одинаковую форму `--model`.

### P2-2. Symbolic mounts резолвятся вручную и могут оставлять `${...}`

Файлы/строки:

- `vllm/sndr_core/cli/compose.py:120-138`
- `vllm/sndr_core/model_configs/schema.py` strict resolver уже существует по смыслу миграции.

Проблема:

- `_resolve_mount()` делает простую string replacement.
- Нерешенный placeholder может попасть в compose и упасть только при runtime.

Что сделать:

1. Использовать один resolver из schema/env слоя.
2. Запретить unresolved `${...}` перед render/apply.
3. Добавить tests:
   - valid `${models_dir}` resolves;
   - missing `${foo}` fails before render;
   - empty host path fails.

Acceptance:

```text
mount="${unknown}:/models:ro" -> validation error
mount="${models_dir}:/models:ro" -> resolved absolute host path
```

### P2-3. Quadlet env/exec escaping недостаточный

Файлы/строки:

- `vllm/sndr_core/cli/quadlet.py:164-166`

Проблема:

- `Environment={k}={v}` и `Exec=...` пишутся без полноценного escaping.
- Значения с пробелами, кавычками, `\n`, `%`, `#` могут сломать systemd/quadlet unit или изменить смысл.

Что сделать:

1. Валидировать env keys.
2. Значения выносить в environment file с mode `0600` или корректно quote по правилам systemd.
3. Добавить tests на пробелы, кавычки, newline.

Acceptance:

- env value with space не ломает unit;
- env value with newline rejected;
- API key не попадает literal в public unit file.

### P2-4. Kubernetes YAML строится f-string/`repr`, а не safe emitter

Файлы/строки:

- `vllm/sndr_core/cli/k8s.py:126-142`
- `vllm/sndr_core/cli/k8s.py:191-243`

Проблема:

- Manifest строится строковой конкатенацией.
- Нет строгой валидации Kubernetes names, label keys, mount paths, PVC names, secret names.

Что сделать:

1. Строить Python dict objects.
2. Выводить через `yaml.safe_dump_all`.
3. Валидировать:
   - DNS-1123 names;
   - absolute `mountPath`;
   - PVC size > 0;
   - secret names;
   - nodeSelector label syntax.
4. Добавить negative tests.

Acceptance:

```bash
python3 -m vllm.sndr_core.cli k8s render <profile> | python3 -c 'import sys,yaml; list(yaml.safe_load_all(sys.stdin))'
```

И invalid names должны падать до render.

### P2-5. Новые k8s/deploy поля почти не валидируются schema-слоем

Файлы/строки:

- `vllm/sndr_core/model_configs/schema.py:415-447`

Проблема:

- `node_selector`, `pvc`, `pvc_size_gib`, `secret_mounts`, resource keys, mount paths не проходят достаточную validation.
- Ошибка попадет в cluster/runtime вместо `model config validate`.

Что сделать:

1. Добавить строгую validation в model config schema.
2. Добавить unit tests:
   - invalid PVC name;
   - negative PVC size;
   - relative mountPath;
   - invalid nodeSelector key;
   - duplicate volume names.

Acceptance:

```bash
python3 -m vllm.sndr_core.cli model-config validate <bad-config>
```

Должно возвращать понятную ошибку до deploy.

### P2-6. `k8s delete` оставляет PVC без явной политики

Файлы/строки:

- `vllm/sndr_core/cli/k8s.py:377-383`

Проблема:

- `_pvc_yaml()` создает PVC.
- `k8s delete` удаляет deployment/service/configmap, но не PVC.
- Это может быть правильным data-preserve default, но сейчас не документировано как policy.

Что сделать:

1. В help/docs явно написать: PVC по умолчанию сохраняются.
2. Добавить флаг `--delete-pvc`.
3. Добавить dry-run output, где видно, что будет удалено.

Acceptance:

- `k8s delete --dry-run` показывает список ресурсов;
- `k8s delete` не удаляет PVC и предупреждает;
- `k8s delete --delete-pvc` включает PVC.

### P2-7. `doctor_logs` шумит из-за unrelated restarting containers

Файлы/строки по журналу:

- `vllm/sndr_core/cli/doctor_logs.py:132-139`
- `vllm/sndr_core/cli/doctor_logs.py:377-382`

Проблема:

- Любой restarting container делает host readiness fatal.
- На сервере baseline `nvidia-gpu-exporter` и `docker-sandbox-1` постоянно restart-loop.
- `doctor-system --logs` может краснеть без relation к vLLM runtime.

Что сделать:

1. Добавить фильтр контейнеров:
   - default: `vllm*`, `genesis*`, `sndr*`;
   - option: `--logs-all-containers`;
   - option: `--logs-container-prefix`.
2. Указывать category: `fatal_runtime`, `infra_warning`, `ignored`.
3. Tests на unrelated restarting container.

Acceptance:

- baseline restarting `nvidia-gpu-exporter` не делает vLLM readiness fatal;
- `--logs-all-containers` показывает его как warning/fatal по явному запросу.

### P2-8. `doctor_logs` неверно фильтрует `dmesg --ctime`

Файлы/строки по журналу:

- `vllm/sndr_core/cli/doctor_logs.py:191-193`
- `vllm/sndr_core/cli/doctor_logs.py:173-175`
- `vllm/sndr_core/cli/doctor_logs.py:275-282`

Проблема:

- `_read_dmesg()` вызывает `dmesg --ctime`.
- Timestamp parser понимает uptime-format `[12345.678]`.
- Для ctime строк timestamp становится `None`, а фильтр включает `None` всегда.
- `--logs-hours` не ограничивает OOM/Xid события корректно.

Что сделать:

1. Либо читать `dmesg` без `--ctime`, либо парсить ctime в epoch.
2. Unknown timestamp не включать автоматически в strict window.
3. Добавить tests на uptime и ctime formats.

Acceptance:

- событие старше окна исключается;
- unknown timestamp получает отдельный warning, но не ломает фильтр.

### P2-9. PN96 bench plan не исполним в текущем v11 tree

Файлы/строки:

- `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md:21`
- `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md:34`
- `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md:40-42`
- `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md:52`
- `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md:57-58`
- `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md:66-69`
- `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md:88-89`

Проблема:

- Ссылается на отсутствующие `scripts/launch/snapshot_pre_arm.sh`.
- Ссылается на отсутствующий `scripts/launch/start_35b_fp8_PROD.sh`.
- Ссылается на отсутствующий `tools/run_stress.py`.
- Содержит destructive commands: `docker stop`, restart, `rm -rf` cache.
- Называет план ready-to-execute, но он требует ручной реконструкции.

Что сделать:

1. Обновить plan под v11 canonical launcher/model-config flow.
2. Заменить `tools/run_stress.py` на существующий `tools/soak.sh` или добавить stress tool отдельно.
3. Добавить operator-only header:
   - не запускать без явного downtime approval;
   - все mutating команды вынести в отдельный gated block.
4. Сначала сделать dry-run plan, затем короткий smoke, затем только полный A/B.

Acceptance:

- все команды в плане существуют;
- dry-run не останавливает containers;
- destructive шаги явно gated.

### P2-10. Public docs содержат hardcoded host/user/path и internal context

Файлы/строки по журналу:

- `docs/WORK_LOG_2026-05-12_RU.md:9`
- `docs/WORK_LOG_2026-05-12_RU.md:33-51`
- `docs/WORK_LOG_2026-05-12_RU.md:136`
- `docs/CONTRIBUTING.md:320`
- `docs/INSTALL.md:348`
- `docs/INSTALL.md:511-516`

Проблема:

- Public docs содержат `192.168.1.10`, `sander`, `/home/sander`, internal migration details.
- Это плохо для community repo и переносимости.

Что сделать:

1. Перенести public work log в `docs/_internal/` или удалить из public docs.
2. Заменить:
   - `ssh sander@192.168.1.10` -> `ssh <user>@<host>`;
   - `/home/sander/...` -> `$SNDR_HOME`, `$VLLM_DIR`, `$MODEL_DIR`;
   - `User=sander` -> `User=<service-user>`.
3. Добавить docs lint на hardcoded host/private paths.

Acceptance:

```bash
rg -n "192\\.168\\.1\\.10|/home/sander|User=sander|sander@" docs scripts vllm
```

Должно вернуть только intentional internal docs.

### P2-11. Launch docs указывают на удаленные scripts и legacy `_genesis`

Файлы/строки по журналу:

- `scripts/launch/README.md:112-113`
- `scripts/launch/README.md:146-147`
- `docs/INSTALL.md:573`

Проблема:

- Docs ссылаются на удаленные `snapshot_pre_arm.sh`, `nsight_profile_capture.sh`.
- Docs говорят про `_genesis` symlink, хотя v11 canonical namespace — `vllm.sndr_core`.

Что сделать:

1. Обновить launch README под фактический набор файлов.
2. Legacy `_genesis` оставить только в migration appendix.
3. Добавить docs check: все referenced local scripts/files существуют.

Acceptance:

```bash
python3 scripts/check_doc_links.py --local-only
```

Если такого скрипта нет, добавить простой scanner для markdown local paths.

### P2-12. PN26: старый `_genesis` log, runtime-doc mismatch, слабый env parse

Файлы/строки по журналу:

- `vllm/sndr_core/integrations/attention/turboquant/pn26_sparse_v_kernel.py:198-205`
- `vllm/sndr_core/integrations/attention/turboquant/pn26_sparse_v_kernel.py:221`
- `vllm/sndr_core/integrations/attention/turboquant/pn26_sparse_v_kernel.py:229`
- `vllm/sndr_core/integrations/attention/turboquant/pn26_sparse_v_kernel.py:231-254`
- `vllm/sndr_core/integrations/attention/turboquant/pn26_sparse_v_kernel.py:321-325`

Проблема:

- Log text ссылается на `vllm._genesis...collect_skip_stats()`.
- Описание BLASST/seq_len route не совпадает с lean dispatcher behavior.
- `GENESIS_PN26_SPARSE_V_LOG_EVERY` парсится через `int(...)` без validation.

Что сделать:

1. Заменить `_genesis` в logs/docs на `sndr_core`.
2. Переписать runtime-сообщение под фактический lean behavior.
3. Добавить helper безопасного env int:

```python
def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)
```

Acceptance:

- invalid `GENESIS_PN26_SPARSE_V_LOG_EVERY=abc` не ломает import/apply;
- `0` и negative values clamp to minimum;
- logs не содержат `vllm._genesis`.

### P2-13. PN59 test top-level `import torch`

Файлы/строки по журналу:

- `tests/unit/integrations/attention/gdn/test_pn59_streaming_gdn.py:17`

Проблема:

- Top-level `import torch` ломает torch-less CI/Mac-dev.
- Для проекта с torch-optional checks тест должен skip, а не падать на import.

Что сделать:

```python
import pytest

torch = pytest.importorskip("torch")
```

Или перенести import внутрь конкретного теста.

Acceptance:

- В окружении без torch тестовый модуль skip, не fail.
- В окружении с torch тесты проходят.

### P2-14. Legacy import gate слишком узкий

Файлы/строки по журналу:

- `scripts/check_no_legacy_imports.sh:54`
- `scripts/check_no_legacy_imports.sh:78`

Проблема:

- Скрипт ловит только часть import patterns.
- Не ловит `from vllm.sndr_core import patches`.
- Сканирует только `*.py`, `*.sh`, `*.md`; пропускает YAML/JSON/TOML/workflows.

Что сделать:

1. Заменить shell regex на Python AST scanner для Python imports.
2. Добавить text scan для configs/docs/workflows.
3. Добавить negative fixtures.

Acceptance:

- `import vllm.sndr_core.patches as patches` fails gate.
- `from vllm.sndr_core import patches` fails gate.
- `vllm._genesis` в YAML/workflow fails gate, если не allowlisted.

### P2-15. Public/internal work logs завышают readiness

Файлы/строки:

- `docs/_internal/WORK_LOG_2026-05-12_RU.md`
- `docs/WORK_LOG_2026-05-12_RU.md`

Проблема:

- Заявления вида `commit-ready`, `P0/P1 closed`, `5413 passed / 0 failed` не подтверждены в самом документе полным воспроизводимым context.
- Фактический server tree остается `528` dirty status entries.
- Некоторые "closed" пункты фактически не wired или не исполнимы.

Что сделать:

1. Добавить в work log формат доказательств:
   - command;
   - cwd;
   - commit;
   - timestamp;
   - output summary;
   - artifact/log path.
2. Запретить `commit-ready` при non-empty uncontrolled `??`.
3. Перенести public work log в `_internal`.

Acceptance:

- `commit-ready` допускается только если release checklist зеленый и dirty-state объяснен.

## P3: улучшить после P1/P2

### P3-1. Отдельный content hash для untracked-файлов

Проблема:

- Наблюдение показало, что `git status --short` hash не менялся при изменениях внутри `??` файлов.

Что сделать:

- Добавить watch/audit script:

```bash
git ls-files --others --exclude-standard -z \
  | xargs -0 sha256sum \
  | sort -k2
```

Acceptance:

- изменение содержимого untracked file меняет audit hash.

### P3-2. Проверка ссылок на локальные файлы в Markdown

Проблема:

- Несколько docs/runbooks ссылались на удаленные scripts.

Что сделать:

- Добавить `scripts/check_doc_local_paths.py`.
- Проверять markdown code spans и links с local-looking paths.
- Allowlist для примеров/placeholders.

Acceptance:

- ссылка на отсутствующий `scripts/launch/start_35b_fp8_PROD.sh` ловится.

### P3-3. Инфраструктурные restart-loop контейнеры

Область:

- `nvidia-gpu-exporter`
- `docker-sandbox-1`

Проблема:

- Это baseline, не v11 regression, но загрязняет doctor/log readiness.

Что сделать:

1. Отдельно разобрать restart reason.
2. Либо исправить инфраструктуру, либо пометить containers как ignored для vLLM readiness.

Acceptance:

- `doctor-system --logs` не смешивает infra restart-loop с vLLM runtime fatal.

## Что не сделано, но должно быть сделано

1. Не сделан полноценный git hygiene pass для server-v11.
2. Не сделана связка `UPSTREAM_WATCHLIST.yaml` -> `make audit-upstream`.
3. Не сделан production-safe trust anchor ceremony.
4. Не сделана строгая license payload validation.
5. Не сделано честное ограничение `production_default=eligible` по test coverage.
6. Не сделан secure secret handling для compose/quadlet/k8s deploy.
7. Не сделан единый runtime command builder.
8. Не сделан единый mount resolver.
9. Не сделана строгая K8s schema validation.
10. Не сделан safe YAML emitter для K8s manifests.
11. Не сделан executable PN96 plan под текущий v11 tree.
12. Не убраны hardcoded host/user/path из public docs.
13. Не синхронизированы launch docs с фактическими scripts.
14. Не закрыты PN26 log/env-validation мелкие дефекты.
15. Не исправлен torch-optional contract для PN59 test.
16. Не усилен legacy import gate.
17. Не введен local markdown path checker.
18. Не введен content hash для untracked files.

## Рекомендуемый порядок исправления

### Этап 1: стабилизировать состояние repo

1. Разложить `528` status entries на batches.
2. Убрать/перенести public internal logs.
3. Закрепить нужные `??` файлы или удалить временные.
4. Добавить content hash для untracked files.

Gate:

```bash
git status --short
python3 -m vllm.sndr_core.compat.cli self-test --json
python3 -m vllm.sndr_core.apply.shadow --strict
```

### Этап 2: закрыть security blockers

1. Перегенерировать production trust anchor offline.
2. Исправить generator stdout behavior.
3. Усилить license payload validation.
4. Обновить docs/security.

Gate:

```bash
python3 -m pytest tests/unit/test_license.py tests/unit/test_trust_anchor_generator.py -q
```

### Этап 3: закрыть deploy correctness

1. Единый command builder.
2. Единый mount resolver.
3. Secure secret handling.
4. Quadlet escaping.
5. K8s dict emitter + validation + delete PVC policy.

Gate:

```bash
python3 -m pytest tests/unit/cli/test_compose_render.py tests/unit/cli/test_quadlet_render.py tests/unit/cli/test_k8s_render.py -q
```

### Этап 4: закрыть audit/docs automation

1. Подключить `UPSTREAM_WATCHLIST.yaml` к `make audit-upstream`.
2. Добавить watchlist schema tests.
3. Исправить PN96 plan под реальные v11 scripts/tools.
4. Добавить doc local path checker.
5. Убрать hardcoded private host/user/path из public docs.

Gate:

```bash
make audit-upstream-offline
make docs-check
rg -n "192\\.168\\.1\\.10|/home/sander|User=sander|sander@" docs scripts vllm
```

### Этап 5: закрыть patch/test hygiene

1. PN26 log/env parse.
2. PN59 torch optional skip.
3. Legacy import gate AST scanner.
4. All builtin configs load test.

Gate:

```bash
python3 -m pytest tests/unit/integrations/attention/gdn/test_pn59_streaming_gdn.py -q
python3 -m pytest tests/unit/model_configs/test_compatibility_matrix.py -q
bash scripts/check_no_legacy_imports.sh
```

## Release acceptance checklist

Перед тем как считать v11 готовым:

```bash
# 1. Git hygiene
git status --short
git ls-files --others --exclude-standard

# 2. Core health
PYTHONDONTWRITEBYTECODE=1 python3 -m vllm.sndr_core.compat.cli self-test --json
PYTHONDONTWRITEBYTECODE=1 python3 -m vllm.sndr_core.apply.shadow --strict

# 3. Syntax/parse
python3 - <<'PY'
import ast, pathlib
for p in pathlib.Path(".").rglob("*.py"):
    if ".git" in p.parts:
        continue
    ast.parse(p.read_text())
print("AST OK")
PY

# 4. Config parse
python3 - <<'PY'
import json, pathlib, tomllib, yaml
for p in pathlib.Path(".").rglob("*.json"):
    json.loads(p.read_text())
for p in pathlib.Path(".").rglob("*.toml"):
    tomllib.loads(p.read_text())
for p in list(pathlib.Path(".").rglob("*.yaml")) + list(pathlib.Path(".").rglob("*.yml")):
    yaml.safe_load(p.read_text())
print("CONFIG PARSE OK")
PY

# 5. Shell syntax
find scripts tools -name "*.sh" -print0 | xargs -0 -n1 bash -n

# 6. Focused tests
python3 -m pytest tests/unit/cli tests/unit/model_configs tests/unit/dispatcher -q

# 7. Docs and audit
make audit-upstream-offline
make docs-check
```

## Итоговое решение

Текущее состояние можно использовать как рабочую v11 миграционную ветку, но нельзя выпускать как production/release. Сначала нужно закрыть P1: git hygiene, trust anchor, license validation, production eligibility, watchlist automation и compose secret leak. После этого закрыть P2 deploy/docs/runtime correctness. Только затем имеет смысл запускать короткие GPU smoke и финальный production readiness audit.
