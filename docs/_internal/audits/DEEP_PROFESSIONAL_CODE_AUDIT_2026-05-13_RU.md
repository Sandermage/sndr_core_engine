# Глубокий аудит кода и незавершенных мест проекта

Дата: 2026-05-13  
Снимок: `dev`, `HEAD=de26be1`  
Корень проверки: `/Users/sander/Documents/Visual Studio Code/genesis-vllm-patches`

Цель: зафиксировать проблемные места текущего состояния проекта без правки кода: ошибки, скрытые ошибки, нарушения целостности, недописанные функции, заглушки, упоминания AI/ИИ, слабые места архитектуры и конкретные варианты исправления.

## 1. Короткий вывод

Проект стал заметно чище по базовой технической гигиене: Python AST чистый, shell-скрипты синтаксически чистые, registry/shadow/config gates проходят, `_genesis` и `sndr_engine` физически пустые. Но до production-ready состояния еще нельзя считать проект закрытым.

Главные блокеры:

1. `make evidence` все еще блокирует релиз: падает gating `audit` из-за приватных путей и адресов в публичных документах/скриптах.
2. `security_scan.py` находит `188` operator-path violations. Это informational gate, но для публичного релиза его нельзя игнорировать.
3. `sndr launch --preflight-only --check-deps` может сказать `all checks passed` даже когда `sndr deps plan` видит отсутствие Docker, NVIDIA и модели. Это скрытая функциональная ошибка preflight.
4. `bootstrap`, `service`, `proxmox` CLI уже существуют, но основные builtin-конфиги не содержат `bootstrap:`, `service:`, `proxmox:` блоки. То есть заявленная единая установка и управление пока не подключены к реальным preset'ам.
5. В `a5000-2x-35b-prod.yaml` есть конфликт pin'ов: top-level требует `dev209`, а `upstream.required_pin` остается `dev93`.
6. В коде и публичных документах остаются прямые упоминания AI/Codex/Claude/ChatGPT, включая один runtime-патч.
7. Есть несколько сознательных заглушек/partial/scaffold патчей. Они не ломают сборку, но должны быть явно помечены как not-prod или доведены до полноценной реализации.

## 2. Проверки, выполненные на текущем снимке

| Проверка | Результат | Комментарий |
|---|---:|---|
| `python3 -m vllm.sndr_core.compat.cli self-test --json` | PASS 8/8 | 19 compat imports, 122 wiring imports, 136 registry entries clean |
| `python3 -m vllm.sndr_core.apply.shadow --strict` | PASS | 133 legacy registrations, 136 specs, 123 with `apply_module`, 13 without |
| `make audit-configs` | PASS | 11 presets compose cleanly |
| `python3 -m vllm.sndr_core.cli patches prove --dead-detect --json` | PASS | 136/136 proven, dead=0 |
| Python AST parse | PASS | 827 `.py`, errors=0 |
| `bash -n` shell scripts | PASS | 66 `.sh`, errors=0 |
| JSON/TOML/YAML parse | WARN | 1 bad JSON in `.history/.claude/settings.local_20260513123049.json`, не release-код |
| `python3 -m vllm.sndr_core.cli memory explain prod-35b --json` | PASS/WARN | verdict `UNKNOWN`, actionable=false, модель/kv shape не читаются |
| `python3 -m vllm.sndr_core.cli license status --json` | PASS | core public, engine null, premium=0 |
| `make evidence` | FAIL | 1 gating fail: `audit`; informational fail: `audit-security`, 188 violations |
| `make audit` | FAIL | `audit-public-paths` |

Рабочее дерево: `822` dirty entries (`375` untracked, `384` deleted, `63` modified). Для dev это допустимо только при текущей dirty-state политике, но для release это высокий риск.

## 3. Что сейчас уже хорошо

- `vllm/_genesis` физически пустой: `0` файлов.
- `vllm/sndr_engine` физически пустой: `0` файлов. Это соответствует стратегии: public core содержит текущие наработки, engine зарезервирован под будущий private overlay.
- Patch registry в текущем состоянии не развален: `shadow --strict` чистый.
- Конфиги, которые участвуют в `make audit-configs`, компонуются.
- `config list --json` работает и отдает 9 публичных builtin-конфигов.
- `memory explain` больше не дает ложное `SAFE`, когда модельные веса и KV shape недоступны. Сейчас корректно возвращается `UNKNOWN`.

## 4. P0: release blockers

### P0-1. Публичный audit падает из-за приватных путей и адресов

Связанные файлы:

- `scripts/audit_no_hardcoded_paths.py:7`
- `scripts/security_scan.py:8`, `scripts/security_scan.py:98`
- `docs/upstream/PRODUCTION_ROADMAP_EXPANDED_DELTA_AUDIT_2026-05-08.md:821`, `:832`
- `docs/upstream/DEEP_AUDIT_VLLM_NOONGHUNNA_2026-05-08_RU.md:370`, `:372`, `:373`
- `docs/upstream/PRODUCTION_ROADMAP_2026-05-09.md:550`, `:552`, `:554`, `:898`, `:913`, `:915`, `:1279`, `:1574`, `:1939`, `:2228`, `:2232`
- `docs/reference/V759_320K_CONTEXT_EXPANSION_20260427.md:4`
- `docs/reference/DEFERRED_P50_DEPLOY.md:28`, `:29`, `:36`, `:38`, `:41`, `:42`, `:75`, `:77`, `:79`, `:81`
- `docs/reference/V758_P75_SUFFIX_DECODING_DEPLOY_VARIANT.md:7`, `:80`, `:128`, `:162`

Фактический результат:

```text
make audit
✗ Private paths found in public files.
Replace LAN IPs with 127.0.0.1 / <your-host>,
/home/sander with $HOME / <your-home>,
sander@ with <user>@<host>.
```

Почему это проблема:

- Публичный release blocked.
- В документации остаются персональные пути, LAN IP и user/host.
- Часть путей находится в audit/roadmap-файлах, которые могут быть внутренними, но сейчас попадают под публичные проверки.

Как исправить:

1. Разделить публичные и внутренние документы.
2. Все `docs/upstream/*`, которые остаются публичными, санитизировать:
   - `192.168.1.10` -> `<host>` или `127.0.0.1` в примерах.
   - `/home/sander/...` -> `$HOME/...`, `${SNDR_ROOT}`, `${MODELS_DIR}`.
   - `sander@host` -> `<user>@<host>`.
3. Внутренние серверные журналы перенести в `docs/_internal/` или добавить осознанный allowlist только для internal docs, не для release docs.
4. В `scripts/audit_no_hardcoded_paths.py` и `scripts/security_scan.py` не считать собственный текст документации scanner'а нарушением, если он описывает запрещенные паттерны. Сейчас scanner частично ловит собственные правила.

### P0-2. `security_scan.py` показывает 188 нарушений operator paths

Файл:

- `scripts/security_scan.py:8`
- `scripts/security_scan.py:98`

Связанные примеры из вывода:

- `CHANGELOG.md:467`
- `CHANGELOG.md:590`
- `assets/chat_templates/README.md:38`
- `compose/docker-compose.unit.yml:11`
- `compose/docker-compose.unit.yml:13`

Фактический результат:

```text
security_scan: 878 tracked files scanned
✗ operator_paths: 188 hit(s)
✓ private_ips: clean
✓ private_keys: clean
✓ env_files: clean
✓ aws_keys: clean
FAIL — 188 total violations
```

Почему это проблема:

- Даже если `audit-security` informational, это release-risk.
- Часть путей находится в документации, часть в compose, часть в changelog.
- При публикации это выглядит как неочищенный homelab dump.

Как исправить:

- Ввести две политики:
  - `public_release`: 0 private paths в `README.md`, `docs/`, `compose/`, `scripts/`, `.github/`.
  - `internal_evidence`: допускает приватные пути только в `docs/_internal/` и только с явной пометкой.
- Для `CHANGELOG.md` заменить конкретные пути на sanitized variables, потому что changelog публичный.

### P0-3. `sndr launch --check-deps` фактически не проверяет deps plan

Файлы:

- `vllm/sndr_core/cli/launch.py:390-422`
- `vllm/sndr_core/cli/launch.py:433-438`
- `vllm/sndr_core/deps/planners.py:117-156`
- `vllm/sndr_core/deps/planners.py:157-196`
- `vllm/sndr_core/deps/planners.py:197-232`
- `vllm/sndr_core/deps/planners.py:234-281`

Текущий код:

```python
def _run_check_deps(cfg, key: str) -> int:
    ...
    try:
        from vllm.sndr_core.deps.checkers import inspect_host
        from vllm.sndr_core.caveats import match_caveats
        facts = inspect_host().to_dict()
    except Exception as e:
        _io.warn(f"--check-deps: deps collector unavailable ({e}); skipping")
        return 0
    ...
    errs = [c for c in triggered if c.severity == "error"]
    ...
    return 0
```

Фактическая скрытая ошибка:

```text
python3 -m vllm.sndr_core.cli deps plan --config a5000-2x-35b-prod --json
```

возвращает blockers:

- Docker Engine missing.
- NVIDIA driver missing.
- model directory missing.

Но:

```text
python3 -m vllm.sndr_core.cli launch a5000-2x-35b-prod --preflight-only --check-deps
```

возвращает:

```text
--preflight-only: all checks passed — exiting without exec
```

Почему это проблема:

- Operator доверяет preflight и получает ложный PASS.
- `deps.plan` и `launch --check-deps` расходятся по смыслу.
- Скрывает отсутствие Docker/NVIDIA/model artifacts на dev machine.

Как исправить:

`launch._run_check_deps()` должен использовать тот же `plan_changes()`, что и `sndr deps plan`, а caveats должны быть дополнительным слоем.

Предлагаемый вариант:

```python
def _run_check_deps(cfg, key: str) -> int:
    _io.step(0, 0, "Checking host dependencies")
    try:
        from vllm.sndr_core.deps import inspect_host, plan_changes
    except Exception as e:
        _io.error(f"--check-deps: dependency planner unavailable: {e}")
        return 2

    plan = plan_changes(cfg, inspect_host())
    blockers = plan.blockers()
    for item in blockers:
        _io.error(f"[{item.scope}] {item.target}: {item.reason}")
        if item.suggested_command:
            _io.info(f"    suggested: {item.suggested_command}")

    if blockers:
        _io.error(f"--check-deps: {len(blockers)} blocker(s); refusing launch")
        return 2

    return _run_caveat_check(cfg)
```

Отдельно: если deps collector сломан, strict/preflight режим не должен молча возвращать `0`.

## 5. P1: functional и architecture defects

### P1-1. `bootstrap`, `service`, `proxmox` CLI есть, но основные preset'ы не содержат нужных блоков

Файлы:

- `vllm/sndr_core/cli/bootstrap.py:62-72`
- `vllm/sndr_core/cli/proxmox.py:62-72`
- `vllm/sndr_core/cli/service.py` через CLI surface
- `vllm/sndr_core/model_configs/builtin/a5000-2x-35b-prod.yaml:169-195`
- `vllm/sndr_core/model_configs/builtin/a5000-2x-27b-int4-tq-k8v4.yaml:154`

Факты:

```text
rg "^bootstrap:|^service:|^proxmox:|^artifacts:" vllm/sndr_core/model_configs/builtin/*.yaml
```

нашел только `artifacts:` в двух файлах. Ни одного `bootstrap:`, `service:`, `proxmox:` в builtin-конфигах нет.

Команды:

```text
python3 -m vllm.sndr_core.cli bootstrap doctor a5000-2x-35b-prod --json
```

```text
⚠ preset 'a5000-2x-35b-prod' has no Y7 bootstrap block
```

```text
python3 -m vllm.sndr_core.cli service install a5000-2x-35b-prod
```

```text
⚠ preset 'a5000-2x-35b-prod' has no Y10 service block
```

```text
python3 -m vllm.sndr_core.cli proxmox render a5000-2x-35b-prod
```

```text
⚠ preset 'a5000-2x-35b-prod' has no Y6 proxmox block
```

Почему это проблема:

- CLI выглядит как готовый единый installer/launcher stack, но реальные production presets к нему не подключены.
- Пользователь видит команды в help, но для главных конфигов получает warning.
- Roadmap обещает единые конфиги с Docker/Proxmox/service/install, но реализация пока частичная.

Как исправить:

В каждый stable builtin config добавить минимальные блоки:

```yaml
bootstrap:
  scopes:
    - os-packages
    - gpu-runtime
    - python-runtime
    - container-runtime
    - model-artifacts
    - service
  apply_policy: ask
  privilege: sudo

service:
  backend: docker_compose
  service_name: sndr-a5000-2x-35b-prod
  working_dir: ${sndr_root}
  env_file: ${sndr_config_dir}/a5000-2x-35b-prod.env
  logs_dir: ${sndr_log_dir}/a5000-2x-35b-prod
  restart: unless-stopped

proxmox:
  mode: lxc
  runtime: docker
  gpu_passthrough: true
  container_id_or_vmid: null
```

Сначала добавить в `a5000-2x-35b-prod` и `a5000-2x-27b-int4-tq-k8v4`, потом распространить на остальные.

### P1-2. `bootstrap --scope all` не включает `service` и `vllm` scope

Файлы:

- `vllm/sndr_core/cli/bootstrap.py:87-100`
- `vllm/sndr_core/deps/planners.py:20`
- `vllm/sndr_core/deps/planners.py:197-232`
- `vllm/sndr_core/deps/planners.py:283-318`

Текущий код:

```python
def _scope_to_plan_scope(s: set[str]) -> set[str]:
    out: set[str] = set()
    if "os-packages" in s:
        out.update({"os"})
    if "gpu-runtime" in s:
        out.update({"nvidia", "docker"})
    if "python-runtime" in s:
        out.update({"python"})
    if "container-runtime" in s:
        out.update({"docker"})
    if "model-artifacts" in s:
        out.update({"model"})
    return out
```

Но `deps.planners.PlanItem.scope` реально использует:

- `os`
- `python`
- `docker`
- `nvidia`
- `vllm`
- `model`
- `service`

Почему это проблема:

- Даже после добавления `bootstrap:` scope `service` будет отфильтрован.
- `vllm` warnings/install items также будут выпадать из plan/apply output.
- `_unsupported_plan_scopes()` возвращает `set()` и не подсвечивает проблему.

Как исправить:

```python
def _scope_to_plan_scope(s: set[str]) -> set[str]:
    out: set[str] = set()
    if "os-packages" in s:
        out.add("os")
    if "gpu-runtime" in s:
        out.update({"nvidia", "docker"})
    if "python-runtime" in s:
        out.update({"python", "vllm"})
    if "container-runtime" in s:
        out.add("docker")
    if "model-artifacts" in s:
        out.add("model")
    if "service" in s:
        out.add("service")
    return out
```

Добавить unit test:

- scope `all` включает `service` PlanItem.
- scope `python-runtime` включает `vllm` PlanItem.
- неизвестный scope возвращает warning/error, а не silent no-op.

### P1-3. `a5000-2x-35b-prod.yaml` содержит конфликт vLLM pin'ов

Файл:

- `vllm/sndr_core/model_configs/builtin/a5000-2x-35b-prod.yaml:18-22`
- `vllm/sndr_core/model_configs/builtin/a5000-2x-35b-prod.yaml:197-205`

Текущий код:

```yaml
vllm_pin_required: 0.20.2rc1.dev209+g5536fc0c0
...
upstream:
  required_pin: 0.20.2rc1.dev93+g51f22dcfd
  allowed_pins:
    - 0.20.2rc1.dev93+g51f22dcfd
```

Почему это проблема:

- Top-level metadata говорит `dev209`.
- Y11 upstream policy говорит `dev93`.
- Если `vllm` установлен локально, `plan_changes()` при наличии `upstream.check()` использует upstream policy раньше legacy top-level pin.
- Это может давать ложный blocker на правильном dev209 или наоборот вводить оператора в заблуждение.

Как исправить:

Сделать один источник истины. Рекомендованный вариант:

```yaml
vllm_pin_required: 0.20.2rc1.dev209+g5536fc0c0
upstream:
  required_pin: 0.20.2rc1.dev209+g5536fc0c0
  allowed_pins:
    - 0.20.2rc1.dev209+g5536fc0c0
    - 0.20.2rc1.dev93+g51f22dcfd   # только если bench подтвердил совместимость
  blocked_pins: []
```

Дополнительно добавить audit gate: `top_level_pin == upstream.required_pin`, если оба поля заданы и `allowed_pins` не содержит явное migration window.

### P1-4. Image digest verification в `auto` режиме слишком мягкая для preflight

Файл:

- `vllm/sndr_core/cli/launch.py:268-304`
- `vllm/sndr_core/cli/launch.py:500-514`

Текущий код:

```python
if not shutil.which("docker"):
    _io.warn(
        "image_digest declared but `docker` not on PATH — "
        "cannot verify. Skipping in --strict-image=auto."
    )
    return 0 if mode == "auto" else 2
```

Фактический результат:

```text
python3 -m vllm.sndr_core.cli launch prod-35b --preflight-only
⚠ image_digest declared but `docker` not on PATH — cannot verify. Skipping in --strict-image=auto.
--preflight-only: all checks passed
```

Почему это проблема:

- `preflight-only` должен быть режимом "fail fast", а не "warn and pass".
- Если Docker отсутствует, Docker-backed config не может быть реально запущен.
- Сейчас отсутствие Docker маскируется и deps check тоже не спасает из-за P0-3.

Как исправить:

- Для `--preflight-only` и Docker-backed config отсутствие Docker должно быть non-zero.
- `--strict-image=auto` может быть мягким только в `--dry-run`, но не в `--preflight-only`.

Вариант:

```python
if not shutil.which("docker"):
    if mode == "off":
        return 0
    _io.error("docker is required to verify declared image_digest")
    return 2
```

Или передавать в `_verify_image_digest(cfg, mode, strict_preflight=is_preflight)`.

### P1-5. `memory_estimator` CLI исправлен, но runtime API все еще может дать неверную рекомендацию

Файлы:

- `vllm/sndr_core/runtime/memory_estimator.py:615-654`
- `vllm/sndr_core/cli/memory.py` post-processing layer

Текущий код:

```python
elif util > 0.0 and util < 0.6:
    recommendations.append(
        f"Budget only {util * 100:.0f}% utilized — you can raise "
        "max_model_len or max_num_seqs for more throughput."
    )
```

CLI теперь возвращает:

```json
"verdict": "UNKNOWN",
"actionable": false,
"missing_inputs": [
  "model safetensors not readable",
  "KV shape (num_hidden_layers / head_dim) not derivable"
]
```

Почему это все еще риск:

- Прямая библиотечная функция `estimate_for_config()` может быть использована другим кодом без CLI safety overlay.
- Нижний слой строит optimistic recommendation на основе `util=0.0505`, хотя веса и KV cache равны 0 из-за отсутствующих данных.

Как исправить:

Перенести low-confidence guard в runtime estimator:

```python
critical_missing = [
    c for c in components
    if c.bytes_ == 0 and c.confidence == "low"
    and (c.name.startswith("Model weights") or c.name.startswith("KV cache"))
]
if critical_missing:
    recommendations.append(
        "Cannot make a capacity recommendation: critical components have "
        "zero-byte low-confidence estimates."
    )
else:
    # existing utilization recommendations
```

Лучше: добавить поля `verdict`, `actionable`, `missing_inputs` в `MemoryEstimate`, чтобы CLI и API не расходились.

### P1-6. Trust anchor активирован как dev/test key, но документация внутри кода противоречит себе

Файлы:

- `vllm/sndr_core/license.py:63-66`
- `vllm/sndr_core/license.py:73-89`
- `vllm/sndr_core/license.py:90-93`
- `tools/license_keygen.py:5-9`

Текущий код:

```python
# placeholder zero-key is documented as "rejects all signatures"
...
# DEV/TEST trust anchor — Ed25519 public key
_TRUST_ANCHOR_PUBKEY_B64URL = (
    "iSk29MUb9HldKokPRyOG7bAjwYaQdgqYsS17yfskE8s"
)
# placeholder zero-key is loaded
```

И:

```python
"""SNDR Engine license tooling...
ships a placeholder zero public-key in `vllm.sndr_core.license`
"""
```

Почему это проблема:

- Реальный anchor уже не zero-placeholder.
- Комментарий говорит одновременно "zero-placeholder" и "dev/test exposed key".
- Для security-аудита это выглядит как неуверенный trust model.

Как исправить:

- Заменить старые zero-placeholder комментарии на текущее состояние:
  - "current public repo ships a development-only trust anchor".
  - "production release must replace before enabling paid engine".
- `tools/license_keygen.py` docstring обновить: не "replace placeholder", а "rotate development anchor to production anchor".
- Добавить release gate: production build запрещен, если anchor fingerprint совпадает с dev/test fingerprint.

### P1-7. `pyproject-engine.toml` как template ссылается на отсутствующий файл

Файл:

- `pyproject-engine.toml:45-50`
- `pyproject-engine.toml:94-113`

Текущий код:

```toml
name = "vllm-sndr-engine"
readme = "vllm/sndr_engine/LICENSE-NOTICE"
...
"vllm.sndr_engine" = [
    "LICENSE-NOTICE",
]
```

Факты:

- `vllm/sndr_engine` сейчас содержит `0` файлов.
- `pyproject-engine.toml` помечен как template, но при попытке сборки standalone wheel будет broken из-за отсутствующего `LICENSE-NOTICE`.

Почему это проблема:

- Если кто-то случайно запустит build по `pyproject-engine.toml`, получит ошибку.
- Документ "reserved namespace" корректный, но template не является самопроверяемым.

Как исправить:

- Либо добавить `vllm/sndr_engine/LICENSE-NOTICE` как единственный разрешенный skeleton-файл.
- Либо перенести `pyproject-engine.toml` в `docs/_internal/templates/` и явно исключить из release.
- Либо добавить `make audit-engine-template` с проверкой: если template существует, все referenced files существуют.

### P1-8. `compose/docker-compose.test-v11.yml` монтирует пустой engine и абсолютные server paths

Файл:

- `compose/docker-compose.test-v11.yml:3-6`
- `compose/docker-compose.test-v11.yml:16-18`
- `compose/docker-compose.test-v11.yml:49-57`

Текущий код:

```yaml
- /home/sander/genesis-vllm-patches-v11/vllm/sndr_core:/usr/local/lib/python3.12/dist-packages/vllm/sndr_core:ro
- /home/sander/genesis-vllm-patches-v11/vllm/sndr_engine:/usr/local/lib/python3.12/dist-packages/vllm/sndr_engine:ro
```

Почему это проблема:

- Это server-specific compose, но лежит в публичной `compose/`.
- `sndr_engine` пустой: mount либо бессмысленен, либо создает ложное ожидание engine runtime.
- Файл сам помечает EXEMPT, но `security_scan.py` все равно видит operator paths.

Как исправить:

Вариант A, лучший для public:

- Перенести в `docs/_internal/server-rig/docker-compose.test-v11.yml`.
- В public оставить sanitized template:

```yaml
volumes:
  - ${SNDR_CORE_SRC}:/usr/local/lib/python3.12/dist-packages/vllm/sndr_core:ro
  - ${SNDR_MODELS_DIR}:/models:ro
  - ${SNDR_HF_CACHE}:/root/.cache/huggingface:ro
```

Вариант B:

- Оставить в `compose/`, но заменить все пути на env vars и добавить `.env.example`.

### P1-9. Unit tests используют приватные IP/path fixtures вместо TEST-NET адресов

Файлы:

- `tests/unit/model_configs/test_service_schema.py:51-56`
- `tests/unit/integrations/middleware/test_pn65_access_log.py:45-68`
- `tests/unit/integrations/middleware/test_pn65_access_log.py:79`
- `tests/unit/model_configs/test_y5_y6_y7_schemas.py:146`
- `tests/unit/model_configs/test_artifacts_schema.py:163`

Пример:

```python
working_dir="/home/sander/genesis-vllm-patches"
...
"GET", "/v1/models", 401, "1.1", "192.168.1.10"
```

Почему это проблема:

- В тестах это fixtures, но scanners не всегда отличают fixtures от leaks.
- Лучше не использовать реальные LAN ranges.

Как исправить:

- IP заменить на TEST-NET:
  - `192.0.2.10`
  - `198.51.100.10`
  - `203.0.113.10`
- Пути заменить на `/home/example/genesis-vllm-patches` или `$HOME/genesis-vllm-patches`.
- Если тест проверяет именно RFC1918, явно назвать тест `test_rfc1918_fixture_allowed` и добавить узкую allowlist только для теста.

## 6. P2: слабые и недописанные реализации

### P2-1. 13 registry specs не имеют `apply_module`

Команда:

```text
python3 - <<'PY'
from vllm.sndr_core.dispatcher.spec import iter_patch_specs
for s in iter_patch_specs():
    if s.apply_module is None:
        print(s.patch_id, s.family, s.lifecycle, s.title)
PY
```

Список:

| Patch | Family | Lifecycle | Комментарий |
|---|---|---|---|
| `PN26b` | `attention.turboquant` | research | Sparse-V kernel research, нет apply module |
| `P1` | `quantization` | legacy | Legacy informational/runtime entry |
| `P17` | `moe` | legacy | Legacy informational/runtime entry |
| `P18b` | `attention.turboquant` | legacy | Legacy informational/runtime entry |
| `P20` | `attention.turboquant` | legacy | Legacy informational/runtime entry |
| `P23` | `kernels` | legacy | Legacy informational/runtime entry |
| `P29` | `tool_parsing` | legacy | Legacy informational/runtime entry |
| `P32` | `attention.turboquant` | legacy | Legacy informational/runtime entry |
| `P51` | `attention.turboquant` | legacy | Known spec-only |
| `P102` | `kv_cache` | experimental | Known spec-only |
| `PN60` | `compile_safety` | legacy | Known spec-only |
| `PN63` | `compile_safety` | legacy | Known spec-only |
| `PN64` | `kernels` | experimental | placeholder |

Почему это не P0:

- `apply.shadow --strict` считает это известным состоянием и проходит.

Почему это все равно нужно закрывать:

- Для production-документации каждый patch должен иметь один из статусов:
  - runnable apply module;
  - pure metadata;
  - coordinator;
  - retired tombstone;
  - research-only not-prod.
- Сейчас пользователю сложно понять, где код реально выполняется, а где registry-only.

Что сделать:

- В registry/spec добавить обязательный `execution_kind`: `source_patch | runtime_hook | coordinator | metadata_only | retired | research`.
- Для `metadata_only`/`retired` не требовать `apply_module`.
- Для `experimental` без `apply_module` требовать явный `production_status: blocked`.

### P2-2. PN26 sparse-V scaffold включается env flag'ом, но ничего не делает

Файл:

- `vllm/sndr_core/integrations/attention/turboquant/pn26_tq_unified_perf.py:345-365`

Текущий код:

```python
sparse_v_enabled = os.environ.get(
    "GENESIS_ENABLE_PN26_SPARSE_V", "0"
).strip().lower() in ("1", "true", "yes", "on")
sparse_v_status = "scaffold-only"
if sparse_v_enabled:
    sparse_v_status = "deferred"
    log.warning(...)
```

Проблема:

- Env flag выглядит как включение функционала, но реальный kernel path не реализован.
- В production это может быть воспринято как работающая оптимизация.

Как исправить:

- Переименовать флаг в `GENESIS_EXPERIMENTAL_PN26_SPARSE_V_SCAFFOLD=1`, пока нет kernel.
- Либо при включении текущего флага возвращать `failed`/`blocked`, а не `applied`.
- В registry поставить `implementation_status: scaffold`, `production_status: blocked`.

### P2-3. PN21 DFlash SWA частичный backport

Файл:

- `vllm/sndr_core/integrations/spec_decode/pn21_dflash_swa_support.py:296-301`

Текущий код:

```python
return "applied", (
    f"PN21 applied {applied} (DFlash SWA partial ... "
    f"qwen3_dflash.py model class deferred — wait for vllm#40898 merge "
    f"or apply manually. Composes with PN24."
)
```

Проблема:

- Возвращает `applied`, но текст говорит `partial`.
- Для operator'а это выглядит как полноценная поддержка DFlash SWA, хотя model-class enabler не встроен.

Как исправить:

- Статус оставить `applied`, но добавить machine-readable detail:
  - `implementation_status: partial`
  - `requires_manual_step: qwen3_dflash.py`
  - `production_status: review_required`
- В doctor/preflight вывести warning, если DFlash+SWA config включает PN21 без PN24/manual enabler.

### P2-4. PN79 конфликтует с PN59/PN54, но lifecycle migration отложена

Файл:

- `vllm/sndr_core/integrations/attention/gdn/pn79_inplace_ssm_state.py:42-47`

Текущий код:

```text
PN59 + PN54 → INTENDED for lifecycle: deprecated / retired...
both remain lifecycle: stable ... migration deferred
```

Проблема:

- В коде прямо зафиксировано, что registry lifecycle не соответствует архитектурному намерению.
- Conflicts защищают apply-time, но docs/roadmap/status могут показывать неверную зрелость PN54/PN59.

Как исправить:

- Если PN79 уже выбран как successor, перевести PN54/PN59 в `deprecated` или `superseded`.
- Добавить `superseded_by: PN79` в metadata.
- Если evidence еще недостаточно, оставить stable, но убрать "INTENDED" из runtime-файла и перенести в `docs/_internal/research/`.

### P2-5. P7 GDN dual-stream остается deferred из-за torch.compile fullgraph

Файл:

- `vllm/sndr_core/integrations/attention/gdn/p7_gdn_dual_stream.py:102-144`

Проблема:

- Patch присутствует, но default behavior всегда skipped.
- Реальный production path требует custom op:
  - `torch.library.define`
  - регистрация в `splitting_ops`
  - C++/CUDA-side stream orchestration.

Как исправить:

- Оставить как research/deferred, но убрать из user-facing "production gains".
- Создать отдельный task: `P7 custom-op implementation`.
- До custom op не включать в stable presets.

### P2-6. P60 GDN+ngram state recovery имеет deferred Triton kernel phase

Файл:

- `vllm/sndr_core/integrations/attention/gdn/p60_gdn_ngram_state_recovery.py:49-56`

Проблема:

- Phase 1 Python-only может не закрывать полный correctness bug.
- Комментарий говорит, что PR author считает kernel fix necessary.

Как исправить:

- Сделать `P60B_TRITON_KERNEL` реальным required companion для workloads `GDN + ngram + spec-decode`.
- Если kernel phase не реализован, preflight должен предупреждать: "P60 enabled without P60B full correctness".

### P2-7. PN54 содержит deferred ABI verification

Файл:

- `vllm/sndr_core/integrations/attention/gdn/pn54_gdn_contiguous_dedup.py:31-36`

Проблема:

- FlashInfer branch и gqa_interleaved branch сознательно отложены.
- Для Qwen3-Next/GQA путей возможна неполная оптимизация.

Как исправить:

- Отразить в patch metadata applicability:
  - `applies_to: not gqa_interleaved`
  - `not validated on FlashInfer branch`
- Добавить smoke test на anchor drift для `chunk_gated_delta_rule_fi`.

### P2-8. P70 хранит upstream TODO typo как load-bearing anchor

Файл:

- `vllm/sndr_core/integrations/spec_decode/p70_auto_strict_ngram.py:73-78`
- `vllm/sndr_core/integrations/spec_decode/p70_auto_strict_ngram.py:88`
- `vllm/sndr_core/integrations/spec_decode/p70_auto_strict_ngram.py:127`

Проблема:

- Комментарий upstream с typo является частью anchor.
- Если upstream исправит комментарий, patch перестанет матчиться.

Как исправить:

- Добавить второй anchor без TODO-comment.
- Anchor должен быть структурным: блок `if self.prompt_lookup_min > self.prompt_lookup_max` + следующий assignment, а не точная typo строка.
- Добавить drift test с upstream вариантом, где TODO исправлен.

### P2-9. Community scaffold создает рабочий no-op stub

Файл:

- `vllm/sndr_core/community/scaffold.py:142-173`

Текущий код:

```python
def apply(target=None, **kwargs):
    """No-op stub. Replace with the actual patch logic."""
    log.info("patch ... apply() called — stub no-op ...")
    return None
```

Это не баг, если:

- `publish_state: draft`;
- validator не разрешает draft попадать в production registry;
- docs ясно говорят, что scaffold нельзя публиковать как finished patch.

Что улучшить:

- В generated manifest добавить `production_status: blocked`.
- `sndr community validate --release` должен падать, если `apply()` содержит scaffold marker.

## 7. Упоминания AI/ИИ/Claude/Codex/ChatGPT

Важно: не все найденные строки нужно удалять. `OpenAI-compatible API`, `OpenAI Node SDK`, `wheels.vllm.ai`, `docs.vllm.ai`, модельные имена вроде `deepseek-ai/*` являются техническими именами и не относятся к авторству или AI-generated comments. Ниже перечислены места, которые стоит очистить или осознанно оставить.

### Нужно удалить или переписать в публичном коде/docs

| Файл:строка | Текущее содержание | Что сделать |
|---|---|---|
| `vllm/sndr_core/integrations/reasoning/pn58_spec_reasoning_boundary.py:65` | `Claude-assisted` в author line | Убрать vendor/AI attribution, оставить upstream PR и автора PR |
| `tests/legacy/test_pN30_ds_layout_fix.py:103` | `ChatGPT/Codex CLI cross-check` | Убрать из публичного test docstring |
| `CHANGELOG.md:904` | `third-party AI deep cross-audits` | Переписать как `independent external audit passes` |
| `CHANGELOG.md:1658` | `ChatGPT/Codex CLI` | Убрать attribution |
| `CHANGELOG.md:1754`, `:1763`, `:1770`, `:1780`, `:1785`, `:1790`, `:1793`, `:1795` | Codex/ChatGPT audit pass | Перенести в internal changelog или нейтрализовать |
| `.github/PULL_REQUEST_TEMPLATE.md:72` | `No Co-Authored-By: AI / Claude` | Можно заменить на `No automated-tool co-author trailers` |
| `assets/charts/_generate.py:895` | `AI cross-audits` | Переписать в chart caption |
| `assets/chat_templates/README.md:58` | `no AI-generated edits` | Переписать как `no generated edits`; оставить authorship policy без AI |
| `docs/CONTRIBUTING.md:528` | `AI translation help is fine` | Если публично не хотим AI mentions, заменить на `machine translation help` или перенести в maintainer note |
| `docs/OOM_RECIPES.md:69` | `codex residency analysis` | Переписать как `residency analysis` |
| `docs/reference/BOTS_SETUP.md:3`, `:30`, `:40`, `:48` | AI/security bots, Google AI code review, AI reviewers | Перенести в internal/reference или переименовать |
| `docs/upstream/DEEP_AUDIT_VLLM_NOONGHUNNA_2026-05-08_RU.md:11` | `Codex` | Если документ публичный, заменить на `local audit environment` |
| `docs/upstream/PR38_PATCHER_REWORK_PLAN_2026-05-07.md:7-8` | `.claude` paths | Перенести в internal или заменить на sanitized source note |
| `docs/reference/DEFERRED_P50_DEPLOY.md:50` | `Codex user_id` | Переписать как `request user_id` |

### Можно оставить как технические имена, если политика разрешает

- `README.md:208`, `vllm/sndr_core/cli/install.py:65`, `vllm/sndr_core/compat/presets.py:67`, `:392`, `:518` упоминают `Claude Code` как IDE agent category. Если цель - ноль AI mentions, заменить на `IDE coding agents`.
- `assets/chat_templates/qwen3.6-enhanced.jinja:9` и `qwen3.5-enhanced.jinja:9` содержат `Claude` в HuggingFace model path. Это имя внешней модели; удаление может сломать attribution/source link.
- `docs/MODELS.md:111-125` обсуждает Claude-named community model. Это модельное описание, не AI-authorship.
- `vllm/sndr_core/dispatcher/registry.py:1004` и `vllm/sndr_core/integrations/tool_parsing/pn56_qwen3coder_xml_fallback.py:10` упоминают `OpenAI Node SDK` как client compatibility. Это нужно оставить.

## 8. Нарушения связности и скрытые ошибки за другими ошибками

### Hidden-1. `make audit` падает раньше, чем становится виден полный security backlog

Связанные файлы:

- `Makefile` targets `audit`, `audit-security`
- `scripts/audit_no_hardcoded_paths.py`
- `scripts/security_scan.py`

Проблема:

- Gating `audit-public-paths` блокирует release.
- `audit-security` informational, поэтому 188 violations можно пропустить глазами.

Решение:

- Для release branch сделать `audit-security --public-release` gating.
- В `make evidence` выводить summary security violations даже если основной `audit` упал.

### Hidden-2. `launch --preflight-only` скрывает отсутствие Docker/NVIDIA/model

Связанные файлы:

- `vllm/sndr_core/cli/launch.py:390-422`
- `vllm/sndr_core/cli/launch.py:268-304`
- `vllm/sndr_core/deps/planners.py:117-281`

Проблема:

- `deps plan` знает о blocker'ах.
- `launch --check-deps` их не использует.
- digest auto skip добавляет второй false-positive pass.

Решение:

- Единый preflight должен вызывать:
  - `plan_changes()`;
  - host paths validation;
  - image digest strict validation;
  - model artifacts validation;
  - config pin consistency.

### Hidden-3. `memory explain` CLI безопасен, но direct API может вернуть unsafe recommendation

Связанные файлы:

- `vllm/sndr_core/runtime/memory_estimator.py:615-654`
- `vllm/sndr_core/cli/memory.py`

Решение:

- Перенести `UNKNOWN/actionable=false` в модель данных runtime estimator.

### Hidden-4. Engine boundary чистый физически, но compose и template создают ложные ожидания

Связанные файлы:

- `vllm/sndr_engine` empty
- `compose/docker-compose.test-v11.yml:17`, `:54`
- `pyproject-engine.toml:45-50`
- `pyproject-engine.toml:94-113`

Решение:

- Public core не должен монтировать/собирать engine skeleton в runtime examples.
- Если нужен placeholder namespace, добавить только `LICENSE-NOTICE` и documented no-code marker.

### Hidden-5. `bootstrap` surface выглядит готовым, но реальные configs не подключены

Связанные файлы:

- `vllm/sndr_core/cli/bootstrap.py`
- `vllm/sndr_core/model_configs/builtin/*.yaml`

Решение:

- Не считать installer реализованным, пока stable configs не имеют Y6/Y7/Y10 blocks и e2e tests.

## 9. Структурные рекомендации

### 9.1. Слои проекта

Текущая структура в целом правильная:

```text
vllm/sndr_core/       public runtime, configs, patch registry, CLI
vllm/sndr_engine/     empty reserved private overlay namespace
vllm/_genesis/        deleted legacy namespace
scripts/             dev/release utilities
tools/               optional tooling and examples
compose/             should contain portable compose only
docs/                public docs
docs/_internal/      internal audit, dashboards, server-specific plans
```

Что улучшить:

1. В `compose/` оставить только portable templates.
2. Все server-rig compose/log/audit evidence перенести в `docs/_internal/server/` или `examples/internal/`.
3. В `docs/upstream/` оставить только публично безопасные upstream notes.
4. В `docs/reference/` не хранить личные deploy paths.
5. В `docs/_internal/` можно хранить реальные server paths, но scanner должен явно различать public/internal.

### 9.2. Public/private boundary

Текущий курс правильный:

- Все уже опубликованные и существующие patch-наработки остаются в core.
- `sndr_engine` сейчас пустой.
- Core знает о возможном overlay, но не зависит от него.

Что не доделано:

- `pyproject-engine.toml` template должен быть самосогласованным или не должен лежать как buildable root artifact.
- Runtime examples не должны монтировать пустой engine.
- License gate должен иметь production trust anchor policy, а не dev/test anchor в ambiguous comments.

### 9.3. Installer/launcher/config automation

Минимальный production contract:

```text
sndr doctor-system
  -> validates Python, Docker, NVIDIA, NVIDIA Container Toolkit, vLLM pin, model artifacts

sndr bootstrap plan <preset>
  -> same data as deps plan, grouped by bootstrap scopes

sndr bootstrap apply <preset>
  -> idempotent install/configure with dry-run default

sndr service install <preset>
  -> renders systemd/docker-compose/podman-quadlet

sndr launch <preset> --preflight-only --check-deps
  -> must fail if host cannot actually run preset
```

Сейчас контракт частично есть, но не замкнут:

- `deps plan` работает.
- `launch --check-deps` не использует plan blockers.
- `bootstrap` не подключен к stable configs.
- `service` не подключен к stable configs.
- `proxmox` не подключен к stable configs.

## 10. Конкретный список исправлений

### Сначала P0/P1

1. Исправить `launch._run_check_deps()` так, чтобы он использовал `plan_changes()`.
2. Сделать `--preflight-only` strict по Docker/image digest, если config Docker-backed.
3. Синхронизировать `a5000-2x-35b-prod.yaml` pin'ы: `dev209` vs `dev93`.
4. Добавить `bootstrap:`, `service:`, `proxmox:` blocks хотя бы в два главных stable config:
   - `a5000-2x-35b-prod`
   - `a5000-2x-27b-int4-tq-k8v4`
5. Исправить `bootstrap._scope_to_plan_scope()`:
   - `python-runtime` -> `python`, `vllm`
   - `service` -> `service`
6. Очистить публичные docs/compose/scripts от `/home/sander`, `sander@`, `192.168.*`.
7. Очистить AI/Codex/Claude/ChatGPT mentions из public code/docs, кроме технически необходимых model/client names.
8. Обновить license comments/docstring под dev/test anchor.
9. Решить судьбу `pyproject-engine.toml`:
   - или добавить `vllm/sndr_engine/LICENSE-NOTICE`;
   - или перенести template в internal docs.

### Затем P2

10. Добавить `execution_kind` / `production_status` для specs без `apply_module`.
11. Перевести PN26 sparse-V env в explicit experimental/scaffold naming или сделать fail-fast.
12. PN21 partial DFlash SWA сделать machine-readable partial status.
13. PN79/PN54/PN59 lifecycle привести к фактической стратегии.
14. P7 custom op вынести в отдельную research task и убрать из production gain claims.
15. P60/P60B correctness contract явно проверить и документировать.
16. Memory estimator safety перенести из CLI в runtime layer.
17. Community scaffold release gate усилить: draft/no-op не может попасть в published release.

## 11. Acceptance checklist после исправлений

Обязательные команды:

```bash
python3 -m vllm.sndr_core.compat.cli self-test --json
python3 -m vllm.sndr_core.apply.shadow --strict
python3 -m vllm.sndr_core.cli patches prove --dead-detect --json
make audit-configs
make audit
make evidence
python3 scripts/security_scan.py --public-release
python3 -m vllm.sndr_core.cli deps plan --config a5000-2x-35b-prod --json
python3 -m vllm.sndr_core.cli launch a5000-2x-35b-prod --preflight-only --check-deps
python3 -m vllm.sndr_core.cli bootstrap plan a5000-2x-35b-prod --scope all
python3 -m vllm.sndr_core.cli service install a5000-2x-35b-prod --dry-run
python3 -m vllm.sndr_core.cli proxmox render a5000-2x-35b-prod
python3 -m vllm.sndr_core.cli memory explain a5000-2x-35b-prod --json
```

Ожидаемый production-ready критерий:

- `make evidence` PASS.
- `security_scan.py --public-release` PASS.
- `launch --preflight-only --check-deps` не дает false-positive pass на машине без Docker/NVIDIA/model.
- Stable configs имеют install/service/proxmox/runtime blocks.
- Нет публичных AI attribution mentions.
- Все partial/scaffold patches явно not-prod или имеют полноценный apply/test/evidence path.

## 12. Итоговая оценка готовности

Текущая оценка:

| Направление | Готовность | Комментарий |
|---|---:|---|
| Patch registry/apply integrity | 85% | Shadow/prove clean, но 13 specs без apply_module требуют классификации |
| Syntax/config health | 90% | AST/shell/config почти чистые; 1 bad JSON в `.history` |
| Public release hygiene | 55% | `make audit` падает, 188 security path violations |
| Launcher/preflight correctness | 60% | Есть false-positive pass при отсутствующих deps |
| Installer/bootstrap automation | 45% | CLI есть, configs не подключены |
| Service/Proxmox automation | 35% | CLI есть, builtin configs без Y6/Y10 blocks |
| Memory planning | 65% | CLI безопаснее, runtime API нужно усилить |
| License/private overlay readiness | 60% | Boundary правильный, trust-anchor docs/template требуют cleanup |
| Docs consistency | 55% | Много старых/internal/private упоминаний в public tree |

Финальная рекомендация: не расширять функционал до закрытия P0/P1. Сейчас выгоднее сделать релизную гигиену, замкнуть preflight/deps/bootstrap/service/proxmox контракт и убрать ложные PASS-сценарии. После этого можно возвращаться к новым patch features.
