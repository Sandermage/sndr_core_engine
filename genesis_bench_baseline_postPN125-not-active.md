# Genesis Bench Run — baseline_postPN125-not-active

- **Started:** 2026-05-15T00:50:59Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-35b-a3b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 22737/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 22527/24564 MiB  BW≈768 GB/s  CC 8.6

## Decode bench

- runs=3 prompts=5 max_tokens=256
- **wall_TPS** mean **205.188**  CV 0.0775  n=15
- **decode_TPOT_ms** mean **4.378**  CV 0.0651
- TTFT_ms mean 113.3933  CV 0.3776

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches