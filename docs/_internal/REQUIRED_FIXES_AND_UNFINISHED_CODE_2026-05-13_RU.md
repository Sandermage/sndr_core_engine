# Genesis / SNDR: список обязательных исправлений и незавершенного кода

**Дата проверки:** 2026-05-13  
**Локальный HEAD:** `59c5a88`  
**Ветка:** `dev`  
**Основа:** `docs/_internal/CONSOLIDATED_ROADMAP_PRODUCTION_DASHBOARD_2026-05-13_RU.html`, `docs/_internal/CONSOLIDATED_ROADMAP_2026-05-13_RU.md`, живые проверки локального дерева.  
**Граница работы:** код проекта не менялся; создан только этот audit/report файл.

---

## 1. Короткий вывод

Проект уже имеет сильное ядро: registry на 136 патчей, V2 config composition, proof-chain, dirty-state policy, engine-boundary gate, no-stub gate и базовые syntax checks проходят. Но для production/public release проект сейчас **не готов**. Основные причины:

1. `make evidence` блокируется gating-аудитом `audit-public-paths`: в публичных файлах остались LAN IP, `/home/sander`, `sander@...`.
2. CLI contract сломан: `sndr config list --json` фактически печатает human table, а не JSON.
3. Launcher/preflight contract неполный: `prod-35b --preflight-only` падает на `${models_dir}` до нормального preflight-отчета.
4. `sndr memory explain` дает опасно оптимистичный `SAFE`, хотя веса и KV-cache оценены как `0`.
5. Security/license слой еще dev-only: trust anchor помечен как development-only, `audit-security` показывает 188 нарушений.
6. Dirty state большой и release-непригодный без freeze: много untracked/modified/deleted, включая важные `vllm/sndr_core/*`, tests, scripts, configs.
7. Patch migration не полностью закончена: 13 patch specs без `apply_module`; часть из них production-blocked/review-required.

---

## 2. Проверки, которые были выполнены

| Проверка | Результат | Вывод |
|---|---:|---|
| `python3 -m vllm.sndr_core.compat.cli self-test --json` | PASS 8/8 | Базовая compat-схема и registry живы. |
| `python3 -m vllm.sndr_core.apply.shadow --strict` | PASS | Нет unexpected divergence, но есть 13 specs без `apply_module`. |
| `make audit-configs` | PASS | 11 presets композятся. |
| `python3 -m vllm.sndr_core.cli patches prove --dead-detect --json` | PASS | 136/136 static-proven, dead=0. |
| Python AST parse по `vllm/sndr_core`, `scripts`, `tools`, `tests` | PASS | 826 `.py`, syntax errors 0. |
| `bash -n` по `scripts/*.sh`, `tools/*.sh` | PASS | 66 shell-файлов синтаксически валидны. |
| JSON/TOML/YAML parse | 1 error вне release scope | Ошибка только в `.history/.claude/settings...json`; проектные configs parse-clean. |
| `make audit-dirty-state-dev` | PASS | Dev policy принимает 833 dirty entries; для release это не означает готовность. |
| `make evidence` | FAIL | 1 gating fail: `audit`; informational fail: `audit-security`. |
| `python3 -m vllm.sndr_core.cli config list --json` | FAIL по контракту | Возвращает таблицу вместо JSON. |
| `python3 -m vllm.sndr_core.cli launch prod-35b --preflight-only` | FAIL | `unknown variable 'models_dir'`. |
| `python3 -m vllm.sndr_core.cli memory explain prod-35b --json` | Логически FAIL | Возвращает `SAFE` при low-confidence weights/KV=0. |

---

## 3. P0: release blockers, которые надо исправить первыми

### P0.1. Public release audit падает на приватных путях и LAN/IP

**Команда:** `make evidence`  
**Симптом:** `RELEASE BLOCKED — 1 gating gate(s) failed`  
**Конкретный gate:** `audit` → внутри `audit-public-paths`.

`make audit` показал реальные срабатывания:

| Файл | Проблема |
|---|---|
| `tools/long_ctx_smoke.sh:9` | пример `HOST=http://192.168.1.10:8101` |
| `benchmarks/harness/_common.py:60` | default endpoint `http://192.168.1.10:8000/v1` |
| `benchmarks/harness/__init__.py:6` | docstring с `192.168.1.10:8000` |
| `benchmarks/harness/README.md:9,33` | пример export / JSON endpoint с LAN IP |
| `benchmarks/harness/cuda_graph_recapture.py:19-20` | пример endpoint/metrics-url с LAN IP |
| `benchmarks/harness/long_context_oom.py:17` | пример endpoint с LAN IP |
| `benchmarks/harness/gsm8k_regression.py:17` | пример endpoint с LAN IP |
| `benchmarks/harness/quality_harness.py:19` | пример endpoint с LAN IP |
| `benchmarks/harness/tgs_decode.py:15` | пример endpoint с LAN IP |
| `tools/soak.sh:6` | пример host с LAN IP |
| `tools/audit_yaml_vs_runtime.sh:21` | пример `sander@192.168.1.10` |
| `docs/upstream/PRODUCTION_ROADMAP_2026-05-09.md` | много исторических примеров с `192.168.1.10`, `/home/sander`, `sander@host` |
| `docs/upstream/PRODUCTION_ROADMAP_EXPANDED_DELTA_AUDIT_2026-05-08.md` | hardcoded remote examples |
| `docs/upstream/DEEP_AUDIT_VLLM_NOONGHUNNA_2026-05-08_RU.md` | endpoint и `/home/sander` |
| `docs/reference/*` | исторические пути `/home/sander/...` |
| `vllm/sndr_core/compat/doctor.py:844` | docstring `sndr doctor --remote sander@host` |
| `scripts/audit_no_hardcoded_paths.py`, `scripts/security_scan.py`, `scripts/audit_public_docs.py` | сами scanners описывают запрещенные строки и попадают под соседний scanner |

**Почему это важно:** публичный релиз будет содержать личные пути/адреса, что одновременно портит переносимость, выглядит непрофессионально и создает security/privacy risk.

**Как исправить:**

1. В публичных scripts/bench examples заменить:
   - `192.168.1.10` → `127.0.0.1` или `<your-host>`.
   - `/home/sander` → `$HOME` или `<your-home>`.
   - `sander@...` → `<user>@<host>`.
2. Исторические audit-docs, которые нужны только внутренне, перенести из `docs/upstream/` и `docs/reference/` в `docs/_internal/archive/` либо явно пометить allowlist-правилом, если они не входят в public release tree.
3. Для scanner-файлов (`scripts/security_scan.py`, `scripts/audit_no_hardcoded_paths.py`) добавить точечный allowlist на строки, где scanner документирует запрещенные паттерны. Не надо глобально ослаблять regex.

**Acceptance:**

```bash
make audit
make evidence
```

Оба должны проходить. Если `audit-security` остается informational, нужен отдельный документированный false-positive allowlist.

---

### P0.2. `sndr config list --json` не JSON

**Файлы:**

- `vllm/sndr_core/cli/config.py:508-527`
- `vllm/sndr_core/compat/model_config_cli.py:53-113`

**Текущий код:**

```python
# vllm/sndr_core/cli/config.py:518-522
bridged_ns = argparse.Namespace(
    json=getattr(args, "json", False),
    include_tested=False,
)
rc = _cmd_list(bridged_ns)
```

```python
# vllm/sndr_core/compat/model_config_cli.py:53-56
def cmd_list(args) -> int:
    configs = load_all()
    if not configs:
        print("(no configs found in vllm/_genesis/model_configs/builtin/)")
        return 0
```

**Проблема:**

`config.py` передает `json=True`, но `compat.model_config_cli.cmd_list()` этот флаг вообще не обрабатывает и всегда печатает human-readable table. Поэтому:

```bash
python3 -m vllm.sndr_core.cli config list --json | python3 -m json.tool
```

падает с `JSONDecodeError`.

**Дополнительные ошибки рядом:**

- `model_config_cli.py:56` печатает устаревший путь `vllm/_genesis/model_configs/builtin/`.
- `model_config_cli.py:99` содержит `if tested and (include_tested or True):`, из-за `or True` tested/QA configs показываются всегда, даже если `include_tested=False`.
- `model_config_cli.py:107-110` продолжает показывать старые команды `genesis model-config ...`, хотя новый публичный слой должен вести к `sndr`.

**Что дописать:**

Вариант минимального исправления:

```python
def cmd_list(args) -> int:
    configs = load_all()
    include_tested = getattr(args, "include_tested", False)

    if getattr(args, "json", False):
        import json
        rows = []
        for key, cfg in sorted(configs.items()):
            rm = cfg.reference_metrics
            is_tested = cfg.lifecycle == "tested"
            if is_tested and not include_tested:
                continue
            rows.append({
                "key": key,
                "source": source_of(key) or "?",
                "title": cfg.title,
                "lifecycle": cfg.lifecycle,
                "tested": is_tested,
                "reference_metrics": None if rm is None else {
                    "long_gen_sustained_tps": rm.long_gen_sustained_tps,
                    "tool_call_score": rm.tool_call_score,
                    "stability_cv_pct": rm.stability_cv_pct,
                },
            })
        print(json.dumps({"configs": rows, "count": len(rows)}, ensure_ascii=False, indent=2))
        return 0
```

Параллельно убрать `or True` и заменить `_genesis`/`genesis model-config` в help text.

**Acceptance:**

```bash
python3 -m vllm.sndr_core.cli config list --json | python3 -m json.tool
python3 -m vllm.sndr_core.cli config list --json | rg "Genesis model configs" && exit 1 || true
```

---

### P0.3. `launch --preflight-only` падает на `${models_dir}` до полезного preflight-отчета

**Файлы:**

- `vllm/sndr_core/model_configs/builtin/a5000-2x-35b-prod.yaml:247-253`
- `vllm/sndr_core/model_configs/host.py:97-130`
- `vllm/sndr_core/model_configs/schema.py:143-191`
- `vllm/sndr_core/cli/launch.py:402-414`

**Текущий mount contract:**

```yaml
mounts:
  - ${models_dir}:/models:ro
  - ${hf_cache}:/root/.cache/huggingface:ro
  - ${cache_root}/triton-cache-mtp-test:/root/.triton/cache
  - ${cache_root}/compile-cache-prod-mirror-test:/root/.cache/vllm/torch_compile_cache
  - ${genesis_src}:/usr/local/lib/python3.12/dist-packages/vllm/sndr_core:ro
  - ${plugin_src}:/plugin:ro
```

**Симптом:**

```text
SchemaError: resolve_symbolic_mounts: unknown variable 'models_dir'
```

**Почему это важно:** оператор запускает preflight, чтобы узнать, что не настроено. Сейчас preflight падает на render stage и не дает структурированного списка действий.

**Корень проблемы:**

- `detect_paths()` добавляет `models_dir` только если найден существующий каталог из списка кандидатов.
- Нет env fallback вроде `SNDR_MODELS_DIR`.
- `--preflight-only` использует `strict_mounts=not opts.dry_run`, то есть ведет себя как live launch.

**Что дописать:**

1. В `host.py` добавить env-fallback:

```python
_ENV_PATHS = {
    "models_dir": ("SNDR_MODELS_DIR", "GENESIS_MODELS_DIR"),
    "hf_cache": ("HF_HOME", "HUGGINGFACE_HUB_CACHE", "SNDR_HF_CACHE"),
    "cache_root": ("SNDR_CACHE_ROOT", "GENESIS_CACHE_ROOT"),
    "genesis_src": ("SNDR_CORE_SRC", "GENESIS_SRC"),
    "plugin_src": ("SNDR_PLUGIN_SRC", "GENESIS_PLUGIN_SRC"),
}
```

и использовать его до/после candidates, но с валидацией absolute path.

2. В `launch.py` для `--preflight-only` не падать фатально на render. Нужен structured diagnostic:

```python
try:
    script = cfg.to_launch_script(host_paths=host_paths, strict_mounts=True)
except SchemaError as e:
    if getattr(opts, "preflight_only", False):
        return _emit_preflight_missing_host_paths(cfg, host_paths, e)
    _io.fatal(...)
```

3. Добавить `sndr host init` или `sndr install` шаг, который создает `~/.sndr/host.yaml` с `models_dir` как required field.

**Acceptance:**

```bash
SNDR_MODELS_DIR=/models python3 -m vllm.sndr_core.cli launch prod-35b --preflight-only
python3 -m vllm.sndr_core.cli launch prod-35b --preflight-only --json | python3 -m json.tool
```

Если `/models` не существует, команда должна вернуть понятный preflight finding, а не Python render exception.

---

### P0.4. `memory explain` возвращает `SAFE` при нулевой оценке weights/KV

**Файлы:**

- `vllm/sndr_core/runtime/memory_estimator.py:519-569`
- `vllm/sndr_core/runtime/memory_estimator.py:627-642`
- `vllm/sndr_core/cli/memory.py:485-662`

**Текущий результат:**

```json
{
  "total_bytes": 1166016512,
  "utilization": 0.0505,
  "components": [
    {"name": "Model weights (after TP shard)", "bytes": 0, "confidence": "low"},
    {"name": "KV cache", "bytes": 0, "confidence": "low"}
  ],
  "warnings": [
    "Model path ... has no readable safetensors...",
    "KV cache estimate is 0..."
  ],
  "recommendations": [
    "Budget only 5% utilized — you can raise max_model_len or max_num_seqs for more throughput."
  ],
  "verdict": "SAFE"
}
```

**Проблема:** это опасный false-safe. Если нет weights и KV-cache данных, estimator не имеет права рекомендовать увеличивать контекст или batch.

**Что дописать:**

1. В `MemoryEstimate` добавить actionable/confidence flag:

```python
def has_critical_low_confidence(self) -> bool:
    critical = ("Model weights", "KV cache")
    return any(
        c.bytes_ == 0 and c.confidence == "low" and c.name.startswith(critical)
        for c in self.components
    )
```

2. В verdict logic:

```python
if estimate.has_critical_low_confidence():
    verdict = "UNKNOWN"
elif utilization > 0.95:
    verdict = "AT_RISK"
...
```

3. Recommendations:

```python
if estimate.has_critical_low_confidence():
    recommendations.append(
        "Cannot make capacity recommendation until model weights and KV shape are readable."
    )
else:
    # current utilization recommendations
```

4. В CLI JSON добавить:

```json
"actionable": false,
"confidence": "low",
"missing_inputs": ["safetensors", "config.json:num_hidden_layers/head_dim"]
```

**Acceptance:**

```bash
python3 -m vllm.sndr_core.cli memory explain prod-35b --json | python3 -m json.tool
```

При недоступном model path verdict должен быть `UNKNOWN`/`INSUFFICIENT_DATA`, а не `SAFE`.

---

### P0.5. Production trust anchor еще dev-only, security gate не закрыт

**Файлы:**

- `vllm/sndr_core/license.py:73-89`
- `tools/license_keygen.py:5-9`

**Текущий код:**

```python
# DEV/TEST trust anchor — Ed25519 public key...
# ... private key was exposed in stdout under the old flow ...
# this anchor is considered development-only.
_TRUST_ANCHOR_PUBKEY_B64URL = (
    "iSk29MUb9HldKokPRyOG7bAjwYaQdgqYsS17yfskE8s"
)
```

**Проблема:**

- Комментарий прямо говорит, что ключ development-only.
- `tools/license_keygen.py:5-9` устарел: пишет, что public distribution ships placeholder zero public-key, хотя сейчас в `license.py` уже dev/test public key.
- `audit-security` показывает `188 total violations`.

**Что дописать/исправить:**

1. Провести offline key ceremony через `scripts/generate_trust_anchor.py`.
2. Обновить `license.py` production public key.
3. Обновить `tools/license_keygen.py` docstring: сейчас не zero placeholder, а dev/test anchor.
4. Добавить CI/release gate:

```python
FORBIDDEN_DEV_ANCHORS = {
    "iSk29MUb9HldKokPRyOG7bAjwYaQdgqYsS17yfskE8s",
}
assert _TRUST_ANCHOR_PUBKEY_B64URL not in FORBIDDEN_DEV_ANCHORS
```

5. Развести режимы:
   - community core: license optional, no private dependency;
   - private engine: fail-closed if license required and invalid;
   - dev: explicit `SNDR_LICENSE_DEV_MODE=1`, не implicit.

**Acceptance:**

```bash
python3 -m vllm.sndr_core.cli license status --json | python3 -m json.tool
make audit-security
make evidence
```

Для public release security gate должен стать green или иметь строгий allowlist с объяснением каждого false positive.

---

## 4. P1: незавершенный код и заглушки, которые не блокируют syntax, но блокируют качество

### P1.1. `compose.py` читает несуществующее поле `symbolic_mounts`

**Файл:** `vllm/sndr_core/cli/compose.py:120-129`

**Текущий код:**

```python
hc = load_host_config()
if hc is None:
    return {}
return hc.symbolic_mounts or {}
```

**Проблема:** `HostConfig` имеет поле `paths`, а не `symbolic_mounts` (`vllm/sndr_core/model_configs/host.py:31-37`). Ошибка проглатывается `except Exception: return {}`, поэтому compose silently теряет host config.

**Также:** regex `compose.py:137`:

```python
_UNRESOLVED_PLACEHOLDER_RE = _re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
```

слишком широкий: ловит `$FOO` как placeholder, хотя contract в `schema.py` работает только с `${var}`.

**Что дописать:**

```python
def _load_host_paths() -> dict[str, str]:
    from vllm.sndr_core.model_configs.host import load_host_config
    hc = load_host_config()
    return dict(hc.paths) if hc else {}

_UNRESOLVED_PLACEHOLDER_RE = _re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
```

И добавить unit test на host.yaml с `models_dir`.

---

### P1.2. 13 PatchSpec без `apply_module`

`shadow --strict` проходит, но migration не завершена: 13/136 specs не имеют `apply_module`.

| Patch | Family | Lifecycle | Impl | Test | Prod default | Что делать |
|---|---|---|---|---|---|---|
| `PN26b` | `attention.turboquant` | research | scaffold | unit | research_only | Либо реализовать Sparse-V, либо держать research-only. |
| `P1` | quantization | legacy | live | none | review_required | Добавить apply_module или явно retired/superseded. |
| `P17` | moe | legacy | live | none | review_required | Добавить тест и apply_module или retired. |
| `P18b` | attention.turboquant | legacy | live | none | review_required | Мигрировать в integration module. |
| `P20` | attention.turboquant | legacy | live | none | review_required | Мигрировать или закрыть. |
| `P23` | kernels | legacy | live | none | review_required | Нужен apply_module/test. |
| `P29` | tool_parsing | legacy | live | none | review_required | Нужен apply_module/test. |
| `P32` | attention.turboquant | legacy | live | none | review_required | Нужен apply_module/test. |
| `P51` | attention.turboquant | legacy | live | unit | eligible | Лучше добавить apply_module, чтобы eligible не зависел от legacy path. |
| `P102` | kv_cache | experimental | live | unit | eligible | Аналогично: eligible без apply_module выглядит как migration debt. |
| `PN60` | compile_safety | legacy | live | none | review_required | Добавить apply_module/test. |
| `PN63` | compile_safety | legacy | live | none | review_required | Добавить apply_module/test. |
| `PN64` | kernels | experimental | placeholder | none | blocked | Оставить blocked до SM12 tuning data или удалить из release-visible matrix. |

**Правило:** все `production_default=eligible` должны иметь `apply_module` или explicit waiver. Иначе operator видит зеленый статус, но apply path остается legacy/spec-only.

**Acceptance:**

```bash
python3 -m vllm.sndr_core.apply.shadow --strict
python3 -m vllm.sndr_core.cli patches plan --profile production --json | python3 -m json.tool
```

Нужно добиться либо 136/136 apply_module, либо отдельного machine-readable allowlist для spec-only entries.

---

### P1.3. PN26 Sparse-V заявлен, но реально scaffold/deferred

**Файл:** `vllm/sndr_core/integrations/attention/turboquant/pn26_tq_unified_perf.py:345-365`

**Текущий код:**

```python
# Sub-patch 2: sparse V kernel scaffold (deferred until NVIDIA validation).
sparse_v_enabled = os.environ.get(
    "GENESIS_ENABLE_PN26_SPARSE_V", "0"
).strip().lower() in ("1", "true", "yes", "on")
sparse_v_status = "scaffold-only"
if sparse_v_enabled:
    sparse_v_status = "deferred"
    log.warning(...)
```

**Проблема:** env flag можно включить, но функционально Sparse-V не применяется. Это нормально для research, но плохо для production UX, если пользователь ожидает реальный kernel win.

**Что дописать:**

1. Явно разделить `PN26` и `PN26b`:
   - `PN26`: centroids prebake, production-safe.
   - `PN26b`: Sparse-V tile-skip, research-only, disabled by default.
2. В CLI `patches explain PN26b` выводить: "not implemented; blocked by Ampere correctness validation".
3. Для реализации PN26b нужны два text patches:
   - `triton_turboquant_decode.py`: `SPARSE_V` constexpr и kernel branch.
   - `turboquant_attn.py`: caller arguments + opt-in.
4. Нужны tests:
   - static anchor test;
   - numerical equivalence на малом tensor;
   - short GPU smoke на A5000/3090;
   - A/B TPS и correctness.

---

### P1.4. PN21 DFlash/SWA частичный

**Файл:** `vllm/sndr_core/integrations/spec_decode/pn21_dflash_swa_support.py:296-301`

**Текущий статус в коде:**

```python
"DFlash SWA partial ... Note: full SWA enabler in "
"qwen3_dflash.py model class deferred — wait for vllm#40898 merge "
"or apply manually."
```

**Проблема:** часть DFlash/SWA поведения зависит от внешнего upstream PR или ручного действия. Это не должно выглядеть как полный production patch.

**Что дописать:**

1. В registry/metadata отметить PN21 как partial или добавить subfeature status.
2. В `patches plan --profile production` не считать PN21 полноценным для DFlash SWA, если `qwen3_dflash.py` path/anchor отсутствует.
3. Добавить probe:
   - модель с SWA layer types;
   - проверка causal=True на SWA;
   - проверка model class enabler.

---

### P1.5. PN79 lifecycle migration deferred

**Файл:** `vllm/sndr_core/integrations/attention/gdn/pn79_inplace_ssm_state.py:42-47`

**Текущий текст:**

```text
PN59 + PN54 → INTENDED for lifecycle: deprecated / retired ...
As of 2026-05-07 both remain lifecycle: stable ... migration deferred
```

**Проблема:** код сам говорит, что lifecycle уже должен быть пересмотрен после evidence. Если PN79 заменяет PN59/PN54, registry должен отражать это, иначе plan/doctor может предлагать несовместимую комбинацию или неверно оценивать stable-патчи.

**Что дописать:**

1. Провести Cliff 2 multi-turn reproducer + memory traffic profiler.
2. Если PN79 подтвержден:
   - PN59/PN54 → `deprecated` или `retired`;
   - PN79 → `stable` только после bench/correctness evidence.
3. Добавить lifecycle audit rule: если патч содержит `migration deferred` и дата старше N дней, gate должен требовать явный waiver.

---

### P1.6. Community scaffold генерирует no-op patch по дизайну

**Файл:** `vllm/sndr_core/community/scaffold.py:2-14`

**Текущий текст:**

```text
Implement the apply hook in patch.py (currently a no-op stub).
```

**Это допустимо**, потому что scaffold всегда `publish_state: draft`. Но для качества нужно:

1. CLI должен явно писать: draft plugin не входит в release registry.
2. `sndr community validate` должен fail-closed, если no-op stub переведен в `review`/`published`.
3. Template должен генерировать `apply()` с явным `raise ScaffoldNotImplementedError`, но только внутри draft tree, не в release registry.
4. Acceptance gate должен проверять: no draft/no-op plugin не попадает в release package.

---

### P1.7. Proof-chain static green, но bench доказательства еще не production-grade

**Файл:** `vllm/sndr_core/proof/bench_attach.py:1-28`

**Текущий дизайн:**

```text
If the proof artefact doesn't exist yet, a stub is created from build_proof_for_patch(...)
Doesn't run the bench — that's GPU work.
```

**Проблема:** `patches prove --dead-detect` дает 136/136, но это static proof. Это не равно "патч проверен на GPU/runtime". Для production roadmap надо разделять:

- static proof: anchors/imports/schema/dead-detect;
- bench attached: есть реальный bench JSON;
- bench with baseline: есть delta против stock/baseline;
- production validated: есть pin/model/hardware tuple.

**Что дописать:**

1. В `patches proof-status` добавить buckets:
   - `static_only`;
   - `bench_no_baseline`;
   - `bench_with_baseline`;
   - `production_validated`.
2. В release-check для stable/perf patches требовать не просто static proof, а bench baseline.
3. Для PN96, PN26, DFlash, TurboQuant, MTP сделать обязательные proof artifacts с methodology sha.

---

## 5. P1/P2: installer, launcher, config automation

### P1.8. Bootstrap scopes не полностью соответствуют planner scopes

**Файл:** `vllm/sndr_core/cli/bootstrap.py:87-111`

**Текущий код:**

```python
if "model-artifacts" in s:
    out.update({"model"})  # not yet a real PlanItem.scope, but reserved
return out
```

```python
def _unsupported_plan_scopes(s: set[str]) -> set[str]:
    ...
    return set()
```

**Проблема:** комментарий говорит, что `model` "not yet a real PlanItem.scope", но `_unsupported_plan_scopes()` всегда возвращает empty set и утверждает, что все scopes covered. Это опасный silent no-op.

**Что дописать:**

1. В `deps/planners.py` явно поддержать scopes:
   - `os`;
   - `python`;
   - `docker`;
   - `nvidia`;
   - `model`;
   - `service`.
2. `_unsupported_plan_scopes()` должен сравнивать requested scopes с реальными planner scopes.
3. `bootstrap doctor --json` должен показывать:
   - requested scopes;
   - supported scopes;
   - unsupported scopes;
   - planned item count per scope.

**Acceptance:**

```bash
python3 -m vllm.sndr_core.cli bootstrap doctor prod-35b --scope service --json | python3 -m json.tool
python3 -m vllm.sndr_core.cli bootstrap doctor prod-35b --scope model-artifacts --json | python3 -m json.tool
```

Нельзя возвращать "готово", если план пустой из-за неподдержанного scope.

---

### P1.9. Proxmox render пока manual recipe, не production automation

**Файл:** `vllm/sndr_core/cli/proxmox.py:162-229`

**Текущие признаки неполноты:**

- `operator must adjust storage / network`;
- `replace with lspci | grep NVIDIA IDs`;
- Docker install команды печатаются как manual steps;
- GPU passthrough редактируется вручную через `/etc/pve/lxc/<id>.conf`;
- нет rollback/apply-state tracking.

**Что дописать:**

1. Разделить команды:
   - `sndr proxmox render` — безопасный dry-run;
   - `sndr proxmox doctor` — проверяет PVE, storage, bridge, IOMMU, NVIDIA devices;
   - `sndr proxmox apply --yes` — только после doctor green.
2. Добавить Proxmox profile config:
   - `storage`;
   - `bridge`;
   - `template`;
   - `vmid/container_id`;
   - `gpu_devices`;
   - `runtime=docker|venv`;
   - `privileged/nesting`.
3. Docker repo key install должен быть fingerprint-pinned. Сейчас `curl -fsSL ... | gpg --dearmor` без fingerprint validation.

---

### P1.10. K8s/Quadlet/Service слой нужно довести до одного RuntimeCommandSpec

Roadmap говорит о RuntimeCommandSpec, но текущие symptoms показывают, что emitters еще расходятся:

- `launch` падает на host vars;
- `compose.py` читает неправильное поле host config;
- `proxmox.py` генерирует manual commands;
- `k8s.py`/`quadlet.py` надо сверить с тем же mount/env/image contract.

**Что дописать:**

1. Один canonical IR:
   - image + digest;
   - command args;
   - env;
   - mounts;
   - ports;
   - GPU policy;
   - cache/model paths;
   - security flags.
2. Все emitters должны строиться из IR:
   - Docker run;
   - compose;
   - quadlet;
   - k8s manifest;
   - proxmox commands.
3. Один test matrix:
   - каждый preset renders all supported runtimes;
   - unresolved placeholders fail consistently;
   - JSON diagnostics одинаковы.

---

## 6. P2: архитектурные долги

### P2.1. Dirty state нужно заморозить перед любыми production выводами

Текущий `git status --short` содержит сотни entries:

- много `D vllm/_genesis/...` — миграция legacy дерева;
- много `?? vllm/sndr_core/...` — новый core слой еще untracked;
- много `?? tests/unit/...` — новая test matrix;
- modified `.github/workflows/*`, scripts, tools, configs.

`make audit-dirty-state-dev` проходит, но это только dev-политика. Для release нужен clean/release-tier gate.

**Что сделать:**

1. Разделить изменения по коммитам:
   - migration `_genesis` removal;
   - `sndr_core` importable package;
   - configs;
   - tests;
   - docs/internal;
   - workflows/release.
2. Запустить release dirty policy:

```bash
make audit-dirty-state-release
```

3. Все release-critical untracked files должны быть tracked или явно excluded.

---

### P2.2. `_genesis` удален, но public docs/scripts все еще должны пройти stale-scan

Физически:

- `vllm/_genesis` files: `0`;
- `vllm/sndr_engine` files: `0`;
- `vllm/sndr_core` Python files: `362`.

Это правильное направление. Но release должен доказать, что:

1. Нет runtime imports `vllm._genesis`.
2. Нет public docs, которые зовут старые команды/пути.
3. Нет tests, которые завязаны на старое дерево вне legacy fixtures.

Часть gates уже это ловит, но `make audit` еще падает на public paths.

---

### P2.3. Dispatch layer все еще требует схлопывания

Roadmap прямо говорит о debt:

- `apply/_per_patch_dispatch.py` остается legacy dispatch table.
- Цель: `PatchApplyResult`, единый `apply()` contract, меньше промежуточных слоев.

**Что улучшить:**

1. Каждый integration module должен экспортировать:

```python
def apply(ctx: PatchApplyContext) -> PatchApplyResult: ...
def is_applied(ctx: PatchApplyContext) -> bool: ...
```

2. Registry должен хранить `apply_module`.
3. Legacy dispatch должен стать compatibility shim и затем удалиться.
4. `shadow --strict` должен стать gate на 100% apply_module или machine-readable allowlist.

---

## 7. Конкретный порядок исправлений

### Шаг 1. Закрыть release blocker `audit-public-paths`

Сначала это, потому что `make evidence` сейчас блокируется именно тут.

**Изменить:**

- `tools/long_ctx_smoke.sh`
- `tools/soak.sh`
- `tools/audit_yaml_vs_runtime.sh`
- `benchmarks/harness/*.py`
- `benchmarks/harness/README.md`
- `docs/upstream/*` или перенести historical internal docs
- `docs/reference/*` или перенести в internal/archive
- `vllm/sndr_core/compat/doctor.py:844`
- scanner allowlist для self-documenting strings

### Шаг 2. Починить CLI JSON contract

**Изменить:**

- `vllm/sndr_core/compat/model_config_cli.py`
- возможно `vllm/sndr_core/cli/config.py`

**Добавить тест:**

- `tests/unit/cli/test_config_list_json.py`

### Шаг 3. Починить host path / preflight

**Изменить:**

- `vllm/sndr_core/model_configs/host.py`
- `vllm/sndr_core/cli/launch.py`
- `vllm/sndr_core/cli/compose.py`
- tests на `models_dir`, `SNDR_MODELS_DIR`, missing host vars.

### Шаг 4. Починить `memory explain` verdict

**Изменить:**

- `vllm/sndr_core/runtime/memory_estimator.py`
- `vllm/sndr_core/cli/memory.py`

**Добавить tests:**

- model path missing → `UNKNOWN`, `actionable=false`;
- local fake config + fake safetensors → нормальный `SAFE/TIGHT/AT_RISK`;
- no recommendation to increase context when confidence low.

### Шаг 5. Довести security/license

**Изменить:**

- `vllm/sndr_core/license.py`
- `tools/license_keygen.py`
- `scripts/security_scan.py`
- docs/security

**Добавить gate:**

- dev anchor forbidden in production release mode;
- secret/private path scanner green.

### Шаг 6. Завершить patch migration

**Изменить/проверить:**

- 13 specs без apply_module;
- PN26b status;
- PN21 partial status;
- PN79 lifecycle migration;
- proof-status buckets.

### Шаг 7. Installer/bootstrap/runtime emitters

**Изменить:**

- `vllm/sndr_core/cli/bootstrap.py`
- `vllm/sndr_core/deps/*`
- `vllm/sndr_core/cli/proxmox.py`
- `vllm/sndr_core/cli/k8s.py`
- `vllm/sndr_core/cli/quadlet.py`
- RuntimeCommandSpec/RuntimeContainerSpec tests.

---

## 8. Что считать готовым после исправлений

Минимальный release acceptance:

```bash
python3 -m vllm.sndr_core.compat.cli self-test --json
python3 -m vllm.sndr_core.apply.shadow --strict
python3 -m vllm.sndr_core.cli config list --json | python3 -m json.tool
python3 -m vllm.sndr_core.cli launch prod-35b --preflight-only --json | python3 -m json.tool
python3 -m vllm.sndr_core.cli memory explain prod-35b --json | python3 -m json.tool
python3 -m vllm.sndr_core.cli patches prove --dead-detect --json
make audit-configs
make audit
make evidence
make audit-dirty-state-release
```

GPU-gated acceptance перед настоящим production:

```bash
python3 scripts/bench_v11_smoke.py --preset prod-35b --duration-short
sndr patches bench-attach PN96 <bench.json> --baseline <baseline.json>
sndr patches release-check --mode require-bench
```

---

## 9. Главное, что надо дописать кодом

1. JSON branch для `cmd_list()`.
2. Env/host fallback для `models_dir`, `hf_cache`, `cache_root`, `genesis_src`, `plugin_src`.
3. Structured preflight diagnostics вместо fatal render exception.
4. Correct `compose.py` host config loading: `hc.paths`, не `hc.symbolic_mounts`.
5. Low-confidence memory verdict: `UNKNOWN`, не `SAFE`.
6. Production trust anchor ceremony + gate against dev key.
7. Planner support for `model-artifacts` and `service`.
8. RuntimeCommandSpec single source for launch/compose/k8s/proxmox/quadlet.
9. Patch proof buckets: static-only vs bench-validated.
10. Apply-module migration or explicit machine-readable allowlist for the 13 remaining specs.
11. PN26b Sparse-V real implementation or strict research-only hiding.
12. PN21 DFlash/SWA full enabler or honest partial status.
13. PN79 lifecycle cleanup after evidence.
14. Release dirty-state freeze.

---

## 10. Мой приоритет исправлений

Если исправлять вручную и быстро, порядок такой:

1. **P0.1 public paths** — без этого `make evidence` не зеленый.
2. **P0.2 config JSON** — простой баг, высокий UX/evidence impact.
3. **P0.3 host/preflight** — основной блокер запуска "из коробки".
4. **P1.1 compose host bug** — рядом с preflight, лучше исправить одним заходом.
5. **P0.4 memory verdict** — опасная логическая ошибка.
6. **P0.5 security/license** — обязательно до публичного релиза.
7. **P1.2 apply_module migration** — уже не обязательно для syntax, но обязательно для чистой архитектуры.
8. **P1.8/P1.9 bootstrap/proxmox** — после ядра, иначе автоматизация будет строиться на неполном host/runtime contract.

---

## 11. Что сейчас не выглядит проблемой

1. Python syntax: зеленый.
2. Shell syntax: зеленый.
3. V2 preset composition: зеленый.
4. Legacy `_genesis` imports gate: зеленый.
5. Engine boundary gate: зеленый.
6. Static proof coverage: 136/136.
7. `sndr_engine` пустой: это сейчас правильно для public core, если optional discovery сохранен и core не зависит от engine напрямую.

Но эти зеленые пункты не отменяют P0/P1 выше: production ломается не синтаксисом, а контрактами CLI/runtime/security.
