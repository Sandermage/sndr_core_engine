# Текущий аудит кода и состояния проекта — 2026-05-13

Дата среза: `2026-05-13 02:34 EEST`  
Ветка: `dev`  
Commit: `052feba`  
Режим: анализ без изменения кода проекта; изменен только этот отчет.

## 1. Краткий вывод

Проект сейчас в существенно лучшем состоянии по ядру, чем в прошлых аудитах: Python-синтаксис чистый, shell-синтаксис чистый, YAML/JSON/TOML парсятся, `self-test` и `apply.shadow --strict` проходят, V2 invariant-chain доведен до Entry 34, `make evidence` содержит 34 gates.

Но release/production пока блокируется не синтаксисом, а несколькими слоями:

1. `make evidence` все еще падает из-за одного gating target: `audit`.
2. `audit-public-paths`, `audit-public-docs`, `audit-security`, `audit-docs-stale` показывают несогласованность public/private политики, старые команды, частные пути/IP, server-only имена контейнеров.
3. Есть реальные CLI-контрактные ошибки: `sndr config list --json` не возвращает JSON, `--include-tested` описан, но не реализован, вывод продолжает советовать старый `genesis model-config`.
4. Host/launcher слой не готов к out-of-box запуску на текущей машине: `~/.sndr/host.yaml` отсутствует, `models_dir` и остальные mount-переменные не резолвятся.
5. Engine/license boundary не полностью согласован: часть кода/документов говорит про entry-point overlay, часть кода все еще проверяет прямой `vllm.sndr_engine` import/spec.
6. Proof-система сейчас зеленая по static checks, но artifact coverage равен `0%`; это надо разделить в терминах release gate.

## 2. Проверки, которые прошли

| Проверка | Результат |
|---|---:|
| AST parse `vllm`, `scripts`, `tools`, `tests` | `812` Python файлов, `0` ошибок |
| `bash -n` по `scripts/**/*.sh`, `tools/**/*.sh` | `64` shell-файла, `0` ошибок |
| Parse JSON/TOML/YAML | `42 json`, `4 toml`, `64 yaml`, `0` ошибок |
| `python3 -m vllm.sndr_core.compat.cli self-test --json` | `8/8 pass` |
| `python3 -m vllm.sndr_core.apply.shadow --strict` | `CLEAN`, `136` specs, `123/136` with `apply_module` |
| `make audit-configs` | `11/11` presets compose cleanly |
| `make audit-dirty-state-dev` | `853` tracked entries accepted by dev policy |
| `make audit-patches-prove-all` внутри `make evidence` | static proof `136/136` |

## 3. Текущий dirty-state

Raw `git status --short --untracked-files=all`:

```text
total 1241
?? 797
 D 384
 M 60
```

По крупным группам:

```text
396 vllm/sndr_core
377 vllm/_genesis
350 tests
36 scripts
16 tools
15 docs
13 sponsor-site
8 .github
8 compose
```

Вывод: миграция `_genesis` → `sndr_core` выглядит технически проведенной, но рабочее дерево еще не приведено к release-представлению. Пока это состояние не зафиксировано или не разложено по ожидаемым коммитам, любой audit/gate будет смешивать реальные дефекты с миграционным шумом.

## 4. P0 — release blockers

### P0-1. `make evidence` все еще блокирует release через `audit`

Команда:

```bash
make evidence
```

Факт:

```text
make evidence — 34 gate(s)
✗ [GATING] audit
✗ RELEASE BLOCKED — 1 gating gate(s) failed
```

Почти все новые V2 gates проходят, включая:

- `audit-v2-env-keys`
- `audit-v2-required-fields`
- `audit-v2-id-consistency`
- `audit-v2-license-coverage`
- `audit-v2-cross-reference`
- `audit-v2-vllm-pin-consistency`
- `audit-v2-patch-lifecycle`
- `audit-v2-hardware-sanity`
- `audit-v2-patch-dependencies`
- `audit-v2-capability-coverage`
- `audit-v2-versions-pin-format`
- `audit-v2-quantization-coverage`
- `audit-v2-context-length-sanity`
- `audit-v2-runtime-image-pin`
- `audit-v2-network-port-consistency`

Проблема находится в legacy aggregate:

```makefile
Makefile:71-86
audit-public-paths:
	@bad=$$(rg -n "192\.168\.1\.10|/home/sander|sander@|User=sander" \
	    README.md docs/ scripts/ tools/ benchmarks/ vllm/ \
	    --glob '!docs/_internal/**' \
	    --glob '!**/_archive/**' \
	    --glob '!**/_internal/**' \
	    --glob '!tests/integration/baselines/**' \
	    2>/dev/null || true); \
```

Почему это важно:

- `audit-public-paths` использует raw `rg` и сканирует `docs/upstream/`, `docs/reference/`, `scripts/`, `tools/`, `benchmarks/`, `vllm/` без общей allowlist-политики.
- `scripts/audit_public_docs.py` при этом считает `docs/upstream/`, `docs/reference/`, `_archive/` intentional/internal/historical:

```python
scripts/audit_public_docs.py:16-17
Allowlist (intentionally internal/historical):
  docs/_internal/, docs/upstream/, docs/reference/, _archive/
```

- `scripts/security_scan.py` тоже имеет свою allowlist:

```python
scripts/security_scan.py:39-49
ALLOWLIST_PATHS = [
    "docs/_internal/",
    "docs/upstream/",
    "docs/reference/",
    "_archive/",
    "tests/",
    "scripts/security_scan.py",
    "scripts/generate_sbom.py",
    "scripts/generate_trust_anchor.py",
    "Makefile",
]
```

Итог: разные audit-слои по-разному понимают, что является public surface. Это не просто “много строк надо почистить”, а нарушение единой release-политики.

Как исправить:

1. Убрать raw `rg` из `Makefile:audit-public-paths`.
2. Сделать единый Python scanner для public/private boundary.
3. Вынести allowlist в один файл, например `scripts/audit_policy.py` или `docs/_internal/audit_allowlist.yaml`.
4. Разделить статусы:
   - `public_docs`: README + `docs/*.md`, которые реально публикуются;
   - `historical_docs`: `docs/upstream`, `docs/reference`;
   - `active_code`: `vllm/sndr_core`, `scripts`, `tools`, `benchmarks`;
   - `operator_local`: server-only compose/smoke файлы.

Acceptance:

```bash
make audit
make evidence
```

должны перестать падать на policy drift.

### P0-2. Public docs still leak private paths/IPs and retired commands

Команды:

```bash
make audit-public-docs
make audit-security
make audit-docs-stale
```

Факты:

```text
audit-public-docs: FAIL — 93 total violation(s)
audit-security: FAIL — 191 total violations
audit-docs-stale: FAIL — 56 stale token(s)
```

Примеры точных строк:

```markdown
docs/REASONING_CONTENT_CONTRACT.md:112
HOST=http://192.168.1.10:8101 make smoke-content
```

```markdown
docs/BENCHMARK_GUIDE.md:118-119
#       -v /home/sander/.cache/huggingface:/root/...      → your HF cache (or remove)
#       -v /home/sander/genesis-vllm-patches/...:/...:ro  → your repo path
```

```markdown
README.md:624
genesis doctor
```

```markdown
README.md:627
docker logs vllm-server-mtp-test | grep -A 200 'structured boot summary'
```

```markdown
README.md:657-663
bash scripts/start_27b_int4_TQ_k8v4.sh
bash scripts/start_35b_fp8_PROD.sh
bash scripts/start_27b_int4_fp8_e5m2_long_256K.sh
bash scripts/start_35b_fp8_DFLASH.sh
```

Проверка показала, что эти `scripts/start_*.sh` файлы отсутствуют:

```text
missing scripts/start_27b_int4_TQ_k8v4.sh
missing scripts/start_35b_fp8_PROD.sh
missing scripts/start_27b_int4_fp8_e5m2_long_256K.sh
missing scripts/start_35b_fp8_DFLASH.sh
```

Как исправить:

- README quickstart должен использовать текущий canonical CLI:

```bash
python3 -m vllm.sndr_core.cli host init
python3 -m vllm.sndr_core.cli launch prod-35b --preflight-only
python3 -m vllm.sndr_core.cli launch prod-35b
```

или короткий console entrypoint, если он гарантированно установлен:

```bash
sndr host init
sndr launch prod-35b --preflight-only
sndr launch prod-35b
```

- `vllm-server-mtp-test` заменить на `<container-name>` или derive из rendered config.
- `192.168.1.10` заменить на `127.0.0.1`, `<host>`, или profile example.
- `/home/sander` заменить на `$HOME`, `<your-home>`, `${models_dir}`.

### P0-3. `audit-public-docs` D-6 ловит реальные TODO/placeholder, но также смешивает их с техническими названиями патчей

Текущее правило:

```python
scripts/audit_public_docs.py:111-114
def check_d6_no_unresolved_todos(files: list[Path]) -> list[str]:
    """D-6: TODO + placeholder + NotImplementedError in public docs."""
    pat = re.compile(r"TODO\(.*\)|placeholder|NotImplementedError")
    return _grep(pat, files)
```

Примеры:

```markdown
README.md:27
license gate (placeholder pubkey until offline keygen ceremony)
```

```markdown
README.md:280
PN64 | Marlin MoE sm_120 placeholder
```

Проблема:

- `placeholder pubkey` — реальный release/security blocker.
- `PN64 placeholder` может быть осознанным lifecycle/status названием патча, а не незавершенной документацией.

Как исправить:

- Разделить rule на:
  - `unresolved_placeholder`: блокирует release;
  - `known_placeholder_patch`: allowlist по `patch_id` + lifecycle + explanation.
- Для PN64 в public docs лучше писать не просто `placeholder`, а `experimental SM120 provisional profile, env-gated, needs empirical sweep`.

## 5. P1 — функциональные ошибки CLI и launcher

### P1-1. `sndr config list --json` не возвращает JSON

Команда:

```bash
python3 -m vllm.sndr_core.cli config list --json
```

Факт:

```text
rc 0
json_parse_error JSONDecodeError Expecting value: line 1 column 1 (char 0)
stdout_head 'Genesis model configs (11 total · 9 working · 2 tested)...'
```

Код:

```python
vllm/sndr_core/cli/config.py:508-522
def run_list(args: argparse.Namespace) -> int:
    from vllm.sndr_core.compat.model_config_cli import cmd_list as _cmd_list

    bridged_ns = argparse.Namespace(
        json=getattr(args, "json", False),
        include_tested=False,
    )
    rc = _cmd_list(bridged_ns)
```

Но bridged implementation не использует `args.json`:

```python
vllm/sndr_core/compat/model_config_cli.py:53-113
def cmd_list(args) -> int:
    configs = load_all()
    ...
    print(...)
    return 0
```

Последствие:

- CLI обещает machine-readable JSON, но возвращает таблицу.
- Любая automation/CI, которая вызывает `sndr config list --json`, будет падать при `json.loads`.

Как исправить:

В `cmd_list` добавить JSON branch до table rendering:

```python
if getattr(args, "json", False):
    payload = [...]
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0
```

Acceptance:

```bash
python3 -m vllm.sndr_core.cli config list --json | python3 -m json.tool >/dev/null
```

### P1-2. `--include-tested` описан в коде, но не реализован и логически заблокирован

Код говорит, что `--include-tested` должен менять поведение:

```python
vllm/sndr_core/compat/model_config_cli.py:59-62
# Split working configs from tested/QA configs. By default, tested
# configs render in a separate section so they do NOT pollute the
# "what should I actually launch" view. --include-tested merges
# everything into one block (operator opt-in).
```

Но условие всегда истинное:

```python
vllm/sndr_core/compat/model_config_cli.py:99
if tested and (include_tested or True):
```

И parser вообще не добавляет `--include-tested`:

```python
vllm/sndr_core/compat/model_config_cli.py:1204-1205
sub.add_parser("list", help="enumerate all configs").set_defaults(
    func=cmd_list)
```

Команда:

```bash
python3 -m vllm.sndr_core.cli model-config list --include-tested
```

Факт:

```text
genesis model-config: error: unrecognized arguments: --include-tested
```

Как исправить:

- Либо удалить обещание `--include-tested` и оставить tested section всегда отдельным.
- Либо добавить argument и сделать реальную merge-логику:

```python
p_list = sub.add_parser("list", help="enumerate all configs")
p_list.add_argument("--include-tested", action="store_true")
```

и убрать `or True`.

### P1-3. Новый CLI все еще печатает старые `genesis model-config` команды

Точные строки:

```python
vllm/sndr_core/compat/model_config_cli.py:106-112
print(
    "\n  Use:  genesis model-config validate <key>     # schema + audit"
    "\n        genesis model-config preflight <key>    # env check"
    "\n        genesis model-config launch <key>       # boot"
    "\n        genesis model-config diagnose <key>     # runtime check"
    "\n        genesis model-config verify <key>       # bench vs reference"
)
```

Еще места:

```python
vllm/sndr_core/compat/model_config_cli.py:308
#    Render via:  genesis model-config render {cfg.key} --runtime bare_metal
```

```python
vllm/sndr_core/compat/model_config_cli.py:433
# Deploy via:  kubectl apply -f - <<< "$(genesis model-config render {cfg.key} --runtime kubernetes)"
```

```python
vllm/sndr_core/compat/model_config_cli.py:901-903
print(f"  Edit it, then `genesis model-config launch {args.key}`.")
print(f"  After bench, `genesis model-config bench-and-update {args.key}` ...")
```

```python
vllm/sndr_core/compat/model_config_cli.py:1197-1200
p = argparse.ArgumentParser(
    prog="genesis model-config",
    description="Manage vetted model launch configurations",
)
```

Проблема:

- `make audit-docs-stale` уже блокирует old `genesis doctor/verify/migrate`.
- Но сам CLI все еще генерирует старую командную поверхность.
- Это ломает UX и делает docs cleanup нестабильным: пользователь копирует старую команду из актуального CLI.

Как исправить:

- `prog="sndr model-config"` или `prog="python3 -m vllm.sndr_core.cli model-config"` в fallback context.
- Все generated comments заменить на `sndr model-config ...`.
- Если `genesis` оставляется как legacy alias, явно писать `legacy alias: genesis ...`, но primary должен быть `sndr`.

### P1-4. Host profile отсутствует, launch preflight не может резолвить canonical mounts

Команда:

```bash
python3 -m vllm.sndr_core.cli launch prod-35b --preflight-only
```

Факт:

```text
render failed: SchemaError: resolve_symbolic_mounts: unknown variable 'models_dir'
Available: ['cache_root', 'hf_cache'].
Update host config (~/.sndr/host.yaml) or config YAML to use absolute path.
```

Host doctor:

```bash
python3 -m vllm.sndr_core.cli host doctor --json
```

Факт:

```json
{
  "host_yaml": "/Users/sander/.sndr/host.yaml",
  "findings": [
    {
      "severity": "FAIL",
      "name": "host_yaml_present",
      "message": "/Users/sander/.sndr/host.yaml does not exist — run `sndr host init`"
    }
  ],
  "fails": 1,
  "warns": 0
}
```

Host detect на текущей машине:

```json
"paths": {
  "models_dir": null,
  "hf_cache": "/Users/sander/.cache/huggingface",
  "triton_cache": null,
  "compile_cache": null,
  "genesis_src": null,
  "plugin_src": null
}
```

Код auto-detect:

```python
vllm/sndr_core/model_configs/host.py:51-58
_DEFAULT_MODELS_CANDIDATES = [
    "/srv/models",
    "/data/models",
    "/opt/models",
    "/var/lib/models",
    str(Path.home() / "models"),
    str(Path.home() / ".cache/genesis/models"),
]
```

```python
vllm/sndr_core/model_configs/host.py:84-94
_DEFAULT_GENESIS_SRC_CANDIDATES = [
    str(Path.home() / "genesis-vllm-patches/vllm/sndr_core"),
    "/opt/genesis-vllm-patches/vllm/sndr_core",
    str(Path.home() / ".genesis/genesis-vllm-patches/vllm/sndr_core"),
]
```

Проблема:

- Workspace находится в `/Users/sander/Documents/Visual Studio Code/genesis-vllm-patches`, но auto-detect ищет только `~/genesis-vllm-patches/...`.
- `host init` на такой машине не найдет `genesis_src` и `plugin_src`, хотя проект открыт локально.
- Hardware YAML требует шесть mount vars:

```yaml
vllm/sndr_core/model_configs/builtin/hardware/a5000-2x-24gbvram-16cpu-128gbram.yaml:45-50
- "${models_dir}:/models:ro"
- "${hf_cache}:/root/.cache/huggingface:ro"
- "${triton_cache}:/root/.triton/cache"
- "${compile_cache}:/root/.cache/vllm/torch_compile_cache"
- "${genesis_src}:/usr/local/lib/python3.12/dist-packages/vllm/sndr_core:ro"
- "${plugin_src}:/plugin:ro"
```

Как исправить:

1. `host detect` должен добавлять текущий checkout root как candidate, если команда запущена из repo.
2. `launch --preflight-only` должен собирать все missing vars за один проход, а не падать на первом `models_dir`.
3. `host init` должен писать starter config с commented missing fields и явным checklist.
4. Для локальной dev-машины без GPU нужно иметь `--target-host server`/remote profile или `--host-yaml <path>`.

Acceptance:

```bash
python3 -m vllm.sndr_core.cli host init --path /tmp/sndr-host.yaml --force
python3 -m vllm.sndr_core.cli launch prod-35b --preflight-only --host-yaml /tmp/sndr-host.yaml
```

или соответствующий supported flow, если `--host-yaml` еще не реализован.

## 6. P1 — engine/license boundary

### P1-5. Engine overlay policy в документах и коде расходится

`pyproject-engine.toml` говорит, что будущий engine должен регистрироваться через entry point:

```toml
pyproject-engine.toml:80-84
# Future entry point group (designed in roadmap §15.1, not yet wired).
# When the private overlay materializes, it registers its `register()`
# callback under this group; `vllm.sndr_core.license.engine_available()`
# discovers it via `importlib.metadata.entry_points`.
[project.entry-points."sndr.engine.overlay"]
```

Но текущий `is_engine_installed()` проверяет import spec:

```python
vllm/sndr_core/license.py:736-766
def is_engine_installed() -> EngineDetection:
    ...
    spec = importlib.util.find_spec("vllm.sndr_engine")
    ...
    return EngineDetection(installed=True, module_name="vllm.sndr_engine", version=version)
```

Отдельно `_engine_overlay_available()` все еще импортирует `vllm.sndr_engine.engine_available`:

```python
vllm/sndr_core/license.py:197-215
def _engine_overlay_available() -> bool:
    ...
    from vllm.sndr_engine import engine_available
```

И bundle tier gate делает raw import:

```python
vllm/sndr_core/bundles/_common.py:64-76
if tier == "engine":
    ...
    try:
        import vllm.sndr_engine
    except ImportError:
        return "skipped", ...
```

Проблема:

- Если завтра появится public skeleton `vllm.sndr_engine`, bundle gate может пропустить engine-tier bundle только по факту import, без `engine_available()` и без license.
- Если будущий private overlay будет жить не под `vllm.sndr_engine`, а как entry point `sndr.engine.overlay`, текущий core его не увидит в `is_engine_installed()`.
- Это противоречит проектной цели: core должен знать, что engine существует, но не зависеть от его namespace.

Как исправить:

1. Сделать единый API:

```python
engine_status = discover_engine_overlay()
```

который проверяет entry points, version compatibility и license state.

2. `bundles/_common.py` должен вызывать этот API, а не `import vllm.sndr_engine`.
3. `license.status` должен показывать:
   - `engine_package_detected`
   - `engine_overlay_registered`
   - `engine_available`
   - `license_valid`

### P1-6. `pyproject-engine.toml` ссылается на файлы пакета, которого сейчас нет

Факт:

```text
find vllm -maxdepth 2 -type d -name 'sndr*'
vllm/sndr_core
```

`vllm/sndr_engine/` отсутствует.

Но template указывает:

```toml
pyproject-engine.toml:46-50
# Source of truth: vllm/sndr_engine/version.py SNDR_ENGINE_VERSION
version = "11.0.0"
description = "SNDR Engine — reserved namespace for future private overlay."
readme = "vllm/sndr_engine/LICENSE-NOTICE"
```

и:

```toml
pyproject-engine.toml:94-112
[tool.setuptools.packages.find]
include = [
    "vllm.sndr_engine*",
]

[tool.setuptools.package-data]
"vllm.sndr_engine" = [
    "LICENSE-NOTICE",
]
```

`.gitignore` при этом игнорирует:

```gitignore
.gitignore:86-87
vllm/sndr_engine/
pyproject-engine.toml
```

Проблема:

- Если `pyproject-engine.toml` является только private-template, его не надо держать как будто он buildable в public tree.
- Если он должен быть buildable skeleton, нужны `vllm/sndr_engine/__init__.py`, `version.py`, `LICENSE-NOTICE` и корректная `.gitignore` политика.

Рекомендация:

- Для текущей стратегии лучше вариант B: не публиковать `vllm.sndr_engine` вообще.
- Тогда README/INSTALL должны говорить: “engine package absent in public repo; future private overlay via entry point”.
- `pyproject-engine.toml` либо перенести в `docs/_internal/templates/`, либо оставить с явной пометкой `not buildable in public tree`.

### P1-7. License trust anchor: комментарий говорит “zero placeholder”, код содержит dev/test ключ

Комментарий:

```python
vllm/sndr_core/license.py:63-66
# Public key (Ed25519, raw 32 bytes, base64url). Replace with the real
# production key once the offline signing rig is set up. Until then the
# placeholder zero-key is documented as "rejects all signatures" — so
# anything not a legacy plain key falls through to NO_KEY.
```

Фактический ключ:

```python
vllm/sndr_core/license.py:73-89
# DEV/TEST trust anchor ...
# the private key was exposed in stdout under the old flow ...
_TRUST_ANCHOR_PUBKEY_B64URL = (
    "iSk29MUb9HldKokPRyOG7bAjwYaQdgqYsS17yfskE8s"
)
```

Проверка placeholder:

```python
vllm/sndr_core/license.py:96-104
def _is_placeholder_anchor() -> bool:
    ...
    return raw == b"\x00" * 32
```

Проблема:

- Код уже не использует zero placeholder, поэтому предупреждение `_maybe_log_placeholder_warning()` не сработает.
- Комментарий прямо говорит, что private key старого flow был exposed.
- Если подписанный токен создан этим dev/private key, `_verify_signed_token()` может его принять как валидный.

Как исправить:

- Для public core до настоящей key ceremony лучше поставить zero-key и оставить signed verification fail-closed.
- Dev/test anchor принимать только через env override, например `SNDR_DEV_TRUST_ANCHOR_PUBKEY`, и только если `SNDR_ALLOW_DEV_LICENSE_ANCHOR=1`.
- README строку про `placeholder pubkey` привести к факту: либо реально placeholder, либо “development anchor, not production”.

## 7. P1 — patch proof и artifact semantics

### P1-8. Static proof green, но artifact coverage равен 0%

Команда:

```bash
python3 -m vllm.sndr_core.cli patches prove --dead-detect
```

Факт:

```text
proven (has passing static artefact): 0
dead   (no passing artefact):         136
coverage:                             0.0%
```

При этом:

```makefile
Makefile:130-131
audit-patches-prove-all:
	@$(PYTHON) -m vllm.sndr_core.cli patches prove --all --no-write
```

и `make evidence` считает это gating proof:

```python
scripts/make_evidence.py:75-77
Gate("audit-patches-prove-all", "audit-patches-prove-all",
     "§6.8 every PATCH_REGISTRY entry passes static checks",
     "gating"),
```

Проблема:

- `audit-patches-prove-all` проверяет static checks, но с `--no-write` не создает proof artifacts.
- `dead-detect` проверяет artifacts, поэтому показывает `0%`.
- Для оператора это выглядит как противоречие: “proof pass 136/136” и одновременно “0 proof artifacts”.

Еще один риск:

```python
vllm/sndr_core/cli/patches.py:1058-1062
proof = build_proof_for_patch(patch_id)
if not args.no_write and proof.static_checks[0].passed:
    write_proof_artefact(proof, out_dir)
ok = proof.static_passed
```

Условие записи artifact смотрит только на `proof.static_checks[0].passed`, а не на `proof.static_passed`. Если первый check прошел, а следующий упал, можно записать failing/partial artifact.

Как исправить:

1. Для release сделать два разных статуса:
   - `static_proof_pass`: `136/136`;
   - `proof_artifact_coverage`: `0/136` или фактическое значение.
2. В `_run_prove_all()` заменить условие записи на:

```python
if not args.no_write and proof.static_passed:
    write_proof_artefact(proof, out_dir)
```

3. Либо `make evidence` должен запускать `patches prove --all` без `--no-write` в dedicated evidence dir, либо `dead-detect` не должен считаться признаком провала до этапа artifact ceremony.

## 8. P2 — runtime/automation issues

### P2-1. Некоторые scripts сами ставят зависимости во время выполнения

Пример:

```python
scripts/bench_suffix_sweep.py:45-49
try:
    import requests
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "requests"])
    import requests
```

Пример:

```bash
scripts/validate_integration.sh:135
docker exec "$CONTAINER" bash -c "pip install pytest -q 2>/dev/null || true"
```

Почему это плохо:

- Нерепродуцируемый запуск: среда меняется в момент теста.
- Сетевой доступ становится скрытой зависимостью.
- CI/offline/server audit может проходить или падать в зависимости от PyPI.
- Supply-chain risk: runtime test скачивает пакет без pin/hash.

Как исправить:

- Перенести зависимости в `requirements-dev.lock`, optional extras или container image.
- В скрипте делать fail-fast с понятным сообщением:

```python
raise SystemExit("missing dependency: requests. Install vllm-sndr-core[bench].")
```

### P2-2. Benchmark harness имеет private LAN endpoint по умолчанию

Код:

```python
benchmarks/harness/_common.py:57-61
p.add_argument(
    "--endpoint",
    default=os.environ.get(
        "GENESIS_BENCH_ENDPOINT",
        "http://192.168.1.10:8000/v1",
    ),
)
```

Проблема:

- Пользователь без env override по умолчанию будет бить в чужой private endpoint.
- Это противоречит уже исправленным smoke scripts, где default переведен на localhost.

Как исправить:

```python
default=os.environ.get("GENESIS_BENCH_ENDPOINT", "http://127.0.0.1:8000/v1")
```

### P2-3. Hardcoded server container name еще живет в runtime/doctor/scripts

Примеры:

```python
vllm/sndr_core/compat/doctor.py:504-505
# club#34 + club#43 — log-driven, fire only if container logs available.
log_text = fetch_container_logs(container_name="vllm-server-mtp-test")
```

```python
scripts/bench_suffix_sweep.py:52-55
# F-017 fix ...
CONTAINER = os.environ.get("GENESIS_CONTAINER", "vllm-server-mtp-test")
```

```bash
scripts/validate_integration.sh:38-44
# Defaults match scripts/launch/start_*_PROD.sh + compose/docker-compose.integration.yml.
CONTAINER=${CONTAINER:-vllm-server-mtp-test}
```

```bash
scripts/moe_lookup_helper.sh:40
CONTAINER="${CONTAINER:-vllm-server-mtp-test}"
```

Проблема:

- Для server rig это удобно, но для public/community release это server-only default.
- `doctor.py` хуже остальных: там вообще нет env/config override в месте вызова.

Как исправить:

- В `doctor.py` брать container name из host profile, launch runtime spec или env `SNDR_CONTAINER`.
- В scripts оставить env override, но default сделать `<unset>` и требовать явного `CONTAINER=...`, если это не localhost-only smoke.

### P2-4. `compose/docker-compose.test-v11.yml` содержит server-only paths и монтирует отсутствующий `sndr_engine`

Файл:

```yaml
compose/docker-compose.test-v11.yml:50-57
- /nfs/genesis/models:/models:ro
- /home/sander/.cache/huggingface:/root/.cache/huggingface:ro
- /home/sander/genesis-vllm-patches-v11/vllm/sndr_core:/usr/local/lib/python3.12/dist-packages/vllm/sndr_core:ro
- /home/sander/genesis-vllm-patches-v11/vllm/sndr_engine:/usr/local/lib/python3.12/dist-packages/vllm/sndr_engine:ro
- /home/sander/Genesis_Project/vllm_engine/triton-cache-test-v11:/root/.triton/cache
- /home/sander/Genesis_Project/vllm_engine/compile-cache-test-v11:/root/.cache/vllm/torch_compile_cache
```

Факт:

```text
find vllm -maxdepth 2 -type d -name 'sndr*'
vllm/sndr_core
```

`vllm/sndr_engine` локально отсутствует.

Как исправить:

- Если файл только серверный, перенести в `docs/_internal/server/` или `compose/_operator_examples/` и исключить из public gates.
- Если он должен быть portable example, заменить пути на `${models_dir}`, `${hf_cache}`, `${genesis_src}`, убрать `sndr_engine` mount до появления package.

## 9. P2 — stale code comments and docs inside active modules

### P2-5. `vllm/sndr_core/__init__.py` описывает старую стадию миграции

Код:

```python
vllm/sndr_core/__init__.py:23-26
Migration status (started 2026-05-07, etap 1):
  Stage 1 (CURRENT) — skeleton only. All code still lives in vllm/_genesis/.
  Stages 2-13      — progressive migration; modules move INTO sndr_core/.
  Final            — vllm/_genesis/ becomes thin forward-alias of sndr_core.
```

Факт:

- `_genesis` удален из рабочего дерева.
- Основной код физически находится в `vllm/sndr_core`.

Как исправить:

Обновить docstring:

```text
Migration status:
  v11 current — canonical implementation lives in vllm/sndr_core.
  vllm/_genesis is removed from public tree; compatibility is handled through
  tests/docs only where explicitly allowlisted.
```

### P2-6. `version.py` содержит конфликтующий back-compat narrative

Код:

```python
vllm/sndr_core/version.py:5-7
GENESIS_VERSION is preserved as alias for back-compat — any code that
reads `from vllm._genesis.__version__ import GENESIS_VERSION` continues
to work after the migration completes (vllm/_genesis becomes forward shim).
```

Но ниже:

```python
vllm/sndr_core/version.py:26-28
# v11.0.0 (2026-05-08): PR38 cleanup release. `vllm/_genesis/` shim
# layer removed entirely. All implementation lives at
# `vllm/sndr_core/`;
```

Проблема:

- Верхний docstring обещает forward shim, нижний changelog говорит, что shim удален.

Как исправить:

- Оставить `GENESIS_VERSION` как alias внутри `sndr_core`.
- Убрать обещание импорта из `vllm._genesis.__version__`, если shim реально удален.

### P2-7. `cmd_list` error message указывает на удаленный `_genesis` path

Код:

```python
vllm/sndr_core/compat/model_config_cli.py:53-57
def cmd_list(args) -> int:
    configs = load_all()
    if not configs:
        print("(no configs found in vllm/_genesis/model_configs/builtin/)")
        return 0
```

Как исправить:

```text
(no configs found in vllm/sndr_core/model_configs/builtin/ or user overlay)
```

## 10. P3 — низкоприоритетные неточности и улучшения

### P3-1. `resolve_symbolic_mounts()` не нормализует `~`

Код:

```python
vllm/sndr_core/model_configs/schema.py:143-190
def resolve_symbolic_mounts(...):
    ...
    return host_paths[var_name]
```

Документация местами советует:

```yaml
models_dir: ~/models
```

Если `host.yaml` содержит `~/models`, Docker mount может получить literal `~`, а не absolute path. Сейчас docstring говорит “absolute paths”, но CLI/docs должны это enforce.

Решение:

- `load_host_config()` может expanduser + resolve for `paths`.
- `host doctor` должен fail/warn, если path не absolute после expand.
- Docs должны показывать `$HOME/models` или `/absolute/path`, не `~/models`.

### P3-2. `curl | bash` остается public install path

Примеры:

```markdown
README.md:84
curl -sSL https://raw.githubusercontent.com/Sandermage/genesis-vllm-patches/main/install.sh | bash
```

Это удобно, но для production/security posture лучше иметь:

- pinned tag install;
- checksum/signature;
- `python -m pip install vllm-sndr-core==...`;
- `curl -fsSLO ... && sha256sum -c ... && bash install.sh`.

Не обязательно блокировать сейчас, но для quality/security standards это желательно.

## 11. Что сейчас не является проблемой

1. Синтаксических Python ошибок не найдено.
2. Shell syntax ошибок не найдено.
3. YAML/JSON/TOML parse ошибок не найдено.
4. `PATCH_REGISTRY` schema/lifecycle/category/predicate self-test проходит.
5. `apply.shadow --strict` чистый: unexpected divergence нет.
6. V2 config composition проходит по 11 presets.
7. V2 invariant gates Entry 31-34 проходят.

## 12. Рекомендуемый порядок исправлений

### Шаг 1 — закрыть release blocker

Цель:

```bash
make audit
make evidence
```

не должны падать.

Действия:

1. Переписать `Makefile:audit-public-paths` на структурированный Python scanner.
2. Единообразно применить allowlist к `docs/upstream`, `docs/reference`, `_archive`, scanner/self-test файлам.
3. Redact реальные public leaks в README/docs/scripts/benchmarks.

### Шаг 2 — починить CLI contracts

1. Реализовать JSON branch для `config list --json`.
2. Удалить или реализовать `--include-tested`.
3. Заменить user-facing `genesis model-config` на `sndr model-config`.
4. Обновить `prog="genesis model-config"`.

### Шаг 3 — привести host/launch к out-of-box flow

1. `host detect` должен находить текущий checkout.
2. `launch --preflight-only` должен показывать все missing vars.
3. Добавить удобный flow для локального Mac + remote GPU server.
4. Убрать silent assumption, что пользователь вручную знает `models_dir`, `genesis_src`, `plugin_src`.

### Шаг 4 — выровнять engine/license boundary

1. Выбрать финальную стратегию: no public `vllm.sndr_engine` package сейчас.
2. Engine detection перевести на entry point overlay, а не import/spec.
3. Bundle tier gate заменить на общий license/engine status API.
4. `pyproject-engine.toml` либо перенести в template/internal, либо сделать buildable skeleton.
5. License trust anchor вернуть к fail-closed placeholder до production key ceremony.

### Шаг 5 — proof artifacts

1. Исправить `proof.static_checks[0].passed` → `proof.static_passed`.
2. Разделить static proof и artifact proof в report/CLI.
3. Сгенерировать artifacts для release-critical patches или явно объявить artifact stage deferred.

## 13. Acceptance checklist после исправлений

```bash
python3 - <<'PY'
import ast
from pathlib import Path
for root in ['vllm','scripts','tools','tests']:
    for f in Path(root).rglob('*.py'):
        ast.parse(f.read_text(encoding='utf-8'), filename=str(f))
print('AST OK')
PY

python3 -m vllm.sndr_core.compat.cli self-test --json
python3 -m vllm.sndr_core.apply.shadow --strict
python3 -m vllm.sndr_core.cli config list --json | python3 -m json.tool >/dev/null
python3 -m vllm.sndr_core.cli host doctor --json
python3 -m vllm.sndr_core.cli launch prod-35b --preflight-only
make audit
make audit-public-docs
make audit-security
make audit-docs-stale
make evidence
```

Для server-side production readiness отдельно:

```bash
sndr launch prod-35b --preflight-only --target <server-profile>
sndr bench smoke --preset prod-35b --max-seconds 60
```

GPU smoke не запускался в этом аудите.

