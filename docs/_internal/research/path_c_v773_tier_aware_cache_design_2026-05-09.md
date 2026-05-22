# Path C — Tier-aware CacheConfig design (v7.73.x / PN95)

**Date:** 2026-05-09
**Author:** Sandermage(Sander)-Barzov Aleksandr
**Companion:** [club3090_issue58_long_ctx_vision_oom_2026-05-09.md](club3090_issue58_long_ctx_vision_oom_2026-05-09.md)
**Scope:** Genesis-original tier-aware KV cache with vision sub-tier and Mamba SSM exclusion.
**Effort:** 5-9 days (deep design + impl + bench).

---

## 1. Code archaeology — what we already have

| Asset | File | Status |
|---|---|---|
| `CacheConfig` dataclass (single-tier, PN91) | `vllm/sndr_core/model_configs/schema.py:602-639` | shipped — `eviction_policy / arc_capacity / q2_a1_ratio` |
| `OffloadConfig` (Path A) with `cpu_offload_gib`, `swap_space_gib`, future-tier docstring | `vllm/sndr_core/model_configs/schema.py:318-372` | shipped — Path A; reserves namespace for `tiers: list[CacheTier]` |
| Hybrid-GDN guard (raises if PN59 + offload set) | `vllm/sndr_core/model_configs/schema.py:1029-1048` | shipped — to be relaxed by Path C |
| `EvictionPolicy` ABC + LRU/2Q/ARC | `vllm/sndr_core/cache/eviction_policies.py` | shipped — `touch / admit / evict / remove`; **single-tier; `evict()` drops** |
| `_is_hybrid_gdn(cfg)` helper | `vllm/sndr_core/model_configs/audit_rules.py:44` | shipped — `int4-autoround` / `lorbus` / PN59-env heuristic |
| KV-cache patches in same hot path (conflict surface) | `patches/kv_cache/p83_*.py`, `patches/kv_cache/p85_*.py`, `patches/scheduler/p8_kv_hybrid_reporting.py`, `patches/attention/turboquant/p67_*.py` | shipped — see §5 conflict matrix |
| Mamba SSM state references in patches | `patches/attention/gdn/pn30_*.py`, `pn32_*.py`, `pn79_*.py`, `p60_*.py` (all touch `ssm_state[...]`, `ssm_state_indices`, `mamba_state_copy_funcs`) | shipped — Mamba state lives at `self_kv_cache[1]` per layer; never in prefix-block pool |
| MM-input awareness | `patches/multimodal/pn62_text_only_vit_skip.py`, `patches/worker/pn35_inputs_embeds_optional.py` (both gate on `self.supports_mm_inputs`) | shipped — model-level boolean only; no per-token MM ranges yet |
| vLLM target files (KV manager) | `vllm/v1/core/kv_cache_manager.py`, `vllm/v1/core/single_type_kv_cache_manager.py`, `vllm/v1/core/block_pool.py`, `vllm/v1/core/kv_cache_coordinator.py` | upstream — text-patch targets, anchored by P83/P85/P8 already |
| Highest used PN | `PN90` (registered at `apply/_per_patch_dispatch.py:828`) — `PN95` would be next free in the "tier-aware/spillover" semantic group, leaving PN91-94 for the design's internal sub-patches |

The chassis is in place. We need: tier dataclass, CPU-pool, demote/promote, MM-tagging at admit, a Mamba-exclusion gate, and a text-patch into `KVCacheManager.cache_blocks` / `block_pool.get_cached_block` to route through the dispatcher.

## 2. Schema design

Add to `vllm/sndr_core/model_configs/schema.py`:

```python
@dataclass
class CacheTier:
    """One level of the KV cache hierarchy. Lower index = closer to compute."""
    device: str               # 'gpu' | 'cpu' | 'nvme'
    capacity_gib: float       # hard cap on this tier's allocation
    eviction_policy: str = "lru"  # forwarded to make_policy()
    promote_on_hit: bool = True   # demoted page hit → bring back to upper tier
    demote_threshold_pct: float = 0.92  # tier fill ratio that triggers demote
    low_water_pct: float = 0.75   # demote until this ratio reached
    vision_first: bool = False    # if True, evict mm pages before text
    pinned: bool = True           # for cpu tier: cudaMallocHost-backed
    nvme_path: Optional[str] = None  # required when device == 'nvme'

    def validate(self) -> None: ...  # device ∈ {'gpu','cpu','nvme'}, ranges, etc.


@dataclass
class CacheConfig:                # extend existing
    # ── existing PN91 fields (kept for back-compat) ──
    eviction_policy: str = "lru"
    arc_capacity: int = 4096
    q2_a1_ratio: float = 0.25
    notes: str = ""
    # ── PN95 (Path C) additions ──
    tiers: list[CacheTier] = field(default_factory=list)
    exclude_mamba_ssm: bool = True   # MUST stay True on hybrid-GDN
    vision_demote_first: bool = True
    tier_low_water_pct: float = 0.05  # GPU free-VRAM threshold to trigger demote
    async_demote: bool = True         # cudaMemcpyAsync vs sync
```

Back-compat rule: when `tiers == []`, schema falls through to current PN91-only behavior — zero impact for existing 35B/27B PROD configs.

`ModelConfig.validate()` already calls `cache_config.validate()` (`schema.py:1021`); we extend it to:
- assert at most one `device='gpu'` tier
- assert exactly one `device='cpu'` tier when len(tiers)>1
- when `_is_hybrid_gdn(self) and tiers and not cache_config.exclude_mamba_ssm` → `SchemaError` (HARD — same energy as the Path A guard, but invertible by setting the flag back to True)

This subsumes the current Path A guard at lines 1029-1048: when `cache_config.tiers` is set, `OffloadConfig.cpu_offload_gib > 0` is *additionally* allowed on hybrid-GDN, because Path C's tier manager handles the SSM exclusion (Path A could not).

## 3. Wire-in approach

Two text-patches + one new runtime module + one new admit-tag hook.

### 3.1 New runtime module: `vllm/sndr_core/cache/tier_manager.py`

```python
class TierManager:
    """Owns the per-tier EvictionPolicy + the host-pinned CPU pool.

    State per page: (block_hash, bytes_view, tier_idx, mm_origin_bool).
    Promote = upload from CPU pool → caller's GPU buffer (pre-existing).
    Demote  = cudaMemcpyAsync GPU block → CPU pool slot, mark in policy.
    """
    def __init__(self, tiers: list[CacheTier], block_nbytes: int): ...
    def admit(self, block_hash, *, mm_origin: bool) -> None: ...
    def touch(self, block_hash) -> Optional[bytes]: ...   # returns CPU bytes if demoted; None if GPU
    def demote_to_threshold(self) -> int: ...  # called when free_vram < low_water; returns nblocks moved
    def evict_terminal(self) -> Optional[Hashable]: ...   # last-resort drop from coldest tier
    def is_mamba_excluded(self, group_id: str) -> bool: ...  # MambaSpec group → True
```

The CPU pool is a single `torch.empty(N_pages, block_nbytes, dtype=torch.uint8, pin_memory=True)` allocated at startup from `tiers[1].capacity_gib`. Demote = `cuda_block.copy_(cpu_slot, non_blocking=True)` reversed; layout is byte-identical so no kernel cost.

### 3.2 PN95 text-patch — minimal vLLM hook

Two anchors, both surgical, both in files we already own anchors in:

**File A: `vllm/v1/core/single_type_kv_cache_manager.py`** (already patched by P83 + P85). Add tier dispatch at the end of `cache_blocks()`:

```python
# [Genesis PN95] tier-aware admit
if _g_pn95_tm is not None:
    for blk in newly_cached:
        _g_pn95_tm.admit(blk.block_hash, mm_origin=request.has_mm_input)
```

**File B: `vllm/v1/core/block_pool.py`** — `get_cached_block()`: before returning the GPU block, call `_g_pn95_tm.touch(block_hash)`; if it returns demoted bytes, the patch enqueues a promote (sync `copy_` from pinned CPU to a free GPU block, evicting the GPU LRU tail).

**File C (only when tiers!=[]):** in `KVCacheManager.__init__` we install the singleton `_g_pn95_tm = TierManager(...)` from `cfg.cache_config.tiers`. SSM-state exclusion is enforced by `KVCacheGroupSpec` filter — the helper from P8 (`token_capacity_kv_cache_groups`) already gives us "is MambaSpec"; we re-use that classifier.

### 3.3 Vision-token recognition

Two-step:
1. At request submission, `Request.has_mm_input = (request.mm_inputs is not None and len(request.mm_inputs) > 0)`. This is already a vLLM attribute path (it's why `pn35_inputs_embeds_optional.py` and `pn62_text_only_vit_skip.py` work).
2. At `cache_blocks()`, every newly-admitted block whose `start_token_idx ∈ request.mm_placeholder_ranges` is tagged `mm_origin=True`. `mm_placeholder_ranges` is the upstream attribute on `MultiModalKwargs`; we tag conservatively (any block whose token span overlaps any range).

`TierManager.demote_to_threshold()` then walks two LRU sub-queues and drains MM pages first when `vision_first=True` (default). MM pages are large (each image = 256-1024 tokens of vision-tower output) and *infrequent re-use* (one-shot screenshot in `opencode`), so their CPU round-trip cost amortizes; text-prefix pages stay GPU-resident.

### 3.4 Mamba-SSM exclusion

**Mandatory and non-overridable on hybrid-GDN.** SSM state at `self_kv_cache[1]` (per `p60_gdn_ngram_state_recovery.py:224, 236, 248, 259`) is a moving target — it's mutated in-place every decode step by `pn79_inplace_ssm_state.py`. Even if we could move it to CPU, by the time we copied it back the model would have moved on. Implementation:

- `TierManager` sees `KVCacheGroupSpec.kv_cache_spec` instances at registration. For every group whose spec `isinstance(MambaSpec, ...)`, register `is_mamba_excluded(group_id) = True`.
- Demotion candidates iterator filters out any block whose `group_id` is mamba-excluded. So demote/promote only ever touches AttentionSpec groups.
- CPU pool's slot count is sized by `attention_block_nbytes` only (mamba block size ≠ attn block size; we don't even allocate slots for mamba).

This is the bit upstream `SimpleCPUOffloadConnector` / LMCache / SGLang HiCache cannot do — their demote loop iterates *all* groups and crashes when it tries to memcpy a `MambaSpec` block whose layout is `(num_layers, head_dim, conv_state_dim)` instead of `(num_layers, num_kv_heads, head_dim, block_size)`.

### 3.5 PN number assignment

Highest existing PN in `apply/_per_patch_dispatch.py` = `PN90`. We assign:

- **PN95** — main tier-aware CacheConfig wire-in (single `register_patch("PN95 tier-aware KV cache + vision sub-tier (Genesis-original)")`). Using a 5-skip from PN90 leaves PN91-94 unconsumed for either: (a) sub-patches if PN95 grows multi-file; (b) future LMCache integration (Path B if revisited); (c) reserved for the deferred V8/observability extension.

The `apply_patch_PN95_tier_aware_cache()` function is opt-in via `GENESIS_ENABLE_PN95_TIER_AWARE_CACHE=1`, default OFF (matches PN90 / PN91 ABA-test pattern).

## 4. Step-by-step implementation order

| Day | Deliverable | Tests |
|---|---|---|
| **1** | `CacheTier` dataclass + extended `CacheConfig` + back-compat fall-through + hybrid-GDN gate flip | 12-15 unit tests in `tests/unit/model_configs/test_cache_tier_schema.py` (validate good/bad device strings, capacity ranges, MM/exclude flags, hybrid-GDN guard relaxation) |
| **2** | `vllm/sndr_core/cache/tier_manager.py` skeleton (CPU pool + admit/touch/demote/evict, no real CUDA copies — torch.zeros stub) + `make_tier_manager(cfg)` factory | 20 unit tests in `tests/unit/cache/test_tier_manager.py` (admit/touch round-trip, mm_origin flag, demote_first when vision_first, mamba exclusion from candidate set) |
| **3** | PN95 text-patch module `patches/kv_cache/pn95_tier_aware_cache.py` — anchors at `single_type_kv_cache_manager.py::cache_blocks` and `block_pool.py::get_cached_block` (mirrors P85 anchor style) | TextPatcher anchor parity test + apply/revert idempotency in `tests/unit/integrations/kv_cache/test_pn95_apply.py` |
| **4** | Wire `register_patch("PN95 ...")` in `apply/_per_patch_dispatch.py`, env-gate, dispatch matrix (`compose_apply_matrix` honors `GENESIS_ENABLE_PN95`); export `_g_pn95_tm` singleton inside the patched scope | 8 wiring tests; full `pytest tests/unit/` must stay GREEN (no regressions) |
| **5** | Vision-token tagging: `Request.has_mm_input` propagation + `mm_placeholder_ranges → block_overlap_set()` in `tier_manager.admit()`; small dense-MM model (Qwen3-VL-2B or any Qwen-VL stub) used in test fixture | 10 tests; **integration smoke test** on dense MM model (CPU only — no GPU needed since CPU pool is CPU-side) |
| **6** | Mamba exclusion runtime: hook into `KVCacheGroupSpec` walk at `TierManager.__init__`; filter MambaSpec groups out of candidate set; assert via `_is_hybrid_gdn(cfg) → mamba_groups > 0` | 6 tests; assertion test that `demote()` never returns a mamba-group block hash |
| **7** | **Live integration on 27B Lorbus** (server `vllm-server-p82-sweep` style container): 145K context + vision encoder live + 5-7 chat turns reproducer (the exact #58 scenario, but on 2× A5000 with `tiers=[gpu(20Gib), cpu(40Gib)]`); compare vs PN95-OFF baseline | bench-compare gate via `sndr bench-compare` |
| **8** | EXAMPLE config `model_configs/community/single-3090/long-vision-tier-aware.yml` (tiers=[gpu(20Gib), cpu(40Gib)], `vision_demote_first: True`); README v7.73.x section + CHANGELOG entry | doc lint passes; example config's `validate()` GREEN |
| **9** | Audit closure: bench numbers committed to `reference_metrics`; `community-test` lifecycle; cross-rig verify scaffolding (so noonghunna can second-rig validate); SESSION_LOG entry | `community-test` lifecycle gate passes |

Total surface area added: ~1100 LOC (300 schema, 500 tier_manager, 200 patch, 100 dispatcher wiring) + ~70 tests.

## 5. Risks + open questions

### 5.1 vLLM internal API surface
- `KVCacheManager.cache_blocks` and `block_pool.get_cached_block` are NOT public stable API — they're private V1 internals that can shift between dev pins. We're already text-patching this surface in P83/P85, so the marginal risk is one more anchor — but ANY upstream refactor of `single_type_kv_cache_manager.py` will hit P83+P85+PN95 simultaneously. Mitigation: drift markers (same pattern as `UPSTREAM_DRIFT_MARKERS_KV` in P8); pin PN95 to KNOWN_GOOD_VLLM_PINS allowlist.
- **Open Q:** is there a `BlockPool` callback hook upstream I missed? — searched `vllm/v1/core/` for `register_*`, `add_callback`, `BlockEvent` — none exist; text-patch is the only path. Confirm by running `grep -rn "register_observer\|on_evict\|on_admit" vllm/v1/` against running container before Day 3.

### 5.2 Spec-decode interaction (MTP K=3)
- MTP verifier needs the *previous* K+1 blocks of KV. If a block was demoted between draft and verify, we'd promote-back and pay a PCIe round-trip on a critical path. Mitigation: `TierManager.touch()` for blocks within the most recent `2 * (max_num_spec_tokens + 1)` decode steps refuses demotion (a "spec-decode hot ring"). P67 (TQ K+1 multi-query kernel) operates on the GPU block itself — it doesn't see the tier abstraction. Conflict-free by construction.
- **Open Q:** does P83 (MTP keep-last-cached-block) interfere? P83 adds a force-pop guard; PN95 should respect it — when P83 marks a block "do not evict", PN95 must also "do not demote". Add a `request.skip_tier_demote: bool` plumbed through the same path. Test under P83+PN95 cross-product on Day 6.

### 5.3 Memory bandwidth on consumer Ampere
- 2× A5000 = PCIe gen 4 x16 = ~30 GiB/s peak host↔device. A 16-token block at FP16 KV+head_dim=128 = ~64 KiB; 1000 blocks = 64 MiB = ~2 ms transfer. Async + low-water demote pre-frees before pressure hits. Single-3090 on PCIe gen 4 x16 ≈ same. PCIe gen 3 x16 → 16 GiB/s, ~4 ms per 1000 blocks; still acceptable. `ConfigConstraints.pcie_ok` already exists — extend with `min_pcie_gen=4` for tier configs (warning only).
- **Open Q:** how badly does cudagraph capture interact with async demotes? Cudagraph captures stream operations; an async demote launched mid-graph would be captured. Mitigation: demote runs on a separate CUDA stream (NOT the cudagraph stream), and `TierManager.demote_to_threshold()` is called from the **scheduler tick**, not from any captured forward path. Test by running `cudagraph_mode=FULL_AND_PIECEWISE` reproducer on Day 7.

### 5.4 Existing Genesis patch conflicts
| Patch | Touches | Conflict with PN95 |
|---|---|---|
| **P8** (`p8_kv_hybrid_reporting`) | `kv_cache_utils.py`, `scheduler.py` | None — different anchors, both rely on `KVCacheGroupSpec`. |
| **P83** (`p83_mtp_keep_last_cached_block`) | `single_type_kv_cache_manager.py:447-468` | Same file; non-overlapping anchors. P83's "keep last cached block" must imply PN95 "do not demote last cached block". Coordination via `request.skip_tier_demote` flag (§5.2). |
| **P85** (`p85_hybrid_fine_shadow_prefix_cache`) | `single_type_kv_cache_manager.py` + `block_pool` | Same files. P85 inserts shadow-cache lookups in `get_cached_block`; PN95 inserts a `tm.touch()` after the lookup returns. Order: P85 anchors first (it's already shipped), PN95 anchors *after* P85's marker. Verify on Day 3 with a combined-apply test. |
| **P67 / P67b / P67c** (TQ multi-query kernel) | attention kernel; reads from already-resident GPU blocks | None — tier moves only happen between forward passes. |
| **PN91** (eviction policies) | apply hook, no file edit yet (single-tier, runtime-only) | Subsumed — when `tiers != []`, PN95 *is* the multi-tier evolution of PN91. PN91's `make_policy(name)` is reused per tier. Both can be on simultaneously (PN91 = LRU on tier 0, PN95 adds tier 1). |
| **PN59** (streaming-GDN) | requires SSM exclusion | Compatible by design — PN95 hard-excludes mamba groups. |

### 5.5 Pinned-memory budget on host
- 40 GiB pinned RAM is non-trivial — competes with OS page cache. `ConfigConstraints.min_host_ram_gib` extension: refuse to enable when `host_ram_gib < 1.5 * tiers_cpu_capacity_gib`. Honors `ulimit -l` if set (Proxmox LXC has `memlock=unlimited` by default per `feedback_genesis_homelab_inventory.md`).

## 6. Bench plan

**Reproducer:** 27B Lorbus INT4-AutoRound (hybrid-GDN, our actual production stack), max_model_len=145000, vision encoder live, MTP num_spec_tokens=3, kv_cache_dtype=turboquant_3bit_nc, prefix-cache + chunked-prefill ON. Hardware: 2× A5000 (we don't have a 3090 — using A5000s gives more headroom but reproduces the same KV-pressure cliff at higher turn counts; on a 3090, Path A's #58 timing was turn 5-7 and that's what noonghunna will second-validate).

**Workload:** scripted `opencode`-style chat — first prompt uploads a 1024×1024 screenshot (~512 vision tokens), follow-ups are text-only ("explain step N", "now try the alternative"). Each turn adds ~2K tokens. Runs to **30 turns or first OOM**.

**Three measurement runs:**
1. **Baseline (no PN95, no Path A):** expected to OOM at turn ~12-15 on A5000s (extrapolated from #58's turn-5-7 on 3090).
2. **Path A only (CPU offload weights):** dense models would help, hybrid-GDN this is currently *blocked* by the schema guard — bench will confirm by running the guard relaxation manually.
3. **PN95 ON, tiers=[gpu(20Gib), cpu(40Gib)], vision_demote_first=True, exclude_mamba_ssm=True:** target = stable through turn 30+, with decode TPS within 30% of GPU-only baseline (the PCIe round-trip on vision pages is the dominant cost; text-prefix pages should never demote because they stay hot).

**Acceptance gates** (all must pass for community-test → community-dev promotion):
- Turn-count reach ≥ 2× baseline OOM point.
- Decode TPS regression ≤ 30% (acceptable — we're trading throughput for capability).
- Tool-call quality unchanged (10/10 on the standard suite, since PN95 doesn't touch decoder logic).
- VRAM peak ≤ 90% of `nvidia-smi` total at every turn (no headroom collapse).
- No assertion failures on `_g_pn95_tm.is_mamba_excluded(...)` — log every excluded group at boot to prove SSM never demoted.
- `sndr bench-compare PN95-OFF.json PN95-ON.json` produces a clean delta report (this CLI already exists from Sprint 2 audit closure).

**Cross-rig validation gate (Day 9):** ship `model_configs/community/single-3090/long-vision-tier-aware.yml` + ask noonghunna to repro on actual 3090 — `community-prod` requires ≥2 distinct `verified_by` entries per `ModelConfig.validate()` line 996.

---

## 7. Recommendation

Path C as designed here is implementable in 5-9 days because (a) the schema chassis exists, (b) the eviction-policy ABC exists, (c) the text-patch wire-in pattern is well-trodden in our P83/P85/P8 family, and (d) Mamba-exclusion has a clean classifier already (the `MambaSpec` instance check in P8). The only genuinely novel runtime code is `tier_manager.py` (~500 LOC) and one text-patch (~200 LOC) — everything else is composition of existing primitives.

**Do not start until** the existing 27B-Lorbus PROD container can be cloned to a `vllm-server-pn95-sweep` instance for Day 7 bench. That instance must run the same vllm pin currently in `KNOWN_GOOD_VLLM_PINS` to keep P83/P85 anchors valid.
