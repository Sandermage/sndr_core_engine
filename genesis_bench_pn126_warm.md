# Genesis Bench Run — pn126_warm

- **Started:** 2026-05-15T11:47:19Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-35b-a3b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 22816/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 22127/24564 MiB  BW≈768 GB/s  CC 8.6

## Decode bench

- runs=5 prompts=5 max_tokens=384
- **wall_TPS** mean **197.5416**  CV 0.0727  n=25
- **decode_TPOT_ms** mean **4.6684**  CV 0.0615
- TTFT_ms mean 115.904  CV 0.3482

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches