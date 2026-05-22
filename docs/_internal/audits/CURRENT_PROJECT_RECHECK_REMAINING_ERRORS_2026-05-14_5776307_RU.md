# Повторная точная проверка после исправлений: оставшиеся ошибки

Дата проверки: 2026-05-14 05:57-06:07 EEST  
Ветка: `dev`  
HEAD: `5776307` (`Release-tier audit closure: legacy imports, README, community gate, compose paths`)  
Scope: локальное состояние проекта `/Users/sander/Documents/Visual Studio Code/genesis-vllm-patches`

## Резюме

Исправления сработали. Большинство прошлых блокеров закрыто:

- `legacy-import gate` теперь чистый.
- `community validate` подключен и проходит.
- AppleDouble `._*.py` файлы удалены: Python compile scan чистый.
- active compose hardcoded-path gate проходит.
- README counters синхронизированы.
- `patches prove --dead-detect` теперь `151/151`, `dead=0`.
- `shadow --strict` чистый.
- `release-check` чистый.
- `launch --check-deps` корректно возвращает `exit 2` при host blockers.

Оставшийся release blocker один: `make evidence` падает из-за `audit`, а `audit` падает на `audit-public-paths`.

Дополнительно найден отдельный unit-test drift: `tests/unit/test_phase9_v1_freeze.py` все еще ожидает 11 V1 presets, хотя `scripts/audit_no_new_v1.py` уже содержит 12-entry baseline.

Текущая оценка production readiness: **90/100**.

## Проверки и результаты

| Проверка | Результат | Детали |
|---|---:|---|
| `python3 -m vllm.sndr_core.compat.cli self-test --json` | PASS | `8/8`, `151` registry entries clean |
| `python3 -m vllm.sndr_core.apply.shadow --strict` | PASS | no unexpected divergence |
| `python3 -m vllm.sndr_core.cli patches doctor --json` | PASS | registry `151`, validation `[]`, apply_module `138/151` |
| `python3 -m vllm.sndr_core.cli patches prove --dead-detect --json` | PASS | `151/151`, `dead=0`, coverage `100%` |
| `make audit-configs` | PASS | `11/11` presets compose |
| Python compile scan | PASS | `1246` `.py` files, `0` compile errors |
| Shell syntax scan | PASS | `72` `.sh` files, `0` syntax errors |
| Project JSON/TOML/YAML parse | PASS | `6` JSON, `1` TOML, `51` YAML, `3` text dependency files |
| `python3 scripts/check_doc_sync.py --strict` | PASS | docs claim `151` consistently |
| `python3 scripts/audit_no_new_v1.py` | PASS | `12` current files, `12` frozen baseline |
| `python3 scripts/check_no_legacy_imports.py` | PASS | `988` files scanned, clean |
| `make audit-community` | PASS | `manifests=0`, `errors=0`, `warnings=0` |
| `make audit-all-referents` | PASS | `443` Python files scanned |
| `make audit-readme-counters` | PASS | patches `151`, families `21`, profiles `11` |
| `make audit-no-hardcoded-paths` | PASS | `50 clean / 1 exempt / 0 with violations` |
| `make audit-no-stub` | PASS | no unresolved stubs in `vllm/sndr_core/**/*.py` |
| `make audit-engine-boundary` | PASS | no unguarded `vllm.sndr_engine` imports |
| `make audit-release-check` | PASS | `151/151`, release policy satisfied |
| `make audit` | FAIL | `audit-public-paths` detects private paths/IPs |
| `make evidence` | FAIL | `1` gating gate failed: `audit` |
| `python3 scripts/security_scan.py` | FAIL | `36` operator-path hits |
| Targeted pytest subset | FAIL | `1 failed, 140 passed`: stale V1 baseline-count unit test |

## P0. Единственный release blocker: `audit-public-paths`

Статус: блокирует `make audit`, а через него блокирует `make evidence`.

Makefile:

```text
Makefile:71-89
```

Текущий gate:

```make
audit-public-paths:
	@bad=$$(rg -n "192\.168\.1\.10|/home/sander|sander@|User=sander" \
	    README.md docs/ scripts/ tools/ benchmarks/ vllm/ \
	    --glob '!docs/_internal/**' \
	    --glob '!**/_archive/**' \
	    --glob '!**/_internal/**' \
	    --glob '!tests/integration/baselines/**' \
	    2>/dev/null || true); \
```

Фактический результат:

```text
✗ Private paths found in public files.
Replace LAN IPs with 127.0.0.1 / <your-host>,
/home/sander with $HOME / <your-home>,
sander@ with <user>@<host>.
```

### Почему это важно

Сейчас portable/public release surface все еще содержит:

- личный домашний путь `/home/sander`;
- LAN IP `192.168.1.10`;
- SSH identity `sander@...`;
- исторические server-specific paths в `vllm/_genesis`, scripts и comments.

Даже если часть этих файлов legacy/historical, текущий `audit-public-paths` сканирует их как public files. Значит либо файлы надо очистить, либо gate должен явно отделять public surface от legacy/internal archive.

### Полный список `audit-public-paths` hits

```text
scripts/audit_no_hardcoded_paths.py:7:filesystem paths like `/home/sander/...` or `/Users/sander/...`.
scripts/stress/genesis_stress_v1.py:13:defaults like `192.168.1.10` were removed (G-010 audit fix 2026-05-02);
scripts/security_scan.py:8:  2. No `/home/sander` / `/Users/sander` in tracked code or public docs.
scripts/security_scan.py:101:    """No `/home/sander` or `/Users/sander` in tracked code or public docs."""
vllm/_genesis/patches/apply_all.py:1793:    Replaces uvicorn's bare `INFO: 192.168.1.10 - "POST /v1/chat/completions" 200 OK`
vllm/_genesis/patches/apply_all.py:1795:        [Genesis-API] 200  POST /v1/chat/completions  34ms  prompt=46t  completion=400t  tools=1  client=192.168.1.10
vllm/_genesis/model_configs/builtin/a5000-2x-35b-prod.yaml:120:    - /home/sander/.cache/huggingface:/root/.cache/huggingface:ro
vllm/_genesis/model_configs/builtin/a5000-2x-35b-prod.yaml:121:    - /home/sander/Genesis_Project/vllm_engine/triton-cache-mtp-test:/root/.triton/cache
vllm/_genesis/model_configs/builtin/a5000-2x-35b-prod.yaml:122:    - /home/sander/Genesis_Project/vllm_engine/compile-cache-prod-mirror-test:/root/.cache/vllm/torch_compile_cache
vllm/_genesis/model_configs/builtin/a5000-2x-35b-prod.yaml:123:    - /home/sander/genesis-vllm-patches/vllm/_genesis:/usr/local/lib/python3.12/dist-packages/vllm/_genesis:ro
vllm/_genesis/model_configs/builtin/a5000-2x-35b-prod.yaml:124:    - /home/sander/genesis-vllm-patches/tools/genesis_vllm_plugin:/plugin:ro
vllm/_genesis/model_configs/builtin/a5000-1x-27b-int4-balanced.yaml:101:    - /home/sander/.cache/huggingface:/root/.cache/huggingface:ro
vllm/_genesis/model_configs/builtin/a5000-1x-27b-int4-balanced.yaml:102:    - /home/sander/Genesis_Project/vllm_engine/triton-cache-27b-1x:/root/.triton/cache
vllm/_genesis/model_configs/builtin/a5000-1x-27b-int4-balanced.yaml:103:    - /home/sander/Genesis_Project/vllm_engine/compile-cache-27b-1x:/root/.cache/vllm/torch_compile_cache
vllm/_genesis/model_configs/builtin/a5000-1x-27b-int4-balanced.yaml:104:    - /home/sander/genesis-vllm-patches/vllm/_genesis:/usr/local/lib/python3.12/dist-packages/vllm/_genesis:ro
vllm/_genesis/model_configs/builtin/a5000-1x-27b-int4-balanced.yaml:105:    - /home/sander/genesis-vllm-patches/tools/genesis_vllm_plugin:/plugin:ro
vllm/_genesis/model_configs/builtin/a5000-2x-27b-int4-balanced.yaml:110:    - /home/sander/.cache/huggingface:/root/.cache/huggingface:ro
vllm/_genesis/model_configs/builtin/a5000-2x-27b-int4-balanced.yaml:111:    - /home/sander/Genesis_Project/vllm_engine/triton-cache-int4-mtp:/root/.triton/cache
vllm/_genesis/model_configs/builtin/a5000-2x-27b-int4-balanced.yaml:112:    - /home/sander/Genesis_Project/vllm_engine/compile-cache-int4-mtp:/root/.cache/vllm/torch_compile_cache
vllm/_genesis/model_configs/builtin/a5000-2x-27b-int4-balanced.yaml:113:    - /home/sander/genesis-vllm-patches/vllm/_genesis:/usr/local/lib/python3.12/dist-packages/vllm/_genesis:ro
vllm/_genesis/CHANGELOG.md:571:  start scripts updated to `/home/sander/genesis-vllm-patches/tools/genesis_vllm_plugin`.
vllm/_genesis/CHANGELOG.md:1665:`/home/sander/launch_scripts/current/start_v759_320k_prod.sh`. Old v7.52
vllm/_genesis/CHANGELOG.md:1813:  Synced to server `/home/sander/genesis-vllm-patches/`. AST OK +
vllm/_genesis/CHANGELOG.md:2074:- Server-side bench tools (`/home/sander/Genesis_Project/vllm_engine/`)
vllm/_genesis/CHANGELOG.md:2144:- Server-side backup `/home/sander/genesis-backups/v7.50-stable-20260427_0202/`
scripts/audit_public_docs.py:10:  D-3  No `/home/sander` or `/Users/sander` operator paths in public docs.
scripts/bench_suffix_sweep.py:84:    /home/sander/start_v742_full_8k_suffix.sh, replaces speculative-config."""
scripts/bench_suffix_sweep.py:85:    base = Path("/home/sander/start_v742_full_8k_suffix.sh").read_text()
scripts/bench_suffix_sweep.py:231:    out_dir = Path(f"/home/sander/Genesis_Project/vllm_engine/suffix_sweep_{args.label}_{datetime.now().strftime('%H%M%S')}")
vllm/_genesis/configs/moe_tuning/README.md:71:  VM 100 (192.168.1.10).
vllm/_genesis/cache/response_cache.py:82:_ENV_REDIS_URL = "GENESIS_P41_REDIS_URL"      # e.g. "redis://192.168.1.10:6379/1"
scripts/validate_integration.sh:21:#   HOST=192.168.1.10 ./scripts/validate_integration.sh    # remote host
scripts/launch/nsight_profile_capture.sh:9:# Output: /home/sander/Genesis_Project/profiles/<run_name>.nsys-rep
scripts/launch/nsight_profile_capture.sh:15:HOST="${HOST:-192.168.1.10}"
scripts/launch/nsight_profile_capture.sh:17:OUT_DIR="/home/sander/Genesis_Project/profiles"
scripts/launch/nsight_profile_capture.sh:19:ssh sander@${HOST} "
scripts/launch/nsight_profile_capture.sh:47:echo "Then run: ssh sander@${HOST} \"nsys stats /home/sander/Genesis_Project/profiles/${RUN_NAME}.nsys-rep | head -50\""
scripts/launch/snapshot_pre_arm.sh:20:ssh sander@192.168.1.10 "
scripts/launch/start_pn95_2xa5000_nightly_dcacdf9a.sh:20:# Verified on: 2× NVIDIA RTX A5000 24 GB, host 192.168.1.10.
scripts/launch/start_pn95_2xa5000_nightly_dcacdf9a.sh:37:mkdir -p /home/sander/Genesis_Project/vllm_engine/compile-cache-pn95-2x \
scripts/launch/start_pn95_2xa5000_nightly_dcacdf9a.sh:38:         /home/sander/Genesis_Project/vllm_engine/triton-cache-pn95-2x
scripts/launch/start_pn95_2xa5000_nightly_dcacdf9a.sh:142:  -v /home/sander/genesis-vllm-patches-v11/vllm/sndr_core:/usr/local/lib/python3.12/dist-packages/vllm/sndr_core \
scripts/launch/start_pn95_2xa5000_nightly_dcacdf9a.sh:144:  -v /home/sander/.cache/huggingface:/root/.cache/huggingface \
scripts/launch/start_pn95_2xa5000_nightly_dcacdf9a.sh:145:  -v /home/sander/Genesis_Project/vllm_engine/compile-cache-pn95-2x:/root/.cache/vllm/torch_compile_cache \
scripts/launch/start_pn95_2xa5000_nightly_dcacdf9a.sh:146:  -v /home/sander/Genesis_Project/vllm_engine/triton-cache-pn95-2x:/root/.triton/cache \
scripts/launch/start_pn95_2xa5000_nightly_dcacdf9a.sh:147:  -v /home/sander/.sndr/cache:/root/.sndr/cache \
scripts/probe_max_ctx.sh:9:#   ENDPOINT=http://192.168.1.10:8000 MODEL=qwen3.6-35b-a3b ./probe_max_ctx.sh
scripts/probe_max_ctx.sh:23:ENDPOINT="${ENDPOINT:-http://192.168.1.10:8000}"
scripts/verify-full.sh:19:#   ENDPOINT=http://192.168.1.10:8000 MODEL=qwen3.6-27b ./verify-full.sh
scripts/verify-full.sh:25:ENDPOINT="${ENDPOINT:-http://192.168.1.10:8000}"
scripts/verify-full.sh:29:SSH_HOST="${SSH_HOST:-sander@192.168.1.10}"
scripts/moe_lookup_helper.sh:41:SSH_HOST="${SSH_HOST:-sander@192.168.1.10}"
scripts/moe_lookup_helper.sh:126:     -v "/home/sander/genesis-vllm-patches/$OUT_PATH:/usr/local/lib/python3.12/dist-packages/vllm/model_executor/layers/fused_moe/configs/$FNAME:ro" \\
vllm/_genesis/wiring/middleware/patch_N65_access_log.py:6:    INFO: 192.168.1.10:45116 - "POST /v1/chat/completions HTTP/1.1" 200 OK
vllm/_genesis/wiring/middleware/patch_N65_access_log.py:10:    [Genesis-API] 200  POST /v1/chat/completions    34ms  prompt=46t  completion=400t  stream=N  tools=N  client=192.168.1.10
vllm/_genesis/wiring/middleware/patch_N65_access_log.py:11:    [Genesis-API] 401  GET  /v1/models              <1ms  client=192.168.1.10
vllm/_genesis/wiring/middleware/patch_N65_access_log.py:255:    PN65 was DUPLICATING uvicorn's bare `INFO: 192.168.1.10 - "GET /v1/models" 401`
vllm/_genesis/dispatcher.py:1933:        "credit": "Genesis-original 2026-05-05 (Sander request 'по апи лог невзрачный надо тоже проработать'). Replaces uvicorn's bare `INFO: 192.168.1.10:45116 - GET /v1/models 401 Unauthorized` with `[Genesis-API] 200  POST /v1/chat/completions  34ms  prompt=46t  completion=400t  tools=1  client=192.168.1.10`. Suppresses /health polling by default (GENESIS_PN65_LOG_HEALTH=1 to include). Status-aware level (2xx INFO / 4xx WARN / 5xx ERROR + exception type).",
vllm/_genesis/tests/test_pn65_access_log.py:99:            "GET", "/v1/models", 401, 0.0005, "192.168.1.10", {}
vllm/_genesis/tests/test_pn65_access_log.py:106:        assert "client=192.168.1.10" in line
vllm/_genesis/tests/test_pn65_access_log.py:205:                           '192.168.1.10 - "GET /v1/models" 401')
vllm/_genesis/tests/test_pn65_access_log.py:348:            uv.info('192.168.1.10:45116 - "GET /v1/models HTTP/1.1" 401')
```

### Что исправлять

Рекомендуемый вариант:

1. В active scripts заменить defaults:
   - `192.168.1.10` → `127.0.0.1` или `<your-host>`;
   - `sander@192.168.1.10` → `${SSH_HOST:-<user>@<host>}`;
   - `/home/sander/...` → `${HOME}/...`, `${SNDR_CACHE_ROOT}`, `${SNDR_PROFILE_DIR}`, `${SNDR_REPO_ROOT}`.
2. Для `vllm/_genesis/**` принять одно решение:
   - либо полностью исключить legacy `_genesis` из public release scan, если это исторический слой;
   - либо очистить legacy файлы от приватных путей, если они остаются в public package.
3. Для audit scripts, которые описывают forbidden patterns, использовать inline allow marker или вынести literal patterns в escaped/docstring form, если gate должен сканировать их самих.

Acceptance:

```bash
make audit
make evidence
python3 scripts/security_scan.py
```

## P1. Security scan: 36 operator-path hits

Статус: informational gate в `make evidence`, но release hygiene все равно красный.

Команда:

```bash
python3 scripts/security_scan.py --json
```

Результат:

```text
operator_paths: 36
private_ips: clean
private_keys: clean
env_files: clean
aws_keys: clean
```

Важно: `security_scan.py` сейчас проверяет только `/home/sander` и `/Users/sander` для operator paths. Поэтому он не видит часть LAN IP/SSH hits, которые видит `audit-public-paths`. Исправление `audit-public-paths` почти наверняка уменьшит и security hits, но это две разные политики.

36 security hits совпадают с path-частью списка выше:

- `compose/docker-compose.integration*.yml:9`;
- `scripts/bench_suffix_sweep.py:84,85,231`;
- `scripts/launch/nsight_profile_capture.sh:9,17,47`;
- `scripts/launch/start_pn95_2xa5000_nightly_dcacdf9a.sh:37,38,142,144,145,146,147`;
- `scripts/moe_lookup_helper.sh:126`;
- `vllm/_genesis/CHANGELOG.md:571,1665,1813,2074,2144`;
- `vllm/_genesis/model_configs/builtin/*.yaml` listed in the P0 section.

Acceptance:

```bash
python3 scripts/security_scan.py
```

## P1. Unit-test drift: V1 freeze test still expects 11 entries

Статус: не блокирует `make evidence`, но блокирует targeted unit subset.

Команда:

```bash
pytest -q tests/unit/test_phase9_v1_freeze.py
```

Результат:

```text
1 failed, 20 passed
FAILED tests/unit/test_phase9_v1_freeze.py::TestAuditNoNewV1::test_baseline_count_is_eleven
E   AssertionError: assert 12 == 11
```

Файл:

```text
tests/unit/test_phase9_v1_freeze.py:153-157
```

Текущий тест:

```python
class TestAuditNoNewV1:
    def test_baseline_count_is_eleven(self):
        mod = _import_script("audit_no_new_v1")
        # Phase 9 freeze captured 11 V1 monolithic presets.
        assert len(mod.FROZEN_V1_BASELINE) == 11
```

Фактическое состояние:

```text
scripts/audit_no_new_v1.py:35-42
```

```python
# Bumps:
#   2026-05-14 +1 — `a5000-1x-tier-aware-pn95.yaml` added as a Wave 9
...
FROZEN_V1_BASELINE: frozenset[str] = frozenset({
```

`FROZEN_V1_BASELINE` содержит 12 entries, и сам audit script это подтверждает:

```text
audit-no-new-v1: 12 V1 file(s) currently present
                 12 in frozen baseline
✓ V1 frozen — top-level builtin/*.yaml matches the 12-entry baseline
```

Проблема: production gate обновлен на 12, но unit-test остался на старом invariant `11`.

Что исправлять:

```python
def test_baseline_count_matches_current_freeze_policy(self):
    mod = _import_script("audit_no_new_v1")
    assert len(mod.FROZEN_V1_BASELINE) == 12
```

Лучше: убрать hardcoded count из теста и проверять комментарий/снимок через named constant, чтобы следующий freeze bump не ломал тест механически:

```python
def test_baseline_count_matches_documented_policy(self):
    mod = _import_script("audit_no_new_v1")
    assert len(mod.FROZEN_V1_BASELINE) == len(mod._current_v1_files())
```

Acceptance:

```bash
pytest -q tests/unit/test_phase9_v1_freeze.py
```

## P2. Local host dependency blockers

Статус: не ошибка проекта, но локальный host не готов к запуску GPU/Docker preset.

Команды:

```bash
python3 -m vllm.sndr_core.cli deps plan --config a5000-2x-35b-prod --json
python3 -m vllm.sndr_core.cli launch a5000-2x-35b-prod --preflight-only --check-deps
```

Результат:

```text
is_ready: false
n_blockers: 3
- Docker Engine: docker is not on PATH
- NVIDIA driver: nvidia-smi is not on PATH
- model directory missing: /models/Qwen3.6-35B-A3B-FP8
warning: vllm not in current Python; OK if running via Docker
```

Позитивный факт: `launch --check-deps` теперь возвращает `exit 2`, то есть false-pass исправлен.

## P2. Dirty state остается dev-only

Статус: не новая ошибка, но release-подготовка еще не завершена.

Снимок:

```text
git status --short
?? 407
total 407
```

Это accepted dev state, но не final release state. Перед публичным релизом нужно отдельно решить, какие файлы входят в tracked release, какие остаются internal/generated.

## Проверка упоминаний ИИ/сгенерированного кода

Проверял active public surface:

```bash
rg -n "\bAI\b|ИИ|искусствен|ChatGPT|Codex|Claude|LLM generated|generated by" \
  --glob '!docs/_internal/**' --glob '!scripts/launch/_archive/**' \
  --glob '!**/_archive/**' --glob '!vllm/_genesis/**' \
  vllm/sndr_core scripts tools compose README.md docs
```

Критичных self-references вроде "сделано ИИ" в production code не найдено. Найдены нормальные предметные упоминания:

- `Claude Code`, `OpenCode`, `Cline` как target clients/tool agents;
- `OpenAI Node SDK`, `Vercel AI SDK` как compatibility targets;
- `Auto-generated by scripts/...` для generated docs;
- model names containing `Claude`.

Исправлять это не требуется, если нет отдельного branding-policy запрета на упоминания external tool-agent clients.

## Что уже закрыто после твоих исправлений

| Старый блокер | Текущее состояние |
|---|---|
| `legacy imports: 20` | закрыто, gate clean |
| missing `community validate` | закрыто, CLI route работает |
| AppleDouble `._*.py` | закрыто, compile scan clean |
| active compose hardcoded paths | закрыто, `audit-no-hardcoded-paths` pass |
| README counter drift | закрыто, `audit-readme-counters` pass |
| `patches prove` dead=15 | закрыто, `151/151`, `dead=0` |
| `shadow --strict` divergence | закрыто, clean |
| release-check dead bucket | закрыто, `151/151` |
| launcher dependency false-pass | закрыто, command returns `exit 2` on blockers |

## Минимальный план до green release

1. Очистить `audit-public-paths` hits.
2. Очистить или allowlist-оформить `security_scan.py` operator-path hits.
3. Исправить unit-test `test_baseline_count_is_eleven`.
4. Повторить:

```bash
make audit
make evidence
python3 scripts/security_scan.py
pytest -q tests/unit/test_phase9_v1_freeze.py
```

Если эти четыре команды зеленые, текущий локальный проект будет близок к release-ready состоянию на уровне статических gates. Серверные GPU smoke/bench и реальный Docker runtime остаются отдельной проверкой.

