# SPDX-License-Identifier: Apache-2.0
"""PN275 — DFlash drafter VllmConfig max_cgs alignment (dev371 compat).

Closes the Q27-DFlash / Q35-DFlash dev371 boot failure documented in
``sndr_private/planning/audits/P2_DFLASH_DEV371_INCOMPATIBILITY_DESIGN_2026-05-21_RU.md``
and root-caused in
``sndr_private/planning/audits/P2_DFLASH_CANDIDATE_A_DESIGN_REFINED_2026-05-21_RU.md``.

Root cause (3-layer chain, verified against upstream dev371 source
SHA bf610c2f56764e1b30bc6065f4ceace3d6e59036):

  1. Parent ``VllmConfig`` init at ``vllm/config/vllm.py:1722``
     forces ``compilation_config.max_cudagraph_capture_size`` to
     match ``max(cudagraph_capture_sizes)`` after auto-computing
     both — so initial state is consistent.

  2. Genesis P95 (Marlin TP cudagraph cap on Ampere) fires AFTER
     ``VllmConfig.__post_init__`` and resets
     ``max_cudagraph_capture_size=8`` for TP>1 + Marlin + Ampere,
     WITHOUT touching ``cudagraph_capture_sizes`` (which stays at
     e.g. ``[..., 6]``). State is now desynchronized.

  3. DFlash ``_create_draft_vllm_config`` calls ``replace(base,
     attention_config=...)`` (via ``vllm/config/utils.py:119``)
     which rebuilds the VllmConfig through ``cls(**dataclass_dict)``.
     The new instance re-runs the post-init cross-validator at
     ``vllm/config/vllm.py:1703-1715`` which raises:

         ValueError: customized max_cudagraph_capture_size(=8) should
         be consistent with the max value of cudagraph_capture_sizes(=6)

  This cross-validator did not exist on dev338, so the desync was
  silently tolerated there.

Fix shape (B1 from the refined design doc):

  Wrap ``vllm.config.utils.replace`` so that for ``VllmConfig``
  instances where the source's ``compilation_config`` has
  ``max != max(sizes)`` AND the caller does NOT supply
  ``compilation_config`` via kwargs, inject an aligned
  ``compilation_config`` (built via the original ``replace`` on the
  CompilationConfig with the corrected ``max_cudagraph_capture_size``)
  BEFORE delegating to the original ``replace``. The rebuilt
  VllmConfig sees consistent state and pydantic validation passes.

Non-goals:
  * Does NOT touch ``CompilationConfig`` directly outside the
    aligned rebuild.
  * Does NOT change P95's contract — P95 still caps to 8 on the
    parent; this wrapper only re-aligns sizes on the rebuilt draft.
  * Does NOT short-circuit any caller's explicit ``compilation_config``
    kwarg — if a caller knows what it wants, the wrapper defers.
  * Default-OFF. Opt-in via ``GENESIS_ENABLE_PN275_DFLASH_MAX_CGS_ALIGN=1``.
    The DFlash hold gate (audit-side) stays in place until the
    smoke validates the fix.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
"""

from __future__ import annotations

import importlib
import logging
import os

log = logging.getLogger("genesis.wiring.pn275_dflash_max_cgs_align")

GENESIS_MARKER = "Genesis PN275 DFlash max_cgs align dev371 compat v1"
ENV_FLAG = "GENESIS_ENABLE_PN275_DFLASH_MAX_CGS_ALIGN"

_WRAPPED_ATTR = "_genesis_dflash_align_wrapped"
_ORIGINAL_ATTR = "_genesis_dflash_align_original"

_TARGET_MODULE = "vllm.config.utils"
_TARGET_FN_NAME = "replace"

_TRUTHY = ("1", "true", "yes", "on")


def should_apply() -> bool:
    """Strict opt-in. No platform / CUDA / SM probe — the wrapper is
    pure Python and safe to install on any host that imports
    `vllm.config.utils`."""
    return os.environ.get(ENV_FLAG, "").strip().lower() in _TRUTHY


def _build_wrapper(original):
    """Construct the wrapper closure. Separated so the unit tests can
    exercise it without importing the real `vllm.config.utils`.

    The wrapper has three fast-exit paths:
      1. Source is NOT a VllmConfig → delegate untouched.
      2. Caller already supplies ``compilation_config`` kwarg → defer.
      3. Source's compilation_config has consistent (or trivially
         absent) sizes / max → delegate untouched.

    Only when ALL fast exits miss does the wrapper compute the aligned
    compilation_config and inject it into kwargs.
    """
    def _wrapped(dataclass_instance, /, **kwargs):
        # Fast exit 1: only intervene on VllmConfig (string match avoids
        # importing the class at wrap time).
        cls = type(dataclass_instance)
        if cls.__name__ != "VllmConfig":
            return original(dataclass_instance, **kwargs)

        # Fast exit 2: caller already supplies compilation_config —
        # assume intent, do not second-guess.
        if "compilation_config" in kwargs:
            return original(dataclass_instance, **kwargs)

        cc = getattr(dataclass_instance, "compilation_config", None)
        if cc is None:
            return original(dataclass_instance, **kwargs)

        sizes = getattr(cc, "cudagraph_capture_sizes", None)
        mx = getattr(cc, "max_cudagraph_capture_size", None)

        # Fast exit 3: nothing to align if either field is absent /
        # empty / already consistent.
        if not sizes or mx is None:
            return original(dataclass_instance, **kwargs)
        target_max = max(sizes)
        if mx == target_max:
            return original(dataclass_instance, **kwargs)

        # Align: rebuild compilation_config with corrected max. Use
        # the same `original` function — that's what's available + we
        # know its semantics on this pin.
        try:
            aligned_cc = original(
                cc, max_cudagraph_capture_size=target_max,
            )
        except Exception as e:  # noqa: BLE001
            # Never break the outer replace because alignment failed —
            # fall through to original and let pydantic surface the
            # real error.
            log.debug(
                "[PN275] alignment of compilation_config failed (%s: %s); "
                "passing through to original replace",
                type(e).__name__, e,
            )
            return original(dataclass_instance, **kwargs)

        kwargs["compilation_config"] = aligned_cc
        log.debug(
            "[PN275] aligned VllmConfig replace: "
            "max_cudagraph_capture_size %s → %s (max of sizes)",
            mx, target_max,
        )
        return original(dataclass_instance, **kwargs)

    setattr(_wrapped, _WRAPPED_ATTR, True)
    setattr(_wrapped, _ORIGINAL_ATTR, original)
    return _wrapped


def apply() -> tuple[str, str]:
    """Install the wrapper on ``vllm.config.utils.replace``. Idempotent.

    Returns ``(status, reason)`` per dispatcher convention. Never
    raises — failure paths log and return ``("skipped", ...)`` so
    other patches keep applying.
    """
    if not should_apply():
        return "skipped", (
            f"{ENV_FLAG} not set — opt-in patch (DFlash dev371 compat). "
            f"See sndr_private/planning/audits/"
            f"P2_DFLASH_CANDIDATE_A_DESIGN_REFINED_2026-05-21_RU.md "
            f"for the design rationale."
        )

    try:
        mod = importlib.import_module(_TARGET_MODULE)
    except ImportError as e:
        return "skipped", (
            f"{_TARGET_MODULE} not importable: {e}. PN275 is a no-op "
            f"on hosts without vllm.config.utils (e.g. torch-less CI)."
        )

    original = getattr(mod, _TARGET_FN_NAME, None)
    if original is None:
        return "skipped", (
            f"{_TARGET_MODULE}.{_TARGET_FN_NAME} not found — upstream "
            f"may have moved the function. PN275 anchor drift; revisit."
        )

    if getattr(original, _WRAPPED_ATTR, False):
        return "applied", "already wrapped (idempotent)"

    wrapped = _build_wrapper(original)
    setattr(mod, _TARGET_FN_NAME, wrapped)
    return "applied", (
        f"{_TARGET_MODULE}.{_TARGET_FN_NAME} wrapped for VllmConfig "
        f"compilation_config.max_cudagraph_capture_size alignment "
        f"(dev371 cross-validator compat)"
    )


def is_applied() -> bool:
    """True iff our marker is present on ``vllm.config.utils.replace``."""
    try:
        mod = importlib.import_module(_TARGET_MODULE)
    except ImportError:
        return False
    fn = getattr(mod, _TARGET_FN_NAME, None)
    return fn is not None and getattr(fn, _WRAPPED_ATTR, False)


def revert() -> bool:
    """Restore the original ``replace`` function. Returns True on
    success. Idempotent: if not wrapped, returns False."""
    try:
        mod = importlib.import_module(_TARGET_MODULE)
    except ImportError:
        return False
    fn = getattr(mod, _TARGET_FN_NAME, None)
    if fn is None or not getattr(fn, _WRAPPED_ATTR, False):
        return False
    original = getattr(fn, _ORIGINAL_ATTR, None)
    if original is None:
        return False
    setattr(mod, _TARGET_FN_NAME, original)
    return True
