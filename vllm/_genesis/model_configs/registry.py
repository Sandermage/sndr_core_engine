# SPDX-License-Identifier: Apache-2.0
"""Registry — discover ModelConfigs from builtin/, community/, user/ dirs.

Builtin (`vllm/_genesis/model_configs/builtin/*.yaml`) ships with
the patcher. Community (`community/*.yaml`) is PR'd and reviewed.
User (`~/.genesis/model_configs/*.yaml` or `$GENESIS_MODEL_CONFIG_DIR`)
is operator-local, never committed.

`get(key)` searches all three in priority order: user > community >
builtin. This lets operators override builtin configs without forking.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from .schema import ModelConfig, load_yaml, SchemaError


_BUILTIN_DIR = Path(__file__).parent / "builtin"
_COMMUNITY_DIR = Path(__file__).parent / "community"


def _user_dir() -> Path:
    """Resolve the operator-local config dir.

    Order:
      1. $GENESIS_MODEL_CONFIG_DIR (explicit override)
      2. ~/.genesis/model_configs/
    """
    override = os.environ.get("GENESIS_MODEL_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".genesis" / "model_configs"


def _load_dir(d: Path, source_label: str) -> dict[str, ModelConfig]:
    """Load every *.yaml from `d`, indexed by config.key.

    Keys collisions within the same dir → SchemaError. Corrupt YAMLs
    → logged + skipped (not raised) so a bad community config doesn't
    blow up the whole registry.
    """
    out: dict[str, ModelConfig] = {}
    if not d.is_dir():
        return out
    for yaml_path in sorted(d.glob("*.yaml")):
        try:
            cfg = load_yaml(yaml_path.read_text())
        except SchemaError as e:
            import logging
            logging.getLogger("genesis.model_configs").warning(
                "[model_configs] skipping %s/%s — schema error: %s",
                source_label, yaml_path.name, e,
            )
            continue
        if cfg.key in out:
            raise SchemaError(
                f"duplicate model_config key '{cfg.key}' in "
                f"{source_label}/ (file: {yaml_path.name})"
            )
        out[cfg.key] = cfg
    return out


def load_all() -> dict[str, ModelConfig]:
    """Return merged registry: user overrides community overrides builtin."""
    builtin = _load_dir(_BUILTIN_DIR, "builtin")
    community = _load_dir(_COMMUNITY_DIR, "community")
    user = _load_dir(_user_dir(), "user")
    # Merge in priority order
    merged: dict[str, ModelConfig] = {}
    for src in (builtin, community, user):
        merged.update(src)
    return merged


def get(key: str) -> Optional[ModelConfig]:
    """Get one config by key, or None if not found in any tier."""
    return load_all().get(key)


def list_keys() -> list[str]:
    """Sorted list of all available config keys."""
    return sorted(load_all().keys())


def source_of(key: str) -> Optional[str]:
    """Return 'builtin' / 'community' / 'user' for the tier providing key."""
    if key in _load_dir(_user_dir(), "user"):
        return "user"
    if key in _load_dir(_COMMUNITY_DIR, "community"):
        return "community"
    if key in _load_dir(_BUILTIN_DIR, "builtin"):
        return "builtin"
    return None
