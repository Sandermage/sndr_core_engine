# Расширенный поиск quality-preserving optimization options

**Date**: 2026-05-10
**Goal**: найти ВСЕ technologies/approaches для оптимизации памяти и кеша, которые **гарантированно не ухудшают** качество (или улучшают). Wider research net beyond previous plans.

## Принцип отбора

✅ **INCLUDE**: techniques where quality impact is mathematically/architecturally **zero or positive**
🚫 **EXCLUDE**: anything с potential drift (даже малый)

## 9 новых категорий optimization (не covered в предыдущих планах)

### Категория I — System-level / cross-component optimizations

#### I1. RadixAttention (SGLang-inspired prefix tree)

**What**: replace vllm's hash-based prefix cache с radix tree structure (prefix tree). Radix tree = compressed trie where common prefixes share storage.

**Why quality-preserving**: 100% — это just better data structure для same blocks. Same KV bytes returned, identical attention computations.

**Эффект**:
- **2-5× higher cache hit rate** для multi-tenant workloads с branching prompts (system + few-shot variations)
- TTFT down dramatically для cache hits
- Memory same as current (radix tree overhead ~5% in metadata)

**Use cases**:
- Multi-tenant API (many users with similar system prompts)
- Few-shot learning workflows
- Code generation (repeated boilerplate)
- Agent workflows (repeated tool definitions)

**Effort**: 3-4 weeks — significant code (radix tree implementation, search algorithm, integration с PN95).

**Risk**: low for quality (mathematically equivalent), medium for implementation complexity.

**Research**: SGLang paper (Stanford 2024), open source code available для adaptation.

#### I2. TP-aware KV deduplication

**What**: при TP=2 (2× A5000 PROD), each rank holds **independent** copy of attention head metadata. Some heads могут быть deduplicated across ranks.

**Why**: GQA (Grouped Query Attention) — Qwen3.6 has KV head share across query groups. TP-2 currently splits всё. Smart partition might allow sharing.

**Эффект**: 5-15% memory reduction на TP=2 setups (35B PROD, 27B 2-card).

**Quality**: 100% identical — это о memory layout, не о computation.

**Effort**: 2-3 weeks — careful TP partition logic.

**Risk**: low for quality, medium for implementation (TP semantics tricky).

#### I3. NUMA-aware CPU pinned RAM allocation

**What**: PN95 prefix store currently uses arbitrary host memory. NUMA-aware allocation places pinned RAM на same NUMA node как GPU.

**Why**: cross-NUMA PCIe transfers slower (~20-30%). Same-NUMA = full PCIe bandwidth.

**Эффект**: 20-30% faster promote/demote latency.

**Quality**: 100% identical (just memory placement).

**Effort**: 1 week — `numactl` integration + `MADV_HUGEPAGE` hints.

**Risk**: minimal.

#### I4. Memory-mapped cold prefix store (Tier 3)

**What**: дополнительный tier — mmap'd file for COLD блоки (older than CPU tier capacity). OS page cache handles automatically.

**Why**:
- CPU tier: ~10-50 GiB typical (limited by host RAM)
- mmap tier: 1-10 TB (limited by disk)
- OS handles caching transparently — frequently-used blocks stay в RAM via OS page cache

**Эффект**: virtually unlimited prefix cache для long-running services.

**Quality**: 100% identical (mmap'd bytes same as memory).

**Effort**: 2-3 weeks — tier 3 integration в TM, async I/O для disk-backed reads.

**Risk**: low (lossless), but disk failures need handling.

#### I5. Cross-instance prefix sharing (CUDA IPC)

**What**: multi-instance vllm deployment (e.g., 27B на :8000 + 35B на :8001). Share prefix cache CPU storage между instances via CUDA IPC mechanisms.

**Why**: many users hit common prompts regardless which model serves. Shared CPU cache = better hit rate cross-model.

**Эффект**: 30-50% better cache hit rate в multi-model deployments.

**Quality**: 100% identical (same bytes regardless of instance).

**Effort**: 4-6 weeks — IPC infrastructure, sync primitives, fault handling.

**Risk**: medium (IPC complexity), low for quality.

### Категория J — Pre-computation / pre-processing

#### J1. Tool definition pre-tokenization caching

**What**: tool schemas в API requests часто identical. Pre-tokenize tool definitions, cache token IDs. Skip re-tokenization on each request.

**Эффект**:
- TTFT improvement: 5-20ms savings per request (tokenization is non-trivial)
- Tool-heavy workloads: significant cumulative

**Quality**: 100% identical (deterministic tokenization).

**Effort**: 1 week — tokenizer cache layer at API server.

**Risk**: minimal.

#### J2. System prompt embeddings cache

**What**: known system prompts (chatbot defaults, coding assistant prompts) — pre-tokenize + pre-prefill, cache resulting KV blocks aggressively.

**Эффект**: zero-prefill latency for new sessions с known system prompt.

**Quality**: 100% identical.

**Effort**: 2 weeks — prompt registry + pre-warm cycle.

**Risk**: minimal.

#### J3. Speculative prefill (для predicted next requests)

**What**: based на access patterns, predict likely next requests, prefill speculatively in idle GPU time.

**Эффект**: zero-TTFT для predicted patterns.

**Quality**: 100% identical (speculative work discarded if mispredicted).

**Effort**: 3-4 weeks — prediction model + speculative execution path.

**Risk**: low quality, medium complexity.

#### J4. Pre-computed tool routing

**What**: для simple tool calls, route directly to tool execution без full LLM prefill (for known patterns).

**Эффект**: 100ms+ savings on simple tool calls.

**Quality**: depends — if routing классификатор correct, identical output. If wrong, falls back к LLM. Net effect: same quality, faster avg.

**Effort**: 2-3 weeks — classifier + routing layer.

**Risk**: low (fallback к LLM safe).

### Категория K — Smarter cudagraph / kernel optimization

#### K1. Extended cudagraph capture coverage

**What**: vllm's cudagraph captures specific shape sets. Extended to cover MORE shapes → fewer JIT compilations during serving.

**Эффект**: -20-50% latency variance, +5-10% TPS на mixed workloads.

**Quality**: 100% identical.

**Effort**: 1-2 weeks — capture config tuning + memory budget management.

**Risk**: minimal (more shapes = more memory but predictable).

#### K2. Per-shape kernel selection registry

**What**: maintain registry of best kernel choice per (shape, dtype, model). Auto-tune per Genesis hardware.

**Эффект**: 5-15% TPS на specific shapes.

**Quality**: 100% identical (kernel correctness verified).

**Effort**: 2-3 weeks — registry infrastructure + auto-tune harness.

**Risk**: minimal.

#### K3. Triton autotuning per hardware (already partial via P67 family)

**What**: extend existing Genesis P67 kernel autotuning к more kernels (mamba, dequant, dispatch).

**Эффект**: 2-10% TPS per kernel tuned.

**Quality**: 100% identical (autotuned kernels deterministic).

**Effort**: 1-2 weeks per kernel (incremental).

**Risk**: minimal.

#### K4. Better warmup procedures

**What**: vllm warmup currently captures specific shapes. Extend to cover real workload patterns (sniff from production traces).

**Эффект**: zero JIT latency spikes during serving.

**Quality**: 100% identical.

**Effort**: 1 week.

**Risk**: minimal.

### Категория L — Smarter scheduling

#### L1. Eviction-aware scheduler

**What**: scheduler doesn't admit request if it would cause CRITICAL eviction (heavy hitter prefixes lost). Currently scheduler admits и let eviction happen.

**Эффект**: better cache stability, fewer wasted evictions.

**Quality**: 100% identical (just scheduling order, не computation).

**Effort**: 2 weeks — extend scheduler с eviction cost estimation.

**Risk**: low.

#### L2. Cache-aware request routing (multi-instance)

**What**: API gateway routes requests к instance с best cache match (via prefix hash).

**Эффект**: 30-70% cache hit improvement в multi-instance setups.

**Quality**: 100% identical.

**Effort**: 2-3 weeks — gateway logic + cache state sync.

**Risk**: low.

#### L3. Length-based bucket batching

**What**: similar-length requests batched together → less padding waste, better GPU utilization.

**Эффект**: 5-15% TPS на mixed-length workloads.

**Quality**: 100% identical.

**Effort**: 1-2 weeks.

**Risk**: minimal.

#### L4. Pipeline async prefill (overlap with previous decode)

**What**: while request A is decoding, async prefill of request B's prefix (pipelining).

**Эффект**: hides prefill latency для multi-request scenarios.

**Quality**: 100% identical.

**Effort**: 2-3 weeks — careful pipeline state management.

**Risk**: medium (concurrency complexity).

### Категория M — Memory management внутри vllm

#### M1. GPU memory defragmentation

**What**: long uptime causes GPU memory fragmentation. Periodic defrag (compact KV pool, return memory to allocator).

**Эффект**: prevents slow degradation over weeks of uptime.

**Quality**: 100% identical (just memory layout).

**Effort**: 2-3 weeks — careful coordination с in-flight requests.

**Risk**: medium (fragmentation safe but moves are tricky).

#### M2. Adaptive KV block size

**What**: vllm currently uses fixed block_size (16, 32, 64 tokens). Adaptive based на context length:
- Short context: smaller blocks (less waste)
- Long context: larger blocks (less metadata overhead)

**Эффект**: 5-10% memory savings on average.

**Quality**: 100% identical.

**Effort**: 3-4 weeks — invasive (PagedAttention assumes fixed block_size).

**Risk**: high (block_size assumed во многих vllm internals).

#### M3. Better memory accounting (less over-reservation)

**What**: vllm conservatively reserves workspace memory. More precise accounting → 200-500 MiB more for KV pool.

**Эффект**: 5-10% more KV capacity.

**Quality**: 100% identical (just budget tightening).

**Effort**: 1-2 weeks — careful workspace measurement.

**Risk**: medium (under-reservation = OOM).

#### M4. Page frame zero-copy

**What**: avoid intermediate buffers in cudaMemcpy operations. Direct register-to-register transfers где possible.

**Эффект**: 20-40% faster intra-GPU operations.

**Quality**: 100% identical.

**Effort**: 2-3 weeks — kernel-level changes.

**Risk**: medium (CUDA semantics tricky).

#### M5. Streaming KV writes (fused decode + cache update)

**What**: fuse decode result writing с KV cache update в single kernel call.

**Эффект**: 5-10% TPS на decode steps.

**Quality**: 100% identical.

**Effort**: 2-3 weeks — kernel surgery.

**Risk**: medium.

### Категория N — Operator-level system optimizations

#### N1. Multi-instance load balancer с cache-aware routing

**What**: deploy 2-3 vllm instances. Load balancer (Caddy/Envoy) routes по cache state (extends L2).

**Эффект**: linear scale + cache locality.

**Quality**: 100% identical.

**Effort**: 1-2 weeks — operator configuration.

**Risk**: minimal.

#### N2. Prompt classifier + specialized routing

**What**: classify incoming requests (simple Q&A vs complex reasoning vs tool call). Route к specialized config (e.g., simple = lower MTP K, complex = higher).

**Эффект**: better TPS на simple requests, no quality loss.

**Quality**: 100% identical (or improved via better tuning).

**Effort**: 2-3 weeks — classifier + routing.

**Risk**: low.

#### N3. RAG pre-retrieval pipelines

**What**: pre-fetch context (RAG) before LLM request. Skip irrelevant context.

**Эффект**: shorter actual prompt → less KV needed → smaller context.

**Quality**: depends на RAG quality, но separate optimization layer.

**Effort**: 4-6 weeks — RAG infrastructure (большая work).

**Risk**: orthogonal к vllm optimization.

#### N4. Smart restart policies

**What**: detect когда optimal к restart (memory fragmentation, slow degradation) → graceful restart с зеro downtime (rolling restart of multi-instance).

**Эффект**: maintain peak performance over weeks.

**Quality**: 100% identical (just operational maintenance).

**Effort**: 2-3 weeks.

**Risk**: low.

### Категория O — Beyond-vllm system architecture

#### O1. Continuous batching v2 (better algorithms)

**What**: vllm v1 уже continuous batching. Research shows newer algorithms (Sarathi-Serve etc) могут give +5-10%.

**Effort**: backport research code (3-4 weeks).

**Risk**: medium (newer code less tested).

#### O2. Pipeline parallelism (PP) для очень больших моделей

**What**: PP=2 + TP=2 для 70B+ models (если будет в Genesis future).

**N/A** для текущих 27B/35B configs.

#### O3. Disaggregated serving (Splitwise architecture)

**What**: separate prefill instances and decode instances. Optimize each для their workload.

**Эффект**: 20-50% throughput на mixed workloads (research-validated).

**Quality**: 100% identical.

**Effort**: 6-8 weeks (large architecture change).

**Risk**: medium (complex coordination).

## Совместимость + ROI matrix

| Item | Effort | ROI | Quality | Risk |
|---|---|---|---|---|
| **I1 RadixAttention** | 3-4 нед | **HIGH** (2-5× cache hit) | 100% | LOW |
| **I3 NUMA-aware allocation** | 1 нед | **HIGH** (20-30% PCIe) | 100% | LOW |
| **I4 mmap tier 3** | 2-3 нед | **VERY HIGH** (TBs cache) | 100% | LOW |
| I5 Cross-instance IPC | 4-6 нед | HIGH (30-50% multi-tenant) | 100% | MED |
| **J1 Tool tokenization cache** | 1 нед | MED (5-20ms TTFT) | 100% | MIN |
| J2 System prompt cache | 2 нед | HIGH | 100% | MIN |
| J3 Speculative prefill | 3-4 нед | MED (predictive) | 100% | LOW |
| **K1 Extended cudagraph** | 1-2 нед | MED (5-10% TPS) | 100% | MIN |
| K2 Kernel registry | 2-3 нед | MED (5-15%) | 100% | MIN |
| K3 Triton extended autotune | 1-2 нед | MED (2-10%) | 100% | MIN |
| **L1 Eviction-aware scheduler** | 2 нед | HIGH (cache stability) | 100% | LOW |
| **L2 Cache-aware routing** | 2-3 нед | HIGH (30-70% multi-inst) | 100% | LOW |
| L3 Length bucketing | 1-2 нед | MED (5-15%) | 100% | MIN |
| L4 Pipeline prefill | 2-3 нед | MED (multi-req) | 100% | MED |
| M1 GPU defrag | 2-3 нед | MED (long uptime) | 100% | MED |
| M3 Better accounting | 1-2 нед | MED (5-10% capacity) | 100% | MED |
| M4 Zero-copy | 2-3 нед | MED (20-40% intra-GPU) | 100% | MED |
| M5 Fused decode+cache | 2-3 нед | MED (5-10%) | 100% | MED |
| N1 Multi-instance LB | 1-2 нед | HIGH (linear scale) | 100% | MIN |
| N2 Prompt classifier | 2-3 нед | MED | 100%+ | LOW |
| N4 Smart restart | 2-3 нед | LOW (maintenance) | 100% | LOW |
| O3 Disaggregated serving | 6-8 нед | HIGH (20-50%) | 100% | MED |

## TOP-7 рекомендации (best ROI, minimal risk)

🥇 **I3: NUMA-aware allocation** (1 неделя, 20-30% PCIe boost)
- Quick win, no quality risk
- Direct boost to PN95 demote/promote speed
- Helps existing Phase 4.2 production stack

🥈 **K1: Extended cudagraph capture** (1-2 недели, 5-10% TPS)
- Simple config tuning + memory budget
- Eliminates JIT spikes during serving
- Predictable benefit

🥉 **J1: Tool definition tokenization cache** (1 неделя, 5-20ms TTFT)
- Trivial implementation
- Tool-heavy workloads big win
- Zero quality risk

🥉 **I4: mmap-backed Tier 3 cold storage** (2-3 недели, TBs cache)
- Massive capacity expansion
- Lossless (just OS page cache)
- Pairs perfectly с zstd compression (Quality-First A1)

🥉 **L1: Eviction-aware scheduler** (2 недели, cache stability)
- Better cache hit rates
- No computational change
- Predictable throughput

🥉 **L2: Cache-aware multi-instance routing** (2-3 недели)
- Linear scale benefit
- Standard ops/dev practice
- Easy rollback

🥉 **I1: RadixAttention prefix tree** (3-4 недели, 2-5× cache hit)
- BIGGEST cache hit improvement
- Lossless data structure change
- Significant implementation effort но очень высокий benefit

## Композитный stack — what's possible БЕЗ quality loss

### Single A5000 + 27B Qwen3.6 (full quality-preserving stack)

| Layer | Capacity | TPS | Quality |
|---|---|---|---|
| Current Phase 4.2 | 4 GiB CPU prefix | baseline | 100% |
| **+ I3 NUMA** | (same) | **+20-30% promote latency** | 100% |
| **+ K1 cudagraph extended** | (same) | **+5-10%** | 100% |
| **+ I4 mmap Tier 3** | **TBs effective cache** | (no impact) | 100% |
| **+ I1 RadixAttention** | (same bytes) | **+2-5× cache hit** | 100% |
| **+ L1 Eviction-aware sched** | (same) | (cache stability) | 100% |
| **+ J1 Tool tokenization cache** | (no change) | **+5-20ms TTFT** | 100% |
| **🎯 Full stack** | **TBs + Radix tree** | **+20-40% TPS, +cache hit 2-5×** | **100%** |

### 2× A5000 + 35B PROD (full quality-preserving stack)

| Layer | Capacity | TPS | Quality |
|---|---|---|---|
| Current PROD | 4 GiB CPU prefix | baseline | 100% |
| + Composite quality-preserving | TBs | +20-40% | 100% |
| **+ N1 Multi-instance LB** (если deploy 2 cards): | **2× linear scale** | **2× linear** | **100%** |

## Sprint Roadmap (расширенный, quality-preserving only)

### Sprint Q5N (1 неделя) — Quick wins

1. **I3 NUMA allocation** (3-5 days)
2. **J1 Tool tokenization cache** (2-3 days)
3. Validation matrix

### Sprint Q6N (2 недели) — Cudagraph + scheduler

1. **K1 Extended cudagraph capture** (1 week)
2. **L1 Eviction-aware scheduler** (1 week)
3. Bench A/B

### Sprint Q7N (3 недели) — Tier 3 + RadixAttention spike

1. **I4 mmap Tier 3 cold storage** (2 weeks)
2. **I1 RadixAttention proof-of-concept** (1 week spike)
3. If RadixAttention validates → commit к full impl in Q8N

### Sprint Q8N (4 недели) — RadixAttention full impl

1. **I1 RadixAttention production integration**
2. Validation matrix (extensive — это big change)
3. A/B vs current LRU on production-like workloads

### Sprint Q9N (3-4 недели) — Multi-instance + classifier

1. **L2 Cache-aware multi-instance routing** (2 weeks)
2. **N1 Multi-instance LB deployment** (1 week)
3. **N2 Prompt classifier** (optional, 2 weeks)

### Sprint Q10N+ (long-term) — Advanced optimizations

- M1 GPU defrag
- M3 Better accounting
- M4-5 Kernel optimizations
- O3 Disaggregated serving

## Validation framework (strict для quality-preserving)

Каждая technique MUST PASS:

1. ✅ **Tool quality 15/15** — strict (для quality-preserving = always pass)
2. ✅ **Byte-identical correctness tests** где applicable (lossless ops)
3. ✅ **TPS regression bench** > +0% (must improve, not just maintain)
4. ✅ **Multi-turn pressure 10/10 turns**
5. ✅ **Long-context probes 16K → 64K passing**
6. ✅ **Cudagraph capture compatibility**
7. ✅ **Cache hit rate measurement** (для caching changes)
8. ✅ **24-hour stability soak test** (для memory management changes)

## Composite estimates — Quality-Preserving full stack

После Quality-First Q1-Q3 + Quality-Preserving Q5N-Q9N:

| Metric | Before | After | Δ |
|---|---|---|---|
| Tool quality | 15/15 | **15/15+** | **+0-3%** (improvement) |
| TPS @ 16K | baseline | **+30-50%** | UP |
| TTFT (cold) | baseline | **-30-50%** | DOWN (cache hits) |
| TTFT (cache hit) | baseline | **near-zero** | massive improvement |
| Cache hit rate | varies | **+200-500%** (multi-tenant) | UP |
| Effective cache capacity | 4 GiB | **TBs (mmap)** | **1000×+** |
| Multi-turn tail latency | varies | **-50-70%** | DOWN |
| Long-context (32K+) TPS | varies | **+25-45%** | UP |
| Multi-instance scale (если 2 cards) | 1× | **2× linear** | UP |

## Honest disclaimer + risks

**Lossless != effortless**:
- Implementations нужны thorough testing
- Some techniques (M1 defrag, M4 zero-copy) имеют moderate complexity risk
- Multi-instance scenarios нужны production ops infrastructure

**Time investment**:
- Quick wins (I3, J1): few days each
- Major items (I1 RadixAttention, I4 mmap, O3 disaggregated): 3-8 weeks each
- Total full stack: ~6-12 months focused work

**Hardware requirements**:
- I3 NUMA: requires multi-socket server (homelab может быть single-socket)
- I4 mmap: requires fast NVMe (SSD)
- I5 IPC: multi-instance deployment
- N1 LB: multi-card or multi-server

## Final ranking — best ROI per effort

### TOP-3 для immediate implementation

1. **🥇 J1 Tool tokenization cache** — 1 week, simple, tool-heavy workloads big win
2. **🥇 I3 NUMA-aware allocation** — 1 week, 20-30% PCIe improvement
3. **🥇 K1 Extended cudagraph capture** — 1-2 weeks, 5-10% TPS, fewer JIT spikes

Total: 3-4 weeks effort = significant cumulative improvement.

### TOP-3 для major projects (2-4 months total)

1. **🌟 I1 RadixAttention** — 3-4 weeks, 2-5× cache hit rate (HUGE win)
2. **🌟 I4 mmap Tier 3** — 2-3 weeks, TBs cache capacity
3. **🌟 L2 + N1 Cache-aware multi-instance** — 3-4 weeks, linear scale

## Composite vision — все три плана объединённые

| Plan tier | Quality | Capacity | TPS | Risk |
|---|---|---|---|---|
| Quality-First (T0) | 100%-103% | +5-25× CPU tier | +15-30% | NONE |
| **+ Quality-Preserving (this plan)** | **100%-103%** | **+1000× (mmap)**, **2-5× hit rate** | **+30-50%** | **LOW** |
| **+ Quality-Budgeted T1 (0.55% drift)** | 99.45%+ | +30-50% extra | +25-40% (composite) | LOW |

**Recommended path**:
1. Phase 1 (Q1-Q3 Quality-First) — 5-8 weeks
2. Phase 2 (Q5N quick wins) — 1-2 weeks
3. Phase 3 (Q6-Q8N major projects) — 8-12 weeks
4. Phase 4 (Q9N multi-instance) — 3-4 weeks
5. Optional Phase 5 (T1 quality-budgeted) — 2-3 weeks

**Total quality-preserving programme**: ~6 months focused work for FAR more capable system без любого quality loss.

## Files

- This plan: `docs/_internal/research/EXPANDED_QUALITY_PRESERVING_OPTIONS_2026-05-10.md`
- Related:
  - `QUALITY_FIRST_OPTIMIZATION_PLAN_2026-05-09.md` (T0 base)
  - `QUALITY_BUDGETED_OPTIMIZATION_PLAN_2026-05-09.md` (T1 budget)
  - `KV_COMPRESSION_COMPREHENSIVE_2026-05-09.md` (full landscape)
