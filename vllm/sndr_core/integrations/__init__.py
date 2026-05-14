# SPDX-License-Identifier: Apache-2.0
"""SNDR Core patches — engine-subsystem-first taxonomy.

Each subsystem corresponds to a vllm-engine subdirectory or coherent
concern. Patches grouped by PRIMARY engine target file (Sander Q1/Q6
decision 2026-05-07). 19 families total.
"""

from __future__ import annotations

__all__ = [
    "attention",
    "compile_safety",
    "kernels",
    "kv_cache",
    "loader",
    "lora",
    "memory",
    "middleware",
    "moe",
    "multimodal",
    "quantization",
    "reasoning",
    "scheduler",
    "serving",
    "spec_decode",
    "tool_parsing",
    "worker",
]

def __getattr__(name: str):
    """Lazy submodule loader (P0-1 fix, audit 2026-05-08).

    Eager `from . import <patch>` cascaded torch imports → torch-less
    hosts (CI / Mac dev / preflight) couldn't import the patches
    package at all. Now patches load only on attribute access.
    """
    import importlib
    if name in __all__:
        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(
        f"module {__name__!r} has no attribute {name!r}"
    )
