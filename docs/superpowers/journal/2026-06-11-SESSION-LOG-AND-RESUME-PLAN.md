# 2026-06-11 — Полный лог сессии + план возобновления

> **Назначение этого файла.** За 2026-06-11 шла большая многочасовая
> сессия по доводке Genesis до энтерпрайз-уровня + адаптации 50
> апстрим-PR vLLM. Сессию несколько раз прерывал лимит токенов. Этот
> документ фиксирует ВСЁ сделанное с 00:00, текущее проверенное
> состояние (включая НЕзакоммиченную волну 2) и точный план
> возобновления. Читать сверху вниз; раздел «С ЧЕГО ПРОДОЛЖАТЬ» —
> в самом низу.
>
> **Пин:** `vllm 0.22.1rc1.dev259+g303916e93` (digest d892cc41…).
> **Ветка:** `feat/v12-sndr-platform` на `sndr-dev` (приватный).
> Публичный origin — НЕ трогаем (правило пользователя).
> **PROD:** 35B FP8 на `vllm-qwen3.6-35b-balanced-k3`, порт 8102, жив.
> **Pristine-дерево пина:** `/private/tmp/candidate_pin_current/vllm`.

---

## ЧАСТЬ 1 — Хронология: что закоммичено сегодня (13 коммитов)

Все коммиты на `sndr-dev/feat/v12-sndr-platform`. Время локальное (Киев).

| Время | Коммит | Суть |
|---|---|---|
| 01:21 | `23033ddb` | triage IMMEDIATE: PN353A self-collision marker fix (патч НИКОГДА не применялся из-за маркера-самострела — имя API пина), P6 merged-superset нейтрализация, bench reasoning-поле, a5000-2x digest bump |
| 01:34 | `27b8138a` | journal: флит-валидация на пине — 4 модели загружены+бенчены, тулы 7/7 |
| 01:39 | `78e35b78` | **P107 v3**: убрана мёртвая `auto_tools_called`-клауза из стримингового детектора (живой NameError на PROD при каждом тул-стриме) |
| 01:51 | `ac98f180` | journal: корень стриминговых тул-коллов (P107 NameError + parse_delta dead-zone) |
| 04:33 | `056282d1` | **fix-drifts батч**: re-anchor PN58/P59/PN288/PN32, trim PN38 site B (SyntaxError-риск), repoint G4_03 (eagle3 модуль исчез) |
| 04:34 | `bbbdbe4f` | **preflight v1.2**: env-forced retry, ENV_GATED_ABSTAIN, `_read_<param>` fill, KNOWN_OPTIONAL_RETIRED + линт маркеров-самострелов |
| 04:34 | `86615ae6` | **retire x9 + гигиена + G4_79 + промоция пинов**: ретайр P7b/PN54/P78/P36/P83/P84/P4/P20/P6 (byte-доказательства), G4_79 TQ mm_prefix разблокировка Gemma-31B, ModelDef'ы промоутнуты на пин |
| 05:26 | `e29fbf5d` | GUI integration audit: reliability + correctness фиксы |
| 05:26 | `f434958d` | GUI: пересборка web_static |
| 05:48 | `596057c9` | GUI: enterprise hardening + release prep |
| 13:13 | `ce2e2de8` | **own-queue**: self-collision 111→0 нарушений (65 модулей), P85 both-sites, P91B alternation-манифест, profile consistency + **50-PR roadmap** |
| 13:42 | `1a38484b` | GUI: chat "(empty)" на reasoning-моделях + web-search handoff |
| **15:10** | **`f84bf7b4`** | **ВОЛНА 1**: PN370-375, G4_80 + G4_31v2, P79d rewrite — реестр 280→287, все гейты зелёные |

**HEAD сейчас = `f84bf7b4` (волна 1).**

### Что дала волна 1 (закоммичено, проверено)

7 новых патчей из роадмапа (все opt-in, default OFF, ждут A/B на сервере):

- **PN370** (vllm#45100): гонка accepted-counts при async+MTP — тихая
  порча вывода на точной PROD-конфигурации 35B + **~2-5% TPOT**
  (убирается per-step synchronize). Двойные якоря координируют с PN341.
- **PN371** (vllm#45199): deferred encoder-cache eviction — engine-fatal
  «Encoder cache miss» на Gemma-4 vision+MTP+async; наш extra: fatal
  assert → warn+skip в drafter-пути.
- **PN372** (vllm#45005): zero-seqlen Triton-гард в eagle_step
  (строже `<=0` vs апстрим `==0`) — CUDA IMA на 262-280K MTP-сессиях.
- **PN373** (vllm#44955): `parallel_tool_calls: null != false` —
  прекращает тихое урезание мульти-тулов для null-клиентов.
- **PN374** (genesis-original): qwen3xml quoted-key asymmetry —
  класс бага #44877 найден в НАШЕМ PROD-парсере 35B аудитом.
- **PN375** (vllm#44741): Gemma-4 мульти-граничные стрим-дельты под MTP;
  наш extra: strip G4_14 pad-set до consistency-чека.
- **G4_80** (vllm#45040): fp8_e5m2 KV для weight-only чекпойнтов + новый
  профиль `gemma4-31b-fp8e5m2-fallback` (путь к возврату 256K на 31B).
- **G4_31 v2** (vllm#45038): второй suppress-arm — guard fp8 auto-override
  для kv-auto на sub-SM90 (мина IMA-on-burst на живом 31B-профиле).
- **P79d v2**: стухший dead-boolean бэкпорт переписан на integer
  credit-семантику пина (включённый — упал бы на assert).
- Бонус: #44877 quoted-key в G4_T1 overlay, PN348 включён в 35B ModelDef,
  PATCHES.md GDN-offload правка, **tools/upstream_watchlist.yaml** с
  retire-on-merge строками по всем 50 PR + валидатор + make-таргет.

---

## ЧАСТЬ 2 — НЕзакоммиченное состояние: ВОЛНА 2 на диске (КРИТИЧНО)

**Волна 2 РЕАЛИЗОВАНА в рабочем дереве, но НЕ интегрирована и НЕ
закоммичена.** Воркфлоу `wf_56f4f4bb-549` (resume `wpc50kn3v`)
отработал фазы реализации+ревью+фиксапов, но **умер на лимите в
финальной registry-фазе**. Поэтому:

- ✅ Все модули и тесты — на диске (61 файл в `git status`).
- ✅ Синтаксис: 0 ошибок (`ast.parse` по всем).
- ✅ Заглушек нет (нет TODO/FIXME/NotImplementedError/stub).
- ✅ Юнит-тесты: **922 passed, 1 skipped** (skip = torch-тест на Mac).
- ❌ Записи реестра НЕ добавлены (реестр = 287, должно стать ~297).
- ❌ Proof-артефакты НЕ сгенерированы.
- ❌ Снапшоты/счётчики доков НЕ обновлены.
- ❌ Гейты (doctor/doc-sync/prove-all/release-check) НЕ прогнаны.
- ❌ НЕ закоммичено.

### Новые патч-модули волны 2 (на диске, ждут реестра)

| Патч | Файл | PR | Что делает | Строк |
|---|---|---|---|---|
| **PN358** | compile_safety/pn358_full_cg_context_refresh.py | #44868 | FULL-CG forward-context refresh + наш extra: data_ptr-pruned copy (убирает 1-3% TPOT апстрима) + detect-режим (аудит утечки тензоров в графы) | 532 |
| **PN376** | quantization/pn376_fp8_ignore_substring.py | #44628 | FP8 modules_to_not_convert substring-match (тихий gibberish на ignore-списках) | 598 |
| **PN377** | moe/pn377_moe_wna16_bsk_clamp.py | #44563 | moe_wna16 BLOCK_SIZE_K legality clamp для gs=32 + наш extra: boot-time legality assert | 449 |
| **PN378** | spec_decode/pn378_recovered_token_vocab_pad_mask.py | #45060 (kernel half) | -inf маска на vocab-padding tile (Qwen vocab 151936%8192≠0 → NaN-livelock) | 198 |
| **PN379** | loader/pn379_load_config_fail_fast.py | #45196 | LoadConfig fail-fast валидация (тихие misconfig → loud ValueError) | 409 |
| **PN380** | spec_decode/pn380_qwen3_mtp_prefused_expert_loader.py | #44943 | Qwen3.5/3.6 MTP pre-fused expert loader + наш extra: load-coverage guard | 477 |
| **PN381** | spec_decode/pn381_allowed_token_ids_spec_metadata.py | #44742 | allowed_token_ids metadata hardening (защита pn369/p71 sampler) | 234 |
| **PN382** | kv_cache/pn382_decode_bench_hybrid_fill.py | #45080 | DecodeBenchConnector fix + наш extra: per-block fill (pin MambaSpec block-indexed) | 369 |
| **G4_81** | attention/turboquant/g4_81_tq_multi_query_direct_route.py | #45144 blueprint | **Variant B**: multi-query DIRECT routing — разблокировка MTP K=3 × TQ на Gemma-31B (**+20-40% decode TPS** если взлетит). НЕ BLOCKED — 625 строк реализации | 625 |

### Изменённые файлы волны 2 (in-place правки)

- **g4_60e_kv_cache_utils.py** + overlays/pr42637/kv_cache_utils.py —
  реконсиляция #45207+#45181 (MambaSpec+AttentionSpec page-padding).
- **p81_fp8_block_scaled_m_le_8.py** + g4_kpad_moe_gemm_triton.py —
  #45126 re-tune note + sweep-target.
- **p62_structured_output_spec_decode_timing.py** — #44993 grammar-тесты.
- **pn133_mtp_scheduler_empty_output.py** — #45060 log.error extension.
- **pn55_wake_up_hybrid_kv.py** — #44778 hygiene (exec-patched-text тест).
- **g4_t1_pr42006_marker.py** + g4_t1_v2…overlay.py — #44877 quoted-key.
- **genesis_bench_suite.py** — #44943 accept-rate floor WARN.
- **g4_t1_v3…pr44844_overlay.py** (новый, 1069 строк) — span-based v3 для A/B.
- **env.py**, **_per_patch_dispatch.py** — env-флаги + dispatch-хуки новых патчей.
- **Makefile**, **docs/PIN_BUMP_PLAYBOOK.md**, **scripts/audit_config_keys.py**.

### 4 новых tool-скрипта волны 2

- **tools/triton_gemm_sweep.py** (843) — оффлайн tile-tuning sweep (sm_86).
- **tools/tokenizer_fingerprint.py** (349) — sha256-гейт токенайзера для pin-bump.
- **tools/endurance_probe.py** (364) — multi-hour VRAM/RSS/KV-creep сэмплер.
- **tools/cudagraph_mem_estimate_ab.py** (487) — measure-first A/B #45197.

---

## ЧАСТЬ 3 — АУДИТ КАЧЕСТВА: найденные недоработки

Пользователь явно попросил проверить, «чтобы не получилось что недописан
код или задача выполнена плохо». Аудит проведён. Найдено ДВА разрыва:

### ✅ ИСПРАВЛЕНО: torch-гард в pn340-тесте
`tests/unit/integrations/attention/gdn/test_pn340_gdn_builder_buffer_stability_torch.py`
делал `import torch` со skip-гардом на `vllm`, а не на `torch` → на
машине без torch падал на сборке вместо скипа. Поправлено на
`torch = pytest.importorskip("torch", …)`. Теперь корректно скипается.

### ❌ ТРЕБУЕТ РЕАЛИЗАЦИИ: модуль P88 ОТСУТСТВУЕТ
Задача `gates-45109-45196-45202` создала тест
`tests/unit/integrations/observability/test_p88_prefix_cache_stats_dedup.py`
(полный TDD: 15+ кейсов), но **сам модуль
`sndr/engines/vllm/patches/observability/p88_prefix_cache_stats_dedup.py`
агент не успел дописать** (умер на лимите). Это #45202 — prefix-cache
stats double-count fix.

**Контракт модуля (из теста), что нужно реализовать:**
- Экспорты: `GENESIS_P88_MARKER`, `P88_LOOKUP_ANCHOR`,
  `P88_LOOKUP_REPLACEMENT`, `P88_ALLOC_COMMIT_ANCHOR`,
  `P88_ALLOC_COMMIT_REPLACEMENT`, `_connector_configured`,
  `_make_kv_cache_manager_patcher` + стандартные `apply()`/`is_applied()`.
- Цель: `KVCacheManager` (pristine `v1/core/kv_cache_manager.py`) —
  подавить запись prefix-cache-stats в `get_computed_blocks`, записать
  на УСПЕХЕ `allocate_slots` (наш safer-вариант в стиле p79d, не
  апстрим-диф). Anchor'ы byte-exact против pristine, count==1.
- Семантика тестов: lookup НЕ записывает; commit записывает один раз и
  чистит pending; failed allocation не считается → retry считает один
  раз; preempted → preempted-счётчики; caching disabled → ничего;
  log_stats off → noop; connector configured → fallback-disable.

---

## ЧАСТЬ 4 — ПЛАН ДАЛЬНЕЙШЕЙ РАБОТЫ

### ЭТАП A — Завершить интеграцию волны 2 (СЛЕДУЮЩИЙ ШАГ)

1. **Дописать модуль P88** по контракту выше (Study pristine
   `get_computed_blocks`/`allocate_slots` → byte-exact anchors →
   реализация → тест зелёный). ~150-200 строк.
2. **Реестр**: добавить записи PN358/376-382, G4_81, P88 (шаблон —
   запись G4_79/G4_80; pin-specific vendor → `vllm_version_range`
   `>=0.22.0,<0.23.0`; `upstream_pr` + relationship; composes/conflicts:
   PN380↔PN348 на qwen3_5_mtp.py, PN378↔PN133, PN377↔P24, G4_60E
   расширить upstream_pr на 45207+45181). Реестр 287 → ~297.
3. **Paired updates** (чеклист G4_79): `KNOWN_SPEC_ONLY_PATCHES`
   (shadow.py), `_KNOWN_REGISTRY_ONLY` (test_apply_all_dispatcher_sync),
   orphan-set (test_legacy_only_drift_zero), proof'ы
   (`sndr.cli.legacy patches prove <ID>`), снапшоты
   (`SNDR_SNAPSHOT_REGEN=1`), PATCHES_AUTO regen, README/doc счётчики,
   V2 count-pinned тесты (новый профиль fp8e5m2).
4. **Гейты**: pytest dispatcher+tools+scripts+integrations, doctor,
   doc-sync --strict, lint_drift_markers (=0), prove-all, release-check.
5. **Коммит** волны 2 + пуш sndr-dev.

> Удобно поручить монопольному registry-агенту (как в волне 1) — он уже
> знает чеклист. Скрипт воркфлоу волны 2:
> `…/workflows/scripts/wave2-implementation-wf_56f4f4bb-549.js`
> (можно НЕ перезапускать целиком — реализация на диске; нужен только
> registry-агент + P88).

### ЭТАП B — Волна 3 (15 позиций, после интеграции волны 2)

Из роадмапа (`docs/superpowers/journal/2026-06-11-pr-sweep-50-roadmap.md`).
**ПЕРВЫМ — PN351 dual-anchor** (защита от следующего pin-bump:
#45151 вставляет 7 kwargs ровно внутрь `PN351_LAUNCH_OLD` — гарантированный
разрушитель якоря). Далее:

- **#44912 → фикс НАШЕГО PN77** (0-D fp8 scale: `amax()` → добавить
  `.view(1)`; будущий InductorError на sm89+). Это фикс к нашему коду.
- **#45176** — ABI pin-bump guard (verify `_C_stable_libtorch`/`_moe_C`
  резолв; путь к нативным Genesis-ядрам через пины).
- **#44850** — 4-строчный tile_mask (constexpr-dead при USE_TD=False =
  доказуемо free) + NaN-canary harness против наших TQ-ядер.
- **#45146 → P79e** (reset placeholders при KV-load-failure rewind;
  dormant до KV-offload).
- **#45053** — explicit-direction API в PN95 stream-pool.
- **#45130** — fail-fast FP8 MoE + LoRA guard (vendor на bump).
- **#45120** — fused softmax microbench port (+ retire router_softmax.py).
- **#45173** — proxy track A (embeddings chat messages, ~20 строк в proxy).
- **#44754** — анти-вендор: watch-row + TQ get_current_vllm_config
  hardening на turboquant_attn.py:496.
- **#45184/#45001/#44932** — практические части (salience-tap для PN95,
  bandwidth-playbook для TQ-ядер, fused gather+dequant паттерн).
- **#45096/#44837** — stream-ordering checklist + prefix= AST-lint
  (часть уже сделана в волне 2 как test_quantized_linear_prefix.py).

### ЭТАП C — Серверная бенч-кампания «до/после» (после волн)

Базлайны утренней флит-валидации (для сравнения):
- **35B PROD** (chat-matrix, reasoning-парсер ON): thinking_off **250.0**,
  thinking_on **250.0**, code **217.6**, multi_turn **231.3**,
  short **200.3** TPS; tool_call стрим работает (5 дельт, finish=tool_calls).
- **27B**: suite **120.9 TPS** (CV 2.7%), TPOT 7.6ms, тулы 7/7.
- **Gemma-26B**: TPOT 6.0ms (~165 TPS decode), тулы 7/7.
- **Gemma-31B**: degraded kv-auto **78.4 TPS**, тулы 7/7 (TQ заблокирован).

Кампания:
1. rsync `sndr/` на риг (`sander@192.168.1.10`), пин-overlay.
2. **35B**: рестарт с PN348-enabled (A/B буст по VRAM/буту) — замерить
   peak VRAM/рank + boot time vs текущее; suite+matrix vs базлайн 250/250/217.6.
3. **PN370 A/B** на 35B (главный TPOT-кандидат: ~2-5%) — env on/off,
   3 прогона, decode-TPOT.
4. **G4_80 31B fp8e5m2 boot** — попытка вернуть 256K контекста (профиль
   gemma4-31b-fp8e5m2-fallback, Triton backend); если взлетит — bench vs 78.4.
5. **Variant B (G4_81)** на 31B — попытка MTP K=3 × TQ (+20-40% если взлетит).
6. **Тулы stream+non-stream** на всех (регрессионная проверка PN373-375).
7. Восстановить 35B PROD в исходное.

**Серверное правило:** стоп 35B → тест → восстановление 35B. Тул-валидация
ОБЯЗАТЕЛЬНО включает стриминговое плечо (урок P107/parse_delta).

---

## ЧАСТЬ 5 — Справочник для следующей сессии

- **Реестр сейчас:** 287 записей (волна 1). После волны 2 → ~297.
- **Линт маркеров:** 0 нарушений (держать через
  `python3 tools/lint_drift_markers.py /private/tmp/candidate_pin_current/vllm`).
- **Pristine-дерево пина:** `/private/tmp/candidate_pin_current/vllm`.
- **Роадмап 50 PR:** `docs/superpowers/journal/2026-06-11-pr-sweep-50-roadmap.md`
  (5 тем-синтезов, волны W1/W2/W3, дубликаты, синергии).
- **Watchlist:** `tools/upstream_watchlist.yaml` (retire/reanchor-on-merge
  по всем 50 PR; валидатор `tools/check_upstream_watchlist.py`).
- **Бэкап partial волны 2:** `/tmp/wave2_partial_backup/` (11 файлов —
  первая попытка до resume; в дереве актуальнее, бэкап для сверки).
- **Конвенции патча:** `apply()` обязателен; гейтинг — либо
  `should_apply()` (dispatcher), либо собственный `_is_enabled()`
  (env-флаг) — оба валидны. Anchor'ы byte-exact против pristine, count==1.
  Drift-маркеры НЕ должны содержать собственный emitted-текст
  (кроме `[Genesis`-префикса).
- **Шесть шагов перед изменением** (iron rule):
  Study→Analyze→Verify→Search→Compare→Change. Для PR: `gh pr view/diff`,
  греп pristine («не в пине?»), греп registry («не вендорим?»).

---

## С ЧЕГО ПРОДОЛЖАТЬ (TL;DR)

1. **Дописать модуль P88** (контракт в Части 3) — единственная реальная
   недоработка волны 2.
2. **Интегрировать волну 2 в реестр** (Этап A, шаги 2-5) — записи,
   proof'ы, снапшоты, гейты, коммит, пуш. ~10 новых патчей, реестр →~297.
3. **Волна 3** (Этап B) — PN351 dual-anchor первым, затем PN77-фикс и
   остальное.
4. **Серверная бенч-кампания** (Этап C) — PN348/PN370 A/B на 35B,
   G4_80+Variant B на 31B, тулы stream+non-stream, восстановить PROD.

Волна 1 — закоммичена и проверена (`f84bf7b4`). Волна 2 — на диске,
922 теста зелёные, нужен только P88 + интеграция в реестр.
