# vllm#42102 backport plan — DFlash + quantized target KV

Дата: 2026-05-12
Author: sandermage
Status: planning (S4.1 audit closure)
Tracking: `docs/upstream/UPSTREAM_WATCHLIST.yaml` entry vllm#42102

## Контекст

Upstream PR [vllm-project/vllm#42102](https://github.com/vllm-project/vllm/pull/42102) предлагает coexistence DFlash drafter с quantized target KV cache. Это напрямую релевантно для Genesis stack, потому что мы уже имеем:

- **PN21/PN23/PN24/PN38/PN40** — DFlash drafter integration на Ampere.
- **TurboQuant k8v4** (`kv_cache_dtype=turboquant_k8v4`) — для target model KV compression.

До текущего момента эти два пути сосуществовали с трудом: DFlash drafter (head_size=256, non-causal) на Ampere не имеет backend'а с fp8/turbo KV → drafter forced на fp16. Если target KV тоже fp16 — fine. Если target = turboquant_k8v4 — нужен path partition.

## Что предлагает upstream

Три механизма:

### 1. Partition DFlash draft KV specs *before* page-size unify

В существующем upstream flow page-size unification происходит на global уровне (все KV groups сводятся к одинаковому page-size для cudagraph batching). Это ломает DFlash, потому что draft KV groups должны иметь свой dtype + page-size.

**Решение upstream:** ввести KV groups partitioning layer ДО global unify — draft KV specs (head_size=256, fp16) живут в отдельной KV group от target (head_size=128, turboquant_k8v4).

### 2. Drafter `cache_dtype="auto"` когда target global KV dtype quantized

При создании AttentionMetadata для drafter, если global config указывает quantized target (`turboquant_k8v4`, `fp8_e5m2`), drafter теперь не наследует это значение — он использует `"auto"`, что в коде транслируется в `bf16` или `fp16` в зависимости от dtype model parameters.

### 3. Per-spec dtype в FlashAttention metadata scheduler

Scheduler теперь хранит per-KV-group dtype в attention metadata, чтобы FA backend знал, что эта конкретная attention call использует другой KV dtype.

## Релевантность для Genesis

| Genesis patch | Что делает сейчас | Что меняется с #42102 |
|---|---|---|
| PN21 | DFlash drafter forward pass на Ampere | Совместимо: head_size=256 + non-causal остаётся, page-size partition снимает текущий workaround |
| PN23 | DFlash KV cache allocator на Ampere | Дублирует upstream partition logic частично — после backport можно retire |
| PN24 | DFlash + cudagraph capture | Сохраняется (cudagraph batch dispatch разный от dtype partition) |
| PN38 | DFlash drafter dtype override (forced fp16) | **Прямо заменяется** механизмом 2 — drafter дефолтно `"auto"` |
| PN40 | DFlash + target turboquant_k8v4 conditional path | **Прямо заменяется** механизмом 1 (KV partition) |

## Backport target

После upstream merge — backport должен жить как **два новых патча**:

### PN94: DFlash independent KV groups

- Mirror of mechanism 1 (partition draft KV specs).
- File: `vllm/sndr_core/integrations/spec_decode/pn94_dflash_independent_kv_groups.py`.
- Anchor: `vllm/v1/spec_decode/dflash_metadata.py` (или новый файл upstream).
- Dependency: PN21 (drafter forward unchanged), PN24 (cudagraph still partitioned).

### PN95b: DFlash drafter dtype override (drafter cache_dtype="auto")

- Mirror of mechanism 2.
- File: `vllm/sndr_core/integrations/spec_decode/pn95b_dflash_drafter_dtype_override.py`.
- Дублирует функционал текущего PN38, но через явный API (`cache_dtype="auto"`) вместо monkey-patch.
- Migration: после merge — retire PN38, переключить configs на PN95b.

## Retire candidates после merge

Когда #42102 merge'ится:

1. **PN38** — retire. PN95b replaces его через cleaner API.
2. **PN40** — retire. PN94 partition механизм заменяет conditional path.

## Test plan (когда backport landed)

1. **Unit tests:** `tests/unit/integrations/spec_decode/test_pn94_dflash_independent_kv_groups.py` — anchor present, KV group partition logic применяется, fallback to legacy без upstream merge.

2. **Integration:** existing `tests/integration/test_patch_regression_bounds.py` запустить с обновлённым 27B Lorbus + TQ k8v4 + DFlash N=5 config. Baseline = текущий PN21..40 stack. Verify:
   - TPS не упал (target: ≥ 88, измерено ~89-90 TPS).
   - Tool-call score не упал (target: 4/4 или 10/10).
   - VRAM usage не вырос > 500 MiB per GPU.

3. **A/B comparison:** Run 200-min soak с PN21+PN94+PN95b vs PN21+PN38+PN40. Welch t-test на TPS / acceptance rate / wall-time CV.

## Когда планировать

- **Trigger:** upstream PR status changes from "open" → "merged" (watch via `make audit-upstream`).
- **ETA:** Upstream review iterations суммируются обычно в 2-4 weeks на complex PRs. Текущая статистика на 2026-05-12 → ожидаем merge в районе 2026-06-01 .. 2026-06-15.
- **Critical path:** только после upstream merge — backport имеет смысл (anchors finalized).

## Cross-references

- Watchlist: `docs/upstream/UPSTREAM_WATCHLIST.yaml` entry `vllm#42102`.
- Compatibility matrix: COMPAT-001 (DFlash on Qwen-next) — refined 2026-05-12, не блокирует Qwen3.6 Lorbus + DFlash.
- DFlash existing wiring: `vllm/sndr_core/integrations/spec_decode/pn{21,23,24,38,40}_*.py`.
- Builtin preset: `vllm/sndr_core/model_configs/builtin/a5000-2x-27b-dflash-true.yaml`.
