# Phase 7 — Single-card 156K+ context: architectural blockers and design

**Дата:** 2026-05-13
**Контекст:** после Phase 6 PoC (PN96 emergency-demote) — изучили что
именно не позволяет single-user 156K context на одной A5000 24 GB.

## Что доказано working на текущем стеке

| Конфигурация | Max context (verified) | Notes |
|---|---|---|
| 2×A5000 (TP=2), fp8 KV | **200K** (225K real prompt tokens) | 249s prefill |
| 1×A5000, fp8 KV, VIRT=0 | **102K** (vllm-confirmed honest max) | 132s prefill @ 100K |
| 1×A5000, fp8 KV, VIRT=1 + 156K | **OOM на boot** | Anchor #10 missing/broken |
| 1×A5000, fp8 KV, VIRT=1 + 100K | работает | но без выгоды |

## Точная диагностика — почему VIRT=1 даёт OOM

При `GENESIS_PN95_VIRT_ENABLE=1` + `max_model_len=156000`:

1. **Anchor #9** (boot-check inflation) — inflate'ит pre-flight check
   `available_memory_for_check += CPU_tier_bytes`. vllm проходит check
   для 156K. ✓ работает

2. **Anchor #11** (pool inflation) — расширяет
   `BlockPool.num_gpu_blocks` от 118 (physical) до 236 (logical+virtual).
   `register_kv_caches` log: `physical=118 → logical=236`. ✓ работает

3. **Anchor #10** (physical cap на KVCacheTensor) — **отсутствует/broken**:
   - В существующем PN95 файлах нет text-patch'а который cap'ит
     `KVCacheTensor.shape[0]` к physical limit
   - vllm читает `pool.num_gpu_blocks=236` и allocates tensor для
     236 blocks физической GPU памяти
   - 236 × ~21 MB/block × 17 attention layers = ~84 GiB запрошено
   - GPU только 24 GiB → CUDA OOM при tensor allocation

   ```
   torch.OutOfMemoryError: CUDA out of memory.
   Tried to allocate 24.00 MiB. GPU 0 has 17.69 MiB free.
   23.52 GiB in use.
   ```

Это **architectural mismatch**: vllm не разделяет
`physical_num_blocks` (real GPU slots) от `logical_num_blocks`
(addressable block_ids). Один и тот же `num_gpu_blocks` используется
И для tensor allocation, И для block addressing.

## Что нужно для Phase 7 (full 156K+ single-card)

### Component 1: Tensor shape decoupling

```python
# Текущее vllm:
kv_cache_tensor = torch.empty(
    (pool.num_gpu_blocks, block_size, num_heads, head_dim),
    dtype=kv_cache_dtype, device='cuda'
)

# Нужно:
kv_cache_tensor = torch.empty(
    (PHYSICAL_NUM_BLOCKS,  # ← capped — fits in GPU
     block_size, num_heads, head_dim),
    dtype=kv_cache_dtype, device='cuda'
)
# But pool.num_gpu_blocks reports LOGICAL (for block_table addressing)
```

Требует **новый text-patch** на `_initialize_kv_caches` /
`KVCacheTensor` constructor — анкор который кап'ит shape к
`min(pool.num_gpu_blocks, PHYSICAL_LIMIT)`.

### Component 2: Block_id translation layer

Когда `block_table[seq_pos] = 234` (logical, virtual block),
attention forward делает `tensor[234, :, :, :]`. Но tensor shape
`(118, ...)` — IndexError → CUDA illegal access.

Нужен **address translation:**

```python
# Replace direct indexing:
kv = tensor[block_id]
# With translated:
phys_id = block_id_table[block_id]
if phys_id < 0:
    # block on CPU — materialize now
    phys_id = pn95_materialize_virtual_block(pool, block_id)
kv = tensor[phys_id]
```

Это **modify attention kernel** (Triton / CUDA). Не achievable text-patch'ем.

### Component 3: Cross-step KV state machine

Между scheduler ticks, какие-то blocks могут перемещаться
GPU↔CPU. Attention forward должен видеть consistent состояние.

Опции:
- **Lock-based**: PN95 lock на time-of-forward, demote/promote только
  между forwards. Простой, но stalls demote.
- **Versioned**: block_id_table версионируется per-step. Каждый
  step pre-compute консистентный snapshot. Сложнее, перфектная latency.

### Component 4: Scheduler-side preemption coordination

Когда `get_new_blocks(N)` fails и no free cached blocks — нужно
preempt active sequence:

```python
# Pseudo
def get_new_blocks_with_preempt(num_blocks):
    if num_blocks > self.get_num_free_blocks():
        # Find oldest active sequence
        victim = self._oldest_active_sequence
        # Demote victim's blocks to PN95 L2
        for blk_id in victim.block_table:
            pn95_demote(blk_id)
        # Free slots, retry
        self.free_blocks(victim.block_table)
        victim.status = SUSPENDED
        # Now there are enough free slots
    return self.free_block_queue.popleft_n(num_blocks)
```

vllm v1 scheduler **already has** `_try_preempt_request` — но он
работает только при multi-user (preempts OLDER request, not self).
Для single-user 156K — нет жертвы.

**Для self-preemption** нужно:
- Разделить single request на chunks (`request_id_chunk_0`, `_chunk_1`)
- Preempt chunk_0 после prefilling chunk_1
- При attention forward на decode — promote chunks дополнительно

Это **chunked prefill через explicit chunking**. Архитектурно новый
flow, не drop-in patch.

## Альтернативные подходы (если Phase 7 не реализуем)

### Alt 1: Use smaller model

`Qwen3-7B-INT4` ≈ 4 GB weights → 19 GB available KV → **~1.1M token
context theoretical**. Если qualиty приемлемое — простой win.

### Alt 2: TurboQuant 3-bit KV (TQ3)

KV size 17 KB/token → 10 KB/token (TQ3) → +60% context на той же
памяти. Reference: club-3090 #119 head-to-head — 27B + TQ3 + MTP
работает на dual 3090 до 262K. На single A5000 = ~163K theoretical.

Limitations:
- TQ3 + hybrid GDN (Qwen3.6) требует наш P67 multi-query kernel ✓
- TQ3 quality penalty ~4pp (per TQ paper)
- Workspace lock issue (наш SNDR-WORKSPACE-001 ловит)

**Это лучший pragmatic путь** для 156K на single card СЕЙЧАС.

### Alt 3: vllm chunked-prefill через PN95 endpoint

Custom OpenAI-API endpoint `/v1/chat/completions/chunked`:
1. Принимает >100K context
2. Делает sliding-window summarization client-side
3. Posts 80K window к vllm internally
4. Reassembles response

Это application-layer fix, не engine fix. Works для агентов / Q&A.
Не works для needle-in-haystack где attention к full 156K нужен.

### Alt 4: 2-card config

Уже works: 2×A5000 + 200K (225K real) proven. Если user может позволить
себе 2 карты — 156K already available.

## Recommendation

**Краткосрочно (этот sprint):**
- VIRT=0 default, **honest 100K cap** single-card
- PN96 emergency-rescue для multi-prefix workloads (`GENESIS_ENABLE_PN96_EMERGENCY_DEMOTE=1`)
- 2×A5000 production = 200K already proven

**Среднесрочно (Phase 7, ~4-8 недель):**
- Anchor #10 (tensor shape cap) — самый short-term win
- Block_id translation layer (новый text-patch in attention kernel
  binding) — требует deep Triton/CUDA знания
- Self-preemption через chunked request — requires scheduler refactor

**Альтернатива среднесрочно (3-5 дней):**
- TQ3 KV format на single card — 156K through quantization
  (quality tradeoff)
