# SPDX-License-Identifier: Apache-2.0
"""Tests for the GPU power-cap write path + its double-gated HTTP routes.

The module is exercised through a fake ``Runner`` (no real nvidia-smi), mirroring
``test_gpu_telemetry``'s runner-driven style. The routes are exercised through the
FastAPI TestClient to pin the apply_on + confirm gates and the validation errors.
"""
from __future__ import annotations

import pytest

from sndr.product_api.legacy import power_cap as P

# Two GPUs with DIFFERENT default/min/max — the realistic dual-card case the
# club-3090 contract handles (default_limit can differ per card, so reset must
# read each card's own default rather than hardcoding one value).
_LIMITS_CSV = (
    "0, 250.00, 370.00, 100.00, 390.00\n"
    "1, 250.00, 420.00, 100.00, 450.00\n"
)


def _runner(applied: list[tuple[int, int]], *, fail_apply: bool = False,
            limits_csv: str = _LIMITS_CSV, limits_rc: int = 0):
    """Build a fake nvidia-smi runner. Records every `-pl` apply as (index, watts)
    in ``applied`` and reflects the new value back in subsequent limit reads."""
    state: dict[int, float] = {}

    def run(argv: list[str]) -> "tuple[int, str, str]":
        if argv[:1] == ["nvidia-smi"] and any(a.startswith("--query-gpu=") for a in argv):
            if limits_rc != 0:
                return limits_rc, "", "nvidia-smi: not found"
            # Reflect any applied caps into the enforced-limit column.
            rows = []
            for line in limits_csv.strip().splitlines():
                cells = [c.strip() for c in line.split(",")]
                idx = int(float(cells[0]))
                lim = state.get(idx, float(cells[1]))
                rows.append(f"{idx}, {lim:.2f}, {cells[2]}, {cells[3]}, {cells[4]}")
            return 0, "\n".join(rows) + "\n", ""
        if argv[:2] == ["nvidia-smi", "-i"] and "-pl" in argv:
            idx = int(argv[2])
            watts = int(argv[argv.index("-pl") + 1])
            if fail_apply:
                return 1, "", "Setting power limit is not supported"
            applied.append((idx, watts))
            state[idx] = float(watts)
            return 0, "", ""
        return 127, "", "unexpected argv"

    return run


# ── module: read_limits ──────────────────────────────────────────────────────

def test_read_limits_parses_per_gpu():
    gpus = P.read_limits(_runner([]))
    assert [g.index for g in gpus] == [0, 1]
    assert gpus[0].default_limit == 370.0 and gpus[0].max_limit == 390.0
    assert gpus[1].default_limit == 420.0 and gpus[1].min_limit == 100.0


def test_read_limits_errors_when_no_gpu():
    with pytest.raises(P.PowerCapError) as ei:
        P.read_limits(_runner([], limits_rc=127))
    assert ei.value.status == 502


# ── module: apply_cap (set) ─────────────────────────────────────────────────

def test_apply_cap_sets_all_gpus_within_range():
    applied: list[tuple[int, int]] = []
    out = P.apply_cap(_runner(applied), watts=300)
    assert out.ok and out.action == "set"
    assert sorted(applied) == [(0, 300), (1, 300)]
    # New enforced limit is read back and attached per result.
    assert all(r.applied for r in out.results)
    assert {r.index: r.limits["limit"] for r in out.results} == {0: 300.0, 1: 300.0}


def test_apply_cap_single_gpu_only():
    applied: list[tuple[int, int]] = []
    out = P.apply_cap(_runner(applied), watts=280, gpu_index=1)
    assert out.ok and applied == [(1, 280)]
    assert [r.index for r in out.results] == [1]


def test_apply_cap_rejects_above_max_before_mutating():
    applied: list[tuple[int, int]] = []
    with pytest.raises(P.PowerCapError) as ei:
        P.apply_cap(_runner(applied), watts=999, gpu_index=0)  # max is 390
    assert "exceeds" in str(ei.value)
    assert applied == []  # validated up front — nothing was applied


def test_apply_cap_rejects_below_min():
    with pytest.raises(P.PowerCapError) as ei:
        P.apply_cap(_runner([]), watts=50, gpu_index=0)  # min is 100
    assert "below" in str(ei.value)


def test_apply_cap_unknown_gpu_is_404():
    with pytest.raises(P.PowerCapError) as ei:
        P.apply_cap(_runner([]), watts=300, gpu_index=7)
    assert ei.value.status == 404


# ── module: apply_cap (reset) ───────────────────────────────────────────────

def test_reset_applies_each_cards_own_default():
    applied: list[tuple[int, int]] = []
    out = P.apply_cap(_runner(applied), reset=True)
    assert out.ok and out.action == "reset"
    # GPU 0 default 370, GPU 1 default 420 — different per card.
    assert sorted(applied) == [(0, 370), (1, 420)]


def test_reset_and_watts_are_mutually_exclusive():
    with pytest.raises(P.PowerCapError):
        P.apply_cap(_runner([]), watts=300, reset=True)
    with pytest.raises(P.PowerCapError):
        P.apply_cap(_runner([]))  # neither given


def test_apply_failure_surfaces_not_ok():
    out = P.apply_cap(_runner([], fail_apply=True), watts=300, gpu_index=0)
    assert not out.ok
    assert out.results[0].applied is False
    assert "not supported" in (out.error or "").lower()


# ── routes: gating + validation ──────────────────────────────────────────────

def _client(*, enable_apply: bool):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from sndr.product_api.legacy.http_app import create_app
    return TestClient(create_app(allowed_origins=(), enable_apply=enable_apply))


def test_route_blocked_when_apply_disabled():
    r = _client(enable_apply=False).post(
        "/api/v1/host/power-cap", json={"watts": 300, "confirm": True})
    assert r.status_code == 403


def test_route_requires_confirm_when_apply_enabled():
    r = _client(enable_apply=True).post(
        "/api/v1/host/power-cap", json={"watts": 300})
    assert r.status_code == 400
    assert "confirm" in r.json()["detail"].lower()


def test_route_rejects_bad_watts():
    r = _client(enable_apply=True).post(
        "/api/v1/host/power-cap", json={"watts": "banana", "confirm": True})
    assert r.status_code == 400


def test_route_applies_via_module(monkeypatch):
    """Route is reached past the gates and calls the module; we stub the module
    so the test never shells out to a real nvidia-smi."""
    captured: dict[str, object] = {}

    def fake_apply_local(*, watts, reset, gpu_index):
        captured.update(watts=watts, reset=reset, gpu_index=gpu_index)
        return P.PowerCapOutcome(ok=True, action="set",
                                 results=(P.GpuCapResult(index=0, requested_watts=300, applied=True),),
                                 limits=({"index": 0, "limit": 300.0},))

    monkeypatch.setattr(P, "apply_cap_local", fake_apply_local)
    r = _client(enable_apply=True).post(
        "/api/v1/host/power-cap", json={"watts": 300, "gpu_index": 0, "confirm": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["action"] == "set"
    assert captured == {"watts": 300, "reset": False, "gpu_index": 0}


def test_route_reset_maps_to_module(monkeypatch):
    captured: dict[str, object] = {}

    def fake_apply_local(*, watts, reset, gpu_index):
        captured.update(watts=watts, reset=reset, gpu_index=gpu_index)
        return P.PowerCapOutcome(ok=True, action="reset")

    monkeypatch.setattr(P, "apply_cap_local", fake_apply_local)
    r = _client(enable_apply=True).post(
        "/api/v1/host/power-cap", json={"watts": "default", "confirm": True})
    assert r.status_code == 200, r.text
    assert captured == {"watts": None, "reset": True, "gpu_index": None}
