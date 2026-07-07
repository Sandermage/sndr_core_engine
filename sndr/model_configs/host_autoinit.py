# SPDX-License-Identifier: Apache-2.0
"""First-run auto-init of `host.yaml` (BREAK #2 fix, 2026-07-06).

A brand-new operator who never edited `~/.sndr/host.yaml` used to watch the
launch renderer emit a literal ``${models_dir}`` token (or fatal with
"unresolved ${models_dir}") because no per-host path map existed yet. This
module closes that gap without changing any existing precedence:

  ``ensure_host_yaml()`` — if the host.yaml is ABSENT, auto-detect the
  conventional paths via the already-written ``host.detect_paths()`` and
  persist them; if it is PRESENT, no-op. Env overrides (``SNDR_*`` /
  ``GENESIS_*``) still pre-empt at detection time (they flow through
  ``detect_paths``), so the DOWNLOAD-3 ladder (env > written file > probe)
  is preserved: an env override is baked into the written map.

Design contract:
  * ADDITIVE — never removes or edits an existing host.yaml.
  * IDEMPOTENT + resumable — safe to call on every launch; a second call on
    an existing file is a no-op.
  * NON-TTY safe — never prompts; writes the silently auto-detected map. On a
    host where nothing is detectable it writes NOTHING (returns ``None``) so
    read-only / CI callers on a bare runner are not polluted with an empty
    stub file.
  * NO baked operator paths — every candidate comes from
    ``host.detect_paths()``; this module hardcodes none.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from sndr.model_configs import host as _host

if TYPE_CHECKING:
    from pathlib import Path


def ensure_host_yaml(
    persist: bool = True,
    path: Path | None = None,
) -> Path | None:
    """Ensure a per-host ``host.yaml`` exists; auto-detect + write on first miss.

    Args:
        persist: when False, detect but do not write (dry-run probe). The
            return value still reflects whether a write WOULD occur.
        path: explicit host.yaml location; defaults to the canonical
            resolution (``$SNDR_HOME``/``~/.sndr`` ladder) via host.py.

    Returns:
        * ``Path`` of the host.yaml that now exists (or would be written when
          ``persist=False``), OR
        * ``None`` when the file already exists (no-op) or nothing was
          detectable (nothing written).
    """
    target = path if path is not None else _host._default_host_yaml_path()

    # Present already -> idempotent no-op. Never touch an existing file.
    if target.is_file():
        return None

    # Auto-detect the conventional paths. Env overrides pre-empt inside
    # detect_paths(), so a set SNDR_MODELS_DIR / GENESIS_* wins here and is
    # what gets written (env-wins ladder, at write time).
    detected = _host.detect_paths()
    if not detected:
        # Bare host / CI runner with nothing to detect: writing an empty
        # `paths: {}` file would provide no value and would pollute
        # read-only callers. Leave the host absent; the resolve layer keeps
        # its existing "unresolved -> fix host.yaml" behavior.
        return None

    if not persist:
        return target

    hc = _host.HostConfig(paths=detected)
    return _host.save_host_config(hc, target)
