# SPDX-License-Identifier: Apache-2.0
"""tools/kv_calc.py — standalone capacity calculator smoke tests."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_TOOL = _REPO / "tools" / "kv_calc.py"


def _run(args: list[str], **kwargs) -> tuple[int, str, str]:
    p = subprocess.run(
        [sys.executable, str(_TOOL), *args],
        capture_output=True, text=True, timeout=30, **kwargs,
    )
    return p.returncode, p.stdout, p.stderr


def test_kv_calc_help_returns_zero():
    rc, out, _ = _run(["--help"])
    assert rc == 0
    assert "VRAM capacity calculator" in out
    assert "--preset" in out and "--model" in out


def test_kv_calc_requires_source():
    """At least one of --preset/--model is required."""
    rc, _, err = _run([])
    assert rc != 0
    assert "--preset" in err or "--model" in err or "required" in err


def test_kv_calc_preset_unknown_returns_2():
    rc, _, err = _run(["--preset", "definitely-not-a-real-preset-xyz"])
    assert rc == 2
    assert "unknown preset" in err.lower()


def test_kv_calc_preset_35b_prod_human_output():
    """Live preset run on 35B PROD — model path doesn't exist on Mac
    but the breakdown still prints (KV/weights = 0 with warnings)."""
    rc, out, _ = _run(["--preset", "a5000-2x-35b-prod", "--gpu-vram", "24"])
    # Verdict GREEN on Mac (since weights+KV=0) → exit 0
    assert rc == 0
    assert "kv_calc — VRAM breakdown" in out
    assert "a5000-2x-35b-prod" in out
    assert "Utilization:" in out
    # Verdict line carries one of the labels
    assert "GREEN" in out or "YELLOW" in out or "RED" in out


def test_kv_calc_preset_27b_human_output():
    rc, out, _ = _run(["--preset", "a5000-2x-27b-int4-tq-k8v4", "--gpu-vram", "24"])
    assert rc == 0
    assert "27b-int4-tq-k8v4" in out


def test_kv_calc_json_output_well_formed():
    rc, out, _ = _run(["--preset", "a5000-2x-35b-prod", "--json"])
    assert rc == 0
    data = json.loads(out)
    assert data["preset_key"] == "a5000-2x-35b-prod"
    assert "components" in data
    assert "verdict" in data
    assert data["verdict"] in ("GREEN", "YELLOW", "RED", "n/a")


def test_kv_calc_ctx_override_via_k_suffix():
    """--ctx '128k' must be parsed as 128*1024."""
    rc, out, _ = _run([
        "--preset", "a5000-2x-35b-prod", "--ctx", "128k", "--json",
    ])
    assert rc == 0
    data = json.loads(out)
    assert data["ctx"] == 128 * 1024


def test_kv_calc_gpu_vram_default_24():
    rc, out, _ = _run(["--preset", "a5000-2x-35b-prod", "--json"])
    assert rc == 0
    data = json.loads(out)
    assert data["gpu_vram_gib"] == 24.0
