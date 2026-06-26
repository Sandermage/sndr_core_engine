# SPDX-License-Identifier: Apache-2.0
"""Tests for `scripts/audit_runtime_hook_ratchet.py` — P2.3 lifecycle
ratchet for runtime-hook patches.

Contract:

  • Every `lifecycle: stable` patch MUST declare `stable_kind`.
  • `stable_kind` ∈ {"text-patch", "runtime-hook"}.
  • If `stable_kind == "runtime-hook"`, `production_validated_pins`
    is a list of ≥2 (genesis_pin, vllm_pin) string tuples; each
    pin non-empty.
  • Live committed PATCH_REGISTRY (currently 2 stable: PN35, PN33)
    passes the ratchet.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "audit_runtime_hook_ratchet.py"


def _import():
    name = "_audit_runtime_hook_ratchet_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ─── Schema constants ─────────────────────────────────────────────────


class TestConstants:
    def test_allowed_stable_kinds(self):
        mod = _import()
        assert mod.ALLOWED_STABLE_KINDS == frozenset(
            {"text-patch", "runtime-hook"},
        )

    def test_min_runtime_hook_pins_is_two(self):
        mod = _import()
        assert mod.MIN_RUNTIME_HOOK_PINS == 2


# ─── Per-patch checker ────────────────────────────────────────────────


class TestCheckOnePatch:
    def test_text_patch_with_kind_passes(self):
        mod = _import()
        r = mod.check_one_patch("PN-X", {
            "lifecycle": "stable",
            "stable_kind": "text-patch",
        })
        assert r.passed is True

    def test_runtime_hook_with_two_pins_passes(self):
        mod = _import()
        r = mod.check_one_patch("PN-Y", {
            "lifecycle": "stable",
            "stable_kind": "runtime-hook",
            "production_validated_pins": [
                ["v11.0.0", "0.20.2rc1.dev209+g5536fc0c0"],
                ["v11.0.1", "0.20.2rc1.dev209+g5536fc0c0"],
            ],
        })
        assert r.passed is True

    def test_missing_stable_kind_fails(self):
        mod = _import()
        r = mod.check_one_patch("PN-MISSING", {
            "lifecycle": "stable",
        })
        assert r.passed is False
        assert any("missing required field `stable_kind`" in v
                   for v in r.violations)

    def test_unknown_stable_kind_fails(self):
        mod = _import()
        r = mod.check_one_patch("PN-WRONG", {
            "lifecycle": "stable",
            "stable_kind": "magic",
        })
        assert r.passed is False
        assert any("magic" in v for v in r.violations)

    def test_runtime_hook_no_pins_fails(self):
        mod = _import()
        r = mod.check_one_patch("PN-NO-PINS", {
            "lifecycle": "stable",
            "stable_kind": "runtime-hook",
        })
        assert r.passed is False
        assert any("production_validated_pins" in v for v in r.violations)

    def test_runtime_hook_single_pin_fails(self):
        mod = _import()
        r = mod.check_one_patch("PN-ONE-PIN", {
            "lifecycle": "stable",
            "stable_kind": "runtime-hook",
            "production_validated_pins": [["v11.0.0", "0.20.2"]],
        })
        assert r.passed is False
        assert any("requires ≥ 2" in v for v in r.violations)

    def test_runtime_hook_empty_genesis_pin_fails(self):
        mod = _import()
        r = mod.check_one_patch("PN-EMPTY-G", {
            "lifecycle": "stable",
            "stable_kind": "runtime-hook",
            "production_validated_pins": [
                ["", "0.20.2"],
                ["v11.0.0", "0.20.2"],
            ],
        })
        assert r.passed is False
        assert any("genesis_pin" in v and "empty" in v
                   for v in r.violations)

    def test_runtime_hook_empty_vllm_pin_fails(self):
        mod = _import()
        r = mod.check_one_patch("PN-EMPTY-V", {
            "lifecycle": "stable",
            "stable_kind": "runtime-hook",
            "production_validated_pins": [
                ["v11.0.0", ""],
                ["v11.0.0", "0.20.2"],
            ],
        })
        assert r.passed is False
        assert any("vllm_pin" in v and "empty" in v
                   for v in r.violations)

    def test_runtime_hook_malformed_tuple_fails(self):
        mod = _import()
        r = mod.check_one_patch("PN-BAD-TUPLE", {
            "lifecycle": "stable",
            "stable_kind": "runtime-hook",
            "production_validated_pins": [
                ["v11.0.0", "0.20.2", "extra"],
                ["v11.0.0", "0.20.2"],
            ],
        })
        assert r.passed is False
        assert any("(genesis_pin, vllm_pin) tuple" in v
                   for v in r.violations)

    def test_non_list_pins_fails(self):
        mod = _import()
        r = mod.check_one_patch("PN-NOT-LIST", {
            "lifecycle": "stable",
            "stable_kind": "runtime-hook",
            "production_validated_pins": "v11.0.0",   # string, not list
        })
        assert r.passed is False
        assert any("expected list" in v for v in r.violations)


# ─── Whole-registry audit (synthetic + live) ──────────────────────────


class TestAudit:
    def test_synthetic_registry_mixed(self):
        mod = _import()
        synth = {
            "PN-A": {"lifecycle": "stable", "stable_kind": "text-patch"},
            "PN-B": {
                "lifecycle": "stable", "stable_kind": "runtime-hook",
                "production_validated_pins": [
                    ["v1", "vA"], ["v2", "vB"],
                ],
            },
            "PN-C": {"lifecycle": "stable"},  # missing stable_kind
            "PN-EXP": {"lifecycle": "experimental"},  # not stable, skipped
        }
        results = mod.audit_runtime_hook_ratchet(synth)
        # Only stable patches checked (3 of 4)
        assert len(results) == 3
        statuses = {r.patch_id: r.passed for r in results}
        assert statuses == {"PN-A": True, "PN-B": True, "PN-C": False}


class TestLiveRegistry:
    def test_live_registry_clean(self):
        """Currently 2 stable patches (PN33, PN35) must declare
        stable_kind=text-patch and pass ratchet."""
        mod = _import()
        results = mod.audit_runtime_hook_ratchet()
        failed = [r for r in results if not r.passed]
        assert failed == [], "\n".join(
            f"  {r.patch_id}: {r.violations}" for r in failed
        )
        # Spot-check: PN35 + PN33 present and stable
        ids = {r.patch_id for r in results}
        assert "PN35" in ids
        assert "PN33" in ids


# ─── Script CLI ────────────────────────────────────────────────────────


class TestScriptCLI:
    def test_cli_zero(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout

    def test_cli_json_shape(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--json"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert "total_stable" in payload
        assert "allowed_stable_kinds" in payload
        assert "min_runtime_hook_pins" in payload
        assert payload["min_runtime_hook_pins"] == 2
        assert payload["failed"] == 0
