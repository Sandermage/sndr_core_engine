# SPDX-License-Identifier: Apache-2.0
"""CPU-only unit tests for PN38 — DFlash drafter quantization (PR #40425
backport) after the 2026-06-11 Site B retirement.

Contract under test (preflight residual triage action plan §1b):

  * Site B TextPatch (``pN38_b_pass_quant_config``) is no longer
    registered in ``sub_patches``: pin 0.22.1rc1.dev259+g303916e93
    plumbs quant_config natively (pristine qwen3_dflash.py:228 init +
    :252 decoder-layer kwarg). Re-applying B would inject a duplicate
    ``quant_config=`` keyword argument → SyntaxError on model import.
  * The B anchor/replacement constants stay in the module for
    git-history reference (P78 Site A convention).
  * ``apply()`` carries an upstream-presence guard: BOTH native Site B
    lines must be present in the target, else a loud skip with an
    explicit reason — never a partial A/C/D application on a pin that
    lacks native quant_config plumbing.
  * The surviving Site D anchor (``pN38_d_quant_fallback``) is recorded
    byte-exactly for the current pin in the committed anchor manifest
    (CI-runnable, replaces the old macOS-only pristine-tree
    green-by-skip byte-check).
  * Site A/C anchor uniqueness against the live pristine source is a
    documented container-gate (installed vllm); their drift on the
    current pin is owned by the anchor-SOT drift.rej gate (see the module
    note below), not re-asserted here.

No torch / CUDA dependency required.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _import_patch():
    from sndr.engines.vllm.patches.spec_decode import (
        pn38_dflash_quant_drafter as p,
    )
    return p


# ─── Site B retirement: registration shape ─────────────────────────────


class TestSiteBRetired:
    def test_sub_patches_are_a_c_d_only(self, monkeypatch, tmp_path):
        p = _import_patch()
        target = tmp_path / "qwen3_dflash.py"
        target.write_text("# stand-in\n", encoding="utf-8")
        monkeypatch.setattr(p, "resolve_vllm_file", lambda rel: target)
        patcher = p._make_patcher()
        assert patcher is not None
        names = [sp.name for sp in patcher.sub_patches]
        assert "pN38_b_pass_quant_config" not in names
        assert names == [
            "pN38_a_qkv_proj_call",
            "pN38_c_conditional_fused_kv",
            "pN38_d_quant_fallback",
        ]

    def test_site_b_constants_kept_for_git_history(self):
        # P78 Site A convention: constants stay in the module as
        # commented history even though not registered in sub_patches.
        p = _import_patch()
        assert isinstance(p.PN38_B_ANCHOR, str)
        assert p.PN38_B_ANCHOR
        assert isinstance(p.PN38_B_REPLACEMENT, str)
        assert p.PN38_B_REPLACEMENT

    def test_native_guard_constants_exist(self):
        p = _import_patch()
        assert "get_draft_quant_config(vllm_config)" in p.PN38_NATIVE_QUANT_INIT
        assert "quant_config=self.quant_config," in p.PN38_NATIVE_QUANT_KWARG


# ─── Upstream-presence guard helper ─────────────────────────────────────


class TestNativeSiteBStatus:
    def test_both_lines_present_passes(self):
        p = _import_patch()
        content = p.PN38_NATIVE_QUANT_INIT + p.PN38_NATIVE_QUANT_KWARG
        ok, reason = p._native_site_b_status(content)
        assert ok is True
        assert reason

    def test_missing_init_line_fails(self):
        p = _import_patch()
        ok, reason = p._native_site_b_status(p.PN38_NATIVE_QUANT_KWARG)
        assert ok is False
        assert "get_draft_quant_config" in reason

    def test_missing_kwarg_line_fails(self):
        p = _import_patch()
        ok, reason = p._native_site_b_status(p.PN38_NATIVE_QUANT_INIT)
        assert ok is False
        assert "quant_config=self.quant_config" in reason

    def test_empty_content_fails_with_both_named(self):
        p = _import_patch()
        ok, reason = p._native_site_b_status("")
        assert ok is False
        assert "get_draft_quant_config" in reason
        assert "quant_config=self.quant_config" in reason


# ─── apply() end-to-end on synthetic target ─────────────────────────────


def _force_enabled(monkeypatch, p, tmp_path, target):
    from sndr import dispatcher

    monkeypatch.setattr(
        dispatcher, "should_apply", lambda patch_id: (True, "test-forced")
    )
    monkeypatch.setattr(
        dispatcher, "log_decision", lambda *a, **kw: None
    )
    monkeypatch.setattr(p, "vllm_install_root", lambda: str(tmp_path))
    monkeypatch.setattr(p, "resolve_vllm_file", lambda rel: target)


def _synthetic_target_content(p, *, with_native: bool) -> str:
    parts = ["# synthetic qwen3_dflash.py stand-in\n"]
    if with_native:
        parts += [p.PN38_NATIVE_QUANT_INIT, p.PN38_NATIVE_QUANT_KWARG]
    parts += [p.PN38_A_ANCHOR, p.PN38_C_ANCHOR, p.PN38_D_ANCHOR]
    return "".join(parts)


class TestApplyGuard:
    def test_apply_skips_loudly_when_native_lines_absent(
        self, monkeypatch, tmp_path
    ):
        p = _import_patch()
        target = tmp_path / "qwen3_dflash.py"
        target.write_text(
            _synthetic_target_content(p, with_native=False), encoding="utf-8"
        )
        _force_enabled(monkeypatch, p, tmp_path, target)
        status, reason = p.apply()
        assert status == "skipped"
        # Loud, explicit reason: names the guard and the missing lines.
        assert "upstream-presence guard" in reason
        assert "get_draft_quant_config" in reason
        # Target untouched — no partial A/C/D application.
        post = target.read_text(encoding="utf-8")
        assert "[Genesis PN38" not in post

    def test_apply_succeeds_with_native_lines(self, monkeypatch, tmp_path):
        p = _import_patch()
        target = tmp_path / "qwen3_dflash.py"
        target.write_text(
            _synthetic_target_content(p, with_native=True), encoding="utf-8"
        )
        _force_enabled(monkeypatch, p, tmp_path, target)
        status, reason = p.apply()
        assert status == "applied", reason
        post = target.read_text(encoding="utf-8")
        assert "[Genesis PN38 Site A]" in post
        assert "[Genesis PN38 Site C]" in post
        assert "[Genesis PN38 Site D]" in post
        # The retired Site B must NOT have injected a second kwarg:
        # exactly the one native occurrence survives.
        assert post.count("quant_config=self.quant_config,") == 1

    def test_second_apply_is_idempotent(self, monkeypatch, tmp_path):
        p = _import_patch()
        target = tmp_path / "qwen3_dflash.py"
        target.write_text(
            _synthetic_target_content(p, with_native=True), encoding="utf-8"
        )
        _force_enabled(monkeypatch, p, tmp_path, target)
        status, _ = p.apply()
        assert status == "applied"
        status2, reason2 = p.apply()
        assert status2 == "skipped"
        assert "already applied" in reason2


# ─── Current-pin manifest evidence (CI-runnable) ────────────────────────


def test_d_anchor_recorded_in_current_pin_manifest():
    """MIGRATED from the macOS-only pristine-tree green-by-skip
    byte-check (audit finding #14). The surviving Site D anchor is recorded
    byte-exactly for the current pin; tying the LIVE patcher constant to the
    manifest md5+length RUNS in CI. Presence of the entry is the CI-runnable
    form of the old ``src.count(anchor) == 1`` uniqueness check.

    NOTE (real drift finding, surfaced 2026-07-06): Sites A
    (``pN38_a_qkv_proj_call``) and C (``pN38_c_conditional_fused_kv``) are
    REQUIRED sub-patches whose anchors ``count == 0`` in the current pin
    (dev748) pristine ``qwen3_dflash.py`` — verified on the rig pristine tree
    and recorded as ``status: anchor_drift, required: true`` in the pin's
    ``drift.rej.json``. PN38 therefore cannot cleanly apply on dev748 and
    needs re-anchor or retirement. That drift is owned/surfaced by the
    anchor-SOT drift gate, so it is NOT re-asserted here (asserting a
    recorded-broken state as "expected" would be dishonest); only the
    still-valid D anchor is pinned in CI.
    """
    from tests.unit.anchor_sot._pin_manifest_assert import assert_anchor_recorded

    p = _import_patch()
    assert_anchor_recorded("PN38", "pN38_d_quant_fallback", p.PN38_D_ANCHOR)


# ─── Live pristine evidence (documented installed-vllm container-gate) ───


def _pristine_dflash() -> Path:
    """Pristine ``qwen3_dflash.py`` from the INSTALLED vllm (documented
    container-gate — the retired-B and native-B whole-file checks need the
    real source, which the md5-only manifest cannot reproduce). Runs wherever
    a matching vllm is importable (rig/container); skips honestly when absent
    — never on a phantom /tmp tree."""
    pytest.importorskip(
        "vllm", reason="container-gate needs a matching installed vllm"
    )
    from sndr.engines.vllm.detection.guards import resolve_vllm_file

    resolved = resolve_vllm_file("model_executor/models/qwen3_dflash.py")
    if resolved is None:
        pytest.skip("installed vllm lacks model_executor/models/qwen3_dflash.py")
    return Path(resolved)


class TestPristineAgainstInstalledPin:
    def test_retired_b_anchor_is_dead(self):
        # Upstream reordered the decoder-layer kwargs and passes
        # quant_config natively — the old B anchor must not match.
        p = _import_patch()
        src = self._pristine_dflash().read_text(encoding="utf-8")
        assert src.count(p.PN38_B_ANCHOR) == 0

    def test_native_site_b_lines_present_and_unique(self):
        p = _import_patch()
        src = self._pristine_dflash().read_text(encoding="utf-8")
        assert src.count(p.PN38_NATIVE_QUANT_INIT) == 1
        assert src.count(p.PN38_NATIVE_QUANT_KWARG) == 1
        ok, _ = p._native_site_b_status(src)
        assert ok is True

    _pristine_dflash = staticmethod(_pristine_dflash)
