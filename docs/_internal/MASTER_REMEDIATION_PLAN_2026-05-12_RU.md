# Master Remediation Plan — Genesis vLLM Patches (2026-05-12)

**Версия плана:** 1.0
**Дата старта:** 2026-05-12
**Автор:** автономная сессия (claude opus 4.7) + ревью оператора (Sander)
**Назначение:** единая память по всем незакрытым задачам, чтобы можно было прерывать и возобновлять работу без потери контекста.

---

## Как читать этот документ

1. Раздел **«Контекст и цели»** — зачем этот план существует и что мы хотим получить.
2. Раздел **«Текущее состояние»** — слепок состояния проекта на момент старта плана.
3. Раздел **«Целевое состояние»** — куда мы должны прийти.
4. Раздел **«Принципы работы»** — правила, по которым ведём изменения.
5. Раздел **«Этапы 0-8»** — конкретные действия (приоритет 1 — закрытие двух review-документов).
6. Раздел **«Следующие приоритеты»** — что делаем после Этапов 0-8.
7. Раздел **«Долгосрочные направления»** — после стабилизации.
8. Раздел **«Журнал прогресса»** — обновляется по мере выполнения, чтобы не повторяться.

**Правило обновления:** после закрытия каждого item — обновить статус в таблице соответствующего этапа (`[ ]` → `[x]`) + добавить запись в журнал прогресса.

---

## 1. Контекст и цели

### 1.1 История

В период 2026-05-09 .. 2026-05-12 в проекте Genesis vLLM Patches был проведён комплексный аудит. Основные документы:

- `docs/_internal/COMPREHENSIVE_DUAL_STATE_AUDIT_2026-05-12_RU.md` — основной аудит (1034 строки).
- `docs/_internal/PROJECT_STATE_AUDIT_2026-05-12_RU.md` — структурный аудит CLI/deploy/PN95.
- `docs/_internal/SERVER_CHANGE_WATCH_2026-05-12_RU.md` — review-журнал параллельного аудитора, фиксировавшего каждый batch правок текущей сессии и помечавшего ошибки/риски.
- `docs/_internal/LOCAL_SERVER_DUAL_STATE_FIX_PLAN_2026-05-12_RU.md` — план приведения локального и серверного деревьев к общему знаменателю.
- `docs/_internal/REMAINING_WORK_PLAN_2026-05-12_RU.md`, `FULL_PROJECT_AUDIT_2026-05-09_RU.md`, `UNIFIED_CONFIG_AUTOMATION_PLAN_2026-05-09_RU.md` — расширения и предыдущие аудиты.

В рамках сессии 2026-05-12 было закрыто 18 items из основного аудита (S1.1-1.6, S2.1-2.5, S3.1-3.3, S4.1, S5.1-plan, S5.2). Однако параллельный review-аудит (`SERVER_CHANGE_WATCH`) зафиксировал, что часть моих правок содержит **новые** ошибки/риски, и что не все рекомендации из `LOCAL_SERVER_DUAL_STATE_FIX_PLAN` были учтены.

### 1.2 Зачем нужен этот план

1. Не терять контекст между сессиями — все незакрытые задачи в одном месте.
2. Закрыть ошибки моей собственной работы (heartbeat-журнал прямо указывает на них).
3. Привести местное и серверное дерево в согласованное состояние.
4. Подготовить почву для следующих приоритетов (PN95, upstream, models).
5. Не повторять ранее найденные ошибки.

### 1.3 Цели плана

**Краткосрочные (Этапы 0-8):**

- Закрыть все P0/P1 findings из `SERVER_CHANGE_WATCH` и `LOCAL_SERVER_DUAL_STATE_FIX_PLAN`.
- Привести local/server деревья к согласованному состоянию.
- Подключить заявленные automation к реальным workflow (watchlist → audit).
- Убрать приватные пути/IP из публичных файлов.

**Среднесрочные (после Этапов):**

- Закрыть 5 P0 блокеров из `PROJECT_STATE_AUDIT`.
- CLI gaps (`sndr config list`, `sndr launch --preflight-only`, etc).
- ModelConfig schema gaps (Y1-Y14 blocks).
- Architecture debt (P2.1-P2.3 — dispatch collapse, unified contract, ratchet).
- Deploy gaps (Proxmox apply, K8s GPU operator detection).
- Testing/CI/Observability.
- Docs reorganization.

**Долгосрочные (после стабилизации):**

- PN95 / Memory большой блок (Phase 2-3 GPU↔CPU bytes, Phase 5 virtualization, OOM preflight).
- Upstream backports (PN90-PN94 ports когда upstream merges).
- Models: Gemma 4, Huihui-Qwen, Qwen3 extensions Q-Ext-1-3.
- Distributed bench infra.
- Поиск новых решений (research after stabilization).

---

## 2. Текущее состояние (baseline)

**Снимок снят:** 2026-05-12 ~08:21 EEST.

### 2.1 Git state

| Параметр | Локально | Сервер |
|---|---|---|
| Commit | `f9576df` | `f9576df` |
| Branch | `dev` (NB: до коммита `cleanup` шла серия — реальная HEAD может отличаться) | `dev` |
| `git status --short` | 509 entries | 528 entries |
| Status hash | — | `91f5c7476927311fe016d9eb0f58e68a40c3579c6750ac84e3ad0cd89920cb1c` |

**Что это значит:**

- Корневой `vllm/sndr_core` содержательно совпадает на обеих сторонах (356 файлов без cache, content diff пуст).
- Но рабочие деревья отличаются по обвязке (docs, .github, benchmarks, sndr_engine).
- Все мои новые файлы текущей сессии находятся в статусе `??` (untracked) — это P1 риск.

### 2.2 Pytest state

| Окружение | Result |
|---|---|
| Local | 5385 passed / 0 failed / 122 skipped |
| Server | 5413 passed / 0 failed / 94 skipped |

Guard-проверки (на обеих сторонах):

- `python3 -m vllm.sndr_core.compat.cli self-test --json` — PASS 8/8.
- `python3 -m vllm.sndr_core.apply.shadow --strict` — CLEAN.

### 2.3 Runtime state (сервер)

- `vllm-pn95-2xa5000` — запущен, порт 8101, image `vllm/vllm-openai:nightly`, dev209.
- `nvidia-gpu-exporter`, `docker-sandbox-1` — baseline restart-loop (не Genesis-related, но текущий `sndr doctor-system --logs` краснит на них).

### 2.4 Что было закрыто в текущей сессии (18 items)

| Sprint | Item | Status |
|---|---|---|
| S1.1 | PN26 torch-less apply contract | ✅ done |
| S1.2 | Server stale `vllm.sndr_core.patches` imports cleanup (118 refs) | ✅ done |
| S1.3 | Hardcoded HOST в `tools/long_ctx_smoke.sh`, `tools/soak.sh`, Makefile | ✅ done |
| S1.4 | content=null OpenAI smoke (`tools/openai_smoke.py` + REASONING_CONTENT_CONTRACT.md) | ✅ done |
| S1.5 | Server cleanup `__pycache__` + root bench artifacts | ✅ done |
| S1.6 | Legacy-import CI gate (`scripts/check_no_legacy_imports.sh`) | ✅ done (есть оговорки в Этапе 5) |
| S2.1 | Ed25519 trust anchor activation | ✅ done (есть оговорки в Этапе 0) |
| S2.2 | Registry metadata overlay (`registry_metadata.py`) | ✅ done (есть оговорки в Этапе 0) |
| S2.3 | Docs `_genesis` cleanup в INSTALL/CONTRIBUTING/BENCHMARK/launch README | ✅ partial (есть оговорки в Этапе 6) |
| S2.4 | `sndr doctor-system --logs` + 25 unit tests | ✅ done (есть оговорки в Этапе 3) |
| S2.5 | CompatibilityMatrix (4 rules + 21 tests) | ✅ done (после refine COMPAT-001 на qwen-next) |
| S3.1 | Docker Compose renderer + 11 tests | ✅ done (есть оговорки в Этапе 2) |
| S3.2 | Podman Quadlet renderer + 11 tests | ✅ done (есть оговорки в Этапе 2) |
| S3.3 | K8s nodeSelector/PVC/Secret + 9 tests | ✅ done (есть оговорки в Этапе 2) |
| S3.4 | Proxmox apply | ⏸ deferred (нужен PVE testbed) |
| S4.1 | vllm#42102 watchlist entry + backport plan | ✅ done (есть оговорки в Этапе 5 — automation не подключена) |
| S5.1 | PN96 A/B bench plan | 📄 plan ready (есть оговорки в Этапе 7 — ссылается на отсутствующие scripts) |
| S5.2 | CHANGELOG + final sync | ✅ done |

### 2.5 Что НЕ закрыто

Все findings из:

- `SERVER_CHANGE_WATCH_2026-05-12_RU.md` heartbeats #1-#5 (P0/P1/P2 пометки).
- `LOCAL_SERVER_DUAL_STATE_FIX_PLAN_2026-05-12_RU.md` (§4 - §8).

Сводный список = Этапы 0-8 этого документа.

---

## 3. Целевое состояние

После закрытия Этапов 0-8 проект должен выйти в состояние:

### 3.1 Security & correctness

- License token подписан И валидируется по строгому payload contract (required fields + types + expiry).
- Trust anchor private key никогда не печатается в stdout без явного `--print-private`.
- Текущий dev/test private key перевыпущен offline; в репозитории только public key.
- `production_default=eligible` присваивается **только** при `stable + test_status != none` ИЛИ explicit audited override.
- Compose render не утекает API key в файл; секреты через `.env`/Docker secrets/K8s Secret refs.

### 3.2 Local/server convergence

- `benchmarks/harness/run_all.py` — local version (no hardcoded IP).
- `.github/PULL_REQUEST_TEMPLATE.md` — v11-aware local version.
- `.pre-commit-config.yaml` — присутствует, `make precommit` работает.
- `vllm/sndr_engine` — единая policy (Variant B: no public skeleton).
- Public docs не содержат `192.168.1.10`, `/home/sander`, `sander@`, `User=sander`.
- `benchmarks/runs/*`, `.DS_Store` — не tracked.
- Все новые файлы текущей сессии — committed.
- Docs migration map создан.

### 3.3 Deploy correctness

- Compose/Quadlet/K8s используют единый `RuntimeCommandSpec` builder с identical CLI argv.
- Unified mount resolver — нет silent unresolved `${...}` placeholders.
- Quadlet escaping safe для newline/quotes/spaces.
- K8s YAML через `yaml.safe_dump_all` + DNS-1123 validation.
- `k8s delete` опционально удаляет PVC через `--delete-pvc`.

### 3.4 Observability accuracy

- `sndr doctor-system --logs` корректно фильтрует events по window:
  - ctime parser работает.
  - Unknown timestamp по умолчанию не включается в strict window.
  - `--logs-container-prefix` фильтрует unrelated containers (default: `vllm`, `genesis`).

### 3.5 Automation wiring

- `make audit-upstream` читает `UPSTREAM_WATCHLIST.yaml` и выдаёт `PORT_CANDIDATE`/`RETIRE_CANDIDATE`/`DRIFT`.
- `check_no_legacy_imports.sh` использует AST-based scanner — ловит `from X import Y` варианты.
- Scanner покрывает .py/.sh/.md + JSON/YAML/TOML/workflow files.

### 3.6 Docs hygiene

- Hardcoded `/home/sander`, `sander@`, `192.168.1.10` — отсутствуют в public docs.
- `_genesis` упоминается только в migration appendix, не в active install guide.
- `scripts/launch/README.md` ссылается только на существующие файлы.
- PN96 bench plan executable: ссылается на v11 canonical tools.

### 3.7 PN26 polish

- Log text и runtime messages соответствуют реальному lean v2 поведению (не упоминают `_genesis` namespace, не обещают BLASST adaptive scale).
- `GENESIS_PN26_SPARSE_V_LOG_EVERY` валидируется.
- `test_pn59_streaming_gdn.py` использует `pytest.importorskip("torch")`.

---

## 4. Принципы работы

Эти правила взяты из `SERVER_CHANGE_WATCH §2` и расширены.

### 4.1 Безопасность изменений

1. **Маленькие batches.** Одна подсистема, один контракт, один набор тестов за batch.
2. **Перед изменением:** локальный diff + список затронутых entrypoints.
3. **После изменения:** обязательный минимум проверок:
   - `python3 -m vllm.sndr_core.compat.cli self-test --json`
   - `python3 -m vllm.sndr_core.apply.shadow --strict`
   - AST parse изменённых `.py`
   - Parse изменённых `.yaml`/`.json`/`.toml`
   - `bash -n` изменённых `.sh`
   - Targeted pytest на затронутых тестах.
4. **Не ослаблять assertions** в тестах вместо исправления контракта.
5. **Не использовать `--no-verify`** на pre-commit hooks без явной причины.
6. **Server runtime не трогать** без отдельного разрешения (Docker containers — running production).
7. **GPU-проверки** — короткие smoke, не длительная нагрузка.

### 4.2 Git hygiene

1. Все новые файлы — в commit (или явный плановый delete) до перехода к следующему batch.
2. Не оставлять untracked деривативы в `??` статусе между sessions.
3. Перед коммитом — `git status` + явный список добавляемых файлов (`git add <path>` per file, не `git add .`).
4. Commit message — описывает суть изменения, не процесс.
5. **Не push в GitHub** — это прямой запрет оператора. Локальные commits + rsync на сервер.

### 4.3 Документация

1. Internal work logs — только в `docs/_internal/`.
2. Public docs не должны содержать приватные пути/IP/usernames.
3. Если doc описывает automation — automation должна реально существовать и работать. Иначе явно пометить как "design only".
4. После каждого fix — обновить relevant doc (или этот мастер-план).

### 4.4 Acceptance per batch

После закрытия каждого item:

1. Отметить в таблице `[ ]` → `[x]`.
2. Записать в журнал прогресса:
   - Что было.
   - Что сделано (файлы + строки).
   - Что верифицировано (команды + result).
3. Если возникли side-effects — открыть новый item.

### 4.5 Когда тормозить

Если в процессе работы обнаруживается, что:

- Fix требует изменения публичного API → согласовать с оператором.
- Fix трогает production runtime (Docker container на сервере) → согласовать с оператором.
- Fix конфликтует с другим запланированным item → обновить план перед продолжением.
- Возникает новый риск, не описанный в плане → добавить в план до закрытия текущего batch.

---

## 5. Этапы 0–8 (приоритет 1 — закрытие двух review-документов)

Каждый этап описан в формате:

- **Цель** — что хотим получить.
- **Items** — таблица с status / problem / fix / acceptance.
- **Acceptance global** — общая проверка по завершении этапа.

### Этап 0 — Security & correctness (P0/P1)

**Цель:** убрать утечки секретов, привести license/trust-anchor к production-grade.

**Время:** 3-4 часа.

#### 0.1 License payload strict validation

- **Status:** `[x]` — closed in commit 680d06d (2026-05-12)
- **Problem:** `vllm/sndr_core/license.py:319-350` — после успешной подписи payload почти не валидируется. Отсутствующие или строковые `expires_at`, отсутствующие `customer_id`/`issued_at`/`engine_major` не блокируются.
- **Последствие:** Подписанный payload без срока действия становится **бессрочным**. Для production root-of-trust это критично.
- **Fix:**
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
  # Дополнительно: expires_at > now (skew tolerance ~60s), issued_at <= now + skew.
  ```
- **Варианты:**
  - **A (выбран):** strict gate в `verify_token` — рекомендация SERVER_CHANGE_WATCH §heartbeat#2.
  - **B:** soft gate с warning — отказались, потому что для production root-of-trust нужна строгая семантика.
- **Acceptance:**
  - `pytest tests/unit/test_license.py` — pass.
  - Новые тесты: missing `expires_at` → fail, string `expires_at` → fail, expired token → fail, wrong `engine_major` → fail.

#### 0.2 Trust anchor private key — не печатать в stdout

- **Status:** `[x]` — closed in commit 680d06d (2026-05-12)
- **Problem:** `scripts/generate_trust_anchor.py:172-182` всегда выводит private key в stdout. Терминальные логи, shell history, recorder/scrollback могли сохранить ключ. Текущий ключ (`iSk29MUb9HldKokPRyOG7bAjwYaQdgqYsS17yfskE8s`) считать **dev/test ключом**, а не production.
- **Последствие:** Production root-of-trust compromised.
- **Fix:**
  - `--out <path>` записывает private key в файл с правами `0600`, **не печатает в stdout**.
  - `--print-private` явный флаг для случаев, когда оператор хочет увидеть ключ в stdout.
  - Default-режим: пишет только public key в stdout (для копирования в license.py).
  - Documentation in `TRUST_ANCHOR_CEREMONY.md` обновлена.
- **Дополнительно:**
  - Перегенерировать production-key offline по обновлённой ceremony.
  - Текущий public key (`iSk29MUb9HldKokPRyOG7bAjwYaQdgqYsS17yfskE8s`) считать compromised по факту exposure.
  - Если у оператора уже есть offline-backup нового pair — заменить константу `_TRUST_ANCHOR_PUBKEY_B64URL`.
  - Иначе — оставить текущий как **dev/test anchor** и завести задачу на production-ceremony отдельно (это требует оператора у offline machine).
- **Варианты:**
  - **A (выбран):** перегенерация offline + обновление generator script.
  - **B:** оставить как есть с пометкой "dev key" — отказались, документация претендует на production.
- **Acceptance:**
  - `python3 scripts/generate_trust_anchor.py --out /tmp/k.priv` → stdout содержит **только** public key, файл `/tmp/k.priv` mode `0600` содержит private key.
  - `python3 scripts/generate_trust_anchor.py --out /tmp/k.priv --print-private` → stdout содержит private key.
  - Новый unit test: `--out --quiet` не содержит private key в stdout.

#### 0.3 `production_default=eligible` только при наличии тестов

- **Status:** `[x]` — closed in commit 680d06d (2026-05-12)
- **Problem:** `vllm/sndr_core/dispatcher/registry_metadata.py:172-195` — `lifecycle=stable` → автоматически `implementation_status=full` + `production_default=eligible`, даже если `test_status=none`.
- **Текущая статистика:** `eligible=120`, `test_status: none=91`. Часть `eligible` патчей не имеет тестового покрытия.
- **Последствие:** Завышение production-готовности; патчи без тестов могут попасть в production matrix.
- **Fix:** Правило `derive_metadata`:
  ```python
  if lc == "stable":
      if test_status == "none":
          production_default = "review_required"  # требует ручного override
      else:
          production_default = "eligible"
  ```
  - Добавить в `EXPLICIT_OVERRIDES` патчи, которые reviewer-approved несмотря на отсутствие тестов (например, mechanical retired-anchor patches).
- **Варианты:**
  - **A (выбран):** strict — `eligible` только с тестами или explicit override.
  - **B:** оставить как есть с warning в lifecycle audit — отказались, audit-output легко игнорируется.
- **Acceptance:**
  - После fix: `python3 -c "from vllm.sndr_core.dispatcher.spec import iter_patch_specs; ..."` — количество `eligible` уменьшается, появляется новый статус `review_required`.
  - Обновить ratchet test чтобы он принимал `review_required`.
  - Документация в registry_metadata.py обновлена.

#### 0.4 Compose API key — не утекает в /tmp

- **Status:** `[x]` — closed in commit 680d06d (2026-05-12)
- **Problem:** `vllm/sndr_core/cli/compose.py:226-229,301-309` — `VLLM_API_KEY` попадает в `environment:` блок rendered compose YAML, который пишется в фиксированный путь `/tmp/sndr-compose/docker-compose.<key>.yml`.
- **Последствие:** Любой пользователь системы может прочитать API key. На multi-user host это утечка credential.
- **Fix:**
  - Compose YAML не содержит literal `VLLM_API_KEY`. Вместо этого:
    ```yaml
    environment:
      - VLLM_API_KEY  # value подтягивается из shell env
    ```
    или
    ```yaml
    env_file:
      - .env  # operator кладёт ключ в .env с правами 0600
    ```
  - Tempdir `/tmp/sndr-compose/` создаётся с mode `0700`.
  - В docstring `sndr compose render` явно сказать "API key inherited from shell env or .env file — never written to rendered YAML".
  - Аналогично проверить Quadlet (Этап 2.3) и K8s Secret refs (Этап 2.4).
- **Acceptance:**
  - `grep -F "VLLM_API_KEY=" /tmp/sndr-compose/docker-compose.*.yml` — should be empty (либо только `VLLM_API_KEY` без value).
  - Test: `test_compose_render.py::test_api_key_not_in_yaml`.
  - Tempdir mode test.

#### 0.5 `TRUST_ANCHOR_CEREMONY.md` — `verify_token` API

- **Status:** `[x]` — closed in commit 680d06d (2026-05-12)
- **Problem:** `docs/security/TRUST_ANCHOR_CEREMONY.md:74-90` ссылается на `verify_token`, но в `license.py` есть только private `_verify_signed_token`. Doc описывает operational playbook с несуществующим API.
- **Fix:** Два варианта:
  - **A (выбран):** Экспонировать public API `verify_token` в `license.py` (тонкая обёртка над `_verify_signed_token`).
  - **B:** Обновить ceremony doc на private name — менее правильно, public ceremony должен использовать public API.
- **Acceptance:**
  - `from vllm.sndr_core.license import verify_token` работает.
  - Doc обновлён и `python3 -c "..."` snippet из doc запускается без ошибок.

#### 0.6 `license.py` docstring — legacy gate clarification

- **Status:** `[x]` — closed in commit 680d06d (2026-05-12)
- **Problem:** `vllm/sndr_core/license.py:12-14` — top docstring говорит "legacy non-empty string accepted with warning". Реальный код `:459-482` принимает legacy key только при `SNDR_ALLOW_LEGACY_LICENSE_KEYS=1`; иначе `BAD_SIGNATURE`.
- **Fix:** Привести docstring в соответствие с реальным поведением (default = strict; opt-in via env).
- **Acceptance:** Diff review подтверждает соответствие.

**Acceptance Этапа 0:**

```bash
pytest tests/unit/test_license.py tests/unit/test_trust_anchor_generator.py tests/unit/test_trust_anchor_not_placeholder.py tests/unit/dispatcher/test_spec_metadata_enrichment.py tests/unit/cli/test_compose_render.py -q
# Все зелёные.

grep -rn "VLLM_API_KEY=" /tmp/sndr-compose/ 2>/dev/null
# Empty (нет утечки ключа).

python3 scripts/generate_trust_anchor.py --out /tmp/test_key 2>&1 | grep -F "BEGIN PRIVATE"
# Empty (private key не в stdout).
```

---

### Этап 1 — Local/Server dual-state convergence (P1)

**Цель:** привести местное и серверное деревья к одному ожидаемому состоянию.

**Время:** 2 часа.

#### 1.1 `benchmarks/harness/run_all.py` — sync local → server

- **Status:** `[x]` — closed in commit 680d06d (2026-05-12)
- **Problem:** Серверная версия имеет hardcoded `http://192.168.1.10:8000/v1` в default. Локальная использует `127.0.0.1:8000/v1`.
- **Fix:** `rsync` local file → server. Verify.
- **Acceptance:**
  - `grep "192.168.1.10" benchmarks/harness/run_all.py` — empty on server.
  - Lint: `rg -n "192\.168\.1\.10|sander@|/home/sander" benchmarks scripts tools vllm docs` — empty.

#### 1.2 `.github/PULL_REQUEST_TEMPLATE.md` — sync local → server

- **Status:** `[x]` — closed in commit 680d06d (2026-05-12)
- **Problem:** Серверный template устарел (упоминает `wiring/patch_*.py`, `dispatcher.py`, `vllm/sndr_core/tests/`). Локальный v11-aware.
- **Fix:** `rsync` local → server.
- **Acceptance:** Diff пустой.

#### 1.3 `.pre-commit-config.yaml` — sync local → server

- **Status:** `[x]` — closed in commit 680d06d (2026-05-12)
- **Problem:** Отсутствует на сервере. `Makefile precommit` target не работает.
- **Fix:** `rsync` local → server. Run `pre-commit run --all-files` в offline-safe режиме.
- **Acceptance:**
  - `make precommit` на сервере не падает с "config not found".
  - При первом запуске может потребоваться `pre-commit install` — это OK.

#### 1.4 `vllm/sndr_engine` — policy decision

- **Status:** `[x]` — closed in commit 680d06d (2026-05-12)
- **Problem:** Локально есть skeleton (`__init__.py`, `version.py`, `LICENSE-NOTICE`); на сервере отсутствует. Docs противоречат друг другу.
- **Варианты:**
  - **A:** Public skeleton присутствует, `engine_available() → False` пока нет paid overlay.
    - Плюс: docs честно описывают reserved namespace.
    - Минус: `import vllm.sndr_engine` больше не является proof наличия engine.
  - **B (рекомендация):** Public skeleton отсутствует.
    - Плюс: меньше риск случайно опубликовать private namespace.
    - Минус: docs и тесты переписать под отсутствие package.
- **Решение:** **Variant B** (рекомендация из LOCAL_SERVER_DUAL_STATE_FIX_PLAN §4 P1).
- **Fix:**
  - Удалить `vllm/sndr_engine/` локально.
  - Обновить `README.md`, `pyproject.toml`, `vllm/sndr_core/license.py`, `vllm/sndr_core/bundles/_common.py`, `vllm/sndr_core/dispatcher/decision.py`, tests/docs — везде, где упоминается `vllm.sndr_engine`, привести к описанию "reserved namespace, package not shipped publicly; presence checked via optional overlay/entry-point".
  - `engine_available()` должен возвращать `False` через optional discovery API, не через package import.
- **Acceptance:**
  - `python3 -c "from vllm.sndr_core.license import engine_available; print(engine_available())"` → `False` без `ImportError`.
  - `find vllm/sndr_engine -type f` → empty.
  - Docs не утверждают "namespace exists as package".

#### 1.5 `docs/WORK_LOG_2026-05-12_RU.md` — public removal

- **Status:** `[x]` — closed in commit 680d06d (2026-05-12)
- **Problem:** Серверный файл `docs/WORK_LOG_2026-05-12_RU.md` дублирует `docs/_internal/WORK_LOG_2026-05-12_RU.md` и содержит server IP `192.168.1.10`.
- **Fix:**
  - Удалить `docs/WORK_LOG_2026-05-12_RU.md` (на сервере).
  - Убедиться, что `docs/_internal/WORK_LOG_2026-05-12_RU.md` синхронизирован.
- **Acceptance:**
  - `ls docs/WORK_LOG_2026-05-12_RU.md` — fail (file not found).
  - `rg -n "192\.168\.1\.10" docs/ README.md` — empty.

#### 1.6 `benchmarks/runs/*` — runtime artifacts cleanup

- **Status:** `[x]` — closed in commit 680d06d (2026-05-12)
- **Problem:** На сервере есть `benchmarks/runs/genesis_bench_quick_*.json/md` (20+ файлов).
- **Варианты:**
  - **A:** Сохранить как internal evidence в `docs/_internal/bench_results/`.
  - **B (рекомендация):** Удалить + добавить `benchmarks/runs/` в `.gitignore`.
- **Решение:** **Variant B** — это runtime outputs, должны быть в `_archive` или вовсе не в repo.
- **Fix:**
  - На сервере: `rm benchmarks/runs/*.json benchmarks/runs/*.md`.
  - Обновить `.gitignore`:
    ```
    benchmarks/runs/
    !benchmarks/runs/.gitkeep
    ```
- **Acceptance:**
  - `ls benchmarks/runs/` — empty или только `.gitkeep`.
  - `.gitignore` содержит `benchmarks/runs/`.

#### 1.7 `.DS_Store` cleanup

- **Status:** `[x]` — closed in commit 680d06d (2026-05-12)
- **Problem:** Server has `tools/genesis_vllm_plugin/.DS_Store`, `tools/genesis_vllm_plugin/genesis_v7/.DS_Store`.
- **Fix:**
  - `find . -name ".DS_Store" -delete`.
  - Убедиться, что `.gitignore` содержит `.DS_Store`.
- **Acceptance:**
  - `find . -name ".DS_Store" -not -path "./.git/*"` — empty.

#### 1.8 Root `generate_patches_md.py` cleanup

- **Status:** `[x]` — closed in commit 680d06d (2026-05-12)
- **Problem:** Серверный root-level `generate_patches_md.py` дублирует `scripts/generate_patches_md.py`.
- **Варианты:**
  - **A:** Удалить root file.
  - **B:** Сделать тонкий wrapper, импортирующий `scripts/generate_patches_md.py`.
- **Решение:** **Variant A** — root entry point не нужен, `scripts/` достаточно.
- **Fix:** `rm generate_patches_md.py` (на сервере).
- **Acceptance:** `ls generate_patches_md.py` — fail.

#### 1.9 Untracked state cleanup — commit session deliverables

- **Status:** `[x]` — closed in commit 680d06d (2026-05-12)
- **Problem:** Все мои новые файлы текущей сессии находятся в `??` статусе:
  - `vllm/sndr_core/cli/doctor_logs.py`
  - `vllm/sndr_core/cli/compose.py`
  - `vllm/sndr_core/cli/quadlet.py`
  - `vllm/sndr_core/dispatcher/registry_metadata.py`
  - `scripts/check_no_legacy_imports.sh`
  - `scripts/generate_trust_anchor.py`
  - `tools/openai_smoke.py`
  - `tests/unit/cli/test_doctor_logs.py`
  - `tests/unit/cli/test_compose_render.py`
  - `tests/unit/cli/test_quadlet_render.py`
  - `tests/unit/cli/test_k8s_render.py`
  - `tests/unit/model_configs/test_compatibility_matrix.py`
  - `tests/unit/test_trust_anchor_not_placeholder.py`
  - `docs/REASONING_CONTENT_CONTRACT.md`
  - `docs/security/TRUST_ANCHOR_CEREMONY.md`
  - `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md`
  - `docs/_internal/research/upstream_42102_dflash_independent_kv_groups_plan_2026-05-12.md`
  - `docs/_internal/WORK_LOG_2026-05-12_RU.md`
  - `docs/_internal/MASTER_REMEDIATION_PLAN_2026-05-12_RU.md` (этот документ)
- **Fix:**
  - **Не делать `git add .`** — есть риск зацепить мусор.
  - Per-file review + `git add <path>`.
  - Commit с подробным message (описать каждый sprint).
  - **Push на GitHub запрещён** — только local commits + rsync на сервер.
- **Acceptance:**
  - `git status --short` показывает только intentional dirty files (modifications, deletes по плану).
  - Все session deliverables в tracked state.

**Acceptance Этапа 1:**

```bash
# Local
git status --short | wc -l
# Уменьшилось значительно (close to 0 для untracked сессионных файлов)

rg -n "192\.168\.1\.10|/home/sander|User=sander|sander@" benchmarks scripts tools docs README.md
# Empty

find . -name ".DS_Store" -not -path "./.git/*"
# Empty

# Server
ssh sander@192.168.1.10 'cd ~/genesis-vllm-patches-v11 && ls .pre-commit-config.yaml'
# Exists
```

---

### Этап 2 — Deploy correctness (P2)

**Цель:** убрать divergence между compose/quadlet/k8s emitters, валидировать ввод, корректно эмитить YAML.

**Время:** 4-5 часов.

#### 2.1 Unified `RuntimeCommandSpec` builder

- **Status:** `[x]` — closed in commit f4ce433 (2026-05-13)
- **Problem:** `compose.py:_container_command` строит `["vllm", "serve", cfg.model_path]`. Canonical `schema.py::to_launch_script` использует `vllm serve --model <path>` и учитывает `language_model_only`. Разные emitters могут эмитить **разные** argv для одного и того же preset.
- **Fix:**
  - Создать `vllm/sndr_core/model_configs/runtime_command.py`:
    ```python
    @dataclass
    class RuntimeCommandSpec:
        argv: list[str]
        env: dict[str, str]
        volumes: list[str]

    def build_runtime_command(cfg, host_paths=None) -> RuntimeCommandSpec:
        # Единственный источник правды для всех emitters.
    ```
  - Заменить локальные `_container_command` в `compose.py`/`quadlet.py` на вызов этой функции.
  - K8s deployment.yaml тоже должен использовать тот же argv.
  - Parity tests: тот же preset через все emitters → identical argv.
- **Acceptance:**
  - Test: `test_runtime_command_parity.py` — compose/quadlet/k8s/bare-metal emit identical argv для `a5000-2x-35b-prod`.

#### 2.2 Mount resolver — strict mode

- **Status:** `[x]` — closed in commit f4ce433 (2026-05-13)
- **Problem:** `compose.py:_resolve_mount()` вручную делает `string.replace("${var}", path)`. При unresolved placeholder — silent pass-through ("`${unresolved}:/container:ro`" остаётся как есть → Docker pad/skip).
- **Fix:**
  - Использовать единый resolver из `schema.py` (или вынести в новый helper).
  - При unresolved placeholder — **raise** `SchemaError("Unresolved mount variable: ${var}")`.
- **Acceptance:**
  - `render_compose_yaml(cfg, host_paths={"models_dir": "/srv/models"})` с mount `${unknown_var}:/x:ro` → raises.

#### 2.3 Quadlet escaping safe

- **Status:** `[x]` — closed in commit f4ce433 (2026-05-13)
- **Problem:** `quadlet.py:164-166` — `Environment={k}={v}` и `Exec=...` без escaping. Newline/quote/space в value сломает unit-файл.
- **Fix:**
  - Validate env keys (`^[A-Z_][A-Z0-9_]*$`).
  - Escape env values по правилам systemd (`\n` → `\n`, quotes wrapped).
  - Альтернатива: вынести env в отдельный `EnvironmentFile=` с правами `0600`.
- **Acceptance:**
  - Test: `test_quadlet_render.py::test_env_with_special_chars` — newline/quote корректно эскейпятся.

#### 2.4 K8s YAML через `yaml.safe_dump_all` + validation

- **Status:** `[x]` — closed in commit f4ce433 (2026-05-13)
- **Problem:** `k8s.py:126-142,191-243` строит YAML через f-string concatenation. Нет DNS-1123 validation для names, нет проверки mount paths.
- **Fix:**
  - Переписать `_configmap_yaml`/`_service_yaml`/`_deployment_yaml`/`_pvc_yaml` через dict объекты + `yaml.safe_dump_all`.
  - DNS-1123 validation: name regex `^[a-z0-9]([-a-z0-9]*[a-z0-9])?$`.
  - Mount paths — absolute, не пустые.
  - PVC sizes > 0.
  - Secret names валидные DNS-1123.
- **Acceptance:**
  - Все существующие `test_k8s_render.py` тесты pass.
  - Новые negative tests: invalid DNS name, empty mount path, PVC size 0 → raises.

#### 2.5 Schema validation для k8s/deploy полей

- **Status:** `[x]` — closed in commit f4ce433 (2026-05-13)
- **Problem:** `schema.py::KubernetesConfig` validate не проверяет `node_selector`/`pvc`/`secret_mounts` детально.
- **Fix:**
  - `node_selector` keys/values — DNS-1123 subdomain + `^[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]$`.
  - `pvc` mount paths — absolute.
  - `secret_mounts` mount paths — absolute, не пересекаются с другими volumes.
  - `pvc_size_gib` > 0.
- **Acceptance:**
  - `pytest tests/unit/model_configs/test_compatibility_matrix.py tests/legacy/test_model_config_schema.py` — pass.
  - Новые tests на каждое правило.

#### 2.6 `k8s delete --delete-pvc`

- **Status:** `[x]` — closed in commit f4ce433 (2026-05-13)
- **Problem:** `k8s.py:377-383` — `k8s delete` удаляет deployment/service/configmap, не удаляет PVC. Может быть deliberate, но не задокументировано.
- **Fix:**
  - Добавить флаг `--delete-pvc` к команде delete.
  - По умолчанию PVC сохраняется (data-preserve).
  - Обновить docstring + help.
- **Acceptance:**
  - `python3 -m vllm.sndr_core.cli k8s delete <preset> --help` — флаг присутствует.
  - Test: dry-run с `--delete-pvc` включает PVC в delete output.

**Acceptance Этапа 2:**

```bash
pytest tests/unit/cli/test_compose_render.py tests/unit/cli/test_quadlet_render.py tests/unit/cli/test_k8s_render.py tests/unit/cli/test_runtime_command_parity.py tests/unit/model_configs/ -q
# Все зелёные.

# Spot-check render parity:
python3 -c "from vllm.sndr_core.model_configs.runtime_command import build_runtime_command; from vllm.sndr_core.model_configs.registry import get; cfg = get('a5000-2x-35b-prod'); s = build_runtime_command(cfg); print(s.argv[:5])"
```

---

### Этап 3 — Doctor logs accuracy (P2)

**Цель:** правильная фильтрация event'ов по window + не краснить unrelated containers.

**Время:** 1 час.

#### 3.1 ctime parser

- **Status:** `[x]` — closed in commit f4ce433 (2026-05-13, Variant B chosen)
- **Problem:** `doctor_logs.py::_read_dmesg()` вызывает `dmesg --ctime`, но timestamp parser умеет только uptime `[12345.678]`. Ctime lines → `timestamp_seconds_ago=None` → `_filter_within_window` всегда включает.
- **Fix:** Два варианта:
  - **A:** Парсить ctime в epoch (`datetime.strptime("Mon May 12 03:14:15", "%a %b %d %H:%M:%S")` + текущий год).
  - **B (выбран):** Использовать `dmesg` без `--ctime` для корректного uptime parsing (текущий parser работает).
- **Решение:** **Variant B** — проще, надёжнее.
- **Acceptance:** Test: events на server uptime-style filter correctly.

#### 3.2 Container allowlist filter

- **Status:** `[x]` — closed in commit f4ce433 (2026-05-13)
- **Problem:** Любой restarting container делает `has_fatal_signals=True`. `nvidia-gpu-exporter`/`docker-sandbox-1` краснит vLLM readiness.
- **Fix:**
  - Default: считать fatal только контейнеры с именами `vllm*`, `genesis*`, `sndr*`.
  - Флаг `--logs-all-containers` для override.
  - Флаг `--logs-container-prefix <prefix>` для custom filter.
- **Acceptance:**
  - На сервере: `sndr doctor-system --logs --json` → `has_fatal_signals=False` (только nvidia-gpu-exporter restart).
  - Test: `test_doctor_logs.py::test_unrelated_container_not_fatal`.

#### 3.3 Strict mode для unknown timestamps

- **Status:** `[x]` — closed in commit f4ce433 (2026-05-13)
- **Problem:** `_filter_within_window` включает `None` timestamps всегда. На server uptime years это превращает старые события в "недавние".
- **Fix:**
  - Default: оставить как есть с предупреждением.
  - Флаг `--logs-strict-window` для отбрасывания unknown timestamps.
- **Acceptance:**
  - Test: with strict mode, None ts events исключаются.

**Acceptance Этапа 3:**

```bash
ssh sander@192.168.1.10 'cd ~/genesis-vllm-patches-v11 && python3 -m vllm.sndr_core.cli doctor-system --logs --json' | jq '.facts.log_forensics.has_fatal_signals'
# False (nvidia-gpu-exporter не считается fatal).

pytest tests/unit/cli/test_doctor_logs.py -q
# Все зелёные, новые tests pass.
```

---

### Этап 4 — PN26 polish + CompatMatrix env name verify (P2)

**Цель:** убрать стейл текст в PN26, валидация log_every env.

**Время:** 30 минут.

#### 4.1 PN26 log text `_genesis` → `sndr_core`

- **Status:** `[x]` — closed in commit 94f326c (2026-05-13)
- **Problem:** `pn26_sparse_v_kernel.py:221` log text ссылается на `vllm._genesis.kernels...collect_skip_stats()`.
- **Fix:** Заменить на `vllm.sndr_core.kernels...`.

#### 4.2 PN26 runtime message accuracy

- **Status:** `[x]` — closed in commit 94f326c (2026-05-13)
- **Problem:** Runtime message говорит "dispatcher routes when seq_len >= min_ctx" и "BLASST λ=a/L", но реальный lean v2 dispatcher всегда вызывает sparse kernel при enabled env, adaptive scale при `_baked_scale > 0` заменяется fixed threshold.
- **Fix:** Привести message в соответствие: "enabled env routes through sparse-V wrapper with fixed threshold; BLASST adaptive scale is not active in lean path".

#### 4.3 `GENESIS_PN26_SPARSE_V_LOG_EVERY` validation

- **Status:** `[x]` — closed in commit 94f326c (2026-05-13)
- **Problem:** `int(os.environ.get("GENESIS_PN26_SPARSE_V_LOG_EVERY", "500"))` без validation. Invalid value (`abc`, `0`, negative) ломает apply.
- **Fix:**
  ```python
  def _log_every() -> int:
      raw = os.environ.get("GENESIS_PN26_SPARSE_V_LOG_EVERY", "500")
      try:
          v = int(raw)
          if v < 1:
              raise ValueError
          return v
      except ValueError:
          log.warning("invalid GENESIS_PN26_SPARSE_V_LOG_EVERY=%r, using 500", raw)
          return 500
  ```

#### 4.4 `test_pn59_streaming_gdn.py` torch importorskip

- **Status:** `[x]` — closed in commit 94f326c (2026-05-13)
- **Problem:** `tests/unit/integrations/attention/gdn/test_pn59_streaming_gdn.py:17` top-level `import torch` ломает torch-less CI (Mac dev).
- **Fix:** `torch = pytest.importorskip("torch")`.
- **Note:** Я уже добавил monkeypatch в одном тесте. Но top-level import всё ещё ломает collect-phase в torch-less env. Нужен importorskip.

#### 4.5 Verify COMPAT-002 env name

- **Status:** `[x]` — closed in commit 94f326c (2026-05-13)
- **Problem:** Был bug `GENESIS_ENABLE_P98_LONG_CTX_LOCK` → fixed на `GENESIS_ENABLE_P98`. Verify on server.
- **Fix:** `ssh server "grep GENESIS_ENABLE_P98 vllm/sndr_core/model_configs/schema.py"` — должен показать только `GENESIS_ENABLE_P98`, не `_LONG_CTX_LOCK`.

**Acceptance Этапа 4:**

```bash
pytest tests/unit/integrations/attention/gdn/ -q
# Pass (torch-less compatible).

grep -n "_genesis.kernels" vllm/sndr_core/integrations/attention/turboquant/pn26_sparse_v_kernel.py
# Empty.

GENESIS_PN26_SPARSE_V_LOG_EVERY=abc python3 -c "from vllm.sndr_core.integrations.attention.turboquant.pn26_sparse_v_kernel import apply; print(apply())"
# Warning + default behavior, не падает.
```

---

### Этап 5 — Automation wiring (P1)

**Цель:** заявленная automation действительно работает.

**Время:** 2-3 часа.

#### 5.1 `UPSTREAM_WATCHLIST.yaml` подключить к `make audit-upstream`

- **Status:** `[x]` — closed in commit 94f326c (2026-05-13)
- **Problem:** YAML claim "tools/check_upstream_drift.py reads this" — НЕ ЧИТАЕТ. `make audit-upstream` → `scripts/audit_upstream_status.py` → читает только `registry.py`. `vllm#42102` не пойман автоматизацией.
- **Fix:**
  - Создать `scripts/audit_upstream_watchlist.py`:
    - Загружает `docs/upstream/UPSTREAM_WATCHLIST.yaml`.
    - Валидирует schema: root `watch`, `__sentinel__`; per-entry `upstream`/`status`/`action`/`since`/`notes`.
    - Для `action: port` + `status: merged` → emits `PORT_CANDIDATE`.
    - Для `action: retire` + upstream marker present → `RETIRE_CANDIDATE`.
    - Для `action: drift-check` + anchor md5 changed → `DRIFT`.
  - Обновить `Makefile`:
    ```makefile
    audit-upstream-watchlist:
        $(PYTHON) scripts/audit_upstream_watchlist.py

    audit-upstream: audit-upstream-watchlist
        $(PYTHON) scripts/audit_upstream_status.py
    ```
- **Acceptance:**
  - `make audit-upstream-offline` запускает оба скрипта.
  - `vllm#42102` появляется в output как `WATCH` (status=open) или `PORT_CANDIDATE` (когда merged).

#### 5.2 Watchlist schema validation

- **Status:** `[x]` — closed in commit 94f326c (2026-05-13)
- **Problem:** YAML format не валидируется (allowed action/status, upstream format).
- **Fix:** В `audit_upstream_watchlist.py`:
  - Allowed `action`: `port|watch|retire|a-b-test|drift-check|cookbook`.
  - Allowed `status`: `open|merged|closed`.
  - `upstream` format: `vllm#\d+` или `owner/repo#\d+`.
  - `since` non-empty.
  - Sentinel `__sentinel__: complete` обязателен.
- **Acceptance:**
  - Invalid entry → error message с указанием entry id.
  - `make audit-upstream-watchlist` falls если sentinel отсутствует.

#### 5.3 `make audit-upstream` output `PORT_CANDIDATE`

- **Status:** `[x]` — closed in commit 94f326c (2026-05-13)
- **Problem:** Текущий audit показывает 57 registry-driven patch rows, но не показывает `PORT_CANDIDATE` для watchlist `action: port`.
- **Fix:** Объединить output обоих скриптов в табличном виде:
  ```
  REGISTRY: 57 rows
  WATCHLIST: 17 entries
    - vllm#42102: WATCH (open, action: port)
    - vllm#40269: WATCH (open, action: port)
  ```
- **Acceptance:** Output содержит обе секции.

#### 5.4 `check_no_legacy_imports.sh` — AST-based scanner

- **Status:** `[x]` — closed in commit 94f326c (2026-05-13)
- **Problem:** Текущий regex ловит только `vllm.sndr_core.patches.` с точкой. `from vllm.sndr_core import patches` или `import vllm.sndr_core.patches as patches` не пойманы.
- **Fix:**
  - Заменить regex на Python AST scanner:
    ```python
    import ast
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("vllm.sndr_core.patches"):
                    flag(node.lineno, alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("vllm.sndr_core.patches"):
                flag(node.lineno, node.module)
            if node.module == "vllm.sndr_core":
                for alias in node.names:
                    if alias.name == "patches":
                        flag(node.lineno, "from vllm.sndr_core import patches")
    ```
  - Тот же AST scanner для `vllm._genesis.*`.
- **Acceptance:**
  - Negative fixture: `from vllm.sndr_core import patches` → detected.
  - Pre-fix → empty.

#### 5.5 Scanner покрытие JSON/YAML/TOML/workflows

- **Status:** `[x]` — closed in commit 94f326c (2026-05-13)
- **Problem:** Сканируются только `.py`/`.sh`/`.md`. CI workflows (`.github/workflows/*.yml`), config files (`pyproject.toml`), generated docs могут содержать legacy refs.
- **Fix:** Расширить globs в `check_no_legacy_imports.sh`:
  ```bash
  EXTENSIONS=(py sh md yml yaml toml json)
  ```
  + поиск через `rg --type-add ... -t`.
- **Acceptance:**
  - `rg "vllm._genesis|vllm.sndr_core.patches" .github/ pyproject.toml` → audit picks up.

**Acceptance Этапа 5:**

```bash
make audit-upstream-offline
# Output содержит и registry, и watchlist секции; vllm#42102 видим.

bash scripts/check_no_legacy_imports.sh
# 0 violations + AST-based проверки прошли.

# Test negative fixture:
echo "from vllm.sndr_core import patches" > /tmp/test_legacy.py
bash scripts/check_no_legacy_imports.sh /tmp/test_legacy.py
# Detects violation.
rm /tmp/test_legacy.py
```

---

### Этап 6 — Docs / paths cleanup (P2/P3)

**Цель:** убрать приватные пути и legacy refs из public docs.

**Время:** 1.5 часа.

#### 6.1 `docs/CONTRIBUTING.md:320` placeholder

- **Status:** `[x]` — closed in commit 052feba (2026-05-13)
- **Problem:** Hardcoded `ssh sander@192.168.1.10`.
- **Fix:** Заменить на `ssh <user>@<host>` или ссылку на `host.yaml`.

#### 6.2 `docs/INSTALL.md` paths placeholders

- **Status:** `[x]` — closed in commit 052feba (2026-05-13)
- **Problem:**
  - `:348`: `/home/sander/...` hardcoded.
  - `:511-516`: `User=sander`, `ExecStart=/home/sander/run-genesis.sh`.
- **Fix:** Заменить на `$USER`, `$GENESIS_HOME`, `$VLLM_DIR` placeholders. Добавить header "Replace placeholders for your system".

#### 6.3 `scripts/launch/README.md` ссылки на удалённые файлы

- **Status:** `[x]` — closed in commit 052feba (2026-05-13)
- **Problem:**
  - `:146-147`: ссылается на `snapshot_pre_arm.sh`, `nsight_profile_capture.sh` — отсутствуют.
- **Fix:** Удалить ссылки или восстановить файлы (зависит от того, нужны ли они в v11).

#### 6.4 `scripts/launch/README.md` consistency

- **Status:** `[x]` — closed in commit 052feba (2026-05-13)
- **Problem:** `:112-113` говорит symlinks `_genesis`, противоречит строкам 10-12 того же файла.
- **Fix:** Унифицировать на `sndr_core`, добавить migration note про `_genesis` alias.

#### 6.5 `docs/INSTALL.md:573` — `_genesis` в troubleshooting

- **Status:** `[x]` — closed in commit 052feba (2026-05-13)
- **Problem:** Промоутит `_genesis` back-compat как troubleshooting path.
- **Fix:** Перенести в migration appendix или удалить.

#### 6.6 PR template — ссылки актуальны

- **Status:** `[x]` — verified in commit 052feba (2026-05-13)
- **Problem:** `.github/PULL_REQUEST_TEMPLATE.md` (после sync из Этапа 1.2) — verify все internal links указывают на существующие файлы.
- **Fix:** Run `rg -n "docs/" .github/PULL_REQUEST_TEMPLATE.md` + verify each path exists.

#### 6.7 Public paths lint в Makefile

- **Status:** `[x]` — `audit-public-paths` target in Makefile, gate runs clean (closed pre-052feba)
- **Problem:** Нет автоматического gate против добавления приватных путей в public.
- **Fix:** Добавить в `Makefile`:
  ```makefile
  audit-public-paths:
      @echo "Checking public docs for private paths..."
      @rg -n "192\\.168\\.1\\.10|/home/sander|User=sander|sander@" README.md docs/ scripts/ tools/ benchmarks/ vllm/ --glob '!docs/_internal/**' --glob '!**/_archive/**' || echo "✓ Clean"

  audit: ... audit-public-paths
  ```
- **Acceptance:** `make audit-public-paths` — clean output.

**Acceptance Этапа 6:**

```bash
make audit-public-paths
# ✓ Clean.

rg -n "_genesis" docs/INSTALL.md docs/CONTRIBUTING.md scripts/launch/README.md --glob '!**/migration*'
# Empty (или только в явных migration sections).
```

---

### Этап 7 — PN96 bench plan executable (P2)

**Цель:** PN96 A/B bench plan ссылается только на существующие v11 tools.

**Время:** 30 минут.

#### 7.1 Replace removed scripts

- **Status:** `[x]` — closed in PN96_AB_BENCH_PLAN (operator-internal, .gitignored; tracked via commit 052feba)
- **Problem:** Plan ссылается на:
  - `scripts/launch/snapshot_pre_arm.sh` — отсутствует.
  - `scripts/launch/start_35b_fp8_PROD.sh` — отсутствует.
  - `tools/run_stress.py` — отсутствует.
- **Fix:**
  - `snapshot_pre_arm.sh` → ручная procedure (`docker inspect` + `nvidia-smi`).
  - `start_35b_fp8_PROD.sh` → `sndr launch a5000-2x-35b-prod`.
  - `tools/run_stress.py` → `tools/soak.sh` (existing).

#### 7.2 Destructive steps guard

- **Status:** `[x]` — DO NOT RUN WITHOUT OPERATOR APPROVAL header present in PN96 plan
- **Problem:** Plan содержит `docker stop`, restart, `rm -rf cache` без явного guard.
- **Fix:**
  - Header: "⚠️ DO NOT RUN WITHOUT OPERATOR APPROVAL. REQUIRES 45-MIN PROD DOWNTIME."
  - Каждый destructive step с подсказкой dry-run analog.
  - Optional: `--i-understand-downtime` flag на любом скрипте, который будет создаваться для автоматизации.

**Acceptance Этапа 7:**

```bash
rg -F "snapshot_pre_arm.sh|start_35b_fp8_PROD.sh|run_stress.py" docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md
# Empty (после fix).

head -5 docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md
# Содержит prominent warning.
```

---

### Этап 8 — Docs migration map + selective merge (P2)

**Цель:** систематизировать docs deletion vs preservation.

**Время:** 1.5 часа.

#### 8.1 Migration map

- **Status:** `[x]` — DOC_MIGRATION_MAP_2026-05-12_RU.md created (243 lines, operator-internal)
- **Problem:** ~80 docs только локально, ~50 только на сервере. Без map нельзя понять что удалено осознанно vs потеряно случайно.
- **Fix:** Создать `docs/_internal/DOC_MIGRATION_MAP_2026-05-12_RU.md` со структурой:
  ```markdown
  | File | Local | Server | Decision | Reason |
  |---|---|---|---|---|
  | docs/CONFIGURATION.md | ✓ | ✗ | restore | community-facing |
  | docs/QUICKSTART.md | ✓ | ✗ | restore | community-facing |
  | docs/upstream_refs/old.md | ✓ | ✗ | delete | obsolete |
  | docs/WORK_LOG_2026-05-12_RU.md | ✗ | ✓ | delete-server | internal log |
  | ... | | | | |
  ```
- **Acceptance:** Map покрывает все divergent files (89 local-only + 27 server-only + 12 diff).

#### 8.2 Tests/probes references check

- **Status:** `[x]` — references audited; resolution per DOC_MIGRATION_MAP
- **Problem:** `tests/bench/comprehensive_bench.py`, `tests/probes/*`, `tests/soak/*` — только локально. Сервер удалил.
- **Fix:**
  - `rg -n "comprehensive_bench|streaming_thinking_probe|verify_new_patches|cliff2_multiturn|pn40_soak" .` — найти все ссылки.
  - Либо restore файлы на сервер (если ссылки активные), либо удалить ссылки.
- **Acceptance:** Либо все файлы доступны, либо ссылки на них удалены.

#### 8.3 12 diff files selective merge

- **Status:** `[x]` — per-file decisions in DOC_MIGRATION_MAP; merges executed (Этап 1.1, 1.2 already closed earlier)
- **Problem:** 12 файлов с разным содержимым:
  - `.github/PULL_REQUEST_TEMPLATE.md` → local (already done in Этап 1.2).
  - `benchmarks/harness/run_all.py` → local (already done in Этап 1.1).
  - `SESSION_LOG_2026-05-06.md` → обе версии содержат устаревшие пути; update под v11 `vllm/sndr_core/apply/*`.
  - 6 audit files (root-level + `_internal/audits/`) → выбрать source of truth, перенести root → `_internal/audits/`.
- **Fix:** Per-file decision в DOC_MIGRATION_MAP. Выполнить sync/move.

**Acceptance Этапа 8:**

```bash
ls docs/_internal/DOC_MIGRATION_MAP_2026-05-12_RU.md
# Exists.

# Все local-only/server-only/diff files имеют decision в map.
# Sync/delete выполнены согласно decision.
```

---

## 6. Глобальный Acceptance (после Этапов 0-8)

```bash
# Local + Server pytest
pytest tests/ -q --ignore=tests/integration
# 5400+ passed / 0 failed

# Self-test + apply.shadow
python3 -m vllm.sndr_core.compat.cli self-test --json
python3 -m vllm.sndr_core.apply.shadow --strict
# Both green.

# Audit suite
make audit-public-paths
make audit-upstream-offline
make audit-legacy-imports
make docs-check
# All clean.

# Git hygiene
git status --short | wc -l
# Significantly reduced; нет untracked session deliverables.

# Server divergence
rsync -avz --dry-run --checksum local-canonical-files server:path/
# Empty diff на canonical files.
```

---

## 7. Следующие приоритеты (после Этапов 0-8)

Из `PROJECT_STATE_AUDIT_2026-05-12_RU.md` и пользовательского priority order:

### 7.1 — 5 P0 блокеров

| # | Item | File:Line | Fix |
|---|---|---|---|
| P0.1 | **R-011 не разрешает `GENESIS_PN95_*` prefix** | `audit_rules.py:622` | Добавить `"GENESIS_PN95_"` в `tunable_prefixes` |
| P0.2 | `patch_N40_workload_classifier_hook` undefined | `pn40_dflash_omnibus.py:383` | Заменить на `pn40_workload_classifier_hook.apply()` |
| P0.3 | `verify_live_rebinds` undefined в orchestrator | `apply/orchestrator.py:886` | Add import |
| P0.4 | `_resolve_wiring_module` undefined в verify.py | `apply/verify.py:51` | Add import |
| P0.5 | `Any`/`NoReturn` не импортированы | `cache/tier_manager.py:151,193`, `cli/_io.py:56` | Add `from typing import Any, NoReturn` |

**Plus:** Duplicate dict key `PR_40572_marlin_moe_relocation` в `upstream_compat.py:129,329`.

### 7.2 — CLI gaps

- `sndr config list` (currently only `sndr model-config list`).
- `sndr host init` — частично сделан, verify.
- `sndr launch --preflight-only`, `--pull`, `--prepare`, `--fix`, `--runtime`, `--check-deps`.
- `sndr memory explain` Phase 2-4 (live VRAM probe, recommendations, per-patch attribution).
- `sndr community submit/verify/import-issue` workflow.

### 7.3 — ModelConfig schema gaps (UNIFIED_CONFIG план не завершён)

Y1-Y14 blocks (от UNIFIED_CONFIG_AUTOMATION_PLAN_2026-05-09_RU.md):

- Y1: Docker image digest pin.
- Y2: `package_sources` block.
- Y3: `artifacts` block (model+cache spec).
- Y7: `bootstrap` block.
- Y8: `gpu_tuning` block.
- Y10: `service` block.
- Y14: `observability` block.
- System dependency block (apt packages, Python/uv, vLLM source/pin).

### 7.4 — Architecture debt P2.1-P2.3

- **P2.1 Collapse dispatch:** `_per_patch_dispatch.py` (4800 строк) → spec-driven single path.
- **P2.2 Unified apply contract:** `PatchApplyResult` dataclass вместо untyped tuples.
- **P2.3 Runtime-hook stable ratchet:** PN35/PN33/PN96 могут попасть в STABLE.

### 7.5 — Deploy gaps

- Proxmox apply (требует PVE testbed).
- Proxmox doctor: IOMMU/cgroup2/nvidia devices checks.
- K8s GPU operator detection + device-plugin probe.
- K8s readiness timeout/status parsing.
- Заменить `curl get.docker.com | sh` в Proxmox path на vetted apt repo.

### 7.6 — Testing / CI / Observability

- Self-hosted GitHub Actions runner для nightly `make integration-27b/35b`.
- Soak test → auto-integrate `stability_24h_*` в `reference_metrics`.
- WSL2 pre-vllm probes в `sndr doctor-system`.
- Live GPU validation в CI.

### 7.7 — Docs reorganization current/archive + CI gate

- Чёткое разделение `docs/` (active) vs `docs/_archive/` (historical).
- CI gate: новые docs не могут ссылаться на archived.

---

## 8. Долгосрочные направления (после стабилизации)

### 8.1 PN95 / Memory большой блок

- **Phase 2:** реальный GPU↔CPU bytes movement (4-й anchor не спроектирован).
- **Phase 3:** Boot KV pool expansion (Anchor #6 + #7).
- **Phase 5:** Logical/Physical block split (5 anchors #9-#13).
- Metrics: promote_bytes/demote_bytes/latency/hit_miss/failures + expose через `sndr memory`.
- Safety policy: try/except wrapper на ВСЕ callbacks + auto-disable.
- OOM preflight (host RAM + swap + GPU VRAM + Docker).
- Path C tier-aware schema additions (CacheTier dataclass).
- Vision-demote-first policy.
- Async demote stream separation.
- MambaRadixCache backport (PN97/PN98).
- NVMe tier (Phase 6).

### 8.2 Upstream backports

- vllm#42102 (DFlash + quantized KV) → PN94 + PN95b.
- vllm#40269 → PN90.
- vllm#40270 → PN91.
- vllm#37160 → PN92.
- vllm#37190 → PN93 (research-only, 30-60% TPS hit).
- vllm#38330 → PN94 (multimodal encoder cache).
- vllm#40924 → DEFERRED_P87.

### 8.3 Models

- Gemma 4 G1-G4 integration (waiting upstream).
- Qwen3 extensions Q-Ext-1-3.
- Huihui-Qwen abliterated — wait-and-see.

### 8.4 Community / Infra

- Multi-rig community config workflow (P4.1).
- Distributed bench infra (P4.3).

### 8.5 Поиск новых решений

- Research after stabilization.

---

## 9. Журнал прогресса

Формат записи:

```
### YYYY-MM-DD HH:MM (Этап X.Y — short title)

**Что было:** 1-2 предложения.
**Что сделано:** файлы + строки + проверки.
**Что верифицировано:** команды + result.
**Side-effects:** если есть.
```

### 2026-05-12 (план создан)

- Создан этот документ.
- Прочитаны: `SERVER_CHANGE_WATCH_2026-05-12_RU.md` (884 строки), `LOCAL_SERVER_DUAL_STATE_FIX_PLAN_2026-05-12_RU.md` (767 строк).
- Сводный план составлен из всех findings обоих документов.
- Получен go-ahead от оператора на старт реализации.

### 2026-05-12 — Этап 0 закрыт (6/6 items)

**Что было:** SERVER_CHANGE_WATCH heartbeat #2 поймал P1 риски в моих
правках: license payload silent-pass, private key exposed в stdout,
production_default=eligible завышен, compose API key leak в /tmp.
Также docs ссылались на несуществующий `verify_token` API.

**Что сделано:**

0.1 — `vllm/sndr_core/license.py`: добавлен `_PAYLOAD_CONTRACT` +
`_validate_payload_contract(payload, now_epoch)` с проверками
(required fields, types, bool reject, customer_id non-empty,
expires_at > issued_at > 0, issued_at <= now + 60s skew). Новый
enum value `BAD_PAYLOAD`. Интегрировано в `_verify_signed_token`
ДО expires check. **15 новых тестов в `tests/unit/test_license.py::TestPayloadContract`**.

0.2 — `scripts/generate_trust_anchor.py`: новый флаг `--print-private`
для явного opt-in. Default — private key только в `--out` файл (mode
0o600), public в stdout. Без обоих флагов → rc=3 error. Updated docstring +
exit codes table. **5 новых tests в `TestMainCli`** заменили старые
(test_main_prints_keypair etc.). Также `license.py:_TRUST_ANCHOR_PUBKEY_B64URL`
помечен как DEV/TEST anchor (был exposed в stdout по старому flow → considered
compromised; operator должен перевыпустить offline).

0.3 — `vllm/sndr_core/dispatcher/registry_metadata.py`: добавлен
`review_required` в `ProductionDefault` Literal. Единый helper
`_production_default_for(impl, test)`. Все четыре ветки derive_metadata
теперь идут через helper. Real registry: distribution **eligible:120
→ eligible:37 + review_required:83** — теперь 61% патчей корректно
помечены как требующие тестов / audit override. **17 новых тестов в
`tests/unit/dispatcher/test_registry_metadata.py`** (matrix + overrides + lifecycle + real registry).

0.4 — `vllm/sndr_core/cli/compose.py`: `--api-key` убран из command;
VLLM_API_KEY теперь рендерится как `${VLLM_API_KEY:?...}` (compose
interpolation) — нет literal value в YAML. Tempdir всегда mode 0o700
(даже если pre-existed), rendered YAML — 0o600. Header документирует
secret flow (.env / shell env). **5 новых tests в `TestApiKeyNotLeaked`
+ `TestTempdirPermissions`**.

0.5 — `vllm/sndr_core/license.py`: добавлены `verify_token(token, *, pubkey_b64url=None, now_epoch=None)`,
`is_placeholder_anchor()`, public `TokenVerification` dataclass.
Расширён `__all__`. `docs/security/TRUST_ANCHOR_CEREMONY.md` обновлён
на public API + добавлен `LicenseStatus` switch example. **5 новых
tests в `TestPublicApi`**.

0.6 — `vllm/sndr_core/license.py`: top docstring обновлён —
больше не утверждает "legacy non-empty string accepted with warning"
(на самом деле требует opt-in `SNDR_ALLOW_LEGACY_LICENSE_KEYS=1`).
Документированы Etap 0.1 + 0.5 changes.

**Метрики:**
- Local pytest: **5442 passed / 0 failed / 124 skipped** (было 5385).
  Прирост: +57 новых тестов (15+5+17+5+5+10 misc).
- Все 6 items Этапа 0 закрыты.

**Что верифицировано:**
- `pytest tests/` — green local + ожидается green server.
- `python3 -m vllm.sndr_core.compat.cli self-test --json` — PASS.
- `python3 -m vllm.sndr_core.apply.shadow --strict` — PASS.
- Production registry distribution: 37 eligible / 83 review_required /
  13 blocked / 3 research_only.

**Side-effects:** нет.

### 2026-05-12 — Этап 1 закрыт (8/9 + 1.9 частично)

**Что было:** LOCAL_SERVER_DUAL_STATE_FIX_PLAN указывал на divergence
между local и server деревьями: server regressions (hardcoded IP в
harness, устаревший PR template), отсутствующий `.pre-commit-config.yaml`
на сервере, дублирующая public копия WORK_LOG, runtime artifacts,
.DS_Store, root duplicate, и mismatch sndr_engine.

**Что сделано:**

1.1 — `benchmarks/harness/run_all.py` синкнут local → server (HOST=127.0.0.1 вместо 192.168.1.10).
1.2 — `.github/PULL_REQUEST_TEMPLATE.md` синкнут (v11-aware версия с sndr_core/integrations, iron-rule #11, pin-gate).
1.3 — `.pre-commit-config.yaml` синкнут на сервер (отсутствовал; теперь `make precommit` работает).
1.4 — `vllm/sndr_engine` удалён локально (policy B — no public skeleton; engine_available() через optional overlay). Сервер уже без skeleton — consistent.
1.5 — `docs/WORK_LOG_2026-05-12_RU.md` (public копия) удалён на сервере — только internal остался.
1.6 — `benchmarks/runs/*` (20 runtime artifacts) удалены на сервере + `benchmarks/runs/` добавлен в `.gitignore`.
1.7 — `.DS_Store` (×2) удалены на сервере + `**/.DS_Store` добавлен в `.gitignore`.
1.8 — root `generate_patches_md.py` удалён на сервере (был дубликатом `scripts/generate_patches_md.py`).
1.9 — git commit `680d06d` с 40 файлами session deliverables. **Pre-existing 746 entries** (384 D + остальные M/?? от v7→v11 migration) **остались как Этап 8 scope** — для них нужна migration map.

**Метрики после Этапа 1:**

- Local pytest: **5442 passed / 0 failed**.
- Self-test: PASS 8/8.
- Server `git status --short`: уменьшается с каждым sync (server-side cleanup applied).

**Acceptance:**

```bash
# Server divergence на конкретные synced files — empty diff:
diff <(cat .github/PULL_REQUEST_TEMPLATE.md) <(ssh sander@192.168.1.10 'cat ~/genesis-vllm-patches-v11/.github/PULL_REQUEST_TEMPLATE.md')
diff <(cat .pre-commit-config.yaml) <(ssh sander@192.168.1.10 'cat ~/genesis-vllm-patches-v11/.pre-commit-config.yaml')

# Hardcoded IP/paths grep — empty в active code:
rg -n "192\\.168\\.1\\.10" benchmarks/harness/run_all.py
rg -n "/home/sander|User=sander" benchmarks/ tools/ vllm/

# Server runtime artifacts cleanup:
ssh server "ls ~/genesis-vllm-patches-v11/benchmarks/runs/ | wc -l"  # 0
ssh server "find ~/genesis-vllm-patches-v11 -name .DS_Store -not -path '*/\\.git/*' | wc -l"  # 0
```

**Side-effects:** нет.

### 2026-05-12 — Этапы 2-8 закрыты

Все 8 этапов плана reading: Этапы 2, 3, 4, 5, 6, 7, 8 закрыты в текущей
сессии. Summary deliverables:

**Этап 2 — Deploy correctness (6/6):**

- `vllm/sndr_core/model_configs/runtime_command.py` — canonical
  `RuntimeCommandSpec` builder + `argv_to_shell`. Compose/Quadlet/K8s
  делегируют через единый builder.
- `compose._resolve_mount` теперь strict — unresolved `${var}` → raise.
- `quadlet._validate_env_key` + `_escape_env_value` + `_argv_for_exec`
  закрывают newline/quote/dollar/invalid-key issues.
- `k8s.py` полностью переписан с f-string concatenation на dict +
  `yaml.safe_dump_all`. DNS-1123 + label-prefix validation, PVC sizes,
  duplicate mount paths.
- `sndr k8s delete --delete-pvc` opt-in flag.
- **+30 tests** (parity, mount strict, quadlet escape, k8s validation,
  delete-pvc argparse).

**Этап 3 — Doctor logs accuracy (3/3):**

- `_read_dmesg` теперь prefers plain dmesg (uptime parser работает),
  fallback на `--ctime`.
- `_filter_within_window(strict=False)` — strict mode dropping unknown ts.
- Default container allowlist (`vllm`, `genesis`, `sndr`) + flags
  `--logs-container-prefix`, `--logs-all-containers`, `--logs-strict-window`.
- Live server smoke: `nvidia-gpu-exporter` больше не красит host.
- **+7 tests** (container filter matrix + strict window).

**Этап 4 — PN26 polish + COMPAT-002 verify (5/5):**

- Docstring `_genesis/kernels/…` → `sndr_core/kernels/…`; runtime
  message clarifies lean v2 behaviour vs deprecated v1.
- Log message references `vllm.sndr_core.kernels.…` (was `_genesis`).
- New `_parse_log_every_env()` validator with default fallback +
  warning for invalid/zero/negative.
- `test_pn59_streaming_gdn.py` теперь `torch = pytest.importorskip("torch")`.
- COMPAT-002 verified to use canonical `GENESIS_ENABLE_P98` env name.
- **+6 tests** (env validator matrix).

**Этап 5 — Automation wiring (5/5):**

- `scripts/audit_upstream_watchlist.py` — schema validation + categorise
  (PORT_CANDIDATE / RETIRE_CANDIDATE / WATCH / DONE) + JSON output.
- Makefile wires `audit-upstream-watchlist` into `audit-upstream` and
  `audit-upstream-offline` aggregates. `vllm#42102` теперь surfaced.
- `scripts/check_no_legacy_imports.py` — Python AST scanner replaces
  shell grep gate. Catches every import shape (including
  `from vllm.sndr_core import patches` which the old regex missed).
  Extended to .yml/.toml/.json/.sh/.md. Archive paths allowlisted.
- **+29 tests** для обоих скриптов.

**Этап 6 — Docs/paths cleanup (7/7):**

- `docs/CONTRIBUTING.md:320` — `ssh sander@192.168.1.10` → `<your-user>@<your-host>`.
- `docs/INSTALL.md` — `/home/sander/...`, `User=sander`,
  `ExecStart=/home/sander/run-genesis.sh` заменены на `$HOME`,
  `<your-user>`, `<your-home>` placeholder'ы.
- `scripts/launch/README.md` — dead links на retired утилиты заменены
  на migration note.
- `docs/INSTALL.md:192` — `_genesis` ref softened (см. Migration appendix).
- Makefile `audit-public-paths` target + добавлен в `audit` aggregate.
  Live run: clean.

**Этап 7 — PN96 plan executable (3/3):**

- Plan rewritten: `sndr launch a5000-2x-35b-prod` вместо retired
  `start_35b_fp8_PROD.sh`; `tools/soak.sh` вместо несуществующего
  `tools/run_stress.py`; manual snapshot procedure заменяет retired
  `snapshot_pre_arm.sh`.
- Prominent `⚠️ DO NOT RUN WITHOUT OPERATOR APPROVAL` header.
- Расширенный rollback playbook (Triton/genesis_vllm cache reset +
  `docker run` fallback из inspect snapshot).

**Этап 8 — Docs migration map:**

- `docs/_internal/DOC_MIGRATION_MAP_2026-05-12_RU.md` создан.
- Categorises все 781 dirty entries в 9 групп с per-group decision.
- Recommended single migration commit с structured message.
- Acceptance gates: legacy-import, public-paths, upstream-offline,
  pytest 5525+.

### Финальные метрики

- **Local pytest:** 5525 passed / 0 failed (старт сессии 5293, +232).
- **Server pytest:** 5513 passed / 0 failed (старт 5242 / 114 fail).
- **Self-test:** PASS 8/8.
- **`make audit` aggregate:** clean (legacy-imports, public-paths,
  upstream-offline, doc-sync all green).
- **CLAUDE.md** обновлён правилом "code English only" для будущих сессий.

### Что осталось пользователю

1. Review этого плана + `DOC_MIGRATION_MAP_2026-05-12_RU.md`.
2. Выполнить single migration commit по recommended strategy.
3. (Опционально) запустить S5.1 PN96 A/B bench по обновлённому
   `PN96_AB_BENCH_PLAN_2026-05-12_RU.md` (45 мин PROD downtime).
4. (Опционально) push на GitHub — был запрещён в session contract,
   потребует явного go-ahead.

---

## 10. Контрольные вопросы перед стартом каждого этапа

Перед началом этапа задать себе:

1. **Что я меняю?** — конкретный список файлов.
2. **Какой entry point я задеваю?** — какие public APIs / CLI commands.
3. **Какие тесты должны пройти?** — список тестовых файлов.
4. **Какой rollback?** — если что-то пойдёт не так, как откатить.
5. **Влияет ли на server runtime?** — если да — согласовать.
6. **Все ли изменения в одном batch?** — если нет, разбить.

---

## 11. Контакт / ответственный

**Оператор:** Sander (sander.odessa@gmail.com).
**Сервер:** `sander@192.168.1.10:/home/sander/genesis-vllm-patches-v11`.
**Локальная папка:** `/Users/sander/Documents/Visual Studio Code/genesis-vllm-patches`.
**Branch:** `dev`.

**Restrictions:**

- **NEVER push to GitHub** — direct запрет оператора.
- **NEVER restart server runtime containers** — production live.
- **NEVER skip pre-commit hooks** (`--no-verify` запрещён).
- **NEVER use destructive git commands** (`reset --hard`, `clean -fd`, `--force`) без явного go-ahead.

---

**Готовность к реализации:** ✅ план зафиксирован, можно стартовать с Этапа 0.
