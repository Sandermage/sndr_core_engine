# SPDX-License-Identifier: Apache-2.0
"""T5 (UNIFIED_CONFIG plan 2026-05-09) — lockfile presence + shape tests."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]


def _read(name: str) -> str:
    p = _REPO / name
    assert p.exists(), f"lockfile missing: {p}"
    return p.read_text()


# ─── Files exist

def test_runtime_lock_exists():
    body = _read("requirements-runtime.lock")
    assert "pyyaml==" in body
    assert "packaging==" in body


def test_dev_lock_exists():
    body = _read("requirements-dev.lock")
    assert "pytest==" in body
    assert "cryptography==" in body


def test_dev_lock_includes_runtime():
    """dev.lock must `-r requirements-runtime.lock` to inherit."""
    body = _read("requirements-dev.lock")
    assert "-r requirements-runtime.lock" in body


# ─── All lines pin exactly

_PIN_LINE = re.compile(r"^([a-z0-9_\-\.]+)\s*==\s*([0-9][0-9a-z\.\-]*)\s*$",
                       re.IGNORECASE)


def _strict_pins(body: str) -> list[tuple[str, str]]:
    out = []
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("-r"):
            continue
        m = _PIN_LINE.match(s)
        assert m, f"line not a strict ==pin: {line!r}"
        out.append((m.group(1).lower(), m.group(2)))
    return out


def test_runtime_lock_pins_are_strict():
    pins = _strict_pins(_read("requirements-runtime.lock"))
    # All lines must be exact pins
    assert len(pins) >= 2
    names = [n for n, _ in pins]
    assert "pyyaml" in names
    assert "packaging" in names


def test_dev_lock_pins_are_strict():
    pins = _strict_pins(_read("requirements-dev.lock"))
    names = [n for n, _ in pins]
    assert "pytest" in names
    assert "pytest-cov" in names
    assert "cryptography" in names
    assert "requests" in names


# ─── Lockfile mirrors PROD config in-container deps

def test_runtime_lock_mirrors_in_container_versions():
    """Y1+B6: pandas/scipy/xxhash versions in the runtime lockfile must
    match the canonical PROD model_config package_versions block. If
    you bump one, you must bump the other."""
    body = _read("requirements-runtime.lock")
    assert "pandas==2.2.3" in body
    assert "scipy==1.14.1" in body
    assert "xxhash==3.5.0" in body
