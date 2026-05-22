# Genesis Bench Run — ctx_320K_full_restore

- **Started:** 2026-05-15T16:24:07Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-35b-a3b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 22493/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 21804/24564 MiB  BW≈768 GB/s  CC 8.6

## Decode bench

- runs=5 prompts=5 max_tokens=384
- **wall_TPS** mean **203.9228**  CV 0.1083  n=25
- **decode_TPOT_ms** mean **4.5547**  CV 0.1597
- TTFT_ms mean 118.428  CV 0.3205

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches