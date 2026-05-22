# Migration map: v7 → v11 working-tree divergence

Дата: 2026-05-12 (Этап 8 закрытие MASTER_REMEDIATION_PLAN)
Связано: `docs/_internal/LOCAL_SERVER_DUAL_STATE_FIX_PLAN_2026-05-12_RU.md`
Назначение: per-category decisions для остаточных 781 dirty git status
entries после Этапов 0-7. Один источник правды по тому, что нужно
закоммитить, что игнорировать и что мигрировать.

## Текущее состояние

После коммита `680d06d` (40 файлов session deliverables) рабочее дерево
содержит:

| Категория | Кол-во | Природа |
|---|---:|---|
| `D` deleted   | 384 | `vllm/_genesis/*` (377) + obsolete `compose/*.yml` (5) + 2 launch scripts |
| `??` untracked | 306 | `vllm/sndr_core/*` (102), tests/* (160), docs/upstream/* (5), tools/* (4), прочее |
| `M` modified  | 91  | Docs/config обновлены в этой и предыдущих сессиях |

Это **v7 → v11 миграционный остаток**, накопленный за серию аудитов и
рефакторов. Делать «один большой commit» здесь правильно: транзакция
переключает namespace `_genesis → sndr_core` целиком.

## Decision matrix

### Группа 1 — `vllm/_genesis/*` (377 D)

**Решение: `git rm` целиком в migration commit.**

Каждый файл там был перемещён в `vllm/sndr_core/*` по карте v11
(PROJECT_STATE_AUDIT P0-1, audit 2026-05-08). Содержание сохранено в
git history pre-commit `680d06d` для forensics; back-compat alias
живёт в `vllm/sndr_core/__init__.py::__getattr__`.

```bash
# Stage all _genesis deletions in one shot
git rm -r vllm/_genesis/
```

Acceptance: после rm — `git status --short | grep "vllm/_genesis"` пуст.

### Группа 2 — `vllm/sndr_core/*` (102 ??)

**Решение: `git add` целиком в migration commit.**

Это v11 namespace, до которого никто из предыдущих сессий не дошёл с
коммитом. 40 файлов уже закоммичены в `680d06d` (session deliverables);
оставшиеся 102 — рутина migration (bundles, compat, dispatcher, kernels,
patches → integrations, и т.д.).

```bash
git add vllm/sndr_core/
```

Перед коммитом: `make audit-legacy-imports && make audit-public-paths`
(оба зелёные — гарантирует, что в add не попало мусора с приватными
путями или legacy refs).

### Группа 3 — `tests/*` (160 ??)

**Решение: `git add` целиком.**

`tests/unit/` (93), `tests/legacy/` (66), `tests/integration` (1) —
тестовая инфраструктура v11. Полная suite уже зелёная (5525/0 local,
5513/0 server). Закоммитить как одну единицу.

```bash
git add tests/
```

Исключения (нужно проверить вручную перед add):

| Файл | Проверка |
|---|---|
| `tests/integration/baselines/*.json` | Содержат legacy refs — allowlisted в `check_no_legacy_imports.py`. Не редактировать. |
| `tests/legacy/pristine_fixtures/*` | Frozen upstream snapshots для anchor-manifest. Не редактировать. |

### Группа 4 — `compose/*.yml` deletions (5 D)

**Решение: `git rm` (intentional — конфиги мигрированы в
`vllm/sndr_core/model_configs/builtin/*.yaml`).**

```bash
git rm compose/docker-compose.gemma4-26b-moe.yml \
       compose/docker-compose.integration-awq.yml \
       compose/docker-compose.integration-fp16kv.yml \
       compose/docker-compose.integration.yml \
       compose/docker-compose.qwen3-5-dense.yml
```

### Группа 5 — `scripts/launch/*` deletions (2 D)

`scripts/launch/snapshot_pre_arm.sh` + `scripts/launch/nsight_profile_capture.sh`.

**Решение: `git rm` (retired in v11, replaced by manual procedure in
`docs/_internal/PN96_AB_BENCH_PLAN_2026-05-12_RU.md` and operator-side
nsys invocation).**

```bash
git rm scripts/launch/snapshot_pre_arm.sh \
       scripts/launch/nsight_profile_capture.sh
```

### Группа 6 — `docs/upstream/*` (5 ??)

| File | Decision |
|---|---|
| `docs/upstream/UPSTREAM_WATCHLIST.yaml` | `git add` (already committed in `680d06d`) — verify with `git ls-files docs/upstream/UPSTREAM_WATCHLIST.yaml` |
| `docs/upstream/DEEP_AUDIT_VLLM_NOONGHUNNA_2026-05-08_RU.md` | `git add` — internal audit reference operators link to |
| `docs/upstream/PR38_PATCHER_REWORK_PLAN_2026-05-07.md` | `git add` — public roadmap doc |
| `docs/upstream/PRODUCTION_ROADMAP_2026-05-09.md` | `git add` |
| `docs/upstream/PRODUCTION_ROADMAP_EXPANDED_DELTA_AUDIT_2026-05-08.md` | `git add` |
| `docs/upstream/STABLE_PROMOTION_CHECKLIST.md` | `git add` |
| `docs/upstream/VLLM_PR_DECISION.md` | `git add` |

```bash
git add docs/upstream/
```

### Группа 7 — `tools/*` (4 ??)

| File | Decision |
|---|---|
| `tools/audit_yaml_vs_runtime.sh` | `git add` (Makefile target `audit-yaml` references it) |
| `tools/kv_calc.py` | `git add` (operator utility for VRAM estimation) |
| `tools/license_keygen.py` | `git add` (engine-tier keygen helper) |
| `tools/memory_observability.sh` | `git add` (sndr memory diagnostics helper) |

```bash
git add tools/
```

### Группа 8 — `M` (91 modified)

В основном docs и charts, обновлённые в текущей сессии (`docs/INSTALL.md`,
`docs/CONTRIBUTING.md`, `Makefile`, `.gitignore` уже committed). Прочие:

| Subgroup | Files | Decision |
|---|---|---|
| `assets/charts/*.png` | 4 modified | `git add` — regenerated chart assets |
| `assets/charts/_generate.py` | 1 modified | `git add` — chart regeneration script |
| `compose/docker-compose.example.yml` + `unit.yml` | 2 modified | `git add` — template updates |
| `benchmarks/v7_10_validation_20260424/*.md` | 3 modified | `git add` — bench narrative |
| `.github/workflows/*` | 3 modified | `git add` — CI workflows |
| `docs/*.md` (BENCHMARKS, CLIFFS, COMMANDS, etc.) | ~30 modified | `git add` — v11 docs |
| `pytest.ini`, `conftest.py`, `install.sh` | 3 modified | `git add` — infra |
| `schemas/patch_entry.schema.json` | 1 modified | `git add` |
| `scripts/*.py`, `scripts/*.sh` | ~15 modified | Per-file review — most are v11 namespace migrations |

Все changes уже совместимы с `make audit` aggregate, иначе аудиторы
поймали бы.

### Группа 9 — 12 diff files (per LOCAL_SERVER_DUAL_STATE_FIX_PLAN §6)

Уже разрешено:

| File | Resolution | Status |
|---|---|---|
| `.github/PULL_REQUEST_TEMPLATE.md` | local wins → server synced (Этап 1.2) | ✅ done |
| `benchmarks/harness/run_all.py` | local wins → server synced (Этап 1.1) | ✅ done |
| `SESSION_LOG_2026-05-06.md` | Update on `vllm/sndr_core/apply/*` paths (was `_genesis`) | ⏸ deferred — historical log, не повышаем приоритет |
| `benchmarks/v7_10_validation_20260424/upstream_compare/PR_DEEP_DIVE.md` | Already English; minor v11 path updates already in current diff | ✅ included via `git add` of M files |
| `docs/_internal/audits/genesis_deep_audit_2026-05-06.md` | Internal audit, lives in `_internal/` (gitignored) | ✅ skip from commit |
| `docs/_internal/audits/genesis_post_fix_rescan_audit_2026-05-05.md` | same | ✅ skip |
| `docs/_internal/audits/genesis_scripts_since_noon_audit_ru_2026-05-05.md` | same | ✅ skip |
| `genesis_deep_audit_2026-05-07.md` (root) | Already in `.gitignore` via `sndr_*_audit_*.md` pattern | ✅ |
| `genesis_full_project_audit_2026-05-08.md` (root) | same | ✅ |
| `sndr_production_readiness_audit_2026-05-08.md` (root) | same | ✅ |
| `sndr_repeat_deep_audit_2026-05-08.md` (root) | same | ✅ |
| `sndr_structure_deep_audit_2026-05-07.md` (root) | same | ✅ |

## Recommended commit strategy

**Single migration commit, structured message:**

```
chore(v7→v11): complete namespace migration

vllm/_genesis/ deleted (377 files); v11 layout in vllm/sndr_core/.
Tests, scripts, tools migrated to the new namespace.

Categories closed:
  • 377 D  vllm/_genesis/*           — deleted (v11 supersedes)
  • 102 A  vllm/sndr_core/*          — added (canonical layout)
  • 160 A  tests/*                   — pytest suite (5525/0 local,
                                       5513/0 server)
  • 5  D   compose/*.yml             — replaced by builtin
                                       model_configs/*.yaml
  • 2  D   scripts/launch/*.sh       — retired (manual procedure
                                       in PN96_AB_BENCH_PLAN)
  • 11 A   docs/upstream/* + tools/* — public infra
  • 91 M   docs/charts/CI            — v11 namespace renames

Audit gates green:
  • make audit-legacy-imports         clean
  • make audit-public-paths           clean
  • make audit-upstream-offline       clean
  • make test                         5525 passed / 0 failed (local)

Plan: docs/_internal/MASTER_REMEDIATION_PLAN_2026-05-12_RU.md
Map:  docs/_internal/DOC_MIGRATION_MAP_2026-05-12_RU.md
```

**Не делать `git push` без явного operator go-ahead** — push в GitHub
запрещён в текущем session contract.

## Acceptance

After the migration commit:

```bash
# Expectation: only intentional dirty state remains
git status --short | wc -l
# Should be a small number (< 20), all in operator-private folders
# or intentional unstaged work-in-progress.

# Audit suite clean
make audit-legacy-imports
make audit-public-paths
make audit-upstream-offline

# Pytest clean
python3 -m pytest tests/ -q --ignore=tests/integration
# Expected: 5525+ passed / 0 failed locally.
```

## Side-effects + risks

- **Risk: large diff makes review hard.** Mitigation: structured commit
  message + this migration map link in commit body.
- **Risk: missed v7 file silently dropped.** Mitigation: `make
  audit-legacy-imports` (Этап 5) catches any v7 ref that slipped past.
- **Risk: untracked test in `tests/` that depends on a delete path.**
  Mitigation: full pytest passes locally → tests can resolve all
  imports in v11 namespace.

## Out-of-scope

- **Server-side `git` operations.** This map covers the local repo only.
  Server state must be synced via the established rsync flow once
  the local migration commit lands (no `git push` per session contract).
- **GitHub release tag / wheel build.** Out of scope for this remediation
  pass; that's a separate release-engineering decision for the operator.
