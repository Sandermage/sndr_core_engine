# Post-remediation deferred work (after MASTER_REMEDIATION_PLAN closure)

Дата: 2026-05-12
Связано: `MASTER_REMEDIATION_PLAN_2026-05-12_RU.md` (closed, 8/8 stages)

После закрытия Этапов 0-8 master remediation plan, серии P0 fix'ов
(`PROJECT_STATE_AUDIT`) и quick wins по приоритетам user'а, остаются
несколько items, которые **сознательно отложены** и почему.

## Текущий зелёный baseline

| Окружение | Pytest | Self-test | Audit |
|---|---|---|---|
| Local  | 5538+ passed / 0 failed | 8/8 PASS | clean |
| Server | 5568+ passed / 0 failed | 8/8 PASS | clean |

`apply.shadow --strict` CLEAN, `make audit` aggregate green, no
hardcoded private paths in public code, all 30 touched files English-only.

## Закрыто в текущем post-MASTER round

### 5 P0 блокеров из `PROJECT_STATE_AUDIT_2026-05-12_RU.md`

| ID | Описание | Status |
|---|---|---|
| P0.1 | R-011 разрешить `GENESIS_PN95_*` prefix | ✅ already registered in `runtime_tunables.py` |
| P0.2 | `patch_N40_workload_classifier_hook` undefined | ✅ already fixed (uses `pn40_workload_classifier_hook.apply()`) |
| P0.3 | `verify_live_rebinds` undefined в orchestrator | ✅ already imported |
| P0.4 | `_resolve_wiring_module` undefined в verify.py | ✅ exists in `_state.py`; verify.py uses `module_for` |
| P0.5 | `Any`/`NoReturn` imports + duplicate dict key | ✅ both clean |

### CLI gaps (incremental)

| Item | Status |
|---|---|
| `sndr config list` | ✅ already exists |
| `sndr launch --preflight-only` | ✅ added + 5 tests |
| `sndr launch --pull` | ✅ added + 4 tests |
| `sndr launch --check-deps` | ✅ added + 4 tests |
| `sndr memory explain` (Phase 1) | ✅ exists |
| WSL2 probes в `doctor-system` | ✅ added + 6 tests |

### Architecture / Deploy / Infra

| Item | Status |
|---|---|
| P2.3 — runtime-hook stable ratchet | ✅ PN33+PN35 promoted to stable (см. CHANGELOG `v11.0.0+stable_first`) |
| K8s GPU operator detection | ✅ уже есть в `sndr k8s doctor` (nvidia_device_plugin + gpu_operator + runtimeClass) |

## Сознательно отложено (с обоснованием)

### Architecture debt — большие refactors

#### P2.1 — Collapse `_per_patch_dispatch.py` (4805 lines)

- **Effort:** 1-2 недели.
- **Risk:** очень высокий — это критический dispatch path для 133+ patches.
  Любая регрессия выключит весь dispatcher.
- **Mitigation prerequisite:** нужна comprehensive test coverage конкретно
  для legacy path (сейчас существующие 5500+ тестов покрывают
  spec-driven path, не legacy).
- **Decision:** defer. Open as separate sprint когда есть test harness
  для apply-layer regression discrimination.

#### P2.2 — Unified `PatchApplyResult` dataclass

- **Effort:** 1 неделя.
- **Risk:** средний — touches every `apply()` callsite (133 wiring modules).
- **Mitigation prerequisite:** typed contract design + migration plan
  для существующих returns (tuple → dataclass).
- **Decision:** defer. Wrap into the same sprint as P2.1, поскольку оба
  меняют dispatcher contract.

### CLI gaps — design-heavy

#### `sndr launch --prepare` / `--fix`

- **Effort:** 1-2 недели каждый.
- **Reason for defer:** оба требуют interactive operator confirmation
  flows + system mutation gates. `--prepare` means apt install / kernel
  module load / driver checks. `--fix` means auto-recovery of broken
  states. Both are dangerous-by-default; need careful UX design first
  (similar to `--strict-image` gating).

#### `sndr launch --runtime <docker|podman|k8s|bare>`

- **Effort:** 3-5 дней.
- **Reason for defer:** требует runtime adapter abstraction — `sndr
  launch` сейчас идёт только через docker/bare-metal `to_launch_script`.
  Подоменно подключить compose/quadlet/k8s renderers + apply gates на
  preset basis — реально сделать, но это новая полноценная feature, не
  quick win.

#### `sndr memory explain` Phase 2-4 (live VRAM, recommendations engine, per-patch attribution)

- **Effort:** 2-4 недели each phase.
- **Reason for defer:** Phase 2 (live probe-vs-estimate diff) уже частично
  есть как `sndr memory report --live`. Phase 3 (recommendations) и
  Phase 4 (per-patch attribution) требуют real profiler data + research.

#### `sndr community submit / verify / import-issue`

- **Effort:** 2-4 недели.
- **Reason for defer:** community engagement strategy decision должен
  принять operator (GitHub Discussions vs Issues vs forms). Reactive
  workflow на community PR — это совершенно другая поверхность
  ответственности.

### Deploy gaps

#### `sndr proxmox apply`

- **Effort:** 3-5 дней.
- **Reason for defer:** требует live PVE testbed (operator не имеет
  идемпотентного rollback'а сейчас). `proxmox render` уже эмитит pct/qm
  команды для review — это safer default.

### Testing / CI

#### Self-hosted GitHub Actions runner

- **Effort:** 1-2 дня (infra) + ongoing maintenance.
- **Reason for defer:** infrastructure decision — нужен dedicated server
  для CI, который не конкурирует за GPU с PROD рабочей нагрузкой.
  Operator-side task.

#### Soak test auto-integration в `reference_metrics`

- **Effort:** 2-3 дня.
- **Reason for defer:** требует extending integration baseline schema
  для `stability_24h_*` поля + scheduled soak runs. Низкий приоритет —
  current 200-min soaks dovетают как ad-hoc proof.

### Long-term (PN95 / Memory)

PN95 Phase 2 (GPU↔CPU bytes), Phase 3 (Boot KV pool expansion), Phase
5 (logical/physical split), MambaRadixCache backport — research/
implementation effort per audit:

- PN95 Phase 3 alone: 11-13 hours.
- PN95 Phase 5: 20-25 hours.
- MambaRadixCache: 2-4 недели.
- OOM preflight from host RAM/swap: 4-6 hours.
- Path C tier-aware completion: 9 days + 70 tests.

Все these требуют focused research session.

### Upstream backports (waiting for upstream merge)

- vllm#42102 (DFlash + quantized target KV) → PN94 + PN95b — план
  ready в `docs/_internal/research/upstream_42102_…md`. Trigger:
  upstream merge.
- vllm#40269 → PN90 — implementation в registry, awaiting merge.
- vllm#40270 → PN91, vllm#37160 → PN92, vllm#37190 → PN93, vllm#38330 → PN94.

### Models

- Gemma 4 G1-G4 — waiting upstream support + new patches family.
- Qwen3 extensions Q-Ext-1-3 — research-level.
- Huihui-Qwen abliterated — wait-and-see, undocumented quality.

### Docs reorganization

- Active vs `_archive/` boundary + CI gate against stale refs.
- Effort: 1 day.
- Reason for defer: needs DOC_MIGRATION_MAP decisions executed first
  (Этап 8 already produced the map; the migration commit itself is the
  next operator step).

## Что operator может делать сейчас

1. **Review этого doc + MASTER_REMEDIATION_PLAN_2026-05-12_RU.md.**
2. Выполнить single migration commit per `DOC_MIGRATION_MAP_2026-05-12_RU.md`
   recommended strategy.
3. (Опционально) запустить S5.1 PN96 A/B bench по обновлённому
   `PN96_AB_BENCH_PLAN_2026-05-12_RU.md`.
4. Решить порядок открытия отложенных items выше — каждый имеет
   обоснование + effort estimate.

## Acceptance global (после всех закрытий)

```bash
# Core gates
python3 -m vllm.sndr_core.compat.cli self-test --json
python3 -m vllm.sndr_core.apply.shadow --strict
make audit                # legacy-imports + public-paths + upstream + doc-sync

# Test suite
python3 -m pytest tests/ -q --ignore=tests/integration
# 5500+ passed / 0 failed

# CLI smoke
python3 -m vllm.sndr_core.cli config list
python3 -m vllm.sndr_core.cli launch <preset> --preflight-only
python3 -m vllm.sndr_core.cli doctor-system --json
python3 -m vllm.sndr_core.cli memory explain <preset>
python3 -m vllm.sndr_core.cli k8s doctor

# Server convergence verify
ssh server "cd ~/genesis-vllm-patches-v11 && python3 -m pytest tests/ -q --ignore=tests/integration | tail -3"
```

Все эти команды должны быть зелёными в текущем состоянии.
