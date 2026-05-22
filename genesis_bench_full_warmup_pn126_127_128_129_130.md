# Genesis Bench Run — full_warmup_pn126_127_128_129_130

- **Started:** 2026-05-15T12:58:06Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-35b-a3b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 22913/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 22224/24564 MiB  BW≈768 GB/s  CC 8.6

## Decode bench

- runs=5 prompts=5 max_tokens=384
- **wall_TPS** mean **210.4468**  CV 0.0724  n=25
- **decode_TPOT_ms** mean **4.3561**  CV 0.0688
- TTFT_ms mean 112.188  CV 0.3176

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches