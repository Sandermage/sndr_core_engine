# Предложения, правки и замены для усиления PROJECT_ROADMAP_V2

Дата: 2026-05-12  
Назначение: рабочая записка для доработки основного файла `PROJECT_ROADMAP_V2_2026-05-12_RU.md`.  
Формат: конкретные замены, дополнения, уточнения, причины, эффект, плюсы, минусы и критерии приемки.  

Этот документ не заменяет основной roadmap. Его смысл - дать список точных правок, по которым можно улучшить master plan без потери уже сделанной структуры.

## Общий вывод

Обновленный roadmap уже стал достаточно зрелым: появились evidence gate, RuntimeCommandSpec, security/license boundary, `memory explain` MVP, patch proof, benchmark methodology, dirty-state policy и external findings pipeline.

Оставшиеся проблемы не стратегические, а в основном **согласовательные**:

- старые строки не везде обновлены после добавления новых фаз;
- некоторые статусы конфликтуют с новыми policy;
- execution order не полностью отражает Phase 4.5/4.6/4.7 и split Phase 8;
- есть места, где acceptance требует команды или файлы, но phase deliverables описаны не до конца;
- часть терминологии CLI не унифицирована.

Главная цель следующего обновления: сделать roadmap не просто полным, а **внутренне непротиворечивым**.

## Приоритеты исправления

| Приоритет | Что исправить | Почему важно |
|---|---|---|
| P0 | Убрать устаревший `memory explain` из deferred/research в §3.4 | Сейчас конфликт с Phase 4.7 |
| P0 | Добавить Phase 4.5/4.6/4.7 в execution priority | Иначе новые design docs есть, но в порядке работ их нет |
| P0 | Уточнить Phase 8a/8b в execution priority | Split описан хорошо, но финальный order еще старый |
| P0 | Убрать `example placeholder` из Phase 5 | Конфликт с no-placeholder policy |
| P1 | Уточнить `release_allowlist.txt` generation | Dirty-state gate должен быть реализуемым |
| P1 | Заменить `tail -3` в evidence/sync recipe на full log + excerpt | Иначе теряется причина падения |
| P1 | Унифицировать `sndr patch` vs `sndr patches` | CLI должен быть последовательным |
| P1 | Переименовать `Open questions (none)` | Блокирующих решений нет, но implementation questions есть |
| P2 | Добавить owner/status/evidence metadata в новые design phases | Упростит параллельную работу |

## P0. Исправить устаревший статус `sndr memory explain`

### Текущая проблема

В разделе `3.4 P1 — CLI gaps` осталась строка:

```markdown
| `sndr memory explain` Phase 2-4 | 2-4w each | Research-level, deferred |
```

Но ниже уже добавлена:

```markdown
### Phase 4.7 — `sndr memory explain` MVP (Day 13, P1)
```

Это прямое противоречие: одна часть roadmap говорит "deferred research", другая - "P1 MVP".

### Как заменить

Заменить строку в `3.4` на:

```markdown
| `sndr memory explain` MVP | 1d | Phase 4.7: weights/KV/cudagraph/fragmentation/OOM estimate; research extensions stay P3 |
```

И отдельно добавить в `3.10 P3 — Memory / PN95 long-term`:

```markdown
| `sndr memory explain` advanced calibration | 2-4w | GPU-measured calibration, allocator telemetry, tier-aware KV prediction |
```

### Почему это нужно

`memory explain` - не второстепенная research-фича. Для пользователей A5000/3090 это одна из самых полезных функций core: понять заранее, где будет OOM, какой context выбрать, какие настройки опасны.

### Что дает

- roadmap становится согласованным;
- MVP получает правильный приоритет;
- research-часть не исчезает, а уезжает в P3;
- core получает сильную практическую утилиту.

### Плюсы

- высокая пользовательская ценность;
- небольшая правка документа;
- хорошо соответствует стратегии "core дает полезный минимум".

### Минусы

- добавляет P1 нагрузку;
- MVP должен честно показывать uncertainty, иначе будет вводить в заблуждение.

### Критерий приемки

В roadmap нет строки, где `sndr memory explain` целиком помечен как deferred. Deferred только advanced/research extensions.

## P0. Добавить Phase 4.5/4.6/4.7 в execution priority

### Текущая проблема

В roadmap появились новые фазы:

- `Phase 4.5 — RuntimeCommandSpec canonical IR`;
- `Phase 4.6 — Security + license gate boundary`;
- `Phase 4.7 — sndr memory explain MVP`.

Но в `Execution priority order` они не отражены отдельными пунктами.

### Как заменить

В секции `Day 7-15 (P1)` вместо:

```markdown
5. Phase 4 (CLI updates, 2d).
6. Phase 5 (community SDK, 3-4d).
```

сделать:

```markdown
5. Phase 4 (CLI updates, 2d).
6. Phase 4.5 (RuntimeCommandSpec canonical IR, 1-2d).
7. Phase 4.6 (Security/license boundary, 1d).
8. Phase 4.7 (`sndr memory explain` MVP, 1d).
9. Phase 5 (community SDK, 3-4d).
```

После этого перенумеровать следующие пункты.

### Почему это нужно

Новые фазы закрывают важные architecture gaps. Если они не попали в final execution order, исполнитель может их пропустить или отложить, хотя они уже стали частью master plan.

### Что дает

- порядок работ соответствует содержанию roadmap;
- RuntimeCommandSpec не потеряется;
- security/license boundary не останется "дизайн-документом без фазы";
- `memory explain` MVP попадет в реальный план.

### Плюсы

- простая организационная правка;
- снижает риск пропуска важных фаз;
- делает roadmap исполнимым.

### Минусы

- Day 7-15 станет плотнее;
- возможно потребуется пересчитать сроки.

### Критерий приемки

Каждая фаза, имеющая заголовок в `Phased execution plan`, имеет отражение в `Execution priority order`.

## P0. Исправить Phase 8 в execution priority

### Текущая проблема

В плане Phase 8 правильно разделена:

- Phase 8a - ранний V1 cold-install smoke;
- Phase 8b - поздний V2 acceptance smoke.

Но в execution priority все еще есть общий пункт:

```markdown
3. Phase 8 smoke (cold install + launcher, 0.5d).
```

Это упрощает и частично ломает смысл split.

### Как заменить

В `Day 1-6`:

```markdown
1. Phase 8a (V1 cold-install smoke, 0.5d) — pre-V2 gate.
2. Phase 1 (V2 schema + composer + tests, 4-5d).
3. Phase 2 (POC migration, 1d).
```

В `Day 16-20`:

```markdown
10. Phase 8b (V2 acceptance smoke, 0.5d) — post-Phase 7 gate.
11. Phase 9 (V1 freeze, 0.5d).
```

### Почему это нужно

Phase 8a и Phase 8b проверяют разные вещи:

- 8a доказывает, что существующий workflow жив до V2;
- 8b доказывает, что V2 workflow готов после миграции.

Смешивать их обратно нельзя.

### Что дает

- четкий rollback baseline до V2;
- поздний acceptance не исчезает;
- легче диагностировать, что сломала V2-миграция.

### Плюсы

- повышает управляемость миграции;
- защищает существующий workflow;
- уменьшает release-риск.

### Минусы

- требует двух smoke-прогонов;
- timeline нужно чуть уточнить.

### Критерий приемки

В execution order нет общего `Phase 8 smoke`; есть отдельные `Phase 8a` и `Phase 8b`.

## P0. Заменить `example placeholder` в Phase 5

### Текущая проблема

В Phase 5 написано:

```markdown
plugins/community/.gitkeep + example placeholder.
```

Но §6.6 запрещает placeholders на main/release. Даже если автор имел в виду template example, слово `placeholder` конфликтует с policy.

### Как заменить

```markdown
plugins/community/.gitkeep + template-only example excluded from release registry.
```

И добавить:

```markdown
Template examples may be used by `sndr community new-patch`, but they are
not loaded as patches and never appear in `sndr patches list` unless
published through manifest validation.
```

### Почему это нужно

No-placeholder policy должна быть однозначной. Если в roadmap остается `placeholder`, gate будет выглядеть непоследовательным.

### Что дает

- community SDK остается удобным;
- release registry остается чистым;
- no-stub policy становится непротиворечивой.

### Плюсы

- простая текстовая правка;
- убирает конфликт;
- сохраняет обучающие templates.

### Минусы

- нужно следить, чтобы template examples реально не попадали в registry.

### Критерий приемки

Слово `placeholder` не используется для deliverables, которые попадают в release tree или patch registry.

## P1. Описать генерацию `release_allowlist.txt`

### Текущая проблема

В dirty-state policy используется:

```bash
git status --porcelain | grep -v -f release_allowlist.txt
```

Но не описано, откуда берется `release_allowlist.txt`: файл tracked, generated, temporary или часть `scripts/check_dirty_state.py`.

### Как уточнить

Добавить в `LOCAL_SERVER_ALLOWED_DIRTY_STATE`:

```markdown
`release_allowlist.txt` is generated by `scripts/check_dirty_state.py`
from §2.3 repo-local allowlist into `/tmp/sndr-release-allowlist.txt`.
It is not committed and not edited manually.
```

Или, если файл должен быть tracked:

```markdown
Tracked source: `scripts/dirty_state_release_allowlist.txt`.
Docs §2.3 and this file must match; CI verifies sync.
```

### Рекомендация

Лучше сделать generated temporary file. Источник истины должен быть в коде/конфиге, а markdown - документация. Еще лучше:

```yaml
tools/policies/dirty_state_allowlist.yaml
```

А markdown описывает его.

### Почему это нужно

Acceptance command должна быть исполнимой. Если файл не существует, gate не работает.

### Что дает

- dirty-state check становится реализуемым;
- меньше ручных файлов;
- понятнее CI.

### Плюсы

- убирает ambiguity;
- упрощает реализацию script;
- подходит для local/server.

### Минусы

- нужно выбрать source of truth;
- markdown и code могут разойтись, если не сделать sync-test.

### Критерий приемки

Команда release dirty-state check работает на clean clone без ручного создания `release_allowlist.txt`.

## P1. Полный лог вместо `tail -3` в evidence/sync

### Текущая проблема

В safe sync recipe последняя проверка:

```bash
python3 -m pytest tests/ -q --ignore=tests/integration | tail -3
```

Для визуального просмотра это удобно, но для evidence это плохо: причина падения может быть выше в логе.

### Как заменить

```bash
mkdir -p /tmp/sndr-evidence
python3 -m pytest tests/ -q --ignore=tests/integration \
  2>&1 | tee /tmp/sndr-evidence/pytest_after_sync.log
tail -20 /tmp/sndr-evidence/pytest_after_sync.log
```

В ledger записывать:

- path to full log;
- tail excerpt;
- rc;
- command;
- commit.

### Почему это нужно

Evidence должен позволять расследовать failure, а не только видеть последние строки.

### Что дает

- диагностика становится лучше;
- server sync становится проверяемым;
- меньше повторных запусков.

### Плюсы

- простая правка;
- повышает качество evidence;
- не мешает краткому выводу.

### Минусы

- нужно чистить старые `/tmp/sndr-evidence`;
- логи могут быть большими.

### Критерий приемки

Каждая sync/evidence проверка сохраняет полный лог и отдельно показывает короткий excerpt.

## P1. Унифицировать CLI namespace: `patch` или `patches`

### Текущая проблема

В roadmap встречается:

```bash
sndr patch prove
```

Но исторически и в других местах проекта используется plural namespace:

```bash
sndr patches doctor
```

### Как решить

Рекомендуемый вариант:

```bash
sndr patches prove <id>
sndr patches prove --all
sndr patches prove --dead-detect
sndr patches doctor
sndr patches list
```

Если хочется короткий alias:

```bash
sndr patch prove
```

можно оставить как hidden alias, но docs должны использовать один canonical вариант.

### Почему это нужно

CLI consistency напрямую влияет на удобство и ощущение качества.

### Что дает

- меньше путаницы;
- проще документация;
- проще тестировать CLI help;
- меньше breaking changes.

### Плюсы

- маленькая правка;
- лучше UX;
- меньше конфликтов с текущей историей проекта.

### Минусы

- если уже реализован singular namespace, нужен alias/deprecation.

### Критерий приемки

В public docs и roadmap используется один canonical namespace. CLI help подтверждает его.

## P1. Уточнить Phase 8a команды под текущий V1

### Текущая проблема

В Phase 8a используется:

```bash
sndr hardware list
sndr launch prod-35b --preflight-only
```

Но нужно проверить: эти команды уже существуют в V1 workflow или являются частью V2 discovery/alias layer.

### Что сделать

Если команды уже существуют - оставить.

Если нет, заменить Phase 8a на реально существующий V1 smoke:

```bash
sndr configs list
sndr launch a5000-2x-35b-prod --preflight-only
```

А V2 aliases оставить для Phase 8b:

```bash
sndr hardware list
sndr launch prod-35b --preflight-only
```

### Почему это нужно

Phase 8a должна доказывать, что текущий workflow жив до V2 изменений. Она не должна зависеть от будущего V2 CLI.

### Что дает

- честный pre-V2 baseline;
- меньше false failures;
- проще rollback.

### Плюсы

- делает Phase 8a технически корректной;
- помогает сравнить V1 и V2.

### Минусы

- может потребоваться два набора команд в документации.

### Критерий приемки

Все команды Phase 8a выполняются на текущем V1 коде до Phase 1.

## P1. Переименовать `Open questions (none for V2 design)`

### Текущая проблема

Раздел говорит:

```markdown
## 11. Open questions (none for V2 design)
```

Но в roadmap уже есть implementation-level вопросы: CLI namespace, exact V1 smoke commands, allowlist generation, artifacts policy, security fixtures, etc.

### Как заменить

```markdown
## 11. Blocking design questions

No blocking operator-level V2 design questions remain. Implementation
questions are tracked per phase as metadata fields:
Owner / Status / Evidence / Blocked by / Acceptance.
```

### Почему это нужно

Фраза "none" может дать ложное ощущение, что вообще вопросов нет. Лучше точнее: нет блокирующих design decisions, но implementation details еще отслеживаются.

### Что дает

- честнее отражает состояние;
- не обесценивает мелкие вопросы;
- лучше для параллельной работы.

### Плюсы

- точная формулировка;
- меньше риска пропуска implementation gaps.

### Минусы

- документ становится менее "закрытым", но более честным.

### Критерий приемки

Раздел не утверждает, что вопросов нет вообще; он отделяет blocking design questions от implementation questions.

## P1. Добавить owner/status/evidence metadata к Phase 4.5/4.6/4.7

### Текущая проблема

Новый metadata convention появился, но его нужно применить к самым важным новым фазам.

### Как добавить

Для каждой из Phase 4.5/4.6/4.7:

```markdown
Owner: sandermage
Status: planned
Evidence: pending, will be recorded in ROADMAP_EVIDENCE_LEDGER
Blocked by: Phase 4 CLI baseline
Acceptance: listed below
```

### Почему это нужно

Новые фазы критичные. У них должен быть явный status/evidence, чтобы они не остались design-doc-only.

### Что дает

- лучше tracking;
- проще работа другого инженера;
- быстрее ревью.

### Плюсы

- простая текстовая правка;
- повышает управляемость.

### Минусы

- нужно поддерживать статусы.

### Критерий приемки

Все новые фазы имеют metadata по конвенции из §5.-1.

## P2. Уточнить место `EXTERNAL_FINDINGS_PIPELINE`

### Текущая проблема

Roadmap ссылается на `EXTERNAL_FINDINGS_PIPELINE` как deferred deliverable Phase 10. Это нормально, но полезно добавить минимальный ранний artifact уже до Phase 10.

### Что сделать

Добавить в Phase 0 или Phase 7:

```markdown
Create empty `docs/_internal/external_findings/README.md` with schema
and one tracked example finding for vLLM #42102 in status `watch`.
```

### Почему это нужно

Если pipeline появится только в Phase 10, external watch снова будет ручным до конца V2 migration.

### Что дает

- vLLM PR #42102 и club findings не потеряются;
- external research становится структурированным раньше;
- проще связывать patch roadmap с upstream.

### Плюсы

- низкая стоимость;
- хорошая дисциплина;
- можно развивать постепенно.

### Минусы

- добавляет еще один internal tracking слой;
- нужно не забывать обновлять statuses.

### Критерий приемки

Есть хотя бы один structured finding по vLLM #42102 и команда/процесс для validation.

## P2. Уточнить release artifacts и storage policy

### Текущая проблема

В roadmap есть разные artifacts:

- evidence ledger;
- patch proof JSON;
- bench results;
- report bundle;
- SBOM;
- security attestation;
- snapshots.

Но не полностью описано, что хранится в repo, что вне repo, что попадает в release, что redacted.

### Что добавить

Таблица:

| Artifact | Location | Tracked | Release artifact | Redacted | Retention |
|---|---|---:|---:|---:|---|
| Evidence ledger | `docs/_internal` | no/public? | internal only | yes if exported | keep |
| Patch proof | `evidence/patch_proof` | maybe | yes for release | yes | per release |
| Bench results | `~/.sndr/bench-results` | no | optional summary | yes | rolling |
| SBOM | `release/` | yes per tag | yes | no secrets | per tag |
| Security attestation | `release/` | yes per tag | yes | yes | per tag |
| Report bundle | generated | no | operator-provided | yes | manual |

### Почему это нужно

Иначе artifacts начнут случайно попадать в repo или наоборот теряться.

### Что дает

- чище git;
- понятный release process;
- меньше утечек;
- проще support.

### Плюсы

- повышает release maturity;
- хорошо связано с security gate.

### Минусы

- нужно поддерживать retention rules;
- часть artifacts надо генерировать.

### Критерий приемки

Каждый artifact из roadmap имеет location, tracked/untracked policy и retention rule.

## P2. Добавить rollback playbook как явный deliverable Phase 7

### Текущая проблема

Roadmap требует `docs/ROLLBACK_PLAYBOOK.md`, но стоит проверить, что он явно входит в deliverables.

### Что сделать

В Phase 7 добавить:

```markdown
`docs/ROLLBACK_PLAYBOOK.md` — V1 fallback, V2 disable switch,
community SDK disable switch, patch pack disable switch, server restore
from pre-sync snapshot.
```

### Почему это нужно

Rollback нельзя оставлять как абстрактный acceptance item. Его нужно написать до freeze.

### Что дает

- меньше риска при V2 migration;
- проще server recovery;
- лучше production readiness.

### Плюсы

- практично;
- сильно помогает оператору;
- снижает страх перед migration.

### Минусы

- требует поддерживать playbook при изменении CLI.

### Критерий приемки

Rollback playbook содержит конкретные команды и smoke test после rollback.

## Предлагаемый порядок обновления основного roadmap

### Шаг 1. Быстрые текстовые исправления

1. Заменить строку `sndr memory explain Phase 2-4`.
2. Убрать `example placeholder`.
3. Переименовать `Open questions`.
4. Унифицировать `sndr patch`/`sndr patches`.

### Шаг 2. Execution order

1. Добавить Phase 4.5/4.6/4.7 в порядок.
2. Разделить Phase 8a и 8b в финальном списке.
3. Пересчитать нумерацию пунктов.

### Шаг 3. Policy детализация

1. Описать generation/source для `release_allowlist.txt`.
2. Полный лог вместо `tail -3`.
3. Добавить artifact storage policy.

### Шаг 4. Deliverables

1. Явно добавить rollback playbook в Phase 7.
2. Добавить early external finding по vLLM #42102.
3. Добавить metadata к Phase 4.5/4.6/4.7.

## Мое итоговое мнение

Текущий roadmap уже достаточно сильный, чтобы быть главным планом проекта. Его не нужно переписывать заново. Нужно сделать **точечную нормализацию**: убрать старые остатки после обновлений, согласовать новые фазы с execution order, закрепить artifact policy и сделать несколько формулировок более строгими.

Самые важные правки перед стартом Phase 1:

1. `memory explain` больше не deferred, MVP идет в Phase 4.7.
2. Phase 4.5/4.6/4.7 должны попасть в execution priority.
3. Phase 8a/8b должны быть отражены в финальном порядке отдельно.
4. Placeholder должен исчезнуть из deliverables.
5. Dirty-state allowlist должен быть технически реализуемым.
6. Evidence должен сохранять full logs, не только хвост.

После этих правок roadmap будет выглядеть цельным и готовым для реальной работы: Phase 0 → Phase 8a → V2 schema/composer → runtime/security/memory utilities → community SDK → V2 acceptance → V1 freeze.
