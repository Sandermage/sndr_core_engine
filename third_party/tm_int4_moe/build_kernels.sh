#!/bin/bash
# Build the TurboMind int4 grouped-MoE shared object (genesis_tm.so) for SM86.
#
# WORKING RECIPE — verified on the rig 2026-06-23. This compiles the FULL
# ~46-object dependency closure of src/turbomind (not just kernels/gemm/*) and
# links a loadable genesis_tm.so with ZERO undefined turbomind:: symbols. The
# kernel FIRES on the 26B (tm_probe()=1, both TP workers load it, numerics
# correct: GEMM_err ~3e-4, full-MoE reldiff ~9e-4).
#
# HISTORY — why the old recipe was wrong: the previous version compiled only
# 13 objects (kernels/gemm/*), so genesis_tm.so failed to dlopen with
# `undefined symbol: _ZTVN9turbomind12LinearWeightE` (vtable for
# turbomind::LinearWeight). torch_ext/tm_moe_op.cu additionally needs
# src/turbomind/models/linear_weight.cc + llama/LlamaLinear.cu + core/* +
# utils/ + gpt_kernels.cu + cublas.cu + the sm70/sm75 tensor-core TUs. The
# correct closure is the `find src/turbomind` set below (MINUS test/,
# sm90_64n32, anomaly_handler — disabled / non-SM86).
#
# END-TO-END STATUS: the kernel BUILDS and FIRES, but the G4_85 patch OOMs
# end-to-end on 2× A5000 — it dequantizes int4 -> fp16 per MoE layer (~2x
# weight memory transiently, w13 ~968 MiB + w2 ~484 MiB per layer per GPU x
# ~30 layers) on top of an int4 model that already fills ~20 of 23.5 GiB.
# Fixing that is a SOURCE redesign (stream-dequant one layer at a time, or
# feed packed int4 directly to TurboMind), NOT a build fix. EP+Marlin (142.5
# tps) beats the pure-TP fallback (125.4 tps) anyway, so G4_85 stays
# experimental / pure-TP-only. See the g4_85 patch docstring for the full
# benchmark verdict.
#
# Run inside the vLLM image with the vendored tree mounted at /work and
# --gpus all (internet only needed if the apt fmt fallback is used):
#   docker run --rm --network host --gpus all --entrypoint bash \
#     -v $(pwd):/work vllm/vllm-openai:nightly -c "bash /work/build_kernels.sh"
set -e
cd "$(dirname "$0")"

# fmt is vendored header-only (-DFMT_HEADER_ONLY -Ithird_party/fmt/include),
# so no apt step is required for the build itself.
find src third_party -name "._*" -delete 2>/dev/null || true
mkdir -p build

# nvcc flags (build-driven, live-confirmed on the rig 2026-06-23):
#  -arch=sm_86             : A5000 (Ampere) tensor cores
#  -DENABLE_BF16           : TurboMind bf16 MMA path uses nv_bfloat16
#  -DFMT_HEADER_ONLY       : vendored header-only fmt (no libfmt link)
#  --expt-relaxed-constexpr: constexpr in __device__ helpers
#  --extended-lambda       : device lambdas in the MoE kernels
#  -Xcompiler -fPIC        : the objects are linked into a shared object
#    (genesis_tm.so via torch_ext). Without position-independent code the
#    link fails with `relocation R_X86_64_PC32 ... cannot be used when making
#    a shared object`. Matches torch_ext/build_probe.sh.
#  -include cuda_fp16/bf16 : the kernel headers assume these are already pulled
#  -I.                     : TurboMind uses absolute "src/turbomind/..." includes
FLAGS="-arch=sm_86 -std=c++17 -DENABLE_BF16 -DFMT_HEADER_ONLY \
  --expt-relaxed-constexpr --extended-lambda -Xcompiler -fPIC \
  -include cuda_fp16.h -include cuda_bf16.h -I. \
  -Ithird_party/fmt/include -Ithird_party/moodycamel"

# Full TU dependency closure for tm_moe_op.cu. Compile every *.cu / *.cc under
# src/turbomind (this KEEPS core/, models/ incl. linear_weight.cc +
# llama/LlamaLinear.cu, utils/, gpt_kernels.cu, cublas.cu, sm70_884_* ,
# sm75_16816_*, tuner/*) MINUS the test/ harness, the disabled sm90_64n32, and
# anomaly_handler. ~46 objects on SM86.
SRCS=$(find src/turbomind -name "*.cu" -o -name "*.cc" \
  | grep -vE "/test/|sm90_64n32|anomaly_handler|gemm_bench|test_logger|test_core|test_scope|test_data_format|test_moe_utils")

n=0; total=$(echo "$SRCS" | wc -w | tr -d ' '); fails=""
for f in $SRCS; do
  o=build/$(echo "$f" | tr '/' '_' | sed 's/\.\(cu\|cc\)$/.o/')
  [ -f "$o" ] && { n=$((n+1)); continue; }   # reuse already-compiled (fPIC) object
  echo "compiling $f ..."
  if nvcc $FLAGS -c "$f" -o "$o"; then n=$((n+1)); else fails="$fails $(basename "$f")"; fi
done
echo "compiled: $n / $total  FAILED:$fails"

# Link torch_ext/tm_moe_op.cu against the full object closure into genesis_tm.so.
echo "linking genesis_tm.so ..."
nvcc $FLAGS --shared "torch_ext/tm_moe_op.cu" build/*.o \
  -lcublas -lcublasLt -L/usr/local/cuda/lib64/stubs -lcuda \
  -o build/genesis_tm.so
echo "OK — genesis_tm.so: $(stat -c%s build/genesis_tm.so 2>/dev/null || echo '?') bytes, $n objects (SM86)."

# NOTE: the JIT path used by the live patch (g4_85, _ensure_ext) re-links
# torch_ext/tm_moe_op.cu against build/*.o via torch.utils.cpp_extension.load;
# this script's standalone link is for offline verification that the closure
# has zero undefined turbomind:: symbols before the patch JIT-builds it.
