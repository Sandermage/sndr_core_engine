# Genesis Bench Run — quick_2026-05-14T19-25-05Z

- **Started:** 2026-05-14T19:25:05Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-35b-a3b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 22197/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 21987/24564 MiB  BW≈768 GB/s  CC 8.6

## Decode bench

- runs=5 prompts=5 max_tokens=1024
- **wall_TPS** mean **219.4088**  CV 0.0644  n=25
- **decode_TPOT_ms** mean **4.2522**  CV 0.039
- TTFT_ms mean 113.96  CV 0.3493

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches