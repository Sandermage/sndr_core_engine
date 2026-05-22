# Quality-First Optimization Plan для Genesis vLLM

**Date**: 2026-05-09
**Principle**: Качество > Quantity. Ни одна оптимизация не должна degrade output quality. Идеальный case — **улучшить** quality (better cache hits, better tool detection, lower latency-induced errors).

## Главное правило

🚫 **REJECTED** (даже если дают max compression):
- TQ k4v4 (K precision loss)
- KIVI 2-bit (quality risk)
- Sliding Window Attention (model degrades без training support)
- DuoAttention (small but real quality risk)
- StreamingLLM (random-access workloads degrade)
- H2O / Heavy Hitter (heuristic eviction может drop critical tokens)
- Layer pruning (workload-specific quality variance)
- 1-bit attention (research-grade quality drop)

✅ **ALLOWED** — только lossless OR quality-improving:
- Lossless byte-level compression (zstd/lz4)
- Async parallelism (hide latency, identical compute)
- Smarter caching (more hits = better UX, identical outputs)
- Better request batching (same outputs, higher throughput)
- Output streaming optimizations (perceived latency)
- Tool-call detection improvements (correctness)
- Memory bandwidth optimizations (zero quality impact)
- Operator-side auto-tuning (find best params)

## Категории оптимизаций (quality-first)

### Категория A — Lossless data compression

#### A1. zstd compression в PN95 CPU prefix store

**Что**: блоки KV cache, выгруженные на CPU pinned RAM, сжимать через zstd перед сохранением в `_PN95_PREFIX_STORE`.

**Lossless**: zstd — bit-identical decompression. Restored bytes идентичны original.

**Эффект**:
- CPU prefix store size: 50KB block × 17 layers = 850KB / block
- После zstd compression: ~250-400KB / block (compression ratio 2-3.5×)
- **Эффективная capacity CPU tier увеличена в 2-3×**
- Quality: 100% (lossless)
- Speed: compress ~50 μs/block, decompress ~20 μs/block
  - На demote: +50 μs (приемлемо — только при evict events)
  - На promote: +20 μs (приемлемо — заметно reduces overall latency vs cold prefill which is 100ms+)

**Risk**: minimal. zstd well-established, mature library.

**Effort**: 3-5 дней
- Add zstd как optional dependency
- Wrap `_PN95_PREFIX_STORE` write/read paths
- Validation: 15-case tool quality, byte-identical restore tests
- Env gate: `GENESIS_PN95_CPU_COMPRESS=zstd` (default off → lz4 → zstd choice)

**Validation gates**:
- ✅ Tool 15/15
- ✅ Byte-identical promote test (write→demote→promote→compare bytes)
- ✅ Multi-turn pressure test 6/6
- ✅ TPS regression < 1%

#### A2. lz4 alternative для скорости

**Что**: lz4 быстрее zstd compression (~2× compress speed, ~2× decompress speed) но compression ratio меньше (~1.5-2× vs zstd 2-3×).

**Use case**: hot cache — predominant promote operations (читать чаще чем писать).

**Trade-off**: меньше compression, но меньше latency overhead.

**Configuration**: env `GENESIS_PN95_CPU_COMPRESS=lz4|zstd|none` (operator choice).

#### A3. Page-level deduplication

**Что**: identical KV blocks (одинаковый prefix → identical KV bytes) дедуплицированы по hash.

**Эффект**: для multi-request workloads с shared prefixes (system prompts, few-shot examples) → 30-70% дополнительная экономия CPU tier.

**Lossless**: identical hash → identical bytes by construction.

**Effort**: 1-2 недели (hash-based storage layer).

**Risk**: low — vllm уже tracks block hashes, мы просто reuse storage.

### Категория B — Async parallelism (hide latency, identical compute)

#### B1. Async CUDA stream для PN95 demote/promote

**Что**: текущий PN95 demote/promote runs на default CUDA stream → блокирует attention forward. Перевести на отдельный stream через `_pn95_stream()` (foundation уже готов в Phase 5 Session 2).

**Эффект**:
- Demote: PCIe transfer GPU→CPU ~25 μs/block currently visible
- С async stream: overlapped с attention compute → 0 visible latency
- Promote: same — overlap с upcoming compute

**Quality**: 100% identical — just hides latency.

**Effort**: 1 неделя
- Wrap demote/promote ops в `with torch.cuda.stream(_pn95_stream()):`
- Add `cudaStreamWaitEvent` где нужна sync с default stream
- Test cudagraph compatibility

**Risk**: low-medium — CUDA stream sync needs careful design. Mitigation: extensive cudagraph capture verification.

**Validation**:
- Tool 15/15 (must)
- TPS regression bench (expect +2-5% improvement under demote pressure)
- Stress test multi-turn 6/6 turns

#### B2. Async prefetch для predicted promotes

**Что**: при scheduler tick analyze prefix cache lookups, predict какие blocks будут needed next, prefetch CPU→GPU async.

**Эффект**: hide promote latency complete (prefetch до actual touch).

**Quality**: 100% identical (prefetched data same as on-demand).

**Effort**: 2 недели — needs prediction heuristic + tracking.

**Risk**: low — incorrect prefetch wastes PCIe bandwidth, no quality impact.

#### B3. Pipeline demote с request scheduling

**Что**: demote операции batched и pipelined с request execution. Например, во время prefill request A, async demote блоков от completed request B.

**Эффект**: amortize demote cost across busy periods.

**Quality**: 100% identical.

**Effort**: 3 недели — invasive scheduler integration.

**Risk**: low в isolation, но scheduler integration риск.

### Категория C — Smarter caching (more hits = better experience)

#### C1. Cross-request prefix dedup в PN95 store

**Что**: PN95 prefix store хранит блоки keyed by hash. Если многие requests share prefix (system prompt + few-shot), их blocks identical hash → одна запись serves всех.

**Эффект**:
- Multi-tenant workloads с shared system prompts: 5-10× CPU tier capacity
- Quality: identical (same block contents)

**Effort**: 1 неделя — PN95 store hash-keyed (already!) → just enforce singleton storage.

**Risk**: minimal.

#### C2. Request-aware demote priority

**Что**: вместо "oldest first" LRU, prioritize:
1. **Vision tokens первыми** — visual context less re-used in chat (current TM `vision_demote_first` already supports)
2. **System prompts последними** — они re-used часто
3. **Reasoning tokens (`<think>`) средне** — depend on workload

**Эффект**: better cache hit rate → меньше re-prefill → ниже latency.

**Quality**: identical outputs, но fewer re-computations.

**Effort**: 1 неделя — extend existing TM eviction policies.

**Risk**: minimal.

#### C3. Multi-tier prefix store (CPU → NVMe)

**Что**: добавить NVMe tier как Tier 2 (после CPU pinned RAM):
- Hot blocks: GPU
- Warm blocks: CPU pinned RAM (~100GB max typical)
- Cold blocks: NVMe (TBs available)

**Эффект**: virtually unlimited prefix cache capacity.

**Quality**: identical (just different storage tiers).

**Effort**: 3-4 недели — NVMe tier implementation, async I/O, eviction across tiers.

**Risk**: low (lossless), but complexity in tier management.

#### C4. Adaptive prefix cache TTL

**Что**: prefix cache entries имеют TTL based на access frequency. Никогда-touched entries могут быть evicted earlier.

**Эффект**: better cache effectiveness.

**Quality**: identical.

**Effort**: 1 неделя.

**Risk**: minimal.

### Категория D — Request batching & throughput optimization

#### D1. Request prompt deduplication

**Что**: identical prompts (multi-tenant с одинаковыми system prompts) дедуплицировать на API server level. Один prefill, multiple decode streams.

**Эффект**: massive throughput boost для shared prompts.

**Quality**: identical (same tokens generated).

**Effort**: 2 недели — APIServer-level batching + decode bookkeeping.

**Risk**: medium — careful concurrent decode management.

#### D2. Smart chunked prefill для long contexts

**Что**: chunked prefill уже active. Smarter chunk sizing based на:
- KV pool availability
- Concurrent request load
- Spec-decode targets

**Эффект**: better TTFT для multi-tenant.

**Quality**: identical.

**Effort**: 1 неделя.

**Risk**: minimal.

#### D3. Continuous batching tuning

**Что**: vllm continuous batching parameters (max_num_seqs, max_num_batched_tokens) tuning по auto-tune script (мы уже сделали `pn95_autotune.py` — extend).

**Эффект**: 10-30% throughput на tuned workload.

**Quality**: identical.

**Effort**: 1 неделя — extend autotune script.

**Risk**: minimal.

### Категория E — Output / streaming optimization

#### E1. Better streaming overlap (Genesis P61b extends)

**Что**: existing P61 streaming overlap can be made smarter:
- Faster tool-call detection (less buffer latency)
- Better ASCII vs JSON detection
- Reduced perceived latency

**Эффект**: lower TTFT perception.

**Quality**: identical tokens, faster delivery.

**Effort**: 3-5 дней.

**Risk**: minimal.

#### E2. Sampling efficiency

**Что**: top-k/top-p sampling kernels (vllm already optimized). Verify FlashInfer sampler enabled (we have `VLLM_USE_FLASHINFER_SAMPLER=1`).

**Effort**: verification only.

**Quality**: identical (math equivalent).

#### E3. Stop sequence early termination

**Что**: detect stop sequences earlier через streaming → terminate generation faster.

**Effort**: existing in vllm.

### Категория F — Quality IMPROVEMENT (active enhancement)

#### F1. Better tool-call detection (Genesis P61c+ enhancements)

**Что**: existing P61, P61c, P64, P68, P69 already excellent. Possible additions:
- Better edge cases (tool-call inside reasoning)
- Better recovery from malformed tool calls
- Per-tool confidence scoring

**Quality impact**: **+1-3% tool accuracy** (improves baseline).

**Effort**: 1 неделя per enhancement.

**Risk**: low — incremental quality improvements.

#### F2. PN16 reasoning mode optimization

**Что**: existing PN16 (lazy reasoner) tuned for tool-presence. Possible improvements:
- Per-tool think budget tuning
- Adaptive budget based на complexity
- Better thinking-mode detection

**Quality impact**: better balance speed vs reasoning depth.

**Effort**: 1 неделя.

#### F3. MTP acceptance rate improvements

**Что**: MTP K=3 currently in production. Possible:
- Adaptive K (higher K для simple prompts, lower для complex)
- Better draft model alignment

**Quality impact**: identical (rejection sampling ensures correctness), но higher acceptance rate = TPS up.

**Effort**: 2 недели — careful spec-decode tuning.

**Risk**: low (rejection sampling math is correct).

### Категория G — Memory bandwidth optimization (zero quality impact)

#### G1. KV access pattern optimization

**Что**: vllm PagedAttention already excellent. Possible:
- Better page locality (consecutive blocks per request)
- Prefetch hints (CUDA L2 cache pre-warm)
- Memory access coalescing

**Effort**: research + experimental.

**Quality**: identical.

#### G2. CUDA graph coverage extension

**Что**: more shapes captured в cudagraph → fewer JIT compilation hits during inference.

**Effort**: configuration tuning + bench.

**Quality**: identical (just less compilation).

### Категория H — Operator-side automation

#### H1. Per-rig auto-tune (already started)

**Что**: extend `pn95_autotune.py` к comprehensive sweep:
- TICK_EVERY, THRESHOLD, BATCH, PREFIX_STORE_GIB
- max_num_seqs, max_num_batched_tokens
- gpu_memory_utilization
- KV dtype choices

**Эффект**: optimal config per hardware automatically.

**Effort**: 1-2 недели — sweep harness + reporting.

**Risk**: minimal — operator-driven.

#### H2. Health monitoring + smart restart

**Что**: detect anomalies (TPS drop, OOM warnings, tool quality drop):
- Prometheus-style metrics endpoint
- Smart restart on detected degradation
- Auto-rollback к known-good config

**Эффект**: better uptime, faster issue detection.

**Quality**: identical (monitoring only).

**Effort**: 2-3 недели.

#### H3. Quality regression CI

**Что**: continuous tool quality monitoring (15-case bench daily).
- Alert on regression
- A/B test new patches before promotion

**Эффект**: catch quality issues early.

**Effort**: 1-2 недели.

## Honest realistic projections

### Single A5000 + 27B Qwen3.6 — quality-first stack

| Stack | Workable max_ctx | TPS @ 64K | Quality vs baseline |
|---|---|---:|---|
| **Current (Phase 4.2)** | 59K boot ceiling | 5-8 | 100% (15/15 tool) |
| + zstd CPU compress | extra 2-3× CPU tier | (no impact) | **100%** lossless |
| + Async stream activation | (no max_ctx change) | **+5-10%** | **100%** |
| + Cross-request dedup | extra 2-5× CPU tier | +2% (less prefill) | **100%** |
| + Auto-tune | (config-only) | +5-15% | **100%** |
| + F1 tool detection | (no max_ctx change) | (small) | **+1-3%** |
| + F3 MTP improvements | (no max_ctx change) | +5-10% | **100%** |
| **🎯 Composite quality-first** | **~80-100K realistic** | **+15-30% TPS** | **100%-103%** |

### 2× A5000 + 35B PROD — quality-first stack

| Stack | Max ctx | TPS @ 128K | Quality |
|---|---|---:|---|
| Current PROD | 320K | 4-8 | 100% |
| + Composite | 400-500K | +15-30% | 100%+ |

## Phase 6 — Quality-first Roadmap (sprints)

### Sprint Q1 (1-2 недели) — Foundation

**Goals**: lossless infrastructure + async stream
1. **A1: zstd CPU compression** в PN95 prefix store
   - Effort: 3-5 days
   - Validation: tool 15/15 + byte-identical promote test
2. **B1: Async CUDA stream activation**
   - Effort: 5-7 days
   - Validation: tool 15/15 + cudagraph capture test
3. **C1: Cross-request prefix dedup**
   - Effort: 5-7 days
   - Validation: tool 15/15 + dedup correctness test

**Sprint Q1 deliverable**: 100% quality, +5-15% TPS, 4-8× CPU tier capacity

### Sprint Q2 (2-3 недели) — Smart caching

**Goals**: better cache hit rates через intelligence
1. **C2: Request-aware demote priority** (1 week)
2. **C4: Adaptive prefix cache TTL** (1 week)
3. **D2: Smart chunked prefill** (5 days)

**Sprint Q2 deliverable**: 100% quality, +10-20% TPS на multi-turn

### Sprint Q3 (3-4 недели) — Quality enhancements

**Goals**: actively improve quality + throughput
1. **F1: Tool-call detection improvements** (1 week)
2. **F2: PN16 reasoning optimization** (1 week)
3. **F3: MTP acceptance improvements** (2 weeks)
4. **D3: Continuous batching tuning** (1 week)

**Sprint Q3 deliverable**: **+1-3% quality** (active improvement) + +10-20% TPS

### Sprint Q4 (4-6 недель) — Infrastructure

**Goals**: operator-side automation + monitoring
1. **H1: Per-rig auto-tune** (2 weeks)
2. **H2: Health monitoring** (2 weeks)
3. **H3: Quality regression CI** (1 week)
4. **C3: NVMe tier (Phase 6)** — optional, big work (3-4 weeks)

**Sprint Q4 deliverable**: production hardening, unlimited prefix cache (NVMe), automated tuning

### Sprint Q5+ (long-term) — Research

**Optional**:
- **B2: Async prefetch prediction**
- **D1: Request prompt deduplication**
- **G1: KV access pattern optimization**

## Validation framework для каждого sprint

Каждая item в sprint MUST pass:

1. ✅ **Tool quality 15/15** — zero regression
2. ✅ **Byte-identical correctness tests** (для lossless ops)
3. ✅ **TPS regression bench** — must not regress > 2%
4. ✅ **Multi-turn pressure 6/6 turns**
5. ✅ **Long-context probes 16K → 64K passing**
6. ✅ **Cudagraph capture compatibility**
7. ✅ **A/B vs PN95 OFF baseline**

Если **любой** gate fails → revert к pre-change state, document gap.

## Risk-reward matrix

| Item | Effort | Risk | Quality | TPS gain | Capacity gain |
|---|---|---|---|---|---|
| **A1 zstd CPU** | 3-5d | LOW | 100% | +0-2% | **+200-300% CPU tier** |
| **B1 Async stream** | 5-7d | LOW | 100% | **+5-10%** | none |
| **C1 Dedup** | 5-7d | LOW | 100% | +2% | **+200-500% CPU tier (multi-tenant)** |
| C2 Smart demote | 5-7d | LOW | 100% | +5% | none |
| C3 NVMe tier | 21-28d | MEDIUM | 100% | +0-3% | **+10000% CPU tier** |
| D1 Prompt dedup | 14d | MEDIUM | 100% | **+50-200% multi-tenant** | none |
| D3 Cont. batching tune | 7d | LOW | 100% | +10-30% | none |
| F1 Tool detection | 7d | LOW | **+1-3%** | none | none |
| F2 PN16 reasoning | 7d | LOW | **+1-2%** | +2% | none |
| F3 MTP improvements | 14d | LOW | 100% | **+5-10%** | none |
| H1 Auto-tune | 14d | LOW | 100% | +5-15% | none |

## Composite estimates

После full Sprint Q1-Q3 (Sprint Q4 optional):

| Metric | Before | After | Δ |
|---|---|---|---|
| Tool quality | 15/15 | **15/15+** (F1 improvement) | **+1-3%** |
| TPS @ 16K | baseline | **+15-30%** | UP |
| TTFT | baseline | **-10-25%** | DOWN |
| CPU prefix tier | 4 GiB | **20-100 GiB equivalent** | **5-25×** |
| Multi-turn cache hit | varies | **+30-70%** | UP |
| Long-context (32K+) | varies | **+15-30%** | UP |

## Conclusion

**Quality-first подход = realistic, sustainable wins**:
- ✅ Zero quality regression risk
- ✅ Often +1-3% quality improvement через F-category items
- ✅ +15-30% TPS achievable
- ✅ 5-25× CPU prefix tier capacity expansion (lossless)
- ✅ Better operator experience через H-category

**Trade-off vs aggressive compression plan**:
- Меньшее max_ctx extension (80-100K vs 256K+ realistic)
- Более consistent quality (100% guaranteed vs 94-99%)
- Меньший regression risk (LOW vs MEDIUM-HIGH)
- Production-deployable incrementally

**Honest comparison**:
- Aggressive plan: bigger numbers, real quality risk
- Quality-first plan: meaningful gains, zero regression risk

Для production-critical environment **quality-first plan правильный choice**.

## Recommended starting point

🎯 **Sprint Q1 — start с A1 zstd compression**:
- Lowest risk (lossless by construction)
- High measurable benefit (+200-300% CPU capacity)
- Simple implementation (1 week)
- Foundation for future tier expansion

Затем B1 (async stream) → C1 (dedup) → дальше по приоритетам.
