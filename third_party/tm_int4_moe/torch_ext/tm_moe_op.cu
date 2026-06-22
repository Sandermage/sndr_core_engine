// SPDX-License-Identifier: Apache-2.0
// Genesis G4_85: torch custom op wrapping TurboMind's sm80_16816 int4 grouped-MoE
// GEMM (LlamaLinear::Forward) so vLLM can replace the slow CUDA-core moe_wna16.
//
// Milestone 1 (this file): a probe op that constructs the TurboMind context +
// LlamaLinear inside the torch-extension process — proves the multi-TU vendored
// engine links + loads against libtorch (ABI / CUDA-runtime interop) before we
// wire the full MoE forward.
#include <torch/extension.h>

#include <cuda_fp16.h>
#include <cuda_bf16.h>

#include "src/turbomind/core/allocator.h"
#include "src/turbomind/core/context.h"
#include "src/turbomind/core/stream.h"
#include "src/turbomind/models/llama/LlamaLinear.h"

namespace tmext {

using namespace turbomind;

// Probe: stand up the TurboMind stream + allocator context and a LlamaLinear
// (which constructs the Gemm kernel registry). Returns 1 on success; any link
// or init failure surfaces as a load-time/runtime error instead.
int64_t tm_probe()
{
    auto               stream = core::Stream::create();
    core::ContextGuard guard{stream, core::Allocator{kCPU}, core::Allocator{stream, false}};
    LlamaLinear        linear;
    cudaStreamSynchronize(stream.handle());
    return 1;
}

}  // namespace tmext

TORCH_LIBRARY(genesis_tm, m)
{
    m.def("tm_probe() -> int");
}

TORCH_LIBRARY_IMPL(genesis_tm, CompositeExplicitAutograd, m)
{
    m.impl("tm_probe", &tmext::tm_probe);
}
