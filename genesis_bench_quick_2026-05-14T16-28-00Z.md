# Genesis Bench Run — quick_2026-05-14T16-28-00Z

- **Started:** 2026-05-14T16:28:00Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-35b-a3b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 21985/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 21985/24564 MiB  BW≈768 GB/s  CC 8.6

## Tool-call quality

**Pass:** 7/7 positive cases passed (negative cases scored separately)

| Case | Thinking | tool_name | args | Verdict |
|---|---|---|---|---|
| paris_no_think | False | `get_weather` | `{"city": "Paris"}` | PASS |
| tokyo_think | True | `get_weather` | `{"city": "Tokyo"}` | PASS |
| nyc_no_think | False | `get_weather` | `{"city": "New York"}` | PASS |
| london_think | True | `get_weather` | `{"city": "London"}` | PASS |
| kyiv_no_think | False | `get_weather` | `{"city": "Kyiv"}` | PASS |
| multi_no_think | False | `get_weather` | `{"city": "Berlin"}` | PASS |
| error_recovery | False | `get_weather` | `{"city": "Rome"}` | PASS |
| denial_no_think | False | `` | `` | PASS |

## Decode bench

- runs=5 prompts=5 max_tokens=1024
- **wall_TPS** mean **217.958**  CV 0.07  n=25
- **decode_TPOT_ms** mean **4.2621**  CV 0.0639
- TTFT_ms mean 114.8  CV 0.3395

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches