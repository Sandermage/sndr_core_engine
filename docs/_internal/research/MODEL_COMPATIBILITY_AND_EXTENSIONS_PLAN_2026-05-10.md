# Model Compatibility Matrix + Qwen/Gemma 4 Extensions Plan

**Date**: 2026-05-10
**Critical principle**: ВСЕ optimizations должны быть compatible со всеми supported моделями. Особый focus — **Qwen3.6 (hybrid GDN)** + **Gemma 4** (dense attention с native SWA).

## vLLM dev93 — Полный список supported моделей (text generation)

### Major dense LLM families

#### Qwen family
- `Qwen` (Qwen 1) — original, mostly historical
- `Qwen2ForCausalLM` (Qwen 1.5, 2) — production
- `Qwen2MoeForCausalLM` (Qwen 2 MoE) — production
- `Qwen2_5_VLForConditionalGeneration` (Qwen 2.5-VL multimodal)
- `Qwen3ForCausalLM` (Qwen 3 dense) — production
- `Qwen3MoeForCausalLM` (Qwen 3 MoE) — production
- `Qwen3_5ForConditionalGeneration` (Qwen 3.5 hybrid GDN) — **Genesis 27B PROD target**
- `Qwen3_6ForConditionalGeneration` (Qwen 3.6 hybrid GDN) — **Genesis 35B PROD target**
- `Qwen3NextForCausalLM` (Qwen3-Next 80B) — emerging support

#### Gemma family
- `GemmaForCausalLM` (Gemma 1)
- `Gemma2ForCausalLM` (Gemma 2 — native SWA per-layer)
- `Gemma3ForCausalLM` (Gemma 3)
- `Gemma3VLForConditionalGeneration` (Gemma 3 multimodal)
- `Gemma4ForCausalLM` (Gemma 4) — **Genesis target для extension**
- `Gemma4VLForConditionalGeneration` (Gemma 4 multimodal)

#### Llama family
- `LlamaForCausalLM` (Llama 1, 2, 3, 3.1, 3.2, 3.3)
- `Llama4ForConditionalGeneration` (Llama 4 — MoE + multimodal)
- `MllamaForConditionalGeneration` (Llama 3.2 Vision)

#### Mistral family
- `MistralForCausalLM` (Mistral 7B, NeMo, Large)
- `MixtralForCausalLM` (Mixtral 8x7B, 8x22B)
- `PixtralForConditionalGeneration` (Pixtral multimodal)

#### DeepSeek family
- `DeepseekForCausalLM` (V1)
- `DeepseekV2ForCausalLM` (V2 — MLA architecture)
- `DeepseekV3ForCausalLM` (V3 — MLA + MoE 671B)
- `DeepseekV3_2ForCausalLM` (V3.2)
- `DeepseekV4ForCausalLM` (V4 — emerging)

#### Phi family
- `PhiForCausalLM` (Phi 1, 1.5, 2)
- `Phi3ForCausalLM` (Phi 3, 3.5)
- `Phi4ForCausalLM` (Phi 4)
- `Phi4MultiModalForCausalLM` (Phi 4 vision)

#### Yi / 01.AI
- `YiForCausalLM` (Yi 1, 2, 3)
- `LlamaForCausalLM` use also (some Yi variants)

#### ChatGLM
- `ChatGLMForCausalLM` (ChatGLM 1-5)

#### InternLM
- `InternLMForCausalLM`
- `InternLM2ForCausalLM` (1.5, 2, 2.5, 3)

#### MiniCPM
- `MiniCPMForCausalLM` (1, 2, 3, 4)
- `MiniCPMVForConditionalGeneration` (V variants)

#### Other dense
- `StableLmForCausalLM`
- `FalconForCausalLM` (1, 2)
- `MPTForCausalLM`
- `BloomForCausalLM`
- `OPTForCausalLM`
- `GPTNeoXForCausalLM`
- `XverseForCausalLM`
- `OrionForCausalLM`
- `OlmoForCausalLM` (OLMo 1, 2)
- `OlmoMoEForCausalLM` (OLMo MoE)
- `OlmoHybridForCausalLM` (OLMo hybrid Mamba+Attn)

### Multimodal models
- `LlavaForConditionalGeneration` (LLaVA 1.5, 1.6)
- `LlavaNextForConditionalGeneration`
- `LlavaOnevisionForConditionalGeneration`
- `Qwen2VLForConditionalGeneration` (Qwen2-VL 7B, 72B)
- `MiniCPMVForConditionalGeneration` (V2.5, 2.6)
- `InternVLChatModel` (InternVL 2, 3, 3.5)
- `CogVLMForConditionalGeneration`
- `IdeficsForConditionalGeneration` (Idefics 1, 2)
- `Florence2ForConditionalGeneration` (Florence 2)

### MoE families (specific)
- Mixtral, DeepSeek V2/V3, Qwen MoE, Llama 4, Snowflake-Arctic, GLaM, Granite-MoE, OLMoE

### Embeddings / classification
- `BgeM3Model`, `BertModel`, `RobertaModel` для embeddings
- `Qwen2VLClassifier` для VLM classification

### Speech
- `WhisperForConditionalGeneration` (Whisper)

## Genesis production matrix

### Currently in Genesis production (validated)

| Model | Architecture | Genesis status | KV setup |
|---|---|---|---|
| **Qwen3.6-27B-int4-AutoRound** | hybrid GDN (Mamba + 17 attn) | ✅ PROD | TQ k8v4 |
| **Qwen3.6-35B-A3B-FP8** | dense attention 64 heads | ✅ PROD | TQ k8v4 |
| Qwen3.5-DFlash | dense | tested | TQ k8v4 |
| Qwen3-Next-80B-AWQ | MoE | candidate | TBD |

### Genesis target additions

| Model | Architecture | Status | Priority |
|---|---|---|---|
| **Gemma 4 (26B MoE)** | dense attn + native SWA | TARGET | HIGH |
| **Gemma 4 (31B dense)** | dense attn + native SWA | TARGET | HIGH |
| Qwen3.6-Next-80B | MoE hybrid | candidate | MEDIUM |
| Llama 4 | MoE | candidate | MEDIUM |
| DeepSeek V4 | MLA + MoE | candidate | LOW (huge model) |

## Compatibility framework — каждый PN95 anchor

### Анализ совместимости anchor → model architecture

| Anchor | Model dependency | Qwen3.6 27B/35B | Gemma 4 | Notes |
|---|---|---|---|---|
| #1 admit | none (BlockPool API) | ✅ | ✅ | Universal |
| #2 touch | none | ✅ | ✅ | Universal |
| #3 mamba-init | Mamba spec only | ✅ active | ⏳ no-op | Gemma 4 has no Mamba |
| #4 register_kv_caches | KV groups iteration | ✅ | ✅ | Universal |
| #5 scheduler_tick | none | ✅ | ✅ | Universal |
| #6 blockpool register | none | ✅ | ✅ | Universal |
| #7 demote_on_evict | _attention_views populated | ✅ | ✅ | Universal |
| #8 promote_on_miss | byte-level copy | ✅ | ✅ | Universal |
| #9 phase5 boot expansion | none | ✅ | ✅ | Universal |
| #10 phase5 metadata init | KVCacheBlock fields | ✅ | ✅ | Universal |
| #11 phase5 inflation | bytes_per_block from views | ✅ | ✅ | Auto-detected |
| #12 phase5 get_new_blocks | swap mechanism | ✅ | ✅ | Universal |

**Conclusion**: ВСЕ existing anchors **model-agnostic** или auto-detect через TM views.

## Gemma 4 specifics — что нужно добавить

### Gemma 4 architecture characteristics

1. **Native sliding window attention** (как Gemma 2/3)
   - Per-layer SWA: некоторые layers global attention, some sliding (e.g., 4096 window)
   - vllm уже supports through `sliding_window` config
   - **Naturally cuts KV memory** для long contexts (built-in!)

2. **Dense attention** (no Mamba)
   - All layers eligible для PN95 demote (no exclusions needed)

3. **Sigmoid attention scale**
   - Different from softmax — некоторые kernels могут различаться

4. **GQA** (Grouped Query Attention)
   - Standard for modern Gemma

5. **Long context support** native
   - Gemma 4 likely 256K+ native (architectural)

### Gemma 4 + PN95 — automatic compatibility

Поскольку PN95 anchors model-agnostic + Gemma 4 native SWA:

- **Native SWA reduces KV needs** ~4-16× for long contexts (free quality-preserving win!)
- PN95 prefix-cache extension работает identical
- Multi-tier (CPU/NVMe) tier integration straightforward
- **Anticipated boot just works** с проверкой config

### Required Gemma 4 patches (если есть)

Need verification после Gemma 4 release:
1. Tool call format (Gemma uses different than Qwen3)
2. Reasoning/thinking mode (Gemma 4 may have own format)
3. Stop sequences
4. Tokenizer specifics

Genesis pattern matching:
- P61 family (Qwen3 tool calls) → нужны Gemma 4 equivalents
- PN16 lazy reasoner (Qwen3 thinking) → нужны Gemma 4 equivalent

## Qwen extension opportunities

### Existing Qwen3.6 enhancements (production)

| Patch | Function | Status |
|---|---|---|
| P58 | Async placeholder fix | ✅ |
| P60/60b | GDN ngram fix | ✅ |
| P61/61b/61c | Multi-tool, streaming, deferred commit | ✅ |
| P62 | Reasoning-aware spec timing | ✅ |
| P64 | Qwen3coder MTP streaming | ✅ |
| P66 | Cudagraph size filter | ✅ |
| P67 family | TQ multi-query kernel | ✅ |
| P68/69 | Auto-force tool, long-ctx tool reminder | ✅ |
| P95 | Qwen3 sampler config | ✅ |
| PN16 V8 | Lazy reasoner think budget | ✅ |
| PN56 | XML fallback | ✅ |
| PN77 | FP8 lm_head | ✅ |

### Possible Qwen extensions

#### Q-Ext-1: Qwen3 reasoning depth optimization
- Adaptive `<think>` budget per request complexity
- **Quality**: improvement (better balance speed vs depth)
- **Effort**: 1 неделя

#### Q-Ext-2: Qwen3 multi-tool parallel execution detection
- Detect когда tools могут run в parallel
- **Quality**: improvement (faster multi-tool)
- **Effort**: 1-2 недели

#### Q-Ext-3: Qwen3 hybrid GDN + Mamba state caching
- Mamba SSM state currently не cached cross-request
- Some workloads могут benefit
- **Quality**: identical
- **Effort**: 2-3 недели

#### Q-Ext-4: Qwen3-Next 80B integration
- Future model support
- **Effort**: 2-4 недели

## Gemma 4 integration plan

### Phase G1 — Foundation (когда Gemma 4 released)

1. **Verify model loads via vllm dev93+** (1 day)
2. **Basic inference test** — tokenization, generation, stop sequences (2-3 days)
3. **PN95 compatibility test** — все 12 anchors apply, no errors (1 day)
4. **Tool call format research** — what does Gemma 4 use? (2-3 days)
5. **15-case tool quality bench** на base Gemma 4 (1 day)

**Sprint G1 deliverable**: Gemma 4 loads + serves + measured baseline.

### Phase G2 — Genesis-Gemma 4 patches (если нужны)

Если Gemma 4 differs:
1. **Tool call parser** (Gemma 4 specific) — analogue of P61 (1-2 weeks)
2. **Thinking mode handler** — analogue of PN16 (1 week)
3. **MTP / spec decode tuning** — Gemma 4 might support own draft (1-2 weeks)
4. **Cudagraph capture sizes** для Gemma 4 architecture (3-5 days)
5. **15-case tool quality** with Gemma 4 patches → must reach 15/15

**Sprint G2 deliverable**: Genesis-quality Gemma 4 production-ready.

### Phase G3 — Long-context optimizations (Gemma 4 native SWA)

1. **Verify SWA enabled** by default или optional
2. **PN95 + SWA composition** — they're orthogonal (no conflict)
3. **Long context probes** — 64K, 128K, 256K, 512K with SWA
4. **Composite stack tuning** — auto-tune for Gemma 4

**Sprint G3 deliverable**: Gemma 4 на 256K+ context с PN95 prefix cache extension.

### Phase G4 — Multimodal (Gemma 4 VL)

1. **Image input support** verification
2. **Vision token handling** (vision_demote_first applicable)
3. **PN95 + Vision tokens** — vision-first demote priority

## Compatibility validation framework

### Model matrix testing protocol

Каждое изменение PN95/Genesis MUST pass на минимум:

#### Tier A — Production critical (must always pass 15/15)
1. Qwen3.6-27B-int4-AutoRound (hybrid GDN)
2. Qwen3.6-35B-A3B-FP8 (dense)

#### Tier B — Reference compatibility (must pass без crash, tool 13/15+)
3. Llama 3.1 8B (canonical dense)
4. Mistral 7B (canonical)
5. Mixtral 8x7B (MoE reference)

#### Tier C — Future targets (when added)
6. Gemma 4 26B MoE
7. Gemma 4 31B dense

#### Tier D — Edge cases
8. DeepSeek V3 (MLA architecture)
9. Qwen3-Next-80B (MoE hybrid)

### Per-architecture compatibility matrix

| PN95 Feature | Dense | MoE | Hybrid GDN/Mamba | MLA | Native SWA |
|---|---|---|---|---|---|
| All 12 anchors | ✅ | ✅ | ✅ | ✅ | ✅ |
| Mamba SSM exclusion | n/a (no-op) | n/a | ✅ critical | n/a | n/a |
| Per-tier demote | ✅ | ✅ | ✅ | ✅ | ✅ |
| Vision demote priority | ✅ | ✅ | ✅ | ✅ | ✅ |
| TQ k8v4 KV | ✅ | ✅ | ✅ | depends на MLA layout | ✅ |
| FP8 long-ctx KV | ✅ | ✅ | ✅ | depends | ✅ |
| RadixAttention | ✅ | ✅ | ✅ | ✅ | ✅ |
| mmap Tier 3 | ✅ | ✅ | ✅ | ✅ | ✅ |
| Async stream | ✅ | ✅ | ✅ | ✅ | ✅ |

**Conclusion**: PN95 architecture **fully model-agnostic** благодаря side-table approach. Никаких model-specific assumptions.

## Композитные projections с Qwen + Gemma 4

### Single A5000 + Gemma 4 31B (dense + native SWA + Genesis full stack)

| Layer | Capacity | TPS | Quality |
|---|---|---|---|
| Gemma 4 base + native SWA | 64K easily | baseline | 100% |
| + PN95 Phase 4.2 (prefix cache) | extra 4 GiB CPU | baseline | 100% |
| + Quality-First T0 stack | 5-25× CPU tier | +15-30% | 100%+ |
| + Quality-Preserving (NUMA, mmap, RadixAttention) | TBs cache | +30-50% | 100% |
| **🎯 Composite на Gemma 4 + native SWA** | **256K+ realistic** | **+30-50%** | **100%+** |

**Native SWA + PN95 prefix cache extension = perfect synergy**:
- SWA сжимает per-token KV cost
- PN95 расширяет cross-request hits
- Together: больше total context capability + better cache hit rates

### 2× A5000 + Gemma 4 26B MoE

| Stack | Max ctx | TPS | Quality |
|---|---|---|---|
| Base | 256K (with SWA) | varies | 100% |
| **+ Genesis full stack** | **1M+ realistic** | **+30-50%** | **100%+** |

### 2× A5000 + Qwen3.6 35B PROD (current production)

| Stack | Max ctx | TPS | Quality |
|---|---|---|---|
| Current | 320K | 233 baseline | 100% |
| + Quality-Preserving full | 500-700K | +30-50% | 100%+ |

## Sprint roadmap для Gemma 4 + Qwen extensions

### Sprint M1 (когда Gemma 4 released) — Gemma 4 foundation

1. **Verify Gemma 4 loads** на vllm dev93+
2. **PN95 compatibility check** (auto via existing test infrastructure)
3. **15-case tool quality baseline** on Gemma 4
4. **Identify needed Genesis patches** для Gemma 4 specifics

**Deliverable**: Gemma 4 production-feasible analysis.

### Sprint M2 (2-4 нед) — Gemma 4 Genesis patches

1. Genesis-Gemma 4 tool call parser (если differs)
2. Genesis-Gemma 4 thinking mode (если differs)
3. MTP/spec decode tuning
4. **15/15 tool quality** validation

### Sprint M3 (2 нед) — Gemma 4 + PN95 long-context

1. Long-context probes 64K → 512K с SWA + PN95
2. Composite TPS bench
3. Multi-turn pressure test

### Sprint M4 (1-2 нед) — Multi-model inventory

1. Document supported model list в Genesis docs
2. Per-model recommended configs
3. Auto-detect helper в `sndr` CLI

### Sprint Q-ext1 (1 нед) — Qwen3 reasoning depth optimization

### Sprint Q-ext2 (1-2 нед) — Qwen3 parallel tool execution

### Sprint Q-ext3 (2-3 нед) — Mamba SSM state caching

## Composite vision — все плани вместе с model support

### Per-model max realistic после full stack

| Model | Hardware | Max ctx | TPS | Quality |
|---|---|---|---|---|
| **Qwen3.6 27B-int4** | 1× A5000 | **150-200K** | +30-45% | 99%+ |
| **Qwen3.6 35B-A3B-FP8** | 2× A5000 | **600-800K** | +30-45% | 99%+ |
| **Gemma 4 31B dense** | 1× A5000 | **256K+** (SWA + PN95) | +30-50% | 100%+ |
| **Gemma 4 26B MoE** | 2× A5000 | **1M+** | +30-50% | 100%+ |
| Llama 4 | TBD | TBD | TBD | TBD |

## Стратегия quality jump через model expansion

**Insight**: каждая supported model = разная trade-off curve. Pick best для use case:

| Use case | Best model | Why |
|---|---|---|
| Multi-turn agent (medium ctx) | Qwen3.6 27B | Best tool quality + reasoning |
| Long-document Q&A | **Gemma 4 (with SWA)** | Native long-ctx + retention |
| Code generation | Qwen3.6 35B Coder | Best code quality |
| RAG | **Gemma 4 31B** | Long ctx + accuracy |
| Multimodal | Qwen2-VL 7B / Gemma 4-VL | Vision + tool call |
| Massive scale | Qwen3-Next 80B / DeepSeek V4 | Top-tier quality |

**Quality jump strategy**: deploy multiple models cooperatively:
- Lightweight model для simple queries (faster TTFT)
- Heavy model для complex queries (better quality)
- Cache-aware routing (L2/N1 from Quality-Preserving plan)

## Compatibility tests infrastructure

### Genesis CLI integration

```bash
# Test PN95 compatibility on any model
sndr test-compat --model <path> --pn95 --tier A|B|C|D

# Run full compat matrix
sndr matrix-test --tier A,B,C
```

### Per-model auto-config

```bash
# Auto-detect optimal config для model
sndr auto-config --model <path> --hw single-a5000
```

## Итоговые рекомендации

### Текущая Sprint priority (immediate)

1. **Document supported model list** в Genesis docs (1-2 days)
2. **Create per-model recommended configs** в `model_configs/builtin/` (1 week)
3. **Compatibility test suite extension** (Tier A/B/C automated) (1-2 weeks)

### Next когда Gemma 4 released

1. **Sprint M1: Gemma 4 foundation** (1-2 weeks)
2. **Sprint M2: Genesis-Gemma 4 patches** (2-4 weeks)
3. **Sprint M3: Long-context + SWA composition** (2 weeks)

### Long-term

1. **Sprint Q-ext1-3: Qwen extensions** (parallel)
2. **Sprint M4: Multi-model orchestration** (cache-aware routing)

## Key insight для quality jump

**Sander prediction**: full integration Gemma 4 + Qwen3.6 + Quality-First/Preserving stack = **systematic quality jump**:

1. **Quality**: 15/15 on Qwen3.6 → 15/15 on Gemma 4 too (proper patches)
2. **Per-model best fit** = better answers per use case
3. **Composite optimizations** (PN95 + native SWA) = **больше capability per dollar**
4. **Operator infrastructure** (auto-config, cache-aware routing) = production-grade

## Файлы

- This plan: `docs/_internal/research/MODEL_COMPATIBILITY_AND_EXTENSIONS_PLAN_2026-05-10.md`
- Related:
  - `EXPANDED_QUALITY_PRESERVING_OPTIONS_2026-05-10.md` (extended optimizations)
  - `QUALITY_FIRST_OPTIMIZATION_PLAN_2026-05-09.md` (T0 baseline)
  - `QUALITY_BUDGETED_OPTIMIZATION_PLAN_2026-05-09.md` (T1 budget)
  - `KV_COMPRESSION_COMPREHENSIVE_2026-05-09.md` (full landscape)
- Future:
  - Per-model configs в `vllm/sndr_core/model_configs/builtin/`
  - `gemma4-26b-moe.yaml`, `gemma4-31b-dense.yaml` (когда Gemma 4 released)
