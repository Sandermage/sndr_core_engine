# Genesis Bench Run — no_prefix_yes_probabilistic

- **Started:** 2026-05-15T15:15:30Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-35b-a3b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 22913/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 22224/24564 MiB  BW≈768 GB/s  CC 8.6

## Decode bench

- runs=5 prompts=5 max_tokens=384
- **wall_TPS** mean **203.0004**  CV 0.0667  n=25
- **decode_TPOT_ms** mean **4.5498**  CV 0.0688
- TTFT_ms mean 107.46  CV 0.3424

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches