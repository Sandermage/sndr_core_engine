# Genesis Bench Run — all_PN12X_active

- **Started:** 2026-05-15T14:31:02Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-35b-a3b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 22635/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 21948/24564 MiB  BW≈768 GB/s  CC 8.6

## Decode bench

- runs=5 prompts=5 max_tokens=384
- **wall_TPS** mean **158.2676**  CV 0.064  n=25
- **decode_TPOT_ms** mean **5.9192**  CV 0.0622
- TTFT_ms mean 115.388  CV 0.3416

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches