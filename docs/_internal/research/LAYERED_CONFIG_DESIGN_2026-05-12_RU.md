# Layered config system + community patch SDK — design (v0.1 draft)

Дата: 2026-05-12
Status: design draft, **awaiting operator approval before any code**.
Связано: `MASTER_REMEDIATION_PLAN_2026-05-12_RU.md` (closed), `POST_REMEDIATION_DEFERRED_2026-05-12_RU.md`.

## Executive summary

Декомпозируем монолитный `model_configs/builtin/<combo>.yaml` на четыре
ортогональных слоя с явным владением полями, profile-based workflow для
безопасного testing новых patches, и framework для community-driven
patch plugins с полной validation цепочкой.

Слои:

| Слой       | Что описывает                                  | Owner        | Меняется когда |
|------------|------------------------------------------------|--------------|----------------|
| `model`    | Identity + capabilities + canonical patches set | Maintainer   | Новый release model |
| `hardware` | Rig identity + sizing knobs                     | Operator     | Новый rig |
| `profile`  | Delta (enable/disable patches, swap kernels)   | Operator/CI  | Testing новых патчей |
| `patch`    | Patch plugin manifest (для community SDK)       | Community/Sander | Новый патч |

Композиция: `final_config = model + hardware + profile_delta`.
Workflow: test в profile → validate → promote в model. Patches могут
прийти из community через явный plugin contract.

## 1. Problem statement

Сейчас один YAML смешивает 5 ортогональных concerns (model, capabilities,
hardware, sizing, patches matrix, deploy, reference metrics). При росте
matrix (M models × N rigs × P profiles) кросс-продукт даёт M·N·P файлов
с 80-90% дублирующим contents. Maintenance nightmare; community contribution
заблокирована т.к. нет clean plug-in surface.

## 2. Decisions (operator-confirmed)

Из обсуждения 2026-05-12:

1. **Merge precedence:** Model wins. Конфликт capability fields →
   `SchemaError` на load. Если rig хочет other capability — он должен
   реферейнсить **другой** model config, а не override'ить.
2. **Profile semantics:** Profile — delta поверх validated model config.
   Workflow: profile тестит → проверено → merge в model. Profiles
   transient, model config — source of truth.
3. **Directory:** `builtin/{model,hardware,logs}/` + `community/...`.
   Community может публиковать hardware безусловно; community-published
   model configs всегда marked `TEST` / `community-test` lifecycle.
4. **Composed naming:** `<model>__<hardware>__<profile>` (двойное `__`
   разделитель). Используется в `logs/<composed>__<ISO-date>.json`.
5. **Community patch SDK:** Каждый патч приходит с self-contained
   manifest (anchors, conflicts, apply, verify), framework валидирует
   совместимость до integration.

## 3. Directory layout (proposed)

```
vllm/sndr_core/model_configs/
├── builtin/
│   ├── model/                         # canonical, maintainer-curated
│   │   ├── qwen3.6-35b-a3b-fp8.yaml
│   │   ├── qwen3.6-27b-int4-autoround.yaml
│   │   ├── qwen3.6-27b-dflash.yaml
│   │   └── ...
│   ├── hardware/                      # canonical rigs
│   │   ├── a5000-2x-24gbvram-16cpu-128gbram.yaml
│   │   ├── a5000-1x-24gbvram-8cpu-64gbram.yaml
│   │   ├── a100-2x-80gbvram.yaml
│   │   ├── rtx5090-1x-32gbvram.yaml
│   │   └── ...
│   └── logs/                          # runtime artifact dropbox
│       └── <model>__<rig>__<profile>__<ISO>.json
└── community/
    ├── hardware/                      # community-published rigs (always OK)
    │   └── <user>__rtx3090-2x-...yaml
    ├── model/                         # community-test models (operator playground)
    │   └── <user>__qwen3-experimental.yaml
    └── profiles/                      # community delta profiles (testing)
        └── <user>__<theme>-2026-05-12.yaml

vllm/sndr_core/model_configs/
└── profiles/                          # canonical delta profiles
    ├── wave9-balanced.yaml
    ├── wave9-dflash.yaml
    ├── wave8-throughput.yaml
    └── ...

vllm/sndr_core/integrations/
└── (existing patches — unchanged)
plugins/                               # community patch plugins (PEP-621 entry points)
└── <user>__<patch_id>/
    ├── pyproject.toml                 # entry-point in [project.entry-points."vllm_genesis_patches"]
    ├── manifest.yaml                  # PatchManifest (anchors, conflicts, etc.)
    ├── patch.py                       # apply/verify/marker
    └── tests/
        ├── test_apply.py
        └── pristine_fixture.py        # captured upstream source
```

**Aliases (optional, operator convenience):**

```
vllm/sndr_core/model_configs/presets/
└── prod-35b.yaml
    # Just three pointers:
    # model:    qwen3.6-35b-a3b-fp8
    # hardware: a5000-2x-24gbvram-16cpu-128gbram
    # profile:  wave9-balanced
```

`sndr launch prod-35b` → resolves alias → composes three layers → existing
launch flow.

## 4. Schema specs

### 4.1 `model/<id>.yaml` — canonical model config

Owns: identity + capabilities + canonical patches matrix.

```yaml
schema_version: 2
kind: model
id: qwen3.6-35b-a3b-fp8

# Identity
title: Qwen 3.6 35B-A3B FP8
maintainer: sandermage
last_validated: '2026-05-09'
license: apache-2.0   # for the model checkpoint itself

# Model identity (canonical)
model_path: /models/Qwen3.6-35B-A3B-FP8
served_model_name: qwen3.6-35b-a3b
quantization: null
dtype: float16
trust_remote_code: true

# Capabilities — these are MODEL-INHERENT, not operator overrides.
# A different capability set = different model file.
capabilities:
  attention_arch: hybrid_gdn_moe       # | dense | hybrid_mamba
  tool_call_parser: qwen3_coder
  reasoning_parser: qwen3
  enable_auto_tool_choice: true
  spec_decode:
    method: mtp                        # mtp | ngram | dflash | eagle | null
    num_speculative_tokens: 3
    model: null                        # null for mtp/ngram; path for dflash/eagle
  kv_cache_dtype: turboquant_k8v4

# Patches matrix — canonical "always-on" set for this model.
# Profile deltas can DISABLE entries here and ADD others (see 4.3).
patches:
  GENESIS_ENABLE_P58_ASYNC_PLACEHOLDER_FIX: '1'
  GENESIS_ENABLE_P60_GDN_NGRAM_FIX: '1'
  GENESIS_ENABLE_P67_TQ_MULTI_QUERY_KERNEL: '1'
  # ... 30+ entries, each one-line commented (as today)

# Compatibility declarations — composer rejects mismatched hardware.
requires:
  min_total_vram_mib: 44000            # 2× 22 GB minimum
  min_gpu_count: 2
  min_cuda_capability: [8, 6]
  attention_arch_blocklist:            # rigs declaring these incompatible
    - sm_120                            # 5090 needs different MoE tuning

# Versioning
versions:
  genesis_pin_min: v11.0.0
  vllm_pin_required: 0.20.2rc1.dev209+g5536fc0c0
  reference_metrics_ref: logs/qwen3.6-35b-a3b-fp8__a5000-2x__wave9__2026-05-09.json
```

### 4.2 `hardware/<id>.yaml` — rig config

Owns: hardware identity + sizing knobs + deploy boilerplate.

```yaml
schema_version: 2
kind: hardware
id: a5000-2x-24gbvram-16cpu-128gbram

title: 2× RTX A5000 (24 GB) — Sander's homelab rig
maintainer: sandermage

# Hardware identity
hardware:
  gpu_match_keys: [rtx a5000]
  n_gpus: 2
  vram_per_gpu_mib: 24576
  total_vram_mib: 49152
  cuda_capability: [8, 6]              # SM 86
  ram_gib: 128
  cpu_cores: 16
  pcie_topology: ok                    # ok | nvlink | unknown

# Sizing knobs — operator tuning for this rig.
# Composer takes these verbatim into final ModelConfig.
sizing:
  max_model_len: 320000
  gpu_memory_utilization: 0.90
  max_num_seqs: 2
  max_num_batched_tokens: 4096
  enable_chunked_prefill: true
  enforce_eager: false
  disable_custom_all_reduce: true

# Deploy boilerplate — defaults the composer fills in.
deploy:
  docker:
    image: vllm/vllm-openai:nightly
    image_digest: 'sha256:9b534fe66daf...'
    container_name: vllm-{model_id}-{rig_id}    # template
    host_port: 8000
    container_port: 8000
    shm_size: 8g
    network: genesis-vllm-patches_default
    mounts:
      - "${models_dir}:/models:ro"
      - "${hf_cache}:/root/.cache/huggingface:ro"

# System env — host knobs that don't change per model.
system_env:
  PYTORCH_CUDA_ALLOC_CONF: expandable_segments:True,max_split_size_mb:256
  NCCL_P2P_DISABLE: '1'
  OMP_NUM_THREADS: '1'
  CUDA_DEVICE_MAX_CONNECTIONS: '8'
```

### 4.3 `profile/<id>.yaml` — delta profile

Owns: patches matrix overrides ONLY. Не трогает identity/capabilities.

```yaml
schema_version: 2
kind: profile
id: wave9-dflash-experimental
parent_model: qwen3.6-27b-int4-autoround   # profile targets a specific model
maintainer: sandermage
status: experimental                       # experimental | validated | promoted
created: '2026-05-12'

# Patches delta — three explicit actions:
patches_delta:
  # 1. Enable patches NOT in the canonical model.patches set.
  enable:
    GENESIS_ENABLE_PN90_PROBABILISTIC_DRAFT: '1'
    GENESIS_ENABLE_PN82_MAMBA_STALE_PREFILL: '1'
  # 2. Disable patches that ARE in canonical.
  disable:
    - GENESIS_ENABLE_P67_TQ_MULTI_QUERY_KERNEL    # testing PN94 instead
    - GENESIS_ENABLE_PN26_SPARSE_V
  # 3. Override values of existing patches (numeric/string knobs).
  override:
    GENESIS_P67_NUM_KV_SPLITS: '32'             # was 48

# Optional: temporary versions override (e.g. trying newer vllm pin)
versions_override:
  vllm_pin_required: 0.20.2rc1.dev220+gxxxxxxxx

# Promotion ledger — when does this profile graduate into model.patches?
promotion:
  validation_required:
    - "tools/genesis_bench_suite.py --quick passes within 2% of canonical baseline"
    - "tool-call regression 4/4 or 10/10"
    - "200-min soak passes (CV < 8%)"
  promote_to: qwen3.6-27b-int4-autoround
  notes: |
    Trying PN90 (probabilistic draft) + PN82 (Mamba stale prefill).
    If TPS +1.5% and CV stable, fold into model.patches.
```

**Promotion workflow:** Когда profile validated, оператор запускает
`sndr profile promote wave9-dflash-experimental`. Tool:

1. Читает profile `enable` / `disable` / `override`.
2. Применяет к `model/qwen3.6-27b-int4-autoround.yaml` `patches:` dict
   (idempotent merge).
3. Bumps `model.last_validated` to current date.
4. Удаляет profile файл (или помечает `status: promoted` для audit trail).
5. Запускает `make audit` чтобы убедиться, что результирующий config
   валиден и `CompatibilityMatrix` чист.

### 4.4 `patch/<id>/manifest.yaml` — community patch SDK

Owns: всё что нужно для plug-in патча извне.

```yaml
schema_version: 2
kind: patch
id: PN999                              # operator-assigned, unique within registry
namespace: community/<user>            # community/sandermage, community/noonghunna, etc.

# Identity
title: PN999 — custom thing X
maintainer: noonghunna
license: apache-2.0
created: '2026-05-15'

# Lifecycle (audit visibility)
lifecycle: community-test              # community-test | community-validated | retired
implementation_status: scaffold        # scaffold | partial | full | research

# Patch contract — what kind of patch this is.
type: runtime_hook                     # runtime_hook | text_patch | composite
family: spec_decode                    # categorisation (see existing _FAMILY_TO_CATEGORY)
env_flag: GENESIS_ENABLE_PN999_FOO     # operator opt-in env var
default_on: false

# Targets — what upstream code does this patch touch.
# For text_patch type:
target_files:
  - path: vllm/v1/spec_decode/eagle/proposer.py
    upstream_sha: a8b3c4d              # captured commit when patch authored
    md5_of_pristine: deadbeef...       # pristine fixture hash (anchor manifest)
    anchors:
      - id: anchor_1
        offset_line: 213
        context_before: |
          def _greedy_sample(self, logits):
        context_after: |
              return torch.argmax(logits, dim=-1)
        what_we_do: "Wrap return with our probabilistic sampler"
# For runtime_hook type:
hook_points:
  - module: vllm.v1.spec_decode.eagle.proposer
    attr: EagleProposer.propose
    operation: monkey_patch            # monkey_patch | post_register

# Conflict declarations — composer rejects co-installation.
conflicts_with:
  - PN77                               # incompatible with adaptive ngram
  - GENESIS_ENABLE_P67_TQ_MULTI_QUERY_KERNEL  # disables our kernel
requires_patches:
  - P58                                # depends on async placeholder fix

# Compatibility scope.
applies_to:
  model_arch:
    - hybrid_gdn_moe                   # only valid on hybrid GDN models
  attention_kernel:
    - turboquant_k8v4
  cuda_capability_min: [8, 6]

# Code entry points (PEP-621 style)
entry_points:
  apply: "patch:apply"                 # returns ("applied"|"skipped"|"failed", reason)
  verify: "patch:verify"               # returns dict[str, bool] live rebind check
  marker: "GENESIS_PN999_MARKER"       # boot log marker

# Test contract — community CI runs these before merge to mainline registry.
tests:
  - pristine_anchor_md5_check
  - apply_returns_tuple
  - apply_idempotent
  - env_off_is_noop
  - conflicts_resolved

# Citations / credits
references:
  - "https://github.com/noonghunna/club-3090/issues/72"
  - "feedback_pn999_design_2026-05-10.md"
```

**Community submission flow:**

1. User clones `genesis-vllm-patches`.
2. `sndr community new-patch --id PN999 --family spec_decode` — scaffolds
   `plugins/community/<user>/PN999/` with manifest + stub `patch.py` +
   pristine_fixture capture script.
3. User implements `apply()` + `verify()` + tests.
4. User runs `sndr community validate PN999` — runs:
   - Manifest schema check.
   - Anchor presence + md5 match against pristine fixture.
   - Conflicts vs current PATCH_REGISTRY.
   - Test suite.
   - Lint + license check.
5. PR opened against `Sandermage/genesis-vllm-patches`.
6. Maintainer review → merge → patch becomes part of community registry
   (separate from canonical builtin registry).
7. After bench validation across ≥2 rigs (cross-rig) → eligible for
   `community-validated` lifecycle promotion.

### 4.5 Composition resolver

`sndr launch --model X --rig Y --profile Z` или `sndr launch <alias>`:

```python
def compose(model_id, rig_id, profile_id=None) -> ModelConfig:
    m = load_model(model_id)               # builtin/model/X.yaml
    r = load_hardware(rig_id)              # builtin/hardware/Y.yaml
    p = load_profile(profile_id) if profile_id else None

    # 1. Hard compatibility — reject before allocating any field.
    if not is_compatible(m, r):
        raise SchemaError(
            f"model {m.id} requires {m.requires.min_total_vram_mib} MiB "
            f"VRAM; rig {r.id} has {r.hardware.total_vram_mib}"
        )
    if p and p.parent_model != m.id:
        raise SchemaError(
            f"profile {p.id} targets model {p.parent_model}, not {m.id}"
        )

    # 2. Build patches dict — canonical, then delta.
    patches = dict(m.patches)
    if p:
        for k in p.patches_delta.disable:
            patches.pop(k, None)
        patches.update(p.patches_delta.enable)
        for k, v in p.patches_delta.override.items():
            patches[k] = v

    # 3. Build final ModelConfig (V1 shape, the one current code expects).
    return ModelConfig(
        key=f"{m.id}__{r.id}__{p.id if p else 'canonical'}",
        # identity → from model
        model_path=m.model_path,
        served_model_name=m.served_model_name,
        # capabilities → from model
        tool_call_parser=m.capabilities.tool_call_parser,
        spec_decode=m.capabilities.spec_decode,
        kv_cache_dtype=m.capabilities.kv_cache_dtype,
        # hardware → from rig
        hardware=r.hardware,
        max_model_len=r.sizing.max_model_len,
        gpu_memory_utilization=r.sizing.gpu_memory_utilization,
        # patches → composed
        genesis_env=patches,
        system_env=r.system_env,
        # versions → profile override wins
        vllm_pin_required=(p.versions_override.vllm_pin_required
                            if p and p.versions_override
                            else m.versions.vllm_pin_required),
        docker=r.deploy.docker._render(model_id=m.id, rig_id=r.id),
        ...
    )
```

V2 schema converts to V1 `ModelConfig` (existing) → entire downstream
flow (CompatibilityMatrix, launch, k8s/compose/quadlet renderers) keeps
working unchanged.

## 5. Bench / log naming

`tools/genesis_bench_suite.py` output filename template:

```
builtin/logs/<model_id>__<rig_id>__<profile_id>__<ISO_DATE>.json
```

Examples:

- `qwen3.6-35b-a3b-fp8__a5000-2x-24gbvram-16cpu-128gbram__wave9-balanced__2026-05-12.json`
- `qwen3.6-27b-int4-autoround__a5000-2x-24gbvram-16cpu-128gbram__wave9-dflash-experimental__2026-05-12.json`

Reverse-lookup: given a log file, the operator immediately knows
exactly which 3-tuple produced it. No more `genesis_bench_quick_*.json`
clutter.

## 6. Migration plan (phased, no big-bang)

### Phase 0 — design approval

This document → operator review → approved.

### Phase 1 — V2 schema + composition resolver (4-5 days)

- `vllm/sndr_core/model_configs/schema_v2.py` — new dataclasses for
  `ModelDef` / `HardwareDef` / `ProfileDef` / `PatchManifest`.
- `vllm/sndr_core/model_configs/compose.py` — `compose(model_id, rig_id,
  profile_id)` → V1 `ModelConfig`.
- `vllm/sndr_core/model_configs/registry_v2.py` — loaders + alias
  resolver.
- 30+ unit tests covering merge precedence, conflict detection, alias
  resolution, edge cases.

### Phase 2 — Migrate one preset as proof of concept (1 day)

Pick `a5000-2x-35b-prod` (most-commented exemplar) → split into:

- `builtin/model/qwen3.6-35b-a3b-fp8.yaml`
- `builtin/hardware/a5000-2x-24gbvram-16cpu-128gbram.yaml`
- `builtin/profiles/wave9-balanced.yaml`
- `builtin/presets/prod-35b.yaml` (alias)

Verify: `sndr launch prod-35b --preflight-only` produces identical V1
ModelConfig as legacy path. Pytest passes.

### Phase 3 — Migrate remaining 10 presets (2-3 days)

One PR per preset. Each migration is independent + reviewable.

### Phase 4 — CLI updates (2 days)

- `sndr model list/show/explain`
- `sndr hardware list/show`
- `sndr profile list/show/promote`
- `sndr launch --model --hardware --profile`
- `sndr community new-patch/validate/submit`

### Phase 5 — Community patch SDK (3-4 days)

- `vllm/sndr_core/community/` package: manifest loader, validator,
  test harness.
- `sndr community validate` end-to-end flow.
- Documentation: `docs/COMMUNITY_PATCHES.md` operator-facing guide.

### Phase 6 — Bench/log integration (1 day)

`tools/genesis_bench_suite.py` writes to canonical composed-name path.
Existing scattered output files → archive job.

### Phase 7 — Tests + docs + CI gate (2 days)

- Schema validation tests (every builtin YAML loads + composes).
- CompatibilityMatrix integration test (composed config flows through).
- New CI gate: `make audit-configs` checks every `(model, hardware,
  profile)` referenced in presets validates.
- Docs: `docs/CONFIG_SYSTEM_V2.md` operator guide.

**Total: ~2 weeks. Phase 1-2 deliver an end-to-end POC; rest is migration
+ polish.**

## 7. Compatibility framework deep-dive

Current `CompatibilityMatrix` (S2.5) уже работает на V1 composed config
→ V2 path не ломает её. Дополнительно ввести **layer-local compat checks:**

### Model-layer compat

```yaml
# model/qwen3.6-35b-a3b-fp8.yaml
requires:
  min_total_vram_mib: 44000
  min_gpu_count: 2
  min_cuda_capability: [8, 6]
```

Composer проверяет `m.requires` против `r.hardware` ДО merge.

### Patch-layer compat (community SDK)

```yaml
# patch/PN999/manifest.yaml
applies_to:
  model_arch: [hybrid_gdn_moe]
  attention_kernel: [turboquant_k8v4]
conflicts_with: [PN77, GENESIS_ENABLE_P67_TQ_MULTI_QUERY_KERNEL]
requires_patches: [P58]
```

Composer проверяет:
- Каждый enabled patch's `applies_to` matches `model.capabilities.attention_arch` / `model.capabilities.kv_cache_dtype`.
- No conflicting patches both enabled.
- All `requires_patches` are also enabled.

### Existing `CompatibilityMatrix` continues working

Текущие COMPAT-001..004 проверяют composed `ModelConfig` → не меняется.
Новые правила можно добавлять в matrix через манифест:

```yaml
# Optional: cross-patch rules в patch manifest
declares_compat_rules:
  - id: COMPAT-005
    severity: forbidden
    title: PN999 incompatible with PN26 sparse-V
    predicate: pn999_enabled AND pn26_enabled
```

## 8. Testing strategy

Каждый слой тестируется изолированно + интеграционно:

**Unit tests:**

- `test_model_def_schema.py` — model YAML loads, requires-block validates.
- `test_hardware_def_schema.py` — hardware YAML loads, sizing knobs in range.
- `test_profile_def_schema.py` — profile YAML, parent_model exists, delta sets disjoint.
- `test_patch_manifest_schema.py` — community patch manifest, anchors well-formed.
- `test_compose_basic.py` — model + rig → V1 ModelConfig has expected fields.
- `test_compose_profile_delta.py` — disable/enable/override все три действуют correctly.
- `test_compose_compat_rejects.py` — incompatible model+rig raises SchemaError.

**Integration tests:**

- `test_compose_to_existing_pipeline.py` — composed ModelConfig flows
  through CompatibilityMatrix / launch / k8s / compose без изменений.
- `test_alias_resolution.py` — `sndr launch prod-35b` resolves alias correctly.

**Acceptance regression:**

- Pre-migration baseline: capture `cfg.to_dict()` for каждого of 11
  existing combined presets.
- Post-migration: composed `(model, hardware, profile)` produces
  byte-identical `cfg.to_dict()`.
- Diff = empty per preset → migration is safe.

## 9. Effort estimate (honest)

| Phase | Work | Days |
|---|---|---|
| 1 | V2 schema + composer + tests | 4-5 |
| 2 | Migrate 1 preset POC | 1 |
| 3 | Migrate remaining 10 | 2-3 |
| 4 | CLI updates | 2 |
| 5 | Community patch SDK | 3-4 |
| 6 | Bench/log integration | 1 |
| 7 | Final tests + docs + CI gate | 2 |
| **Total** | | **~2 weeks (focused)** |

Это **наибольший architectural shift** проекта since v7→v11 migration.
Делать только с focus session — частичная имплементация хуже чем
status quo.

## 10. Open questions (perfect for operator review)

1. **Aliases naming.** `presets/prod-35b.yaml` — короткое имя удобно
   для CLI, но операторы могут забыть какие три файла он включает.
   Альтернатива: длинные explicit названия `sndr launch --model X --hardware Y
   --profile Z` без alias. Что предпочитаешь?

2. **Profile lifecycle automation.** Promote profile в model config —
   automated через `sndr profile promote` (текущая proposal) или manual
   через PR review?

3. **Community patch SDK directory.** `plugins/community/<user>/PN999/`
   внутри repo, или **отдельный repo** (`genesis-vllm-patches-community`)
   с auto-discovery via entry points? Отдельный repo даёт чистое разделение
   ответственности (Sandermage не review every PN999), но requires
   discovery infrastructure.

4. **`builtin/logs/` vs runtime-only directory.** Logs обычно НЕ хранятся
   в repo (operator-specific output). Может быть `~/.sndr/bench-results/`
   вместо `vllm/sndr_core/model_configs/logs/`? Repo может содержать
   только **reference baselines** (validated bench numbers), не runtime
   raw output.

5. **Schema version migration.** V1 ModelConfig (legacy combined) и V2
   (layered) — coexist forever, или V2 strict eventually deprecates V1?
   Если deprecate — после какого release/sprint?

6. **Patch versioning.** Manifest имеет `lifecycle: community-test`.
   Должен ли каждый patch иметь semver (`PN999@1.0.0`) и история changes?
   Это даёт promote workflow (community-test 1.0 → 1.1 fix → 2.0
   community-validated).

7. **Conflict resolution UX.** При `sndr launch X --profile Y` если
   profile конфликтует с другим enabled patch — fail loud (текущее
   предложение) или ask interactive `[y/n] disable conflicting patch P?`

## 11. Next action

**Не приступать к коду** пока не получены ответы на 7 open questions.

После approval:

1. Create empty branches/folders для V2 packages.
2. Phase 1 — V2 schema + composer + 30+ tests.
3. Phase 2 — POC migration `a5000-2x-35b-prod` → verify byte-identical
   composed output vs legacy.
4. Operator review POC → green light для Phase 3.
5. Continue through Phase 7 with regular check-ins.

Status quo (текущий single-YAML approach) остаётся working, V2 живёт
параллельно. Migration phased, не big-bang. Safety net: byte-identical
acceptance regression на каждый preset.

## 12. Why I support this design

1. **DRY.** Изменение patches matrix для модели — один файл, не 4.
2. **Separation of concerns.** Каждый слой имеет clear owner + lifecycle.
3. **Profile workflow safety.** Тестирование новых патчей в isolated
   profile, не рискуя production model config.
4. **Community-ready.** Plugin SDK даёт чистый contract для external
   contributors.
5. **Composable naming.** Bench/log files self-describe by composition
   key — no detective work to identify provenance.
6. **Backward compatible.** V1 ModelConfig остаётся the runtime type;
   V2 живёт как layer над ним. Existing tests + CompatibilityMatrix
   continue working.
7. **Audit-friendly.** Каждый слой validated independently; composed
   result validated по существующим gates.

**Конкретная польза для тебя как оператора:**

- Изменил patch для всех Qwen3.6 моделей → правишь model файл, все rigs
  автоматически подхватывают через композицию.
- Тестируешь новый patch → создаёшь profile, запускаешь bench, видишь
  результаты в `logs/<canonical-name>__<date>.json`, promote'ишь когда
  готов.
- Community user предложил patch PN999 → `sndr community validate PN999`
  гонит full audit pipeline, ты review'ишь report не лезя в код.
