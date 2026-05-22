# Work Log — Comprehensive Dual-State Audit Fixes (2026-05-12+)

Журнал автономной работы. После каждого исправления — апдейт этого файла,
чтобы не повторяться и не забывать.

Источник: `docs/_internal/COMPREHENSIVE_DUAL_STATE_AUDIT_2026-05-12_RU.md`
Связанный план: `docs/_internal/REMAINING_WORK_PLAN_2026-05-12_RU.md`

Server: `sander@192.168.1.10:~/genesis-vllm-patches-v11`
27B PROD: `vllm-pn95-2xa5000` (port 8101, dev209)

---

## Sprint 1 — Local/Server convergence + critical (P0)

### ✅ S1.1 — PN26 torch-less apply contract

**Что было.** `apply()` вызывал `from vllm.sndr_core.kernels.triton_turboquant_decode_sparse_v import (should_apply, is_pn26_sparse_v_enabled)` ДО проверки env. Kernel модуль импортирует torch на top-level — падал в torch-less окружении (CI, Mac dev) даже когда env disabled.

**Что сделано.** Файл `vllm/sndr_core/integrations/attention/turboquant/pn26_sparse_v_kernel.py`:

1. Добавил локальную функцию `_pn26_env_enabled()` — читает `GENESIS_ENABLE_PN26_SPARSE_V` через `os.environ`, без импорта kernel.
2. В `apply()` env-check сделан ДО любых импортов.
3. Kernel import обёрнут в try/except ImportError → graceful skip с понятной reason.

**Верификация.** Pytest `test_patch_apply_contracts.py::test_apply_returns_tuple_when_env_disabled[PN26]` теперь зелёный. Manual torch-less smoke: `apply()` корректно возвращает `("skipped", ...)` без torch.

**Тесты после:** 5291 passed / 0 failed.

---


### ✅ S1.2 — Server v11 stale `vllm.sndr_core.patches` imports

**Что было.** Аудит насчитал 108, реальный grep на сервере показал 118 матчей в `tests/` и `vllm/sndr_core/`. Локально оставался 1 (schema description — false positive). Full pytest на сервере падал на 114 тестах из-за `ModuleNotFoundError: vllm.sndr_core.patches`.

**Что сделано.**
1. Rsync `tests/` (все 4 директории + конфтест) на сервер. После: 1 ref остался (тот же schema description).
2. Сервер pytest показал 13 оставшихся failures по 3 новым категориям:
   - 6 × `test_lockfiles.py` — отсутствовали `requirements-dev.lock` / `requirements-runtime.lock` → rsync.
   - 3 × `test_pn{17,19,35}_in_patches_md` — `docs/PATCHES.md` устарел → rsync.
   - 2 × `test_stable_manifest_policy::TestStableRatchetDocumented` — `docs/upstream/STABLE_PROMOTION_CHECKLIST.md` отсутствовал → rsync.
3. Остались 2 real test bugs (server-only, не виден локально):
   - **R-019 host.yaml**: тест полагался на `GENESIS_HOME` env, но `load_host_config()` использует фиксированный путь. На сервере у меня есть реальный `~/.sndr/host.yaml` (создан в `sndr host init` smoke), поэтому R-019 не срабатывал. **Fix:** в `tests/legacy/test_model_config_audit_rules.py::test_host_yaml_absent_with_symbolic_mounts_fires` добавил monkeypatch на `load_host_config()` + `detect_paths()` — тест стал hermetic.
   - **test_mem_snapshot_returns_zero_without_cuda**: тест assumed env без CUDA (Mac), на сервере CUDA есть. **Fix:** monkeypatch `torch.cuda.is_available` → False.

**Верификация.** Server full pytest: **5319 passed / 0 failed** (было 114 failed / 5242 passed).

### ✅ S1.3 — Hardcoded HOST в публичных smoke-инструментах

**Что было.** `tools/long_ctx_smoke.sh`, `tools/soak.sh` и 6 таргетов в Makefile содержали `HOST=${HOST:-http://192.168.1.10:8101}` — приватный LAN IP оператора как default. Community-пользователь, скачавший репо, стучался бы в чужой rig.

**Что сделано.** Везде заменил default на `http://127.0.0.1:8101` (27B) или `http://127.0.0.1:8000` (35B), с явной возможностью override через `HOST=` env. Добавил комментарии-объяснения почему default безопасный.

Файлы: `tools/long_ctx_smoke.sh`, `tools/soak.sh`, `Makefile` (integration-27b/35b, long-ctx-27b/35b, soak-1h-27b/-8h-27b, audit-yaml).

### ✅ S1.4 — Content=null runtime contract (P0-3)

**Что было.** Live smoke на 27B PROD (`max_tokens=32`) возвращал `message.content=null` и весь budget в `message.reasoning` — OpenAI-совместимые клиенты видели пустой ответ. PN16 V1 (template mutation) был retired в Wave 6 (CUDA-graph dispatch регрессия). V7 (CLASSIFIER_MAX_TOKENS) был disabled в live start-script.

**Что сделано.**
1. Создал `tools/openai_smoke.py` — OpenAI-совместимый smoke с флагом `--assert-content` (P0-3 контракт). Поддерживает `--enable-thinking true|false` для проверки PN16 V3 (client override) path.
2. Добавил `make smoke-content` таргет.
3. Создал `docs/REASONING_CONTENT_CONTRACT.md` — объясняет архитектурное решение PN16 v2 (4 варианта V3/V5/V7/V8 без мутации chat-template) + контракт для клиентов: явно передавать `chat_template_kwargs.enable_thinking=false`.

**Верификация.** На live 27B PROD:
- С `--enable-thinking false` → content=2 chars ("OK"), rc=0.
- Без флага → content_chars=0, reasoning_chars=108, smoke fail (rc=2 — корректно ловит P0-3).

### ✅ S1.5 — Server cleanup (`__pycache__` + root bench artifacts)

**Что сделано.**
- Переместил 20 root-level `genesis_bench_quick_*.json/md` в `~/genesis-vllm-patches-v11/benchmarks/runs/`.
- Удалил `__pycache__` (88→0 директорий; 4 не-удалились из-за docker-root permissions — не критично, dust).

### ✅ S1.6 — Legacy-import CI gate

**Что сделано.** Создал `scripts/check_no_legacy_imports.sh` — POSIX-совместимый bash скрипт:
- Сканирует `tests/`, `vllm/sndr_core/`, `scripts/`, `tools/`.
- Запрещает `vllm.sndr_core.patches.*` (pre-v10 namespace).
- Запрещает active `import/from vllm._genesis.<X>` (pre-v11 namespace, оставляет ОК для docstring references).
- Allowlist для known-good файлов (schema descriptions, version.py back-compat doc, etc.).

Добавил в Makefile: `make audit-legacy-imports` + включил в `audit` aggregate. Result: **0 violations**.

### ✅ S2.1 — Trust anchor Ed25519 ceremony

**Что было.** `vllm/sndr_core/license.py::_TRUST_ANCHOR_PUBKEY_B64URL = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"` (32-нулевой placeholder). Подписанные токены отвергались как BAD_SIGNATURE.

**Что сделано.**
1. Сгенерировал реальный Ed25519 keypair на сервере через `scripts/generate_trust_anchor.py`.
2. Public key (`iSk29MUb9HldKokPRyOG7bAjwYaQdgqYsS17yfskE8s`) вшит в `license.py` с провенанс-комментарием.
3. Private key показан в stdout сессии — оператор (Sander) должен сохранить offline (paper / USB / YubiKey). Файлы с private key НЕ закоммичены.
4. Создал `docs/security/TRUST_ANCHOR_CEREMONY.md` — операционный playbook для rotation.
5. Создал `tests/unit/test_trust_anchor_not_placeholder.py` — CI gate, чтобы placeholder не вернулся в будущем (2 теста: not_placeholder + valid pubkey shape).
6. Обновил `tests/unit/test_trust_anchor_generator.py::TestPlaceholderDetection` — все 3 теста теперь monkeypatch'ат константу в placeholder для проверки behavior функции (тесты раньше assume'или live placeholder state, теперь активирован реальный ключ).

**Верификация.** `_is_placeholder_anchor() → False`. License tests: 24 passed / 0 failed.

### ✅ S2.2 — Registry implementation_status overlay

**Что было.** Из 136 entries только 4 имели `implementation_status=full`, 1 = `partial`, 1 = `placeholder`, 1 = `retired`. Остальные 129 — пусто, inferred при boot в `live`. Аудит P1-2: нельзя построить production matrix без явного статуса.

**Что сделано.**
1. Создал `vllm/sndr_core/dispatcher/registry_metadata.py` — overlay-модуль:
   - `derive_metadata(patch_id, registry_meta) → {implementation_status, test_status, production_default}`.
   - `EXPLICIT_OVERRIDES` для точечных коррекций (PN95, PN64, PN26b, P5b).
   - Lifecycle-based defaults (stable → full+eligible, retired → retired+blocked, etc.).
   - File-based `test_status` detection (`tests/unit/integrations/<family>/test_<id>_*.py`).
2. Обновил `spec.py::infer_implementation_status` — делегирует в overlay когда patch_id известен.
3. Расширил `VALID_IMPLEMENTATION_STATUSES`: добавил `scaffold`, `coordinator`.
4. Обновил `test_spec_metadata_enrichment.py::test_default_to_live` — учёл новую семантику (`stable → full`, не `live`).

**Результат.**
```
implementation_status: live=113, retired=11, full=6, research=2, partial=1, scaffold=1, coordinator=1, placeholder=1
test_status: unit=45, none=91
production_default: eligible=120, blocked=13, research_only=3
```

16 патчей корректно помечены как не-production: 11 retired + PN95 (partial) + PN64 (placeholder) + P82/P83 (research) + PN26b (scaffold).

### ✅ S2.3 — Docs v7/v11 cleanup (stale `_genesis` instructions)

**Что было.** Аудит P1-5: `docs/INSTALL.md` (lines 178-192, 260, 539-543, 573), `docs/CONTRIBUTING.md:394`, `docs/BENCHMARK_GUIDE.md:406`, `scripts/launch/README.md:10` всё ещё содержали активные операторские инструкции с pre-v11 namespace `_genesis`. Опасно: пользователь скачавший community-репо мог следовать устаревшим bind-mount / symlink / logger config рекомендациям.

**Что сделано.**

1. `docs/INSTALL.md` (4 правки):
   - L186: "bind-mount `_genesis/` package" → "bind-mount `sndr_core/` package".
   - L192: "`_genesis/` is the only thing under version control" → "`sndr_core/` … (pre-v11 scripts may still reference `_genesis/` — back-compat alias)".
   - L260: "Source-level edits to `_genesis/`" → "Source-level edits to `sndr_core/`".
   - L539-543: rsync пример `_genesis/` → `sndr_core/`.
   - L370-374 уже корректные (legacy note про back-compat alias), оставил.

2. `docs/CONTRIBUTING.md:394`: `logging.getLogger("vllm._genesis")` → `logging.getLogger("vllm.sndr_core")` с back-compat пояснением.

3. `docs/BENCHMARK_GUIDE.md:406`: symlink инструкция теперь говорит `sndr_core`, добавлен back-compat абзац про `_genesis` alias.

4. `scripts/launch/README.md:10-12`: bare-metal flavor описание теперь говорит `sndr_core` + back-compat note.

**Что НЕ трогалось (intentionally).**
- `docs/_internal/` — audit reports / план / work log сами по себе исторические артефакты; они **обсуждают** legacy и должны оставаться как есть.
- `docs/CREDITS.md:131` — credit для Alberto-Codes/turboquant-vllm как inspiration для нашего `_genesis/` layout (исторический факт).
- `docs/PLUGINS.md` — entry-point group `vllm_genesis_patches` это **актуальное** имя в `pyproject.toml`, не legacy (используется текущим plugin loader).
- `_archive/` под scripts/launch — explicit historical.

**Верификация.** `grep -RIn "_genesis" docs/INSTALL.md docs/CONTRIBUTING.md docs/BENCHMARK_GUIDE.md scripts/launch/README.md | grep -v archive` показывает только intentional back-compat references с пояснением про alias. Pytest local: pre-cleanup 5293 passed, должно остаться без изменений (docs не задействованы в test logic).

### ✅ S2.4 — Operational hygiene: `sndr doctor-system --logs`

**Что было.** Аудит P2-1: operator не имел быстрого способа проверить host-side stability signals — нужно было вручную копаться в `dmesg | grep -i oom`, `dmesg | grep -i xid`, `docker ps --filter status=restarting`, `journalctl -u genesis-vllm`. Каждый раз заново и легко пропустить какой-то источник.

**Что сделано.**

1. Создал `vllm/sndr_core/cli/doctor_logs.py` (~280 строк):
   - `collect_log_forensics(window_hours=24, ...)` — top-level композитор с injected collectors (testable).
   - dmesg парсинг → OOM-kill events (regex `Out of memory: Killed process N (NAME)`).
   - dmesg парсинг → NVRM Xid events (regex `NVRM: Xid (PCI:X): N`) с severity классификацией:
     - **fatal** (`FATAL_XIDS = {31, 43, 45, 63, 64, 74, 79}`) — MMU page fault, channel reset, ECC retirement, NVLink, GPU off-bus.
     - **warning** (13, 14, 62, 119) — graphics engine, display, GSP RPC.
     - **info** (всё остальное).
   - `docker ps --filter status=restarting` → list restart loops.
   - `journalctl -u genesis-vllm.service --since "{N} hours ago"` → grep `error|fatal|panic|oom|cuda|nvrm|xid|killed|exit`, last 20 lines.
   - Uptime-aware window filter (`/proc/uptime` для конверсии `[12345.678]` → seconds-ago).
   - Graceful degradation: каждый источник optional, отсутствие → `sources_unavailable` запись без падения.

2. Расширил `doctor_system.py`:
   - Новые флаги `--logs` и `--logs-hours N` (default 24).
   - JSON output ключ `facts.log_forensics` (full structured data).
   - Text output блок "Log forensics (last Nh):" с ✓/✗/⚠ маркерами.
   - OOM events / fatal Xid / restarting containers эскалируют verdict в "NOT READY".

3. Создал `tests/unit/cli/test_doctor_logs.py` — **25 unit tests** покрывают:
   - OOM regex (classic, multiple events, clean log, case-insensitive).
   - Xid regex + severity classification + FATAL_XIDS coverage + malformed line handling.
   - Window filter (unknown timestamps включаются, старые отбрасываются).
   - `LogForensicsResult.has_fatal_signals` логика (OOM, fatal Xid, restart loop триггерят; warning Xid — нет).
   - Top-level composition с инъецированными fake-collectors.
   - Text summarization (clean → три "✓", fatal → "✗", sources_unavailable рендерится).

**Верификация.**
- Local pytest: **25/25 passed**. Full sweep: **5332 passed / 0 failed**.
- Server pytest: **5360 passed / 0 failed**.
- Live `sndr doctor-system --json --logs --logs-hours 168` на сервере корректно нашёл 2 restarting containers (nvidia-gpu-exporter, docker-sandbox-1 — не Genesis, но реальные restart loops), dmesg недоступен без sudo (ожидаемо), journalctl пустой (genesis-vllm не systemd-unit на этом хосте).
- Failed/fixed: первый прогон на сервере упал на `test_oom_and_xid_detected` потому что `[10.0]` uptime префикс на server uptime years конвертился в "очень-давно" и события улетали из 24h окна. Fix: fake dmesg в тесте использует `Mon May 12 03:14:15 host kernel: ...` формат (без uptime) — парсинг с uptime покрыт отдельными unit-тестами.

### ✅ S2.5 — CompatibilityMatrix в model_configs.schema

**Что было.** Аудит P2-2: известные несовместимости разбросаны по
`ModelConfig.validate()` и `audit()` (`OffloadConfig.cpu_offload_gib >
0` + hybrid GDN, `CacheConfig.exclude_mamba_ssm=False` + hybrid GDN,
TQ k8v4 + hybrid + no P98). Operator не имел единого "источника правды"
с табличкой "что нельзя комбинировать и почему". Кроме того,
несколько *новых* комбинаций (DFlash + hybrid GDN, ngram + TQ +
long-ctx) ещё нигде не проверялись.

**Что сделано.**

1. Расширил `vllm/sndr_core/model_configs/schema.py`:
   - Новый `@dataclass CompatibilityRule { id, severity, title, message, mitigation, references }` (~50 строк).
   - Новый класс `CompatibilityMatrix` с `register(rule, predicate)`, `rules()`, `evaluate(cfg) → (forbidden[], discouraged[])`.
   - Singleton `COMPATIBILITY_MATRIX` экспортируется из модуля.
   - Predicate exceptions глотаются с warning в log (правило с багом не должен ронять validate()).

2. Зарегистрировал 4 правила:
   - **COMPAT-001** (forbidden): `spec_decode.method=dflash` + hybrid GDN — DFlash drafter не понимает SSM state, crash в drafter forward.
   - **COMPAT-002** (discouraged): `kv_cache_dtype=turboquant_k8v4` + hybrid GDN без `GENESIS_ENABLE_P98_LONG_CTX_LOCK=1` — non-deterministic prefill (vllm#40941 race).
   - **COMPAT-003** (discouraged): `spec_decode.method=ngram` + TQ k8v4 + `max_model_len > 131072` — acceptance rate падает 0.62 → 0.41 (cache thrashing).
   - **COMPAT-004** (forbidden): `method=dflash` без `spec_decode.model` — declarative duplicate of `SpecDecodeConfig.validate` для CLI visibility.

3. Интеграция:
   - `ModelConfig.validate()`: forbidden → `SchemaError` с inline-объяснением и mitigation hint.
   - `ModelConfig.audit()`: discouraged → `[COMPAT-XXX] title: message` в warning list.

4. Создал `tests/unit/model_configs/test_compatibility_matrix.py` — **21 unit tests**:
   - `CompatibilityRule.validate()` (good + 5 bad shapes).
   - Matrix bookkeeping: duplicate id → SchemaError, predicate exception swallowed, canonical matrix содержит все 4 правила.
   - Per-rule regression: positive (правило срабатывает) + 2 negative (не срабатывает на edge cases) для каждого COMPAT-001/002/003.
   - End-to-end: `validate()` raises при forbidden, `audit()` surfaces discouraged, clean config не содержит COMPAT-* warnings.

**Верификация.**
- Local pytest: **5353 passed / 0 failed** (5332 → 5353 = +21 новых тестов).
- Server pytest: **5381 passed / 0 failed** (синк прошёл, full sweep зелёный).
- Все 214 существующих тестов в `tests/unit/model_configs/` + `tests/legacy/test_model_config_audit_rules.py` остались green — backward-compatible изменение.

**Post-S2.5 correction.** Первый прогон на сервере поймал regression: COMPAT-001 (DFlash + hybrid GDN) был слишком жёстким и блокировал существующий PROD-stable preset `a5000-2x-27b-dflash-true` (Qwen3.6-27B Lorbus hybrid Mamba + DFlash отдельный drafter checkpoint работает). Refine: COMPAT-001 теперь срабатывает только когда `model_path` содержит `qwen-next`/`qwen3-next` substring (точное соответствие audit указанию `dflash: blocked_for_qwen_next`). Все 11 builtin presets снова загружаются.

### ✅ S3.1 — Docker Compose renderer

**Что было.** Audit P3-1: Genesis эмитил ТОЛЬКО bash launch-script. Community feedback: operator'ы интегрируют Genesis в существующий docker-compose stack и хотят готовый `docker-compose.yml`. Раньше им приходилось вручную переводить bash в compose.

**Что сделано.**

1. Создал `vllm/sndr_core/cli/compose.py` (~310 строк):
   - `render_compose_yaml(cfg, host_paths)` — pure-function рендерер.
   - `run_compose_render/up/down/logs` — argparse handlers.
   - `_container_command(cfg)` — реконструирует полную `vllm serve …` команду из ModelConfig.
   - `_resolve_mount(spec, paths)` — host.yaml substitution для `${var}` в mounts.
   - Идемпотентность: повторный render с тем же input даёт тот же байтоидентичный output.
   - GPU reservation через Docker Compose Spec `deploy.resources.reservations.devices` (nvidia driver, gpu count).
   - yaml.safe_dump (не f-strings) — корректные escapes для special chars в env values.

2. Зарегистрировал в `cli/__init__.py` как `sndr compose <render|up|down|logs>`.

3. Создал `tests/unit/cli/test_compose_render.py` — **11 unit tests**:
   - Header содержит preset key + maintainer.
   - yaml.safe_load → dict (proves it's parseable).
   - image/container_name/ports правильные.
   - environment combines system_env + genesis_env.
   - volumes substitution через host_paths применяется.
   - command[0:2] == ["vllm", "serve"], `--tensor-parallel-size` берётся из hardware.n_gpus.
   - GPU reservation block правильный.
   - external network block.
   - no-docker raises ValueError.
   - Идемпотентность.

**Верификация.** Local pytest: 11/11. Live render для `a5000-2x-35b-prod` дал валидный compose YAML со всеми patches.

### ✅ S3.2 — Podman Quadlet renderer

**Что было.** Audit P3-2: production-grade systemd-managed containers (без root daemon) рекомендуется через Podman Quadlet (.container файлы в `~/.config/containers/systemd/`). Genesis не имел этого пути.

**Что сделано.**

1. Создал `vllm/sndr_core/cli/quadlet.py` (~160 строк):
   - `render_quadlet(cfg, host_paths)` — pure-function рендерер.
   - Эмитит INI-формат с секциями `[Unit]` / `[Container]` / `[Service]` / `[Install]`.
   - Environment lines — одна на строку (Quadlet принимает повторяющиеся записи).
   - Volume lines с host_paths substitution.
   - `AddDevice=nvidia.com/gpu=all` для GPU access.
   - `Exec=` — однострочная команда с shlex-quoted args.
   - Reuse `_container_command` / `_load_host_paths` / `_resolve_mount` из compose.py.

2. Зарегистрировал в `cli/__init__.py` как `sndr quadlet render`.

3. Создал `tests/unit/cli/test_quadlet_render.py` — **11 unit tests**:
   - Все секции присутствуют.
   - Image / ContainerName / PublishPort правильные.
   - Environment line per env var.
   - Volume substitution.
   - Exec= одна строка с `vllm serve`.
   - GPU device line.
   - Idempotence.
   - Restart=on-failure, WantedBy=default.target.

**Верификация.** Local: 11/11. Server full sweep: 5413 / 0.

### ✅ S3.3 — Kubernetes renderer extensions (nodeSelector + PVC + Secret)

**Что было.** Audit P3-3: existing `KubernetesConfig` уже имел namespace + image + hostPath storage + runtimeClassName. Не хватало:
- `nodeSelector` (для multi-node clusters с GPU class labels)
- PVC (persistent volumes — для read-write models cache / hf-cache)
- Secret mounts (для bearer tokens / HF tokens, чтобы не светить в ConfigMap)
- Плюс bug в emit'е empty volumeMounts/volumes (misaligned `[]` → YAML parse error).

**Что сделано.**

1. Расширил `KubernetesConfig` в schema:
   - `node_selector: dict[str, str]` — labels для pod scheduler.
   - `pvc: dict[str, str]` — `claim_name → mount_path`.
   - `pvc_size_gib: dict[str, int]` — size per claim (default 100 GiB).
   - `pvc_storage_class: str` — storageClassName (пусто → default class).
   - `secret_mounts: dict[str, str]` — `secret_name → mount_path`.

2. Расширил `vllm/sndr_core/cli/k8s.py`:
   - Новая функция `_pvc_yaml(cfg)` — генерирует один `PersistentVolumeClaim` manifest per claim.
   - `_deployment_yaml` теперь композирует volumes из трёх источников (hostPath / PVC / Secret) в один список.
   - nodeSelector block в pod template spec (omit если пусто).
   - **Bug fix:** empty volumeMounts/volumes раньше эмитились с misaligned `        []` → YAML parser failed. Теперь inline `volumeMounts: []` / `volumes: []`.

3. Создал `tests/unit/cli/test_k8s_render.py` — **9 unit tests**:
   - baseline YAML parses (yaml.safe_load_all → kinds in [ConfigMap, Service, Deployment]).
   - hostPath storage regression (existing path still works).
   - nodeSelector renders + omitted when empty.
   - PVC creates PersistentVolumeClaim + mounts в Deployment + default size 100Gi + custom size.
   - Secret mount renders с secretName.
   - No PVC when empty.

**Верификация.** Local: 9/9. Server: 5413 passed (включая 9 новых k8s render тестов).

### S3.4 — Proxmox apply: DEFERRED (документировано)

**Что есть.** `vllm/sndr_core/cli/proxmox.py` уже содержит `sndr proxmox doctor` (PVE host sanity), `inventory` (pct list / qm list), `render` (генерация pct/qm команд для preset'а), `status` (pct status / qm status).

**Чего нет (deferred).** Команда `proxmox apply`, которая автоматически выполняла бы render output (`pct create`/`qm create`). Решение отложить до live PVE testbed: непротестированная PVE automation чревата destructive поведением (не тот container_id, GPU passthrough ошибки). Текущий путь — operator копирует output `proxmox render` и выполняет вручную после review. Это явная разумная safety boundary.

**Action.** Зарегистрировать в roadmap deferred-tasks. Когда появится testbed — добавить `apply` с `--yes` gate и full integration test.

### ✅ S4.1 — vllm#42102 watchlist + backport plan

**Что было.** Аудит P4-1: upstream PR vllm-project/vllm#42102 (DFlash + quantized target KV coexistence) напрямую релевантен Genesis stack'у (PN21..PN40 DFlash + TQ k8v4), но не было entry в `UPSTREAM_WATCHLIST.yaml` и не было плана backport.

**Что сделано.**

1. Добавил entry в `docs/upstream/UPSTREAM_WATCHLIST.yaml`:
   - `upstream: vllm#42102`, `status: open`, `action: port`, `since: 2026-05-12`.
   - `local_patches: [PN21, PN23, PN24, PN38, PN40]` — affected Genesis patches.
   - Notes описывают три upstream механизма: KV partition before page-size unify, drafter `cache_dtype="auto"`, per-spec dtype в FA metadata.

2. Создал `docs/_internal/research/upstream_42102_dflash_independent_kv_groups_plan_2026-05-12.md` — backport plan:
   - Per-mechanism mapping (1→PN94 new, 2→PN95b new, 3→handled by PN94).
   - Retire candidates после merge (PN38, PN40).
   - Test plan (unit + integration + 200-min A/B soak с Welch t-test).
   - Trigger condition (upstream status open → merged через `make audit-upstream`).
   - ETA ожидания (~2-4 weeks от 2026-05-12, target ~2026-06-01 .. 2026-06-15).

3. Cross-references: COMPAT-001 refinement (S2.5) теперь не блокирует Qwen3.6 Lorbus + DFlash dev work.

**Верификация.** `python3 -c "yaml.safe_load(...)"` подтвердил sentinel остался `complete`, 17 entries (было 16). Pytest не задействован (data-only change).

### ✅ S5.1 — PN96 A/B bench plan (gated execution)

**Что было.** PN96 (Persistent Marlin MoE workspace) включён в 35B PROD как часть Wave 9 dev209 pin bump, но без live A/B бенча мы не знаем реального contribution.

**Что сделано.** Создал `docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md`:

- 5-phase execution sequence (baseline → disable → measure → restore → analyze).
- ~45 минут PROD downtime budget.
- Verdict criteria: PN96 keeps ON если delta>1.5% Welch p<0.05; retire candidate если delta < 1% p > 0.10.
- Rollback procedure при любой phase failure.

**Status.** Plan ready, **execution gated на operator availability** (45 min PROD downtime требует explicit Sander go-ahead). Не запускалось автономно.

### ✅ S5.2 — Final sync + CHANGELOG

**Что было.** Все sprint deliverables нужно зафиксировать в CHANGELOG.md для commit-ready state, и sync на сервер должен быть подтверждён green.

**Что сделано.**

1. Создал entry `[v11.0.0+audit_2026_05_12_dual_state_closure]` в `CHANGELOG.md` — summary всех 18 sprint sub-tasks (P0-P5) с конкретными метриками (test counts per phase, deferred items, retire candidates).

2. Final rsync на сервер: CHANGELOG.md + UPSTREAM_WATCHLIST.yaml + WORK_LOG + 2 plan-docs.

3. Final pytest both sides:
   - Local: **5385 passed / 0 failed** (старт 5293 → +92 за всю сессию).
   - Server: **5413 passed / 0 failed** (старт 5242 / 114 failed → +171 / -114).

4. Все P0 findings closed. Все P1 closed. P2/P3 закрыты except Proxmox apply (S3.4, deferred, документировано). P5.1 (PN96 bench) gated on operator availability — план готов.

**Verdict.** Project в commit-ready state. Sander возвращается → нужно review WORK_LOG_2026-05-12_RU.md, CHANGELOG entry, optionally запустить S5.1 PN96 bench перед коммитом.
