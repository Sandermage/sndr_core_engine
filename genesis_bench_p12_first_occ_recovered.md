# Genesis Bench Run — p12_first_occ_recovered

- **Started:** 2026-05-15T15:56:46Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-35b-a3b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 22935/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 22246/24564 MiB  BW≈768 GB/s  CC 8.6

## Decode bench

- runs=5 prompts=5 max_tokens=384
- **wall_TPS** mean **208.1044**  CV 0.102  n=25
- **decode_TPOT_ms** mean **4.4315**  CV 0.1034
- TTFT_ms mean 116.052  CV 0.3623

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches