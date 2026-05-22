# Повторная проверка проекта: оставшиеся ошибки и блокеры

Дата проверки: 2026-05-14 05:31 EEST  
Локальная ветка: `dev`  
HEAD: `e4663d8` (`Migrate active code off vllm._genesis → vllm.sndr_core`)  
Scope: локальная версия проекта в `/Users/sander/Documents/Visual Studio Code/genesis-vllm-patches`

## Короткий вывод

Проект стал заметно ближе к release-состоянию, чем в предыдущем срезе:

- `python3 -m vllm.sndr_core.compat.cli self-test --json` проходит: `8/8`.
- `python3 -m vllm.sndr_core.apply.shadow --strict` теперь `CLEAN`.
- `make audit-configs` проходит: `11/11` presets compose.
- `python3 scripts/check_doc_sync.py --strict` проходит: docs/registry count согласованы на `151`.
- `python3 scripts/audit_no_new_v1.py` проходит: V1 freeze baseline соблюден.
- `python3 -m vllm.sndr_core.cli launch ... --preflight-only --check-deps` теперь корректно возвращает non-zero при dependency blockers.
- `make audit-release-check` проходит: `considered=151/151 passed=151 failed=0`.

Но production release все еще нельзя считать готовым: `make evidence` блокируется `7` gating failures. Основные причины: legacy-ссылки на `vllm._genesis`, отсутствующий CLI route для `community`, мусорные macOS AppleDouble `._*.py` файлы, drift в README counter, hardcoded operator paths, падение no-stub/engine-boundary scanners на non-UTF8 файлах.

## Итог по проверкам

| Проверка | Результат | Комментарий |
|---|---:|---|
| `python3 -m vllm.sndr_core.compat.cli self-test --json` | PASS | `8/8`, `151` registry entries валидны |
| `python3 -m vllm.sndr_core.apply.shadow --strict` | PASS | legacy/spec shadow больше не расходится |
| `python3 -m vllm.sndr_core.cli patches prove --dead-detect --json` | WARN | `136/151`, `dead=15`; теперь не release-blocker, но остается quality debt |
| `make audit-configs` | PASS | `11/11` config presets compose cleanly |
| `python3 scripts/security_scan.py` | FAIL | `46` operator-path hits |
| Python compile scan всех `.py` | FAIL | `6` AppleDouble файлов с null bytes |
| Shell syntax scan | PASS | `72` shell files, `0` syntax errors |
| `python3 scripts/check_doc_sync.py --strict` | PASS | PATCH_REGISTRY count `151` согласован |
| `make audit-dirty-state-dev` | PASS | `408` untracked entries accepted by dev policy |
| `python3 scripts/audit_no_new_v1.py` | PASS | `12/12` baseline |
| `make audit` | FAIL | legacy-import gate: `20` violations |
| `make evidence` | FAIL | `7` gating failures |
| `make audit-release-check` | PASS | release policy по patch registry выполнена |

## P0. Legacy imports `vllm._genesis` в активных scripts/tools

Статус: блокирует `make audit`, а значит и `make evidence`.

Команда:

```bash
python3 scripts/check_no_legacy_imports.py
```

Результат:

```text
✗ legacy-import gate: 20 violation(s)
```

Найденные места:

| Файл | Строка | Текущий код / текст | Проблема | Что сделать |
|---|---:|---|---|---|
| `scripts/launch.sh` | 20 | `exec python3 -m vllm._genesis.compat.cli model-config list` | CLI launcher все еще вызывает старый namespace | Перевести на `python3 -m vllm.sndr_core.compat.cli ...` или новый canonical `vllm.sndr_core.cli` |
| `scripts/launch.sh` | 28 | `exec python3 -m vllm._genesis.compat.cli model-config render "$KEY"` | То же | Перевести на `sndr_core` |
| `scripts/launch.sh` | 31 | `exec python3 -m vllm._genesis.compat.cli model-config validate "$KEY"` | То же | Перевести на `sndr_core` |
| `scripts/launch.sh` | 34 | `exec python3 -m vllm._genesis.compat.cli model-config preflight "$KEY"` | То же | Перевести на `sndr_core` |
| `scripts/launch.sh` | 47 | `python3 -m vllm._genesis.compat.cli model-config diagnose <key>` | Help text stale | Обновить help |
| `scripts/launch.sh` | 48 | `python3 -m vllm._genesis.compat.cli model-config verify <key>` | Help text stale | Обновить help |
| `scripts/launch.sh` | 54 | `exec python3 -m vllm._genesis.compat.cli model-config launch "$KEY"` | Runtime path старого namespace | Перевести на `sndr_core` |
| `scripts/launch.sh` | 58 | `exec python3 -m vllm._genesis.compat.cli model-config launch "$KEY" "$@"` | Runtime path старого namespace | Перевести на `sndr_core` |
| `scripts/validate_integration.sh` | 96 | `from vllm._genesis import __version__, __author__` | Integration validation проверяет старый пакет | Проверять `vllm.sndr_core.version` / `vllm.sndr_core` |
| `scripts/validate_integration.sh` | 97 | `pass "vllm._genesis imports cleanly"` | Stale success message | Переименовать сообщение |
| `scripts/validate_integration.sh` | 99 | `fail "vllm._genesis import failed"` | Stale fail message | Переименовать сообщение |
| `scripts/validate_integration.sh` | 103 | `from vllm._genesis.guards import platform_summary` | Старый import | Перевести на новый модуль guards/doctor в `sndr_core` |
| `tools/genesis_vllm_plugin/pyproject.toml` | 16 | comment про `vllm._genesis/*` | Public packaging doc stale | Обновить комментарий |
| `tools/genesis_vllm_plugin/pyproject.toml` | 36 | comment про `python3 -m vllm._genesis.compat.cli` | Stale command | Обновить на `sndr_core` |
| `tools/genesis_vllm_plugin/pyproject.toml` | 38 | comment `Requires vllm._genesis` | Stale dependency boundary | Обновить на `sndr_core` |
| `tools/genesis_vllm_plugin/pyproject.toml` | 40 | `genesis = "vllm._genesis.compat.cli:main"` | Entry point ведет в старый namespace | Заменить на `vllm.sndr_core.compat.cli:main` или новый стабильный CLI facade |
| `tools/external_probe/README.md` | 25 | `python3 -m vllm._genesis.patches.apply_all` | Документация ведет к старому apply path | Обновить |
| `tools/external_probe/README.md` | 29 | `python3 -m vllm._genesis.patches.apply_all` | То же | Обновить |
| `tools/examples/genesis-plugin-hello-world/README.md` | 30 | `python3 -m vllm._genesis.compat.cli plugins list` | Plugin example stale | Обновить |
| `tools/examples/genesis-plugin-hello-world/README.md` | 43 | `vllm._genesis.compat.schema_validator` | Stale validator path | Обновить |

Риск: пока эти ссылки есть в активных scripts/tools, пользователь может запустить старый path и получить несовместимый behavior после миграции на `sndr_core`.

Acceptance:

```bash
python3 scripts/check_no_legacy_imports.py
make audit
```

## P0. Отсутствует CLI route `community`, но Makefile его вызывает

Статус: блокирует `make audit-community` и `make evidence`.

Файл:

```text
Makefile:139-140
```

Текущий код:

```make
audit-community: ## Phase 7 gate: community SDK release-tier validator (R-1..R-7)
	@$(PYTHON) -m vllm.sndr_core.cli community validate
```

Фактическое поведение:

```text
usage: __main__.py ...
__main__.py: error: argument command: invalid choice: 'community'
```

Проблема: `Makefile` уже содержит release gate, но CLI surface не реализован или не подключен в root parser.

Что сделать:

1. Либо добавить subcommand `community validate` в `vllm/sndr_core/cli`.
2. Либо временно заменить target на реально существующую команду/скрипт community validator.
3. Если community SDK еще не входит в release scope, gate должен быть явно `deferred`, а не падать как отсутствующая команда.

Acceptance:

```bash
make audit-community
make evidence
```

## P0. AppleDouble `._*.py` файлы ломают scanners и compile scan

Статус: блокирует `audit-all-referents`, `audit-no-stub`, `audit-engine-boundary`; также ломает broad Python compile.

Найденные файлы:

```text
vllm/sndr_core/apply/.__per_patch_dispatch.py
vllm/sndr_core/cache/.__pn95_disk_tier.py
vllm/sndr_core/cache/.__pn95_runtime.py
vllm/sndr_core/cli/._patches.py
vllm/sndr_core/dispatcher/._registry.py
vllm/sndr_core/integrations/worker/._sndr_workspace_001_grow_after_lock.py
```

Ошибки:

```text
SyntaxError: source code string cannot contain null bytes
UnicodeDecodeError: 'utf-8' codec can't decode byte 0x80 ...
```

Проблема: это не Python-код, а macOS resource-fork файлы. Они попали в tree и сейчас воспринимаются scanners как production `.py`.

Что сделать:

1. Удалить эти `._*.py` файлы из рабочего дерева.
2. Добавить защиту в scanners: игнорировать `._*`, `.DS_Store`, `__MACOSX`.
3. Добавить `.gitignore` rule для AppleDouble:

```gitignore
._*
.DS_Store
__MACOSX/
```

Acceptance:

```bash
find . -name '._*' -type f
python3 - <<'PY'
import py_compile
from pathlib import Path
for p in Path('.').rglob('*.py'):
    if '/.git/' not in str(p):
        py_compile.compile(str(p), doraise=True)
PY
make audit-all-referents
make audit-no-stub
make audit-engine-boundary
```

## P0. Hardcoded operator paths в active compose files

Статус: блокирует `make audit-no-hardcoded-paths`; security scan также падает.

Команды:

```bash
make audit-no-hardcoded-paths
python3 scripts/security_scan.py
```

Gate result:

```text
51 files scanned
45 clean / 1 exempt / 5 with violations
10 hardcoded paths
```

Активные hardcoded paths:

| Файл | Строка | Текущий путь | Что сделать |
|---|---:|---|---|
| `compose/docker-compose.gemma4-26b-moe.yml` | 35 | `/home/sander/Genesis_Project/vllm_engine/triton-cache` | заменить на `${SNDR_TRITON_CACHE}` или `${SNDR_CACHE_ROOT}/triton-cache` |
| `compose/docker-compose.gemma4-26b-moe.yml` | 36 | `/home/sander/Genesis_Project/vllm_engine/compile-cache-integration` | заменить на `${SNDR_COMPILE_CACHE}` |
| `compose/docker-compose.integration-awq.yml` | 113 | `/home/sander/Genesis_Project/vllm_engine/triton-cache` | заменить на env/config placeholder |
| `compose/docker-compose.integration-awq.yml` | 120 | `/home/sander/Genesis_Project/vllm_engine/compile-cache-integration` | заменить на env/config placeholder |
| `compose/docker-compose.integration-fp16kv.yml` | 113 | `/home/sander/Genesis_Project/vllm_engine/triton-cache` | заменить на env/config placeholder |
| `compose/docker-compose.integration-fp16kv.yml` | 120 | `/home/sander/Genesis_Project/vllm_engine/compile-cache-integration` | заменить на env/config placeholder |
| `compose/docker-compose.integration.yml` | 113 | `/home/sander/Genesis_Project/vllm_engine/triton-cache` | заменить на env/config placeholder |
| `compose/docker-compose.integration.yml` | 120 | `/home/sander/Genesis_Project/vllm_engine/compile-cache-integration` | заменить на env/config placeholder |
| `compose/docker-compose.qwen3-5-dense.yml` | 35 | `/home/sander/Genesis_Project/vllm_engine/triton-cache` | заменить на `${SNDR_TRITON_CACHE}` |
| `compose/docker-compose.qwen3-5-dense.yml` | 36 | `/home/sander/Genesis_Project/vllm_engine/compile-cache-integration` | заменить на `${SNDR_COMPILE_CACHE}` |

Дополнительно `scripts/security_scan.py` нашел `46` operator-path hits в tracked files. Часть относится к archived/historical paths и legacy `_genesis`, но для публичного repo лучше либо перенести их в internal archive, либо добавить осознанные allowlist с причиной.

Acceptance:

```bash
make audit-no-hardcoded-paths
python3 scripts/security_scan.py
```

## P1. README counter drift

Статус: блокирует `audit-readme-counters`, а значит и `make evidence`.

Файл:

```text
README.md:404
```

Текущий текст:

```markdown
### Patch coverage — 151 patches across 20 categories
```

Фактическое состояние:

```text
151 patches across 21 categories
```

Что сделать:

```markdown
### Patch coverage — 151 patches across 21 categories
```

Дополнительная проблема рядом:

```text
README.md:408
```

Текст все еще говорит про `v7.72`, `128 PATCH_REGISTRY entries`, `9 functional groups`, `~120 patches`. Это не совпадает с текущим `v11`, `151` entries и `21/22` category counters. Даже если строгий gate сейчас ругается только на строку `404`, README semantic drift остается.

Acceptance:

```bash
make audit-readme-counters
python3 scripts/check_doc_sync.py --strict
```

## P1. `patches prove --dead-detect` показывает 15 dead patches

Статус: больше не блокирует `make audit-release-check`, но остается важным quality debt.

Команда:

```bash
python3 -m vllm.sndr_core.cli patches prove --dead-detect --json
```

Результат:

```json
{
  "proven": 136,
  "total_patches": 151,
  "dead": 15,
  "coverage_pct": 90.1
}
```

Dead list:

```text
SNDR_WORKSPACE_001
PN202
PN203
PN200
PN201
PN106
PN105
PN104
PN97
PN92
PN71
PN73
PN91
PN204
PN108
```

Почему это важно: release-check уже считает все `151/151` policy-clean, значит строгий release contract исправлен. Но CLI proof view показывает, что 15 patches не имеют такого же доказательного статуса, как остальные. Это создает риск расхождения между operator dashboard, release gate и реальным уровнем верификации.

Что сделать:

1. Разделить в UI/CLI понятия `release-policy passed` и `runtime/dead-detect proof coverage`.
2. Для каждого из 15 patch id добавить один из статусов: `static_proof`, `bench_proof`, `tombstone`, `spec_only`, `retired`.
3. Если patch intentionally non-runtime, убрать его из dead-detect numerator через явный allowlist с причиной.

Acceptance:

```bash
python3 -m vllm.sndr_core.cli patches prove --dead-detect --json
make audit-release-check
make evidence
```

## P1. Security scan: operator paths в tracked files

Статус: security gate падает, хотя keys/env/private IP checks чистые.

Команда:

```bash
python3 scripts/security_scan.py
```

Результат:

```text
operator_paths: 46 hits
private_ips: clean
private_keys: clean
env_files: clean
aws_keys: clean
```

Первые активные hits:

```text
compose/docker-compose.gemma4-26b-moe.yml:35
compose/docker-compose.gemma4-26b-moe.yml:36
compose/docker-compose.integration-awq.yml:9
compose/docker-compose.integration-awq.yml:113
compose/docker-compose.integration-awq.yml:120
```

Что сделать:

1. Active compose: заменить `/home/sander/...` на `${SNDR_*}` variables.
2. Test-only compose: либо exempt с reason, либо перенести в internal docs/test fixtures.
3. Historical scripts/docs: перенести в archive allowlist или удалить из public release package.
4. В `security_scan.py` отделить `public tracked` от `internal archive`, чтобы gate был строгим именно для release surface.

Acceptance:

```bash
python3 scripts/security_scan.py
```

## P1. Dirty state не готов для release freeze

Статус: dev policy проходит, release policy еще не проверена чисто.

Команда:

```bash
make audit-dirty-state-dev
```

Результат:

```text
entries=408 accepted=408 rejected=0
```

Проблема: это нормальное состояние для активной разработки, но не release baseline. Перед production release нужен отдельный frozen snapshot: какие untracked docs/tests/research accepted, какие должны быть staged/tracked/removed.

Что сделать:

1. Сформировать `LOCAL_SERVER_ALLOWED_DIRTY_STATE` или аналогичный release manifest.
2. Разделить generated reports, temp research и production files.
3. Прогнать release-tier dirty gate.

Acceptance:

```bash
make audit-dirty-state-release
```

## P2. Local dependency plan не готов на текущей машине

Статус: не ошибка кода после текущих исправлений, но важное runtime условие.

Команда:

```bash
python3 -m vllm.sndr_core.cli deps plan --config a5000-2x-35b-prod --json
```

Результат:

```text
is_ready: false
blockers: 3
- Docker not found on PATH
- NVIDIA/nvidia-smi not found on PATH
- model directory missing: /models/Qwen3.6-35B-A3B-FP8
warning: vllm not importable in current Python
```

Важно: `launch --preflight-only --check-deps` теперь корректно возвращает exit code `2`, то есть прежний false-pass исправлен.

Что сделать:

1. Для локальной macOS/dev среды не считать эти blockers кодовой ошибкой.
2. Для сервера проверять тот же `deps plan` отдельно, потому что там есть GPU/Docker.
3. В dashboard явно отделять `host readiness` от `project release readiness`.

## Что исправлено с прошлого отчета

| Было | Сейчас |
|---|---|
| `self-test` падал из-за schema/doc drift | `self-test 8/8 PASS` |
| `shadow --strict` был divergent | `shadow --strict CLEAN` |
| `audit-release-check` падал по dead bucket | `audit-release-check PASS` |
| `launch --check-deps` давал false-positive success | теперь exit code `2` при blockers |
| `check_doc_sync.py --strict` ранее расходился | теперь PASS |
| V1 freeze был risk | теперь `audit_no_new_v1.py` PASS |
| `make audit-configs` нужно было перепроверить | `11/11` PASS |

## Минимальный план исправления

1. Удалить AppleDouble файлы и добавить ignore/scanner skip для `._*`.
2. Обновить `scripts/launch.sh`, `scripts/validate_integration.sh`, plugin pyproject и README examples с `vllm._genesis` на `vllm.sndr_core`.
3. Реализовать или отключить корректно `community validate` gate.
4. Заменить hardcoded compose paths на `${SNDR_CACHE_ROOT}`, `${SNDR_TRITON_CACHE}`, `${SNDR_COMPILE_CACHE}`, `${HF_HOME}`.
5. Исправить README counters и semantic drift вокруг старого `v7.72`.
6. Решить 15 dead-detect patches через explicit proof/tombstone/spec-only statuses.
7. Повторить:

```bash
python3 scripts/check_no_legacy_imports.py
make audit-community
make audit-all-referents
make audit-no-stub
make audit-engine-boundary
make audit-readme-counters
make audit-no-hardcoded-paths
python3 scripts/security_scan.py
make audit
make evidence
```

## Production readiness оценка

Текущая техническая оценка: **68/100**.

Причина не выше:

- `make evidence` все еще красный.
- Есть активные hardcoded operator paths.
- Есть мусорные non-UTF8 `.py` файлы в production tree.
- Makefile вызывает несуществующую CLI команду.
- README все еще содержит старую semantic информацию.
- Patch proof dashboard показывает 15 dead entries.

Причина не ниже:

- Registry/schema/import lifecycle теперь зеленые.
- Strict shadow gate исправлен.
- Release policy по registry проходит.
- Config composition проходит.
- Dependency preflight больше не скрывает blockers.

