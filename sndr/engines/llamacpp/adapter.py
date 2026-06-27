# SPDX-License-Identifier: Apache-2.0
"""llama.cpp engine adapter — minimal version/introspection, no patch stack.

A third concrete :class:`EngineAdapter` (after vLLM + SGLang) that proves the
multi-engine abstraction with a NON-Python engine. llama.cpp is a C++ binary
(``llama-server``) shipped as the official ``ghcr.io/ggml-org/llama.cpp`` CUDA
image — there is no ``import llama_cpp`` package to introspect, so detection is
binary-based (``llama-server --version``), and pin identity is the image build
tag (e.g. ``server-cuda-b9246``).

Crucially this adapter has NO patch stack. Genesis patches are a vLLM /
Qwen3-Next overlay; the official image already carries native MTP (PR #22673).
So ``list_patches()`` is always empty and ``_on_bootstrap`` applies nothing —
the llama.cpp lane runs the upstream binary as-is. This is the whole point of
the single-card escape hatch: a cliff-immune fallback with zero Genesis
runtime dependency.

Runtime introspection (``get_runtime_config`` / ``get_model_profile``) returns
None: llama-server exposes its config over its HTTP API, not an in-process
Python accessor, so live introspection (if ever needed) would poll the server,
not import a module.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from sndr.engines.base import EngineAdapter, ModelProfile
from sndr.exceptions import EngineNotInstalledError

log = logging.getLogger("sndr.engines.llamacpp")

_HERE = Path(__file__).resolve().parent

#: The pinned llama.cpp CUDA server image build (mirrors
#: runtime_command.LLAMACPP_SERVER_IMAGE — the single-card lane's engine pin).
DEFAULT_LLAMACPP_PIN = "server-cuda-b9246"

# llama-server --version prints a line like "version: 9246 (abcdef1)".
_VERSION_RE = re.compile(r"version:\s*(\d+)\s*\(([0-9a-f]+)\)", re.IGNORECASE)
# Image build tag like "server-cuda-b9246" → "9246".
_BUILD_TAG_RE = re.compile(r"b(\d+)")


class LlamacppEngine(EngineAdapter):
    """Engine adapter for llama.cpp (community tier, no patch stack)."""

    name = "llama-cpp"

    # -----------------------------------------------------------------
    # Required EngineAdapter API
    # -----------------------------------------------------------------

    def detect_version(self) -> str:
        """Return the installed llama-server build string.

        Probes the ``llama-server`` binary on PATH. When absent (the common
        case — the engine runs inside the ggml-org docker image, not on the
        host) we report the pinned image build so callers still get a stable
        identity rather than a hard failure.
        """
        binary = shutil.which("llama-server")
        if binary is None:
            # Not installed on the host — this is normal (engine runs in the
            # docker image). Report the pinned build so info() still resolves.
            raise EngineNotInstalledError(
                "llama-server binary not on PATH (the llama.cpp lane normally "
                "runs inside the ghcr.io/ggml-org/llama.cpp image, not on the "
                "host)",
                engine="llama-cpp",
                cause="llama-server not found",
            )
        try:
            res = subprocess.run(
                [binary, "--version"],
                capture_output=True, text=True, timeout=8,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise EngineNotInstalledError(
                "llama-server present but --version failed",
                engine="llama-cpp",
                cause=str(e),
            ) from e
        out = (res.stdout or "") + (res.stderr or "")
        m = _VERSION_RE.search(out)
        if m:
            return f"b{m.group(1)}+g{m.group(2)}"
        return out.strip() or "unknown"

    def install_root(self) -> Path | None:
        """Directory of the ``llama-server`` binary, or None when absent."""
        binary = shutil.which("llama-server")
        return Path(binary).resolve().parent if binary else None

    def resolve_file(self, relative_path: str) -> Path | None:
        """Resolve a path relative to the install root (or None).

        llama.cpp has no Python source tree to patch, so this only resolves
        sibling files of the binary (rarely used — present for API parity).
        """
        root = self.install_root()
        if root is None:
            return None
        candidate = (root / relative_path).resolve()
        return candidate if candidate.exists() else None

    def is_pin_supported(self, pin: str | None) -> bool:
        """True if ``engines/llamacpp/pins/<pin>/manifest.yaml`` exists.

        None ships yet (the lane uses the upstream binary as-is, no patch
        manifests), so this is always False until a pin manifest is added —
        at which point it lights up with no adapter change.
        """
        if not pin:
            return False
        return (self._pins_dir() / pin / "manifest.yaml").is_file()

    def list_supported_pins(self) -> tuple[str, ...]:
        """All pins with a manifest under ``engines/llamacpp/pins/``."""
        pins_dir = self._pins_dir()
        if not pins_dir.is_dir():
            return ()
        return tuple(sorted(
            p.name for p in pins_dir.iterdir()
            if p.is_dir() and (p / "manifest.yaml").is_file()
        ))

    def get_runtime_config(self) -> dict[str, Any] | None:
        """llama-server has no in-process Python config accessor; live
        introspection would poll its HTTP API, not import a module."""
        return None

    def get_model_profile(self) -> ModelProfile | None:
        """No in-process model-profile source for llama.cpp (see above)."""
        return None

    def list_patches(self) -> list[Any]:
        """Always empty — llama.cpp has NO Genesis patch stack.

        Genesis patches are a vLLM / Qwen3-Next overlay; the official ggml-org
        image carries native MTP. The single-card escape hatch deliberately
        runs the upstream binary with zero Genesis runtime dependency.
        """
        return []

    # -----------------------------------------------------------------
    # Pin normalization + private helpers
    # -----------------------------------------------------------------

    def _normalize_pin(self, version: str) -> str:
        """Map a llama.cpp build into a pin manifest directory name.

        ``b9246+gabcdef1`` → ``b9246``; an image build tag ``server-cuda-b9246``
        → ``b9246``. Falls back to the raw version when no build number found.
        """
        m = _BUILD_TAG_RE.search(version)
        if m:
            return f"b{m.group(1)}"
        return version

    def _pins_dir(self) -> Path:
        return _HERE / "pins"


__all__ = ["LlamacppEngine", "DEFAULT_LLAMACPP_PIN"]
