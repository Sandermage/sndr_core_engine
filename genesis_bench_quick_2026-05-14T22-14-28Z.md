# Genesis Bench Run — quick_2026-05-14T22-14-28Z

- **Started:** 2026-05-14T22:14:28Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-35b-a3b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 22317/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 22107/24564 MiB  BW≈768 GB/s  CC 8.6

## Decode bench

- runs=5 prompts=5 max_tokens=1024
- **wall_TPS** mean **218.61**  CV 0.0651  n=25
- **decode_TPOT_ms** mean **4.2647**  CV 0.0482
- TTFT_ms mean 112.388  CV 0.3311

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches