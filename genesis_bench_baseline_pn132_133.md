# Genesis Bench Run — baseline_pn132_133

- **Started:** 2026-05-15T14:44:24Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-35b-a3b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 22933/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 22244/24564 MiB  BW≈768 GB/s  CC 8.6

## Decode bench

- runs=5 prompts=5 max_tokens=384
- **wall_TPS** mean **160.8644**  CV 0.0619  n=25
- **decode_TPOT_ms** mean **5.8181**  CV 0.0559
- TTFT_ms mean 114.452  CV 0.3271

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches