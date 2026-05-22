# Genesis Bench Run — pn125_on_5run

- **Started:** 2026-05-15T01:11:16Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-35b-a3b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 22292/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 21603/24564 MiB  BW≈768 GB/s  CC 8.6

## Decode bench

- runs=5 prompts=5 max_tokens=384
- **wall_TPS** mean **205.4284**  CV 0.1107  n=25
- **decode_TPOT_ms** mean **4.4853**  CV 0.1469
- TTFT_ms mean 120.292  CV 0.3052

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches