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
  original SPDX headers (`// Copyright (c) OpenMMLab. All rights reserved.`).
  This is a vendored subset, not a fork.

## Why vendored (and not a git submodule)
This stays a vendored copy, deliberately, rather than a `.gitmodules`
submodule:

1. **It is a curated subset, not the whole repo.** Only the dependency
   closure needed for the SM86 `sm80_16816` int4 grouped-MoE GEMM is
   vendored (`gemm/` + the `kernels/core/` headers + the high-level `core/`
   headers + a header-only `fmt`/`moodycamel`), explicitly *minus* `test/`,
   `sm90_64n32`, and `anomaly_handler` (see `build_kernels.sh`). A submodule
   would pull the entire LMDeploy tree, which the build does not want.
2. **The build assumes this exact in-repo layout.** `build_kernels.sh`
   compiles with `-I.` against the preserved `src/turbomind/...` include
   paths and a hand-listed object closure. A submodule's directory shape
   would not match these include roots without extra glue.
3. **The pin is a branch HEAD, not a release tag.** Upstream has no tagged
   release carrying this kernel at the needed state; pinning a submodule to a
   moving `main` HEAD (`3c00e811`) gives no stability benefit over recording
   the SHA here.

Consequence: the **`G4_85`** patch
(`sndr/engines/vllm/patches/moe/g4_85_tm_int4_moe_kernel.py`) depends on this
tree's layout — at runtime via `GENESIS_TM_INT4_MOE_DIR` (the tree is copied
to the rig and pre-built), and at build time via `build_kernels.sh`. Keeping
it vendored keeps that apply path intact. To refresh the vendor, re-copy the
subset from a newer LMDeploy SHA and update the HEAD recorded above.

## Why TurboMind (verified)
The only tensor-core int4-MoE kernel that (a) runs on SM86, (b) **tolerates
K=352** (its 16×8×32 MMA tile + offline weight repack, where Marlin's hard
`thread_k∈{64,128}` rejects), (c) **supports group_size=32** (confirmed in
`gemm/kernel/sm80_16816_4.cu:82` — `register_u4_g(integral_constant<int,32>)`),
(d) is **CUTLASS-free** (hand-written multistage). Measured +134-220% over
FP16 on M=1-16 decode, +19% over Marlin (A100, arXiv:2508.15601) — pending
A5000 re-bench.

## Vendint status (Phase 0)
- [x] full `gemm/` (104 files), `gemm/arch/sm80`, `gemm/kernel/sm80_16816_{4,8,16}`
- [x] `kernels/core/` (header-only) + high-level `core/` headers (data_type,
      check, logger, allocator, tensor, ...) + `attention/quantization.h`
- [x] structure preserves original `src/turbomind/...` include paths (build `-I.`)
- [x] fmt: apt `libfmt-dev` (preferred) OR vendored `third_party/fmt` header-only
- [x] **ALL 3 tensor-core kernels COMPILE on SM86** — proven 2026-06-22 in the
      vLLM image: `sm80_16816_{4,8,16}.cu` → 19.5/2.7/5.8 MB objects. See
      `build_kernels.sh` for the exact recipe. Critical flags found build-driven:
      `-arch=sm_86 -DENABLE_BF16 --expt-relaxed-constexpr -include cuda_fp16.h
      -include cuda_bf16.h -I.`. **The core::-dependency risk is RESOLVED** —
      gemm.cu pulls only check.h+logger.h; the kernel headers need bf16 includes,
      not a Tensor/Allocator shim.
- [x] Phase 0 cont.: full multi-TU build (`test/buildrun.sh`, 54 TUs) → `tm_test`
      links + runs on SM86. **252 sm80 kernels register** (file-probe verified;
      sm70/75 correctly arch-skipped). cuBLAS reference (`test/reference.cu`) wired.
- [x] **Phase 1 PROVEN on rig (2026-06-22, 2×A5000 SM86)** — TurboMind
      `sm80_16816` int4 g32 grouped-MoE kernel dispatches + runs **correctly** for
      the exact Gemma-4-26B-A4B geometry (E=128, top_k=8, hidden=2816,
      inter=704, group_size=32, `f16` act). **rel-err vs FP16 reference (same
      dequantized weights) = 0.000356 mean / 1.60 max, ~0 outliers** → the int4
      tensor-core math is numerically faithful; quantization itself adds ~1.88%
      (inherent to int4 g32, NOT the kernel). **Zero-point fusion verified**:
      `fuse_scales_and_zeros` (packV=0x141) decodes `x*s + (-zp*s)` correctly —
      this **resolves spec risk #1** (the zero-point format) empirically.
      - **Critical learning for Phase 2**: MoE expert weights MUST call
        `LinearWeight::set_grouped(true)` before `prepare()` so `GetConverters`
        returns the *grouped* u4 layout (`order_b` col-major). The dense u4 layout
        has the opposite `order_b` → "No feasible kernel" for the grouped GEMM.
- [x] **Speed A/B PROVEN on rig (2026-06-22, 2×A5000 SM86)** — cudaEvent-timed
      grouped-MoE GEMM latency for the Gemma-4-26B-A4B shape (E=128, top_k=8,
      hidden=2816, inter=704, g32), TurboMind int4 (`test_gemm_v2` `Benchmark()`,
      both GEMMs w1w3+w2) vs vLLM `moe_wna16` (`fused_experts_impl`, CUDA path
      `should_moe_wna16_use_cuda`), both int4 g32, random weights (latency depends
      only on shape/dtype):

      | tokens | M (=tok·8) | TurboMind int4 w1w3+w2 | vLLM moe_wna16 full | speedup |
      |-------:|-----------:|-----------------------:|--------------------:|--------:|
      |   1 (decode) |    8 |  **57.2 µs** |  187.4 µs | **3.3×** |
      |   4          |   32 |   159.2 µs   |  788.1 µs | **4.95×** |
      |  16          |  128 |   506.4 µs   | 2354.3 µs | **4.65×** |
      |  64          |  512 |   701.7 µs   | 4247.8 µs | **6.05×** |

      The TurboMind int4 w1w3 GEMM alone hits **~737 GB/s = ~96% of A5000 peak HBM
      BW** at M=128 (memory-bound optimal). Caveat: the TurboMind figure sums the
      two grouped GEMMs (no silu/combine epilogue); moe_wna16 full includes
      silu+combine (small), so the GEMM-core speedup is the conservative end.
- [ ] Phase 2: torch.ops custom op + offline weight-prep (grouped layout) +
      swap moe_wna16 in the live engine + end-to-end TPOT A/B on the 26B

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
