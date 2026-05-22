# PN95 Phase 5 — KV Pool Virtualization (Detailed Plan)

**Status:** DESIGN DRAFT 2026-05-09
**Goal:** Расширить `max_model_len` за GPU hardware ceiling через logical/physical num_blocks split.
**Effort estimate:** **20-25 hours focused work**, very invasive, requires incremental per-anchor regression testing.

## Цель

Сейчас (после Phase 4.1):
- Single A5000 24GB + 27B-int4 hard ceiling = ~59K tokens (vllm pre-flight check)
- PN95 расширяет prefix CACHE capacity, но не max_model_len single request

После Phase 5:
- Single A5000 + 27B: max_ctx **с 59K → ~120-150K** (CPU tier даёт +60-90K extra)
- 2× A5000 + 27B: **с 320K → ~500K+**
- Single 24GB + 35B (если weights fit): **новый workable range**
- Без потери TPS на normal workload (когда блоки не demoted)

## Архитектурный подход

**Logical/physical num_blocks split**:

```
vllm scheduler view (LOGICAL):
  num_blocks = (gpu_memory + cpu_tier_memory) / page_size
  Used for: max_seq_len enforcement, scheduler concurrency, request admission

physical KVCacheTensor allocation (PHYSICAL):
  num_blocks_phys = gpu_memory_only / page_size
  Used for: actual torch.empty() on GPU, BlockPool slot creation

PN95 maintains logical_to_physical mapping:
  block_id_logical → (block_id_physical OR cpu_slot_id)
```

При `BlockPool.get_new_blocks(N)`:
- Если physical free slot есть → return как обычно
- Если нет → demote коldest physical block в CPU → reuse slot
- При attention forward: read через physical block_table (always physical IDs)
- При prefix cache hit на логический id → promote из CPU если нужно

## 5 новых text-patch anchor'ов

### Anchor #9 — Boot pre-flight expansion

**File**: `vllm/v1/core/kv_cache_utils.py`
**Function**: `_check_enough_kv_cache_memory` (line 690)
**Patch**: inflate `available_memory` += `cpu_tier_capacity_bytes`

```python
def _check_enough_kv_cache_memory(available_memory, get_needed_memory, max_model_len, estimate_max_model_len):
    # [Genesis PN95 v1.0 Phase 5] tier-aware boot check expansion
    try:
        from vllm.sndr_core.cache._pn95_runtime import pn95_extra_logical_memory_bytes
        extra = pn95_extra_logical_memory_bytes()
        if extra > 0:
            available_memory += extra
    except Exception:
        pass
    # ... rest unchanged
```

**Effort**: 2-3h (anchor + helper + boot test)

### Anchor #10 — Physical KVCacheTensor cap

**File**: `vllm/v1/core/kv_cache_utils.py`
**Site**: line ~1252, `KVCacheTensor(size=ps * num_blocks, ...)` allocation

**Critical**: physical GPU allocation must NOT use inflated num_blocks → CUDA OOM.

```python
# Cap physical allocation to GPU-only memory
physical_num_blocks = num_blocks
try:
    from vllm.sndr_core.cache._pn95_runtime import pn95_physical_num_blocks_cap
    cap = pn95_physical_num_blocks_cap()
    if cap is not None and cap < physical_num_blocks:
        physical_num_blocks = cap
except Exception:
    pass
kv_cache_tensors.append(
    KVCacheTensor(size=ps * physical_num_blocks, shared_by=shared_by)
)
```

**Effort**: 2-3h. **Risk**: vllm может assume `num_blocks == tensor.shape[0]` в downstream code → if mismatch crashes. Нужен careful tracing.

### Anchor #11 — BlockPool inflated logical blocks

**File**: `vllm/v1/core/block_pool.py`
**Site**: `BlockPool.__init__` line ~149

**Strategy**: создаём N inflated logical KVCacheBlocks (N=logical), но physical_num_blocks из них помечены `physical_resident=True`, остальные `physical_resident=False` (demoted by default).

```python
def __init__(self, num_gpu_blocks, ...):
    # [Genesis PN95 v1.0 Phase 5] inflated logical pool
    try:
        from vllm.sndr_core.cache._pn95_runtime import pn95_logical_num_blocks_override
        logical = pn95_logical_num_blocks_override(num_gpu_blocks)
        if logical is not None:
            num_logical = logical
            num_physical = num_gpu_blocks  # original
        else:
            num_logical = num_gpu_blocks
            num_physical = num_gpu_blocks
    except Exception:
        num_logical = num_gpu_blocks
        num_physical = num_gpu_blocks

    self.num_gpu_blocks = num_logical  # what scheduler sees
    self.num_physical_blocks = num_physical
    self.blocks = [KVCacheBlock(idx) for idx in range(num_logical)]
    # Mark first num_physical as resident, rest as virtual
    for i, blk in enumerate(self.blocks):
        blk.physical_resident = (i < num_physical)
        blk.physical_block_id = i if i < num_physical else None
    # ...
```

**Effort**: 4-5h. **Risk**: KVCacheBlock object size inflation; downstream code touching `block.block_id` directly may fail.

### Anchor #12 — get_new_blocks virtualization

**File**: `vllm/v1/core/block_pool.py`
**Function**: `get_new_blocks(num_blocks)` line ~322

**Strategy**: при allocate:
1. Pop logical block from free_block_queue
2. If `block.physical_resident`: return as-is
3. Else: trigger sync demote of coldest resident block → take its physical_id → mark new block resident

```python
def get_new_blocks(self, num_blocks):
    if num_blocks > self.get_num_free_blocks():
        raise ValueError(f"Cannot get {num_blocks} free blocks from the pool")
    ret = self.free_block_queue.popleft_n(num_blocks)
    
    # [Genesis PN95 v1.0 Phase 5] materialize virtual blocks
    for blk in ret:
        if not getattr(blk, "physical_resident", True):
            try:
                from vllm.sndr_core.cache._pn95_runtime import pn95_materialize_virtual_block
                pn95_materialize_virtual_block(self, blk)
            except Exception:
                pass
    # ... rest unchanged
    return ret
```

**Helper `pn95_materialize_virtual_block(pool, blk)`**:
- Find coldest resident block via free_block_queue tail walk
- Copy GPU bytes → CPU prefix store (key: that block's hash)
- Take its `physical_block_id` → assign to `blk`
- Mark old block `physical_resident=False`
- New block now points to physical slot

**Effort**: 5-6h. **Critical race**: if cold block being read by attention NOW, demote corrupts. Solution: `cudaDeviceSynchronize` before swap, OR use ref_cnt guard (skip if ref_cnt > 0).

### Anchor #13 — Promote-on-touch для virtual blocks

**File**: `vllm/v1/core/block_pool.py`
**Function**: `touch(blocks)` line ~390

**Strategy**: when block touched (cache hit), if `physical_resident=False` → restore from CPU.

```python
def touch(self, blocks):
    for block in blocks:
        # [Genesis PN95 v1.0 Phase 5] promote virtual blocks on touch
        if not getattr(block, "physical_resident", True):
            try:
                from vllm.sndr_core.cache._pn95_runtime import pn95_promote_virtual_block
                pn95_promote_virtual_block(self, block)
            except Exception:
                pass
        # ... rest unchanged
```

**Effort**: 3-4h.

## Validation matrix

После каждого anchor:
1. Boot test (модель грузится OK)
2. Tool quality 15/15 (no regression)
3. Quick bench wall_TPS (within 3% of baseline)
4. Full bench при final integration

After all 5 anchors:
1. **27B PROD на 2× A5000**: max_ctx 320K (current) → ?? (tier extension)
2. **Single A5000 + 27B**: max_ctx 59K → 120-150K
3. **Stress test**: 100K probe должен PASS (раньше OOM)
4. **Multi-turn 30K cumulative**: TPS regression < 5%
5. **35B PROD**: 15/15 tool, decode TPS within noise

## Risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Race: demote during attention read | Garbage outputs | cudaDeviceSync before block_table commit; ref_cnt guard |
| Inflated num_blocks breaks downstream code | Crash on init | Trace ALL usages of num_gpu_blocks; gate via env var GENESIS_PN95_VIRT |
| CPU pinned RAM exhaustion | OOM на host | LRU evict from prefix store; warn if cpu_tier > host_ram*0.4 |
| Promote latency spike | TTFT +20-50ms | Async prefetch on speculative read; warm cache |
| Mamba SSM corruption | Garbage outputs | exclude_mamba_ssm enforced (already in TM); never demote Mamba |

## Per-anchor effort + cumulative validation

| Anchor | Effort | Validation gate |
|---|---:|---|
| #9 boot expansion | 2-3h | Boot OK with max_model_len=GPU_max + 30% |
| #10 physical cap | 2-3h | Boot OK no CUDA OOM |
| #11 logical pool | 4-5h | Boot OK, scheduler sees inflated num_blocks |
| #12 get_new_blocks | 5-6h | Allocate triggers virt → real demote, wall_TPS no regression |
| #13 promote-on-touch | 3-4h | Cache hit on virt block → restore correctly |
| Integration testing | 3-4h | Full bench A/B + stress + multi-turn + bigger model |
| **Total** | **20-25h** | |

## Rollback plan

Each anchor has env gate `GENESIS_PN95_VIRT_<anchor>=1`. Disable bad anchors via env without code change. Hard rollback: remove anchors via text-patcher's `revert()` (if implemented) or git checkout.

## Decision criteria для start

Phase 5 нужно делать ТОЛЬКО если:
1. Phase 4.1 полностью stable в production (week+ uptime)
2. Sander подтверждает что 15/15 tool quality сохранён в реальных workloads
3. Sander принимает 20-25h time budget + risk regression
4. Есть multi-day window для incremental work с regression testing

Если что-то из 1-4 не выполнено — defer Phase 5 to next iteration.
