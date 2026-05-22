# PN95 Phase 3 Design — Boot-time KV Pool Expansion via CPU Tier

**Status:** DRAFT 2026-05-09 (5 empirical findings from live single-A5000 test)
**Trigger:** Single-A5000 live test revealed PN95 cannot extend max_seq_len beyond what fits in GPU pool because vLLM's `_check_enough_kv_cache_memory` pre-flight check rejects boot before PN95 can engage. **Additionally** — Phase 2 demote is bookkeeping-only and does NOT release physical GPU memory back to the pool, so even when demote fires under pressure, vLLM still hits CUDA OOM.

## Empirical findings (single A5000 24 GiB, 27B-int4-AutoRound, TQ k8v4, MTP K=3)

### Test 1 — `max_model_len=200000`, `gpu-memory-utilization=0.85`

```
ValueError: To serve at least one request with the models's max seq len (200000),
(5.55 GiB KV cache is needed, which is larger than the available KV cache
memory (0.48 GiB).
```

**Result:** Engine init crash. PN95 anchors never get a chance to register/demote.

### Test 2 — `max_model_len=64000`, `gpu-memory-utilization=0.92`

```
ValueError: To serve at least one request with the models's max seq len (64000),
(2.23 GiB KV cache is needed, which is larger than the available KV cache memory
(2.13 GiB). Based on the available memory, the estimated maximum model length
is 59136.
```

**Result:** Same crash. vLLM tells us the **hard ceiling on this hardware = 59136 tokens**.

## Root cause — boot-time validation gap

vLLM v1 startup sequence:

```
EngineCore.__init__()
  └─ _initialize_kv_caches(vllm_config)
       └─ get_kv_cache_configs(...)
            └─ _check_enough_kv_cache_memory(available_memory, get_needed_memory, ...)
                 └─ if needed > available: raise ValueError
```

`available_memory` is computed as `gpu_memory * gpu_memory_utilization - model_size - workspace_overhead`.

**The check considers GPU memory only.** It has no awareness of:
- `CacheConfig.tiers` (Genesis Path C config)
- `_pn95_runtime.tier_manager()._cpu_slab.capacity`
- Anything outside `vllm.cache_config`

PN95's 5 current text-patch anchors all fire **inside the engine's hot path**:
- `cache_blocks` (admit) — runtime
- `get_cached_block` (touch) — runtime
- `KVCacheManager.__init__` (mamba-init) — engine init, but AFTER `_check_enough_kv_cache_memory`
- `gpu_model_runner.initialize_kv_cache` (register) — engine init, but AFTER
- `Scheduler.schedule` (tick) — runtime

**None of them intercept the pre-flight memory check.** Result: PN95 today is a *runtime safety belt* but cannot enable boot configurations that would otherwise fail.

## Why this matters

The original target use case for Path C v1.0 was:
> club-3090 #58: Single 3090 + Qwen3.6-27B + vision + 100K+ context →
> OOM at turn ~12 of conversation.

But on a single 24 GiB card with 27B+TQ k8v4+MTP, the empirical hard ceiling is **~59K tokens at boot**. That doesn't even reach the start of the long-context use case. PN95 in its current form would never engage because vLLM refuses to start.

**For PN95 to deliver its value-prop, it must extend `available_memory` at boot to include the CPU tier capacity, AND ensure subsequent physical KV pool allocation respects the GPU-only limit.**

## Phase 3 design — Two-anchor extension

### Anchor #6 — `_check_enough_kv_cache_memory` boost

**File:** `vllm/v1/core/kv_cache_utils.py`
**Function:** `_check_enough_kv_cache_memory` (line 690)

**Patch:**
```python
def _check_enough_kv_cache_memory(
    available_memory: int,
    get_needed_memory: Callable[[], int],
    max_model_len: int,
    estimate_max_model_len: Callable[[int], int],
):
    # [Genesis PN95 v1.0 Phase 3] tier-aware boot-time KV pool expansion
    # — fail-silent
    try:
        from vllm.sndr_core.cache._pn95_runtime import (
            pn95_extra_logical_memory_bytes,
        )
        extra = pn95_extra_logical_memory_bytes()
        if extra > 0:
            available_memory += extra
    except Exception:
        pass

    if available_memory <= 0:
        ...  # unchanged
```

**Helper to add to `_pn95_runtime.py`:**
```python
def pn95_extra_logical_memory_bytes() -> int:
    """Returns bytes that PN95 will offload to CPU/NVMe tiers.

    This expands vLLM's view of available KV pool size at boot time,
    allowing larger max_model_len to pass the pre-flight check.

    Physical GPU allocation is bounded separately via Anchor #7.
    """
    if not _enabled():
        return 0
    tm = _TM
    if tm is None:
        return 0
    extra = 0
    for tier_idx, tier in enumerate(tm.tiers):
        if tier_idx == 0:
            continue  # tier 0 is GPU, already counted by vLLM
        if tier.device == "cpu":
            extra += int(tier.capacity_gib * (1024 ** 3))
        # Future: nvme tier
    return extra
```

### Anchor #7 — Physical num_blocks cap

**File:** `vllm/v1/core/kv_cache_utils.py`
**Function:** `get_num_blocks` (line 931) and the `KVCacheTensor` allocation site (around line 1252)

**Problem:** If we just inflate `available_memory`, vLLM computes
`num_blocks = available_memory // page_size` → too many blocks → physical
GPU `torch.empty(...)` allocation crashes with CUDA OOM.

**Solution:** Two-track block accounting:
- **Logical num_blocks** — used by scheduler/planner for max_seq_len enforcement
- **Physical num_blocks** — actually allocated on GPU; bounded by GPU-only memory

**Patch:**
```python
def get_num_blocks(
    vllm_config: VllmConfig,
    num_layers: int,
    available_memory: int,
    page_size: int,
) -> int:
    num_blocks = int(available_memory // page_size // num_layers)
    num_blocks = max(num_blocks, 0)
    # [Genesis PN95 v1.0 Phase 3] expose logical count for scheduler;
    # bound physical allocation separately
    try:
        from vllm.sndr_core.cache._pn95_runtime import (
            pn95_logical_num_blocks_override,
        )
        logical = pn95_logical_num_blocks_override(num_blocks)
        if logical is not None:
            return may_override_num_blocks(vllm_config, logical)
    except Exception:
        pass
    return may_override_num_blocks(vllm_config, num_blocks)
```

And **separate** physical allocation override at `KVCacheTensor`
construction site:
```python
# Around line 1252-1264
physical_num_blocks = num_blocks
try:
    from vllm.sndr_core.cache._pn95_runtime import (
        pn95_physical_num_blocks_cap,
    )
    cap = pn95_physical_num_blocks_cap()  # GPU-only
    if cap is not None and cap < physical_num_blocks:
        physical_num_blocks = cap
except Exception:
    pass

kv_cache_tensors.append(
    KVCacheTensor(size=ps * physical_num_blocks, shared_by=shared_by)
)
```

**Helpers in `_pn95_runtime.py`:**
```python
def pn95_logical_num_blocks_override(physical: int) -> Optional[int]:
    """Inflated block count used by scheduler — physical+demoted."""
    if not _enabled():
        return None
    tm = _TM
    if tm is None:
        return None
    cpu_extra_blocks = sum(
        int(tier.capacity_gib * (1024 ** 3) // _block_size_bytes())
        for tier in tm.tiers[1:]
    )
    return physical + cpu_extra_blocks

def pn95_physical_num_blocks_cap() -> Optional[int]:
    """Bounded by GPU-only memory — what we'll actually torch.empty."""
    if not _enabled():
        return None
    tm = _TM
    if tm is None or len(tm.tiers) < 1:
        return None
    return int(tm.tiers[0].capacity_gib * (1024 ** 3) // _block_size_bytes())
```

### Anchor #8 (optional) — BlockPool allocate hot-path

**File:** `vllm/v1/core/block_pool.py`
**Function:** `BlockPool.get_new_blocks` (or whatever the allocator entry-point is in dev93)

When a request needs a new block but all `physical_num_blocks` are taken, the current PN95 scheduler-tick (anchor 5) only fires periodically. For predictable behavior we want **synchronous demote** at allocation time when the pool is exhausted.

**Patch sketch:**
```python
def get_new_blocks(self, num_blocks: int) -> list[KVCacheBlock]:
    # ... existing code ...
    if not self.free_block_queue.has_n_blocks(num_blocks):
        # [Genesis PN95] try synchronous demote before raising
        try:
            from vllm.sndr_core.cache._pn95_runtime import (
                synchronous_demote_for_blocks,
            )
            freed = synchronous_demote_for_blocks(num_blocks)
            if freed >= num_blocks:
                pass  # retry allocation
        except Exception:
            pass
    # ... continue existing ...
```

## Open design questions

1. **Block size mismatch between tiers.** Currently `_CpuSlab` uses `slot_nbytes` from config. But each KV layer might have a different `page_size_bytes` (TQ k8v4 ≠ stock fp16). Need to either:
   - Multi-class CpuSlab (different slot sizes per layer family), OR
   - Single max-page-size slab + per-layer offset accounting
2. **Logical block count must reflect Mamba exclusion.** 3 of 4 KV groups in Qwen3.6-27B are Mamba SSM (excluded from demote). So `logical_num_blocks` should only inflate for the *attention* groups. Wrong inflation → scheduler thinks Mamba blocks can be demoted → state corruption when they get touched.
3. **vLLM's `estimate_max_model_len` binary search** assumes available_memory is GPU-only. With PN95 it will report an inflated max — which is correct for the user, but will surprise them if they later disable PN95 and the same config no longer boots. Need a clear error message in the `_check_enough_kv_cache_memory` raise path naming PN95 as the dependency.
4. **Pinned RAM at scale.** Inflating logical blocks by 8 GiB of pinned RAM × 2 TP workers = 16 GiB pinned. On the user's 64 GiB host that's fine, but at TP=4+ on a 32 GiB host this is a footgun. Need a pre-check in `init_from_config` that warns/refuses when `cpu_tier_capacity_gib_per_worker × n_workers > host_ram * 0.4`.
5. **Cold-start latency.** Synchronous demote at allocation time blocks the request. Worst case: long-context request needs 100 new blocks at once → 100× cudaMemcpyDeviceToHost serialized → tens of ms latency spike. Mitigation: keep async-demote (anchor 5) aggressive enough that synchronous demote is rare.

## Validation plan

After Phase 3 implementation:

1. **Boot test** — `max_model_len=120000` on single A5000 should now pass `_check_enough_kv_cache_memory` (with 8 GiB CPU tier giving +66K tokens of headroom).
2. **Long-context probe** — single 100K-token request → should generate output (not OOM). Demote should fire midway through prefill.
3. **A/B vs PN95=OFF** — with PN95=OFF, max workable context = 59K. With PN95=ON+Phase3, max workable context = ~120K (2× extension).
4. **Multi-turn pressure** — 20-turn conversation with 8K context per turn. Without PN95: dies at turn ~7. With PN95 Phase 3: completes all 20 turns.
5. **Bench A/B at 32K context** (well below GPU ceiling) — should be NULL impact (no demote needed).

## Effort estimate

- Anchor #6 (boot check expansion) + helper: **2-3 hours** (text-patch + tests + live verify)
- Anchor #7 (logical/physical split) + helpers: **6-8 hours** (more invasive — needs to thread two-track accounting through all call sites)
- Anchor #8 (synchronous demote on allocate): **3-4 hours**
- Multi-class CpuSlab (open question 1): **4-6 hours**
- Live A5000 + 27B verification matrix: **2-3 hours**
- Phase 3 design doc + PR review prep: **2 hours**

**Total: ~20-25 hours focused work** = 1 long autonomous session or 3-4 normal sessions.

## Decision deferred to Sander

Three options:
- **A.** Implement Phase 3 in next autonomous session (high value — finally delivers the headline use case)
- **B.** Ship a partial fix (Anchor #6 only, with documented caveat that physical OOM at allocation is still possible) — gives boot success, doesn't deliver real KV extension
- **C.** Document only, defer Phase 3 to community contribution

Recommend **A**: this is the missing piece that makes PN95 actually
deliver on its design promise. Without Phase 3, PN95 is "tier-aware
plumbing without the tier extension."
