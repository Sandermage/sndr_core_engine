# Genesis Bench Run — quick_2026-05-14T20-10-34Z

- **Started:** 2026-05-14T20:10:34Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-27b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 22525/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 22315/24564 MiB  BW≈768 GB/s  CC 8.6

## Decode bench

- runs=5 prompts=5 max_tokens=1024
- **wall_TPS** mean **132.5472**  CV 0.0324  n=25
- **decode_TPOT_ms** mean **7.2527**  CV 0.0438
- TTFT_ms mean 118.116  CV 0.0621

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches