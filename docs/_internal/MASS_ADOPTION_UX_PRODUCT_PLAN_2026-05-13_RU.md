# Genesis / SNDR: план вывода продукта в более массовое потребление

Дата: 2026-05-13

Цель: превратить Genesis/SNDR из сильного инженерного patch-layer проекта для vLLM в продукт, которым могут пользоваться два типа аудитории:

1. Массовый пользователь с GPU, который хочет "запустить локальный AI сервер без боли".
2. Инженер/оператор, который хочет ставить, проверять, запускать и сопровождать все через CLI/SSH.

Главный принцип: GUI, TUI и CLI не должны быть тремя разными продуктами. Это должны быть три оболочки над одним backend API, одной моделью конфигурации и одной системой диагностики.

---

## 1. Текущая реальность продукта

Проект уже имеет сильную техническую базу:

- `sndr` как основной CLI entry point и `genesis` как back-compat alias.
- `sndr install` как Python wizard поверх тонкого `install.sh`.
- `sndr launch` как основной запуск через model config.
- `sndr doctor`, `sndr doctor-system`, `sndr verify`, `sndr deps check/plan`.
- V2 layered configs: model + hardware + profile + preset.
- `RuntimeContainerSpec` как зарождающийся общий IR для Docker, Compose, Podman Quadlet, Kubernetes.
- Community config flow: validate -> preflight -> launch -> verify -> promote.
- Diagnostic bundle: `sndr report bundle`.
- Большой набор патчей, бенчей, профилей, runtime caveats и проверок железа.

Это означает, что массовость надо строить не переписыванием ядра, а продуктовой упаковкой:

- один onboarding path;
- понятные профили железа и моделей;
- GUI/TUI поверх уже существующих CLI primitives;
- нормальная терминология для пользователя;
- стабильный backend API для всех оболочек.

---

## 2. Главная продуктовая формулировка

Сейчас внешний сигнал проекта:

> Runtime patches for vLLM with 136 patches, TurboQuant, MTP, GDN, tool-calling and long context.

Для массового потребления это слишком инженерно. Нужно разделить позиционирование.

### Для массового пользователя

> Запусти локальный OpenAI-compatible AI сервер на своей RTX 3090/4090/5090/A5000 за 15 минут. SNDR сам проверит железо, подберет модель, сгенерирует конфиг, запустит vLLM и объяснит ошибки.

### Для инженера

> Reproducible vLLM runtime layer for consumer and workstation NVIDIA GPUs: pinned configs, patch registry, diagnostics, benchmark gates and SSH-first automation.

### Для команд

> Self-hosted inference stack for small teams without H100 budget.

---

## 3. Два мира, один backend

Нужно явно закрепить архитектуру "две оболочки, один двигатель".

```text
              ┌──────────────────────────┐
              │        GUI Desktop/Web    │
              │  wizard, dashboard, logs  │
              └────────────┬─────────────┘
                           │
              ┌────────────▼─────────────┐
              │          TUI             │
              │ SSH-friendly terminal UI │
              └────────────┬─────────────┘
                           │
              ┌────────────▼─────────────┐
              │          CLI             │
              │ sndr install/launch/...  │
              └────────────┬─────────────┘
                           │
              ┌────────────▼─────────────┐
              │    SNDR Product API      │
              │ inventory, plan, launch, │
              │ logs, presets, reports   │
              └────────────┬─────────────┘
                           │
      ┌────────────────────┼────────────────────┐
      │                    │                    │
┌─────▼─────┐      ┌───────▼────────┐   ┌───────▼────────┐
│ configs   │      │ runtime IR      │   │ patch/apply     │
│ V2 model  │      │ container spec  │   │ dispatcher      │
└───────────┘      └────────────────┘   └────────────────┘
```

Запрещенное направление: делать GUI, который просто вызывает случайные shell commands и парсит stdout. Это быстро сломается.

Правильное направление: выделить Python API слой, который возвращает typed JSON-compatible objects:

- inventory;
- compatibility verdict;
- recommended preset;
- dependency plan;
- launch plan;
- running service status;
- logs summary;
- benchmark result;
- next action.

CLI, TUI и GUI должны использовать этот слой.

---

## 4. Что спрятать от массового пользователя

В GUI/TUI по умолчанию нельзя показывать:

- номера патчей `PN59`, `P67`, `PN16`, кроме advanced режима;
- десятки `GENESIS_ENABLE_*`;
- vLLM anchor drift детали;
- internal lifecycle states;
- raw docker command как первый экран;
- long-form patch registry;
- сложные bench methodology детали.

Вместо этого показывать:

- "модель помещается / не помещается";
- "рекомендуемый режим";
- "что будет установлено";
- "какой endpoint получится";
- "почему запуск не готов";
- "что нажать/выполнить дальше";
- "какая скорость и качество после запуска";
- "можно ли использовать в Cursor/OpenCode/agents".

Advanced mode должен оставлять инженерный доступ:

- env flags;
- rendered launch script;
- patch decision waterfall;
- dry-run;
- JSON reports;
- raw logs;
- registry explain.

---

## 5. Целевые пользовательские сценарии

### Сценарий A: первый запуск на домашней RTX 4090/5090

Пользователь открывает GUI или TUI:

1. SNDR видит GPU, driver, Docker/Podman/bare-metal options.
2. Показывает "Recommended path".
3. Предлагает 2-3 модели: small reliable, recommended, long-context.
4. Проверяет VRAM и disk.
5. Скачивает/подключает модель.
6. Запускает endpoint.
7. Показывает URL, API key, пример для OpenAI-compatible клиента.
8. Дает кнопку "Test chat" и "Copy client config".

Критерий успеха: пользователь не видел слова `patch registry` до первого успешного ответа модели.

### Сценарий B: инженер по SSH

Оператор делает:

```bash
curl -sSL https://.../install.sh | bash -s -- --workload tool_agent -y
sndr doctor-system --config prod-27b-tq
sndr deps plan --config prod-27b-tq
sndr launch prod-27b-tq --preflight-only
sndr launch prod-27b-tq
sndr report bundle --preset prod-27b-tq --container vllm-server
```

Критерий успеха: все можно автоматизировать в runbook/CI без GUI.

### Сценарий C: small team

Команда хочет reproducible setup:

1. Maintainer создает team profile.
2. Экспортирует config bundle.
3. Другой сервер импортирует bundle.
4. `sndr verify` сравнивает TPS/tool quality/VRAM с эталоном.
5. Если drift, создается report bundle.

Критерий успеха: настройка переносится между машинами без ручного копирования 50 env flags.

---

## 6. Основные продуктовые модули

### 6.1 SNDR Product API

Это первый обязательный слой перед GUI/TUI.

Предлагаемый пакет:

```text
vllm/sndr_core/product/
  api.py
  models.py
  workflows.py
  status.py
  recommendations.py
  log_events.py
```

Минимальные функции:

```python
inspect_host() -> HostSummary
recommend_paths(host) -> list[RecommendedPath]
plan_setup(path) -> SetupPlan
apply_setup(plan, dry_run: bool) -> OperationResult
list_models() -> list[ModelCard]
list_presets() -> list[PresetCard]
preflight(preset) -> Verdict
launch(preset, mode) -> LaunchOperation
service_status() -> ServiceStatus
tail_logs(service) -> Iterator[LogEvent]
run_smoke_test(endpoint) -> SmokeResult
create_report_bundle(scope) -> ReportBundle
```

Этот слой должен быть pure/side-effect separated:

- read-only inspection;
- plan generation;
- explicit apply.

Так GUI сможет сначала показать пользователю план, а потом выполнить.

### 6.2 TUI

TUI нужен первым, потому что:

- работает по SSH;
- быстрее разработать;
- сразу полезен текущей аудитории;
- станет прототипом UX для GUI.

Рекомендуемый стек: Python `textual` или `rich` first. Если хочется минимально рискованно, начать с `rich` menus, потом перейти на `textual`.

Команды:

```bash
sndr tui
sndr setup-tui
```

Экраны TUI:

1. System Overview: GPU, driver, Docker, vLLM, disk, RAM.
2. Choose Goal: coding agent, long context, high throughput, local chat.
3. Choose Model: recommended cards.
4. Readiness Plan: blockers/warnings/action list.
5. Launch Monitor: logs, boot stages, endpoint health.
6. Benchmark: quick smoke, tool-call check, TPS estimate.
7. Export: commands, report bundle, client config.

### 6.3 GUI

GUI лучше делать после Product API и TUI, иначе UI начнет диктовать плохую архитектуру.

Варианты:

1. Local web app: `sndr gui` поднимает localhost dashboard.
2. Desktop shell: Tauri/Electron wrapper поверх локального API.
3. Remote dashboard: подключение к серверу по SSH или agent token.

Рекомендуемый старт: local web app.

Команда:

```bash
sndr gui --host 127.0.0.1 --port 7799
```

Состав GUI:

- Dashboard: current service, endpoint, GPU memory, logs summary.
- Setup Wizard: 5 шагов до запуска.
- Model Library: модели, требования, статус скачивания.
- Preset Gallery: hardware/workload cards.
- Diagnostics: blockers with fixes.
- Launch History: configs, runs, bench results.
- Client Setup: Cursor/OpenAI SDK/OpenCode examples.
- Advanced: rendered scripts, env flags, patch matrix.

---

## 7. Расширение функций

### 7.1 Model recommender

Нужно уйти от "выбери preset key" к "выбери цель".

Вход:

- GPU model/count/VRAM;
- RAM/disk;
- runtime backend;
- цель: coding agent, RAG, long context, throughput, experimentation;
- желаемый privacy/performance/quality баланс.

Выход:

- recommended model;
- fallback model;
- not recommended options with reason.

Пример:

```text
Recommended:
  Qwen3.6 27B INT4, tool_agent, 1x RTX 3090

Why:
  Fits 24GB VRAM with conservative context.
  Tool-calling patches enabled.
  Lower OOM risk than 35B.

Tradeoff:
  Less throughput than 2x GPU config.
```

### 7.2 Setup planner

Существующий `deps` planner нужно поднять до user-facing setup plan.

План должен группировать действия:

- required now;
- recommended;
- optional;
- dangerous/manual.

GUI/TUI должны показывать не raw errors, а действие:

```text
Docker NVIDIA runtime missing.
Fix: install nvidia-container-toolkit.
Why: container will not see GPU.
Can SNDR fix this automatically? No, requires system package manager.
```

### 7.3 Service manager

Массовому пользователю нужен не просто запуск в foreground, а понятие сервиса.

Функции:

- install service;
- start/stop/restart;
- enable on boot;
- status;
- logs;
- endpoint health;
- port/API key management.

Уже есть `sndr service`; его надо сделать центральным для GUI/TUI.

### 7.4 Client config generator

После успешного запуска пользователь должен получить готовые snippets:

- OpenAI Python SDK;
- curl;
- Cursor/OpenCode/Cline style endpoint config;
- LiteLLM proxy config;
- Continue.dev config;
- generic OpenAI-compatible JSON.

Это критично для массовости: endpoint без "как подключить" не ощущается продуктом.

### 7.5 Error explainer

Нужно создать каталог ошибок:

```text
vllm/sndr_core/findings/
```

Часть уже есть. Его надо превратить в user-facing объяснитель:

- pattern;
- severity;
- user message;
- technical details;
- fix action;
- docs link;
- report bundle fields.

Источники:

- docker logs;
- vLLM boot logs;
- nvidia-smi;
- `doctor-system --logs`;
- patch apply summary;
- OOM signals;
- xgrammar/tool-call errors;
- prefix cache/hybrid caveats.

### 7.6 Model/download manager

Массовый пользователь не хочет вручную делать `huggingface-cli download`.

Нужно:

- показывать размер модели;
- показывать наличие файлов;
- resumable download;
- disk check до скачивания;
- HF token support;
- local model import;
- checksum/manifest warning;
- "model ready" status.

### 7.7 Bench and proof screen

После запуска показывать:

- tokens/sec;
- latency;
- tool-call pass/fail;
- VRAM steady state;
- context smoke result;
- comparison to expected preset reference.

Не как research report, а как "system health card".

### 7.8 Update and compatibility center

Отдельный экран:

- current SNDR version;
- current vLLM pin;
- known good pins;
- update channel stable/beta/dev;
- drift risk;
- available migration plan;
- rollback option.

Для инженеров оставить:

```bash
sndr update-channel check
sndr migrate ...
sndr lifecycle-audit
```

---

## 8. UX информационная архитектура

### Главная навигация GUI/TUI

1. Overview
2. Setup
3. Models
4. Launch
5. Monitor
6. Benchmark
7. Clients
8. Reports
9. Advanced

### Advanced должен быть выключен по умолчанию

Включает:

- patch IDs;
- env matrix;
- dry-run scripts;
- RuntimeContainerSpec JSON;
- raw logs;
- registry lifecycle;
- upstream drift;
- Kubernetes/Quadlet emitters.

---

## 9. CLI стратегия

CLI нельзя упрощать ценой потери инженерной мощности. Нужно сделать два уровня CLI.

### Friendly CLI

Команды для большинства:

```bash
sndr setup
sndr status
sndr launch recommended
sndr stop
sndr restart
sndr logs
sndr test
sndr clients
sndr report
```

### Engineer CLI

Существующие/расширенные команды:

```bash
sndr install
sndr doctor-system --json
sndr deps plan --config <key> --json
sndr launch <key> --dry-run
sndr launch <key> --preflight-only
sndr model-config validate <key>
sndr patches ...
sndr explain PN59
sndr report bundle ...
```

Friendly CLI должен быть thin wrapper над engineer CLI/Product API, а не отдельной реализацией.

---

## 10. Документация и упаковка

Сейчас документация богата, но для массового пользователя слишком много входов и старых исторических слоев.

Нужно разделить docs:

```text
docs/
  START_HERE.md              # 10-minute first run
  USER_GUIDE.md              # GUI/TUI oriented
  SSH_OPERATOR_GUIDE.md      # CLI/SSH path
  TROUBLESHOOTING.md         # error explainer index
  CLIENTS.md                 # Cursor/OpenCode/OpenAI SDK/LiteLLM
  ADVANCED_PATCHES.md        # patch registry, env flags
  ARCHITECTURE.md            # for contributors
```

README должен стать короче:

- what it does;
- who it is for;
- one screenshot/GIF;
- install;
- supported GPUs/models;
- proof numbers;
- links to docs.

Патчи и detailed internals оставить, но ниже и в advanced docs.

---

## 11. Roadmap по фазам

### Phase 0: Product cleanup and naming

Срок: 2-4 дня.

Работы:

- Зафиксировать публичное имя: `SNDR` или `Genesis`, выбрать один primary brand.
- Описать 3 persona: home GPU owner, SSH operator, small team.
- Составить список терминов, которые нельзя показывать beginner mode.
- Сделать `docs/START_HERE.md`.
- Обновить README first viewport под user outcome.

Результат:

- Проект становится понятнее за 60 секунд.

Риск:

- Можно потерять инженерную глубину в README. Решение: вынести ее в advanced docs.

### Phase 1: Product API foundation

Срок: 1-2 недели.

Работы:

- Добавить `vllm/sndr_core/product/`.
- Обернуть existing primitives: host inventory, deps plan, config list, recommender, launch preflight, status.
- Ввести стабильные dataclasses/Pydantic-like schemas без тяжелых зависимостей.
- Добавить JSON snapshots для GUI/TUI.
- Покрыть unit tests.

Результат:

- GUI/TUI/CLI получают один источник правды.

Риск:

- Если API начнет выполнять shell side effects без явного apply step, GUI станет опасным. Нужна строгая граница plan/apply.

### Phase 2: TUI first

Срок: 1-2 недели.

Работы:

- Добавить `sndr tui`.
- Экран inventory.
- Экран goal/workload picker.
- Экран recommended preset/model.
- Экран readiness plan.
- Экран launch monitor.
- Экран endpoint/client config.

Результат:

- SSH-friendly массовый UX.
- Быстрый способ проверить будущий GUI flow.

Риск:

- TUI может стать отдельным кодом. Решение: TUI только вызывает Product API.

### Phase 3: Local GUI dashboard

Срок: 2-4 недели.

Работы:

- Добавить `sndr gui`.
- Локальный web server на `127.0.0.1`.
- Dashboard + setup wizard.
- Model library.
- Launch monitor with log events.
- Client config page.
- Advanced panel.

Результат:

- Проект становится визуальным и пригодным для менее технических пользователей.

Риск:

- Web UI потянет frontend complexity. Решение: начать с простого server-rendered UI или легкого SPA без тяжелого state stack.

### Phase 4: Service and lifecycle polish

Срок: 1-2 недели.

Работы:

- Довести `sndr service` до first-class.
- Support: systemd, Quadlet, Docker Compose.
- Start/stop/restart/status/logs.
- GUI/TUI buttons use service layer.
- Add rollback and safe update flow.

Результат:

- Пользователь перестает воспринимать SNDR как одноразовый install script.

### Phase 5: Client ecosystem

Срок: 1 неделя.

Работы:

- `sndr clients list`.
- `sndr clients show cursor`.
- GUI page with copyable configs.
- OpenAI SDK smoke.
- LiteLLM config.
- Agent coding presets.

Результат:

- Запущенный endpoint сразу становится полезным.

### Phase 6: Community presets marketplace

Срок: 2-3 недели.

Работы:

- Сделать browser для community configs.
- Trust/lifecycle badge: experimental, verified, prod.
- Import/export config bundle.
- Report successful verification back to GitHub issue/discussion manually or via opt-in.
- GUI "submit my config" flow.

Результат:

- Расширение железа и моделей идет через community, а не только через maintainer.

### Phase 7: Paid Pro boundary

Срок: после стабилизации free flow.

Возможные Pro функции:

- curated verified profiles;
- GUI advanced dashboard;
- automatic update compatibility advisor;
- team config export/import;
- priority diagnostic rules;
- private support bundle workflow;
- multi-node/fleet view;
- commercial `sndr_engine` overlays, если появится настоящий private IP.

Важно: open-core граница должна быть честной. Core patching and basic CLI должны оставаться полезными.

---

## 12. Приоритетный backlog

### P0: Без этого массовость невозможна

- Product API layer.
- `sndr tui`.
- `docs/START_HERE.md`.
- Beginner vocabulary cleanup.
- Recommended model/preset flow.
- Service status abstraction.
- Client config generator.

### P1: Сильно повышает adoption

- `sndr gui`.
- Model download manager.
- Error explainer.
- Benchmark health card.
- Report bundle UX.
- README simplification with screenshots.

### P2: Расширяет рынок

- Community preset browser.
- Team config bundles.
- Podman/Quadlet polish.
- Kubernetes manifest polish.
- Remote GUI via SSH tunnel guide.
- Hardware compatibility public matrix.

### P3: Monetization / Pro

- Pro profile pack.
- Update compatibility advisor.
- Team/fleet dashboard.
- SLA/support workflow.
- Signed commercial engine overlays.

---

## 13. Что конкретно менять в репозитории

### Новые модули

```text
vllm/sndr_core/product/
vllm/sndr_core/tui/
vllm/sndr_core/gui/
vllm/sndr_core/clients/
```

### Расширить существующие

```text
vllm/sndr_core/cli/__init__.py       # add setup/status/tui/gui/clients friendly commands
vllm/sndr_core/cli/service.py        # make service lifecycle central
vllm/sndr_core/cli/report.py         # expose beginner report flow
vllm/sndr_core/findings/             # user-facing error explainer
vllm/sndr_core/model_configs/        # model cards and recommendation metadata
vllm/sndr_core/deps/                 # convert plan to beginner-friendly actions
```

### Документация

```text
docs/START_HERE.md
docs/USER_GUIDE.md
docs/SSH_OPERATOR_GUIDE.md
docs/CLIENTS.md
docs/TROUBLESHOOTING.md
docs/ADVANCED_PATCHES.md
```

---

## 14. Критерии готовности

### MVP mass-user

Готово, когда новый пользователь может:

1. Установить SNDR.
2. Выбрать цель, а не patch/config key.
3. Получить recommended model/preset.
4. Запустить endpoint.
5. Проверить test prompt.
6. Получить client config.
7. Создать report bundle при ошибке.

Без чтения patch registry.

### MVP engineer

Готово, когда оператор может:

1. Выполнить все через SSH без GUI.
2. Получить JSON outputs для CI.
3. Render/dry-run все runtime artifacts.
4. Проверить config/pin/drift.
5. Сгенерировать bundle для передачи другому человеку.

### MVP team

Готово, когда можно:

1. Экспортировать рабочую конфигурацию.
2. Импортировать на другой машине.
3. Запустить verify against reference.
4. Получить diff по performance/VRAM/tool quality.

---

## 15. Самое важное решение

Не надо начинать с красивого GUI.

Правильная последовательность:

1. Product API.
2. TUI.
3. Friendly CLI aliases.
4. GUI.
5. Service lifecycle.
6. Client ecosystem.
7. Community presets.

Так проект сохранит инженерную силу и одновременно станет понятным для широкой аудитории.

Если начать с GUI без API, получится fragile оболочка над shell commands. Если начать с API и TUI, GUI станет естественным следующим слоем.

---

## 16. Итоговая формула продукта

Техническое ядро:

> Genesis/SNDR patches and validates vLLM for consumer/workstation GPUs.

Массовый продукт:

> SNDR turns your NVIDIA GPU box into a local OpenAI-compatible AI server.

Инженерный продукт:

> SNDR gives operators a reproducible, diagnosable and benchmarked vLLM runtime stack.

Это одна и та же система, но с разными дверями входа.
