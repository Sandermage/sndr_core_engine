# Текущий аудит после исправлений: что закрыто и что осталось

Дата среза: `2026-05-14 05:03:09 EEST`

Рабочая копия: `/Users/sander/Documents/Visual Studio Code/genesis-vllm-patches`

HEAD: `d7eb86a` (`PN59 anchor fix (Cliff 2 streaming-GDN) + PN108 tombstone`)

Ветка: `dev`

## Executive summary

Часть прошлых P0 действительно исправлена:

- `PN204.upstream_pr` приведен к schema-clean виду;
- `self-test` снова проходит: `8/8`;
- docs больше не застряли на `136`: `check_doc_sync.py --strict` подтверждает `151`;
- V1 freeze теперь проходит: baseline расширен до `12`;
- `audit-patches-prove-all` теперь проходит: `151/151`;
- Python/shell синтаксис основного дерева в целом не содержит обычных syntax errors.

Но production release все еще заблокирован. Главные остаточные проблемы:

- `make evidence` падает: `8` gating failures;
- `make audit` падает на legacy imports: `24` ссылки на `vllm._genesis`;
- `apply.shadow --strict` все еще divergent по `SNDR_WORKSPACE_001`;
- `patches prove --dead-detect` все еще показывает `15` dead patches;
- `audit-release-check` блокирует release из-за bucket `dead`;
- `security_scan` снова красный: `46` operator-path violations;
- `audit-no-hardcoded-paths` красный: `10` активных hardcoded `/home/sander/...` в compose;
- в дереве есть `._*.py` AppleDouble/resource-fork файлы, которые ломают UTF-8 scanners и широкий compile;
- `launch --check-deps` все еще дает false-positive pass при реальных blockers;
- `audit-community` вызывает несуществующую CLI-команду `community validate`;
- README counter drift остался: `151 patches across 20 categories`, должно быть `21`.

Оценка текущей production readiness: `58/100`.

## Проверки текущего среза

| Проверка | Результат | Детали |
|---|---:|---|
| `python3 -m vllm.sndr_core.compat.cli self-test --json` | PASS | `8/8`, `151` entries schema-clean, `138` wiring imports, `22` categories |
| `python3 -m vllm.sndr_core.apply.shadow --strict` | FAIL | `SNDR_WORKSPACE_001` все еще divergent |
| `python3 -m vllm.sndr_core.cli patches prove --dead-detect --json` | FAIL-quality | `136/151`, dead=`15`, coverage `90.1%` |
| `make audit-configs` | PASS | `11/11` presets compose cleanly |
| `python3 scripts/check_doc_sync.py --strict` | PASS | все checked docs заявляют `151` patches |
| `python3 scripts/audit_no_new_v1.py` | PASS | `12` V1 files match `12` frozen baseline |
| `make audit` | FAIL | падает на `audit-legacy-imports`, `24` violations |
| `make evidence` | FAIL | `8` gating failures |
| `make audit-dirty-state-dev` | PASS dev-only | `424` dirty entries accepted |
| `python3 scripts/security_scan.py` | FAIL | `923` tracked files scanned, `46` operator-path hits |
| Python compile broad scan | FAIL-noise | `1252` `.py`, `6` compile errors, все из `._*.py` AppleDouble files |
| Shell syntax | PASS | `72` shell files, `0` `bash -n` errors |
| `deps plan --config a5000-2x-35b-prod` | NOT READY | `3` blockers: Docker, NVIDIA/nvidia-smi, model dir |
| `launch ... --preflight-only --check-deps` | FALSE PASS | возвращает success несмотря на blockers из `deps plan` |

## Что исправлено по сравнению с прошлым срезом

### 1. Schema regression `PN204.upstream_pr` закрыт

Файл: `vllm/sndr_core/dispatcher/registry.py`

Строки: `1889-1918`

Текущее состояние:

```python
"PN204": {
    "title": "GDN dual-stream input projection (port of vllm#42301)",
    ...
    "upstream_pr": 42301,
```

Оценка: исправлено корректно. `self-test` снова проходит, upstream audit видит `PN204 PR #42301`.

### 2. Doc-sync `136 -> 151` закрыт

Команда:

```bash
python3 scripts/check_doc_sync.py --strict
```

Результат:

```text
PATCH_REGISTRY count: 151
✓ All checked docs claim 151 patches consistently.
```

Оценка: предыдущий blocker `README/docs still 136` закрыт.

### 3. V1 freeze закрыт

Команда:

```bash
python3 scripts/audit_no_new_v1.py
```

Результат:

```text
audit-no-new-v1: 12 V1 file(s) currently present
                 12 in frozen baseline
✓ V1 frozen
```

Оценка: gate теперь зеленый. Архитектурно лучше позже все равно вынести новый `a5000-1x-tier-aware-pn95.yaml` в V2 layered preset, но текущий release-gate больше не блокируется этим пунктом.

### 4. `audit-patches-prove-all` закрыт

В `make evidence`:

```text
✓ [GATING] audit-patches-prove-all
```

Оценка: static proof all-gate теперь проходит. Отдельно остается dead-detect/release-check, см. ниже.

## Оставшиеся P0/P1 ошибки и что исправить

## P0. `make audit` падает на legacy imports `vllm._genesis`

Команда:

```bash
make audit
```

Фактический результат:

```text
legacy-import gate: 24 violation(s)
make: *** [audit-legacy-imports] Error 1
```

Ключевые файлы и строки:

- `tests/probes/verify_new_patches_all_models.py:30` — `from vllm._genesis.dispatcher import PATCH_REGISTRY, should_apply`
- `scripts/launch.sh:20` — `python3 -m vllm._genesis.compat.cli model-config list`
- `scripts/launch.sh:28` — `python3 -m vllm._genesis.compat.cli model-config render`
- `scripts/launch.sh:31` — `python3 -m vllm._genesis.compat.cli model-config validate`
- `scripts/launch.sh:34` — `python3 -m vllm._genesis.compat.cli model-config preflight`
- `scripts/launch.sh:47-48` — help text still points to `vllm._genesis.compat.cli`
- `scripts/launch.sh:54,58` — launch still uses `vllm._genesis.compat.cli`
- `scripts/validate_integration.sh:96-103` — imports/checks `vllm._genesis`
- `scripts/run_validation_suite.sh:125` — imports `vllm._genesis.model_detect`
- `tools/check_upstream_drift.py:235` — imports `vllm._genesis.patches.upstream_compat`
- `tools/genesis_vllm_plugin/pyproject.toml:40` — entrypoint points to `vllm._genesis.compat.cli`
- `tools/genesis_vllm_plugin/genesis_v7/__init__.py:77` — imports `vllm._genesis.patches.apply_all`
- `tools/external_probe/README.md` and example plugin docs still teach old namespace.

Проблема:

`vllm/_genesis` уже считается legacy/pre-v11 namespace, но часть scripts/tools/tests все еще исполняет или документирует старый импорт. Это ломает migration gate и может ломать fresh install, где `_genesis` больше не установлен.

Что сделать:

1. `scripts/launch.sh` перевести на новый CLI:

```bash
python3 -m vllm.sndr_core.cli config list
python3 -m vllm.sndr_core.cli config render "$KEY"
python3 -m vllm.sndr_core.cli config validate "$KEY"
python3 -m vllm.sndr_core.cli config preflight "$KEY"
python3 -m vllm.sndr_core.cli launch "$KEY"
```

2. `tests/probes/verify_new_patches_all_models.py` заменить на:

```python
from vllm.sndr_core.dispatcher.registry import PATCH_REGISTRY
from vllm.sndr_core.dispatcher.decision import should_apply
```

Точное имя модуля `should_apply` проверить по текущей структуре, но старый `vllm._genesis.dispatcher` оставить нельзя.

3. `tools/check_upstream_drift.py` перевести на `vllm.sndr_core.apply.upstream_compat` или актуальное место `UPSTREAM_MARKERS`.

4. Для исторических docs/examples либо заменить namespace, либо добавить узкий allowlist в `scripts/check_no_legacy_imports.py` только для явно архивных документов.

Acceptance:

```bash
make audit
```

должен проходить дальше legacy-import gate.

## P0. `SNDR_WORKSPACE_001` shadow mismatch все еще не закрыт

Команда:

```bash
python3 -m vllm.sndr_core.apply.shadow --strict
```

Фактический результат:

```text
spec_only_unexpected:
  - SNDR_WORKSPACE_001
legacy_unparseable:
  - 'SNDR_WORKSPACE_001 workspace grow-after-lock graceful fix'
DIVERGENT
```

Файлы:

- `vllm/sndr_core/dispatcher/registry.py:1193-1202`
- `vllm/sndr_core/apply/_per_patch_dispatch.py:904-918`
- `vllm/sndr_core/apply/shadow.py:65-121`

Текущее состояние:

```python
@register_patch("SNDR_WORKSPACE_001 workspace grow-after-lock graceful fix")
def apply_patch_sndr_workspace_001() -> PatchResult:
```

Проблема:

Дефис в legacy name уже убрали, но strict shadow parser все равно не распознает `SNDR_WORKSPACE_001`. Вероятная причина: `_patch_id_from_legacy_name()` в `shadow.py` знает обычные `P*`/`PN*` id, но не знает новый `SNDR_*` id class.

Что сделать:

Вариант A, правильный для будущих SNDR ids: расширить parser в `vllm/sndr_core/apply/shadow.py`, чтобы он принимал `SNDR_[A-Z0-9_]+` как валидный patch id.

Вариант B, если `SNDR_WORKSPACE_001` должен быть registry-only: добавить его в `KNOWN_SPEC_ONLY_PATCHES`. Но это хуже, потому что у него уже есть `@register_patch`, значит он не registry-only.

Acceptance:

```bash
python3 -m vllm.sndr_core.apply.shadow --strict
```

Ожидаемо: no `spec_only_unexpected`, no `legacy_unparseable`.

## P0. `make evidence` все еще блокирует release: 8 gating failures

Команда:

```bash
make evidence
```

Фактический результат:

```text
RELEASE BLOCKED — 8 gating gate(s) failed
```

Падающие gates:

| Gate | Причина |
|---|---|
| `audit` | падает на legacy imports |
| `audit-community` | Makefile вызывает несуществующую CLI-команду `community validate` |
| `audit-all-referents` | 6 AppleDouble `._*.py` не читаются как UTF-8 |
| `audit-readme-counters` | README line 404: `20 categories`, должно быть `21` |
| `audit-no-hardcoded-paths` | 10 hardcoded `/home/sander/...` в active compose |
| `audit-no-stub` | падает UnicodeDecodeError на `._*.py` |
| `audit-engine-boundary` | падает UnicodeDecodeError на `._*.py` |
| `audit-release-check` | 15 patches в bucket `dead`, policy `require-static` |

Плюс informational `audit-security` красный: `46` operator path hits.

## P0. `audit-community` сломан на уровне Makefile/CLI

Файл: `Makefile`

Строки: `139-140`

Текущий код:

```make
audit-community:
	@$(PYTHON) -m vllm.sndr_core.cli community validate
```

Фактический результат:

```text
sndr: error: invalid choice: 'community'
```

Проблема:

В текущем CLI нет subcommand `community`, но release gate уже на него завязан. Это не проблема данных, это несоответствие Makefile и CLI surface.

Что сделать:

Вариант A: реализовать `community validate` в `vllm.sndr_core.cli`.

Вариант B: заменить Makefile target на реально существующую команду/скрипт community validator, если он уже переименован.

Acceptance:

```bash
make audit-community
```

должен возвращать `0`.

## P0. AppleDouble `._*.py` файлы ломают scanners и compile

Файлы:

- `vllm/sndr_core/apply/.__per_patch_dispatch.py`
- `vllm/sndr_core/cache/.__pn95_disk_tier.py`
- `vllm/sndr_core/cache/.__pn95_runtime.py`
- `vllm/sndr_core/cli/._patches.py`
- `vllm/sndr_core/dispatcher/._registry.py`
- `vllm/sndr_core/integrations/worker/._sndr_workspace_001_grow_after_lock.py`

Симптомы:

```text
SyntaxError: source code string cannot contain null bytes
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xa3 ...
```

Падают:

- broad Python compile scan;
- `audit-all-referents`;
- `audit-no-stub`;
- `audit-engine-boundary`.

Проблема:

Это macOS resource fork / AppleDouble artifacts. Они не являются Python-кодом, но лежат рядом с `.py` и попадают в scanners.

Что сделать:

1. Удалить эти `._*.py` файлы из рабочей копии.
2. Добавить в `.gitignore`:

```gitignore
._*
.DS_Store
```

3. Усилить audit scripts: пропускать basename, начинающийся с `._`, и по возможности не падать на UnicodeDecodeError, а выдавать controlled finding.

Acceptance:

```bash
find . -name '._*' -type f
make audit-all-referents
make audit-no-stub
make audit-engine-boundary
```

## P0. Hardcoded operator paths в active compose

Команда:

```bash
make audit-no-hardcoded-paths
```

Фактический результат:

```text
10 hardcoded path(s) found
```

Файлы и строки:

- `compose/docker-compose.gemma4-26b-moe.yml:35-36`
- `compose/docker-compose.integration-awq.yml:113,120`
- `compose/docker-compose.integration-fp16kv.yml:113,120`
- `compose/docker-compose.integration.yml:113,120`
- `compose/docker-compose.qwen3-5-dense.yml:35-36`

Пример текущего кода:

```yaml
- /home/sander/Genesis_Project/vllm_engine/triton-cache:/root/.triton/cache
- /home/sander/Genesis_Project/vllm_engine/compile-cache-integration:/root/.cache/vllm/torch_compile_cache
```

Что сделать:

Заменить на env placeholders:

```yaml
- ${SNDR_TRITON_CACHE_DIR:-${HOME}/.cache/sndr/triton}:/root/.triton/cache
- ${SNDR_COMPILE_CACHE_DIR:-${HOME}/.cache/sndr/torch_compile_cache}:/root/.cache/vllm/torch_compile_cache
```

Для compose, который является историческим/архивным, перенести в archive и исключить из active scan только с явным header-comment justification.

Acceptance:

```bash
make audit-no-hardcoded-paths
python3 scripts/security_scan.py
```

## P0. Security scan снова красный

Команда:

```bash
python3 scripts/security_scan.py
```

Результат:

```text
923 tracked files scanned
operator_paths: 46 hit(s)
FAIL — 46 total violations
```

Проблема:

Часть hits относится к тем же compose/scripts path violations. Security scanner шире `audit-no-hardcoded-paths`: видит также архивные scripts, tests, old `_genesis` paths и другие tracked references.

Что сделать:

1. Для active runtime/config файлов заменить `/home/sander/...` на env placeholders.
2. Для архивных/исторических файлов:
   - либо перенести под явно excluded archive;
   - либо добавить точечный allowlist с причиной.
3. Не allowlist-ить active compose без причины: это реальная portability проблема.

## P0. `launch --check-deps` все еще false-positive

Команды:

```bash
python3 -m vllm.sndr_core.cli deps plan --config a5000-2x-35b-prod --json
python3 -m vllm.sndr_core.cli launch a5000-2x-35b-prod --preflight-only --check-deps
```

Фактическое состояние:

- `deps plan`: `is_ready=false`, `n_blockers=3`;
- blockers: Docker missing, NVIDIA/nvidia-smi missing, model directory missing;
- `launch --check-deps`: возвращает `0` и пишет `all checks passed`.

Файл:

`vllm/sndr_core/cli/launch.py:390-422`, `510-514`

Что сделать:

`launch --check-deps` должен использовать canonical deps planner, а не только caveats matcher. При `plan.blockers()` команда должна вернуть non-zero.

Acceptance на текущей локальной машине:

```bash
python3 -m vllm.sndr_core.cli launch a5000-2x-35b-prod --preflight-only --check-deps
```

должен вернуть non-zero и напечатать Docker/NVIDIA/model blockers.

## P0/P1. Release-check блокирует 15 dead patches

Команда:

```bash
make audit-release-check
```

Результат:

```text
considered=151/151  passed=136  failed=15
RELEASE BLOCKED — policy='require-static'
```

Dead patches:

- `SNDR_WORKSPACE_001`
- `PN202`
- `PN203`
- `PN200`
- `PN201`
- `PN106`
- `PN105`
- `PN104`
- `PN97`
- `PN92`
- `PN71`
- `PN73`
- `PN91`
- `PN204`
- `PN108`

Что сделать:

Для каждого patch выбрать один путь:

- добавить static proof artefact;
- добавить bench artefact;
- оформить formal allowlist только для research/experimental;
- перевести в retired/skipped, если patch не должен участвовать в release.

Важно: `audit-patches-prove-all` уже зеленый, но `release-check` работает по другой, более строгой policy. Нельзя считать proof полностью закрытым, пока `audit-release-check` красный.

## P1. README counter drift: category count

Команда:

```bash
make audit-readme-counters
```

Файл: `README.md`

Строка: `404`

Текущий текст:

```markdown
### Patch coverage — 151 patches across 20 categories
```

Должно быть:

```markdown
### Patch coverage — 151 patches across 21 categories
```

Acceptance:

```bash
make audit-readme-counters
```

## P1. Dirty state улучшился, но release freeze еще не закрыт

Текущий status:

```text
M 13
?? 411
total 424
```

По сравнению с прошлым срезом:

- удаленные `D 384` исчезли из status;
- modified уменьшились до `13`;
- untracked остаются большими: `411`.

`make audit-dirty-state-dev` проходит:

```text
entries=424 accepted=424 rejected=0
```

Но это dev-tier. Для release нужен отдельный clean/frozen state.

## Что сейчас выглядит здоровым

- `self-test`: `8/8`;
- registry schema: `151` clean entries;
- wiring imports: `138`;
- lifecycle audit: `151`, no unknown lifecycle states;
- categories build: `151 patches -> 22 categories`;
- doc-sync registry count: `151`;
- V1 freeze: `12/12`;
- configs: `11/11`;
- shell syntax: `72/72`;
- `audit-patches-prove-all`: pass;
- major V2 config gates в `make evidence` проходят.

## Рекомендуемый порядок следующих исправлений

1. Удалить AppleDouble `._*.py` файлы и добавить ignore/protection.
2. Исправить `SNDR_WORKSPACE_001` shadow parser или registry/apply mapping.
3. Закрыть legacy imports `vllm._genesis` в active scripts/tools/tests.
4. Исправить `audit-community`: реализовать CLI command или поправить Makefile target.
5. Заменить hardcoded `/home/sander/...` в active compose на env placeholders.
6. Синхронизировать README category counter `20 -> 21`.
7. Исправить `launch --check-deps` false-positive.
8. Довести 15 dead patches до release-acceptable proof state.
9. Повторить:

```bash
python3 -m vllm.sndr_core.compat.cli self-test --json
python3 -m vllm.sndr_core.apply.shadow --strict
python3 -m vllm.sndr_core.cli patches prove --dead-detect --json
make audit
make evidence
python3 scripts/security_scan.py
make audit-dirty-state-release
```

## Production readiness

Текущая оценка: `58/100`.

Почему не выше:

- `make evidence` красный;
- `make audit` красный;
- security scan красный;
- shadow strict красный;
- release-check красный;
- preflight deps false-positive;
- AppleDouble мусор ломает scanners.

Почему выше прошлого среза:

- self-test/schema снова зеленые;
- doc-sync закрыт;
- V1 freeze закрыт;
- proof-all gate закрыт;
- dirty state заметно чище.
