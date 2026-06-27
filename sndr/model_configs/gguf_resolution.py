# SPDX-License-Identifier: Apache-2.0
"""GGUF weights resolution for the llama.cpp engine lane.

vLLM consumes an HF checkpoint DIRECTORY (``--model /models/Qwen3.6-27B-...``);
llama.cpp / llama-server consumes a single GGUF FILE (``-m
/models/.../Qwen3.6-27B-Q4_K_M.gguf``). This is the load-bearing difference
between the two launch lanes: a directory is wrong for llama.cpp (it has no
multi-file loader), and a file is wrong for vLLM.

This module owns the file-vs-dir contract for the llama.cpp lane. It is PURE
(no filesystem I/O) so it works from a typed ModelConfig alone — the GUI / CLI
can render + validate the llama.cpp command before any weights exist on the
host. (A live boot still needs the GGUF on disk; that check lives in the
launch-time preflight, not here.)

Resolution rule
───────────────
``ModelConfig.model_path`` (carried from ``ModelDef.model_path``) IS the
container-side path to the single ``.gguf`` file for a llama-cpp model. We
validate the contract:

  - the path is non-empty,
  - it ends in ``.gguf`` (case-insensitive) — i.e. it is a FILE not a DIR,

and return it verbatim. A ModelDef that points an engine=llama-cpp lane at a
directory (the vLLM convention) is a configuration error surfaced here with a
clear message rather than a cryptic llama-server "failed to load model".

``weights_variant`` is the human label for which quant the GGUF file encodes
(e.g. ``unsloth-q4km`` → ``Qwen3.6-27B-Q4_K_M.gguf``). It is descriptive only;
the authoritative path is ``model_path``. ``gguf_variant_label`` extracts it
from the filename for display (the card / GUI engine line).
"""
from __future__ import annotations

import os

from .schema import SchemaError

__all__ = [
    "resolve_gguf_file",
    "gguf_variant_label",
    "is_gguf_path",
]

_GGUF_SUFFIX = ".gguf"


def is_gguf_path(path: str) -> bool:
    """True when ``path`` names a single ``.gguf`` file (case-insensitive)."""
    return bool(path) and path.lower().endswith(_GGUF_SUFFIX)


def resolve_gguf_file(model_path: str) -> str:
    """Resolve a llama-cpp ModelConfig's ``model_path`` to a single GGUF file.

    Args:
        model_path: container-side path declared on the ModelDef/ModelConfig.
            For a llama-cpp lane this MUST be a single ``.gguf`` file (NOT an
            HF directory, which is the vLLM convention).

    Returns:
        The validated GGUF file path (verbatim — no normalization, so the
        container-side path the operator declared is what llama-server gets).

    Raises:
        SchemaError: when the path is empty, or does not end in ``.gguf``
            (i.e. it looks like a directory / the vLLM convention).
    """
    if not model_path:
        raise SchemaError(
            "llama-cpp engine requires model_path to be a single .gguf FILE; "
            "got an empty model_path"
        )
    if not is_gguf_path(model_path):
        raise SchemaError(
            f"llama-cpp engine requires model_path to be a single .gguf FILE "
            f"(e.g. /models/qwen3.6-27b-gguf/unsloth-mtp-q4km/"
            f"Qwen3.6-27B-Q4_K_M.gguf), not an HF checkpoint directory. "
            f"Got: {model_path!r}. The vLLM directory convention does not "
            f"work for llama.cpp — point model_path at the .gguf file."
        )
    return model_path


def gguf_variant_label(model_path: str) -> str:
    """Human label for the GGUF quant variant, derived from the filename.

    Best-effort display string for the card / GUI engine line — e.g.
    ``/models/.../Qwen3.6-27B-Q4_K_M.gguf`` → ``Qwen3.6-27B-Q4_K_M``. Returns
    an empty string when ``model_path`` is not a ``.gguf`` file.
    """
    if not is_gguf_path(model_path):
        return ""
    base = os.path.basename(model_path)
    return base[: -len(_GGUF_SUFFIX)]
