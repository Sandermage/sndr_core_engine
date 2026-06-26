# SPDX-License-Identifier: Apache-2.0
"""Latency of vLLM's moe_wna16 path for the Gemma-4-26B-A4B MoE shape.

This is the *competitor* side of the TurboMind int4 A/B. It times the full
fused MoE (w1w3 + silu + w2) via ``fused_experts_impl`` with ``use_int4_w4a16``,
which dispatches to the CUDA ``moe_wna16_gemm`` kernel at decode batch sizes
(``should_moe_wna16_use_cuda``: tokens/experts <= 6). Random int4 weights are
fine — moe_wna16 latency depends only on shape/dtype, not values.

The TurboMind side is measured by ``test_gemm_v2`` ``Benchmark()`` on the rig
(see the repo README). Result (2x A5000, SM86, 2026-06-22):

    tokens  M     TurboMind int4 (w1w3+w2)   moe_wna16 full   speedup
       1    8           57.2 us                 187.4 us        3.3x
       4   32          159.2 us                 788.1 us        4.95x
      16  128          506.4 us                2354.3 us        4.65x
      64  512          701.7 us                4247.8 us        6.05x

Run inside the vLLM image on the rig:
    docker run --rm --gpus all --entrypoint bash \
      -v $(pwd)/bench/wna16_compare.py:/b.py:ro vllm/vllm-openai:nightly \
      -c "python3 /b.py"
"""

import time

import torch
from vllm.model_executor.layers.fused_moe.fused_moe import fused_experts_impl

E, HID, INTER, TOPK, G = 128, 2816, 704, 8, 32
PF = 2  # int4: two values per uint8
dev, dt = "cuda", torch.float16

w13_q = torch.randint(0, 255, (E, 2 * INTER, HID // PF), dtype=torch.uint8, device=dev)
w2_q = torch.randint(0, 255, (E, HID, INTER // PF), dtype=torch.uint8, device=dev)
w13_s = torch.randn(E, 2 * INTER, HID // G, dtype=dt, device=dev) * 0.01
w2_s = torch.randn(E, HID, INTER // G, dtype=dt, device=dev) * 0.01


def bench(M, iters=100, warmup=10):
    hs = torch.randn(M, HID, dtype=dt, device=dev)
    tw = torch.softmax(torch.randn(M, TOPK, device=dev), dim=-1).to(torch.float32)
    ti = torch.stack([torch.randperm(E, device=dev)[:TOPK] for _ in range(M)]).to(torch.int32)

    def run():
        return fused_experts_impl(
            hs, w13_q, w2_q, tw, ti, activation="silu", use_int4_w4a16=True,
            w1_scale=w13_s, w2_scale=w2_s, block_shape=[0, G], global_num_experts=E,
        )

    for _ in range(warmup):
        run()
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(iters):
        run()
    torch.cuda.synchronize()
    return (time.perf_counter() - t0) / iters * 1e6  # microseconds


if __name__ == "__main__":
    print(f"=== vLLM moe_wna16 full MoE (w1w3+silu+w2) Gemma-26B "
          f"E={E} hid={HID} inter={INTER} g{G} ===")
    for m in (1, 4, 16, 64):
        us = bench(m)
        nvt = m * TOPK
        path = "CUDA" if nvt / E <= 6 else "Triton"
        print(f"  tokens={m:4d}  M*topk={nvt:5d}  latency={us:8.2f} us  ({path} path)")
