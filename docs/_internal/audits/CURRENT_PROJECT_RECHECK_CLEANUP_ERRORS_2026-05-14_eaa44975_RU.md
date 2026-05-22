# Повторная проверка проекта после cleanup `sndr_core` и root docs

Дата проверки: 2026-05-14  
Ветка: `dev`  
HEAD: `eaa44975` (`docs: rewrite README + restructure CHANGELOG + extract v11 migration appendix`)  
Режим: анализ и аудит, без правок production-кода. Изменены только этот отчет и HTML-dashboard.

## 1. Короткий вывод

После последних исправлений основной кодовый слой `vllm/sndr_core` выглядит значительно лучше: registry, shadow gate, patch proof, static compile, shell syntax, config parse, security scan и `make evidence` проходят.

Главные оставшиеся проблемы находятся вокруг проекта, а не внутри ядра:

1. **326 файлов тестов не отслеживаются Git.** Они участвуют в локальном `pytest --collect-only`, но не попадут в релиз/PR/чистый checkout.
2. **`.gitignore` все еще игнорирует важные JSON-артефакты.** Под угрозой package schema, MoE tuning JSON и anchor manifest.
3. **Часть compose/scripts/hooks все еще завязана на старый `_genesis` слой.** Это противоречит v11-структуре и может ломать запуск/проверки вне текущей машины.
4. **В публичных compose/probe/soak файлах есть operator-specific IP, host paths и ключи-заглушки.**
5. **В дереве много generated/cache мусора:** сейчас найдено `1271` cache/artifact items.
6. **Есть 61 zero-reference candidate** вне `sndr_core`: архивные launch scripts, raw bench dumps, upstream refs, отдельные tools/scripts. Часть можно оставить как historical evidence, но не в active public surface.

## 2. Проверки, которые прошли

| Проверка | Статус | Результат |
|---|---:|---|
| `python3 -m vllm.sndr_core.compat.cli self-test --json` | PASS | 8/8, `152` registry entries schema-clean |
| `python3 -m vllm.sndr_core.apply.shadow --strict` | PASS | clean, `150` legacy apply registrations, `152` specs, `139` specs with `apply_module` |
| `python3 -m vllm.sndr_core.cli patches prove --dead-detect --json` | PASS | `152/152`, `dead=0`, `coverage_pct=100.0` |
| `python3 scripts/security_scan.py --json` | PASS | `909` files scanned, `0` failures |
| Python compile scan | PASS | `880` `.py` files, `0` compile errors |
| Shell syntax scan | PASS | `72` shell files, `0` syntax errors |
| YAML/JSON/TOML parse | PASS | `51` YAML, `2` TOML, `1` JSON checked, `0` parse errors |
| `python3 scripts/check_doc_sync.py --strict` | PASS | docs claim `152` patches consistently |
| `python3 scripts/audit_no_new_v1.py` | PASS | V1 baseline frozen: `12/12` |
| `python3 scripts/audit_public_docs.py` | PASS | 36 public docs clean |
| `make audit` | PASS | audit suite complete |
| `make evidence` | PASS | `40/40` gates green, `0` informational warnings |
| `pytest --collect-only -q tests` | PASS | `6171` tests collected |
| `pytest -q tests/unit/test_phase9_v1_freeze.py` | PASS | `21 passed` |

Важно: `make evidence` зеленый, но он не решает проблемы релизной упаковки (`untracked`, ignored package data, stale compose/scripts).

## 3. P0/P1 ошибки и неточности

### P0-1. Тесты локально есть, но не отслеживаются Git

Данные:

```bash
git status --short --untracked-files=all | awk ...
# tests 326
# total 326

git ls-files tests | wc -l
# 70

git ls-files --others --exclude-standard tests | wc -l
# 326

pytest --collect-only -q tests
# 6171 tests collected
```

Проблема:

`tests/` сейчас состоит из двух слоев: `70` tracked-файлов и `326` untracked-файлов. Локальная машина видит полный тестовый слой, но чистый clone/CI/release его не увидит. Это скрытая ошибка зрелости проекта: локальный `make evidence` может проходить рядом с файлами, которые не попадут к пользователю.

Риск:

- другой разработчик/CI не получит большую часть тестов;
- часть новых проверок будет казаться существующей только локально;
- при `git clean -fd` эти тесты исчезнут;
- дорожная карта и dashboard будут завышать readiness.

Что сделать:

1. Принять решение по каждому классу `tests/`: public CI, legacy archive, internal-only.
2. Все public tests добавить в Git.
3. Legacy/pristine fixtures оставить в `tests/legacy/` только если они нужны для regression gates; иначе перенести в `docs/_internal` или `internal`.
4. Добавить release gate:

```bash
test -z "$(git ls-files --others --exclude-standard tests)"
```

5. В `make evidence` добавить отдельный gate `audit-clean-public-test-tree`.

Приоритет: **P0 перед релизом**.

---

### P0-2. `.gitignore` игнорирует важные JSON-артефакты `sndr_core`

Файл: `.gitignore:44-47`

Текущий фрагмент:

```gitignore
# Logs
*.log
*.json
```

Проблемные ignored-файлы:

```bash
git check-ignore -v pyproject-engine.toml \
  vllm/sndr_core/schemas/patch_entry.schema.json \
  vllm/sndr_core/configs/moe_tuning/E=256,N=512,device_name=NVIDIA_RTX_A5000,dtype=fp8_w8a8,block_shape=[128,128].json \
  vllm/sndr_core/manifests/anchor_manifest.json
```

Результат:

```text
.gitignore:90:pyproject-engine.toml pyproject-engine.toml
.gitignore:46:*.json vllm/sndr_core/schemas/patch_entry.schema.json
.gitignore:46:*.json vllm/sndr_core/configs/moe_tuning/E=256,N=512,device_name=NVIDIA_RTX_A5000,dtype=fp8_w8a8,block_shape=[128,128].json
.gitignore:46:*.json vllm/sndr_core/manifests/anchor_manifest.json
```

Дополнительно:

```bash
git ls-files vllm/sndr_core/schemas/patch_entry.schema.json \
  vllm/sndr_core/configs/moe_tuning/E=256,N=512,device_name=NVIDIA_RTX_A5000,dtype=fp8_w8a8,block_shape=[128,128].json \
  vllm/sndr_core/manifests/anchor_manifest.json
# пусто
```

Проблема:

Файлы есть локально и используются/документируются, но Git их игнорирует. `git clean -ndX` показывает, что они будут удалены как ignored:

```text
Would remove vllm/sndr_core/configs/moe_tuning/E=256,N=512,...
Would remove vllm/sndr_core/manifests/anchor_manifest.json
Would remove vllm/sndr_core/schemas/patch_entry.schema.json
```

Риск:

- package/wheel может остаться без schema/package data;
- anchor manifest исчезнет в clean checkout;
- MoE tuning JSON исчезнет из public package;
- локальные self-test результаты будут отличаться от clean clone.

Рекомендованная правка:

```gitignore
# Logs / generated result JSON
*.log
*.results.json
*.bench.json

# Keep source JSON artifacts.
!schemas/patch_entry.schema.json
!vllm/sndr_core/schemas/
!vllm/sndr_core/schemas/patch_entry.schema.json
!vllm/sndr_core/manifests/
!vllm/sndr_core/manifests/*.json
!vllm/sndr_core/configs/
!vllm/sndr_core/configs/**/*.json
```

Приоритет: **P0**.

---

### P0-3. Два schema-файла расходятся

Файлы:

- `schemas/patch_entry.schema.json`
- `vllm/sndr_core/schemas/patch_entry.schema.json`

Проверка:

```bash
cmp -s schemas/patch_entry.schema.json vllm/sndr_core/schemas/patch_entry.schema.json
# schema_cmp=1
```

Разница по properties:

```text
root-only: stable_kind, production_validated_pins, enables_upstream_feature
core-only: implementation_status, source, apply_module, related_upstream_prs
```

Связанный код:

- `vllm/sndr_core/compat/self_test.py:237-284`
- `vllm/sndr_core/compat/schema_validator.py:39-59`

Проблема:

`schema_validator` сначала ищет package schema в `vllm.sndr_core.schemas`, а только потом fallback в root `schemas/`. При этом root schema и package schema уже разные. Значит локальная валидация, package-валидация и документация могут расходиться.

Рекомендация:

1. Назначить один canonical schema.
2. Если canonical внутри package: root `schemas/patch_entry.schema.json` генерировать из package schema или удалить.
3. Если canonical root: package schema брать из root на build step и проверять `cmp`.
4. Добавить gate:

```bash
cmp -s schemas/patch_entry.schema.json vllm/sndr_core/schemas/patch_entry.schema.json
```

Приоритет: **P0**.

---

### P1-1. Active compose-файлы все еще используют `_genesis` и deleted plugin path

Файлы и строки:

- `compose/docker-compose.example.yml:32` — `../vllm_engine/patch_genesis_unified.py`
- `compose/docker-compose.example.yml:43` — `python3 /patches/patch_genesis_unified.py`
- `compose/docker-compose.qwen3-5-dense.yml:37-38` — `../vllm/_genesis` и `../genesis_vllm_plugin`
- `compose/docker-compose.qwen3-5-dense.yml:53` — `python3 -m vllm._genesis.patches.apply_all`
- `compose/docker-compose.gemma4-26b-moe.yml:37-38` — `../vllm/_genesis` и `../genesis_vllm_plugin`
- `compose/docker-compose.gemma4-26b-moe.yml:53` — `python3 -m vllm._genesis.patches.apply_all`
- `compose/docker-compose.integration.yml:122-123`, `164`, `171`
- `compose/docker-compose.integration-awq.yml:122-123`, `164`, `171`
- `compose/docker-compose.integration-fp16kv.yml:122-123`, `164`, `171`

Проблема:

Эти файлы лежат в активной `compose/`, но рассчитаны на pre-v11 layout. После удаления/миграции `_genesis` они либо не стартуют, либо будут запускать несовместимый legacy flow.

Что сделать:

Вариант A, если файлы еще нужны:

```yaml
volumes:
  - ../vllm/sndr_core:/usr/local/lib/python3.12/dist-packages/vllm/sndr_core:ro

command:
  - |
    set -e
    python3 -m vllm.sndr_core.apply --verify-rebinds
    exec python3 -m vllm.entrypoints.openai.api_server ...
```

Вариант B, если это только история:

- перенести в `scripts/launch/_archive/` или `docs/_internal`;
- убрать из public `compose/`;
- оставить один canonical public compose через `sndr launch`/config renderer.

Приоритет: **P1**.

---

### P1-2. `scripts/git/pre-commit` все еще проверяет `_genesis`, а не `sndr_core`

Файл: `scripts/git/pre-commit`

Проблемные строки:

- `33-35` — staged-file filter смотрит только `vllm/_genesis/...`
- `48` — `python3 -m vllm._genesis.compat.schema_validator`
- `60` — `from vllm._genesis.dispatcher import ...`
- `75` — `python3 -m vllm._genesis.compat.lifecycle_audit_cli`
- `89` — `python3 -m vllm._genesis.compat.cli self-test`

Проблема:

В v11 hook почти всегда будет false-pass: реальные изменения в `vllm/sndr_core/...` не попадут в `CHANGED`, значит hook выйдет на `exit 0` без проверки. Если же legacy path случайно совпадет, hook попытается импортировать удаленный `_genesis`.

Рекомендованная правка:

```bash
CHANGED=$(git diff --cached --name-only --diff-filter=ACMR | grep -E \
    '^(vllm/sndr_core/|schemas/patch_entry.schema.json|scripts/audit_|scripts/check_doc_sync.py|README.md|docs/PATCHES)' \
    || true)

python3 -m vllm.sndr_core.compat.schema_validator --quiet
python3 - <<'PY'
from vllm.sndr_core.dispatcher import PATCH_REGISTRY, validate_registry
issues = validate_registry(PATCH_REGISTRY)
...
PY
python3 -m vllm.sndr_core.compat.lifecycle_audit_cli --quiet
python3 -m vllm.sndr_core.compat.cli self-test --quiet
```

Приоритет: **P1**.

---

### P1-3. `tools/check_upstream_drift.py` все еще сканирует старый `_genesis/wiring`

Файл: `tools/check_upstream_drift.py`

Проблемные строки:

- `8-17` — docstring описывает `vllm/_genesis/wiring/patch_*.py` и `vllm/_genesis/patches/upstream_compat.py`
- `95-98` — `_list_wiring_modules()` читает `REPO_ROOT / "vllm" / "_genesis" / "wiring"`
- `310-311` — форматирует label через `vllm._genesis.wiring.`

Проблема:

Инструмент drift-check больше не проверяет актуальную структуру. В v11 он не увидит `vllm/sndr_core/integrations/**` и даст ложное чувство безопасности.

Рекомендованная замена:

- брать список из `vllm.sndr_core.dispatcher.spec.iter_patch_specs()`;
- фильтровать `spec.apply_module` и `implementation_status in {"text_patch", "runtime_hook", "full"}`;
- для text patch сверять anchor manifest через `vllm.sndr_core.wiring.anchor_manifest`;
- upstream markers брать из registry metadata / `upstream_pr`.

Приоритет: **P1**.

---

### P1-4. `scripts/moe_lookup_helper.sh` пишет в удаленный legacy path

Файл: `scripts/moe_lookup_helper.sh`

Проблемные строки:

- `4` — документация пишет `vllm/_genesis/configs/moe_tuning/`
- `30-31` — output path still `_genesis`
- `57` — `OUT_DIR="vllm/_genesis/configs/moe_tuning"`

Проблема:

Запуск helper может заново создать `vllm/_genesis/configs/moe_tuning`, то есть вернуть legacy-структуру после cleanup. Это прямо противоречит `vllm/sndr_core/locations/project_paths.py:254-267`, где canonical path уже `vllm/sndr_core/configs/moe_tuning`.

Рекомендованная правка:

```bash
OUT_DIR="${SNDR_MOE_TUNING_DIR:-vllm/sndr_core/configs/moe_tuning}"
```

Плюс обновить docstring lines `4`, `30-31`.

Приоритет: **P1**.

---

### P1-5. Hardcoded operator endpoints, local paths и ключи в public surface

Файлы:

- `compose/docker-compose.example.yml:112` — `OPENAI_API_KEY=genesis-gw-f9d719aaab89c97bdf649cb7295feb4f1f394c87`
- `compose/docker-compose.example.yml:113` — `OLLAMA_BASE_URL=http://192.168.1.15:9621`
- `compose/docker-compose.integration*.yml:1` — `192.168.1.10` в public compose comments
- `scripts/launch/start_pn95_2xa5000_nightly_dcacdf9a.sh:30-34` — default host paths tied to `genesis-vllm-patches-v11`, `Genesis_Project/vllm_engine`, `/nfs/genesis/models`
- `tests/probes/streaming_thinking_probe.py:45-49` — default endpoint/API key
- `tests/soak/cliff2_multiturn_soak.py:52-57` — default endpoint + `sander@192.168.1.10`
- `tests/soak/pn40_soak_1000.py:21-23` — default endpoint/API key

Проблема:

Часть значений является допустимыми operator defaults, но в public surface лучше иметь `localhost`, `<server-ip>`, `${SNDR_ENDPOINT}`, `${SNDR_API_KEY}` или обязательную env-переменную. Особенно плохо выглядит `OPENAI_API_KEY=genesis-gw-...`: даже если это тестовый ключ, security scan сейчас его не ловит.

Рекомендованная правка:

```yaml
- OPENAI_API_KEY=${OPENAI_API_KEY:?set OPENAI_API_KEY}
- OLLAMA_BASE_URL=${OLLAMA_BASE_URL:-http://localhost:11434}
```

Для probes/soak:

```python
ENDPOINT = os.environ.get("GENESIS_ENDPOINT", "http://localhost:8000/v1/chat/completions")
API_KEY = os.environ.get("GENESIS_API_KEY", "genesis-local")
SSH_HOST = os.environ.get("GENESIS_SSH_HOST", "")
```

И если `SSH_HOST` пустой, выключать SSH telemetry вместо `sander@192.168.1.10`.

Приоритет: **P1**.

---

### P1-6. `tools/genesis_vllm_plugin` код частично обновлен, README остался legacy

Файлы:

- `tools/genesis_vllm_plugin/genesis_v7/__init__.py:77` — код уже импортирует `vllm.sndr_core.apply.orchestrator`
- `tools/genesis_vllm_plugin/README.md:3` — README говорит про `vllm._genesis/`
- `tools/genesis_vllm_plugin/README.md:33` — README говорит `Imports vllm._genesis.patches.apply_all`

Проблема:

Код shim уже направлен в `sndr_core`, а документация говорит обратное. Это не ломает runtime, но ломает понимание и onboarding.

Что сделать:

- переименовать описание в `legacy vLLM plugin shim for sndr_core`;
- заменить `_genesis` на `vllm.sndr_core.apply.orchestrator`;
- явно указать, что новый предпочтительный путь — package entrypoint из `vllm/sndr_core/plugin.py`, а этот tool оставлен как compatibility shim.

Приоритет: **P1/P2**.

## 4. Мусорные/generated файлы

Текущий счетчик:

```text
garbage_total 1271
vllm/sndr_core/ 706
tests/          448
scripts/         63
tools/           17
docs/            15
benchmarks/      10
plugins/          6
assets/           2
repo root         3
```

Классы мусора:

- `__pycache__/`
- `*.pyc`
- `.pytest_cache/`
- `.DS_Store`

Важно: **не использовать** `git clean -fdX` вслепую. Проверка `git clean -ndX` показывает, что оно удалит не только cache, но и важные ignored артефакты:

```text
Would remove docs/_internal/
Would remove evidence/
Would remove internal/
Would remove pyproject-engine.toml
Would remove vllm/sndr_core/schemas/patch_entry.schema.json
Would remove vllm/sndr_core/configs/moe_tuning/E=256,N=512,...
Would remove vllm/sndr_core/manifests/anchor_manifest.json
```

Безопасная точечная чистка:

```bash
find . -name '__pycache__' -type d -prune -exec rm -rf {} +
find . -name '*.pyc' -type f -delete
find . -name '.pytest_cache' -type d -prune -exec rm -rf {} +
find . -name '.DS_Store' -type f -delete
```

Перед этим лучше закрыть P0-2, чтобы важные JSON перестали быть ignored.

## 5. Zero-reference / unused candidates вне `sndr_core`

Метод: текстовый scan по tracked + untracked source files, excluding `docs/_internal`, `evidence`, `internal`, caches. Это не доказательство удаления, а список кандидатов на разбор.

Итого: `61` candidate.

### 5.1. Архивные bench/raw данные

Кандидаты:

- `benchmarks/2026-04-21_40420_cliff_analysis/raw/02_patch20_only_234cliff/nvidia-smi_post.csv`
- `benchmarks/2026-04-21_40420_cliff_analysis/raw/02_patch20_only_234cliff/nvidia-smi_pre.csv`
- `benchmarks/2026-04-21_40420_cliff_analysis/raw/03_patch20_util085_seqs2/genesis_bench_exp_A_probe_250to260_20260421_200459.json`
- `benchmarks/2026-04-21_40420_cliff_analysis/raw/03_patch20_util085_seqs2/nvidia-smi_post.csv`
- `benchmarks/2026-04-21_40420_cliff_analysis/raw/03_patch20_util085_seqs2/nvidia-smi_pre.csv`
- `benchmarks/2026-04-21_40420_cliff_analysis/raw/03_patch20_util085_seqs2/startup_info.txt`
- `benchmarks/2026-04-21_40420_cliff_analysis/raw/04_patch20_util0905_seqs1/nvidia-smi_post.csv`
- `benchmarks/2026-04-21_40420_cliff_analysis/raw/04_patch20_util0905_seqs1/nvidia-smi_pre.csv`
- `benchmarks/2026-04-21_40420_cliff_analysis/raw/04_patch20_util0905_seqs1/startup_info.txt`
- `benchmarks/2026-04-21_40420_cliff_analysis/raw/05_patch22_util085/genesis_bench_p22_cliff_228to260_util085_20260421_215807.json`
- `benchmarks/2026-04-21_40420_cliff_analysis/raw/05_patch22_util085/harness_32_33_GO.json`
- `benchmarks/2026-04-21_40420_cliff_analysis/raw/06_patch22_util0905_TRUTH/genesis_bench_p22_util0905_TRUTH_228to260_20260421_220314.json`
- `benchmarks/archive_v5_v6/bench_v5.10_20260419.json`
- `benchmarks/archive_v5_v6/harness_baseline_fp8_v5.7.json`
- `benchmarks/archive_v5_v6/harness_v5.10.json`
- `benchmarks/archive_v5_v6/longbench_awq.jsonl`
- `benchmarks/archive_v5_v6/longbench_fp8.jsonl`
- `benchmarks/archive_v5_v6/longbench_gptq.jsonl`
- `benchmarks/archive_v5_v6/sweep_awq.jsonl`
- `benchmarks/archive_v5_v6/sweep_fp8.jsonl`
- `benchmarks/archive_v5_v6/sweep_gptq.jsonl`
- `benchmarks/v7_10_validation_20260424/gemma4_26b_moe/FAILURE_NOTE.md`
- `benchmarks/v7_10_validation_20260424/gemma4_26b_moe/boot_FAILED.log`
- `benchmarks/v7_10_validation_20260424/qwen3_next_awq/real_256k_bullseye.jsonl`
- `benchmarks/v7_10_validation_20260424/qwen3_next_fp8/real_256k_bullseye.jsonl`
- `benchmarks/v7_10_validation_20260424/qwen3_next_fp8/real_256k_sweep.jsonl`

Рекомендация:

- оставить в public только aggregated markdown + selected benchmark data;
- raw logs/CSV/JSON перенести в `docs/_internal/bench_results` или release artifact storage;
- если raw нужен публично, добавить README index с назначением каждого файла.

### 5.2. Reference docs без входящих ссылок

- `docs/reference/BOTS_SETUP.md`
- `docs/reference/DEFERRED_P50_DEPLOY.md`
- `docs/reference/DEFERRED_P87_PR40924.md`
- `docs/reference/LONG_CONTEXT_VALIDATION_20260427.md`
- `docs/reference/V758_P75_SUFFIX_DECODING_DEPLOY_VARIANT.md`
- `docs/upstream/PRODUCTION_ROADMAP_EXPANDED_DELTA_AUDIT_2026-05-08.md`
- `docs/upstream/VLLM_PR_DECISION.md`

Рекомендация:

- добавить `docs/reference/README.md` index;
- либо перенести устаревшее в `docs/_internal/audits`;
- public docs должны быть навигационными, не кладбищем старых решений.

### 5.3. Upstream reference code/diffs без входящих ссылок

- `docs/upstream_refs/dev134_chunk_scaled_dot_kkt.py`
- `docs/upstream_refs/dev134_linear_attn.py`
- `docs/upstream_refs/dev134_triton_turboquant_decode.py`
- `docs/upstream_refs/dev134_turboquant_attn.py`
- `docs/upstream_refs/pr_40792_k8v4_gqa_grouping.diff`
- `docs/upstream_refs/pr_40798_workspace_manager.diff`

Рекомендация:

- оставить только через `docs/upstream_refs/README.md` с mapping: upstream PR → local patch → reason kept;
- если mapping не нужен, перенести в internal research.

### 5.4. Scripts/tools без входящих ссылок

- `scripts/genesis_longbench_runner.py`
- `scripts/server_validate.sh`
- `scripts/stress/genesis_stress_v1.py`
- `tools/memory_observability.sh`
- `tools/phase_final_extended_stress.sh`

Рекомендация:

- если это active operator tools — добавить в `docs/COMMANDS.md`, `README.md` или `Makefile`;
- если это разовые harnesses — перенести в `scripts/_archive/` или `docs/_internal/runs`;
- `tools/phase_final_extended_stress.sh:11` содержит незавершенный пункт `TODO — requires container restarts`, то есть это не production-ready tool.

### 5.5. Archived launch scripts

Кандидаты:

- `scripts/launch/_archive/historical/start_ngram_p77adaptive.sh`
- `scripts/launch/_archive/historical/start_no_spec_async.sh`
- `scripts/launch/_archive/historical/start_v747_p82.sh`
- `scripts/launch/_archive/historical/start_v755_mamba_align.sh`
- `scripts/launch/_archive/historical/start_v756_align_no_spec.sh`
- `scripts/launch/_archive/historical/start_v757_align_mtp_no_p5.sh`
- `scripts/launch/_archive/research/start_v786_arm_a_baseline_refresh.sh`
- `scripts/launch/_archive/research/start_v786_arm_b_prefix_cache_on.sh`
- `scripts/launch/_archive/research/start_v786_arm_c_p83_p85.sh`
- `scripts/launch/_archive/research/start_v786_arm_d_p83_p84_p85.sh`
- `scripts/launch/_archive/research/start_v786_arm_e_p40_enable.sh`
- `scripts/launch/_archive/research/start_v786_template.sh`
- `scripts/launch/_archive/research/start_v788_int8_27b_pn8_pn9.sh`
- `scripts/launch/_archive/research/start_v789_35b_pn8_only.sh`
- `scripts/launch/_archive/research/start_v791c_27b_util088.sh`
- `scripts/launch/_archive/superseded_by_model_configs/start_27b_int4_TQ_k8v4_root.sh`
- `scripts/launch/_archive/superseded_by_model_configs/start_35b_fp8_PROD_root.sh`

Проблема:

Много архивных scripts содержит старые `/home/sander/...`, `_genesis`, личные cache paths. Поскольку они уже в `_archive`, это не P0, но они продолжают засорять search results и путают аудит.

Рекомендация:

- оставить только если есть `README.md` с историческим назначением;
- иначе удалить или перенести в private/internal history;
- active launch должен идти через `sndr launch` и model configs.

## 6. Что исправлять в каком порядке

1. **P0:** разобраться с `tests/` untracked: stage public tests или вынести лишнее.
2. **P0:** поправить `.gitignore` и schema duplication; добавить gate на schema sync.
3. **P1:** мигрировать/убрать legacy compose files из active `compose/`.
4. **P1:** обновить `scripts/git/pre-commit` на `sndr_core`.
5. **P1:** переписать `tools/check_upstream_drift.py` под `iter_patch_specs()`.
6. **P1:** обновить `scripts/moe_lookup_helper.sh` на `sndr_core/configs/moe_tuning`.
7. **P1:** убрать hardcoded private IP/key/path из public compose/probes/soak.
8. **P2:** создать explicit archive policy для `benchmarks/`, `docs/upstream_refs`, `scripts/launch/_archive`.
9. **P2:** почистить generated cache только точечными find-командами.
10. **P2:** добавить cleanup gate: `audit-no-generated-cache`, `audit-no-untracked-public-tests`, `audit-schema-sync`, `audit-no-legacy-compose`.

## 7. Минимальный acceptance checklist после исправлений

```bash
git status --short --untracked-files=all
git ls-files --others --exclude-standard tests
git check-ignore -v vllm/sndr_core/schemas/patch_entry.schema.json \
  vllm/sndr_core/manifests/anchor_manifest.json \
  vllm/sndr_core/configs/moe_tuning/*.json
cmp -s schemas/patch_entry.schema.json vllm/sndr_core/schemas/patch_entry.schema.json
rg -n "vllm\\._genesis|vllm/_genesis|genesis_vllm_plugin|patch_genesis_unified" \
  compose scripts tools docs README.md --glob '!docs/_internal/**' --glob '!scripts/launch/_archive/**'
find . -name '__pycache__' -o -name '*.pyc' -o -name '.pytest_cache' -o -name '.DS_Store'
make audit
make evidence
pytest --collect-only -q tests
```

Целевое состояние перед релизом:

- `make evidence`: `40/40` green;
- no untracked public tests;
- no ignored source JSON artifacts;
- no active `_genesis` references outside compatibility notes and explicit archives;
- no generated cache in working tree;
- active compose examples run through `sndr_core`/`sndr launch`, not legacy monolith.
