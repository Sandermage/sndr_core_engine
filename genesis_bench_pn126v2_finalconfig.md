# Genesis Bench Run — pn126v2_finalconfig

- **Started:** 2026-05-15T12:12:54Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-35b-a3b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 22912/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 22223/24564 MiB  BW≈768 GB/s  CC 8.6

## Decode bench

- runs=5 prompts=5 max_tokens=384
- **wall_TPS** mean **209.5268**  CV 0.0768  n=25
- **decode_TPOT_ms** mean **4.3654**  CV 0.0617
- TTFT_ms mean 115.648  CV 0.35

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches