# Universal persistent, brain-like, self-evolving memory — architecture & engine selection

**Status:** design / discussion (rev 2, 2026-06-30). Grounded in a live web + HuggingFace
research sweep of 25+ systems, the commercial landscape, eval benchmarks, governance, and
the self-improvement literature. Every option was checked for license, maturity,
self-hostability, and OpenAI-compatible/vLLM fit. Sources inline. **No build yet — this is
the decision document we iterate on.**

## 0. Goal

A single persistent memory that is:

1. **Universal** — shared by **every** model: local (Qwen3.6, **Gemma-4**, Llama, Mistral)
   AND external (GPT, Claude, Gemini) via the proxy/aggregator. Not Qwen-specific.
2. **Brain-like** — entities as nodes, relationships as edges, connections that
   strengthen with use and decay when stale; structural integrity (no duplicate entities,
   contradictions resolved).
3. **Self-evolving** — reorganizes over time; gets smarter the longer it runs.
4. **Capability-growing for the local models** — not just retrieval; a path where
   accumulated memory becomes new *weights-level* ability for the local fleet.

## 1. Universality — the load-bearing principle (this is the answer to "not just Qwen")

The research is unanimous and verified across mem0, Letta, Zep/Graphiti, and LiteLLM: a
shared memory is **model-agnostic by design**, achieved with **pattern (a) — inject
retrieved memory as plain text into the request at the proxy/middleware layer** — *not*
pattern (b) per-model tool-calls.

- **Why (a) is universal:** retrieval returns *plain text*; every model family ingests it
  identically as ordinary prompt context. The model never sees a vector or a memory schema.
  One retrieve→inject path serves Qwen, Gemma, Llama, Mistral, GPT, Claude, Gemini with zero
  per-model branching. (LiteLLM's `async_pre_call_hook` modifies the `messages` array
  uniformly regardless of provider — https://docs.litellm.ai/docs/proxy/call_hooks; Hindsight
  injects memory via exactly this hook — https://hindsight.vectorize.io/cookbook/recipes/litellm-memory-demo.)
- **Why NOT (b):** tool-call formats differ per family (vLLM needs a different
  `--tool-call-parser` for hermes/mistral/llama3_json/pythonic — https://docs.vllm.ai/en/latest/features/tool_calling/);
  using memory-as-tool would break on any model with a missing/wrong parser. Reserve tool
  calls for *actual* tools; never for the shared memory channel.

### 1a. The embedder is NOT the chat model (the key clarification)

Picking **Qwen3-Embedding does NOT make the memory "Qwen-only."** The retrieval encoder is
a separate, pluggable component that emits a generic L2-normalized float vector; the chat
model is a downstream text consumer that never touches the vectors. Gemma/Llama/GPT/Claude
all retrieve from the same store identically. (Confirmed: RAG is a 3-part pipeline where
embedder ⟂ generation model — https://docs.langchain.com/oss/python/langchain/rag; vLLM
serves embeddings on a separate `/v1/embeddings` runner — https://docs.vllm.ai/en/latest/models/pooling_models.html.)

**The one real constraint** is internal to the store: **one embedder builds and queries the
entire index**; switching it later means re-embedding everything (old/new vector spaces are
incompatible — https://arxiv.org/pdf/2509.23471). So: pick ONE embedder deliberately,
version-pin its name into the store metadata, keep the chat layer freely swappable on top.

### 1b. Cross-model correctness invariant (5 axes, all mitigated by pattern (a))

| Divergence | Breaks naive memory | Mitigation |
|---|---|---|
| Chat templates (ChatML / `<start_of_turn>` Gemma / `[INST]` Mistral) | wrong control tokens → silent quality loss | emit neutral OpenAI `role`/`content`; let each backend's `apply_chat_template` render it (https://huggingface.co/docs/transformers/en/chat_templating) |
| Context window (32k→1M) | over-stuffing 32k models; lost-in-the-middle | per-model token budget `Avail = Limit − (prompt+query+output)`, ranked top-k, headroom |
| Tokenizers (different vocabs) | one counter mis-budgets another → overflow | count with the *target* model's own tokenizer |
| Tool-call formats | memory-as-tool breaks per missing parser | deliver memory as plain context, never tool calls |
| Provider schema (Anthropic top-level `system`, Gemini `contents`/`parts`) | naive passthrough breaks | neutral OpenAI messages → per-provider adapter remaps; put recalled (untrusted) text in a non-system message + sanitize (prompt-injection defense — https://www.promptfoo.dev/docs/red-team/rag/) |

### 1c. The weights-loop is per-architecture (the only non-universal part)

The retrieval layer is universal; the *"model gets smarter in weights"* layer is
irreducibly per-base-architecture. A LoRA adapter is bound to one architecture's module
shapes/names (PEFT: `target_modules` chosen by architecture, error if unknown —
https://huggingface.co/docs/peft/developer_guides/lora). So:

- **One shared memory store** (universal, retrieval-time).
- **One LoRA per base architecture** — a Qwen3.6 LoRA, a **Gemma-4 LoRA**, etc. — distilled
  from the same shared memory (MemLoRA https://hf.co/papers/2512.04763, TMEM https://hf.co/papers/2606.04536).
- **One vLLM instance per base model**, each `--enable-lora` + hot-reload via
  `/v1/load_lora_adapter` (https://docs.vllm.ai/en/latest/features/lora/); a single engine
  hosts only its own family's adapters (vLLM #13633 — one base per engine, "run multiple
  instances + a routing layer").
- **The aggregator routes** by architecture + per-request `model`. **This is exactly the
  existing Genesis topology** (aggregator in front of multiple vLLM engines) — the design
  fits what we already run.

## 2. Architecture

```
   any client / agent ─▶ OpenAI-compatible PROXY (memory-middleware: inject on READ, capture on WRITE)
                              │ routes to                       │ calls every request
              ┌───────────────┼────────────────┐       ┌───────▼─────────────────────────┐
        external APIs   vLLM: Qwen3.6 (+LoRA)  vLLM: Gemma-4 (+LoRA)   MEMORY SERVICE (universal)
        (via aggregator)      └──────── share ─────────┘ ──────▶ brain = temporal/onto KG + vector
                                                                  embed/rerank via vLLM /v1/embeddings
                                                                  REST + MCP; async consolidation worker
                                                          nightly memory→LoRA distiller (per-arch) ──┘
```

## 3. Engine selection — the brain (all Apache-2.0/MIT, self-hostable, vLLM via base_url)

Commercial reality: the leaders are **open-core** — the engine is OSS-self-hostable, the
cloud sells managed hosting/compliance. So we self-host the engine.

| Engine | Brain mechanism | Self-evolution | Universal-share | Stars / release |
|---|---|---|---|---|
| **cognee** | ECL graph+vector + ontology + coreference | `memify`: usage-weighted edge reinforcement + stale-node pruning (Hebbian-like) + `improve()` | FastAPI **API-mode** — many models share one graph; MCP | 26k / v1.2.2 (2026-06) |
| **Graphiti** (Zep OSS) | bi-temporal KG | edge **invalidation** (validity windows; contradictions close old edges, never delete) → audit-preserving "forget" | `group_id` namespacing; MCP+REST | 28k / v0.29.2 (2026-06) |
| **Mem0** | vector + entity-graph | ADD/UPDATE/DELETE/NOOP (paper) → append-only v3 | `user_id`/`agent_id` scoping; "universal memory layer" | 60k / 2026-06 |
| **Letta** (MemGPT) | tiered blocks (RAM/disk) | self-editing blocks + **sleep-time** consolidation agent | shared memory blocks across agents | 24k / 2026-05 |
| **HippoRAG 2** | neocortex(LLM)+hippocampus(KG)+PPR | non-parametric continual learning | library (wrap it) | 4k / 2025 |

- **Primary: cognee** — closest literal fit for "neuron-like connections that strengthen +
  structural integrity + self-evolving," and its **API-mode is explicitly the universal
  shared store** ("Claude, GPT-4, local Llama talk to the same cognee instance"). vLLM via
  LiteLLM `hosted_vllm/`. (https://github.com/topoteretes/cognee, https://docs.cognee.ai/cognee-mcp/mcp-overview)
- **Alternative/companion: Graphiti** — best when auditable bi-temporal fact validity +
  provenance (every fact → source episode) matter most. (https://github.com/getzep/graphiti)
- **HippoRAG 2** as the retrieval engine behind the service for multi-hop reasoning.

### Retrieval models (pick ONE embedder, version-pin; all Apache-2.0, vLLM-served, multilingual incl. Russian)
- Embedding: **Qwen3-Embedding-4B** (~8 GB, MTEB-multi ~69.5) or **-8B** (~16 GB, #1 ~70.6);
  **BGE-M3** (MIT, ~2 GB, dense+sparse+ColBERT) as the pragmatic light default.
- Reranker: **Qwen3-Reranker-4B** or **bge-reranker-v2-m3** (light).
- (Avoid Jina/Cohere-open — CC-BY-NC non-commercial.)

## 4. Memory tiers + build-blocks (CoALA taxonomy, arXiv 2309.02427)

Working / episodic / semantic / procedural. Coverage: **Letta** + **LangGraph+LangMem** are
the only OSS that cleanly span all four (LangMem adds procedural = evolving system prompts).
cognee/Graphiti/Mem0 = strong episodic+semantic.

- **Ingestion/extraction:** LLM entity+relation extraction on the local fleet (Graphiti
  `OpenAIGenericClient` json_schema; or **GLiNER** Apache-2.0 no-LLM NER for cheap/deterministic).
  Avoid GLiREL/ReLiK (CC-BY-NC).
- **Entity resolution / dedup (structural integrity):** the production pattern is
  **embedding-similarity blocking → LLM judge** (Graphiti `resolve_extracted_nodes`: cosine
  top-15 @ 0.6 → LLM; Mem0 ADD/UPDATE/DELETE/NOOP). Classical add-on: **Splink** (MIT) or
  **SemHash** (MIT, cosine@0.9) / **datasketch** MinHash-LSH.
- **Decay / forgetting (brain-like):** Generative-Agents `recency×importance×relevance`
  (decay 0.995) or **MemoryBank** Ebbinghaus `R=e^(−t/S)` (MIT); LangChain
  `TimeWeightedVectorStoreRetriever` (decay_rate default 0.01) is the drop-in.
- **Async consolidation (off the hot path):** keep retrieval cheap+sync; push
  extraction/dedup/reflection to a background worker (**Celery**/RQ/**arq**) or **Letta
  sleep-time** (arXiv 2504.13171, ~5× test-time-compute reduction) — batch the cold LLM work
  on the local vLLM via `LLM.generate()` / `run_batch`. We have idle GPU at night for this.

## 5. Governance & security (a shared store is a poisoning target — OWASP Agentic T1)

- **Isolation:** do NOT rely on metadata-filter-only (confirmed leakage + injection-bypass).
  Use DB-enforced isolation: **pgvector + Postgres Row-Level Security** (predicate in the
  engine), or per-tenant Qdrant collections / Weaviate tenants for regulated data.
- **PII at ingestion:** **Microsoft Presidio (MIT) + GLiNER-PII (Apache-2.0)**; redact the
  stored chunks, not just the live turn. (Avoid Piiranha — CC-BY-NC-ND.)
- **Poisoning (the dominant threat):** MINJA (arXiv 2503.03704) shows an *unprivileged* user
  can plant memories that later hit others (>95% injection success). Defenses: isolation +
  ingestion scrubbing + **write-time provenance & source trust-scoring** (down-weight/quarantine
  by author) + retrieval audit logs.
- **Forget/GDPR:** Graphiti's two ops — soft invalidation (audit-preserving) + hard delete
  for erasure; track lineage so deletion reaches derived embeddings/summaries.
- **Provenance:** Graphiti gives native answer→fact→source-episode backlinks; else store
  `source_id`/`chunk_id` per row + log retrieved IDs per answer.

## 6. Self-improvement — smarter over time (ranked by practicality)

1. **Reflexion** + **2. ExpeL** — verbal self-correction + abstracted reusable insights;
   zero training, pure memory layer, **work for external + internal alike**.
3. **Voyager skill library** — verified executable skills (for tool/code agents).
4. **Self-RAG** — critic gates retrieval + self-validates.
5. **Memory → LoRA distillation** — the realistic *weights-level* path for the **local
   models** (per §1c, one adapter per architecture; vLLM hot-swaps). MemLoRA/TMEM confirm.
6. **SEAL** (self-adapting LLMs) — highest ceiling, research-grade (catastrophic forgetting);
   long-horizon target, not a near-term build.

## 7. Evaluation — measure that memory actually helps (adopt before/with build)

- **LongMemEval** (primary, MIT, arXiv 2410.10813) — natively runs the system-under-test on a
  **self-hosted vLLM** (`serve_vllm.sh`); 5 abilities incl. temporal + abstention. Use a fixed
  grader.
- **ConvoMem** (arXiv 2511.10523) — 75k QA, statistical power; **and its key finding gates our
  whole effort: below ~150 conversations, long-context beats RAG (70-82% vs 30-45%); the heavy
  memory layer only pays off past ~150-300 interactions.** → don't over-build; gate the KG
  layer behind a conversation-volume threshold.
- **Skip LoCoMo as primary** — answer-key 6.4% wrong, lenient judge accepts ~63% of wrong
  answers, and the public Mem0↔Zep dispute shows the numbers aren't reproducible. Treat all
  vendor "#1 on LoCoMo/LongMemEval" claims as marketing; **validate on our own data**.
- Optional: **HHEM-2.1-Open** (Apache-2.0, <600 MB CPU) as a factual-consistency gate on
  answers (replicates Vectara's hallucination score self-hosted).

## 8. Recommendation & phased rollout

- **Phase 0 — gate (cheap):** measure conversation volume; if a workload is < ~150 repeated
  interactions, plain long-context + the existing `chat_rag` vector RAG is enough — don't
  build the KG yet (ConvoMem). Stand up **LongMemEval** self-hosted as the scoreboard first.
- **Phase 1 — universal retrieval brain:** deploy **cognee API-mode** (Postgres+pgvector
  (+Neo4j/Kuzu graph)) on the homelab; point its LLM/embed at the proxy/vLLM; serve
  **Qwen3-Embedding-4B + Qwen3-Reranker-4B**. Add the **proxy memory-middleware**
  (LiteLLM-style pre-call hook: inject on read, async capture on write) — **shared by all
  models (Gemma, Qwen, external) by construction**. Seed from the existing `chat_rag` corpus.
  Add Presidio PII scrubbing + pgvector RLS isolation from day one.
- **Phase 2 — self-evolution:** enable cognee `memify` (edge reinforcement + pruning) +
  decay weighting; run extraction/consolidation on the async worker (sleep-time, batched on
  idle GPU); add Reflexion/ExpeL insight capture.
- **Phase 3 — per-architecture weights loop:** nightly distiller selects high-value validated
  memory → SFT set → **one LoRA per local architecture** (Qwen3.6, Gemma-4) → hot-swap into
  the matching vLLM engine, gated by a held-out eval (forgetting guard). The aggregator routes.

**Bottom line for your concern:** the memory is **universal for every model** because it
lives in the proxy and injects plain text — Gemma, Qwen, Llama, and external GPT/Claude all
share one brain. The embedder choice is an internal detail, not a model lock-in. The only
per-model piece is the optional weights-loop, which is one small LoRA per local architecture,
served by the engines + aggregator we already run.

### Key sources
- Universality/injection: https://docs.litellm.ai/docs/proxy/call_hooks · https://docs.langchain.com/oss/python/langchain/rag · https://huggingface.co/docs/transformers/en/chat_templating
- Per-arch LoRA: https://docs.vllm.ai/en/latest/features/lora/ · https://github.com/vllm-project/vllm/issues/13633 · https://hf.co/papers/2512.04763 (MemLoRA) · https://hf.co/papers/2606.04536 (TMEM)
- Engines: https://github.com/topoteretes/cognee · https://github.com/getzep/graphiti · https://github.com/mem0ai/mem0 · https://github.com/letta-ai/letta · https://github.com/OSU-NLP-Group/HippoRAG
- Tiers/decay: https://arxiv.org/abs/2309.02427 (CoALA) · https://arxiv.org/abs/2305.10250 (MemoryBank) · https://arxiv.org/abs/2304.03442 (Generative Agents) · https://arxiv.org/abs/2504.13171 (sleep-time)
- Governance: https://arxiv.org/abs/2503.03704 (MINJA) · https://github.com/microsoft/presidio · OWASP Agentic T1
- Eval: https://github.com/xiaowu0162/LongMemEval · https://arxiv.org/abs/2511.10523 (ConvoMem) · https://huggingface.co/vectara/hallucination_evaluation_model
- Embedders: https://hf.co/Qwen/Qwen3-Embedding-4B · https://hf.co/BAAI/bge-m3 · https://huggingface.co/spaces/mteb/leaderboard
