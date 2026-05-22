# Genesis Bench Run — quick_2026-05-14T17-05-02Z

- **Started:** 2026-05-14T17:05:02Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-35b-a3b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 21985/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 21985/24564 MiB  BW≈768 GB/s  CC 8.6

## Decode bench

- runs=5 prompts=5 max_tokens=1024
- **wall_TPS** mean **217.7904**  CV 0.084  n=25
- **decode_TPOT_ms** mean **4.29**  CV 0.0584
- TTFT_ms mean 111.868  CV 0.3231

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches