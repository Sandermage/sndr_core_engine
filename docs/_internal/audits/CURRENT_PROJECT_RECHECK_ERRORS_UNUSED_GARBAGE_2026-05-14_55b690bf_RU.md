# Повторная проверка после исправлений: ошибки, мусорные и потенциально неиспользуемые файлы

Дата проверки: 2026-05-14 06:42-06:47 EEST  
Ветка: `dev`  
HEAD: `55b690bf` (`tests: track current FROZEN_V1_BASELINE size dynamically`)  
Scope: локальный проект `/Users/sander/Documents/Visual Studio Code/genesis-vllm-patches`

## Executive Summary

Статический release-контур сейчас зеленый:

- `make evidence`: **PASS, 40/40 gates green**.
- `make audit`: PASS.
- `python3 scripts/security_scan.py`: PASS, `0` findings.
- `python3 -m vllm.sndr_core.compat.cli self-test --json`: PASS, `8/8`.
- `python3 -m vllm.sndr_core.apply.shadow --strict`: PASS, clean.
- `python3 -m vllm.sndr_core.cli patches prove --dead-detect --json`: PASS, `151/151`, `dead=0`.
- `make audit-release-check`: PASS, `151/151`.
- `pytest -q tests/unit/test_phase9_v1_freeze.py`: PASS, `21 passed`.

Кодовых release-блокеров по локальным статическим gates не осталось.

Оставшиеся риски не являются падением release gates, но требуют решения перед чистым публичным релизом:

1. Локальная машина не готова к запуску GPU/Docker preset: нет Docker, нет `nvidia-smi`, нет model dir.
2. В worktree `405` untracked entries: много новых файлов проекта, которые нужно либо добавить в git, либо убрать/архивировать.
3. Есть подтвержденный мусор после тестов: `1957` `.pyc`, `118` `__pycache__`, `3` `.DS_Store`, `2` `.pytest_cache`.
4. Найдены `71` кандидатов на “неиспользуемые/неподключенные” файлы по статическому zero-reference scan. Это не автоматическое доказательство удаления, но список нужно разобрать.

## Результаты проверок

| Проверка | Результат | Детали |
|---|---:|---|
| `git rev-parse --short HEAD` | `55b690bf` | текущий HEAD |
| `git status --short` | WARN | `405` untracked entries |
| `self-test --json` | PASS | `8/8`, registry `151` |
| `apply.shadow --strict` | PASS | no unexpected divergence |
| `patches prove --dead-detect --json` | PASS | `151/151`, `dead=0`, `coverage=100%` |
| `security_scan.py --json` | PASS | `0` total failures, `549` tracked files scanned |
| `check_no_legacy_imports.py` | PASS | `988` files scanned, clean |
| `make audit-public-paths` | PASS | public paths clean |
| `make audit-configs` | PASS | `11/11` presets compose cleanly |
| `make audit-community` | PASS | `0` manifests, `0` errors, `0` warnings |
| `make audit-all-referents` | PASS | `443` Python files scanned |
| `make audit-readme-counters` | PASS | README authoritative counts match |
| `make audit-no-hardcoded-paths` | PASS | `50 clean / 1 exempt / 0 violations` |
| `make audit-no-stub` | PASS | no unresolved stubs in `vllm/sndr_core/**/*.py` |
| `make audit-engine-boundary` | PASS | no unguarded `vllm.sndr_engine` imports |
| `make audit-release-check` | PASS | `151/151`, release policy satisfied |
| Python compile scan | PASS | `880` files checked, `0` errors |
| Shell syntax scan | PASS | `72` `.sh` files, `0` errors |
| Project config parse | PASS | `6` JSON, `1` TOML, `51` YAML, `3` text files |
| `pytest -q tests/unit/test_phase9_v1_freeze.py` | PASS | `21 passed` |
| `make audit` | PASS | audit suite complete |
| `make evidence` | PASS | `40/40`, `0` informational warnings |

## Ошибки, которые остались

### E-001. Локальная host-среда не готова к запуску GPU/Docker preset

Статус: не ошибка кода, но runtime blocker для локальной машины.

Команды:

```bash
python3 -m vllm.sndr_core.cli deps plan --config a5000-2x-35b-prod --json
python3 -m vllm.sndr_core.cli launch a5000-2x-35b-prod --preflight-only --check-deps
```

Результат:

```text
is_ready: false
n_blockers: 3
warning: 1
```

Blockers:

| Scope | Target | Причина |
|---|---|---|
| `docker` | Docker Engine | Docker не найден в `PATH` |
| `nvidia` | NVIDIA driver | preset требует 2 GPU, но `nvidia-smi` не найден в `PATH` |
| `model` | `cyankiwi/Qwen3.6-35B-A3B-FP8 → /models/Qwen3.6-35B-A3B-FP8` | model directory missing |

Warning:

| Scope | Target | Причина |
|---|---|---|
| `vllm` | `vllm 0.20.2rc1.dev209+g5536fc0c0` | `vllm` не импортируется в текущем Python; допустимо, если запуск через Docker |

Позитивный факт: `launch --check-deps` теперь корректно возвращает `exit 2`, то есть false-pass исправлен.

Решение:

- На локальной macOS/dev машине это можно считать expected.
- На сервере нужно отдельно прогнать тот же `deps plan` и короткий GPU smoke.
- В release dashboard разделять `static release green` и `runtime host ready`.

### E-002. Worktree содержит 405 untracked entries

Статус: не падает в `make evidence`, но мешает clean release snapshot.

Сводка:

```text
?? 405
total 405
```

Группы untracked entries:

| Top-level | Count | Комментарий |
---|---:|---|
| `tests/` | 187 | похоже на реальный новый test surface, не мусор |
| `vllm/` | 187 | похоже на реальный новый `sndr_core` code surface, не мусор |
| `scripts/` | 11 | часть release/audit/build utilities |
| `.github/` | 4 | CI/release workflows |
| `docs/` | 4 | generated/community docs |
| `tools/` | 4 | tools/test helpers |
| `assets/` | 2 | generated charts/images |
| `sponsor-site/` | 1 dir | отдельный site/app surface; нужно решить, входит ли в repo |
| `compose/docker-compose.test-v11.yml` | 1 | test compose |
| `constraints.txt` | 1 | dependency/release artifact candidate |
| `requirements-dev.lock` | 1 | dependency/release artifact candidate |
| `requirements-runtime.lock` | 1 | dependency/release artifact candidate |
| `SESSION_LOG_2026-05-06.md` | 1 | session log, возможно internal-only |

Решение:

1. Если это текущая рабочая версия проекта, нужно staged/tracked решение: добавить в git или вынести из release tree.
2. Для `sponsor-site/` решить отдельно: это продуктовая часть или внешний сайт.
3. Для generated docs (`docs/CONFIGS_AUTO.md`, `docs/PATCHES_AUTO.md`) лучше либо трекать, либо явно генерировать в CI и держать вне git.
4. Для `docs/_internal` не делать `git clean -X` без бэкапа: там лежат audit reports.

## Подтвержденный мусор

Это файлы/директории, которые не являются исходниками и безопасны для удаления после сохранения нужных отчетов:

| Тип | Count |
|---|---:|
| `*.pyc` | 1957 |
| `__pycache__/` dirs | 118 |
| `.DS_Store` | 3 |
| `.pytest_cache/` dirs | 2 |
| AppleDouble `._*` | 0 |

Найденные top-level/cache locations:

```text
.DS_Store
.pytest_cache/
__pycache__/
assets/charts/__pycache__/
benchmarks/harness/__pycache__/
docs/.DS_Store
docs/_internal/.DS_Store
docs/upstream_refs/__pycache__/
docs/upstream_refs/pr_40792/__pycache__/
docs/upstream_refs/pr_40798/__pycache__/
plugins/community/_template/PN999/__pycache__/
plugins/community/_template/PN999/tests/__pycache__/
scripts/__pycache__/
scripts/_archive/__pycache__/
scripts/stress/__pycache__/
tests/__pycache__/
tests/bench/__pycache__/
tests/bundles/__pycache__/
tests/installer/__pycache__/
tests/integration/__pycache__/
tests/legacy/.pytest_cache/
tests/legacy/__pycache__/
tests/legacy/compat/__pycache__/
tests/legacy/pristine_fixtures/__pycache__/
tests/probes/__pycache__/
tests/soak/__pycache__/
tests/unit/**/__pycache__/
tools/__pycache__/
tools/external_probe/__pycache__/
tools/genesis_vllm_plugin/genesis_v7/__pycache__/
vllm/sndr_core/**/__pycache__/
```

Не запускать вслепую `git clean -ndX` как команду на удаление: dry-run показывает, что вместе с мусором под чистку попадают важные ignored артефакты:

```text
docs/_internal/
evidence/
internal/
pyproject-engine.toml
genesis_deep_audit_2026-05-07.md
genesis_full_project_audit_2026-05-08.md
sndr_production_readiness_audit_2026-05-08.md
sndr_repeat_deep_audit_2026-05-08.md
sndr_structure_deep_audit_2026-05-07.md
sponsor-site/config/
sponsor-site/data/
sponsor-site/package.json
```

Рекомендованная безопасная чистка, если решишь удалять только мусор:

```bash
find . -name '__pycache__' -type d -prune -exec rm -rf {} +
find . -name '*.pyc' -type f -delete
find . -name '.DS_Store' -type f -delete
find . -name '.pytest_cache' -type d -prune -exec rm -rf {} +
```

Команды выше не запускались.

## Кандидаты на неиспользуемые/неподключенные файлы

Методика: статический scan `1159` текстовых файлов; файл попадает в список, если его путь, имя, stem или Python module path не найден ни в одном другом текстовом файле. Это не абсолютное доказательство: standalone CLI, архивные scripts, pytest-discovered tests и внешние operator scripts могут быть полезны без текстовых ссылок.

### Высокий приоритет ручной проверки

Эти файлы выглядят как реальные code/util файлы, но имеют ноль внешних текстовых ссылок:

| Файл | Почему проверить |
|---|---|
| `vllm/sndr_core/cli/pn95_prometheus.py` | CLI module не подключен к root CLI; только self-docstring usage |
| `vllm/sndr_core/compat/quant_config_compat.py` | compat module не найден в root CLI/tests/import lists; только self references |
| `vllm/sndr_core/integrations/offload/pn102_pinned_alloc_pool.py` | выглядит как patch implementation, но не привязан к registry/apply_module; `PN102` не совпадает с registry `P102` |
| `scripts/genesis_longbench_runner.py` | standalone script, внешних ссылок не найдено |
| `scripts/server_validate.sh` | standalone validation script, внешних ссылок не найдено |
| `tools/phase_final_extended_stress.sh` | standalone stress script, внешних ссылок не найдено |

Решение:

- Если нужны: добавить README/Makefile/CLI/docs ссылки или tests.
- Если не нужны: перенести в `scripts/_archive/` или удалить.
- Для `pn102_pinned_alloc_pool.py`: либо добавить registry entry/apply_module, либо переименовать/удалить как orphan patch draft.

### Scripts/archive candidates

```text
scripts/launch/_archive/historical/start_ngram_p77adaptive.sh
scripts/launch/_archive/historical/start_no_spec_async.sh
scripts/launch/_archive/historical/start_v747_p82.sh
scripts/launch/_archive/historical/start_v755_mamba_align.sh
scripts/launch/_archive/historical/start_v756_align_no_spec.sh
scripts/launch/_archive/historical/start_v757_align_mtp_no_p5.sh
scripts/launch/_archive/research/start_v786_arm_a_baseline_refresh.sh
scripts/launch/_archive/research/start_v786_arm_b_prefix_cache_on.sh
scripts/launch/_archive/research/start_v786_arm_c_p83_p85.sh
scripts/launch/_archive/research/start_v786_arm_d_p83_p84_p85.sh
scripts/launch/_archive/research/start_v786_arm_e_p40_enable.sh
scripts/launch/_archive/research/start_v786_template.sh
scripts/launch/_archive/research/start_v788_int8_27b_pn8_pn9.sh
scripts/launch/_archive/research/start_v789_35b_pn8_only.sh
scripts/launch/_archive/research/start_v791c_27b_util088.sh
scripts/launch/_archive/superseded_by_model_configs/start_27b_int4_TQ_k8v4_root.sh
scripts/launch/_archive/superseded_by_model_configs/start_35b_fp8_PROD_root.sh
```

Оценка: это архивные/historical scripts. Не release blocker. Если цель — компактный public repo, их лучше вынести в отдельный archive/internal repo или оставить только через documented archive policy.

### Docs/reference candidates

```text
docs/CONFIGS_FOR_COMMUNITY.md
docs/PATH_C_TIER_AWARE_KV_CACHE.md
docs/PROJECT_MAP.md
docs/reference/BOTS_SETUP.md
docs/reference/DEFERRED_P50_DEPLOY.md
docs/reference/DEFERRED_P87_PR40924.md
docs/reference/LONG_CONTEXT_VALIDATION_20260427.md
docs/reference/V758_P75_SUFFIX_DECODING_DEPLOY_VARIANT.md
docs/upstream/PRODUCTION_ROADMAP_EXPANDED_DELTA_AUDIT_2026-05-08.md
docs/upstream/VLLM_PR_DECISION.md
```

Оценка: могут быть полезными, но не связаны из public README/docs navigation. Если нужны пользователям — добавить index links. Если internal — перенести в `docs/_internal` или `docs/reference/archive`.

### Upstream reference code candidates

```text
docs/upstream_refs/dev134_chunk_scaled_dot_kkt.py
docs/upstream_refs/dev134_linear_attn.py
docs/upstream_refs/dev134_triton_turboquant_decode.py
docs/upstream_refs/dev134_turboquant_attn.py
```

Оценка: похоже на raw upstream reference snapshots. Если они нужны как evidence/source comparison, лучше добавить README в `docs/upstream_refs/` с назначением. Если нет — архивировать.

### Benchmark raw/orphan candidates

```text
benchmarks/2026-04-21_40420_cliff_analysis/raw/01_baseline_sweep_128-256k/128k_mml131072_startup.txt
benchmarks/2026-04-21_40420_cliff_analysis/raw/01_baseline_sweep_128-256k/148k_mml151552_startup.txt
benchmarks/2026-04-21_40420_cliff_analysis/raw/01_baseline_sweep_128-256k/160k_mml163840_startup.txt
benchmarks/2026-04-21_40420_cliff_analysis/raw/01_baseline_sweep_128-256k/172k_mml176128_startup.txt
benchmarks/2026-04-21_40420_cliff_analysis/raw/01_baseline_sweep_128-256k/188k_mml192512_startup.txt
benchmarks/2026-04-21_40420_cliff_analysis/raw/01_baseline_sweep_128-256k/204k_mml208896_startup.txt
benchmarks/2026-04-21_40420_cliff_analysis/raw/01_baseline_sweep_128-256k/226k_mml231424_startup.txt
benchmarks/2026-04-21_40420_cliff_analysis/raw/01_baseline_sweep_128-256k/245k_mml250880_startup.txt
benchmarks/2026-04-21_40420_cliff_analysis/raw/01_baseline_sweep_128-256k/256k_mml262144_startup.txt
benchmarks/2026-04-21_40420_cliff_analysis/raw/01_baseline_sweep_128-256k/genesis_bench_sweep_128k_mml131072_20260421_173953.json
benchmarks/2026-04-21_40420_cliff_analysis/raw/01_baseline_sweep_128-256k/genesis_bench_sweep_148k_mml151552_20260421_174518.json
benchmarks/2026-04-21_40420_cliff_analysis/raw/01_baseline_sweep_128-256k/genesis_bench_sweep_160k_mml163840_20260421_175055.json
benchmarks/2026-04-21_40420_cliff_analysis/raw/01_baseline_sweep_128-256k/genesis_bench_sweep_172k_mml176128_20260421_175643.json
benchmarks/2026-04-21_40420_cliff_analysis/raw/01_baseline_sweep_128-256k/genesis_bench_sweep_188k_mml192512_20260421_180232.json
benchmarks/2026-04-21_40420_cliff_analysis/raw/01_baseline_sweep_128-256k/genesis_bench_sweep_204k_mml208896_20260421_180830.json
benchmarks/2026-04-21_40420_cliff_analysis/raw/01_baseline_sweep_128-256k/genesis_bench_sweep_226k_mml231424_20260421_181428.json
benchmarks/2026-04-21_40420_cliff_analysis/raw/01_baseline_sweep_128-256k/genesis_bench_sweep_245k_mml250880_20260421_182027.json
benchmarks/2026-04-21_40420_cliff_analysis/raw/01_baseline_sweep_128-256k/genesis_bench_sweep_256k_mml262144_20260421_182530.json
benchmarks/2026-04-21_40420_cliff_analysis/raw/02_patch20_only_234cliff/genesis_bench_patch20_cliff_228to260_step2_20260421_183252.json
benchmarks/2026-04-21_40420_cliff_analysis/raw/03_patch20_util085_seqs2/genesis_bench_exp_A_probe_250to260_20260421_200459.json
benchmarks/2026-04-21_40420_cliff_analysis/raw/03_patch20_util085_seqs2/genesis_bench_exp_A_util085_maxseq2_20260421_200224.json
benchmarks/2026-04-21_40420_cliff_analysis/raw/03_patch20_util085_seqs2/startup_info.txt
benchmarks/2026-04-21_40420_cliff_analysis/raw/04_patch20_util0905_seqs1/genesis_bench_exp_B_util0905_maxseq1_20260421_200857.json
benchmarks/2026-04-21_40420_cliff_analysis/raw/04_patch20_util0905_seqs1/startup_info.txt
benchmarks/2026-04-21_40420_cliff_analysis/raw/05_patch22_util085/genesis_bench_p22_cliff_228to260_util085_20260421_215807.json
benchmarks/2026-04-21_40420_cliff_analysis/raw/05_patch22_util085/harness_32_33_GO.json
benchmarks/2026-04-21_40420_cliff_analysis/raw/06_patch22_util0905_TRUTH/genesis_bench_p22_util0905_TRUTH_228to260_20260421_220314.json
benchmarks/archive_v5_v6/bench_v5.10_20260419.json
benchmarks/archive_v5_v6/harness_baseline_fp8_v5.7.json
benchmarks/archive_v5_v6/harness_v5.10.json
benchmarks/v7_10_validation_20260424/gemma4_26b_moe/FAILURE_NOTE.md
```

Оценка: это не “мусор” технически, но public repo может раздуваться raw bench artifacts. Лучше:

- оставить summarized benchmarks в docs;
- raw JSON/TXT перенести в `benchmarks/archive/` с README;
- или вынести в release assets / external storage.

### Остальные zero-reference candidates

```text
SESSION_LOG_2026-05-06.md
tests/integration/baselines/27b_v8.json
```

Оценка:

- `SESSION_LOG_2026-05-06.md` вероятно internal/session artifact.
- `tests/integration/baselines/27b_v8.json` может быть нужен runtime/integration tests, но статически не найден. Проверить fixture loader.

## Пустые файлы

Найдены пустые файлы, но они не считаются мусором автоматически:

- `__init__.py` в пакетах tests/plugins;
- `.gitkeep` в `plugins/community`;
- package markers.

Их не удалять без проверки, потому что они могут быть нужны для package discovery или сохранения пустой директории.

## Итоговый план

1. Не исправлять код по release gates: они уже зеленые.
2. Удалить confirmed generated trash: `.pyc`, `__pycache__`, `.DS_Store`, `.pytest_cache`.
3. Разобрать `405` untracked entries:
   - staged: новый `sndr_core`, tests, CI, lockfiles, generated docs;
   - archive/internal: session logs, old audit docs, raw benches;
   - remove: confirmed cache files only.
4. Проверить high-priority orphan candidates:
   - `vllm/sndr_core/cli/pn95_prometheus.py`;
   - `vllm/sndr_core/compat/quant_config_compat.py`;
   - `vllm/sndr_core/integrations/offload/pn102_pinned_alloc_pool.py`;
   - `scripts/genesis_longbench_runner.py`;
   - `scripts/server_validate.sh`;
   - `tools/phase_final_extended_stress.sh`.
5. После cleanup повторить:

```bash
make evidence
python3 scripts/security_scan.py
pytest -q tests/unit/test_phase9_v1_freeze.py
git status --short
```

