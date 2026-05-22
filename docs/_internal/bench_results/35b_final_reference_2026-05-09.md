# Genesis Bench Run — quick_2026-05-08T23-58-03Z

- **Started:** 2026-05-08T23:58:03Z
- **Mode:** quick
- **Server:** 127.0.0.1:8000  Model: `qwen3.6-35b-a3b`
- **Local GPUs detected:**
  - GPU 0: NVIDIA RTX A5000  VRAM 21954/24564 MiB  BW≈768 GB/s  CC 8.6
  - GPU 1: NVIDIA RTX A5000  VRAM 21954/24564 MiB  BW≈768 GB/s  CC 8.6

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
- **wall_TPS** mean **233.8412**  CV 0.063  n=25
- **decode_TPOT_ms** mean **3.9582**  CV 0.0502
- TTFT_ms mean 110.9  CV 0.3295

## Multi-turn TTFT (cache benefit smell test)

- turn 1: TTFT 148.1ms  elapsed 0.331s
- turn 2: TTFT 139.4ms  elapsed 0.324s
- turn 3: TTFT 139.0ms  elapsed 0.322s
- turn 4: TTFT 134.7ms  elapsed 0.319s
- turn 5: TTFT 140.6ms  elapsed 0.318s

## Context window probe

**Max stable context:** none

| Target | prompt_tokens | elapsed_s | prefill_tps_est | Verdict |
|---|---|---|---|---|

---

Genesis Benchmark Suite v1.0 · Apache-2.0 · 
https://github.com/Sandermage/genesis-vllm-patches