# Комплексный анализ KV Cache Compression — все доступные пути

**Date**: 2026-05-09
**Context**: Genesis vLLM patches, Qwen3.6-27B-int4 (hybrid GDN) + 35B-A3B (dense)
**Goal**: Найти максимально безопасные пути compression KV cache без regression качества/скорости

## Текущее состояние (baseline)

Уже активно в Genesis:
- **TurboQuant k8v4** (TQ k8v4) — packed INT8 K + INT4 V → ~4× compression vs fp16 KV
- **MTP K=3** spec decode
- **PN95 v1.0 Phase 4.2** — prefix cache extension к CPU pinned RAM
- **PN95 Phase 5 Anchor #11+#12** — swap-based pool virtualization (1.5× inflation)

**Per-token KV cost**:
- Без TQ (fp16): ~200 KB/token (17 attention layers × 12 KB)
- С TQ k8v4 (current): ~50 KB/token (4× compression)
- Theoretical floor: ~12 KB/token (1-bit attention) — research only

## Категории compression (комплексный обзор)

### Категория 1: Quantization KV (числовая precision reduction)

| Method | Compression | Quality | Speed | Production Ready | Risk Level |
|---|---|---|---|---|---|
| FP16 KV (baseline) | 1× | 100% | reference | ✅ | none |
| **TQ k8v4 (current)** | **4×** | **≈100%** | **+11%** | ✅ | LOW |
| FP8 e5m2 KV | 2× | ≈99% | +5% | ✅ vllm native | LOW |
| FP8 e4m3 KV | 2× | ≈99.5% | +5% | ✅ vllm native | LOW |
| **TQ k4v4** (Genesis exp.) | **8×** | **~95-98%** | **+15%?** | ⏳ experimental | MEDIUM |
| INT8 KV (no packing) | 2× | ≈99% | +3% | ✅ vllm | LOW |
| INT4 KV plain | 4× | ~95% | +0% | ⏳ vllm draft | MEDIUM |
| **KIVI 2-bit** | **8×** | **~94%** | **+10%** | ⏳ paper code | MEDIUM-HIGH |
| 1-bit ternary | 16× | ~85% (POOR) | varies | ❌ research | HIGH |

#### Рекомендации по quantization:

1. **TQ k4v4 expansion** (Genesis-original):
   - Сжать K до 4-bit вместо 8-bit
   - **Потенциал**: 50KB → 25KB/token = 2× больше KV capacity
   - **Risk**: K precision critical для attention scores. K compression более рискованна чем V.
   - **Mitigation**: error correction layers (некоторые transforms preserve dot product)
   - **Effort**: 1-2 weeks engineering + validation

2. **KIVI 2-bit integration**:
   - Известный paper (CMU 2024), open source
   - Per-channel K quant + per-token V quant + retain few "outlier" tokens fp16
   - **Потенциал**: ~5-8× compression vs fp16 (vs наш current 4×)
   - **Risk**: paper claims minimal degradation на benchmarks
   - **Effort**: backport implementation в vllm, integrate с TQ infrastructure
   - **Compatibility check**: hybrid GDN models — KIVI tested mostly на dense transformers

### Категория 2: Sparse Attention (token-level pruning)

| Method | KV Reduction | Quality | Speed | Production Ready |
|---|---|---|---|---|
| **Sliding Window Attention** | 4-16× (для long ctx) | ~95-100% | **+2-5×** | ✅ if model supports |
| **StreamingLLM (attention sinks)** | 8-32× | ~98% (streaming) | +3-10× | ⏳ vllm experimental |
| **H2O (Heavy Hitter Oracle)** | 4-8× | ~97% | +2-5× | ⏳ research |
| **Scissorhands** | 5-10× | ~95% | +3-7× | ⏳ research |
| **DuoAttention** | 5-10× | ~99% | +2-4× | ⏳ paper 2024 |
| Token Merging | 2-4× | ~94% | +1.5× | ❌ early research |

#### Sliding Window Attention (SWA)

**Как работает**: каждый token attend только на recent W tokens (sliding window). Per-layer attention complexity O(N×W) вместо O(N²).

**Для Qwen3.6-27B Lorbus**:
- Window size W = 4096 typical
- 256K context → effective KV = 256K × 17 × W × bytes... Wait, нет — KV size is 4096 × 17 × bytes = 4096 × 12K (TQ) = ~200 MB, FIXED размер независимо от total context length!
- **Compute**: O(N × W) на token = linear в context, не квадратичный
- **Memory**: O(W) total (огромная экономия!)

**Caveat**: модель должна быть trained с SWA для preserving quality. Иначе degradation сильное.

**Qwen3.6 native SWA?** Проверить нужно — если yes, **immediate enable** даст 5-50× compression на длинных контекстах + 2-10× speed boost.

#### StreamingLLM (attention sinks)

**Как работает**: keep first N=4 tokens (attention sinks) + last K=2048 tokens, evict middle.

**Эффект**: 
- 256K context → ~2K KV stored = 128× compression
- Quality preserved для streaming workloads (chat, dictation)
- Documents/code review degradation (random access patterns)

**Production**:
- vllm experimental support
- Best для chatbot agent workloads
- НЕ подходит для full-document Q&A

#### DuoAttention (2024, Han Lab MIT)

**Insight**: heads разделяются на:
- **Retrieval heads** (5-25% от всех heads): нужны full KV для long-context retrieval
- **Streaming heads** (75-95% от всех heads): только sink + recent суффicient

**Эффект**: 
- 17 attention layers Qwen3.6 → ~3 retrieval + 14 streaming
- Streaming heads compress 8-16× via SWA
- Retrieval heads keep full KV
- **Total KV reduction**: ~5-10× на длинных контекстах

**Quality**: paper claims ~99% retention на long-context benchmarks (LongBench, RULER)

**Production**: open source code, requires per-model "retrieval head identification" preprocessing (~1h on calibration data).

**Highly recommended для Genesis** — best risk/reward ratio.

#### H2O (Heavy Hitter Oracle)

**Insight**: 5% tokens получают 95% attention. Identify "heavy hitters" (high attention scores), evict rest.

**Эффект**: 4-8× compression возможен с <2% quality drop.

**Compatibility**: requires attention score tracking — vllm has all necessary hooks.

### Категория 3: Layer-wise compression

| Method | Reduction | Quality | Effort |
|---|---|---|---|
| Per-layer KV pruning | 2-3× | varies | MEDIUM |
| Layer-skip attention | 1.5-2× | ~98% | MEDIUM |
| MoE-style attention | 2-4× | ~99% | HIGH (model surgery) |

#### Per-layer KV importance pruning

**Insight**: некоторые layers contribute больше к final output. Можно lower precision для unimportant layers.

**Approach**:
- Calibration phase: measure layer importance (gradient-based attribution)
- Production: layers ranked low → 2-bit KV; high → 8-bit KV
- Mixed precision per-layer

**Genesis fit**: 17 attention layers в 27B → может pre-rank, top 8 layers full TQ k8v4, bottom 9 layers TQ k4v4. Net ~30% memory saving.

### Категория 4: Cross-request optimization (уже в PN95)

**Уже реализовано**:
- ✅ Phase 4 prefix cache extension (CPU pinned RAM)
- ✅ Phase 4.1 smart LRU + hot ring exclusion
- ✅ Phase 4.2 byte-correct demote/promote (dtype-agnostic)
- ✅ Phase 5 Session 1-3 (boot expansion, side-table, swap virt)

**Возможные улучшения**:
- **Cross-request prefix sharing** (vllm уже)
- **Hash-based deduplication** (current vllm uses block hashes)
- **Multi-tier prefix cache** (CPU → NVMe → S3) — Phase 6 territory
- **Compressed CPU storage** (CPU side compression — zstd/lz4 на cold blocks): 2-5× CPU capacity boost

### Категория 5: Hardware-aware optimizations

| Method | Win | Cost | Notes |
|---|---|---|---|
| **FA2 (FlashAttention 2)** | up to 2× speed | none | already used |
| FA3 (Hopper) | up to 3× speed | requires H100+ | not для A5000 |
| **FP8 attention compute** | 2× speed | quality test | available но needs Hopper для full FP8 GEMM |
| Sage Attention | 2× speed | varies | research |
| Xformers SDPA | up to 1.5× | none | alternative kernel |

### Категория 6: Algorithmic memory tricks

#### Multi-Query Attention (MQA) / Grouped Query Attention (GQA)

**Already в Qwen3.6**: GQA с group size 4 → 4× меньше KV vs MHA (already активно).

#### Multi-Latent Attention (MLA)

**DeepSeek V2/V3 architecture**: low-rank decomposition of K и V.
- KV size: ~1/8 от стандартного multi-head
- **Не applicable к Qwen3.6** (different architecture)

#### KV Sharing

**Insight**: некоторые layers могут разделять KV (cross-layer attention).
- **Effort**: model surgery, retraining
- **Не подходит для production deployment** на existing models

## Комплексная стратегия для Genesis (приоритизированная)

### Tier 1 — Quick wins (low risk, high reward)

#### A. Активация SWA если Qwen3.6 supports

**Action**: check Qwen3.6 architecture для sliding window support.
- Если yes: `--max-model-len 256000 --sliding-window 4096` → instant 50-100× memory reduction для long contexts
- Effort: <1h activation + benchmark
- Risk: minimal если model trained for SWA

#### B. DuoAttention integration

**Action**: integrate Han Lab MIT DuoAttention.
- 1h calibration preprocessing
- 1 day vllm patch для retrieval/streaming head separation
- Expected: 5-10× KV reduction на длинных контекстах
- Quality: ~99% retention (paper validated)

### Tier 2 — Quantization deeper

#### C. TQ k4v4 (Genesis original extension)

**Action**: extend TurboQuant к 4-bit K + 4-bit V.
- Effort: 1-2 weeks engineering + careful validation
- Expected: 2× more KV capacity (8× vs fp16)
- Risk: K compression более sensitive чем V

#### D. KIVI 2-bit backport

**Action**: backport KIVI-2 (CMU paper).
- Effort: 1 week vllm integration
- Expected: 8× compression vs fp16
- Risk: medium (paper-validated но not Genesis-tested)

### Tier 3 — Hybrid approach (комбинация)

**Strategy**: Genesis Composite Stack:
1. SWA для streaming heads (если applicable)
2. TQ k4v4 для retrieval heads
3. PN95 Phase 4 prefix cache extension к CPU
4. CPU storage compression (zstd) для cold blocks

**Combined effect**:
- Single-request 256K context: viable на single A5000
- Multi-turn agent: extreme prefix cache hit rate
- Quality: ~98% retention (composite quality budget)
- TPS: estimated +10-30% vs current baseline

### Tier 4 — Research (long-term)

#### E. Layer-wise KV importance pruning

Per-Genesis calibration → mixed precision per layer.
Effort: 1-2 weeks calibration + integration.
Expected: 30-50% additional KV saving.

#### F. CPU-side compression (zstd/lz4)

PN95 prefix store currently raw bytes.
- zstd compression на cold blocks (compressing 50KB blocks → ~15-25KB compressed)
- 2-3× CPU tier capacity boost
- CPU compute cost per promote: ~50 μs/block (acceptable)

## Совместимость analysis для Genesis

| Method | Hybrid GDN safe? | TQ k8v4 compat? | MTP K=3 compat? | Cudagraph compat? |
|---|---|---|---|---|
| FP8 KV | ✅ | ❌ (replaces TQ) | ✅ | ✅ |
| TQ k4v4 | ✅ | ⏳ extends TQ | ✅ | ✅ (needs warmup) |
| KIVI-2 | ⏳ untested | ❌ replace TQ | ✅ | ✅ |
| **SWA** | ✅ (Mamba uses own state) | ✅ | ✅ | ✅ |
| **DuoAttention** | ✅ | ✅ | ✅ | needs careful capture |
| StreamingLLM | ✅ | ✅ | ✅ | ✅ |
| H2O | ✅ | ✅ | ⏳ may interact | ✅ |
| Layer pruning | ✅ | ✅ | ✅ | ✅ |
| zstd CPU compress | ✅ (PN95 only) | ✅ | ✅ | ✅ |

## Конкретные рекомендации по приоритету

### Приоритет 1 — Сделать СЕЙЧАС (high ROI, low risk)

1. **Проверить SWA support в Qwen3.6** (1h research + test)
   - Если supports — immediate enable, gigantic KV reduction
2. **CPU-side compression в PN95 prefix store** (1 week)
   - zstd на cold blocks
   - 2-3× CPU tier capacity
   - Низкий risk, чистый PN95 work
3. **Smart layer-wise prefix demote priority** (3 days)
   - Different layers cached с different priority
   - Vision/early layers demote first

### Приоритет 2 — Spike (validate then commit)

1. **DuoAttention proof-of-concept** (1 week spike)
   - Calibrate retrieval heads on Qwen3.6
   - Apply to single layer first → measure quality
   - If validates → full integration (2 weeks)
2. **TQ k4v4 spike** (1 week)
   - Extend existing TQ infrastructure
   - Quality bench на Genesis test suite
   - If validates → production rollout (1 week)

### Приоритет 3 — Research (long-term)

1. KIVI integration
2. Layer-wise mixed precision
3. NVMe tier (Phase 6)
4. H2O / Heavy Hitter integration

## Risk mitigation framework

Для каждой compression technique должны быть:

1. **Canary deployment**: env-gated activation, default OFF
2. **A/B regression bench**: 15-case tool quality + TPS measurement
3. **Quality benchmarks**: perplexity на calibration set
4. **Stress tests**: long-context probes (16K, 64K, 128K, 256K)
5. **Rollback plan**: env disable → no behavior change

## Realistic projections

### Single A5000 + 27B Qwen3.6, после full stack

| Compression stack | Workable max_ctx | TPS @ 64K | Quality vs baseline |
|---|---|---|---|
| Current (TQ k8v4 + Phase 4) | 59K boot ceiling | 5-8 | 100% |
| + Anchor #9 boot expansion | 80K boot pass | (single req limited) | 100% |
| + SWA если supports | 256K+ | 8-15 | 95-100% |
| + DuoAttention | 256K+ | 6-12 | 99% |
| + TQ k4v4 | 120K | 5-7 | 95-98% |
| + KIVI-2 | 100K+ | 5-7 | 94-97% |
| + zstd CPU compress | extra 2-3× CPU | (no impact) | 100% |
| **Composite (SWA + TQ k4v4 + zstd)** | **256K+** | **6-10** | **94-99%** |

### 2× A5000 + 35B Qwen3.6, после full stack

| Stack | Max ctx | TPS @ 128K |
|---|---|---|
| Current PROD | 320K | 4-8 |
| + Composite | 1M+ | 3-7 |

## Implementation roadmap (комплексный)

### Sprint 1 (1-2 weeks): SWA verification + zstd
- Verify Qwen3.6 SWA support
- If yes: immediate enable + bench
- Implement zstd CPU compression в PN95 prefix store
- Validation matrix

### Sprint 2 (2-3 weeks): TQ k4v4 spike
- Extend TurboQuant к 4-bit K
- Quality validation на Genesis test suite
- A/B bench tool quality + TPS
- If validates → production rollout

### Sprint 3 (3-4 weeks): DuoAttention integration
- Calibrate retrieval heads на Qwen3.6 (27B + 35B)
- vllm integration (per-head KV separation)
- Per-tier prefix cache priority
- Validation matrix

### Sprint 4 (4-6 weeks): Composite optimization
- Combine SWA + DuoAttention + TQ k4v4
- Quality budget management
- Performance regression bench
- Production rollout

### Sprint 5+ (long-term): Research items
- KIVI-2 backport
- H2O / Heavy Hitter
- NVMe tier
- Layer-wise importance pruning

## Conclusion

**Краткий ответ**: ДА, можно много compress без потери качества/скорости через комплексный подход.

**Самые перспективные** в порядке приоритета:
1. **SWA если Qwen3.6 supports** — 5-50× memory reduction, возможно instant activation
2. **DuoAttention** — 5-10× с retention 99%
3. **TQ k4v4** (Genesis extension) — 2× over current 4×
4. **CPU-side zstd compression** — 2-3× extra PN95 capacity
5. **Layer-wise pruning** — 30-50% extra savings

**Composite результат**: realistic **256K на single A5000 + 27B** через combination, без значительной regression качества.

Все techniques requires careful per-Genesis validation (15-case tool, perplexity, stress probes) перед production deployment. Каждая опция env-gated для safe rollback.

**Honest disclaimer**: ничто не "free lunch". Trade-off matrix важна. Лучшие methods (SWA, DuoAttention) require model architecture support — нужна verification что Qwen3.6 trained compatible.
