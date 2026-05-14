# SPDX-License-Identifier: Apache-2.0
"""patch_genesis_unified.py — v7.14+ backward-compatibility shim.

Genesis migrated from a monolithic `patch_genesis_unified.py` (≤ v7.13)
to a modular `vllm/_genesis/` Python package + `python3 -m
vllm._genesis.patches.apply_all` invocation (v7.14+).

This file is a thin shim that invokes the new modular `apply_all` so old
compose files / launch scripts that mount this path keep working with a
deprecation warning. New deployments should call the module directly:

    python3 -m vllm._genesis.patches.apply_all

Why we keep this shim
---------------------
Several downstream repos (noonghunna/qwen36-27b-single-3090,
noonghunna/qwen36-dual-3090, tedivm/qwen36-27b-docker, etc.) have
docker-compose files that volume-mount `patch_genesis_unified.py` into
the vLLM container's entrypoint. Without this shim, fresh `git clone` of
the Genesis repo breaks those launches with `can't find '__main__' module`.

The shim is also useful for users who pinned to a v7.13 tag or older and
upgrade incrementally — the deprecation warning gives them a clear path
to update their launch invocation.

Status: shipped 2026-04-27 (v7.53.x compat layer) per
noonghunna/qwen36-27b-single-3090#2 community ask. Removable once all
known downstream repos migrate to the `python3 -m` invocation; will be
deprecated for removal in Genesis v8.0.

Author: Sandermage(Sander) Barzov Aleksandr, Ukraine, Odessa.
"""
from __future__ import annotations

import sys
import warnings


def main() -> int:
    """Run the Genesis patch suite (v11+ entrypoint via sndr_core)."""
    warnings.warn(
        "patch_genesis_unified.py is deprecated since Genesis v7.14 and "
        "the underlying _genesis package was migrated to vllm.sndr_core in "
        "v11. Update your launch invocation to: "
        "python3 -m vllm.sndr_core.apply",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        from vllm.sndr_core.apply import apply_all as _modular_main
    except ImportError as e:
        print(
            "ERROR: cannot import vllm.sndr_core.apply — Genesis sndr_core "
            "was not found in this vLLM install.\n"
            f"Reason: {e}\n\n"
            "Migration:\n"
            "  - Mount sndr_core into vLLM's site-packages:\n"
            "      -v <repo>/vllm/sndr_core:/usr/local/lib/python3.12/dist-packages/vllm/sndr_core:ro\n"
            "  - Then call:\n"
            "      python3 -m vllm.sndr_core.apply",
            file=sys.stderr,
        )
        return 1

    # apply_all returns the patch dispatch matrix list; keep shell exit 0.
    _modular_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
