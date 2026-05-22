# Genesis Bench Run — baseline_5run_v2

- **Started:** 2026-05-15T00:51:35Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-35b-a3b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 22737/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 22527/24564 MiB  BW≈768 GB/s  CC 8.6

## Decode bench

- runs=5 prompts=5 max_tokens=384
- **wall_TPS** mean **212.6768**  CV 0.0648  n=25
- **decode_TPOT_ms** mean **4.2909**  CV 0.0651
- TTFT_ms mean 112.76  CV 0.3327

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches