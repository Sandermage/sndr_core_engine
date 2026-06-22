# SPDX-License-Identifier: Apache-2.0
"""Build + load the Genesis TurboMind int4-MoE torch extension on the rig.

Links the pre-built vendored engine objects (/work/build/*.o, minus the test
main) into a torch C++ extension and exercises the probe op. Run inside the
vLLM image after the engine objects are compiled (see build_probe.sh).
"""
import glob
import os

import torch
from torch.utils.cpp_extension import load

WORK = os.environ.get("TM_WORK", "/work")

# Engine objects, minus anything carrying main() or test-only cublas deps.
objs = [
    o for o in glob.glob(f"{WORK}/build/*.o")
    if "test_gemm_v2" not in o and "_test_" not in o
]
print(f"[build_ext] linking {len(objs)} engine objects")

cuda_flags = [
    "-arch=sm_86", "-std=c++17", "-DENABLE_BF16", "-DFMT_HEADER_ONLY",
    "--expt-relaxed-constexpr", "--extended-lambda",
    "-include", "cuda_fp16.h", "-include", "cuda_bf16.h",
    f"-I{WORK}", f"-I{WORK}/third_party/fmt/include", f"-I{WORK}/third_party/moodycamel",
]
cpp_flags = ["-std=c++17", "-DFMT_HEADER_ONLY", f"-I{WORK}", f"-I{WORK}/third_party/fmt/include"]

torch.zeros(1, device="cuda")  # force torch to init the CUDA context first

# This torch build's load() has no extra_objects kwarg; pass the pre-built
# engine objects positionally through the linker via extra_ldflags.
# is_python_module=False: ops are registered via TORCH_LIBRARY static init, not
# a pybind module, so torch just dlopen()s the .so and the ops appear on torch.ops.
load(
    name="genesis_tm",
    sources=[f"{WORK}/torch_ext/tm_moe_op.cu"],
    extra_cuda_cflags=cuda_flags,
    extra_cflags=cpp_flags,
    extra_ldflags=[*objs, "-lcublas", "-lcublasLt",
                   "-L/usr/local/cuda/lib64/stubs", "-lcuda"],
    is_python_module=False,
    verbose=True,
)
print("[build_ext] extension LOADED OK")
print("[build_ext] tm_probe() =>", torch.ops.genesis_tm.tm_probe())
