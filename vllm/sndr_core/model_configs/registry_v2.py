# SPDX-License-Identifier: Apache-2.0
"""V2 layered registry — YAML loaders + alias resolver (PROJECT_ROADMAP_V2 Phase 1).

Discovery layout (per § 4.4):

  vllm/sndr_core/model_configs/builtin/
  ├── model/<id>.yaml         → ModelDef
  ├── hardware/<id>.yaml      → HardwareDef
  ├── profile/<id>.yaml       → ProfileDef
  └── presets/<alias>.yaml    → triplet {model, hardware, profile?, runtime?}

  vllm/sndr_core/model_configs/community/
  ├── hardware/<id>.yaml      → HardwareDef (community-tier)
  └── profile/<id>.yaml       → ProfileDef (community-tier)

`load_alias(name)` resolves a preset alias → composed V1 ModelConfig.
`compose_by_ids(model_id, hw_id, profile_id, runtime)` is the
non-alias entry point used by `sndr launch --model X --hardware Y ...`.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Optional

from .schema import ModelConfig, SchemaError
from .schema_v2 import (
    HardwareDef,
    ModelDef,
    PatchManifest,
    ProfileDef,
)
from .compose import compose


__all__ = [
    "REPO_ROOT_HINT",
    "load_model",
    "load_hardware",
    "load_profile",
    "load_alias",
    "compose_by_ids",
    "list_models",
    "list_hardware",
    "list_profiles",
]


# Resolved at import time so tests can monkeypatch.
_PKG_ROOT = Path(__file__).resolve().parent
REPO_ROOT_HINT = _PKG_ROOT


# ─── Helpers ─────────────────────────────────────────────────────────────


def _yaml_safe_load(path: Path) -> dict:
    try:
        import yaml
    except ImportError as e:  # pragma: no cover — pyyaml is a hard dep
        raise RuntimeError(
            "V2 registry requires `pyyaml` — `pip install pyyaml`"
        ) from e
    if not path.is_file():
        raise SchemaError(f"V2 YAML not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise SchemaError(f"{path}: top-level YAML must be a mapping")
    return data


def _resolve_field_type(cls, field_name: str):
    """Resolve a dataclass field's runtime type, unwrapping Optional / Union.

    PEP 563 `from __future__ import annotations` defers annotation
    resolution → `dataclasses.Field.type` is a string. We use
    `typing.get_type_hints()` to materialise it once per class, then
    strip Optional/Union[X, None] down to X for nested-dataclass detection.
    """
    import typing
    try:
        hints = typing.get_type_hints(cls)
    except Exception:
        return None
    t = hints.get(field_name)
    if t is None:
        return None
    # Optional[X] = Union[X, None] → return X if exactly one non-None arg.
    origin = typing.get_origin(t)
    if origin is typing.Union:
        args = [a for a in typing.get_args(t) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return t


def _dataclass_from_dict(cls, data: dict):
    """Construct a dataclass instance from a YAML-loaded dict.

    Recursively materialises nested dataclass fields. PEP 563 annotations
    are resolved via `_resolve_field_type` so we get real classes, not
    string forward references.

    List/tuple fields of dataclass element type are also materialised
    (e.g. `target_files: list[PatchTargetFile]`).
    """
    if not dataclasses.is_dataclass(cls):
        return data
    import typing
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        ftype = _resolve_field_type(cls, f.name)
        if value is None:
            kwargs[f.name] = None
            continue
        # Nested dataclass {dict} → recurse.
        if isinstance(value, dict) and dataclasses.is_dataclass(ftype):
            kwargs[f.name] = _dataclass_from_dict(ftype, value)
            continue
        # list[Dataclass] → recurse per element.
        if isinstance(value, list) and ftype is not None:
            origin = typing.get_origin(ftype)
            if origin in (list, tuple):
                args = typing.get_args(ftype)
                if args and dataclasses.is_dataclass(args[0]):
                    kwargs[f.name] = [
                        _dataclass_from_dict(args[0], v) if isinstance(v, dict) else v
                        for v in value
                    ]
                    continue
        # dict[str, Dataclass] → recurse per value.
        # Phase A (2026-05-16): added so ModelDef.patches_attribution
        # `dict[str, PatchAttribution]` materialises through YAML load.
        if isinstance(value, dict) and ftype is not None:
            origin = typing.get_origin(ftype)
            if origin is dict:
                args = typing.get_args(ftype)
                if len(args) == 2 and dataclasses.is_dataclass(args[1]):
                    kwargs[f.name] = {
                        k: (_dataclass_from_dict(args[1], v) if isinstance(v, dict) else v)
                        for k, v in value.items()
                    }
                    continue
        kwargs[f.name] = value
    return cls(**kwargs)


# ─── Layer loaders ───────────────────────────────────────────────────────


def _builtin_dir(layer: str) -> Path:
    return _PKG_ROOT / "builtin" / layer


def _community_dir(layer: str) -> Path:
    return _PKG_ROOT / "community" / layer


def load_model(model_id: str) -> ModelDef:
    """Load `builtin/model/<id>.yaml` into a validated ModelDef."""
    path = _builtin_dir("model") / f"{model_id}.yaml"
    data = _yaml_safe_load(path)
    obj = _dataclass_from_dict(ModelDef, data)
    obj.validate()
    return obj


def load_hardware(hw_id: str) -> HardwareDef:
    """Load `builtin/hardware/<id>.yaml` → HardwareDef. Falls back to
    `community/hardware/<id>.yaml` if not in builtin (Q3 hybrid)."""
    candidates = [
        _builtin_dir("hardware") / f"{hw_id}.yaml",
        _community_dir("hardware") / f"{hw_id}.yaml",
    ]
    for p in candidates:
        if p.is_file():
            data = _yaml_safe_load(p)
            obj = _dataclass_from_dict(HardwareDef, data)
            obj.validate()
            return obj
    raise SchemaError(
        f"hardware {hw_id!r} not found in builtin/ or community/ directories"
    )


def load_profile(profile_id: str) -> ProfileDef:
    """Load `builtin/profile/<id>.yaml` → ProfileDef. Falls back to
    `community/profile/<id>.yaml`."""
    candidates = [
        _builtin_dir("profile") / f"{profile_id}.yaml",
        _community_dir("profile") / f"{profile_id}.yaml",
    ]
    for p in candidates:
        if p.is_file():
            data = _yaml_safe_load(p)
            obj = _dataclass_from_dict(ProfileDef, data)
            obj.validate()
            return obj
    raise SchemaError(
        f"profile {profile_id!r} not found in builtin/ or community/"
    )


def load_patch_manifest(path: Path) -> PatchManifest:
    """Load a `plugins/community/<user>/<id>/manifest.yaml` (community SDK).

    Path is explicit because community plugins live outside the
    model_configs tree (see PROJECT_ROADMAP_V2 § 4.4).
    """
    data = _yaml_safe_load(path)
    obj = _dataclass_from_dict(PatchManifest, data)
    obj.validate()
    return obj


# ─── Listing ─────────────────────────────────────────────────────────────


def _list_yaml_ids(directory: Path) -> list[str]:
    if not directory.is_dir():
        return []
    return sorted(
        p.stem for p in directory.glob("*.yaml")
        if p.is_file() and not p.stem.startswith("_")
    )


def list_models() -> list[str]:
    return _list_yaml_ids(_builtin_dir("model"))


def list_hardware() -> list[str]:
    return sorted(set(
        _list_yaml_ids(_builtin_dir("hardware"))
        + _list_yaml_ids(_community_dir("hardware"))
    ))


def list_profiles(parent_model: Optional[str] = None) -> list[str]:
    """List profile ids; optionally filter to those whose `parent_model`
    matches the given model id (loads each profile to inspect)."""
    ids = sorted(set(
        _list_yaml_ids(_builtin_dir("profile"))
        + _list_yaml_ids(_community_dir("profile"))
    ))
    if parent_model is None:
        return ids
    out: list[str] = []
    for pid in ids:
        try:
            if load_profile(pid).parent_model == parent_model:
                out.append(pid)
        except SchemaError:
            continue
    return out


# ─── Alias + compose entry points ────────────────────────────────────────


def _alias_dir() -> Path:
    return _PKG_ROOT / "builtin" / "presets"


def load_alias(alias: str) -> ModelConfig:
    """Resolve `presets/<alias>.yaml` (a 3-pointer file) → composed V1 ModelConfig.

    Alias YAML format:
      model:    <model_id>            # required
      hardware: <hardware_id>         # required
      profile:  <profile_id>          # optional
      runtime:  <runtime>             # optional override (docker/podman/bare-metal)
    """
    path = _alias_dir() / f"{alias}.yaml"
    data = _yaml_safe_load(path)
    model_id = data.get("model")
    hw_id = data.get("hardware")
    if not model_id or not hw_id:
        raise SchemaError(
            f"alias {alias!r}: `model:` and `hardware:` are required pointers"
        )
    return compose_by_ids(
        model_id=model_id,
        hardware_id=hw_id,
        profile_id=data.get("profile"),
        runtime=data.get("runtime"),
    )


def compose_by_ids(
    model_id: str,
    hardware_id: str,
    profile_id: Optional[str] = None,
    runtime: Optional[str] = None,
) -> ModelConfig:
    """Load each layer by id and produce the composed V1 ModelConfig."""
    model = load_model(model_id)
    hardware = load_hardware(hardware_id)
    profile = load_profile(profile_id) if profile_id else None
    return compose(model, hardware, profile, runtime_override=runtime)
