# План оставшейся работы — Genesis vLLM Patches

Дата составления: 2026-05-12
Контекст: после полного закрытия P1+P2+P3 из аудита `PROJECT_STATE_AUDIT_2026-05-12_RU.md`

## Краткое резюме состояния

**Уже сделано:**

- Все 7 пунктов P1 (TypedStorage warning, gitignore, `sndr config list`, runtime tunable registry, production profile gate, README counters, docs cleanup)
- Все 3 пункта P2 (integration endpoint pipeline с per-metric budgets, long-ctx smoke scripts, soak tests)
- Все 5 пунктов P3 (bootstrap scopes, host profile manager, community config workflow, Proxmox safer install, K8s doctor)
- 29 новых TDD-тестов (runtime_tunables × 20 + CLI extensions × 9)
- Wave 9 dev209 re-bench на 27B PROD (нейтральный пин-бамп) и 35B PROD (-2.82% TPS — upstream-side регрессия)
- PN96 (Persistent Marlin MoE workspace) реализован но ещё не A/B-протестирован на 35B
- Локально: 5291 тестов pass / 0 failed
- Сервер: self-test 8/8, integration 5/5, host detect видит 2× A5000

**Не сделано / стратегические задачи:** см. ниже по приоритетам.

---

## Приоритет 1 (P1) — Критичное, делать сейчас

Влияние на работоспособность PROD или на следующий релиз.

### P1.1. Live A/B bench PN96 на 35B PROD

**Зачем.** PN96 (Persistent Marlin MoE workspace) реализован как runtime-hook patch, который кеширует workspace тензор Marlin GEMM на инстансе `MarlinExperts` вместо аллокации на каждый вызов через `marlin_make_workspace_new(device, 4)`. Цель — частично восстановить -2.82% TPS / +2.86% TPOT регрессию на 35B A3B-FP8 после пин-бампа dev93→dev209.

**Что делает.** При `apply()` патч:

1. Сохраняет оригинальные `MarlinExperts.apply` и `fused_marlin_moe`.
2. Подменяет `MarlinExperts.apply` обёрткой, которая лениво создаёт `self._genesis_pn96_ws = marlin_make_workspace_new(hidden_states.device, 4)` на первом вызове и кладёт его в thread-local `_TLS.default_workspace`.
3. Подменяет `fused_marlin_moe` обёрткой, которая инжектит `workspace=_TLS.default_workspace` если caller передал `workspace=None`.

**Что меняет.** Поведение MoE-ветки на 35B FP8 — `_fused_marlin_moe` теперь принимает persistent workspace вместо аллокации каждый раз. На 27B (hybrid GDN+Mamba INT4) патч — no-op, потому что 27B не использует MarlinExperts.

**Что даёт.** Ожидаемое улучшение TPS на 35B — от 0.1% до 2% (зависит от того, насколько часто `marlin_make_workspace_new` в горячем пути).

**Как реализовать (план бенча).**

1. Stop 27B PROD: `docker stop vllm-pn95-2xa5000`.
2. Start 35B PROD baseline с `GENESIS_DISABLE_PN96=1`: модифицированный `~/start_35b_prod_wave8.sh` или одноразовый docker run. Дождаться API-готовности (~3-5 min).
3. Bench: `tools/genesis_bench_suite.py --quick --ctx 8k --model qwen3.6-35b-a3b --port 8000 --name baseline_pn96_off`.
4. Stop 35B, start 35B с PN96=1 (по умолчанию), bench: `--name candidate_pn96_on`.
5. Сравнить через `bench_compare.render_table baseline.json candidate.json`.
6. Stop 35B, restart 27B PROD.

**Технологии.** docker, curl, jq, Genesis bench suite.

**Совместимость.** PN96 composes с P17/P18 (per-SM tuning), P22/P38 (TQ workspace) — разные оптимизационные векторы, не конфликтуют. PN96 безопасен с auto-skip при отсутствии `experts/marlin_moe.py` (dev93-era pin).

**Риски.**

- Если PN96 не работает корректно — boot 35B failed или WORSE perf. Откат: `docker stop vllm-35b-prod && export GENESIS_DISABLE_PN96=1 && ~/start_35b_prod_wave8.sh`.
- 27B PROD downtime ~45 минут.

**Стоимость:** 45 минут PROD downtime.
**Ценность:** конкретная цифра recovery — даёт основание либо принять PN96 как Wave 10 default-on, либо удалить (если delta ≤ 0.3%).

### P1.2. Wave 10 решение по PN96 + промоут до stable

**Зачем.** Если PN96 показывает recovery ≥ 1% TPS на 35B и стабильность ≤ 7%, патч готов к промоут до `lifecycle=stable` по тому же ratchet'у, что PN33+PN35.

**Что делает.** Промоут патча через STABLE-pipeline:

1. Создать pristine fixture для `experts/marlin_moe.py` под `tests/legacy/pristine_fixtures/` (dev209).
2. Хотя PN96 — runtime hook без TextPatcher, у него уже есть `apply_module`. Расширить `build_anchor_manifest.py::_REGISTRY_TARGETS` ИЛИ дать PN96 свой `register_for_manifest()` (для runtime-hook режима — пустая регистрация, чтобы пройти ratchet).
3. Поднять `lifecycle = "stable"` + `stable_since` в registry.

**Что даёт.** Первый production-blessed perf-recovery patch для post-dev209 эры.

**Альтернатива.** Если delta < 1% — оставить PN96 на `experimental` или удалить совсем.

**Зависимости.** P1.1 (нужны цифры).

### P1.3. Sprint 1 35B regression bisect (если PN96 не закрывает)

**Зачем.** Понять, какой именно upstream-коммит между dev93 и dev209 (116 dev-коммитов) сломал A3B-FP8 perf. Если PN96 не recovery ≥ 2.5% — нужно копать upstream.

**Что делает.** Бинарный поиск по vllm коммитам:

1. Из `docker run --entrypoint git -C /usr/local/lib/python3.12/dist-packages/vllm log dev93..dev209` извлечь list коммитов в MoE/FP8/Marlin путях.
2. Pull docker image с промежуточным пином (если есть в Docker Hub) либо собрать локально из конкретного SHA.
3. Run bench с каждой версии, бисектировать.

**Что даёт.** Конкретный upstream PR — основание для:

- (a) backport-fix через Genesis text-patch если causal change ясен,
- (b) submit PR в vllm-project с perf-restore predmpute,
- (c) принять регрессию как architectural cost.

**Стоимость.** Высокая — потенциально дни bisect-работы + сборка кастомных docker images.

**Альтернатива (дешевле).** Подождать upstream perf-PR — после major refactor обычно следует серия optimization-PR'ов. Track через `audit_upstream_status.py` weekly cron.

---

## Приоритет 2 (P2) — Важные стратегические улучшения

Архитектурные изменения, которые принесут долгосрочный выигрыш в качестве/поддерживаемости.

### P2.1. Strategic Theme 1: collapse dispatch — единый источник правды для патчей

**Зачем.** Сейчас в проекте сосуществуют два механизма регистрации патчей:

- Legacy `_per_patch_dispatch.py` — функции `apply_patch_<id>_<name>` для каждого патча, регистрируются через `register_patch(...)`.
- Modern `iter_patch_specs()` — spec-driven, берёт `PatchSpec` из `dispatcher/spec.py` и идёт через `apply_module` поле.

Это создаёт риск drift — тест `test_apply_all_dispatcher_sync.py` отлавливает расхождения, но это reactive, а не preventive. К тому же 132 функции в `_per_patch_dispatch.py` — большой mostly-boilerplate файл.

**Что делает.** Удалить `_per_patch_dispatch.py` целиком, оставив только spec-driven путь. Каждый патч сам по себе — wiring модуль в `integrations/<family>/<id>_*.py` с функциями `apply()`, `is_applied()`, `revert()`. Registry содержит `apply_module` указатель.

**Что меняет.** Файл `_per_patch_dispatch.py` (~4800 строк) удаляется. `apply/orchestrator.py` упрощается — single path через `iter_patch_specs()`. Legacy `register_patch` декоратор остаётся только для transition периода.

**Что даёт.**

- Уменьшение complexity (минус 4800 строк boilerplate).
- Невозможно создать divergence — нет двух источников.
- Каждый патч — autonomous module с понятным интерфейсом.

**Как реализовать (этапы).**

1. **Этап A** — verify: для каждого `apply_patch_<id>` функции в legacy найти соответствующий wiring-модуль с `apply()`. Тест уже есть (`test_apply_all_dispatcher_sync.py`).
2. **Этап B** — migrate edge cases: некоторые patches (P5, P5b, P32+P33 bundled) в legacy используют shared state — вынести в общие helpers.
3. **Этап C** — remove `_per_patch_dispatch.py` и `register_patch` декоратор.
4. **Этап D** — упростить `orchestrator.py` под single path.

**Технологии.** Pure Python refactor.

**Совместимость.** Compose с любой текущей патч-системой. Зависимости: только TextPatcher/runtime-hook patterns остаются.

**Стоимость.** 1-2 недели работы. Большой риск регрессий — каждый патч надо проверять.

### P2.2. Strategic Theme 2: unified apply — единый контракт apply()

**Зачем.** Сейчас функция `apply()` патча возвращает `tuple[str, str]` (status, reason), где status ∈ {"applied", "skipped", "failed"}. Это работает, но:

- Нет типизации (статус — обычная строка, опечатка тихая).
- Нет structured payload (например, для observability нужно знать `elapsed_ms`, `rss_delta_kb` — собирается отдельно в `observability.py`).
- Контракт между TextPatcher (text-patch путь) и runtime-hook (monkey-patch путь) разный — TextPatcher возвращает `TextPatchResult`, runtime-hook возвращает строку.

**Что делает.** Ввести dataclass `PatchApplyResult`:

```python
@dataclass
class PatchApplyResult:
    status: Literal["applied", "skipped", "failed", "idempotent"]
    reason: str
    elapsed_ms: float = 0.0
    rss_delta_kb: int = 0
    revert_callable: Optional[Callable[[], bool]] = None
```

Все `apply()` функции возвращают эту структуру. Orchestrator читает её для observability, не вызывая отдельный pipeline.

**Что меняет.** Сигнатура каждой `apply()` функции — backward-compatibly через адаптер для transition периода. observability.py становится тоньше.

**Что даёт.**

- Type safety — статус не может быть случайной строкой.
- Observability — встроена в результат, не нужно cross-reference.
- Простая revert-семантика для каждого патча.

**Как реализовать.** Schema-driven миграция: создать `PatchApplyResult` в `vllm/sndr_core/apply/result.py`, добавить адаптер для tuple-возвратов, постепенно мигрировать патчи (один файл — один PR).

**Технологии.** Python 3.10+ dataclasses + Literal types.

**Совместимость.** Полностью совместимо с P2.1 (Theme 1). Можно делать параллельно.

**Стоимость.** Средняя — много файлов, но механически.

### P2.3. Strategic Theme 3: lifecycle ratchet для runtime-hook patches

**Зачем.** Сейчас STABLE ratchet ([test_stable_manifest_policy.py](tests/unit/infra/test_stable_manifest_policy.py)) требует:

1. `apply_module` (есть у всех патчей).
2. `register_text_patcher()` зарегистрирован (text-patch only).
3. `anchor_manifest.json` coverage (text-patch only).

Это блокирует runtime-hook патчи (PN35, PN96 и будущие) от продвижения в STABLE, даже если они production-validated. Архитектурная дыра.

**Что делает.** Ввести опциональное поле в registry: `stable_kind: "text-patch" | "runtime-hook"`. Расширить ratchet:

- Для `stable_kind="text-patch"` — текущие проверки (TextPatcher + manifest).
- Для `stable_kind="runtime-hook"` — обязательны:
  - `apply_module` (как сейчас);
  - `production_validated_pins: list[tuple[genesis_pin, vllm_pin]]` — минимум 2 разных пина с PROD-валидацией;
  - `apply()` функция в module возвращает `("applied", ...)` при normal call.

**Что меняет.** Schema `patch_entry.schema.json` + `runtime_tunables.py` + новая dataclass поле + ratchet test обновляется.

**Что даёт.** Runtime-hook патчи (включая PN96) получают законный путь к STABLE. Архитектурное обещание STABLE-ratchet'а сохраняется (validated infrastructure), но расширяется на оба класса патчей.

**Как реализовать.**

1. Добавить `stable_kind` поле в schema (default — `text-patch` для backward compat).
2. Расширить `test_stable_manifest_policy.py`:
   - Если `stable_kind=="text-patch"` — старая логика.
   - Если `stable_kind=="runtime-hook"` — проверять `production_validated_pins` (минимум 2 entries) и `apply()` не raise.
3. Промоут PN35 (уже stable как text-patch — OK), PN33 (text-patch — OK), PN96 как первый `runtime-hook` STABLE.

**Технологии.** JSON Schema + pytest fixtures + Python dataclasses.

**Совместимость.** Полная — расширение существующего ratchet'а, не breaking.

**Стоимость.** 1-2 дня.

### P2.4. Phase 7: SGLang MambaRadixCache интеграция

**Зачем.** Hybrid GDN+Mamba модели (27B Lorbus + grand) сейчас используют стандартный vLLM KV cache для GDN-блоков, который non-optimal для Mamba state. SGLang проект имеет `MambaRadixCache` — radix-tree-based cache для Mamba states. Backport может дать существенное улучшение memory + perf на hybrid моделях.

**Что делает.** Backport SGLang MambaRadixCache архитектуры в vllm:

- Новый patch (PN97 или PN98) — реализация radix-tree storage для Mamba SSM state.
- Интеграция с `gdn_linear_attn.py` — добавить опциональную RadixCache как backend для SSM state allocation.
- Env flag `GENESIS_ENABLE_MAMBA_RADIX_CACHE` (default OFF до validation).

**Что меняет.** Расширение кеша на Mamba-side. ~500 строк нового кода в integrations/attention/gdn/.

**Что даёт.**

- Ожидаемое улучшение в long-context хранении (256K+ context на 27B).
- Возможное снижение peak VRAM на hybrid моделях.
- Открывает путь для multi-rig sharing того же Mamba state.

**Как реализовать (этапы).**

1. **Этап A** — изучить SGLang [реализацию](https://github.com/sgl-project/sglang/blob/main/python/sglang/srt/mem_cache/radix_cache.py).
2. **Этап B** — определить attachment point в `gdn_linear_attn.py` (вероятно `forward_cuda` → SSM state init).
3. **Этап C** — пилотная реализация на 1 модели (Qwen3.6-27B).
4. **Этап D** — bench + validation; promote если ≥ 5% memory win.

**Технологии.** Triton, torch, radix tree structure.

**Совместимость.** Composes с PN54 (GDN contiguous dedup), PN59 (streaming-GDN). НЕ compose с PN79 (in-place SSM state) — оба меняют одну и ту же allocation модель; нужен явный `conflicts_with`.

**Стоимость.** 2-4 недели.

---

## Приоритет 3 (P3) — Качественные улучшения

Не блокирующее, но повышает поддерживаемость и operational quality.

### P3.1. Live GPU validation в CI (remote runner)

**Зачем.** Сейчас `make integration-27b/35b` работает только когда у разработчика есть SSH к PROD-серверу. Нет автоматической ночной валидации, что текущий main-branch не сломал PROD.

**Что делает.** GitHub Actions workflow, который через self-hosted runner на homelab-сервере:

- Запускает `make integration-27b` каждую ночь.
- Сравнивает с baseline.
- Открывает issue если регрессия.

**Что меняет.** Новый файл `.github/workflows/nightly_integration.yml`. Self-hosted runner setup на сервере (одноразовая операция).

**Что даёт.** Detection регрессий в течение 24h вместо weeks.

**Технологии.** GitHub Actions, self-hosted runner, Genesis bench suite.

**Совместимость.** Стоит ОТДЕЛЬНО от `make ci` (CI без GPU). 

**Стоимость.** 1 день setup + один self-hosted runner registration.

### P3.2. K8s structured YAML emitter + Secret/PVC/runtimeClass rendering

**Зачем.** Сейчас `sndr k8s render` собирает manifests через string concatenation. Хрупко: легко пропустить escape, легко выйти из YAML spec.

**Что делает.** Переписать через `yaml.safe_dump(manifests_dict)`:

- Deployment с `runtimeClassName`, `nodeSelector`, `resources.requests/limits`, `tolerations`.
- Service.
- ConfigMap для не-секретных env vars.
- **Secret** для API key (отдельный объект, не ConfigMap).
- **PersistentVolumeClaim** для model weights + caches (cluster-managed storage, не hostPath).

**Что меняет.** `vllm/sndr_core/cli/k8s.py` — internal rendering replaced. CLI surface remains the same.

**Что даёт.** Production-grade K8s output, готовый для real clusters.

**Технологии.** PyYAML, k8s API conventions.

**Совместимость.** Composes с `sndr k8s doctor` — doctor проверяет, что cluster поддерживает то, что renderer генерирует.

**Стоимость.** 3-5 дней.

### P3.3. Trust anchor key ceremony — Ed25519 keypair

**Зачем.** Сейчас [vllm/sndr_core/license.py](vllm/sndr_core/license.py) содержит placeholder pubkey (`_TRUST_ANCHOR_PUBKEY_B64URL = "AAAA..."`). Любая signed-token проверка отклоняется. Для public release это OK (engine tier пустой), но для будущего commercial engine — критично.

**Что делает.** Offline key ceremony:

1. На airgapped машине сгенерировать Ed25519 keypair (`cryptography` lib).
2. Public key — встроить в `license.py` как `_TRUST_ANCHOR_PUBKEY_B64URL`.
3. Private key — хранить в hardware security module / secure offline storage.
4. Снести legacy unsigned-key support code path (за исключением `SNDR_ALLOW_LEGACY_LICENSE_KEYS=1` для transition периода).
5. Документировать revocation/rotation процедуру в `docs/security/`.

**Что меняет.** `license.py` (pubkey + remove legacy code path) + новые docs.

**Что даёт.** Real signed-token infrastructure для будущих private engine wheels.

**Технологии.** `cryptography` (Ed25519), GnuPG для signing ceremony.

**Совместимость.** Backward-compatible — старые tokens продолжают работать через legacy mode пока `SNDR_ALLOW_LEGACY_LICENSE_KEYS=1`.

**Стоимость.** 1 день + offline ceremony.

### P3.4. WSL2 / pre-vllm probe pipeline

**Зачем.** В `tools/external_probe/` есть pre-vllm probes (CUDA version, driver compat). Сейчас они не интегрированы в `sndr install`. Операторам приходится разбираться вручную, почему vllm не стартует на их WSL2 / consumer setup.

**Что делает.** Расширить `sndr doctor-system`:

- Probe WSL2 detection.
- Driver mode (passthrough vs translation).
- CUDA capability vs vllm requirements.
- Memory budget (free RAM vs model size).
- Эмитить actionable hints типа "driver 570 detected, but vllm dev209 requires ≥ 580 — `apt install nvidia-driver-580-server`".

**Что меняет.** `vllm/sndr_core/cli/doctor_system.py` + новые helpers.

**Что даёт.** Меньше "почему не запускается" issues на community.

**Технологии.** Python stdlib + `nvidia-smi` + `/proc/version` parsing.

**Совместимость.** Standalone; bridges с `sndr host doctor`.

**Стоимость.** 3-5 дней.

### P3.5. Pytest plugin для Genesis-specific fixtures

**Зачем.** Сейчас тесты раскиданно используют:

- `tests/conftest.py::deterministic_seed` fixture.
- Manual mocking torch / vllm guards.
- Pristine-fixture loading через прямой `pathlib.Path` чтение.

Это работает, но плохо обнаруживается контрибьюторами.

**Что делает.** Pytest plugin `vllm.sndr_core.test_plugin`:

- Auto-registered fixtures: `genesis_registry`, `genesis_host_inventory`, `pristine_vllm_source`.
- Marker classes: `@pytest.mark.requires_torch`, `@pytest.mark.requires_gpu`.
- Helper для mock-PatchRegistry overlay.

**Что меняет.** Новый module `vllm/sndr_core/test_plugin/` + entry point в `pyproject.toml`.

**Что даёт.** Контрибьюторы пишут тесты быстрее, с меньшим boilerplate.

**Технологии.** pytest plugin API, entry_points.

**Совместимость.** Не ломает существующие тесты.

**Стоимость.** 2-3 дня.

### P3.6. Documentation reorganization (current vs archive)

**Зачем.** В `docs/` сейчас смешаны actual-current документы и historical references на старые версии. Аудит рекомендовал разделить.

**Что делает.**

- Создать `docs/archive/` для пре-v11 материалов.
- Переместить туда `docs/_internal/INTEGRATED_PLAN_2026-05-09.md`, старые roadmaps.
- В каждом current документе явный header: "Current as of v11.0.0+wave9".
- CI grep gate (тест), что в `docs/` (не `docs/archive/` или `docs/_internal/`) нет mentions `_genesis` (кроме explicitly historical sections).

**Что меняет.** Структуру `docs/`. Контент сохраняется, но reorganized.

**Что даёт.** Новый оператор видит только релевантное; historical контекст доступен для тех, кто разбирает evolution.

**Технологии.** git mv + sed for header updates.

**Совместимость.** Не ломает links — старые URL станут `docs/archive/<file>.md`. Обновить главные refs в README.

**Стоимость.** 1-2 дня.

---

## Приоритет 4 (P4) — Долгосрочные улучшения (месяцы)

### P4.1. Multi-rig community config workflow

**Зачем.** Сейчас community configs (`community-test` / `community-dev` / `community-prod` lifecycles) — концепция, но workflow не автоматизирован.

**Что делает.** Поднять до production-grade:

- `sndr community submit <config.yaml>` — отправляет конфиг на review (открывает PR).
- `sndr community verify <key>` — запускает локальный bench, добавляет результат в config.
- Cross-rig validation — система отслеживает, на скольких разных GPU/driver/pin комбинациях конфиг был verified.

**Стоимость.** 2-4 недели.

### P4.2. Soak test integration в reference_metrics

**Зачем.** Сейчас `tools/soak.sh` пишет логи в /tmp; нет автоматической интеграции в `verify`.

**Что делает.** После 1h soak — авто-добавление `stability_24h_*` полей в reference_metrics. `sndr verify` сможет проверять не только peak perf, но и long-term stability.

**Стоимость.** 1 неделя.

### P4.3. Распределённая bench infrastructure

**Зачем.** Cross-rig validation вручную — медленно. Нужна инфра, где community-контрибьюторы могут отправить config-PR и автоматически получить bench-результаты с разных hardware.

**Что делает.** Distributed worker pool — community-owners регистрируют свой rig как worker, GitHub Actions распределяет bench-задачи.

**Стоимость.** 1-2 месяца.

### P4.4. Comments → русский (для новых модулей)

**Зачем.** По запросу пользователя — для новых модулей и тех, что часто меняются.

**Что делает.** Для НОВЫХ файлов (создаваемых далее) — комментарии на русском. Существующий codebase оставить английским (массовая переводка — wasted churn).

**Когда применять.**

- Новый patch (например PN97+) — комментарии русские.
- Новый CLI command (например `sndr something-new`) — русские.
- Существующий файл при существенном refactor — мигрируем comment блоки на русский.

**Принципы (по запросу пользователя).**

- Точно объяснять значение, назначение и что делает.
- Без упоминаний AI / Claude / Anthropic.
- Компактно но подробно и по делу.
- Использовать актуальное название проекта (Genesis vLLM Patches / sndr_core), не legacy `_genesis`.

**Пример приемлемого комментария.**

```python
# Кеш Marlin workspace на инстансе MarlinExperts. Eliminates
# per-call allocation в горячем пути A3B-FP8 MoE. Lazy init на
# первом вызове (нужен device из hidden_states).
```

**Пример НЕприемлемого.**

```python
# AI-generated comment that walks through every line and adds
# noise. Removed in audit pass.
```

---

## Зависимости и порядок выполнения

```text
P1.1 (PN96 bench) ─┬─→ P1.2 (Wave 10 PN96 promote)
                   └─→ P1.3 (35B bisect — only if P1.1 doesn't recover)

P2.1 (Theme 1 dispatch) ─→ P2.2 (Theme 2 unified apply)
P2.3 (ratchet runtime) ─→ P1.2 (нужно для PN96 → stable)
P2.4 (MambaRadixCache) — independent

P3.* — все independent, можно делать в любом порядке.
P4.* — после P1+P2+P3.
```

**Рекомендованный порядок:**

1. P1.1 → P1.2 (1 день — даёт конкретное perf-число)
2. P2.3 ratchet runtime (1-2 дня — открывает дорогу для STABLE runtime-hook)
3. P3.1 live GPU CI (1 день — autodefence regressions)
4. P2.1 Theme 1 dispatch (1-2 недели — большой quality win)
5. P3.2 K8s structured emitter (3-5 дней — operational improvement)
6. P2.2 Theme 2 unified apply (2-3 недели)
7. P2.4 MambaRadixCache (2-4 недели — high-impact perf win)
8. Остальные P3 + P4 по приоритету команды.

---

## Текущее состояние проекта (баланс к 2026-05-12)

**Готовность к release:**

| Категория | Состояние | Балл |
|---|---|---:|
| Архитектура (sndr_core/sndr_engine split) | хорошо | 8/10 |
| Patch registry (136 entries, ratchet, schema) | стабильно | 9/10 |
| Unit/integration tests (5291 + 5 integration) | strong coverage | 8/10 |
| CLI surface (35+ команд) | comprehensive | 8/10 |
| Production launch (27B PROD up на dev209) | live | 8/10 |
| Documentation | current docs OK, archive нужен | 6/10 |
| Installer/bootstrap | model-artifacts + service planners активированы | 7/10 |
| K8s/Proxmox | doctor + safer install — основа есть | 6/10 |
| Security (license signing) | placeholder pubkey | 4/10 |

**Production verdict:** **готово для public beta**.

Для private/commercial overlay — нужны P3.3 (trust anchor) + P3.1 (live CI) минимум.
Для full production-grade — нужны P2.1 (dispatch collapse) + P2.4 (MambaRadixCache) для качественного скачка.

---

## Изменения процесса (lessons learned)

1. **TDD-first для новых features.** Все 29 новых тестов написаны ПЕРЕД или ВО ВРЕМЯ implementation, не после. Каталог lessons:

   - `runtime_tunables.py` + 20 тестов (registry contract, integration с audit).
   - `cli/host.py` + tests later в P4.4 цикле.
   - `cli/k8s.py::doctor` + 3 теста (exit codes, JSON contract).

2. **Per-metric tolerance в bench.** Универсальный 5% budget для bench-метрик ложно срабатывает на TTFT (CV ~35%). Per-metric override через env (`GENESIS_INTEGRATION_REGRESSION_BUDGET_TTFT_MS`) — паттерн для будущих jittery метрик.

3. **Ratchet архитектурная защита.** STABLE-ratchet корректно блокировал PN33/PN35 промоут до infrastructure был готов — система работает как design'ом задумано. Не упростить ratchet, а расширить (P2.3).

4. **No curl|sh даже в инструкциях.** Аудит правильно указал — заменили `curl get.docker.com | sh` на apt+keyring во всех places. Принцип: даже строки, которые операторы могут скопировать, должны быть safest-by-default.

---

## Контакт / ссылки

- Источник аудит: `docs/_internal/PROJECT_STATE_AUDIT_2026-05-12_RU.md`
- CHANGELOG: `CHANGELOG.md` (раздел `[v11.0.0+stable_first]` и далее)
- STABLE checklist: `docs/upstream/STABLE_PROMOTION_CHECKLIST.md`
- Бенч-baselines: `tests/integration/baselines/27b_v11_wave9.json` + `35b_v11_wave9.json`
