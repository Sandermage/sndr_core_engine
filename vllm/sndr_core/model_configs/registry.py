# SPDX-License-Identifier: Apache-2.0
"""Registry — discover ModelConfigs from builtin/, community/, user/ dirs.

Builtin (`vllm/sndr_core/model_configs/builtin/*.yaml`) ships with
the patcher. Community (`community/*.yaml`) is PR'd and reviewed.
User (`~/.sndr/model_configs/*.yaml` or `$SNDR_MODEL_CONFIG_DIR`) is
operator-local, never committed. Legacy `GENESIS_*` paths remain as
fallback aliases during the migration window.

`get(key)` searches all three in priority order: user > community >
builtin. This lets operators override builtin configs without forking.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .schema import ModelConfig, load_yaml, SchemaError


_BUILTIN_DIR = Path(__file__).parent / "builtin"
_COMMUNITY_DIR = Path(__file__).parent / "community"


def _user_dir() -> Path:
    """Resolve the operator-local config dir.

    P1-5 (audit 2026-05-08): canonical env is `SNDR_MODEL_CONFIG_DIR`,
    legacy alias `GENESIS_MODEL_CONFIG_DIR` honored. Default root is
    `~/.sndr/model_configs/` with fallback to `~/.genesis/model_configs/`
    when the legacy dir exists alone.

    Order:
      1. $SNDR_MODEL_CONFIG_DIR (canonical override)
      2. $GENESIS_MODEL_CONFIG_DIR (legacy alias)
      3. $SNDR_HOME/model_configs/  (canonical, derived from operator root)
      4. $GENESIS_HOME/model_configs/  (legacy alias, derived)
      5. ~/.sndr/model_configs/  (canonical default)
      6. ~/.genesis/model_configs/  (legacy default — only if it exists)
    """
    from vllm.sndr_core.locations.project_paths import model_configs_user_dir
    return model_configs_user_dir()


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
    """Get one config by key, or None if not found in any tier.

    Phase 9 (V1 freeze): when the resolved key comes from the V1
    monolithic top-level `builtin/*.yaml` tier AND a V2 alias with the
    same shape exists (`prod-35b` ↔ `a5000-2x-35b-prod`), this function
    emits a single `DeprecationWarning`. The warning is informational
    only — V1 path keeps working through Phase 9 sunset; Phase 10 will
    sunset V1 loader after operator confirmation.
    """
    cfg = load_all().get(key)
    if cfg is not None and source_of(key) == "builtin":
        # Top-level builtin = V1 monolithic preset. V2 layered tiers
        # live under builtin/model/, builtin/hardware/, etc. — those
        # don't surface via load_all() because _load_dir uses *.yaml
        # (not recursive). So a hit on the top-level builtin tier is
        # by definition V1.
        _maybe_warn_v1_deprecation(key)
    return cfg


_V1_DEPRECATION_WARNED: set[str] = set()


def _maybe_warn_v1_deprecation(key: str) -> None:
    """Emit a one-time DeprecationWarning per V1 preset key.

    Phase 9 contract: warning is once-per-key-per-process so operators
    see it on first load but the warning doesn't flood logs on repeated
    `sndr launch` calls (e.g. CI sweeps that exercise many presets).
    Set `GENESIS_DISABLE_V1_DEPRECATION_WARNING=1` to silence entirely
    (release-engineering escape hatch for the freeze transition window).
    """
    import os
    if os.environ.get("GENESIS_DISABLE_V1_DEPRECATION_WARNING"):
        return
    if key in _V1_DEPRECATION_WARNED:
        return
    _V1_DEPRECATION_WARNED.add(key)
    import warnings
    warnings.warn(
        f"V1 monolithic preset key {key!r} is deprecated. "
        f"Prefer a V2 alias under model_configs/builtin/presets/ "
        f"(see `sndr hardware list` / `sndr model list-v2` / `sndr profile list`). "
        f"V1 loader stays functional during the Phase 9 freeze window.",
        DeprecationWarning,
        stacklevel=3,
    )


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


def path_for(key: str) -> Optional[Path]:
    """Return the YAML file path that provides `key`, or None.

    Walks user → community → builtin in that priority. Caller can write
    back into that file (e.g. `bench-and-update` updating reference_metrics).
    """
    for d in (_user_dir(), _COMMUNITY_DIR, _BUILTIN_DIR):
        if not d.is_dir():
            continue
        for yaml_path in sorted(d.glob("*.yaml")):
            try:
                cfg = load_yaml(yaml_path.read_text())
            except SchemaError:
                continue
            if cfg.key == key:
                return yaml_path
    return None
