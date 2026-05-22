# PN95 — сравнительный research vs LMCache / SGLang HiCache / vLLM v1 kv_offload

Дата: 2026-05-13. Цель — извлечь lessons из других inference-стеков для
дальнейших улучшений PN95 (Path C tier-aware KV cache с CPU offload и
boot-time KV pool expansion).

## Что изучено

| Стек | Файлы | Что взято |
|---|---|---|
| LMCache (8.3k★) | `lmcache/v1/memory_management.py`, `cache_engine.py`, `config.py` | unified memory abstraction, paged allocator, pin/ref counting |
| SGLang HiCache (27.7k★) | `python/sglang/srt/mem_cache/memory_pool_host.py`, `hi_mamba_radix_cache.py` | dedicated MambaPoolHost class, layout-aware transfer backends, HOST_MEMORY_RESERVE_BYTES safety margin |
| vLLM v1 offload (79.8k★) | `v1/kv_offload/base.py`, `v1/kv_offload/cpu/`, `distributed/kv_transfer/kv_connector/v1/ssm_conv_transfer_utils.py` | новый OffloadingManager / LoadStoreSpec / OffloadingSpec framework, SSM transfer utils для RDMA |

## Ключевые insights

### Insight 1 — Mamba требует выделенной обработки (PN95 design validated)

- **SGLang HiCache** имеет специализированные классы: `MHATokenToKVPoolHost`,
  `MLATokenToKVPoolHost`, **`MambaPoolHost`**, `NSAIndexerPoolHost`.
  Mamba получает свой собственный pool с отдельным управлением temporal +
  convolution state buffers.
- **vLLM upstream `ssm_conv_transfer_utils.py`** (новый код) делает 3-read
  transfer mechanism для distributed RDMA — НО НЕ для CPU offload.
  Upstream offload framework только "align hybrid models through prefix
  caching", без semantic separation.
- **LMCache** трактует все KV как generic tensors — **не имеет специальной
  Mamba логики**.

**Вывод:** PN95's MambaSpec filtering — уникальная Genesis innovation,
которая правильна по design. LMCache + upstream vllm offload бы крашились
на hybrid-GDN моделях. SGLang validates подход через dedicated pool.

### Insight 2 — Multi-tier нужен AddressManager (PN95 gap)

- **LMCache** `AddressManager` использует `SortedList` для explicit
  free-list + coalescing на освобождении. `PagedTensorMemoryAllocator`
  даёт O(1) operations через deque для fixed-page case.
- **PN95** сейчас: CPU slab = `torch.empty(pin_memory=True)` единым
  блоком. Demote/promote — bookkeeping only, no actual byte movement yet.
- Когда Phase 5 anchor #10 wire-in активируется → нужно реальное
  размещение пользовательских блоков в CPU slab → fragmentation control
  становится критичным.

**Действие:** для будущего Phase 5 implement — заимствовать
AddressManager-style free-list + coalescing. Сейчас фиксируется как
design note.

### Insight 3 — HOST_MEMORY_RESERVE_BYTES safety margin (immediate improvement)

- **SGLang** `HICACHE_HOST_MEMORY_RESERVE_BYTES` = 10 GiB safety margin —
  pre-allocation validates against available host RAM с буфером.
  Защищает от OOM хоста.
- **PN95** сейчас принимает `cpu_capacity_gib` from config без host RAM
  validation. Оператор может задать значение, превышающее реальную
  host capacity → CPU OOM при первом allocation.

**Действие (можно сейчас):** добавить opt-in env переменную
`GENESIS_PN95_HOST_RESERVE_GIB` (default 8 GiB) — при `init_from_config`
вычитать reserve из доступной host RAM и кепить cpu_capacity_gib.

### Insight 4 — Pin/ref counting защищает in-flight blocks (PN95 gap)

- **LMCache** имеет `pin_count` для temporary holds и `ref_count` для
  allocation tracking. Pinned objects не evict-ятся; PinMonitor отслеживает
  timeout pins.
- **PN95** сейчас demote candidate selection не учитывает блоки в active
  use во worker'е. Если scheduler решит demote, а worker одновременно
  читает блок — race condition, потенциальный crash.

**Действие:** в `TierManager.demote_candidates` ввести concept "active
blocks" — те, которые worker зарегистрировал как in-flight за последние
N ticks. Эти блоки skip из candidate list. Реализация — простой `set`
+ TTL.

### Insight 5 — Layout-aware transfer kernels (SGLang innovation, optional)

- **SGLang** поддерживает 3 transfer backends:
  - `"kernel"` — optimized JIT kernels
  - `"direct"` — raw memory copy
  - `"kernel_ascend"` — NPU-specific
  и 3 layouts: `"layer_first"`, `"page_first"`, `"page_first_direct"`
- **PN95** сейчас: один async stream, simple `tensor.cpu()` copy.

**Действие:** не критично. Defer до GPU bench session. Сейчас фиксируется
как future improvement.

### Insight 6 — Upstream vLLM v1 offload framework (compatibility risk)

- vLLM upstream **активно разрабатывает** свой offload framework:
  `v1/kv_offload/base.py` определяет `OffloadingManager` /
  `LoadStoreSpec` / `OffloadingSpec`. Block-based с `block_size_factor`
  для multi-tier; LRU через `touch()`.
- Дизайн похож на PN95 (`TierManager.notify_admit/touch`), но upstream
  не имеет Mamba-aware filtering.

**Compatibility risk:** если оператор включит upstream offload connector
ОДНОВРЕМЕННО с PN95, два manager'а будут конкурировать за те же blocks
→ undefined behavior.

**Действие:**
1. Сейчас (immediate): добавить в PN95 boot-time check — если
   `cache_config.kv_transfer_config` указывает на upstream offload
   connector → log warning + skip PN95 init (don't double-manage).
2. Long-term: реализовать PN95 как `OffloadingSpec` implementation,
   чтобы интегрироваться в upstream framework. Это переводит PN95 из
   text-patch overlay в clean upstream extension — но требует upstream
   framework stabilization (он сейчас active development).

## Сводка действий

### Immediate (this session — implementable без GPU validation)

1. ✅ Document research → этот файл
2. **HOST_MEMORY_RESERVE_BYTES safety margin** — добавить env
   `GENESIS_PN95_HOST_RESERVE_GIB` + validation в `init_from_config()`.
   Cap cpu_capacity if exceeds (host_total - reserve).
3. **In-flight block protection** — `TierManager.mark_active(block_id)` /
   `is_active(block_id, ttl_ticks)` API. `demote_candidates` фильтрует
   active blocks.
4. **Upstream offload compatibility check** — boot-time warning +
   conditional skip если upstream offload connector detected.
5. **Unit tests** для каждого нового item.

### Deferred (requires live GPU box)

- Phase 5 anchor #10 — KVCacheTensor physical num_blocks cap text-patch
  wire-in (helper `pn95_physical_num_blocks_cap()` готов).
- Real demote/promote byte movement validation на 24 GiB single-A5000.
- Layout-aware transfer kernels (layer_first / page_first).

### Long-term (design / refactor)

- AddressManager-style free-list for CPU tier (когда demote реально
  движет байты).
- Refactor PN95 как `OffloadingSpec` implementation, чтобы прибиться
  к upstream framework, когда тот стабилизируется.

## Сравнительная матрица (резюме)

| Feature | LMCache | SGLang HiCache | vLLM v1 offload (upstream WIP) | **PN95 (Genesis)** |
|---|---|---|---|---|
| Unified memory abstraction | ✅ MemoryObj | ✅ HostPoolGroup | ✅ LoadStoreSpec | partial (TierManager) |
| Paged allocator | ✅ | slot-based | block-based + `block_size_factor` | block-based |
| Mamba-aware separation | ❌ | ✅ MambaPoolHost | ❌ (alignment-only) | ✅ MambaSpec filter (unique) |
| MM/vision sub-tier | ❌ | ❌ | ❌ | ✅ (PN95 drains MM first) |
| Eviction policy ABC | ❌ (fixed LRU) | callback-only | ✅ (touch + complete_store) | ✅ (LRU/2Q/ARC via PN91) |
| Pin/ref counting | ✅ | RLock-based | implicit via prepare/complete | ❌ (planned) |
| Host RAM safety margin | ❌ | ✅ 10 GiB reserve | ❌ | ❌ (planned) |
| Distributed (RDMA) | ✅ | ✅ | ✅ NIXL | ❌ (out of scope) |
| Boot-time KV expansion | ❌ | ❌ | ❌ | ✅ (Phase 5 Anchor #9) |
| Upstream upstream-compat | n/a | n/a | n/a | gap (planned: warn + skip) |

**Резюме:** PN95 уникально решает три проблемы, которые ни один
конкурент не решает:
1. Mamba SSM exclusion (LMCache+upstream offload upstream бы крашились)
2. MM/vision sub-tier prioritization
3. Boot-time KV pool expansion

Но имеет три gaps относительно competitors, легко закрываемые в этой
сессии: host RAM safety margin, in-flight protection, upstream
compatibility check.
