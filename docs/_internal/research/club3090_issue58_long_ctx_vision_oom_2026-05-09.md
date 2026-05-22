# club-3090 #58 — Long-Context + Vision OOM on 3090

**Research date:** 2026-05-09
**Issue:** [noonghunna/club-3090#58](https://github.com/noonghunna/club-3090/issues/58)
**Status upstream:** CLOSED (filed 2026-05-05 by `syangsao`, traced into Sandermage/genesis-vllm-patches#22; pivoted to v7.73.x memory-mgmt rework)
**Genesis hardware:** 2× RTX A5000 (48 GB total) — Sander has no 3090; #58 is a **community/cross-rig** signal we treat as architectural.

---

## 1. Issue summary

`syangsao` ran the single-3090 (24 GB) preset on `bash scripts/launch.sh`, picking either:

- **Option 1** — `long-text-vision.yml`: Qwen3.6-27B-AutoRound-INT4, **`max_seq_len = 145000`**, MTP `num_spec_tokens=3`, `kv_cache_dtype=turboquant_3bit_nc`, prefix-cache + chunked-prefill ON, vision encoder live.
- **Option 4** — bounded thinking, 180K ctx, structured-CoT FSM.

A fresh `opencode "hello"` chat works for the first ~5 turns (KV usage ~26 %). On the **6th–7th turn**, KV jumps to 36 % and the EngineCore crashes with `torch.OutOfMemoryError: Tried to allocate 50 MiB; GPU 0 has 23.56 GiB total / 56.88 MiB free`. Reproducer chain (from dump):

1. Vision-tower persistent allocation (~1 GB) is locked in by default.
2. Chunked-prefill on a hybrid GDN model promotes a 4128-token chunk while MTP holds 3 draft slots.
3. Eligibility check on **PN59 (streaming-GDN)** rejects the chunked-prefill path → no streaming free.
4. Activation+KV peak crosses the 24 GiB ceiling on the *second* prompt of the session.

Issue closed only because `syangsao` switched to `llamacpp/default` (no Cliff 2). The **structural defect remains open** in vLLM v0.20.1rc1.dev16 + Genesis v7.72.2.

`noonghunna` confirms PN59's runtime gate is too strict for forced-chunked-prefill on 24 GiB single-card configs and that v7.73.x will be a memory-mgmt rework, not a one-off patch.

---

## 2. State of the art (VRAM → RAM spillover)

| Project | What it offloads | API surface | Notes |
|---|---|---|---|
| **vLLM `--cpu-offload-gb`** ([docs](https://docs.vllm.ai/en/stable/configuration/engine_args/), [offload config](https://docs.vllm.ai/en/stable/api/vllm/config/offload/)) | **Weights only**, layer-by-layer | CLI flag, `auto` / `uva` / `prefetch` backends, `group_size` + `num_in_group` selectivity | Cheap, mature. Adds PCIe per-token cost on every offloaded-layer forward. **Doesn't help #58** — vision peaks are KV+activations, not weights. |
| **vLLM `OffloadingConnector` / `SimpleCPUOffloadConnector`** ([blog 2026-01](https://blog.vllm.ai/2026/01/08/kv-offloading-connector.html), dev93 native) | **KV cache pages** (prefix-block granularity) | `--kv-transfer-config '{"kv_connector":"SimpleCPUOffloadConnector",…,"cpu_bytes_to_use":N}'`. LRU / FIFO / S3FIFO eviction. Async worker threads (GPU↔CPU, future CPU↔Disk). | TTFT 2-22× lower on prompt re-use. **Doesn't work on hybrid GDN** (Mamba SSM state lives outside KV pool). Qwen3.6-A3B is GDN → blocked today. |
| **LMCache** ([docs](https://docs.lmcache.ai/), [v1 multimodal blog 2025-07](https://blog.lmcache.ai/2025-07-03-multimodal-models/)) | KV pages → CPU DRAM, NVMe, Redis, S3, Mooncake; **vision-aware** in V1 | `LMCacheConnectorV1`; `LMCACHE_CHUNK_SIZE` + `LMCACHE_LOCAL_CPU` env or yaml. | 3-10× delay savings on RAG/multi-turn. Multimodal hit-rate ~100 % on repeated images. Same hybrid-GDN blocker as SimpleCPU. |
| **SGLang HiCache** ([LMSYS blog 2025-09](https://www.lmsys.org/blog/2025-09-10-sglang-hicache/), [design](https://docs.sglang.io/advanced_features/hicache_design.html)) | L1 GPU + L2 CPU + L3 (Mooncake / 3FS / NIXL / AIBrix); `HiRadixTree` page table; GPU-assisted I/O kernels (3× over `cudaMemcpyAsync`) | `--hicache-ratio` (host pool / device pool, must be > 1); `write-through` / `selective` / `write-back` policies | Up to 6× throughput, 80 % TTFT reduction. Hybrid-GDN explicitly listed as **open** ([sglang#12826](https://github.com/sgl-project/sglang/issues/12826)). Different engine — not a vLLM patch. |
| **DeepSpeed-Inference / accelerate `device_map`** | Whole layers / weights to CPU + NVMe | `device_map="auto"`, ZeRO-Infinity offload | Static layer pinning, training-oriented. Not a serving solution for our workload. |
| **llama.cpp `mmap` + `--n-gpu-layers`** | Weight pages via OS page cache | CLI flag | Already shipped as the `llamacpp/default` Genesis route — what `syangsao` fell back to. Validates demand but isn't a vLLM fix. |

Key takeaway: **all three of vLLM's native CPU paths assume dense attention**. Hybrid-GDN models (Qwen3.6-27B / 35B-A3B — Genesis's whole production stack) are excluded today.

---

## 3. Where Genesis stands

Relevant code paths (verified locally 2026-05-09):

- **`vllm/sndr_core/cache/eviction_policies.py`** — PN91 (vllm#40270 backport) ships LRU / 2Q / ARC with a uniform `EvictionPolicy(touch/admit/evict/remove)` ABC. Pure-Python, no torch. Currently single-tier (GPU-only); `evict()` drops a key — it never moves the page to a host pool.
- **`vllm/sndr_core/model_configs/schema.py:CacheConfig`** — exposes `eviction_policy`, `arc_capacity`, `q2_a1_ratio`. **No `cpu_pool_gib`, no tier knob.**
- **`docs/PATCHES.md` §"Native upstream features"** — already documents `SimpleCPUOffloadConnector` with hybrid-GDN incompatibility caveat.
- **PN17 (FA2 softmax_lse runtime clamp)** — already widens the long-text-no-vision envelope from 150K → 205K on 24 GB cards (Cliff 1 fix). Vision still hits Cliff 2.
- **PN59 streaming-GDN orchestrator** — eligibility check rejects chunked-prefill batches, the exact path 24 GB single-card configs are forced into. This is the proximate gap #58 hits.

So the chassis (`CacheConfig` + `EvictionPolicy` ABC) is in place — what's missing is a **second tier** in eviction and a hybrid-GDN-safe spillover path.

---

## 4. Three concrete implementation paths

### Path A — Surface vLLM's native flags better in YAML (cheap, low-risk)

**Scope:** Two YAML keys + launcher plumbing + docs. **No new patch.**

- Add `cpu_offload_gb: int = 0` and `kv_offload_gb: int = 0` to `DeploymentConfig` (or a new `OffloadConfig` dataclass).
- Launcher renders `--cpu-offload-gb N` and (for dense models only) `--kv-transfer-config '{"kv_connector":"SimpleCPUOffloadConnector",…}'`.
- Hybrid-GDN guard: refuse to set `kv_offload_gb > 0` when `model.arch.is_hybrid_gdn`. Hard error with link to `docs/PATCHES.md#native-upstream-features`.
- Ship a `single-3090/long-vision-cpu-offload.yml` reference config wired with `cpu_offload_gb: 8` (weights → host) — buys ~2 GiB free VRAM for the activation peak.

**Effort:** 1 day. **Closes #58?** Partially — only on **dense** models and only the **weight** pressure.
**Wins on Genesis hybrid stack?** Negligible (Qwen3.6 is GDN).

### Path B — Backport LMCache integration as PN95 (medium, moderate risk)

**Scope:** Wrap upstream `LMCacheConnectorV1`, expose hybrid-GDN-aware feature flag.

- New patch `PN95_LMCACHE_KV_OFFLOAD` — adds `lmcache.LMCacheEngineBuilder` import + connector wiring in launcher.
- New `OffloadConfig` schema: `backend: 'lmcache' | 'simple_cpu' | 'none'`, `cpu_bytes: int`, `disk_path: str | None`.
- Reuse PN91 `EvictionPolicy.touch()` to **forward hits** to LMCache's hot-set predictor (write-through-selective on hot, write-back on cold).
- Vision-token policy: lean on LMCache V1 multimodal hit-rate (~100% on repeat-image) — frees image-token KV between turns of an `opencode` chat that re-uploads the same screenshot.
- Hard-gate behind `model.arch.is_hybrid_gdn == False` until upstream sglang#12826-equivalent lands.

**Effort:** 1-2 weeks (real bench cycle on dense reference model + cross-rig validation). **Closes #58?** On dense models yes, big win for vision hit-rate. **Hybrid-GDN still blocked** — same upstream gap.

### Path C — Genesis-original tier-aware `CacheConfig` (ambitious, high payoff)

**Scope:** Extend PN91 from single-tier eviction to **two-tier promotion/demotion**, with a Genesis-original CPU pool that handles hybrid-GDN's quirks.

- New `EvictionPolicy.evict(target_tier='cpu')` returns the victim **plus** triggers an async `_demote_to_cpu(page)` instead of unconditional drop.
- New `vllm/sndr_core/cache/cpu_pool.py` — pinned-memory (cudaMallocHost) page pool sized by `CacheConfig.cpu_pool_gib`. Page format mirrors the GPU block layout so promote/demote is `cudaMemcpyAsync` of contiguous bytes (no re-layout).
- **Vision-token tier** (the Genesis-original bit): tag pages with `mm_origin: bool` at admit time; CPU pool runs **two LRU sub-queues** — text pages (small, hot, kept warm) vs vision pages (large, cold-skewed, demoted aggressively). Vision tokens re-fetch from CPU on attention re-use — zero quality loss, since they've already been encoded.
- **Hybrid-GDN safety:** hold Mamba SSM state in a separate `ssm_pool` that is **never demoted** (correctness — SSM state is a moving target, not content-addressable). Only KV pages move. This is the bit upstream `SimpleCPUOffloadConnector` doesn't model — it tries to demote everything.
- Risk-score gate (`ConfigConstraints` already exists): refuse to enable on PCIe gen 3 or when host RAM < 32 GiB.
- Wire to existing `CacheConfig`: add `cpu_pool_gib: float = 0.0`, `vision_demote_priority: bool = True`, `tier_low_water_mark: float = 0.05` (free-VRAM threshold that triggers promotion).

**Effort:** 4-6 weeks (kernel-adjacent, needs cross-rig empirical bench, cudagraph capture-path implications). **Closes #58?** Yes, end-to-end, on Genesis's actual hybrid-GDN stack — including `opencode + screenshot + 145K` workflow.
**Risk:** High — touches the hot path; cudagraph capture must skip async demotes; pinned-memory budget can starve the OS page cache.

---

## 5. Recommendation

Propose **Path C** as the v7.73.x **headline feature**, gated by **Path A** as the v7.72.x point release.

Reasoning:

- **noonghunna already pre-announced** that v7.73.x is "a full memory-mgmt rework" in disc #19. The community expects a structural answer, not a flag flip. Path A alone would read as "we shipped CLI sugar."
- **Path B's blocker is the same as upstream's blocker** (hybrid-GDN incompatibility). Spending 2 weeks to ship a patch that excludes Genesis's own production model family is poor ROI.
- **Path C is the only one that addresses both axes #58 stresses**: vision-token KV pressure (mm-tier demotion) **and** long-context KV pressure (text-tier 2-Q with CPU spillover) **and** does it on the hybrid-GDN stack.
- The chassis already exists (`CacheConfig`, `EvictionPolicy` ABC, PN91 wired in dispatcher, `ConfigConstraints` for hardware gates). Path C is "extend what's there," not "greenfield."
- Path A is still worth doing as an interim — 1 day of work, gives single-3090-dense users (e.g. anyone running Qwen3-7B-Instruct on the recipes) a usable knob immediately, and proves the YAML schema before Path C lands the deeper machinery.

**Concrete next deliverable to propose to Sander:**

> Sprint plan for v7.72.x → v7.73.x: ship Path A this week (`OffloadConfig` schema + launcher flags + `single-3090/long-vision-cpu-offload.yml` for dense models, dense-only guard, docs update); start Path C as a 4-sprint design doc (week 1: spec + ABC extension + cpu_pool stub + tests; week 2: pinned-memory pool + promote/demote primitives; week 3: vision-tier tagging + Mamba SSM exclusion; week 4: cross-rig bench on 24 GB single-3090 with the exact #58 reproducer + bench-compare gate before promotion).

Path A unblocks dense-model 3090 users now. Path C is the answer the community has been told to expect.
