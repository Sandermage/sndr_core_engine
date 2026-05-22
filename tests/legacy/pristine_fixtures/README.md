# Pristine vLLM source fixtures

Snapshots of upstream vLLM source files at known pristine pin, used by
build-time anchor validation tests (`test_patcher_anchors_invariants.py`).

## Pin

- PN79 fixtures: vllm `0.20.2rc1.dev93+g51f22dcfd` (extracted 2026-05-07)
- PN33+PN35 fixtures: vllm `0.20.2rc1.dev209+g5536fc0c0` (extracted 2026-05-12)

These files were extracted from `vllm/vllm-openai:nightly` Docker image
at the noted pin. 3 of 4 PN79 files are bit-identical to dev9 / dev60
(chunk.py, chunk_delta_h.py, olmo_hybrid.py — kernel files unchanged
across 84+ dev versions). Only `gdn_linear_attn.py` shifted in dev93
(commit #33 added CPU GDN attention dispatch + reshape contiguity fix).

## Files

| File | MD5 | Lines | Purpose |
|---|---|---|---|
| chunk.py | 0f66320b6b74a11d7b4f3e7ea223ecec | 234 | FLA chunk_gated_delta_rule wrapper (PN79 Sub-1 target) |
| chunk_delta_h.py | e90e9a46606fadcf22cf5f8425f0f490 | 361 | Triton kernel chunk_gated_delta_rule_fwd_kernel_h_blockdim64 (PN79 Sub-2 target) |
| gdn_linear_attn.py | a0ef142d6edf8f65fd1ef444f64ddb1f | 1234 | GDN linear attention with forward_cuda/forward_native/_forward_core (PN79 Sub-3 target) |
| olmo_hybrid.py | 63ab5a2d29b29b522693188a8da2e421 | 1179 | Olmo-Hybrid model with `_forward_core` gather/scatter pattern (PN79 Sub-4 target) |
| gpu_model_runner.py | ac61702177b286d0d7239050fd07cbbc | 7179 | v1 worker GPU model runner (PN33.Sub-1 + PN35.Sub-1 targets) |
| llm_base_proposer.py | b2b5def581d27d4654e66d83b4ff4998 | 1638 | v1 spec-decode LLM base proposer (PN35.Sub-2 target) |

## Update procedure

When upgrading the pristine pin (rare — only when an anchor genuinely no
longer matches because upstream refactored the touched region):

1. Pull the new file from a clean docker container:
   ```
   docker cp <container>:/usr/local/lib/python3.12/dist-packages/vllm/<rel_path> ./<filename>
   ```
2. Update the MD5 + line count table above.
3. Update `genesis_pin` in `anchor_manifest.json` (when Site Map P2.1 lands).
4. Re-run anchor invariant tests — they will catch broken anchors.

## What these fixtures DO NOT do

- They are NOT runtime targets. The patcher targets vllm install root via
  `resolve_vllm_file()`. These are TEST fixtures only.
- They DO NOT replace the need for live integration testing. The patcher's
  apply path against real vllm install is still the ground truth — fixtures
  catch drift early in CI but cannot guarantee runtime correctness.
- They are NOT auto-updated. Manual update on pin change.
