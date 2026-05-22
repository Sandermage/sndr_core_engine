# Genesis Bench Run — ttft_opts_k1

- **Started:** 2026-05-15T13:31:05Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-35b-a3b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 22439/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 21770/24564 MiB  BW≈768 GB/s  CC 8.6

## Decode bench

- runs=5 prompts=5 max_tokens=384
- **wall_TPS** mean **150.1176**  CV 0.0382  n=25
- **decode_TPOT_ms** mean **6.2077**  CV 0.0184
- TTFT_ms mean 133.152  CV 0.0289

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches