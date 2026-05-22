# Genesis Bench Run — envs_only_pn125_off

- **Started:** 2026-05-15T01:16:21Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-35b-a3b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 22712/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 22023/24564 MiB  BW≈768 GB/s  CC 8.6

## Decode bench

- runs=5 prompts=5 max_tokens=384
- **wall_TPS** mean **207.1184**  CV 0.0896  n=25
- **decode_TPOT_ms** mean **4.4148**  CV 0.072
- TTFT_ms mean 118.94  CV 0.3382

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches