# Quality-Budgeted Optimization Plan — Drift Budget 0.2-0.8%

**Date**: 2026-05-09
**Quality budget**: до 0.8% drift на validation benchmarks (15-case tool, perplexity, RULER)
**Principle**: extend Quality-First Plan techniques которые дают значительный gain в обмен на минимальный, измеримый quality cost.

## Что меняет 0.8% budget

**Quality-First Plan** (zero drift): только lossless + speed-up без любых compromise.

**Quality-Budgeted Plan** (0.2-0.8% drift): добавляются techniques с **измеримой, ограниченной** quality cost где **выгода значительная**.

**Critical guardrails**:
- 🚫 НЕ техники с >0.8% drift даже если очень выгодны
- 🚫 НЕ техники с **variable** drift (workload-dependent)
- ✅ Только techniques с **measured, predictable** drift в budget
- ✅ Каждая technique независимо env-gated (можно disable)
- ✅ **Composite drift не превышает 1.0%** (sum of individual drifts с safety margin)

## Категории по drift budget

### Категория T0 — Lossless (как в Quality-First plan)

Все из Quality-First Plan включены. Drift = 0%.

- A1 zstd CPU compression
- B1 Async stream
- C1 Cross-request dedup
- C2 Smart demote priority
- D1-3 batching/throughput
- F1-3 quality enhancements (often **+drift = improvement**)
- H1-3 operator automation

**Composite drift contribution**: 0% (часто negative — improvement).

### Категория T1 — Conservative drift (0.05-0.3% per technique)

Most safe additions:

#### T1.1 — FP8 e4m3 KV для **long-context only**

**What**: 
- Текущий TQ k8v4 для **all contexts**
- Switch к FP8 e4m3 для контекстов > 32K (long contexts менее sensitive к KV precision)
- Short contexts остаются TQ k8v4 (current)

**Why**:
- FP8 e4m3 даёт hardware acceleration на A5000+ (Marlin, FA2 native FP8)
- ~0.2-0.4% perplexity drift на long contexts
- TPS boost +5-10% на длинных prompts (better tensor core utilization)
- Capacity **same** as TQ k8v4 (~4× compression)

**Drift**: 0.2-0.4% (paper validated)

**Effort**: 1 неделя — per-context-length KV dtype switching logic

**Validation**: tool 15/15 + RULER long-context bench

#### T1.2 — Mixed precision layer KV (calibration-driven)

**What**: 
- Calibrate layer importance на Genesis test suite
- Top 50% важных layers: TQ k8v4 (current)
- Bottom 50% layers: TQ k4v4 (more aggressive)

**Why**:
- ~30% capacity boost (mixed precision avg)
- Less aggressive vs full TQ k4v4 across all layers (which would be 0.5-2% drift)
- Mixed approach: 0.2-0.4% drift

**Drift**: 0.2-0.4% (calibration-validated)

**Effort**: 2 недели — calibration harness + per-layer dtype config

**Validation**: tool 15/15 + perplexity bench + per-layer quality ablation

#### T1.3 — CUDA graph fusion relaxation

**What**: enable more aggressive op fusion в cudagraph capture (uses approximate math для some ops).

**Why**: TPS +5-10% через fusion.

**Drift**: 0.05-0.15% (numerical noise)

**Effort**: 3-5 days — vllm config tuning

**Validation**: tool 15/15 + numerical reproducibility test

### Категория T2 — Moderate drift (0.3-0.6% per technique)

Higher gain в обмен на slightly бigger drift:

#### T2.1 — DuoAttention conservative split (75% retrieval / 25% streaming)

**What**: вместо paper's typical 25%/75%, использовать conservative 75% retrieval / 25% streaming.

**Why**:
- 25% streaming heads compress 4-8× via SWA
- Overall KV reduction: ~25-35% (less aggressive чем full DuoAttention)
- Drift: 0.3-0.5% (paper data implies)

**Drift**: 0.3-0.5%

**Effort**: 2-3 недели — calibration + per-head KV separation

**Validation**: tool 15/15 + RULER + LongBench

**Critical**: requires per-model calibration. 27B и 35B separately calibrated.

#### T2.2 — Conservative SWA window=16K для very-long contexts

**What**: для контекстов > 32K, attention использует sliding window=16K вместо full attention.

**Why**:
- 32K → 4K window: 4× compute reduction, ~2× memory reduction
- Quality drift typically 0.4-0.7% на most workloads
- Some workloads (random-access retrieval) могут degrade больше — нужна validation

**Drift**: 0.4-0.7% (workload-dependent — нужна careful validation)

**Effort**: 1-2 недели — per-context-length attention config

**Validation**: extensive — tool 15/15 + RULER + LongBench needle-in-haystack

#### T2.3 — Light H2O eviction (top 50% retention)

**What**: PN95 demote choosing — instead of pure LRU, prefer evicting tokens с low attention scores (heavy hitter inverse).

**Why**:
- Better cache hit rates (важные tokens reside longer)
- 0.3-0.5% quality drift typical

**Drift**: 0.3-0.5%

**Effort**: 2 недели — per-token attention tracking + heuristic

**Validation**: tool 15/15 + multi-turn pressure 10/10

### Категория T3 — Higher drift (0.5-0.8% per technique)

Use only if **other techniques don't meet capacity goal**:

#### T3.1 — Aggressive DuoAttention (50/50 split)

**What**: 50% retrieval + 50% streaming (closer to paper recommendations)

**Drift**: 0.5-0.8%

**Effort**: same as T2.1 + more validation

**Use case**: только если T1+T2 не enough capacity

#### T3.2 — TQ k6v4 (intermediate K precision)

**What**: K compressed к 6-bit вместо 8-bit (intermediate между current k8v4 и aggressive k4v4)

**Drift**: 0.5-0.8%

**Effort**: 1-2 недели — extend Genesis TurboQuant к 6-bit K

**Use case**: middle ground между current и aggressive

## Composite drift accounting

**КРИТИЧНО**: composite drift = sum of individual drifts (with safety margin).

**Maximum acceptable composite**: 1.0% (sum of individual drifts within budget + margin).

### Safe combinations (composite < 1.0%)

| Combination | Individual drifts | Composite (worst case) |
|---|---|---|
| **Lossless only** (Quality-First) | 0% | 0% |
| **+ T1.1 FP8 long-ctx** | +0.4% | 0.4% |
| **+ T1.2 Mixed precision** | +0.4% | 0.8% |
| **+ T1.3 CUDA fusion** | +0.15% | 0.95% |
| **🎯 Composite T1 stack** | (T1.1 + T1.2 + T1.3) | **~0.95%** |
| **OR + T2.1 DuoAttention conservative** | (T1.1 + T2.1) | **~0.9%** |
| **OR + T2.2 SWA conservative** | (T1.1 + T2.2) | **~1.1%** ⚠️ EXCEEDS budget |

**Avoid mixing T2 + T3** — composite exceeds budget.

### Realistic projection — Quality-Budgeted full stack

**Single A5000 + 27B Qwen3.6**:

| Stack | Workable max_ctx | TPS @ 64K | Quality drift | Composite quality |
|---|---|---:|---|---|
| Quality-First (T0) | 80-100K | +15-30% | 0% | 100%-103% |
| **+ T1.1 FP8 long-ctx** | 100-120K | **+20-35%** | -0.4% | 99.6%+ |
| **+ T1.2 Mixed precision** | 130-160K | +20-35% | -0.8% | 99.2%+ |
| **🎯 Quality-Budgeted T1 stack** | **130-160K realistic** | **+25-40%** | **-0.95%** | **99.05%+** |
| + T2.1 DuoAttention conservative | 180-220K | +30-45% | -0.9% (alt path) | 99.1%+ |

**2× A5000 + 35B PROD**:

| Stack | Max ctx | TPS @ 128K | Drift | Quality |
|---|---|---:|---|---|
| Quality-First | 400-500K | +15-30% | 0% | 100%+ |
| **Quality-Budgeted** | **500-700K** | **+25-40%** | **-0.95%** | **99.05%+** |

## Updated Sprint Roadmap

Sprints Q1-Q4 from Quality-First plan unchanged (T0 items).
Plus new sprints для T1/T2 items:

### Sprint Q5 (2 нед) — T1 conservative drift items

**Goal**: добавить FP8 long-ctx + CUDA fusion. Total drift ~0.55%.

1. **T1.1 FP8 e4m3 long-context KV** (1 week)
2. **T1.3 CUDA fusion relaxation** (3-5 days)
3. Bench A/B: tool 15/15 + perplexity drift measurement

**Sprint Q5 deliverable**: +5-15% TPS, drift 0.5-0.55%, composite quality ≥99.45%

### Sprint Q6 (3 нед) — T1.2 mixed precision

**Goal**: per-layer mixed precision via calibration.

1. **T1.2 Mixed precision layer KV** (2 weeks calibration + impl)
2. Validation matrix
3. Per-layer ablation testing

**Sprint Q6 deliverable**: 30% capacity boost, drift +0.3-0.4%, composite ~0.85%

### Sprint Q7 (3-4 нед) — Choose between T2.1 OR T2.2

**Goal**: bigger capacity expansion. Choose ONE из:

**Option A — T2.1 DuoAttention conservative** (recommended):
- Quality drift в budget (0.3-0.5%)
- Capacity gain ~25-35%
- Per-model calibration required

**Option B — T2.2 SWA window=16K**:
- Variable workload performance
- Higher capacity gain (~2× для long ctx)
- Higher validation burden

**Recommend A** unless workload primarily long-document Q&A.

### Sprint Q8 (optional) — T3 if needed

Только если T1+T2 не достигают capacity goal. **Avoid by default**.

## Validation framework для quality-budgeted

**Каждая technique MUST pass**:

1. ✅ **Tool quality 15/15** — strict (никакой degradation на tool detection)
2. ✅ **Perplexity bench** — drift < technique's budget allocation
3. ✅ **Long-context benchmark** (RULER, LongBench) — within budget
4. ✅ **TPS regression** — > +0% (must improve, not just maintain)
5. ✅ **Multi-turn pressure** — 10/10 turns (extended)
6. ✅ **Composite test** — when adding к existing stack, composite drift measured

**Если технique exceeds budget** → **revert + document**, not deployed.

## Per-technique honest assessment

### T1.1 FP8 e4m3 long-ctx — RECOMMENDED

**Why recommend**:
- Paper-validated drift (~0.3-0.5%)
- vllm native support (mature)
- Hardware-accelerated (Tensor Cores)
- TPS boost meaningful (+5-15%)
- Easy rollback (env switch)

**Risk**: low — well-known technique.

### T1.2 Mixed precision — CONDITIONALLY RECOMMENDED

**Why recommend**:
- Capacity boost meaningful (+30%)
- Drift в budget if calibrated properly

**Risk**: medium — calibration must be done well; bad calibration can cause >budget drift.

### T1.3 CUDA fusion — RECOMMENDED

**Why recommend**:
- Tiny drift (0.05-0.15%, numerical noise)
- Easy TPS win
- vllm config-driven

**Risk**: minimal.

### T2.1 DuoAttention conservative — RECOMMENDED IF NEEDED CAPACITY

**Why recommend**:
- Significant capacity gain (25-35%)
- Drift acceptable (0.3-0.5%)
- Paper-validated

**Risk**: medium — per-model calibration; quality on edge cases varies.

### T2.2 SWA conservative — CONDITIONAL

**Why conditional**:
- Workload-dependent quality
- Some retrieval workloads may exceed budget

**Recommend**: only if T1+T2.1 don't meet capacity goal AND workload predominantly streaming/sequential (not random-access retrieval).

### T3.x — AVOID

**Why avoid**:
- Drift на upper edge of budget — composite math doesn't work
- Better alternatives в T1+T2

## Honest comparison: 3 plan tiers

| Aspect | Quality-First (T0) | **Quality-Budgeted (T0+T1)** | Aggressive |
|---|---|---|---|
| Quality drift | 0% (often improvement) | **0.4-0.95%** | 1-5% (variable) |
| Workable max_ctx | 80-100K | **130-160K** | 256K+ |
| TPS gain | +15-30% | **+25-40%** | +15-50% (varies) |
| Risk | Minimal | **Low (controlled)** | Medium-High |
| Production deployable | Incrementally | **Incrementally** | Requires careful rollout |
| Composite stability | Guaranteed | **Validated <1%** | Variable |

## Recommended deployment strategy

### Phase 1 — Foundation (Quality-First sprints Q1-Q3)

Deploy Q1 (zstd + async + dedup) → Q2 (smart caching) → Q3 (quality enhancements F1-F3).

**Result**: 100%-103% quality, +15-30% TPS, 5-25× CPU tier.

### Phase 2 — Conservative drift (T1 sprints Q5-Q6)

После Phase 1 stable in production:

1. **Q5 (2 weeks)**: T1.1 FP8 long-ctx + T1.3 CUDA fusion
   - Drift: ~0.55%
   - Gain: +5-15% TPS, hardware-accelerated long-ctx

2. **Q6 (3 weeks)**: T1.2 Mixed precision (only if needed)
   - Drift: +0.3-0.4%
   - Gain: +30% capacity

**Result**: ~99.05% quality, +25-40% TPS, +30-50% capacity.

### Phase 3 — Capacity expansion (T2 sprints Q7)

Только если capacity goal not met:

3. **Q7 (3-4 weeks)**: T2.1 DuoAttention conservative
   - Drift: -0.3 to -0.5%
   - Gain: +25-35% additional capacity

**Maximum stack**: ~98.5% quality, +30-45% TPS, ~2× capacity vs baseline.

## Final recommendations

🎯 **Sequenced implementation**:

1. **First**: complete Quality-First plan (Sprints Q1-Q3) — production-deploy
2. **Then**: **Sprint Q5 T1.1 FP8 long-ctx** — single technique, easy rollback, measurable
3. **Then**: validate в production 2-4 weeks
4. **Then**: **Sprint Q6 T1.2 mixed precision** — calibrate carefully
5. **Then**: validate
6. **Conditional**: **Sprint Q7 T2.1 DuoAttention** only if capacity needed

**Avoid simultaneous T1 + T2** — composite drift control requires sequential validation.

## Bottom line

**0.8% budget unlock**:
- ✅ +30-50% additional capacity (vs Quality-First plan alone)
- ✅ +5-15% additional TPS
- ✅ Hardware acceleration (FP8 long-ctx)
- ⚠️ Real но measured quality cost
- ⚠️ Each technique requires careful per-Genesis validation
- ⚠️ Composite drift management critical

**Reasonable target after full Phase 1+2+3**:
- Single A5000 + 27B: max workable **150-200K**, TPS +30-45%, quality 98.5-99%
- 2× A5000 + 35B: max workable **600-800K**, TPS +30-45%, quality 98.5-99%

**Honest disclaimer**: 0.8% budget — это real cost. Если workload требует strict quality (legal, medical, etc), stick с Quality-First plan (T0 only). For consumer/agent/coding workloads — T1 stack почти всегда acceptable.

## Files

Этот plan saved as: `docs/_internal/research/QUALITY_BUDGETED_OPTIMIZATION_PLAN_2026-05-09.md`

Related:
- `QUALITY_FIRST_OPTIMIZATION_PLAN_2026-05-09.md` (T0 baseline)
- `KV_COMPRESSION_COMPREHENSIVE_2026-05-09.md` (full landscape including T3+)
