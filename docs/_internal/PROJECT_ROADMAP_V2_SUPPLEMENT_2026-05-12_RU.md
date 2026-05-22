# Дополнения к PROJECT_ROADMAP_V2

Дата: 2026-05-12  
Базовый файл: `docs/_internal/PROJECT_ROADMAP_V2_2026-05-12_RU.md`  
Назначение: отдельный список того, что в roadmap V2 стоит добавить, уточнить или усилить после сверки с текущими markdown-документами проекта, внутренними заметками в `Genesis_internal_docs`, локальными `.claude`-памятями и текущими выявленными расхождениями local/server.

Этот файл не заменяет roadmap V2. Его задача - дать отдельный слой поправок: что упущено, что сформулировано слишком оптимистично, какие gates нужны перед реализацией, и какие решения надо зафиксировать до дальнейшего переноса кода.

## Краткий вывод

`PROJECT_ROADMAP_V2_2026-05-12_RU.md` в целом правильно задает направление: layered config V2, единый composer, launcher/install/config automation, community SDK, разделение public core и future private engine. Но в текущем виде roadmap смешивает три разных слоя:

1. фактическое состояние проекта;
2. архитектурное целевое состояние;
3. желаемую release-картину.

Из-за этого часть пунктов выглядит как уже закрытая, хотя по документам local/server и по старым аудитам еще требуется проверка доказательствами. Главный недостающий слой - `evidence gate`: для каждого утверждения вида "готово", "clean", "production-ready", "P0 закрыты" должен существовать воспроизводимый артефакт с командой, commit/ref, хостом, датой, выходом проверки и решением.

Главная рекомендация: добавить перед текущей Phase 1 отдельную Phase 0 `Roadmap Truth / Evidence Gate`, а уже после нее начинать схему V2, SDK и интеграции. Иначе есть риск строить новую архитектуру поверх недосверенного состояния.

## Что добавить в roadmap как Phase 0

### 0.1. Roadmap Truth / Evidence Gate

В roadmap V2 есть сильные утверждения о текущей базе: local/server self-test green, shadow strict green, pytest green, отсутствие открытых P0. Это нужно оставить только при наличии проверяемого журнала.

Добавить новый обязательный артефакт:

`docs/_internal/ROADMAP_EVIDENCE_LEDGER_2026-05-12_RU.md`

Содержимое ledger:

- `host`: local или server;
- `path`: абсолютный путь проекта;
- `git rev-parse --short HEAD`;
- `git branch --show-current`;
- `git status --short`;
- команда проверки;
- дата/время запуска;
- итог: pass/fail/skip;
- ссылка на лог или embedded excerpt;
- причина skip, если проверка не запускалась;
- решение: принять, перепроверить, исправить, удалить из roadmap.

Минимальный набор evidence-команд:

```bash
git status --short
python3 -m compileall -q vllm/sndr_core
python3 -m vllm.sndr_core.compat.cli self-test --json
python3 -m vllm.sndr_core.apply.shadow --strict
python3 -m pytest vllm/sndr_core/tests -q
bash -n install.sh
```

Для server отдельно:

```bash
ssh sander@192.168.1.10 'cd /home/sander/genesis-vllm-patches-v11 && git status --short'
ssh sander@192.168.1.10 'cd /home/sander/genesis-vllm-patches-v11 && python3 -m vllm.sndr_core.compat.cli self-test --json'
ssh sander@192.168.1.10 'cd /home/sander/genesis-vllm-patches-v11 && python3 -m vllm.sndr_core.apply.shadow --strict'
```

Почему это нужно:

- в `LOCAL_SERVER_DUAL_STATE_FIX_PLAN_2026-05-12_RU.md` зафиксировано, что local и server находились на одном commit, но были dirty и расходились по файлам;
- текущие документы содержат разные состояния готовности: старые аудиты говорят о pytest red/server regressions, roadmap V2 говорит о green baseline;
- без ledger невозможно понять, какие утверждения уже актуальны, а какие остались от предыдущего состояния.

Критерий приемки:

- roadmap не должен утверждать "готово", если в ledger нет свежего pass по этой проверке;
- строки с production-ready статусом должны ссылаться на evidence ledger;
- при каждом крупном изменении проекта ledger обновляется до изменения roadmap.

### 0.2. Local/server convergence gate

Перед V2-архитектурой нужно закрыть расхождения local/server как отдельный этап.

Добавить в roadmap таблицу решений:

| Класс расхождения | Что сделать | Почему |
|---|---|---|
| Код `sndr_core` | выбрать один источник истины и синхронизировать | иначе тесты local/server проверяют разные реализации |
| `sndr_engine` skeleton | принять единое policy-решение | сейчас документы расходятся: где-то engine должен быть пустым, где-то public skeleton допускается |
| `.pre-commit-config.yaml` | вернуть/синхронизировать на server | без одинаковых hooks server может принимать код, который local бы отсеял |
| PR template | обновить server-шаблон под `sndr_core`/`integrations` | старые `wiring/patch_*.py` ломают contributor workflow |
| benchmark artifacts | отделить tracked examples от runtime outputs | иначе репозиторий загрязняется результатами прогонов |
| docs deletion | сделать migration map | нельзя удалять старые docs без указания, где теперь живет информация |

Критерий приемки:

- есть `docs/_internal/LOCAL_SERVER_CONVERGENCE_DECISION_2026-05-12_RU.md`;
- каждый файл из diff-классов имеет решение: keep local, keep server, merge, archive, delete, regenerate;
- local/server self-test и shadow strict проходят на выбранной целевой структуре.

## Что усилить в разделе production readiness

### 1. Разделить "feature roadmap" и "release readiness"

Roadmap V2 хорошо описывает будущие возможности, но production readiness должен быть отдельным gate, а не итоговой фразой.

Добавить два статуса:

- `Feature-complete for internal testing` - можно тестировать в своей среде, допустимы ручные шаги и ограниченные сценарии;
- `Public production release` - можно отдавать пользователям без знания внутренней структуры проекта.

Для `Public production release` добавить жесткий минимум:

- чистая установка в fresh venv;
- clean clone без внутренних документов;
- `sndr doctor --full`;
- `sndr report bundle --redact`;
- `sndr launch --dry-run` для каждого builtin profile;
- `sndr launch --prepare` без ручного создания директорий;
- `sndr deps plan` и `sndr deps apply --dry-run`;
- отсутствие hardcoded `/home/sander`, `192.168.1.10`, private container names в public docs и default configs;
- documented rollback для Docker/quadlet/K8s/Proxmox;
- секреты не попадают в compose, logs, report bundle и markdown-примеры.

### 2. Добавить release evidence matrix

Минимальная матрица:

| Сценарий | Local | Server | Fresh clone | Docker | Bare metal | GPU required |
|---|---:|---:|---:|---:|---:|---:|
| self-test | да | да | да | нет | да | нет |
| shadow strict | да | да | да | нет | да | нет |
| config parse all builtins | да | да | да | нет | да | нет |
| launch dry-run all profiles | да | да | да | опционально | да | нет |
| one short GPU smoke | нет | да | нет | да | да | да |
| report bundle redaction | да | да | да | опционально | да | нет |
| docs stale-link scan | да | да | да | нет | да | нет |

Это нужно, чтобы не смешивать "код компилируется" и "проект готов к установке пользователем".

## Документация: что явно упущено

### 3. Docs stale gate

В roadmap V2 есть общая фаза документации, но нужен конкретный docs gate. Сейчас по markdown-файлам встречаются старые команды, старые пути и private/server-specific значения. Это особенно опасно перед public release: пользователь будет запускать несуществующие команды или читать архитектуру, которой уже нет.

Добавить `make docs-check` или `python3 scripts/docs_stale_scan.py`.

Запрещенные или требующие allowlist маркеры:

- `_genesis`;
- `vllm/_genesis`;
- `vllm/sndr_core/wiring`;
- `wiring/patch_`;
- `genesis doctor`;
- `genesis verify`;
- `genesis migrate`;
- `./scripts/launch.sh`;
- `192.168.1.10`;
- `/home/sander`;
- `vllm-server-mtp-test`;
- `GENESIS_` runtime env для новых SNDR-only документов, если нет compatibility-примечания.

Обнаруженные кандидаты на очистку или allowlist:

- `README.md` содержит старую архитектурную ссылку на `vllm/sndr_core/wiring/`;
- `docs/DAY_1_CHECKLIST.md` содержит старые команды `genesis doctor`, `genesis verify --quick`, `./scripts/launch.sh`;
- `docs/PATCHES.md` содержит старые `wiring` пути;
- `docs/CLIFFS.md` содержит старые `wiring` ссылки;
- `docs/COMMANDS.md` содержит старые CLI-команды `genesis doctor`, `genesis verify`, `genesis migrate`;
- `docs/REASONING_CONTENT_CONTRACT.md` содержит пример host `http://192.168.1.10:8101`;
- `docs/CONFIGURATION.md` содержит `/home/sander`;
- `README.md` содержит старое имя контейнера `vllm-server-mtp-test`;
- `docs/CONFIGS_FOR_COMMUNITY.md` содержит старые команды и container naming.

Решение:

- public docs должны использовать generic placeholders: `<host>`, `<model-path>`, `<container-name>`, `<project-root>`;
- internal docs могут содержать реальные IP/пути, но должны жить только в `docs/_internal` или external private папке;
- для archived docs добавить явный header: `ARCHIVED / not current`.

Критерий приемки:

```bash
rg -n "_genesis|vllm/_genesis|sndr_core/wiring|wiring/patch_|genesis doctor|genesis verify|genesis migrate|scripts/launch.sh|192\.168\.1\.10|/home/sander|vllm-server-mtp-test" README.md docs
```

Команда должна возвращать только allowlisted строки.

### 4. Public/private documentation boundary

Из `.claude`-памяти и старых внутренних заметок повторяется правило: internal docs нельзя коммитить в public repo. Roadmap V2 это подразумевает, но не формализует.

Добавить gate:

- `docs/_internal` не включается в release artifacts;
- `Genesis_internal_docs` не копируется в repo;
- `feedback_*.md`, `session memory`, private benchmark notes не линкуются из public README;
- public docs должны быть самодостаточны, но без private IP, приватных названий серверов, внутренних заметок и незавершенных обещаний.

Нужная утилита:

```bash
python3 scripts/release_public_docs_check.py
```

Что проверяет:

- private paths;
- private IP;
- internal doc references;
- "TODO", "placeholder", "stub", "scaffold" в public docs;
- ссылки на файлы, которых нет в release profile;
- команды, которых нет в CLI.

## Противоречие: no stubs vs community SDK

Roadmap V2 предлагает community SDK и manifest examples с `implementation_status: scaffold`. Это конфликтует с сильным правилом из локальных `.claude`-заметок: не оставлять stubs/scaffolds/placeholders как часть проекта.

Нужно уточнить политику:

Разрешено:

- генератор `sndr community new` может создать локальный draft в рабочем каталоге пользователя;
- draft может иметь статус `draft` до публикации;
- draft не должен попадать в tracked public registry как "готовый патч".

Запрещено:

- tracked placeholder patch в `vllm/sndr_core`;
- manifest со статусом `scaffold` в release registry;
- CLI-команда, которая показывает scaffold как доступную production-функцию;
- README, где scaffold выглядит как реализованный функционал.

Рекомендуемая модель статусов:

```yaml
implementation_status: experimental | beta | stable | deprecated | disabled
publish_state: draft | review | published | rejected
```

`draft` не может быть частью release registry. `scaffold` лучше не использовать как runtime status, чтобы не путать генерацию файлов и состояние продукта.

Критерий приемки:

```bash
rg -n "stub|scaffold|placeholder|TODO|pass #|NotImplementedError" vllm/sndr_core README.md docs
```

Каждое найденное место должно иметь одно из решений:

- удалить;
- реализовать;
- перенести в template-only папку;
- пометить как internal draft и исключить из release.

## Engine/Core: что нужно зафиксировать

Roadmap V2 правильно говорит, что `sndr_engine` должен быть зарезервирован под будущий private layer. Но в документах проекта есть разные формулировки:

- engine должен быть пустым;
- public skeleton engine допускается;
- core должен знать о наличии engine;
- core не должен зависеть от engine.

Нужно принять одну политику и записать ее в roadmap.

Рекомендуемая политика на текущий этап:

1. `sndr_core` является единственным обязательным public layer.
2. `sndr_engine` в public repo может существовать только как optional namespace boundary без приватных алгоритмов.
3. `sndr_core` не импортирует `sndr_engine` напрямую.
4. Все обращения к engine идут через один discovery API:

```python
def engine_available() -> bool:
    ...

def load_engine_provider() -> EngineProvider | None:
    ...
```

5. Если engine отсутствует, все public CLI-команды должны работать.
6. Если engine требуется конкретному профилю, ошибка должна быть понятной:

```text
Profile requires sndr_engine feature "private_patch_pack", but engine provider is not installed.
Install private engine package or select a core-only profile.
```

7. Public builtin profiles не должны требовать engine.
8. Private engine не должен патчить core через implicit side effects при import.

Критерий приемки:

```bash
rg -n "sndr_engine" vllm/sndr_core
```

Допустимы только файлы discovery/feature-gate/tests. Любой прямой импорт конкретного private module считается ошибкой архитектуры.

## Launcher/installer/config: что добавить

### 5. RuntimeCommandSpec как единый источник истины

Roadmap V2 описывает Docker/K8s/Proxmox/VM/LXC, но не хватает общего контракта между launcher, installer, dry-run, report bundle и docs.

Добавить объект:

```python
@dataclass(frozen=True)
class RuntimeCommandSpec:
    runtime: Literal["baremetal", "docker", "compose", "quadlet", "kubernetes", "proxmox_lxc", "proxmox_vm"]
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

Все backend-рендереры должны строиться из него:

- `sndr launch --dry-run --runtime docker`;
- `sndr launch --dry-run --runtime compose`;
- `sndr launch --dry-run --runtime quadlet`;
- `sndr launch --dry-run --runtime kubernetes`;
- `sndr launch --dry-run --runtime proxmox-lxc`;
- `sndr report bundle`;
- docs examples.

Так исчезнет расхождение, когда docs показывают одно, launcher запускает другое, а report bundle собирает третье.

### 6. Host init / host doctor

В roadmap есть dependency/install plan, но надо отдельно закрыть проблему host-level readiness.

Добавить команды:

```bash
sndr host doctor
sndr host init --dry-run
sndr host init --apply
sndr host paths explain
sndr host gpu explain
```

Что проверять:

- Python version и venv;
- CUDA driver/runtime visibility;
- `nvidia-smi`;
- Docker version;
- NVIDIA Container Toolkit;
- Compose plugin;
- permissions на Docker socket;
- доступность model path;
- writable cache/log dirs;
- symlink mount resolution;
- filesystem type для model/cache dirs;
- `ulimit -n`;
- swap;
- hugepages, если используются;
- Proxmox LXC nesting/keyctl/devices/cgroups;
- VM passthrough hints;
- K8s GPU device plugin.

Критерий приемки:

- `sndr launch --prepare` не должен молча создавать сломанный compose;
- если путь является symlink, dry-run должен показывать realpath и mount source;
- если GPU недоступна в контейнере, ошибка должна появляться до запуска vLLM.

### 7. Dependency planner

Пользовательский сценарий должен быть таким:

```bash
sndr deps plan --profile a5000-2x-27b-int4-tq-k8v4
sndr deps apply --dry-run
sndr deps apply --scope user
sndr deps apply --scope system
```

План должен показывать:

- требуемый Python;
- compatible vLLM version/ref;
- torch/CUDA constraints;
- Docker image tag/digest;
- required apt packages;
- optional repositories;
- install commands per OS;
- что будет изменено;
- что уже установлено;
- что несовместимо;
- rollback hints.

Важно: `deps apply` не должен выполнять `sudo`, `curl | sh`, package repo changes без явного подтверждения. В CI/public docs сначала должен быть `--dry-run`.

## Memory/KV/bench: что упущено

### 8. `sndr memory explain` нужно поднять в P1

В старых roadmap и memory docs тема memory/cache повторяется как один из главных источников практической пользы. В roadmap V2 она выглядит вторично относительно SDK и config V2. Для проекта с A5000/3090/long-context memory planning должен быть P1.

Добавить `sndr memory explain` как обязательную утилиту:

```bash
sndr memory explain --profile a5000-2x-35b-prod
sndr memory explain --model Qwen/Qwen3.6-27B --tp 2 --dtype fp8 --kv-dtype fp8 --ctx 32768
sndr memory explain --from-running http://localhost:8000
```

Вывод:

- weights estimate;
- KV cache estimate;
- activation/cudagraph reserve;
- quantization overhead;
- Marlin/TurboQuant scratch estimate;
- fragmentation reserve;
- prefix cache impact;
- max concurrency estimate;
- cliff points по context/concurrency;
- рекомендации: уменьшить ctx, batch, max-num-seqs, enable/disable DFlash/TQ/MTP.

Уроки, которые нужно записать в roadmap:

- Python-level `torch.empty/zeros` recorder не видит основную память vLLM/kernels, поэтому не должен быть главным инструментом prealloc;
- основной бюджет: weights, KV, activations/cudagraph, kernel scratch, fragmentation;
- `garbage_collection_threshold` может быть no-op при `expandable_segments`;
- `VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=1` важен для точной оценки KV;
- MTP K=3 может быть оптимальным для 35B, K2/K4 не всегда лучше;
- PN95 полезен для cross-request rotation, но не решает single-request long-context без scheduler/preemption поддержки.

### 9. Bench methodology gate

Roadmap должен запретить сравнивать результаты, полученные разными методиками.

Добавить:

- `bench run` всегда пишет методику: warmup, max_tokens, prompts, tool-call payloads, concurrency, context, model path, docker image digest, git ref, env;
- tool-call bench должен иметь достаточный `max_tokens` и warmup, иначе можно получить ложный "провал";
- каждый benchmark должен указывать cold/warm cache;
- TPS claims в README допускаются только из canonical bench artifacts;
- long-context/OOM tests должны иметь short timeout и separate label, чтобы не запускаться случайно в quick CI.

Критерий приемки:

```bash
sndr bench run --profile a5000-2x-27b-int4-tq-k8v4 --quick --json
sndr bench compare --baseline baseline.json --candidate candidate.json
sndr bench report --redact
```

## Patch lifecycle: что добавить

### 10. Per-model verification matrix

Roadmap перечисляет patch roadmap, но нужна матрица того, где патч реально проверен.

Минимальные family/profile gates:

| Профиль | Что проверять |
|---|---|
| 27B TQ | short decode, tool call, structured output, long-ish context, memory explain |
| 27B DFlash | DFlash path, fallback behavior, dtype invariants |
| 35B prod | TPS regression, memory cliff, long context |
| 35B DFlash | aux layer indexing, combine hidden dtype, drafter compatibility |
| Gemma | reasoning/content contract, tool schema, tokenizer edge cases |
| Qwen | MTP, tool call, structured output, prompt logprobs |
| Nemotron | FP8/BF16 profile, 2x GPU, OpenAI endpoint behavior |

Каждый патч должен иметь:

- source: upstream PR, local original, club-derived idea, experiment;
- owner;
- implementation status;
- test status;
- supported model families;
- default policy;
- rollback policy;
- upstream retire condition;
- env flags;
- config keys;
- failure signature;
- acceptance command.

### 11. Dead/no-op patch detector

Старые внутренние заметки фиксируют опасный класс: patch enabled, but no real runtime effect. Roadmap V2 должен добавить detector.

Проверка:

- патч включен в config;
- patch apply log говорит applied;
- runtime log подтверждает, что vLLM код реально изменен/использован;
- ON/OFF bench или behavior test показывает отличие;
- если upstream уже содержит fix, patch переводится в deprecated/retired.

Нужная команда:

```bash
sndr patches prove --patch PN95 --profile a5000-2x-35b-prod
```

Вывод:

- anchor found;
- replacement applied;
- runtime marker present;
- behavior changed;
- test passed;
- retire condition not met.

### 12. Env flag canonicalization

В старых аудитах были проблемы с YAML vs runtime env drift и неизвестными `GENESIS_PN95_*` knobs. Roadmap V2 должен добавить единый каталог env/config keys.

Добавить:

```bash
sndr config keys validate
sndr config env explain GENESIS_PN95_ENABLE
sndr config env migrate --from genesis --to sndr
```

Правила:

- каждый env key объявлен в одном месте;
- YAML profiles не могут содержать unknown keys;
- deprecated `GENESIS_*` допускаются только через compatibility alias;
- compatibility alias имеет дату удаления;
- docs генерируют список keys из кода, а не наоборот.

## External integration: что добавить

### 13. vLLM watchlist automation

Roadmap V2 упоминает vLLM PR #42102 и внешние PR/bugs, но нужен механизм, а не ручной список.

Добавить `docs/_internal/UPSTREAM_WATCHLIST.md` и команду:

```bash
sndr upstream scan --topic memory,cache,spec-decode,gemma,qwen,mtp,fp8,fp4 --since 2026-05-08
```

Статусы:

- `backport-now`;
- `watch`;
- `blocked`;
- `skip`;
- `retire-local-patch`;
- `needs-bench`;
- `needs-reproducer`.

Для PR #42102:

- держать отдельный watch item;
- фиксировать changed files, риск для local patches, merge status;
- при merge запускать deep-diff against current pinned vLLM;
- если upstream закрывает локальный patch, добавить retire task.

### 14. club-3090 integration pipeline

Идеи из `noonghunna/club-3090` не должны попадать в проект как разовые заметки. Нужен pipeline:

1. issue/discussion/bench превращается в `external finding`;
2. finding получает категорию: Docker, hardware, K8, memory, Gemma, Qwen, long context, OOM, installer, benchmark;
3. если finding практический, создается:
   - doctor rule;
   - config recipe;
   - benchmark case;
   - docs cookbook entry;
   - optional patch proposal.

Пример категорий для переноса:

- K8/KV/cache tuning для 3090/A5000 профилей;
- Docker compose patterns для dual GPU/NVLink;
- power-cap and residency instrumentation;
- OOM recipes;
- Gemma-specific structured output/tool-call cases;
- hardware docs для 3090/A5000 mixed setups;
- community-proven model profiles.

Критерий приемки:

- каждое внешнее наблюдение имеет ссылку, summary, применимость, risk, owner, статус;
- нет "copy-paste patch" без собственной реализации и теста;
- club-derived configs проходят тот же schema/profile gate, что builtin configs.

### 15. Другие движки: только переносимые идеи

Roadmap должен явно запретить бессистемное копирование из SGLang/TensorRT-LLM/FlashInfer/llama.cpp/exllama. Нужен принцип:

- берем не код, а архитектурную идею;
- сначала пишем adapter/design note;
- затем proof-of-concept;
- затем benchmark;
- затем production gate.

Кандидаты:

- SGLang: prefix/cache routing, radix cache ideas, adaptive speculative decode heuristics;
- TensorRT-LLM: deployment/profile discipline, engine build artifacts, quantization profile separation;
- FlashInfer: kernel availability detection and fallback discipline;
- llama.cpp/ik_llama.cpp/exllama: quantization UX, model file discovery, low-VRAM recipes, practical CLI ergonomics;
- LMCache/vLLM ecosystem: KV offload/tiered cache patterns, if compatible with vLLM pin.

## Security/commercial readiness

### 16. License/trust gate

Roadmap V2 говорит про будущий private engine, но не хватает security/release gate для криптографического ключа и закрытых утилит.

Добавить:

- public core не должен иметь runtime dependency on license server;
- private engine может проверять license, но core должен работать без него;
- public CLI должен показывать engine feature as unavailable, а не падать;
- license payload validation: schema, signature, expiry, hardware binding optional, clock skew;
- trust anchor: публичный ключ в core, private key никогда не в repo/logs/docs;
- no telemetry by default;
- offline activation option для доверия community;
- explicit error codes для license failure;
- redaction в `sndr report bundle`.

Критерий приемки:

```bash
sndr license verify --file sample.license --offline
sndr license status --json
sndr report bundle --redact
```

### 17. Secrets and hardcoded endpoints

Добавить в roadmap mandatory scanner:

```bash
python3 scripts/security_scan.py --public-release
```

Проверяет:

- IP addresses;
- `/home/sander`;
- tokens/API keys;
- private repo URLs;
- compose passwords;
- `curl | sh`;
- `sudo` inside installer;
- world-writable paths;
- accidental benchmark logs with model paths or hostnames;
- hidden `.env` examples with real values.

## Acceptance checklist: что добавить

Roadmap V2 acceptance checklist стоит расширить так:

```bash
# evidence
make evidence

# syntax and static
python3 -m compileall -q vllm/sndr_core
bash -n install.sh
python3 scripts/parse_all_configs.py

# core gates
python3 -m vllm.sndr_core.compat.cli self-test --json
python3 -m vllm.sndr_core.apply.shadow --strict
python3 -m pytest vllm/sndr_core/tests -q

# docs
make docs-check
python3 scripts/release_public_docs_check.py

# config and launch
sndr config validate --all
sndr launch --dry-run --all-builtins
sndr deps plan --all-builtins
sndr host doctor

# patch proof
sndr patches doctor
sndr patches prove --changed

# report/security
sndr report bundle --redact --dry-run
python3 scripts/security_scan.py --public-release
```

Для server:

```bash
ssh sander@192.168.1.10 'cd /home/sander/genesis-vllm-patches-v11 && python3 -m vllm.sndr_core.compat.cli self-test --json'
ssh sander@192.168.1.10 'cd /home/sander/genesis-vllm-patches-v11 && python3 -m vllm.sndr_core.apply.shadow --strict'
ssh sander@192.168.1.10 'cd /home/sander/genesis-vllm-patches-v11 && sndr launch --dry-run --all-builtins'
```

GPU quick checks должны быть короткими и отдельными от обычного CI.

## Приоритетный список дополнений

### P0

1. Добавить `Roadmap Truth / Evidence Gate`.
2. Создать local/server convergence decision.
3. Ввести docs stale gate.
4. Зафиксировать единую policy по `sndr_engine`.
5. Убрать tracked placeholders/scaffolds из release-surface или явно перевести их в draft templates.
6. Добавить public/private docs boundary.
7. Зафиксировать release evidence matrix.

### P1

1. Добавить `RuntimeCommandSpec`.
2. Добавить `sndr host doctor/init/paths explain/gpu explain`.
3. Поднять `sndr memory explain` в P1.
4. Добавить dependency planner.
5. Добавить env/config key canonicalization.
6. Добавить patch proof/dead-patch detector.
7. Добавить security/license/trust gate.
8. Добавить upstream watchlist automation.
9. Добавить club-3090 finding pipeline.

### P2

1. Довести K8s до validate/dry-run/apply/rollback ladder.
2. Довести Proxmox LXC/VM до host doctor и apply plan.
3. Добавить community profile signing/verification.
4. Добавить profile promote workflow с benchmark evidence.
5. Добавить report bundle redaction and reproducibility artifacts.
6. Добавить pin bump deep-diff workflow.

### P3

1. DuoAttention/SWA/TQ k4v4/MambaRadixCache/NVMe tiered cache только после P0/P1 gates.
2. Новые speculative decode и memory optimizations только через bench-driven enable.
3. External engine ideas только через design note + POC + benchmark + retire/upstream policy.

## Что не стоит добавлять сейчас

1. Не стоит закрывать утилиты/шифровать core до стабилизации public API. Иначе сложнее строить доверие и принимать community feedback.
2. Не стоит публиковать TPS claims без canonical bench artifacts.
3. Не стоит держать `sndr_engine` как fake-working слой. Если private engine пока пустой, он должен быть честно optional.
4. Не стоит тащить крупные upstream patches без reproducible bug/bench.
5. Не стоит продолжать Python-level prealloc recorder как основной путь экономии VRAM: прошлые заметки показывают, что он атакует слабый слой абстракции.
6. Не стоит смешивать internal docs и public docs даже временно: это быстро превращается в release debt.

## Предлагаемые вставки в PROJECT_ROADMAP_V2

### После раздела `0. Executive Summary`

Добавить:

```markdown
## 0.1. Roadmap Truth / Evidence Gate

Все статусы "готово", "clean", "P0 закрыт", "production-ready" подтверждаются evidence ledger: команда, host, commit, дата, stdout/stderr excerpt, решение. Без evidence статус считается плановым, а не фактическим.
```

### После раздела `1. Current Baseline`

Добавить:

```markdown
## 1.1. Local/Server Convergence Gate

Local и server считаются равноправными источниками до решения по каждому diff-классу. Нельзя объявлять release baseline, пока выбранная структура не проходит self-test, shadow strict, config parse и docs-check на целевом источнике истины.
```

### В раздел `3.4. CLI gaps`

Добавить команды:

```text
sndr host doctor
sndr host init --dry-run
sndr host paths explain
sndr host gpu explain
sndr memory explain
sndr patches prove
sndr upstream scan
sndr report bundle --redact
sndr config keys validate
```

### В раздел `6. Quality Gates`

Добавить gates:

- docs stale scan;
- public/private docs scan;
- evidence ledger;
- no-stub release scan;
- security scan;
- env key canonical scan;
- patch proof for changed patches;
- local/server convergence.

### В раздел `7. Risks`

Добавить риски:

- roadmap говорит green, но evidence устарел;
- public docs содержат internal paths/IP;
- community SDK легализует placeholders;
- core начинает неявно зависеть от private engine;
- patch applied, но runtime effect отсутствует;
- benchmark results несравнимы из-за разных методик;
- upstream merge делает local patch вредным или no-op;
- dependency installer выполняет системные изменения без явного dry-run/approval.

### В раздел `9. Production-ready definition`

Добавить:

- fresh clone install;
- host doctor;
- launch dry-run all builtins;
- report bundle redaction;
- docs-check clean;
- security scan clean;
- canonical bench artifacts;
- engine-absent mode works;
- public docs have no private paths/IP.

## Итоговое решение

Roadmap V2 стоит оставить как основной стратегический план, но перед его Phase 1 нужно добавить жесткую Phase 0. Без нее проект рискует получить хорошую новую архитектуру при незафиксированном фактическом состоянии.

Самые важные дополнения:

1. evidence ledger;
2. local/server convergence;
3. docs stale/public-private gate;
4. no-stub/no-placeholder release policy;
5. explicit engine optional boundary;
6. host/deps/runtime command spec;
7. memory explain and benchmark methodology;
8. patch proof/dead-patch detector;
9. security/license trust gate;
10. external findings pipeline для vLLM/club-3090/других движков.

После этих дополнений roadmap станет не только списком направлений, но и рабочим contract-документом: что реально сделано, что проверено, что можно отдавать пользователям, а что пока остается внутренней разработкой.
