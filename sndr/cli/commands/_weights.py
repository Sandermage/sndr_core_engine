# SPDX-License-Identifier: Apache-2.0
"""Shared model-weight ensuring for the turnkey launch verbs (`run`, `up`).

Both ``sndr run`` (resolve → pull → launch → chat) and ``sndr up`` (launch
engine + GUI) must guarantee the preset's weights are on disk before the engine
boots — otherwise the container either fails or silently blocks on a slow
in-container HF download with no progress in the CLI. This module is the single
implementation both verbs call, so "one command downloads everything" behaves
identically whether the user takes the terminal path or the GUI path.

The puller (``sndr.compat.models.pull.pull_via_artifacts``) verifies before it
downloads, so ``ensure_weights`` is a no-op when the weights are already
complete — safe to call on every launch.
"""
from __future__ import annotations


def has_artifacts_block(preset_id: str) -> bool:
    """True when the preset declares an ``artifacts.models`` block to pull.

    Many V2 presets resolve their model via a host-side mount rather than a
    declared HF artifact; for those there is nothing for the puller to do, and
    calling it would emit a misleading "no artifacts.models block" ERROR. This
    pre-check lets a caller skip the puller cleanly in that case (the launch
    path's own mount resolution then reports a truly missing model precisely).
    """
    try:
        from sndr.model_configs.registry_v2 import load_alias

        cfg = load_alias(preset_id)
        artifacts = getattr(cfg, "artifacts", None)
        return bool(artifacts and getattr(artifacts, "models", None))
    except Exception:
        return False


def ensure_weights(preset_id: str, *, dry_run: bool = False) -> int:
    """Ensure the preset's model weights are present. Reuses the artifacts
    puller, which verifies before downloading (so this is a no-op when the
    weights are already complete). Returns the puller's rc (0 = ready).

    A preset without an ``artifacts.models`` block has nothing to pull (its
    model comes from a host mount) — skip the puller so the launch path's own
    preflight catches a truly missing model path with a precise message.
    """
    if not has_artifacts_block(preset_id):
        return 0
    from sndr.compat.models.pull import pull_via_artifacts

    rc = pull_via_artifacts(preset_id, dry_run=dry_run)
    if rc == 2:
        # Defensive: a late artifacts/verify edge — not a download failure.
        return 0
    return rc


__all__ = ["ensure_weights", "has_artifacts_block"]
