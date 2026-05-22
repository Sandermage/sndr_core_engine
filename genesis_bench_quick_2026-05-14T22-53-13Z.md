# Genesis Bench Run — quick_2026-05-14T22-53-13Z

- **Started:** 2026-05-14T22:53:13Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-35b-a3b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 22025/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 22025/24564 MiB  BW≈768 GB/s  CC 8.6

## Decode bench

- runs=5 prompts=5 max_tokens=1024
- **wall_TPS** mean **216.1572**  CV 0.1062  n=25
- **decode_TPOT_ms** mean **4.3288**  CV 0.0731
- TTFT_ms mean 115.232  CV 0.3533

## Context window probe

**Max stable context:** 32K

| Target | prompt_tokens | elapsed_s | prefill_tps_est | Verdict |
|---|---|---|---|---|
| 8K | 4056 | 1.16 | 4457.1 | PASS |
| 16K | 8152 | 1.79 | 5293.5 | PASS |
| 32K | 16344 | 2.84 | 6310.4 | PASS |

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches