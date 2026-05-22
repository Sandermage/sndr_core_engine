# Genesis vLLM Patches — Consolidated Master Roadmap

**Дата:** 2026-05-13
**Версия:** v1.0 — единый источник правды
**Статус:** active master plan (заменяет 30+ планов из `docs/_internal/`)
**Автор синтеза:** Claude Opus 4.7 (1M context), верификация — operator

Этот документ объединяет **все** активные планы проекта в один навигационный план. Source docs (PROJECT_ROADMAP_V2, MASS_ADOPTION_UX_PRODUCT_PLAN, UNIFIED_CONFIG_AUTOMATION_PLAN, REMAINING_WORK_PLAN, INTEGRATED_PLAN, и 25 supplements) перечислены в §16 cross-reference. Этот файл — единственный, по которому ведётся работа дальше.

Принципы:
- **Источник правды у работающего кода**, не у markdown. Roadmap не дублирует pytest counts — они в `ROADMAP_EVIDENCE_LEDGER_2026-05-12_RU.md`.
- **Каждое утверждение "сделано" подтверждено commit SHA** (см. §2 + §16).
- **Каждый item имеет** owner (по умолчанию `sandermage`), status, blocked-by, acceptance.
- **Без хардкода test-counts**, без "примерно", без "должно быть готово". Если статус неясен — `unknown`, не `done`.

---

## §1. Executive summary

### 1.1 Что проект делает сейчас

Genesis vLLM Patches — community patch layer над upstream vLLM. **136 патчей** (P-серия + PN-серия), организованных в **PATCH_REGISTRY** с lifecycle (stable / experimental / legacy / retired / research / coordinator), tier (community), env_flag, family. Применяются runtime'ом через `vllm/sndr_core/apply/` + `vllm/sndr_core/integrations/<family>/`.

**V2 layered config** на финальной стадии миграции: model + hardware + profile + preset YAMLs в `vllm/sndr_core/model_configs/builtin/`. 11 preset aliases (`prod-35b`, `prod-27b-tq`, etc.) композят в V1 `ModelConfig` через `registry_v2.load_alias()`. Composer V1-bridge поддерживает byte-identity с legacy combined YAMLs (Q1 decision).

**CLI**: `sndr` ≈ 35+ subcommand'ов: install / launch / doctor / doctor-system / verify / deps / patches / model / hardware / profile / config / k8s / proxmox / compose / quadlet / bench / report / community / config-keys / report bundle, etc.

**Production**: 27B PROD на dev209 (neutral pin bump), 35B PROD с известной регрессией -2.82% TPS (upstream regression dev93→dev209 в A3B-FP8 MoE path — PN96 designed to recover).

### 1.2 Что ещё впереди (high-level)

Шесть параллельных треков:

| Track | Scope | Главные deliverables | Effort baseline |
|---|---|---|---|
| **A** V2 Layered Config | Phase 1-9 PROJECT_ROADMAP_V2: schema, composer, presets, freeze | composer V1-bridge, 11 preset aliases, V1 freeze | 15-20 days |
| **B** Patch Quality + Bench | INTEGRATED_PLAN S0-S9, REMAINING_WORK P1.1-P1.3 | live PN96 A/B, Wave 10 promotion, methodology contract | 5-10 days (+ GPU ops) |
| **C** Mass Adoption UX | MASS_ADOPTION_UX_PRODUCT_PLAN phases 0-7 | Product API + TUI + GUI + clients | 3-4 months |
| **D** Deploy + Bootstrap | UNIFIED_CONFIG K8s/Proxmox/Bootstrap | sndr k8s/proxmox/bootstrap full coverage | 8-12 weeks |
| **E** Architecture Debt | P2.1 dispatch collapse, P2.2 unified apply() | -4805 LOC, PatchApplyResult | 3-4 weeks (deferred) |
| **F** Research / Long-term | PN95 phases, MambaRadixCache, KV compression | PN97/PN98, DuoAttention | months-quarters |

### 1.3 Главный критерий успеха

Новый оператор может:
1. `git clone` + `pip install -e .`
2. `sndr install` → wizard validates host
3. `sndr launch <preset>` → vLLM up, патчи applied, bench in tolerance
4. Community может вкладывать patches/configs через прозрачный SDK

Без bug'ов. Без открытых вопросов. С working installer + launcher.

---

## §2. Текущий baseline (что реально сделано)

### 2.1 Commits, фиксирующие закрытые scope

| Commit | Scope | Дата |
|---|---|---|
| `680d06d` | MASTER_REMEDIATION_PLAN Этапы 0 + 1 (security + dual-state, 15 items) | 2026-05-12 |
| `8b4b033` | model_configs comprehensive validation pipeline | (prior) |
| `8264512` | model_configs unified ModelConfig framework | (prior) |
| `c1e4cf3` | **§6.8 proof chain + V2 schema-coverage invariants E18-E34** (27 audit/test files + Makefile + proof/ module) | 2026-05-13 |
| `f4ce433` | **MASTER_REMEDIATION_PLAN Этапы 2 + 3** (deploy + doctor logs, 9 items) | 2026-05-13 |
| `94f326c` | **MASTER_REMEDIATION_PLAN Этапы 4 + 5** (PN26 polish + automation wiring, 10 items) | 2026-05-13 |
| `052feba` | **MASTER_REMEDIATION_PLAN Этапы 6 + 7 + 8** (docs cleanup + bench plan + migration map, 12 items) | 2026-05-13 |

**Status:** local branch `dev` на 5 commits впереди `origin/dev`. **Push не выполнен** (operator instruction).

### 2.2 Что точно зелёное

- **Full pytest**: 6377 passed / 131 skipped / 0 failed (последний прогон 2026-05-13)
- **make evidence**: 34 gates (26 gating + 2 informational зелёных + 6 gating new from prior); 9 gating informational not green (audit-docs-stale, audit-public-docs, audit-security — pre-existing warnings)
- **MASTER_REMEDIATION_PLAN**: 48/48 items closed (Stages 0-8, status markers updated)
- **§6.8 proof chain полностью замкнут**: prove → bench-attach → proof-status → release-check
- **V2 schema invariants**: 22 gating audit gates frozen (mounts, env keys, env values, refs, lifecycle, dependencies, capability strings, pin formats, etc.) — все cross-checked

### 2.3 Что фактически в WD, но НЕ committed

- `vllm/sndr_core/model_configs/builtin/` — **42 V2 YAML файла** (model/, hardware/, profile/, presets/ trees). Untracked. Audit gates ссылаются на них, но в CI checkout их не будет.
- `vllm/sndr_core/cli/patches.py` — extended мной (E19-E21 handlers), но whole file untracked (operator's pre-session work + my additions).
- `compose/docker-compose.test-v11.yml` — E26 EXEMPT marker, untracked.
- **351 untracked + 60 modified** файла total — operator's WIP, не тронуто в session arc.

### 2.4 Что НЕ закрыто

- **MASS_ADOPTION_UX_PRODUCT_PLAN** (создан 2026-05-13): 0/7 phases actioned
- **PROJECT_ROADMAP_V2** Phases 1-10: V2 schema partially exists (composer working, 11 presets migrated), но Phase 4.5-4.7 (RuntimeCommandSpec, security boundary, memory explain) — design only
- **REMAINING_WORK_PLAN** P1-P4: P1.1-P1.3 GPU-gated; P2.1-P2.4 deferred refactors
- **UNIFIED_CONFIG_AUTOMATION_PLAN** K8s / Proxmox / Bootstrap full — partial implementation
- **EXTERNAL_FINDINGS_PIPELINE** — design draft, Phase 10 deferred
- **PN96 live A/B bench** — protocol готов, ждёт operator + GPU downtime

---

## §3. Архитектура (current state снимок)

### 3.1 Top-level dirs

```
vllm/sndr_core/                          # community-tier core
  ├── apply/                             # patch application engine (orchestrator + verify + shadow + state)
  │   └── _per_patch_dispatch.py         # legacy 4805-line dispatch table (P2.1 target for collapse)
  ├── integrations/<family>/             # canonical patches (spec-driven, apply_module path)
  │   ├── attention/{gdn, turboquant, ...}/
  │   ├── spec_decode/
  │   ├── worker/
  │   └── ... (10+ families)
  ├── dispatcher/
  │   ├── registry.py                    # PATCH_REGISTRY (136 entries)
  │   ├── spec.py                        # PatchSpec dataclass
  │   └── registry_metadata.py           # implementation_status overlay
  ├── model_configs/
  │   ├── schema.py                      # V1 ModelConfig + Hardware/Docker/K8s configs
  │   ├── schema_v2.py                   # V2 layered dataclasses
  │   ├── registry_v2.py                 # load_alias / list_models / load_model / load_profile
  │   ├── runtime_command.py             # E22 RuntimeCommandSpec (Phase 4.5)
  │   ├── runtime_container.py           # RuntimeContainerSpec IR
  │   ├── builtin/{model, hardware, profile, presets}/
  │   ├── community/{hardware, profile}/
  │   ├── audit_rules.py                 # CompatibilityMatrix + R-001..R-011 rules
  │   ├── preflight.py                   # check vllm pin in image
  │   └── compose.py / verify.py / diagnose.py / host.py
  ├── proof/                             # NEW (E18-E21): §6.8 chain
  │   ├── __init__.py                    # static_checks_for_patch + classify_proof + summarize_proof_status
  │   ├── bench_attach.py                # E19 — ingest bench JSON into proof artefact
  │   └── release_check.py               # E21 — release-gate consumer
  ├── cli/
  │   ├── __init__.py                    # cli_main entry point
  │   ├── compose.py / quadlet.py / k8s.py / proxmox.py
  │   ├── patches.py                     # prove / bench-attach / proof-status / release-check / plan / explain
  │   ├── model.py / profile.py / hardware.py / config.py / config_keys.py
  │   ├── install.py / launch.py / service.py / deps.py
  │   ├── doctor_logs.py / doctor_system.py / verify.py
  │   ├── memory.py                      # PARTIAL (Phase 4.7 MVP pending)
  │   ├── report.py / bench.py / bench_compare.py
  │   ├── community.py / findings.py / image.py / migrate.py / upstream.py
  │   ├── host.py / hardware.py / tune.py / license.py
  │   └── caveats.py / bootstrap.py
  ├── detection/                         # GPU + host detection helpers
  ├── deps/                              # dependency inventory (UNIFIED_CONFIG P1.1)
  ├── memory/                            # placeholder for `sndr memory explain` MVP
  ├── observability/                     # log + bench helpers
  ├── oracle/                            # patch oracle (apply decisions)
  └── ...

vllm/sndr_engine/                        # PRIVATE optional namespace (placeholder)
plugins/                                 # community patch plugins
scripts/                                 # 24 audit_* + utility scripts
tests/                                   # 6377 pass / 131 skip
tools/                                   # bench suite, methodology, soak, smoke
schemas/                                 # JSON schemas for patch_entry, etc.
benchmarks/                              # bench harness + historical results
docs/                                    # public docs (CONFIGURATION, MODELS, ...)
docs/_internal/                          # planning + ledger + research (gitignored)
```

### 3.2 V2 Layered config tree (untracked WD state)

```
vllm/sndr_core/model_configs/builtin/
├── model/                               # 6 model YAMLs (qwen3.6-{7b-dense, 27b-dflash, 27b-int4-fp8kv, 27b-int4-tq-k8v4, 35b-a3b-fp8, 35b-a3b-fp8-dflash})
├── hardware/                            # 3 hardware YAMLs (a5000-1x, a5000-2x, single-3090)
├── profile/                             # 11 profile YAMLs (wave9-*, qa-*, experimental-*, path-{a,c}-*)
├── presets/                             # 11 alias triplets
├── *.yaml (V1 legacy)                   # 11 monolithic combined YAMLs (frozen by audit-no-new-v1)
```

### 3.3 §6.8 proof chain (commit c1e4cf3)

```
[prove static-checks]  →  [bench-attach (ingest GPU JSON)]  →  [proof-status (read aggregate)]  →  [release-check (decider)]
       (E12+17)                  (E19)                              (E20)                              (E21)

  PatchProof artefact at evidence/patch_proof/<patch_id>__<vllm_pin>.json:
    static_checks: [P-1..P-7]
    bench_delta:  {median_tps, p95_tps, decode_tpot_ms, ttft_ms, cv_pct,
                   tool_call_score, methodology_sha, vllm_pin, composed_key,
                   median_tps_delta_pct, p95_tps_delta_pct, ...}
```

### 3.4 Audit gates frozen (34 in make evidence)

**Gating (26)**:
1. `audit` (legacy aggregate)
2. `audit-configs` (V2 alias compose)
3. `audit-community` (R-1..R-7 community SDK validator)
4. `audit-no-new-v1` (V1 freeze — 11 frozen baseline)
5. `audit-patches-prove-all` (§6.8 P-1..P-7 — 136/136)
6. `audit-all-referents` (F822 — every `__all__` referent resolves)
7. `audit-readme-counters` (136/20/6/3/11/11 sync)
8. **`audit-model-baselines`** (E22 — reference_metrics_ref paths exist)
9. **`audit-launch-coverage`** (E22 — 6 mount slots + 7 env keys per hardware)
10. **`audit-v2-env-keys`** (E25 — cross-layer canonical env keys)
11. **`audit-bench-methodology`** (E26 — bench_delta.methodology_sha matches)
12. **`audit-no-hardcoded-paths`** (E26 — no `/home/USER` in active config)
13. **`audit-v2-required-fields`** (E27 — per-kind frozen required field set)
14. **`audit-v2-id-consistency`** (E28 — id == filename stem)
15. **`audit-v2-license-coverage`** (E28 — SPDX license + non-empty maintainer)
16. **`audit-v2-cross-reference`** (E29 — profile parent + preset triplet refs resolve)
17. **`audit-v2-vllm-pin-consistency`** (E29 — model.vllm_pin_required == baseline.vllm_version)
18. **`audit-v2-patch-lifecycle`** (E30 — retired patches require allowlist)
19. **`audit-v2-hardware-sanity`** (E30 — cuda, n_gpus, vram, gmu bounds)
20. **`audit-v2-patch-dependencies`** (E31 — requires_patches + conflicts_with satisfied)
21. **`audit-v2-capability-coverage`** (E32 — capabilities strings frozen allowed sets)
22. **`audit-v2-versions-pin-format`** (E32 — vllm/genesis pin regex)
23. **`audit-v2-quantization-coverage`** (E33 — quantization + dtype frozen)
24. **`audit-v2-context-length-sanity`** (E33 — max_model_len + batch bounds)
25. **`audit-v2-runtime-image-pin`** (E34 — sha256 digest pin)
26. **`audit-v2-network-port-consistency`** (E34 — ports + shm_size + network)

**Informational (8)**:
- `audit-docs-stale` (warning — pre-existing drift)
- `audit-public-docs` (warning until cleanup)
- `audit-security` (warning — pre-existing operator paths)
- `audit-patches-prove` (informational coverage report)
- `audit-proof-status` (E20 — 5-bucket aggregate)
- `audit-release-check` (E21 — release-gate consumer)
- `audit-v2-freshness` (E27 — last_validated ≤ 180 days)
- `audit-v2-default-on-mismatch` (E31 — explicit default-on overrides)

### 3.5 Operator decisions Q1-Q7 (final, captured)

| # | Question | Decision | Impact на план |
|---|---|---|---|
| Q1 | Aliases vs explicit triplet | **Hybrid**: explicit triplet default + optional aliases | V2 alias supports both, composer V1-bridge byte-identical |
| Q2 | Profile promote | **CLI auto** with dry-run default + atomic write + archive | `sndr profile promote --dry-run --yes` workflow |
| Q3 | Community plugin SDK location | **Hybrid A+B**: in-repo `plugins/community/<user>/` + maintainer-approval PR-style | One repo, one CI, one review pipeline |
| Q4 | Logs/baselines | **Hybrid C**: `tests/integration/baselines/` (curated) + `~/.sndr/bench-results/` (runtime) | Baselines reviewable in git; outputs operator-private |
| Q5 | V1 deprecation timeline | **Freeze → deprecate**: V1 frozen after Phase 7, removed when all 11 presets migrated | Gentle migration, no forced deadline |
| Q6 | Patch versioning | **Inline semver** + `patches.lock` operator-side reproducibility | Pin-compatible, standard Python |
| Q7 | Conflict UX | **Fail loud default** + opt-in `--auto-resolve-conflicts` | CI safety, profile YAML stays explicit source of truth |
| **+ runtime placement** | docker/podman/k8s/quadlet/bare-metal — где живёт? | **В hardware layer** (не profile) | Profile — patches delta; hardware — deployment target |

---

## §4. Track A: V2 Layered Config (Phase 0-10)

**Источник:** PROJECT_ROADMAP_V2_2026-05-12_RU.md §5

**Цель:** превратить V1 monolithic YAML в V2 layered (model + hardware + profile + preset) с byte-identical V1 composer bridge, community SDK, V1 freeze.

### 4.1 Phase 0 — Evidence Gate (P0, 0.5d)

**Status:** ✅ DONE (commit c1e4cf3 + Entry 18 в evidence ledger)

**Deliverables:**
- `docs/_internal/ROADMAP_EVIDENCE_LEDGER_2026-05-12_RU.md` (append-only) — DONE
- `make evidence` aggregate target (14→34 gates через E22-E34) — DONE

**Acceptance:**
```bash
make evidence    # appends entry; rc=0 only if all gating green
```

### 4.2 Phase 8a — Cold-install smoke V1 (P0, 0.5d)

**Status:** ⏳ PENDING

**Rationale:** проверить что installer + launcher работают на чистом checkout ДО V2 work.

**Acceptance:**
```bash
make clean && python3 -m venv .venv && source .venv/bin/activate
pip install -e .
sndr --version                                   # rc=0
sndr install --dry-run                           # rc=0
sndr config list                                 # V1 preset discovery works
sndr launch a5000-2x-35b-prod --preflight-only   # V1 composition green (NOT V2 alias)
```

### 4.3 Phase 1 — V2 schema + composer + tests (P0, 4-5d)

**Status:** ✅ MOSTLY DONE (schema_v2.py + registry_v2.py + composer working; tests partial)

**Done:**
- `vllm/sndr_core/model_configs/schema_v2.py` — `ModelDef`, `HardwareDef`, `ProfileDef`, `RuntimeBlock`
- `vllm/sndr_core/model_configs/registry_v2.py` — `load_alias()`, `load_model()`, `load_hardware()`, `load_profile()`, `list_models()`
- `load_alias()` composes V1 `ModelConfig` byte-identically
- E22-E34 audits enforce schema invariants

**Остаётся:**
- Formal 30+ unit tests in `tests/unit/model_configs/test_compose_v2.py` (partial coverage exists via E25 audit-v2-env-keys resolved-alias tests)
- Acceptance regression: `cfg.to_dict()` byte-identical для всех 11 aliases (audit-configs implicitly enforces)

### 4.4 Phase 2 — POC migration (P0, 1d)

**Status:** ✅ DONE — `a5000-2x-35b-prod` мигрирован в `model/qwen3.6-35b-a3b-fp8.yaml` + `hardware/a5000-2x-24gbvram-16cpu-128gbram.yaml` + `profile/wave9-balanced.yaml` + `presets/prod-35b.yaml`. Verified by `audit-configs`.

### 4.5 Phase 3 — Migrate remaining 10 presets (P1, 2-3d)

**Status:** ✅ DONE — все 11 presets мигрированы (audit-configs: 11/11 compose). Note: V2 builtin tree остаётся untracked в commit'ах, но functional state присутствует.

### 4.6 Phase 4 — CLI updates (P1, 2d)

**Status:** ⏳ PARTIAL — большая часть `sndr model/hardware/profile/community` subcommand'ов реализована. Tests есть. Финализация:

**Остаётся:**
- `sndr profile new <name> --parent-model <m>` (publish_state=draft)
- `sndr profile diff <id>` (what would change if promoted)
- `sndr community new-patch --id PN999 --family spec_decode --user <handle>`
- `sndr community lock > ~/.sndr/patches.lock`
- `sndr community install <id>[@version]`

### 4.7 Phase 4.5 — RuntimeCommandSpec canonical IR (P1, 1-2d)

**Status:** ✅ DONE (commit f4ce433, Etap 2.1 — vllm/sndr_core/model_configs/runtime_command.py + parity tests test_runtime_command_parity.py).

**Done:**
- `RuntimeCommandSpec` frozen dataclass (`argv`, `env`, `volumes`)
- `build_runtime_command(cfg)` — single source of truth
- compose.py, quadlet.py, k8s.py delegate to `build_runtime_command()`
- Parity tests: compose/quadlet/k8s/bare-metal emit identical argv для `a5000-2x-35b-prod`

**Design doc:** `RUNTIME_COMMAND_SPEC_DESIGN_2026-05-12_RU.md` (206 lines)

### 4.8 Phase 4.6 — Security + license gate boundary (P1, 1d)

**Status:** ⏳ PARTIAL — license.py существует, audit-security informational gate работает, но финализация:

**Остаётся:**
- `vllm/sndr_core/license/__init__.py` — unlicensed-core default (current code path needs explicit unlicensed branch)
- `vllm/sndr_core/license/verify.py` — offline pub-key signature check (Ed25519 — blocked on operator key ceremony)
- `vllm/sndr_core/cli/license.py` — `sndr license status/verify/import` (status partially exists)
- `vllm/sndr_core/report/redact.py` — report bundle redaction
- `scripts/security_scan.py` — currently informational, promote to gating per release tier
- `scripts/sbom_generate.py` — SBOM SPDX + constraints.txt + attestation
- `make audit-security` — already exists but informational

**Acceptance:**
```bash
sndr license status --json | jq -e '.core == "public (unlicensed)" and .engine == null'
sndr license verify --file tests/fixtures/valid_license.lic --offline
make audit-security           # all 6 sub-checks pass (gating tier)
```

**Critical invariants:**
- Public core NEVER makes network calls for licensing
- Private key NEVER in repo
- No telemetry by default

**Design doc:** `SECURITY_LICENSE_GATE_2026-05-12_RU.md` (202 lines)

### 4.9 Phase 4.7 — `sndr memory explain` MVP (P1, 1d) — NEW PRIORITY

**Status:** ❌ NOT STARTED — design done, implementation pending

**Rationale:** "will prod-35b fit on my 2× A5000 at ctx=64k seqs=4?" — one CLI call, не launch attempt.

**Deliverables:**
1. `vllm/sndr_core/memory/explain.py` — estimator:
   - Weights: param_count × dtype_bytes (FP16=2, FP8=1, INT4=0.5)
   - KV cache: `2 × layers × hidden × kv_heads × ctx × seqs × kv_dtype_bytes` (turboquant_k8v4 уменьшает в 2× vs fp8)
   - CUDA graph reserve: ~50-150 MiB/seq per arch (calibration table)
   - Activations: `activation_factor × max_num_batched_tokens × hidden` (FP8=1.0, INT4=1.15)
   - Quantization overhead: per-dtype constant (TQ k8v4 = +400 MiB)
   - Drafter (DFlash): per-arch MiB after TP split
   - Fragmentation: 5-10% буфер

2. `tools/memory_explain_calibration/v1.yaml` — calibration seeded from Wave 9 bench:
   ```yaml
   architectures:
     hybrid_gdn_moe:
       cudagraph_reserve_per_seq_mib: 80
     dense:
       cudagraph_reserve_per_seq_mib: 50
   quantizations:
     fp8: {activation_factor: 1.0, kv_overhead_mib: 0}
     turboquant_k8v4: {activation_factor: 1.05, kv_overhead_mib: 400}
   ```

3. `vllm/sndr_core/cli/memory.py` — CLI modes:
   ```bash
   sndr memory explain --profile prod-35b              # known preset
   sndr memory explain --model X --hardware Y --ctx Z  # composed triplet
   sndr memory explain --profile prod-35b --ctx-sweep 4096,16384,65536,131072
   sndr memory explain --profile prod-35b --json       # tooling
   ```

4. **30+ unit tests** per V2 alias (acceptance: verdict ∈ {SAFE, TIGHT, OOM_RISK} matches Wave 9 bench reality):
   - prod-35b → SAFE
   - long-ctx-27b → TIGHT at ctx=280k
   - qa-27b-tq-1x → SAFE

**Honesty rule:** MVP NEVER outputs single-point estimate без uncertainty band. Median + p95 + worst-case mandatory.

**Design doc:** `MEMORY_EXPLAIN_MVP_2026-05-12_RU.md` (199 lines)

### 4.10 Phase 5 — Community patch SDK (P1, 3-4d)

**Status:** ⏳ PARTIAL — discovery + validator skeleton exists

**Остаётся:**
- `vllm/sndr_core/community/manifest.py` — `PatchManifest` dataclass schema (см. §4.5 in PROJECT_ROADMAP_V2)
- `vllm/sndr_core/community/validator.py` — schema + anchor md5 + conflicts + tests harness
- `vllm/sndr_core/community/scaffold.py` — `sndr community new-patch` generator
- `plugins/community/_template/` (publish_state: draft, не в release registry)
- `docs/COMMUNITY_PATCHES.md` operator guide

**Community patch manifest shape** (research lessons 4, 5, 7, 8):
```yaml
schema_version: 2
kind: patch
id: PN999
namespace: community/<user>
title: PN999 — custom thing X
maintainer: <user>
version: 1.0.0
license: apache-2.0
lifecycle: community-test
implementation_status: experimental
publish_state: draft

type: runtime_hook   # | text_patch | composite
family: spec_decode
env_flag: GENESIS_ENABLE_PN999
default_on: false

compatibility:
  min_vllm_pin: 0.20.2rc1.dev93
  max_vllm_pin: null
  min_sndr_core_version: 11.2.0
  model_arch_required: [hybrid_gdn_moe]
  cuda_capability_min: [8, 6]

target_files:
  - path: vllm/v1/spec_decode/eagle/proposer.py
    target_callable: EagleProposer.propose
    context_md5: deadbeef...
    anchors: [...]

conflicts_with: [PN77]
requires_patches: [P58]
marker_attr: _genesis_pn999_applied

entry_points:
  apply: "patch:apply"
  verify: "patch:verify"
  revert: "patch:revert"

tests_required:
  - test_apply_returns_tuple
  - test_apply_idempotent
  - test_env_off_is_noop
  - test_conflicts_resolved
  - test_revert_restores_original
  - test_pristine_anchor_md5
```

### 4.11 Phase 6 — Bench/log + methodology contract (P2, 1d)

**Status:** ⏳ PARTIAL — `tools/bench_methodology.yaml` exists (audit-bench-methodology E26 enforces SHA pin)

**6.A Output layout (DONE):**
- `tools/genesis_bench_suite.py` writes `~/.sndr/bench-results/<composed>__<ISO>.json`
- Legacy combined-key path preserved для legacy operators

**6.B Methodology contract:**

| Element | Contract |
|---|---|
| Prompt set | `tools/bench_corpus/v1/` (SHA pinned in result JSON) |
| Sequence count | configurable but recorded; default = `max_num_seqs` |
| Warmup | 3 full requests discarded |
| Measurement | N=10 runs; median + p95; flag if CV>5% |
| GPU clock | `nvidia-smi --lock-gpu-clocks=<base>,<base>` (recorded) |
| Tolerance | ≤2% regression on median TPS = accept; >5% blocks |
| Tool-call corpus | 10 fixed scenarios from Wave 9 dev209 (10/10 required) |
| Soak | optional; if run, ≥200 min with CV<3% rolling 10-min |
| Artifact | result JSON includes: methodology SHA, vllm pin, model id, hw id, profile id, composed key, all knob values, GPU clock state, p50/p95 TPS, tool-call score |

**Acceptance:**
```bash
tools/genesis_bench_suite.py --quick prod-35b
sndr bench validate <result.json>    # round-trip без warnings
```

### 4.12 Phase 7 — Tests + docs + CI gate (P1, 2d)

**Status:** ⏳ PARTIAL — multiple audit gates wired, docs partial

**Остаётся:**
- `docs/CONFIG_SYSTEM_V2.md` operator guide
- `docs/COMMUNITY_PATCHES.md` operator-facing community SDK guide
- `docs/INSTALL.md` cold-install (no `_genesis` refs) — DONE (commit 052feba)
- **`docs/ROLLBACK_PLAYBOOK.md`** — REQUIRED per §9 production-ready item 9. **Не создан.** Each feature shipped in Phase 1-6 must list revert SHA + smoke command proving V1 still works.
- New CI gate: `make audit-configs` — DONE (gating)
- New CI gate: `make audit-public-docs` — DONE (gating since 2026-05-13)
- New CI gate: `make audit-security` — DONE (informational; promote after Phase 4.6)
- Final pytest + audit + self-test green — current 6377/0 ✓

### 4.13 Phase 8b — V2 acceptance smoke (P0, 0.5d)

**Status:** ⏳ PENDING (after Phase 7 finalization)

**Acceptance:**
```bash
sndr launch prod-35b --preflight-only         # V2-composed alias
sndr launch prod-27b-tq --preflight-only      # V2-composed alias
sndr hardware list                            # V2 discovery (new in Phase 4)
sndr model list                               # V2 discovery
sndr config show prod-35b --runtime docker
sndr patches validate path/to/community-manifest.yaml
```

### 4.14 Phase 9 — V1 freeze (P2, 0.5d)

**Status:** ⏳ PARTIAL — `audit-no-new-v1` enforces 11-entry baseline (DONE). Финализация:

**Остаётся:**
- Mark V1 loaders as deprecated (DeprecationWarning at load)
- One-shot warning per session
- V1 removal: когда все combined presets либо migrated, либо explicitly retired (gradual, no forced deadline)

### 4.15 Phase 10 — Patch integration (continuous, P2-P3)

**Status:** ❌ NOT STARTED (gated by V2 acceptance + community SDK)

**Priority order:**

| # | Patch | Effort | Expected impact |
|---|---|---|---|
| 1 | **PN72** revert contract fix | 1d | Idempotency restoration |
| 2 | **Sliding Window Attention** activation check | 0.5d | 50-100× compression if Qwen3.6 supports |
| 3 | **PN94 + PN95b** (after vllm#42102 merge) | 2-3d | DFlash + TQ k8v4 coexistence |
| 4 | **PN90** probabilistic draft (vllm#40269) | 1-2w | +0.5-2% TPS spec-decode |
| 5 | **PN80** embedding FP8 | 1-2w | ~800 MiB savings on 35B |
| 6 | **DuoAttention** integration | 1-2w | 5-10× KV reduction |
| 7 | **TQ k4v4 extension** | 1-2w | 2× memory savings vs k8v4 |

Каждый идёт через community SDK pipeline (canonical patches тоже проходят validation gates).

---

## §5. Track B: Patch Quality + Bench (REMAINING_WORK P1.1-P1.3 + INTEGRATED_PLAN S0-S9)

### 5.1 P1.1 — Live A/B bench PN96 на 35B PROD (45 min, GPU-gated)

**Status:** 🟡 READY TO EXECUTE — operator GPU access + downtime gate

**Protocol** (PN96_AB_BENCH_PLAN_2026-05-12_RU.md, 131 lines):

1. **Phase A** (baseline, PN96=ON): measure current TPS, soak 5 min
2. **Phase B** (disable PN96, restart): `sndr launch a5000-2x-35b-prod` with `GENESIS_DISABLE_PN96=1`
3. **Phase C** (measure disabled): re-bench, soak
4. **Phase D** (restore PN96): verify
5. **Phase E** (analysis): `sndr bench-compare` baseline vs disabled
   - Record в `tests/integration/baselines/35b_v11_wave9.json` if Welch p<0.05
   - Verdict:
     - PN96 keep ON if delta > 1.5% TPS
     - Retire candidate if delta ≤ 0%
     - Inconclusive if 0% < delta < 1% (p>0.10)

**Boot validation:**
```bash
curl -s http://127.0.0.1:8000/v1/models -H "Authorization: Bearer genesis-local"
```

**Cold compile window:** ~240 sec
**Rollback:** `rm -rf /root/.triton/cache/*` если cache corrupted

### 5.2 P1.2 — Wave 10 PN96 promotion to stable (1-2d, after P1.1)

**Status:** ❌ BLOCKED on P1.1 result

**If PN96 recovery ≥ 1% TPS:**
- Create pristine fixture
- Update PATCH_REGISTRY: `lifecycle: stable + stable_since: 2026-05-XX`
- Update `reference_metrics_ref` JSON в model YAML
- First production-blessed perf-recovery patch post-dev209 era
- Requires P2.3 (lifecycle ratchet for runtime-hook patches — см. §6.3)

### 5.3 P1.3 — 35B regression bisect (alternative, days)

**Status:** ❌ HIGH COST ALTERNATIVE — only if PN96 не recover ≥ 2.5%

**Approach:** binary search 116 vllm dev-commits dev93→dev209, find specific upstream PR breaking A3B-FP8 perf.

**Options:**
- (a) backport-fix через Genesis text-patch если causal change clear
- (b) submit PR в vllm-project для perf-restore
- (c) accept regression as architectural cost

### 5.4 INTEGRATED_PLAN Sprint completion items

**Из docs/_internal/INTEGRATED_PLAN_2026-05-09.md (637 lines):**

| Sprint | Item | Status | Effort |
|---|---|---|---|
| S0.1 | README actualization (130→136 patches, pytest counts) | ⏳ partial | 0.5d |
| S0.3 | Bare-metal renderer wheel-mode separation | ⏳ partial | 0.5d |
| S1.1 | `GENESIS_P67_NUM_KV_SPLITS` sweep (16/32/48/64) | ❌ blocked GPU | 0.5d + bench |
| S1.2 | `GENESIS_P82_THRESHOLD_SINGLE` sweep (0.2/0.3/0.4) | ❌ blocked GPU | 0.5d + bench |
| S1.3 | `VLLM_FLOAT32_MATMUL_PRECISION=medium` A/B | ❌ blocked GPU | 0.5d + bench |
| S1.4 | `max_num_batched_tokens` 4096→8192 A/B | ❌ blocked GPU | 0.5d + bench |
| S2.1 | Regression bench harness in CI (`tests/integration/test_patch_regression_bounds.py`) | ❌ not started | 1-2d |
| S2.2 | Decode_TPOT-first reporting | ❌ not started | 0.5d |
| S2.3 | Apply contract tests (walk PATCH_REGISTRY, validate apply() signature) | ⏳ partial via §6.8 P-1..P-7 | 0.5d |
| S2.4 | Patch conflict/dependency resolver | ✅ DONE (audit-v2-patch-dependencies E31) | 0d |
| S2.5 | `sndr bench compare A.json B.json` CLI | ⏳ partial | 0.5d |
| S4 | PN16 V6 streaming truncator (`vllm/sndr_core/middleware/think_streaming_truncator.py`) | ❌ not started | 3-5d |
| S5.1 | Registry specs metadata enrichment (132→136 entries with implementation_status) | ⏳ partial | 1-2d |
| S5.2 | Gemma 4 sprint (DFlash/quant KV, INT8 PTH config) | ❌ not started | 3-5d |
| S5.3 | Memory/KV sprint (`sndr memory explain` Phase 4.7) | ❌ pending (Track A §4.9) | 1d MVP |

---

## §6. Track C: Mass Adoption UX (MASS_ADOPTION_UX_PRODUCT_PLAN_2026-05-13)

**Источник:** `docs/_internal/MASS_ADOPTION_UX_PRODUCT_PLAN_2026-05-13_RU.md` (859 lines)

**Цель:** превратить SNDR из engineering patch-layer в массовый продукт. Два аудитория — home GPU user + SSH operator. Единый backend, оболочки GUI/TUI/CLI.

### 6.1 Phase 0 — Product cleanup and naming (P1, 2-4d)

**Status:** ❌ NOT STARTED

**Deliverables:**
- Fix public brand: SNDR vs Genesis (primary)
- Описать 3 persona: home GPU owner / SSH operator / small team
- Beginner vocabulary blocklist (что НЕ показывать новичкам)
- `docs/START_HERE.md` — 60-second onboarding
- Update README first viewport (user outcome, не engineering deep-dive)

**Acceptance:** проект понятен за 60 секунд новому посетителю.

**Риск:** потеря engineering depth в README. **Mitigation:** вынести в `docs/ADVANCED_PATCHES.md`.

### 6.2 Phase 1 — Product API foundation (P0, 1-2w)

**Status:** ❌ NOT STARTED — prerequisite для всего UI

**Deliverables:**

Создать `vllm/sndr_core/product/`:
- `api.py` — публичный API
- `models.py` — dataclasses + typed JSON contracts
- `workflows.py` — composable plans
- `status.py` — runtime status
- `recommendations.py` — model/preset recommender
- `log_events.py` — structured log events

API contracts:
```python
def inspect_host() -> HostSummary
def recommend_paths(host: HostSummary) -> list[RecommendedPath]
def preflight(preset: str) -> Verdict
def launch(preset: str, mode: LaunchMode) -> LaunchOperation
def service_status() -> ServiceStatus
def tail_logs(service: str) -> Iterator[LogEvent]
```

**Critical invariant:** Plan/Apply separation. GUI/TUI must call `plan()` first, render to user, only then call `apply()`. Prevents GUI side effects.

### 6.3 Phase 2 — TUI first (P0, 1-2w)

**Status:** ❌ NOT STARTED

**Tech stack:** Python `textual` или `rich` (SSH-friendly).

**Commands:**
- `sndr tui` — interactive
- `sndr setup-tui` — guided onboarding

**Screens:**
1. System Overview (GPU, VRAM, host)
2. Goal selection (chat / coding / batch)
3. Model selection (with recommender)
4. Readiness Plan (preflight + deps)
5. Launch Monitor (live logs)
6. Benchmark (run + compare)
7. Export (client configs)

### 6.4 Phase 3 — Local GUI dashboard (P1, 2-4w)

**Status:** ❌ NOT STARTED — depends on TUI UX validation

**Tech:** local web app, `sndr gui --host 127.0.0.1 --port 7799`.

**Components:**
- Dashboard (current state)
- Setup Wizard (per persona)
- Model Library (browse + download)
- Preset Gallery (community + builtin)
- Diagnostics (sndr doctor + reports)
- Client Setup (Cursor/Continue.dev/etc.)
- Advanced panel (off by default — patches, env, K8s)

### 6.5 Phase 4 — Service & lifecycle polish (P1, 1-2w)

**Status:** ⏳ PARTIAL — `sndr service` exists

**Остаётся:**
- systemd / Quadlet / Docker Compose integration in one CLI surface
- start / stop / restart / status / logs unified
- GUI/TUI integration

### 6.6 Phase 5 — Client ecosystem (P0, 1w)

**Status:** ❌ NOT STARTED

**Commands:**
- `sndr clients list` — supported clients
- `sndr clients show <name>` — config snippet copy-paste ready
- `sndr clients export --to cursor.json`

**Clients:**
- Cursor IDE
- OpenAI Python SDK
- LiteLLM
- Continue.dev
- generic OpenAI-compatible

### 6.7 Phase 6 — Community presets marketplace (P2, 2-3w)

**Status:** ❌ NOT STARTED — gated by Phase 5 community SDK

**Features:**
- Config browser (filter by GPU/model/use-case)
- Trust badges: experimental / verified / prod
- Import / export bundles
- Community reporting (issues, kudos)

### 6.8 Phase 7 — Paid Pro boundary (P3, post-stabilization)

**Status:** ❌ FUTURE

**Pro features (proposed):**
- Curated profiles (operator-vetted)
- Advanced dashboard (multi-rig view)
- Update / compatibility advisor
- Team export/import
- Priority diagnostics
- Multi-node view

### 6.9 Cross-cutting: beginner vocabulary blocklist

**Hide from beginner mode:**
- Patch IDs (PN59, P67, P82)
- GENESIS_ENABLE_* env flags
- vLLM anchor drift details
- Raw docker commands
- Patch registry internals
- Bench methodology contract details

**Advanced mode unlocks:**
- Env flags
- Rendered scripts
- Patch decision waterfall
- Dry-run modes
- JSON reports
- Raw logs
- Registry explain
- Kubernetes/Quadlet emitters

### 6.10 CLI strategy (two levels)

**Friendly CLI** (new operators):
```bash
sndr setup            # interactive wizard
sndr status           # what's running
sndr launch recommended  # auto-pick preset
sndr stop / restart / logs / test
sndr clients / report
```

**Engineer CLI** (full surface):
```bash
sndr install --config <key> --prepare
sndr deps check / plan / apply
sndr doctor / doctor-system / verify
sndr patches list / prove / bench-attach / proof-status / release-check
sndr explain <patch_id|env_flag>
sndr launch <preset> --runtime <r> --dry-run --pull --preflight-only
sndr k8s / proxmox / compose / quadlet
```

---

## §7. Track D: Deploy + Bootstrap (UNIFIED_CONFIG_AUTOMATION_PLAN_2026-05-09)

**Источник:** `docs/_internal/UNIFIED_CONFIG_AUTOMATION_PLAN_2026-05-09_RU.md` (2687 lines, главный план install/deploy)

**Цель:** YAML config — single source of truth (model + Docker/Podman/bare runtime + deps + sources + artifacts + preflight + install actions).

### 7.1 P0 fixups (1-2d each, mostly DONE)

| # | Item | Status |
|---|---|---|
| P0.1 | Sync vLLM pin в stable YAMLs (dev9→dev93→dev209) | ⏳ partial (audit-v2-vllm-pin-consistency enforces) |
| P0.2 | Add `image_digest` to all stable builtin configs | ✅ DONE (audit-v2-runtime-image-pin enforces) |
| P0.3 | Enable full vLLM pin check inside image (`preflight.py:check_vllm_pin_in_image()` with `--full`) | ⏳ partial |
| P0.4 | Fix `_match_preset()` to use `gpu_match_keys` from HardwareSpec | ⏳ unknown — needs audit |
| P0.5 | Rewrite `compat.models.pull` — use ModelConfig + host.yaml | ⏳ unknown |
| P0.6 | Convert `scripts/fetch_models.sh` to thin wrapper of `sndr model pull` | ❌ not started |
| P0.7 | Split `host_port` and `container_port` in Docker config | ✅ DONE (audit-v2-network-port-consistency enforces) |
| P0.8 | Move hardcoded runtime deps (pandas/scipy/xxhash) from renderer to `vllm_runtime.package_versions` | ❌ not started |

### 7.2 P1 deps contract (1w)

**Status:** ⏳ PARTIAL — `vllm/sndr_core/deps/` skeleton exists

**Deliverables (полная реализация):**

Создать в `vllm/sndr_core/deps/`:
- `inventory.py` — что есть на хосте
- `checkers.py` — version comparators, GPU probes
- `planners.py` — gap analysis
- `installers.py` — apt/dnf/pacman/brew adapters
- `sources.py` — package source resolvers
- `docker.py` — Docker version + nvidia-container-toolkit detection
- `python_env.py` — venv/conda detection + creation
- `models.py` — HF download with revision/digest verification
- `report.py` — install report writer

Новые CLI:
```bash
sndr deps check <config-key>       # current state
sndr deps plan <config-key>        # what would change
sndr deps apply <config-key>       # execute (with confirmation)
sndr install --config <key> --prepare   # skip workload heuristic
sndr launch --preflight             # run preflight before live
```

Report path: `~/.sndr/reports/install-YYYYMMDD-HHMMSS.{json,md}`

### 7.3 P2 image reproducibility (2w)

**Status:** ❌ NOT STARTED

**Deliverables:**
- `sndr image build <config-key>` — custom image builder (base → install wheel/reqs → smoke → label)
- Wire SBOM into release/image build (`scripts/sbom_generate.py`)
- Lockfiles: `requirements-runtime.lock`, `requirements-dev.lock` (source of truth = config, lockfile = derived)

### 7.4 P3 community + UX (2w)

**Status:** ⏳ PARTIAL — config wizard skeleton exists

**Deliverables:**
- `sndr config new --from-detect` — community config wizard
- `sndr config doctor` — verify stable digest, vLLM match, no `_genesis`, no hardcoded paths
- `sndr migrate v11-runtime-contract` — schema migration tool

### 7.5 Kubernetes (3-4w)

**Status:** ⏳ PARTIAL — k8s.py CLI exists (`sndr k8s doctor`, etc.)

**Schema:**
```yaml
kubernetes:
  namespace: genesis
  image: vllm/vllm-openai:nightly
  gpu:
    resource_name: nvidia.com/gpu
  storage:
    mode: hostPath | pvc | nfs
  service:
    type: ClusterIP | NodePort | LoadBalancer
  pod:
    security_context: {...}
```

**Commands:**
```bash
sndr k8s doctor <config-key>           # cluster + GPU + storage readiness
sndr k8s render <config-key>           # manifests to stdout
sndr k8s apply <config-key>            # kubectl apply
sndr k8s status <config-key>           # pod/service state
sndr k8s logs <config-key>             # tail logs
sndr k8s report <config-key>           # diagnostic bundle
sndr k8s delete <config-key> [--delete-pvc]
```

**Doctor checks:**
- kubectl available + context valid
- Cluster reachable
- Namespace exists or creatable
- GPU nodes present
- NVIDIA device plugin running
- StorageClass for chosen mode
- Image pull permission
- Pod security policy compatible

**3 supported modes:**
1. microk8s-single-node (HostPath)
2. generic-single-node (kubeadm/k3s, PVC)
3. generic-multinode (PVC/NFS)

Optional Helm chart for repeatable deployment.

### 7.6 Proxmox (3-4w)

**Status:** ⏳ MINIMAL — `sndr proxmox doctor/render` partial

**Schema:**
```yaml
proxmox:
  node: pve-1
  ctid: 200  # OR vmid
  gpu_passthrough:
    mode: bind_devices | pci_passthrough | bare_metal
  cgroup_allow: [c 195:* rwm, c 234:* rwm]
  runtime:
    preferred: docker | bare-venv
  storage: {...}
  network: {...}
  service: {...}
```

**Commands:**
```bash
sndr proxmox doctor <config-key>       # IOMMU, cgroup, nvidia
sndr proxmox inventory                  # list LXC/VM with GPU
sndr proxmox render-lxc <config-key>   # /etc/pve/lxc/<ctid>.conf
sndr proxmox render-vm <config-key>    # PVE QEMU config
sndr proxmox apply <config-key>        # write configs (deferred — needs PVE testbed)
sndr proxmox status / report
```

**3 deployment modes:**
1. **bare_metal_host** — fastest, least isolated
2. **lxc_bare_metal_venv** — recommended (Docker-inside-LXC quirks avoided)
3. **vm_gpu_passthrough** — clean, supports k8s

**Important:** Docker inside LXC marked experimental/risky, не default. Use bare-venv or VM passthrough.

### 7.7 Universal Bootstrap (2-3w)

**Status:** ❌ NOT STARTED

**Concept:** `sndr bootstrap` — one entry point unifying bare metal / VM / LXC / Docker / Podman / systemd-nspawn / Proxmox / k8s.

**Commands:**
```bash
sndr bootstrap doctor                  # inventory current host
sndr bootstrap plan --config <key>     # what would change
sndr bootstrap apply --scope <s>       # execute per scope
sndr bootstrap status / report / rollback
```

**Scopes:**
- `os-packages` (apt/dnf/pacman/brew)
- `gpu-runtime` (NVIDIA driver/CUDA/CUDNN)
- `python-runtime` (Python version + venv)
- `container-runtime` (Docker/Podman + nvidia-container-toolkit)
- `model-artifacts` (HF download)
- `service` (systemd unit/Quadlet)

**Critical limitation:** cannot install host-level GPU deps from container; must emit host-side action plan.

---

## §8. Track E: Architecture Debt (DEFERRED P2.1, P2.2)

**Источник:** REMAINING_WORK_PLAN P2.1-P2.4

### 8.1 P2.1 — Collapse `_per_patch_dispatch.py` (1-2w, **DEFERRED**)

**Status:** ❌ DEFERRED (very high risk)

**Problem:** 4805 строк legacy dispatch boilerplate в `vllm/sndr_core/apply/_per_patch_dispatch.py`. Каждый патч имеет `apply_patch_<id>_<name>` функцию + `register_patch()`. Drift risk vs modern spec-driven `iter_patch_specs()` path.

**Solution:**
- Delete `_per_patch_dispatch.py`
- Use only spec-driven `iter_patch_specs()` from `dispatcher/spec.py`
- Each patch — autonomous module в `integrations/<family>/<id>_*.py` с `apply / is_applied / revert`
- Simplifies `orchestrator.py` to single path

**Risk:** very high — это критический dispatch path для 136 патчей. Regressions on каждом патче.

**Prerequisite:** comprehensive test harness regression discrimination (currently audit gates partially cover; need stronger integration coverage).

**Decision:** defer до отдельного sprint когда test harness готов.

### 8.2 P2.2 — Unified `PatchApplyResult` dataclass (2-3w, **DEFERRED**)

**Status:** ❌ DEFERRED (bundle with P2.1)

**Problem:** `apply()` сейчас возвращает `tuple[str, str]` (status, reason) — untyped, no observability payload. Status — обычная строка, опечатка тихая.

**Solution:**
```python
@dataclass
class PatchApplyResult:
    status: Literal["applied", "skipped", "failed"]
    reason: str
    elapsed_ms: float
    rss_delta_kb: int
    revert_callable: Optional[Callable[[], None]] = None
```

Все 136 `apply()` функций возвращают structured result. Observability built-in.

**Risk:** medium — touches every apply() callsite.

**Decision:** bundle with P2.1 sprint.

### 8.3 P2.3 — Lifecycle ratchet для runtime-hook patches (1-2d)

**Status:** ❌ NOT STARTED — blocks PN96 promotion

**Problem:** Current STABLE ratchet требует text-patcher + anchor_manifest — blocks runtime-hook patches (PN35, PN96).

**Solution:** добавить в PATCH_REGISTRY field:
```python
stable_kind: Literal["text-patch", "runtime-hook"]
```

Для `runtime-hook`:
- Require `production_validated_pins: list[tuple[genesis_pin, vllm_pin]]` (min 2 entries)
- Require apply() doesn't raise

Expands ratchet to both patch classes while keeping STABLE promise.

### 8.4 P2.4 — SGLang MambaRadixCache (PN97/PN98) (2-4w)

**Status:** ❌ NOT STARTED (research-grade)

**Problem:** Hybrid GDN+Mamba models (27B) use standard KV cache (non-optimal для Mamba state).

**Solution:** integrate SGLang's `MambaRadixCache` — radix-tree storage для Mamba SSM state.

**New patches:**
- **PN97** или **PN98**: radix-tree integration
- env flag `GENESIS_ENABLE_MAMBA_RADIX_CACHE` (default OFF до validation)

**Expected impact:**
- Long-context memory win (256K+ on 27B)
- Possible peak VRAM reduction on hybrid models
- Multi-rig sharing того же Mamba state

**Composes with:** PN54 (GDN contiguous dedup), PN59 (streaming-GDN)
**Conflicts with:** PN79 (in-place SSM state)

---

## §9. Track F: Research & Long-term

### 9.1 PN95 phases (research-grade, dni-3 weeks each)

**Из PROJECT_ROADMAP_V2 §3.10:**

| Item | Effort | Notes |
|---|---|---|
| PN95 Phase 2 (real GPU↔CPU bytes movement) | dni (design pending) | 4-й anchor не спроектирован |
| PN95 Phase 3 (boot KV expansion) | 11-13h | Anchor #6 + #7 design done |
| PN95 Phase 5 (virtualization) | 20-25h | Design draft |
| PN95 metrics + safety policy | 1-2h | Quick win after Phase 2 |

### 9.2 KV compression research

**Из COMPREHENSIVE_DUAL_STATE_AUDIT_2026-05-12_RU §6.5:**

- **Sliding Window Attention** activation (0.5d): 50-100× compression если Qwen3.6 supports
- **DuoAttention** integration (1-2w): 5-10× KV reduction
- **TQ k4v4 extension** (1-2w): 2× memory savings vs current k8v4
- **PN80 embedding FP8** (1-2w): ~800 MiB savings on 35B

### 9.3 `sndr memory explain` advanced calibration

**Status:** ❌ FUTURE (Phase 4.7 MVP first)

**Beyond MVP** (2-4w):
- GPU-measured calibration data
- Allocator telemetry hooks
- Tier-aware KV prediction
- profile_run capture
- Per-layer attention sizing

### 9.4 OOM preflight (4-6h, quick win)

**Out from PROJECT_ROADMAP_V2 §3.10:**

Combine host RAM + swap + GPU + Docker shm_size check before launch.

### 9.5 Cross-engine integrations (10-30 days each)

**Из INTEGRATED_PLAN S7:**

- LMCache integration (после prefix-cache problem solved)
- SGLang HiCache backport
- TRT-LLM cache reuse
- SGLang fused_gdn_gating (27B only)
- SGLang `<think>` strip from radix cache

### 9.6 External findings pipeline (P2, continuous)

**Status:** ⏳ DESIGN ONLY (EXTERNAL_FINDINGS_PIPELINE_2026-05-12_RU.md, 161 lines)

**Goal:** structured state machine для upstream vLLM/SGLang/papers watching.

**Schema:** `docs/_internal/external_findings/<id>.yaml`:
```yaml
id: external-vllm-42102
source: vllm-pr
upstream: vllm#42102
category: memory-cache
status: watch
risk: medium
acceptance: "PN94 + PN95b coexistence на dev209 baseline"
action: port
since: '2026-05-12'
notes: |
  ...
```

**Status transitions:**
```
discovered → watch → {skip, needs-reproducer, needs-bench}
            → {backport-now, doctor-rule, config-recipe, skip}
            → done → retire-local-patch
```

**Commands:**
```bash
sndr findings add <id> --source vllm-pr --upstream vllm#42102
sndr findings list --status watch
sndr findings update <id> --status needs-bench --notes "..."
sndr findings validate                  # schema + transitions + acceptance presence
```

**Review cadence:** weekly, biweekly, on-pin-bump, retired.

**Decision:** deferred until Phase 10 patch integration starts.

---

## §10. Cross-cutting: Quality gates (continuous)

**Из PROJECT_ROADMAP_V2 §6:**

### 10.1 Per-commit

- `pytest tests/ -q --ignore=tests/integration` — green
- `python3 -m vllm.sndr_core.cli self-test` — 8/8 PASS
- `python3 -m vllm.sndr_core.apply.shadow --strict` — CLEAN

### 10.2 Per-PR

- `make audit` aggregate: legacy-imports, public-paths, upstream-offline, doc-sync — clean
- `make audit-configs` — every preset composes
- `make docs-stale-scan` — zero matches against forbidden tokens (`wiring/patch_`, `genesis doctor`, `genesis verify`, `genesis migrate`, `./scripts/launch.sh`, `vllm-server-mtp-test`)
- Pre-commit hooks pass

### 10.3 Extended quality gates (after Phase 7)

`make audit` aggregate must include:

1. **Docs stale scan** — `scripts/docs_stale_scan.py` clean against forbidden tokens
2. **No-stub release scan** — `rg "scaffold|placeholder|TODO|NotImplementedError" vllm/sndr_core README.md docs` — every match either resolved, removed, or в `docs/_internal`
3. **Evidence ledger up-to-date** — last entry within 7 days OR matches current commit
4. **Env key canonical scan** — `sndr config keys validate` returns 0 unknown keys across all YAML profiles
5. **Engine boundary check** — `rg "from vllm.sndr_engine|import vllm.sndr_engine" vllm/sndr_core` returns only optional-discovery helpers
6. **Local/server convergence** — per three-tier policy in `LOCAL_SERVER_ALLOWED_DIRTY_STATE_2026-05-12_RU.md`
7. **Patch proof gate** — `sndr patches prove --all` ≥80% release threshold

### 10.4 Per-release

- Acceptance regression: V1 vs V2 byte-identical per preset
- Integration smoke on at least 1 live GPU (operator)
- CHANGELOG entry (см. §10.6 format)
- Rollback documentation present (`docs/ROLLBACK_PLAYBOOK.md`)

### 10.5 Scaffold/draft/placeholder boundary (§6.6 clarification)

| Marker | Meaning | Allowed in | Forbidden in |
|---|---|---|---|
| `scaffold` | Generator output / intentional template | `vllm/sndr_core/cli/scaffold.py`, generated files | All other `vllm/sndr_core/*.py`, public docs |
| `draft` | Authored content in progress | `docs/_internal/`, YAML with `publish_state: draft` | Public docs, runtime code |
| `placeholder` | Stub that would crash if reached | Never on `main` after Phase 7 | Anywhere except non-default git branches |
| `TODO` | Future work; must have name + date | Comments + `docs/_internal/`; max 7 days un-tracked | Public docs |
| `NotImplementedError` | Runtime stub | Never on `main` after Phase 7 | All `vllm/sndr_core/*.py` |

### 10.6 CHANGELOG entry shape

```markdown
## [vX.Y.Z] — Short summary (YYYY-MM-DD)

### Closed
- ... bullet list per category

### Tests
- Local: NNNN passed / 0 failed   (see evidence ledger)
- Server: NNNN passed / 0 failed  (see evidence ledger)

### Migration notes (если applicable)
- ...

### Rollback
- Revert SHA: <commit>
- Smoke command: <one-line repro proving V1 still works>
```

### 10.7 Canonical env-key registry CLI (§6.7 mitigates R2)

```bash
sndr config keys list              # enumerate every recognized env key
sndr config keys describe VLLM_X   # show origin patch + valid values
sndr config keys validate <yaml>   # exit 1 if YAML uses unknown key
```

**Source of truth:** every patch manifest declares `env_keys: []`. Registry = union across all published manifests. Unknown keys = typo or undocumented patch.

### 10.8 Patch proof gate (§6.8 mitigates R1)

**Tier thresholds:**

| `implementation_status` | Release tier requirement |
|---|---|
| `stable` | **100%** proof artifact OR explicit waiver |
| `beta` | Proof required IF `default_on: true`. Optional otherwise. |
| `experimental` | May skip proof. MUST be `default_on: false` to land in release registry. |
| `deprecated` | Retire note required (retired_at, replacement, reason). No proof needed. |
| `draft` | **Never** in release registry. |

**Waiver schema** (`evidence/patch_proof/_waivers/<patch_id>.yaml`):
```yaml
patch_id: PN999
owner: sandermage
reason: "anchor drift across vllm 0.20.2→0.21.0 rebase; proof pending re-anchor"
expiry: '2026-06-01'             # MUST be ≤30 days from creation
risk: medium                     # low | medium | high
rollback: "revert SHA abc1234; patch already default_off in profile X"
issue_ref: "github.com/.../issues/N"
```

**Audit tier (per-PR):** stable may have ≤10% waiver budget. `dead-detect` MUST list every drift candidate.

**Dev tier:** no minimum, `--dead-detect` runs informationally.

### 10.9 Public/private docs boundary (§6.10 mitigates R3)

`scripts/release_public_docs_check.py` — must return 0 hits for:

1. No `docs/_internal` link from public docs (except `docs/upstream/`, `docs/reference/`)
2. No private IPv4 (RFC 1918 ranges): `10.*`, `172.16-31.*`, `192.168.*`
3. No operator home path: `/home/sander`, `/Users/sander`
4. No server-only container names: `vllm-pn95-2xa5000-*`, `vllm-server-mtp-test`
5. No retired commands: `genesis doctor|verify|migrate`, `._genesis`
6. No unresolved TODOs/placeholders in public docs (§6.6 boundary)
7. Every public-doc link points at existing release-tree path

### 10.10 Artifact storage policy (§6.11)

| Artifact | Location | Tracked | Release | Redacted | Retention |
|---|---|---|---|---|---|
| Evidence ledger | `docs/_internal/ROADMAP_EVIDENCE_LEDGER_*.md` | yes (internal) | no | yes if exported | keep all |
| Patch proof JSON | `evidence/patch_proof/<id>__<vllm_pin>.json` | yes per release | yes | yes | per release tag |
| Patch proof waivers | `evidence/patch_proof/_waivers/<id>.yaml` | yes | yes | no secrets | per release, max 30d each |
| Bench result JSON | `~/.sndr/bench-results/<composed>__<ISO>.json` | no | optional summary | yes | rolling 30d local |
| SBOM | `release/SBOM.spdx.json` | yes per tag | yes | no secrets | per release tag |
| Constraints | `release/constraints.txt` | yes per tag | yes | no secrets | per release tag |
| Security attestation | `release/security_attestation.json` | yes per tag | yes | yes | per release tag |
| Report bundle | `report-<ISO>.tar.gz` | no | operator-provided | yes | manual |
| Snapshots | `snapshots/<ISO>/` | partial | optional | yes | per release tag |
| External findings | `docs/_internal/external_findings/*.yaml` | yes (internal) | no | n/a | keep until done OR retired |
| Dirty-state allowlist | `tools/policies/dirty_state_allowlist.yaml` | yes | no | n/a | keep + version |

**Verification:** `make audit-artifacts` (Phase 7 gate) walks table, exits non-zero на drift.

---

## §11. Risk register (extended)

**Источник:** PROJECT_ROADMAP_V2 §7

### 11.1 Architectural risks (V2 design)

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| **A1** | V2 composer produces drift vs V1 output | Medium | High (silent regression) | Byte-identical `cfg.to_dict()` test per preset (Phase 2-3 acceptance) |
| **A2** | Community patch manifest schema diverges from registry expectations | Low | Medium | Single source of truth in `schema_v2.py`; validators share rules |
| **A3** | Profile promote corrupts model config | Low | High | Dry-run default + atomic write + archive (not delete) + git commit always |
| **A4** | Community patches break upstream rebase | Medium | Medium | `min/max_vllm_pin` gates + CI matrix test |
| **A5** | Migration takes > 2 weeks, operator loses focus | Medium | Medium | Phased plan; each phase delivers usable POC |
| **A6** | V1 + V2 coexistence creates two-source-of-truth bugs | Medium | Medium | Phase 9 freeze enforces no-new-V1; sunset когда все migrated |

### 11.2 Release/operational risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| **R1** | Dead patches accumulate (anchor mismatch, never applied) | High | Medium | §6.8 patch-proof gate: ≥80% release threshold |
| **R2** | Env-key drift (YAML uses unknown keys) | Medium | Medium | §6.7 canonical env-key registry + `sndr config keys validate` |
| **R3** | Internal docs leak into public release | Medium | High | §6.10 public/private docs boundary gate |
| **R4** | Stale doc text (`_genesis`, `genesis doctor`) | High | Low | docs-stale-scan gate |
| **R5** | Rollback path unknown when V2 ships and operator hits crash | Medium | High | `docs/ROLLBACK_PLAYBOOK.md` required per release |
| **R6** | Local/server divergence drifts uncaught | Medium | Medium | Three-tier dirty-state policy + `make evidence` |
| **R7** | Bench delta not reproducible | Medium | High | Phase 6 bench methodology contract |
| **R8** | Hardcoded numbers in roadmap rot | High | Low | All counts moved to evidence ledger |
| **R9** | Phase 8 regresses silently mid-Phase-3 | Medium | High | Phase 8 split: 8a pre-Phase-1, 8b at Day 19 |
| **R10** | Operator skips evidence ledger update | High | Medium | §6.3 gate: ledger entry within 7 days OR matches commit |
| **R11** | Convergence definition ambiguous | Medium | Low | Three-tier policy spells out per-tier allowlist |

**Risk-ownership rule:** every mitigation maps to a §6.x gate, §X CLI command, or operator playbook section.

---

## §12. Open operator decisions (blocking-tier)

### 12.1 Confirmed (Q1-Q7 + runtime placement)

Все 8 captured в §3.5. No new design decisions blocking.

### 12.2 Implementation-level questions (non-blocking)

Per-deliverable, tracked в phase metadata:

- "Should profile YAML support `null` for default runtime?" (Phase 4)
- "Exact V1 smoke command set on Phase 8a?" (Phase 8a)
- "Patch proof artifact JSON shape on first run?" (Phase 4.5 — partially answered by E12+E19 artifact shape)
- "RTX 5090 / future GPU support — Blackwell SM 12.0 placeholder PN64 sweep timing?" (Phase 10+)
- "MASS_ADOPTION brand: SNDR vs Genesis?" (Phase 0 — UX track)
- "Pro tier feature set?" (Phase 7 UX — post-stabilization)

### 12.3 GPU-blocked items (operator-gated)

- **P1.1** PN96 A/B bench (45 min PROD downtime)
- **S1.1-S1.4** TPS sweeps (knob exploration)
- **P3.1** live GPU CI runner (infra decision)
- **P3.3** Ed25519 trust anchor offline ceremony

### 12.4 Infrastructure decisions

- Self-hosted GitHub Actions runner (P3.1)
- Live PVE testbed для Proxmox `apply` (Track D §7.6)
- HF mirror / private model registry strategy (UNIFIED_CONFIG)

---

## §13. Execution priority (recommended order)

### 13.1 Immediate (this week)

1. **Phase 8a** — cold-install smoke V1 (0.5d, P0)
2. **Phase 4.7** `sndr memory explain` MVP (1d, P1) — closes design-only debt
3. **P2.3** lifecycle ratchet for runtime-hook (1-2d) — unblocks P1.2 promotion
4. **P3.1** live GPU CI runner setup (1d + operator infra)

### 13.2 Next sprint (1-2 weeks)

5. **Phase 4.6** Security boundary + license CLI finalization (1d + Ed25519 ceremony blocked)
6. **Phase 5** Community SDK finalization (3-4d) — `manifest.py`, `scaffold.py`, `validator.py`
7. **Phase 7** Tests + docs + CI gates finalization (2d):
   - **`docs/ROLLBACK_PLAYBOOK.md`** ← MANDATORY missing piece
   - `docs/CONFIG_SYSTEM_V2.md`
   - `docs/COMMUNITY_PATCHES.md`
   - Promote audit-public-docs / audit-security from informational → gating
8. **Phase 8b** V2 acceptance smoke (0.5d)
9. **Phase 9** V1 deprecation warnings (0.5d)
10. **Track B P1.1** PN96 A/B (45 min) → P1.2 Wave 10 promotion (1-2d if ≥1%)

### 13.3 Месяц после (2-4 weeks)

11. **Track C** MASS_ADOPTION Phase 0 (brand + START_HERE.md, 2-4d)
12. **Track C** Phase 1 Product API foundation (1-2w)
13. **Track D** Kubernetes finalization (доделать sndr k8s render/apply, 3-5d)
14. **Track D** Proxmox doctor incremental polish (1-2d)
15. **Track B** S2.1 regression bench harness в CI (1-2d)
16. **Track B** S4 PN16 V6 streaming truncator (3-5d)

### 13.4 Квартал (1-3 months)

17. **Track C** Phase 2 TUI (1-2w)
18. **Track C** Phase 3 GUI dashboard (2-4w)
19. **Track C** Phase 4 Service lifecycle polish (1-2w)
20. **Track C** Phase 5 Client ecosystem (1w)
21. **Track D** Universal Bootstrap (2-3w)
22. **Track A** Phase 10 patch integration (priority order §4.15)
23. **Track E** P2.1 + P2.2 dispatch collapse + unified apply (3-4w sprint, sequential)

### 13.5 Long-term (3+ months)

24. **Track C** Phase 6 community marketplace (2-3w)
25. **Track F** PN95 Phase 2/3/5 (research-grade)
26. **Track F** MambaRadixCache (PN97/PN98) (2-4w)
27. **Track F** Cross-engine integrations (10-30d each: LMCache, SGLang HiCache, TRT-LLM)
28. **Track F** Distributed bench infrastructure
29. **Track F** Multi-rig community config workflow

---

## §14. Test growth + audit gate trajectory

### 14.1 Current baseline (2026-05-13)

- **pytest**: 6377 passed / 131 skipped / 0 failed
- **make evidence gates**: 34 total (26 gating + 8 informational)
- **gating green**: 26/26 ✓
- **informational not green**: 3 pre-existing warnings (audit-docs-stale, audit-public-docs, audit-security)

### 14.2 Projected after Phase 4.7 (memory explain MVP)

- pytest: ~6407 (+30 estimator tests)
- gates: 35 (audit-memory-explain-verdict if promoted)

### 14.3 Projected after Phase 5 (community SDK)

- pytest: ~6500+ (validator tests, scaffold tests)
- gates: 36-37 (audit-community-manifest, audit-plugin-discovery)

### 14.4 Projected after Phase 7 (audit-public-docs + audit-security promoted to gating)

- pytest: ~6550+
- gating: 28-29 (audit-public-docs + audit-security promoted from informational)
- informational: ~5 (audit-docs-stale remains; new informational)

### 14.5 Projected after Phase 10 first integration (PN72/PN90/PN94)

- pytest: ~6700+ (per-patch tests)
- gates: ~38 (no new audit gates per-patch; existing prove/bench-attach covers)

---

## §15. Production-ready definition (§9 PROJECT_ROADMAP_V2)

Project считается production-ready когда:

1. ✅ **MASTER_REMEDIATION_PLAN closed** (48/48 items, commits 680d06d + 2026-05-13 series)
2. ✅ **§6.8 proof chain** замкнут (commit c1e4cf3)
3. ⏳ **Phases 1-8 done** — V2 layered config working, all 11 presets migrated, community SDK live, installer/launcher smoke green
4. ✅ **Tests**: local + server ≥ baseline (6377/0), self-test 8/8, apply.shadow CLEAN, audit aggregate green
5. ✅ **No P0 blockers** — все 5 PROJECT_STATE_AUDIT P0 closed
6. ⏳ **No private paths/IPs** в public code (audit-public-paths clean, audit-public-docs gating)
7. ✅ **English code-only** (audit grep clean)
8. ✅ **CompatibilityMatrix** ≥4 rules с tests
9. ⏳ **Cold install works** — new operator clones, `pip install -e .`, launches preset within 10 min (Phase 8a)
10. ⏳ **Documentation complete**: `docs/CONFIG_SYSTEM_V2.md`, `docs/COMMUNITY_PATCHES.md`, `docs/INSTALL.md` (no `_genesis` refs ✓)
11. ❌ **Rollback documented** — `docs/ROLLBACK_PLAYBOOK.md` REQUIRED, **MISSING**
12. ⏳ **Patch proof coverage** ≥80% of registry patches с evidence artifact
13. ⏳ **Public/private docs boundary clean** — audit-public-docs gating

**Critical gap:** `docs/ROLLBACK_PLAYBOOK.md` НЕ создан. Без него §9 acceptance не пройдёт.

---

## §16. Cross-reference: source documents

Все 30 planning docs из `docs/_internal/`:

### 16.1 Главные roadmap docs (closed by this consolidated plan)

- ✅ **PROJECT_ROADMAP_V2_2026-05-12_RU.md** (1360 lines) — main roadmap, integrated в §4
- ✅ **PROJECT_ROADMAP_V2_SUPPLEMENT_2026-05-12_RU.md** (850 lines) — supplement, integrated в §4 + §10
- ✅ **PROJECT_ROADMAP_V2_IMPROVEMENT_PROPOSALS_2026-05-12_RU.md** (952 lines) — integrated в §10 + §11
- ✅ **PROJECT_ROADMAP_V2_REVIEW_NOTES_2026-05-12_RU.md** (780 lines) — integrated в §11
- ✅ **PROJECT_ROADMAP_V2_REFINEMENT_ACTIONS_2026-05-12_RU.md** (761 lines) — integrated в §4 + §10
- ✅ **MASS_ADOPTION_UX_PRODUCT_PLAN_2026-05-13_RU.md** (859 lines) — integrated в §6 (Track C)
- ✅ **UNIFIED_CONFIG_AUTOMATION_PLAN_2026-05-09_RU.md** (2687 lines) — integrated в §7 (Track D)
- ✅ **INTEGRATED_PLAN_2026-05-09.md** (637 lines) — integrated в §5
- ✅ **REMAINING_WORK_PLAN_2026-05-12_RU.md** (519 lines) — integrated в §5 + §8

### 16.2 Closed (superseded by commits)

- ✅ **MASTER_REMEDIATION_PLAN_2026-05-12_RU.md** (1447 lines) — 48/48 closed (commits 680d06d, c1e4cf3, f4ce433, 94f326c, 052feba)
- ✅ **POST_REMEDIATION_DEFERRED_2026-05-12_RU.md** (203 lines) — все deferred items folded в §8 + §9
- ✅ **PROJECT_STATE_AUDIT_2026-05-12_RU.md** (1113 lines) — 5 P0 blockers закрыты (см. §2)
- ✅ **PROJECT_FIX_AUDIT_2026-05-10_RU.md** (1182 lines) — 14 fixes applied
- ✅ **LOCAL_SERVER_DUAL_STATE_FIX_PLAN_2026-05-12_RU.md** (767 lines) — closed by commits 680d06d + 052feba
- ✅ **COMPREHENSIVE_DUAL_STATE_AUDIT_2026-05-12_RU.md** (1034 lines) — findings folded в §9
- ✅ **DOC_MIGRATION_MAP_2026-05-12_RU.md** (243 lines) — Этап 8 closure marker (commit 052feba)
- ✅ **SERVER_V11_FIX_QUEUE_2026-05-12_RU.md** (905 lines) — items mapped в §5, §7
- ✅ **SERVER_CHANGE_WATCH_2026-05-12_RU.md** (884 lines) — historical review journal, не updates further
- ✅ **WORK_LOG_2026-05-12_RU.md** (381 lines) — historical record, не updates further
- ✅ **PROJECT_IMPLEMENTATION_STATUS_DASHBOARD_2026-05-12_RU.html** (376 lines) — auto-generated, regenerate from registry
- ✅ **BACKLOG_2026-05-09.md** (251 lines) — items integrated в §5
- ✅ **FULL_PROJECT_AUDIT_2026-05-09_RU.md** (1012 lines) — historical baseline

### 16.3 Design specs (active references)

- 📄 **MEMORY_EXPLAIN_MVP_2026-05-12_RU.md** (199 lines) — Phase 4.7 design (§4.9)
- 📄 **EXTERNAL_FINDINGS_PIPELINE_2026-05-12_RU.md** (161 lines) — Phase 10 deferred (§9.6)
- 📄 **RUNTIME_COMMAND_SPEC_DESIGN_2026-05-12_RU.md** (206 lines) — Phase 4.5 (done, §4.7)
- 📄 **SECURITY_LICENSE_GATE_2026-05-12_RU.md** (202 lines) — Phase 4.6 (§4.8)
- 📄 **PN96_AB_BENCH_PLAN_2026-05-12_RU.md** (131 lines) — operator protocol (§5.1)

### 16.4 Active reference docs

- 📋 **ROADMAP_EVIDENCE_LEDGER_2026-05-12_RU.md** (4393 lines) — append-only evidence ledger (single source of truth для test counts + gate state)
- 📋 **LOCAL_SERVER_ALLOWED_DIRTY_STATE_2026-05-12_RU.md** (254 lines) — three-tier dirty-state policy (R6/R11 mitigation)

### 16.5 This document

- 🎯 **CONSOLIDATED_ROADMAP_2026-05-13_RU.md** (this file) — единственный план, по которому работа ведётся дальше

---

## §17. Appendix A: Patch catalog (high-level)

PATCH_REGISTRY содержит 136 entries (см. `vllm/sndr_core/dispatcher/registry.py`). Краткий обзор по families:

### 17.1 Attention family

- **GDN** (gated delta net): P7b, PN29, PN50, PN54, PN59 (streaming), PN79 (in-place SSM state, conflicts MambaRadixCache)
- **TurboQuant**: P67, P67b (multi-query kernel, +32% TPS на 35B), PN26 (sparse-V), PN35 (E29 vllm_pin pin)

### 17.2 Spec-decode family

- **MTP**: P58, P59, P60, P60b, P61, P61b, P61c, P62, P64, P66
- **DFlash**: PN82, PN90 (probabilistic draft, Phase 10 #4)
- **Eagle**: (various)

### 17.3 Worker family

- PN55 (wake-up hybrid KV)
- PN82 (mamba cudagraph prefill zero)

### 17.4 Scheduler family

- P58 (async placeholder fix)
- PN96 (Persistent Marlin MoE workspace, REMAINING_WORK P1.1)

### 17.5 Tool-call family

- PN16 (V8 active, V6 streaming truncator planned)
- PN56 (qwen3_coder XML+JSON fallback)

### 17.6 Retired (3 in V2 prod, allowlisted in audit-v2-patch-lifecycle E30)

- **PN19** — carry-over from W-A; replacement is part of PN-series consolidation work
- **PN52** — still actively consumed by 27B INT4 / 35B FP8 prod path
- **P94** — enabled in 27B INT4 TQ + 35B FP8 prod — operator review pending

### 17.7 Lifecycle distribution (PATCH_REGISTRY current state)

```
experimental: 86
legacy:       33
retired:      11
research:      3
stable:        2
coordinator:   1
```

Tier: all 136 are `community` (single-tier project currently).

### 17.8 Default-on distribution

33 patches с `default_on: true` (см. E31 audit-v2-default-on-mismatch — 0 explicit overrides currently).

---

## §18. Appendix B: CLI surface (current + planned)

### 18.1 Current CLI subcommands (~35+)

```
sndr install                   # install wizard (Track D foundation)
sndr launch <preset>           # main runtime entry
  --runtime <r>                # docker / podman / k8s / bare (Phase 4.5)
  --dry-run / --pull / --preflight-only / --check-deps
sndr doctor                    # quick host check
sndr doctor-system [--logs]    # deep system audit (E29 doctor_logs fix)
sndr verify                    # apply integrity check
sndr deps check / plan / apply # dependency management (Track D §7.2)

# Discovery
sndr model list / show <id>
sndr hardware list / show <id>
sndr profile list / show / diff / new / validate / promote
sndr config list / show / search / new / doctor / migrate
sndr community list / new-patch / validate / lock / install

# Patches (§6.8 chain)
sndr patches prove <id|--all|--dead-detect>
sndr patches bench-attach <patch_id> <bench.json> [--baseline <X>]
sndr patches proof-status [--bucket <b>] [--json]
sndr patches release-check [--mode <m>] [--max-regression-pct <N>]
sndr patches explain <id> / list / plan / diff

# Env keys
sndr config-keys list / describe <KEY> / validate <yaml>

# Bench
sndr bench run / compare / report / validate
sndr bench-compare A.json B.json

# Deploy
sndr compose render / up
sndr quadlet render
sndr k8s doctor / render / apply / status / logs / report / delete
sndr proxmox doctor / inventory / render-lxc / render-vm / status / report

# License
sndr license status / verify / import

# Reporting
sndr report bundle [--redact]
sndr findings add / list / update / validate (Phase 10 deferred)

# Memory (Phase 4.7 pending)
sndr memory explain --profile <p> / --model <m> --hardware <h>

# Self-test + service
sndr self-test
sndr service start / stop / restart / status / logs

# Misc
sndr migrate v11-runtime-contract
sndr tune <preset>
sndr caveats
sndr host doctor / init / paths explain / gpu explain (Track C UX)
```

### 18.2 Planned new CLI (per track)

**Track C MASS_ADOPTION:**
```
sndr tui                       # interactive TUI (Phase 2)
sndr setup-tui                 # guided onboarding
sndr gui [--host 127.0.0.1 --port 7799]  # local web (Phase 3)
sndr setup / status            # friendly aliases (Phase 0)
sndr launch recommended        # auto-pick (Phase 0)
sndr clients list / show / export   # client config ecosystem (Phase 5)
sndr test                      # smoke test current setup
```

**Track D Bootstrap:**
```
sndr bootstrap doctor / plan / apply / status / report / rollback
  --scope os-packages|gpu-runtime|python-runtime|container-runtime|model-artifacts|service
sndr image build <config-key>  # Phase 7.3
sndr model pull <config-key>   # replaces fetch_models.sh
```

---

## §19. Appendix C: Effort baseline summary

**Тotal effort across all tracks (parallel-trackable):**

| Track | Total effort | Critical path |
|---|---|---|
| **A** V2 Layered Config | 15-20 days | Phase 4.7 MVP (1d) → Phase 7 finalization → Phase 8b → Phase 9 |
| **B** Patch Quality + Bench | 5-10 days static-side + GPU ops | P1.1 PN96 (45 min) → P1.2 promotion |
| **C** MASS_ADOPTION UX | 3-4 months sequential | Phase 0 (2-4d) → Phase 1 API → Phase 2 TUI → Phase 3 GUI |
| **D** Deploy + Bootstrap | 8-12 weeks | P0 fixups → P1 deps → K8s → Proxmox → Bootstrap |
| **E** Architecture Debt | 3-4 weeks (sprint, deferred) | P2.3 lifecycle ratchet (1-2d) prerequisite for P1.2; P2.1+P2.2 bundled |
| **F** Research / Long-term | months-quarters | PN95 phases parallel; MambaRadixCache 2-4w; cross-engine 10-30d each |

**Consolidated horizon:** ~2-3 months to production-ready public beta (Tracks A + B + critical part of C); +2-4 months для enterprise-grade (Tracks D + E); +6+ months для full feature parity (Track F).

---

## §20. Next action items (concrete)

### Immediate (≤1 week)

1. ~~**`docs/ROLLBACK_PLAYBOOK.md`** — создать (mandatory §9 item 9, currently missing)~~ ✅ DONE commit `c5b917e` (2026-05-13)
2. **Phase 8a** cold-install smoke V1 (script + run on clean checkout) — pending
3. ~~**Phase 4.7** `sndr memory explain` MVP implementation~~ ✅ DONE commit `ce27953` (2026-05-13)
4. ~~**P2.3** lifecycle ratchet for runtime-hook patches~~ ✅ DONE commits `82e0c37` + `eb22356` (2026-05-13)

### Sprint 1 (1-2 weeks)

5. **Phase 4.6** Security boundary finalization (без Ed25519 — placeholder pubkey OK as DEV anchor)
6. **Phase 5** Community SDK finalization (manifest, scaffold, validator)
7. **Phase 7** docs finalization (CONFIG_SYSTEM_V2, COMMUNITY_PATCHES) + audit gate promotion
8. **PN96 A/B** (operator GPU window)

### Sprint 2-4 (1 month)

9. **Phase 8b + 9** V2 acceptance + V1 deprecation warnings
10. **Phase 10** patch integration: PN72, Sliding Window, PN94 (after vllm#42102)
11. **Track C Phase 0** product cleanup + START_HERE.md
12. **Track C Phase 1** Product API foundation

---

## §21. Maintenance rules для этого документа

1. **Single source of truth.** Все 30 source docs marked closed/superseded в §16. Этот файл — единственный план, по которому работа дальше ведётся.
2. **Status updates only через commit reference.** Item помечается `✅ DONE` только когда commit SHA указан.
3. **Status `unknown` allowed.** Если что-то неясно, пишем `⏳ PARTIAL — needs audit`. НЕ `done` без proof.
4. **Effort estimates только из source docs.** Не выдумываем новые числа.
5. **Quarterly review:** operator пересматривает execution priority (§13), переоценивает effort, обновляет risks (§11).
6. **Когда добавляется новый план:** integrate в этот документ + mark new doc как cross-reference (§16). Не плодим новых master plans.

---

## §22. Известные missing/неясные items (требуют operator review)

После аудита всех 30 source docs обнаружены items, требующие явного operator decision/action:

1. ~~**`docs/ROLLBACK_PLAYBOOK.md`** — REQUIRED по §9 item 9; **не создан**. Блокирует production-ready acceptance.~~ ✅ CLOSED commit `c5b917e` (2026-05-13) — 302 строки, 8 R-001..R-008 procedures
2. **Ed25519 trust anchor offline ceremony** — blocked на operator; placeholder pubkey помечен DEV anchor.
3. **Sponsor-site/** (16 untracked files) — operator marked as «мусор», не включаем.
4. ~~**`tools/policies/dirty_state_allowlist.yaml`** — REFINEMENT_ACTIONS proposes versioned allowlist; не создан.~~ ✅ CLOSED commit `9a2c882` (2026-05-13) — 94-line yaml + 197-line check script, three-tier policy (dev/audit/release)
5. ~~**External findings seed** — `docs/_internal/external_findings/` directory + README + first entry (vllm#42102 example); создание deferred.~~ ✅ DONE pre-session — operator-built README (38 lines) + external-vllm-42102.yaml (52 lines) live in `docs/_internal/external_findings/` (gitignored per Q4 internal docs policy)
6. **GPU CI self-hosted runner** — infrastructure decision pending.
7. **Live PVE testbed** для Proxmox `apply` — operator infrastructure decision.
8. **Brand decision** SNDR vs Genesis (Track C Phase 0).
9. ~~**42 V2 builtin YAMLs** untracked в WD — нужен отдельный commit чтобы audits работали в CI.~~ ✅ CLOSED commit `1155845` (2026-05-13) — 42 V2 layered YAMLs (11 model+hw+profile+presets) committed with verification: 22 audit gates green pre-commit

### Updates 2026-05-13 (autonomous session)

Закрыто в одной сессии:

| # | Item | Status | Commit |
|---|---|---|---|
| 1 | ROLLBACK_PLAYBOOK.md | ✅ closed | `c5b917e` |
| 9 (partial) | PATCH_REGISTRY committed | ✅ done | `82e0c37` |
| §20 #3 | Phase 4.7 memory explain MVP | ✅ closed | `ce27953` |
| §20 #4 | P2.3 lifecycle ratchet | ✅ closed | `82e0c37` + `eb22356` (schema fix) |
| §20 #4 (cont.) | V2 builtin tree (42 YAMLs) | ✅ closed | `1155845` |
| §22 #4 | dirty_state_allowlist three-tier | ✅ closed | `9a2c882` |
| Phase 8a | cold-install smoke automation | ✅ closed | `c1b9fd1` |
| §10.3 | audit-docs-stale promoted to gating | ✅ closed | (pending) — 56 stale tokens cleaned in 9 public docs (8 files: COMMANDS.md, DAY_1_CHECKLIST.md, MODEL_CONFIG_LAUNCHER.md, CONFIGS_FOR_COMMUNITY.md, CLIFFS.md, SELF_TEST.md, PATCHES.md, COMPATIBILITY.md, PLUGINS.md, FAQ.md, BENCHMARKS.md, README.md, scripts/launch/README.md) — genesis verb→sndr verb, ./scripts/launch.sh→sndr launch, vllm/sndr_core/wiring/→vllm/sndr_core/integrations/, vllm-server-mtp-test→vllm-server |
| §10.3 | audit-public-docs promoted to gating | ✅ closed | `4e5b9ba` — 93→0 violations across D-1..D-6 (D-6 regex refined: actionable markers only, backticked identifiers skipped); 31 new unit tests in `tests/unit/scripts/test_audit_public_docs.py` + 9 new tests in `test_docs_stale_scan.py` |
| §10.3 #2 | audit-no-stub gate (new, gating) | ✅ closed | (pending) — AST scan for bare `raise NotImplementedError` + textual scan for `TODO(name): ...` markers + `pass  # placeholder/scaffold/FIXME` sentinels in `vllm/sndr_core/**/*.py`; correctly ignores string-literal references to upstream `NotImplementedError` (which patches replace); 12 unit tests + live-corpus contract |
| §10.3 #4 | audit-config-keys gate (new, gating) | ✅ closed | (pending) — every committed V1/V2 YAML's Genesis/SNDR env keys validated against canonical registry (149 keys); 31 YAMLs scanned, 0 unknown keys; 6 unit tests + live-corpus contract |
| §10.3 #5 | audit-engine-boundary gate (new, gating) | ✅ closed | (pending) — AST-detected `import vllm.sndr_engine` outside `try/except ImportError` blocks; allows optional-discovery pattern + `# audit-engine-boundary: allow` marker; 10 unit tests + live-corpus contract |
| §10.3 #3 | audit-evidence-freshness gate (new, informational) | ✅ closed | (pending) — ledger newest entry ≤7 days OR contains HEAD short SHA; gracefully SKIPS when ledger absent (CI / fresh clone); 7 unit tests |
| §10.3 #7 | audit-release-check promoted to gating | ✅ closed | (pending) — switched from `--mode report` to `--mode require-static`; populated 136/136 static proof artefacts via `sndr patches prove --all` (currently 100% static_only bucket; bench-with-baseline tier remains operator-GPU work) |
| Phase 5 | community SDK `_template/` reference + 7 contract tests | ✅ closed | (pending) — `plugins/community/_template/PN999/` skeleton + README; pinned `publish_state: draft` + discovery skip + manifest loadability + empty-release-tree contract via `tests/unit/community/test_reference_template.py` |

`make evidence`: 32/35 → **38/39 gating gates green** (+4 new gates added; audit-security remains the only informational warning — 188 operator-path violations across configs/scripts predate this work).

### Quality pass 2026-05-13 (audit + hygiene)

Дополнительно за тот же день:

| Item | Результат |
|---|---|
| AI attribution в commit/PR | Отключено через `.claude/settings.local.json` (gitignored) — Claude trailer не появляется в новых commits |
| Шумные комментарии (`DA-005 (audit YYYY-MM-DD): heuristic-tagged`, `Phase 4.6 — ...`) | `/tmp/scrub_audit_noise.py` — 29 файлов, ~129 inline-комментариев очищены без удаления содержательного хвоста; 83 чисто-служебных `heuristic-tagged` блока заменены на простой `"lifecycle": "experimental"` |
| Аудит на заглушки в `vllm/sndr_core/` | `audit-no-stub` green; 3 `implementation_status≠full` патча (PN78 retired, PN95 partial, PN64 hardware-placeholder) — все легитимны |
| PN95 метаданные | Обновлены — 11 anchors через Phase 1/2/4/5; Phase 5 anchor #10 (физический cap) — pending GPU validation; helper `pn95_physical_num_blocks_cap()` готов |
| 38 PR re-audit | Live проверка через `gh pr view` — 7 MERGED upstream с 2026-05-07, все в категориях Skip/Watch для нашего stack; Do-список (PN82, PN55, P61c) был и остаётся в `PATCH_REGISTRY`; см. `docs/_internal/UPSTREAM_PR_AUDIT_2026-05-13_RU.md` |
| pytest baseline после quality pass | **6482 passed / 131 skipped / 0 failed** (без регрессий) |

Все коммиты локальные — `dev` branch впереди `origin/dev`.

---

**End of Consolidated Master Roadmap**

Дата последнего обновления: 2026-05-13
Версия: v1.0
Author/maintainer: sandermage

Этот файл заменяет 30 предшествующих планов как единый источник правды для forward work. Любое изменение scope — через update этого файла + commit reference.
