# Genesis Bench Run — quick_2026-05-14T22-39-15Z

- **Started:** 2026-05-14T22:39:15Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-27b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 22705/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 22495/24564 MiB  BW≈768 GB/s  CC 8.6

## Decode bench

- runs=5 prompts=5 max_tokens=1024
- **wall_TPS** mean **131.976**  CV 0.0349  n=25
- **decode_TPOT_ms** mean **7.3481**  CV 0.0301
- TTFT_ms mean 104.608  CV 0.054

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches