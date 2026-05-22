# Genesis Bench Run — quick_2026-05-14T22-35-11Z

- **Started:** 2026-05-14T22:35:11Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-27b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 22525/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 22315/24564 MiB  BW≈768 GB/s  CC 8.6

## Decode bench

- runs=5 prompts=5 max_tokens=1024
- **wall_TPS** mean **133.9108**  CV 0.0376  n=25
- **decode_TPOT_ms** mean **7.2239**  CV 0.0395
- TTFT_ms mean 105.348  CV 0.1012

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches