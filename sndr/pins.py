# SPDX-License-Identifier: Apache-2.0
"""Single-source-of-truth loader for the vLLM pins Genesis targets.

Reads ``sndr/pins.yaml`` and exposes the current / rollback / stable pins plus
the derived operational handles. Every place that needs "the current pin" — the
boot-smoke restore container, the drift-watcher version gate, the bump script,
the consistency audit — reads it from here instead of hand-copying the literal.

The downstream allowlists (guards.KNOWN_GOOD_VLLM_PINS, audit_v2
ALLOWED_MODELDEF_PINS, test_pin_gate EXPECTED_PINS) are intentionally NOT derived
from this file: they are cumulative, differently-scoped histories with per-pin
validation receipts. Instead ``scripts/audit_pin_consistency.py`` asserts the
CURRENT pin here is a member of each — which catches the real failure mode (a
bump that forgot one list) without flattening those histories.
"""
from __future__ import annotations

import functools
from pathlib import Path

_PINS_YAML = Path(__file__).resolve().parent / "pins.yaml"


@functools.lru_cache(maxsize=1)
def _load() -> dict:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - yaml is a base dep
        raise RuntimeError("sndr.pins requires pyyaml (a base dependency)") from exc
    with _PINS_YAML.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    for key in ("current", "rollback", "canonical_substring"):
        if not data.get(key):
            raise ValueError(f"sndr/pins.yaml missing required key {key!r}")
    return data


def current() -> str:
    """The setuptools_scm version string of the deployed pin."""
    return _load()["current"]


def rollback() -> str:
    """The retained previous pin (rollback bucket)."""
    return _load()["rollback"]


def stable_release() -> str | None:
    """The stable release pin (LTS slot), or None if unset."""
    return _load().get("stable_release")


def canonical_substring() -> str:
    """Substring uniquely identifying the current pin in version strings."""
    return _load()["canonical_substring"]


def current_sha_short() -> str:
    return _load().get("current_sha_short", "")


def current_sha_full() -> str:
    """Full 40-char upstream commit SHA for the current pin (git fetch@sha)."""
    return _load().get("current_sha_full", "")


def current_image() -> str | None:
    return _load().get("current_image")


def current_image_digest() -> str:
    """Rig RepoDigest of the current image (repo@sha256:<64-hex>).

    The digest is the HIGHEST-precedence image reference at render time
    (effective_image_ref = image_digest or image) — a stale digest silently
    boots the rollback pin even when the image tag is current (2026-07-04
    audit CRIT). Captured on bump via docker inspect RepoDigests."""
    return _load().get("current_image_digest", "")


def current_container() -> str | None:
    """Default live container name for restore/boot-smoke (pin-coupled)."""
    return _load().get("current_container")


def current_anchor_dir() -> str:
    """Directory name under sndr/engines/vllm/pins/ for the current pin."""
    return _load().get("current_anchor_dir", "")


def live_pins() -> list[str]:
    """The <=2 rolling nightly pins (current + rollback) — the live set."""
    return [current(), rollback()]


__all__ = [
    "current", "rollback", "stable_release", "canonical_substring",
    "current_sha_short", "current_sha_full", "current_image",
    "current_image_digest", "current_container",
    "current_anchor_dir", "live_pins",
]
