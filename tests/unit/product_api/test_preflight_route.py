# SPDX-License-Identifier: Apache-2.0
"""Tests for the GUI preflight fit-check route (/api/v1/preflight).

The route must mirror ``sndr preflight <preset>`` exactly (it reuses
``preflight_fit.evaluate_fit``), so the GUI pre-launch fit-check and the CLI
never diverge. These tests pin the single-card escape-hatch case from
docs/SINGLE_CARD.md (1× 24 GB rig vs a 2× preset -> gpu_count FAIL).
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from sndr.product_api.legacy.http_app import create_app  # noqa: E402

_PRESET = "prod-qwen3.6-35b-balanced"


def _client() -> TestClient:
    return TestClient(create_app(allowed_origins=()))


def test_single_card_fake_rig_fails_gpu_count():
    """A single 24 GB card vs a 2× preset: gpu_count FAILs, VRAM/SM pass,
    verdict CANNOT RUN — the exact docs/SINGLE_CARD.md output shape."""
    r = _client().get(
        "/api/v1/preflight",
        params={"preset_id": _PRESET, "fake_gpus": "RTX 3090:24576:8.6"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["preset"] == _PRESET
    assert body["can_run"] is False
    assert body["verdict"] == "CANNOT RUN"
    assert body["rig"]["gpu_count"] == 1
    assert body["rig"]["min_vram_gb"] == 24

    by_dim = {c["dimension"]: c for c in body["checks"]}
    assert by_dim["gpu_count"]["status"] == "fail"
    assert by_dim["vram"]["status"] == "pass"
    assert by_dim["cuda_capability"]["status"] == "pass"
    # The required envelope is surfaced so the GUI can render "needs 2× 24GB".
    assert body["required"]["min_gpu_count"] == 2
    assert body["required"]["tensor_parallel"] == 2


def test_builtin_rig_two_cards_can_run():
    """The 2× A5000 builtin rig clears the 2× preset (CAN RUN), offline."""
    r = _client().get(
        "/api/v1/preflight",
        params={"preset_id": _PRESET, "rig": "a5000-2x-24gbvram-16cpu-128gbram"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["can_run"] is True
    assert body["verdict"] == "CAN RUN"
    assert body["rig_source"].startswith("rig:")


def test_unknown_preset_is_404():
    r = _client().get("/api/v1/preflight", params={"preset_id": "no-such-preset"})
    assert r.status_code == 404


def test_unknown_rig_is_404():
    r = _client().get(
        "/api/v1/preflight",
        params={"preset_id": _PRESET, "rig": "no-such-rig"},
    )
    assert r.status_code == 404
