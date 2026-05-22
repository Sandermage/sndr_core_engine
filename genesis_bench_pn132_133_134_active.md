# Genesis Bench Run — pn132_133_134_active

- **Started:** 2026-05-15T14:25:43Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-35b-a3b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 22915/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 22228/24564 MiB  BW≈768 GB/s  CC 8.6

## Decode bench

- runs=5 prompts=5 max_tokens=384
- **wall_TPS** mean **212.6108**  CV 0.0803  n=25
- **decode_TPOT_ms** mean **4.3134**  CV 0.0639
- TTFT_ms mean 110.512  CV 0.3521

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches