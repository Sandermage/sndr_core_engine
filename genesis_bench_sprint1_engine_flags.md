# Genesis Bench Run — sprint1_engine_flags

- **Started:** 2026-05-15T16:06:23Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-35b-a3b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 22503/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 21814/24564 MiB  BW≈768 GB/s  CC 8.6

## Decode bench

- runs=5 prompts=5 max_tokens=384
- **wall_TPS** mean **205.7476**  CV 0.1206  n=25
- **decode_TPOT_ms** mean **4.5137**  CV 0.1851
- TTFT_ms mean 120.036  CV 0.3507

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches