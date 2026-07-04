# PN521 split-K / raw-tail dev tooling

Opt-in developer tooling for the **PN521 / PN521_SPLIT_K** TurboQuant raw-bf16-tail
spec-verify work (the INT4 non-pow2-GQA Qwen3.6-27B AutoRound MTP collapse fix).
Gathered verbatim from the rig on 2026-07-04 so the canonical repo carries the
reproducible validation + tuning harness for those patches.

**These are NOT part of the default `pytest` run** (they live under `tools/`, not
`tests/`, and `testpaths = ["tests"]`). They import `triton` + `vllm` and assume the
live 27B kernel geometry (GQA=24/4=6, head_dim=256, sm_86), so run them explicitly
on the rig with a CUDA vLLM install:

```bash
python -m pytest tools/pn521/test_splitk_e2e.py -q      # on the rig, GPU present
python tools/pn521/bench_splitk.py                       # split-K vs single-CTA latency
```

## Contents

| File | What it validates / measures |
|---|---|
| `test_pn521_raw_tail.py`  | raw-bf16-tail spec-verify numeric equivalence (Triton == torch bf16-causal reference) |
| `test_splitk_e2e.py`      | split-K stage1→stage2 end-to-end vs bf16 causal ground truth |
| `test_splitk_prior.py`    | committed-split == single-CTA at `prior_seq_len > 0` |
| `test_stage2.py`          | stage-2 log2 LSE-combine correctness |
| `bench_pn521_config.py`   | which `(BLOCK_KV, num_stages)` fit sm_86 SMEM at the 27B raw-tail geometry |
| `bench_splitk.py`         | split-K vs single-CTA latency (the rationale for the split-K grid on the 64-SM A5000) |

The 4 ad-hoc profiling scratch scripts (`conc_load.py`, `inproc_profile.py`,
`offline_gen.py`, `offline_profile.py`) were intentionally **not** gathered — they are
throwaway probes with hardcoded `/tmp` paths and no assertions; they remain captured
in the rig snapshot bundle if ever needed.
