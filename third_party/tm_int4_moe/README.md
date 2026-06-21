# tm_int4_moe — vendored TurboMind sm80_16816 int4 grouped-MoE GEMM

Phase 2 of the 26B MoE speed work (see
`docs/superpowers/specs/2026-06-22-turbomind-int4-moe-port.md`).

## What this is
A minimal vendor of TurboMind's (LMDeploy) hand-written `sm80_16816`
tensor-core int4 grouped-MoE GEMM kernel, to be JIT-compiled (via
`torch.utils.cpp_extension`) and wired into vLLM as a custom op that
replaces the slow CUDA-core `moe_wna16_gemm` for Marlin-ineligible int4
MoE shapes (Gemma-4-26B-A4B at TP=2: N=352%64≠0, group_size=32).

## Source & license
- Upstream: **`InternLM/lmdeploy`** @ `main` (HEAD 3c00e811), path
  `src/turbomind/kernels/gemm/`.
- License: **Apache-2.0** (same as Genesis). Vendored files retain their
  original SPDX headers. This is a vendored subset, not a fork.

## Why TurboMind (verified)
The only tensor-core int4-MoE kernel that (a) runs on SM86, (b) **tolerates
K=352** (its 16×8×32 MMA tile + offline weight repack, where Marlin's hard
`thread_k∈{64,128}` rejects), (c) **supports group_size=32** (confirmed in
`gemm/kernel/sm80_16816_4.cu:82` — `register_u4_g(integral_constant<int,32>)`),
(d) is **CUTLASS-free** (hand-written multistage). Measured +134-220% over
FP16 on M=1-16 decode, +19% over Marlin (A100, arXiv:2508.15601) — pending
A5000 re-bench.

## Vendint status
- [x] `gemm/gemm.h` — Gemm::Run API
- [x] `gemm/types.h` — POD descriptors (Operation, MatrixLayout, QuantDesc, Workspace)
- [x] `gemm/kernel/sm80_16816_4.cu` — g32 instantiation confirmed
- [ ] remaining ~25 files (see spec §"Vendor set") — gemm core, arch/sm80,
      convert/cast, moe_utils_v2, core/ headers, attention/quantization.h
- [ ] shim out `core::Tensor`/`core::Context`, stub sm70/75/90 registry,
      drop tuner (force `DispatchPolicy::kDefault`)
- [ ] mini-CMakeLists → `libtm_int4_moe.a` (CMAKE_CUDA_ARCHITECTURES=86)

## Build feasibility — PROVEN
`cpp_extension.load_inline` JIT-compiled+ran a CUDA op under `-arch=sm_86`
in the vLLM image (nvcc 13.0, torch 2.11) on the rig 2026-06-22. The full
kernel is multi-TU so it builds as a static lib + cpp_extension binding,
not a single-file JIT.

## Next (Phase 0 → 1 → 2)
See the spec's scaffold plan. Phase 0: finish vendint + shim + standalone
sm_86 build. Phase 1: cuBLAS reference + weight-repack byte-test (the
zero-point format is the critical risk). Phase 2: torch.ops custom op +
swap moe_wna16 + rig A/B vs moe_wna16 (speed) and FP16 (accuracy).
