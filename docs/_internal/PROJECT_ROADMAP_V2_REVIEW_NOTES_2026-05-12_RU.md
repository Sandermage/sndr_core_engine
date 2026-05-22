# Уточнения и замечания к обновленному PROJECT_ROADMAP_V2

Дата: 2026-05-12  
Проверенные файлы:

- `docs/_internal/PROJECT_ROADMAP_V2_2026-05-12_RU.md`
- `docs/_internal/LOCAL_SERVER_ALLOWED_DIRTY_STATE_2026-05-12_RU.md`

Тип документа: отдельные замечания, дополнения, ошибки и упущения.  
Существующие файлы roadmap/policy этим документом не изменяются.

## Краткое резюме

Обновленный roadmap стал заметно сильнее. В нем появились важные элементы, которых раньше не хватало:

- Phase 0 `Roadmap Truth / Evidence Gate`;
- split Phase 8 на ранний V1 smoke и поздний V2 acceptance;
- dirty-state policy для local/server;
- no-stub/no-placeholder policy;
- env-key registry;
- patch proof gate;
- benchmark methodology contract;
- расширенный risk registry;
- production-ready definition.

Это правильное направление. Сейчас roadmap уже похож на рабочий master plan, а не просто список задач.

Но текущая версия все еще содержит несколько противоречий и недостающих gates. Их лучше исправить до начала большой V2-миграции, иначе часть ошибок переедет в новую структуру и станет дороже.

## Итоговая оценка

| Область | Оценка | Комментарий |
|---|---:|---|
| Архитектурное направление | 8/10 | V2 layering и runtime в hardware layer выбраны правильно |
| Управление качеством | 7/10 | Gates появились, но часть еще декларативная |
| Production readiness | 6.5/10 | План правильный, но release/security/runtime gaps еще открыты |
| Local/server discipline | 8/10 | Dirty-state policy сильно улучшила ситуацию |
| Patch lifecycle | 7/10 | Patch proof появился, но threshold и artifact policy надо уточнить |
| Документация/release hygiene | 7/10 | Stale scan есть, public/private boundary нужно усилить |

Мое мнение: roadmap можно использовать как основной план, но перед Phase 1 нужно сделать короткий cleanup-документ/commit по самому roadmap: убрать противоречия, уточнить статусы, закрыть RuntimeCommandSpec/security/memory explain MVP.

## P0. Убрать hardcoded test counts из roadmap

### Что не так

В roadmap одновременно встречаются разные цифры:

- baseline table: `Local 5544 passed`, `Server 5574 passed`;
- Phase 0: `5622 local / 5652 server`;
- acceptance: уже правильно говорит `see evidence ledger`.

Даже если все цифры были верны в разные моменты, в одном master plan они создают неоднозначность.

### Почему это важно

Test count меняется после добавления/удаления тестов. Если roadmap хранит живые цифры, он быстро устаревает и начинает противоречить evidence ledger.

### Что сделать

В roadmap заменить конкретные числа на:

```markdown
Актуальный baseline хранится только в
`docs/_internal/ROADMAP_EVIDENCE_LEDGER_2026-05-12_RU.md`.
Roadmap не дублирует test counts, чтобы не создавать устаревшие claims.
```

В Phase 0 заменить:

```markdown
Initial baseline entry — current state (5622 local / 5652 server / audit clean).
```

на:

```markdown
Initial baseline entry — current state captured in evidence ledger
for both local and server.
```

### Что это дает

- roadmap не устаревает после каждого тестового изменения;
- evidence ledger становится настоящим source of truth;
- local/server сравнение становится проверяемым;
- меньше ложных claims о production readiness.

### Плюсы

- простая правка;
- сразу повышает строгость документа;
- меньше риск расхождения с реальностью.

### Минусы

- придется открыть ledger, чтобы увидеть конкретные числа;
- release summary должен подтягивать counts из evidence ledger.

### Влияние на проект

Высокое. Это улучшает доверие к roadmap и снижает риск принятия решений по устаревшим цифрам.

## P0. Привести scaffold/placeholder/status к одной политике

### Что не так

В roadmap есть:

- `implementation_status: scaffold` в manifest example;
- `sndr profile new ... # scaffold delta profile`;
- Phase 5: `plugins/community/.gitkeep + example placeholder`;
- §6.6 запрещает placeholder и ограничивает scaffold только generator/templates.

Это внутреннее противоречие.

### Почему это важно

Для patcher-проекта опасно показывать заготовки как функциональность. Пользователь или contributor может принять scaffold/placeholder за рабочий patch.

### Что сделать

В manifest example заменить:

```yaml
implementation_status: scaffold
```

на:

```yaml
implementation_status: experimental
publish_state: draft
```

Для CLI использовать формулировку:

```text
sndr profile new <name> --parent-model <m>       # generate draft delta profile
```

Для Phase 5 заменить:

```markdown
plugins/community/.gitkeep + example placeholder
```

на:

```markdown
plugins/community/.gitkeep + template-only example excluded from release registry
```

### Что это дает

- release registry не содержит ложных сущностей;
- community SDK остается удобным, но честным;
- no-stub gate не конфликтует с собственным roadmap;
- меньше риска технического долга.

### Плюсы

- повышает качество public API;
- делает статусы понятными;
- снижает риск "мертвых" patches.

### Минусы

- нужно аккуратно переписать examples;
- придется сделать настоящий minimal example вместо placeholder.

### Влияние на проект

Высокое. Это прямо влияет на доверие к public core и registry.

## P0. Уточнить dirty-state release allowlist

### Что не так

В `LOCAL_SERVER_ALLOWED_DIRTY_STATE` release allowlist содержит:

```text
~/.sndr/bench-results/*.json
```

Но это путь вне git worktree. Он не появляется в `git status --porcelain`, поэтому не должен быть частью release dirty-state allowlist.

### Почему это важно

Dirty-state policy должна проверять состояние репозитория. Host-level artifacts должны быть описаны отдельно, иначе смешиваются два разных класса:

- tracked/untracked files внутри repo;
- runtime artifacts вне repo.

### Что сделать

В release allowlist оставить только repo-local patterns:

```text
snapshots/<ISO>/
evidence/patch_proof/*.json
```

А `~/.sndr/bench-results/*.json` перенести в отдельный раздел:

```markdown
Host artifacts allowed outside worktree:
- ~/.sndr/bench-results/*.json
- ~/.cache/sndr/*

Эти файлы не участвуют в git dirty-state check, но могут быть
проверены report bundle / evidence ledger.
```

### Что это дает

- policy становится технически точной;
- release check проще реализовать;
- не смешиваются git state и host runtime state.

### Плюсы

- меньше ложной логики в проверках;
- проще `check_dirty_state.py`;
- понятнее для другого инженера.

### Минусы

- нужен отдельный host-artifact policy;
- report bundle должен уметь ссылаться на внешние artifacts.

### Влияние на проект

Среднее. Это не ломает архитектуру, но делает release gate правильнее.

## P0. Сделать sync recipe безопасной

### Что не так

В dirty-state policy sync recipe использует:

```bash
rsync -avh --delete ...
```

Как инструкция по умолчанию это опасно. `--delete` может стереть server-only результаты или изменения другого агента, если человек выполнит команду без dry-run и snapshot.

### Почему это важно

Проект уже ведется в dual-state режиме: local и server оба важны. Сервер может содержать runtime artifacts, логи, результаты проверок или изменения другого агента.

### Что сделать

Заменить sync recipe на безопасный порядок:

```bash
# 1. Server snapshot before sync
ssh server 'cd /path/to/genesis-vllm-patches && git status --porcelain && git diff --stat'

# 2. Dry-run first
rsync -avhn --delete --exclude='.git' \
  /local/path/genesis-vllm-patches/ \
  server:/path/to/genesis-vllm-patches/

# 3. Review output manually

# 4. Only then real sync
rsync -avh --delete --exclude='.git' \
  /local/path/genesis-vllm-patches/ \
  server:/path/to/genesis-vllm-patches/
```

Добавить правило:

```markdown
If server has uncommitted unique tracked changes, sync is blocked until
they are copied back, committed, or explicitly archived.
```

### Что это дает

- меньше риска потерять server-only работу;
- safe workflow для другого инженера;
- лучше audit trail;
- меньше конфликтов между агентами.

### Плюсы

- высокая практическая безопасность;
- почти не усложняет процесс;
- подходит для release discipline.

### Минусы

- sync занимает больше шагов;
- нужен человек/оператор для review dry-run.

### Влияние на проект

Высокое для dual-state workflow. Это снижает риск потери данных.

## P1. Добавить RuntimeCommandSpec как обязательный архитектурный контракт

### Что не так

Roadmap правильно решил, что runtime живет в hardware layer. Но пока не зафиксирован единый объект, из которого строятся:

- Docker command;
- Compose YAML;
- Quadlet unit;
- K8s manifest;
- Proxmox LXC/VM plan;
- bare-metal systemd;
- dry-run output;
- report bundle;
- docs examples.

Без такого контракта runtime layer снова может расползтись по emitters.

### Почему это важно

Launcher/install/config - один из главных user-facing слоев проекта. Если dry-run показывает одно, docs другое, а launcher запускает третье, проект будет выглядеть нестабильным.

### Что сделать

Добавить в roadmap отдельный deliverable:

```python
@dataclass(frozen=True)
class RuntimeCommandSpec:
    runtime: str
    image: str | None
    image_digest: str | None
    env: dict[str, str]
    mounts: list[MountSpec]
    ports: list[PortSpec]
    devices: list[DeviceSpec]
    ulimits: dict[str, str]
    shm_size: str | None
    security: SecuritySpec
    command: list[str]
```

И acceptance:

```bash
sndr launch prod-35b --dry-run --runtime docker
sndr launch prod-35b --dry-run --runtime compose
sndr launch prod-35b --dry-run --runtime quadlet
sndr launch prod-35b --dry-run --runtime kubernetes
sndr report bundle --dry-run --redact
```

Все команды должны выводить данные из одного composed spec.

### Что это дает

- единый источник истины;
- меньше runtime drift;
- проще тестировать emitters;
- проще добавлять Proxmox/K8s;
- report bundle становится точнее.

### Плюсы

- профессиональная архитектура;
- хорошо масштабируется;
- уменьшает дублирование.

### Минусы

- потребует аккуратной миграции существующего launcher/deploy кода;
- может вскрыть несовместимости в текущих configs.

### Влияние на проект

Очень высокое. Это ключевой элемент превращения проекта из набора утилит в цельный runtime/config engine.

## P1. Поднять `sndr memory explain` до MVP в ранние фазы

### Что не так

В roadmap `sndr memory explain` остается deferred/research-level на 2-4 недели. Для проекта, ориентированного на A5000/3090, long context, KV cache, TQ, DFlash и MTP, это слишком поздно.

### Почему это важно

Пользовательская ценность проекта не только в patches, но и в ответе на вопрос:

```text
Какая модель запустится на моих картах, с каким context, batch и риском OOM?
```

### Что сделать

Сделать MVP раньше, без сложной research-части:

```bash
sndr memory explain --profile prod-35b
sndr memory explain --model <id> --hardware a5000-2x --ctx 32768 --tp 2
```

MVP должен считать:

- weights estimate;
- KV cache estimate;
- cudagraph reserve;
- activation reserve;
- quantization overhead;
- fragmentation reserve;
- host RAM/swap warning;
- Docker shm warning;
- recommended context/concurrency range.

### Что это дает

- меньше OOM;
- быстрее onboarding;
- лучше community configs;
- сильная бесплатная core-фича;
- база для будущих private engine optimizations.

### Плюсы

- высокая практическая ценность;
- можно реализовать постепенно;
- не требует сразу сложных patches.

### Минусы

- оценки будут приблизительными;
- нужны calibration data;
- нужно честно показывать uncertainty.

### Влияние на проект

Высокое. Это одна из функций, которая может реально "привязать" пользователей к core без закрытия кода.

## P1. Усилить security/license gate

### Что не так

Roadmap упоминает trust anchor rotation, но security model пока слабее остальных частей. Для будущего private engine и криптографического ключа нужно больше конкретики.

### Почему это важно

Если private engine появится позже, core уже должен иметь правильный optional boundary и безопасную модель проверки license. Иначе придется ломать API и доверие пользователей.

### Что сделать

Добавить в roadmap:

```bash
sndr license status --json
sndr license verify --file sample.license --offline
sndr report bundle --redact --dry-run
python3 scripts/security_scan.py --public-release
```

Требования:

- public core работает без license server;
- private engine optional;
- public key может быть в core;
- private key никогда не хранится в repo;
- offline activation supported;
- no telemetry by default;
- report bundle redacts tokens, paths, IP if needed;
- SBOM/constraints generated for release;
- installer не делает `curl | sh`;
- system-level changes только через explicit confirmation.

### Что это дает

- безопасный путь к private engine;
- доверие community;
- меньше риска утечки ключей;
- лучше release readiness.

### Плюсы

- создает правильный фундамент;
- можно внедрять поэтапно;
- уменьшает будущую переделку.

### Минусы

- требует аккуратного дизайна;
- легко переусложнить;
- нельзя превращать public core в license-dependent проект.

### Влияние на проект

Высокое. Особенно важно для выбранной стратегии: public core + private paid patches later.

## P1. Сделать public/private docs boundary отдельным gate

### Что не так

Roadmap говорит про docs stale scan и private paths/IPs, но public/private boundary стоит сделать отдельным release gate.

### Почему это важно

В проекте много внутренних audit docs, server notes, internal plans и private paths. Они полезны для работы, но опасны для public release.

### Что сделать

Добавить:

```bash
python3 scripts/release_public_docs_check.py
```

Проверять:

- public docs не ссылаются на `docs/_internal`;
- нет private IP;
- нет `/home/sander`;
- нет server container names;
- нет old commands;
- нет internal-only notes;
- нет TODO/placeholder в public docs;
- все ссылки существуют в release tree.

### Что это дает

- чище public repo;
- меньше утечек внутренней информации;
- меньше confusion у пользователей;
- проще подготовить release.

### Плюсы

- легко автоматизировать;
- высокая практическая польза;
- снижает репутационные риски.

### Минусы

- нужен allowlist;
- придется чистить старые docs;
- некоторые internal docs нужно перенести в private storage.

### Влияние на проект

Средне-высокое. Это напрямую влияет на доверие к проекту.

## P1. Уточнить patch proof threshold

### Что не так

Roadmap требует:

```text
release tier: ≥80% of implementation_status: stable patches
```

Это лучше, чем ничего, но для `stable` patches в release лучше целиться в 100% или иметь явный allowlist исключений.

### Почему это важно

Если patch имеет статус `stable`, но нет proof artifact, его нельзя считать production-ready.

### Что сделать

Разделить threshold:

| Статус | Release requirement |
|---|---|
| `stable` | 100% proof или explicit waiver |
| `beta` | proof required for enabled-by-default |
| `experimental` | may skip proof, disabled by default |
| `draft` | never in release registry |
| `deprecated` | retire note required |

Waiver должен иметь:

- owner;
- reason;
- expiry date;
- risk;
- rollback.

### Что это дает

- честный stable статус;
- меньше dead patches;
- проще release audit;
- лучше доверие к registry.

### Плюсы

- строгая production дисциплина;
- легко понять статус patch;
- снижает скрытые runtime bugs.

### Минусы

- больше работы перед release;
- часть старых stable patches придется downgrade до beta/experimental.

### Влияние на проект

Высокое для patch-layer качества.

## P2. Добавить external findings pipeline

### Что не так

Roadmap содержит upstream/club/research идеи, но процесс превращения внешнего наблюдения в действие еще не полностью формализован.

### Почему это важно

Иначе vLLM PR, club-3090 issues и идеи из других движков будут оставаться списком ссылок, а не задачами с acceptance.

### Что сделать

Добавить файл:

`docs/_internal/EXTERNAL_FINDINGS_PIPELINE_2026-05-12_RU.md`

Формат finding:

```yaml
id: external-vllm-42102
source: vllm-pr
url: https://github.com/vllm-project/vllm/pull/42102
category: memory-cache
relevance: qwen/gemma/dflash/tq
status: watch
action: needs-bench
target:
  - doctor-rule
  - config-recipe
  - patch-backport
risk: medium
acceptance: "short GPU smoke + apply.shadow strict"
```

Статусы:

- `backport-now`;
- `watch`;
- `skip`;
- `needs-reproducer`;
- `needs-bench`;
- `retire-local-patch`;
- `doctor-rule`;
- `config-recipe`.

### Что это дает

- внешние идеи становятся управляемыми;
- меньше случайных интеграций;
- лучше связь с upstream;
- проще объяснить, почему что-то берем или не берем.

### Плюсы

- системность;
- полезно для roadmap;
- снижает риск copy-paste решений.

### Минусы

- требует поддержки;
- внешние источники быстро меняются;
- некоторые findings будут устаревать.

### Влияние на проект

Средне-высокое. Особенно полезно для проекта, который активно зависит от vLLM upstream.

## P2. Добавить owner/status/evidence в крупные задачи roadmap

### Что не так

Roadmap стал большим, но не все задачи имеют owner, status и evidence link. При параллельной работе это быстро станет проблемой.

### Почему это важно

Если другой агент или инженер работает на server, нужно быстро видеть:

- кто делает задачу;
- что уже проверено;
- что blocked;
- какой artifact доказывает done.

### Что сделать

Для крупных задач добавить поля:

```markdown
Owner:
Status: planned | in_progress | blocked | done | verified
Evidence:
Blocked by:
Acceptance:
```

### Что это дает

- меньше потерь контекста;
- проще ревью;
- лучше параллельная работа;
- легче выпускать release notes.

### Плюсы

- просто внедрить;
- хорошо работает с evidence ledger;
- полезно для server watcher.

### Минусы

- документ станет длиннее;
- нужно поддерживать статусы.

### Влияние на проект

Среднее. Это улучшение управления, но не блокер для кода.

## Мелкие ошибки и точечные улучшения

### 1. Опечатки и формулировки

В Phase 0 есть `progress treckable` - лучше `progress is trackable`.

Почему: мелочь, но master plan должен выглядеть аккуратно.

### 2. `sndr patch` vs `sndr patches`

В roadmap встречается `sndr patch prove`, но раньше в проекте часто используется plural naming вроде `patches doctor`. Нужно выбрать один стиль.

Рекомендация:

- если CLI уже имеет `sndr patches doctor`, использовать `sndr patches prove`;
- если вводится новый singular namespace, описать migration/alias.

Почему: CLI consistency важна для UX.

### 3. `genesis_bench_suite.py --quick prod-35b`

Проверить, совпадает ли эта команда с реальным CLI/argparse. Если фактический интерфейс другой, roadmap создаст ложную acceptance-команду.

Почему: acceptance commands должны быть исполнимыми.

### 4. `sndr hardware list` в V1 smoke

Если `sndr hardware list` относится к V2 discovery, его нельзя использовать как V1 smoke без реализации compatibility bridge.

Почему: Phase 8a должна проверять существующий workflow, а не будущий V2.

### 5. `docs/ROLLBACK_PLAYBOOK.md`

Roadmap требует rollback docs, но надо добавить его в phase deliverables.

Почему: иначе acceptance требует файл, который ни одна phase явно не создает.

## Что я бы сделал следующим шагом

1. Обновил roadmap минимальным cleanup:
   - убрать hardcoded counts;
   - заменить scaffold/placeholder wording;
   - исправить `sndr patch` vs `sndr patches`;
   - убрать `~/.sndr` из git dirty allowlist;
   - добавить safe rsync dry-run.

2. Добавил отдельные маленькие design docs:
   - `RUNTIME_COMMAND_SPEC_DESIGN_2026-05-12_RU.md`;
   - `SECURITY_LICENSE_GATE_2026-05-12_RU.md`;
   - `MEMORY_EXPLAIN_MVP_2026-05-12_RU.md`;
   - `EXTERNAL_FINDINGS_PIPELINE_2026-05-12_RU.md`.

3. Только после этого начинал Phase 1 V2 schema/composer.

## Финальное мнение

Текущее состояние roadmap хорошее и стало значительно профессиональнее. Самое ценное изменение - переход от "планируем и верим" к "доказываем через gates". Но еще нужно убрать последние противоречия, особенно вокруг test counts, scaffold/placeholder, dirty-state allowlist, runtime contract и security/license.

Если эти замечания закрыть, roadmap можно считать достаточно строгим master plan для начала V2-миграции и подготовки проекта к production-grade состоянию.
