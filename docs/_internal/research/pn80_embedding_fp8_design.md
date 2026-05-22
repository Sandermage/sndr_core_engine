# PN80 R&D — embedding FP8 compression design

**Status:** RESEARCH ONLY (2026-05-06). No implementation. Document is the
record of decisions + open questions for a future dedicated session.

## Problem statement

After PN77 successfully compressed `lm_head` (ParallelLMHead) to FP8 on 35B
PROD (+6.4% TPS, ~242 MiB/rank saving via Marlin tier), the natural extension
is the **input embedding** (VocabParallelEmbedding). On Qwen3.6 + Gemma 4
models the embedding matrix is the same size or LARGER than lm_head. If we
can compress it equivalently, we'd see an additional ~242–635 MiB/rank
savings depending on hidden_size.

## Architectural mismatch — why this isn't trivial

`lm_head` is a **GEMM** (`hidden × vocab` projection):
```
logits[b, vocab] = hidden[b, hidden] @ lm_head_weight[hidden, vocab]
```
This is amenable to:
- Marlin (FP8/INT4 weight-only GEMM)
- scaled_mm (native FP8 GEMM on Hopper+)
- cast-back fallback (decompress on every call — slow but correct)

`embedding` is a **gather/scatter** (`vocab[token_idx]`):
```
hidden[b] = embedding_weight[token_ids[b], :]
```
This is NOT a GEMM. There's no Marlin-equivalent kernel for FP8 storage +
gather. The options are:

| Strategy | Mechanics | Cost per call | Quality |
|---|---|---|---|
| **A: dequant-on-lookup** | Store FP8, decompress to bf16 inside `forward()` | O(B × hidden) — small | exact (bit-for-bit on integer ops) |
| **B: native FP8 lookup** | Custom Triton kernel: gather FP8 + cast to bf16 in-kernel | O(B × hidden), single launch | exact |
| **C: leave bf16** | Skip compression entirely | 0 | - |
| **D: dedicated compressed-embedding path** | Run forward in FP8, never decompress | impossible — downstream layers need bf16 | - |

Option D is dead — embedding output feeds layer-norm + first transformer
layer, both bf16. Option A is straightforward but adds B*hidden*2 bytes per
call. Option B is the right answer but requires custom Triton.

## Per-model sizing

### Qwen3.6-35B-A3B-FP8 (current PROD)
- vocab_size: 248320
- hidden_size: 2048
- tie_word_embeddings: False (lm_head ≠ embedding)
- embedding bf16 footprint: 248320 × 2048 × 2 = **968 MiB**
- TP=2 split (vocab axis): **484 MiB/rank**
- After FP8 (1 byte/elem): **242 MiB/rank**
- **Saving: 242 MiB/rank** (matches PN77 lm_head saving exactly)

### Qwen3.6-27B-int4-AutoRound (Hybrid GDN)
- vocab_size: 248320
- hidden_size: 5120 (2.5× 35B)
- tie_word_embeddings: False
- embedding bf16 footprint: 248320 × 5120 × 2 = **2.42 GiB** (note: AutoRound
  typically does NOT quantize embedding — stays bf16)
- TP=2 split: **1.21 GiB/rank**
- After FP8: **606 MiB/rank**
- **Saving: 606 MiB/rank** = ~1.2 GiB total

### Gemma 4 26B-A4B-it-AWQ-4bit (sparse MoE)
- vocab_size: 262144
- hidden_size: 2816
- **tie_word_embeddings: True** ← embedding shared with lm_head
- embedding bf16 footprint: 262144 × 2816 × 2 = **1.41 GiB** (just one matrix
  used as both lookup AND output projection)
- TP=2: **704 MiB/rank**
- After FP8: **352 MiB/rank**
- **Saving: 352 MiB/rank** — but on Gemma 4 the lookup AND projection are
  the SAME tensor (tied), so PN77 already saves it via lm_head path. PN80
  on tied models is redundant unless we're explicitly choosing dequant-on-
  lookup for quality reasons.

### Gemma 4 31B-it-int4-AutoRound (dense)
- vocab_size: 262144
- hidden_size: 5376
- **tie_word_embeddings: True**
- Footprint: 262144 × 5376 × 2 = **2.69 GiB**
- TP=2: **1.34 GiB/rank**
- Same tied-embedding observation as 26B.

**Summary of opportunity:**
- Untied models (Qwen3.6-A3B / 27B) — full PN80 win
- Tied models (Gemma 4) — PN77 already covers; PN80 only relevant if
  embedding lookup quality is concern

## Quality risk assessment

Embedding lookup is on the EVERY forward pass critical path. Any quantization
error compounds through 30-60 transformer layers. Empirical evidence from
literature:

- FP8 e4m3 on weights typically <0.1 perplexity hit on instruction-tuned models
- BUT: embedding precision is more sensitive than weight precision —
  small errors in embedding propagate through residual stream
- Real-world reports (from W8A8 / FP8 weight-only quantization papers) put
  embedding-only FP8 quality regression at 0–0.5% on LM-eval benchmarks
- This is small but **measurable** — and our PROD criterion is **10/10
  tool-call quality**, which is sensitive to nuanced token decisions

**Mitigation strategies (in order of preference):**
1. **Per-row scaling** — same as PN77: store FP8 + per-row fp32 scale; cost
   is one extra multiply on lookup, near-zero quality loss
2. **Selective compression** — compress only ranges of vocab not used in
   tool-call grammar tokens (preserve precision on `<tool_call>`,
   `<function=`, `<parameter=`, etc.)
3. **A/B gate** — run with PN80 for 1000-prompt eval suite, compare
   tool-call score, abort promotion if any regression
4. **Operator opt-in only** — never default-on; document quality risk
   explicitly

## Implementation sketch (NOT yet committed)

```
# vllm/sndr_core/kernels/embedding_fp8_method.py

class Genesis_FP8_VocabEmbeddingMethod:
    """Duck-typed protocol matching VocabEmbeddingMethod interface.
    Stores layer.weight as packed FP8 + per-row fp32 scale; on forward()
    does lookup + dequant via Triton kernel."""

    def process_weights_after_loading(self, layer):
        # 1. Quantize layer.weight to FP8 (e4m3) + extract per-row scales
        # 2. replace_parameter() with FP8 weight + companion scale tensor
        # 3. Set marker `_genesis_pn80_fp8 = True`

    def forward(self, layer, input_ids):
        # Triton kernel: gather FP8 row, multiply by scale, cast to bf16
        return triton_fp8_gather(
            weight_fp8=layer.weight,
            scales=layer.scales,
            indices=input_ids,
            out_dtype=torch.bfloat16,
        )
```

Triton kernel design (per-token, per-hidden-element parallelism):
```
@triton.jit
def fp8_embedding_lookup_kernel(
    fp8_weight_ptr,   # (vocab × hidden), torch.float8_e4m3fn
    scales_ptr,       # (vocab,), torch.float32
    token_ids_ptr,    # (B,), torch.int64
    output_ptr,       # (B × hidden), torch.bfloat16
    B: tl.constexpr,
    HIDDEN: tl.constexpr,
    BLOCK_HIDDEN: tl.constexpr,
):
    pid_b = tl.program_id(0)
    pid_h = tl.program_id(1)
    token_id = tl.load(token_ids_ptr + pid_b)
    scale = tl.load(scales_ptr + token_id)

    h_offsets = pid_h * BLOCK_HIDDEN + tl.arange(0, BLOCK_HIDDEN)
    h_mask = h_offsets < HIDDEN

    fp8_vals = tl.load(
        fp8_weight_ptr + token_id * HIDDEN + h_offsets,
        mask=h_mask,
    )
    bf16_vals = (fp8_vals.to(tl.float32) * scale).to(tl.bfloat16)
    tl.store(output_ptr + pid_b * HIDDEN + h_offsets, bf16_vals, mask=h_mask)
```

Open questions:
- Triton FP8 → fp32 cast intrinsic — verify works on Ampere SM 8.6
  (FP8 dtype is technically Hopper-only; needs `torch.float8_e4m3fn` runtime
  conversion)
- How does this interact with PN77 lm_head when both apply (untied models)?
  Two separate compressions, no shared scale tensor — should work but tested.
- Vocab-parallel sharding — embedding is split across TP ranks on vocab axis;
  scales tensor needs same sharding
- LoRA / multi-LoRA path — these dynamically modify embedding; PN80 should
  refuse to apply if LoRA detected

## Decision: deferred to dedicated session

This is a real R&D project, not a "evening edit". To do it properly:

1. **Day 1 (4h):** kernel research + Ampere FP8 dtype experiments
2. **Day 2 (4h):** TDD scaffold + first kernel implementation
3. **Day 3 (4h):** integration with VocabParallelEmbedding + replace_parameter
4. **Day 4 (4h):** quality eval suite (1000 prompts, full LM-eval lite)
5. **Day 5 (4h):** A/B bench on 27B PROD, decision on default-OFF/ON

Total: ~20 hours real work. Out of scope for this evening.

## Alternative paths that DON'T need PN80

Since PN80 is heavy work, what's available NOW?

1. **gpu_memory_utilization tweak** — if PN77 freed 242 MiB/rank, raise
   gpu_memory_utilization 0.90 → 0.92 to reclaim. Free, no code, immediate
2. **Pool_budget full wire-up (W-2)** — gives operator EXPLICIT memory caps
   without requiring compression. Less dramatic but lower risk
3. **Lower max_num_seqs** — frees KV cache, tradeoff for concurrency
4. **PN59 streaming threshold reduction** — already documented; covers
   long-ctx single-seq case

Most of the memory pressure on 27B PROD is KV cache, NOT weights. Compressing
weights only helps if they're the binding constraint, which they may not be.

## Decision matrix — when PN80 vs alternatives

| Scenario | Right answer | Reason |
|---|---|---|
| 35B PROD on 24 GiB cards | Already optimal — keep PN77, raise util | weights aren't binding |
| 27B + long-ctx 256K | PN80 might help (frees 1.2 GiB total) | KV is binding, less weight = more KV pool |
| 27B + max-num-seqs 4-8 | Pool_budget caps preferred over PN80 | concurrency binding, weight ≪ KV |
| Future 70B on 2× 24 GiB | PN80 essential | weights ARE binding |
| Tied-embedding models (Gemma 4) | PN77 already covers | redundant |

**Conclusion:** PN80 is the right tool for **untied-embedding models on
binding-weight scenarios**, primarily 27B+long-ctx and future ≥70B models.
For our current 35B + 27B + Gemma 4 fleet, the lower-effort alternatives
(util tweak, pool_budget caps) cover most cases.

## What would unlock priority

PN80 should be picked up when:
- A new 70B+ untied-embedding model lands and weight VRAM becomes binding
- OR a community member contributes the FP8-lookup Triton kernel
- OR Gemma 4 untied variants ship

Until then: **deferred, R&D-documented, no code committed.**

## References

- PN77 implementation: `vllm/sndr_core/kernels/lm_head_fp8_method.py`
- PN77 wiring: `vllm/sndr_core/wiring/loader/patch_N77_fp8_lm_head.py`
- vLLM FP8 weight-only docs: https://docs.vllm.ai/en/latest/features/quantization/fp8.html
- Triton FP8 examples: https://github.com/triton-lang/triton/tree/main/python/tutorials
- W8A8 quality literature: review LM-eval ablations on FP8/INT8 weight-only

Author: Sandermage research notes 2026-05-06.
