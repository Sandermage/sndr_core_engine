# Genesis Bench Run — all_fp8_off

- **Started:** 2026-05-15T16:20:01Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-35b-a3b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 22913/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 22224/24564 MiB  BW≈768 GB/s  CC 8.6

## Decode bench

- runs=5 prompts=5 max_tokens=384
- **wall_TPS** mean **203.2668**  CV 0.0694  n=25
- **decode_TPOT_ms** mean **4.5184**  CV 0.0592
- TTFT_ms mean 115.436  CV 0.3454

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches