# SPDX-License-Identifier: Apache-2.0
"""TDD for the dry-run anchor-validation wiring in the apply orchestrator.

Before this, the spec-driven dry-run path reported a bare ("applied",
"dry-run: apply_module ready") for every patch whose module merely imported —
a false green: a text-patch whose anchor had drifted still reported "applied".

`_dry_run_report(mod, display)` closes that hole GENERICALLY (no per-patch
churn) by using the dominant `_make_patcher() -> TextPatcher | None`
convention: it builds the patcher and calls the read-only `TextPatcher
.validate()`, so dry-run "applied" now means "anchors validated against the
live source". Modules without `_make_patcher` (runtime rebinds) or on a
torch-less host (patcher is None) return None so the caller keeps the honest
"apply_module ready" fallback.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

_PRISTINE = (
    "def bar():\n"
    "    raise NotImplementedError('no hybrid')\n"
)


@pytest.fixture
def fake_source(tmp_path):
    path = tmp_path / "fake_target.py"
    path.write_text(_PRISTINE)
    return str(path)


def _module_with_patcher(target, *, anchor, marker="DR_MARK", drift=None):
    """Build a fake patch module exposing `_make_patcher()` — the convention
    117 real text-patch modules follow."""
    from sndr.kernel.text_patch import TextPatch, TextPatcher

    def _make_patcher():
        return TextPatcher(
            patch_name="fake",
            target_file=target,
            marker=marker,
            sub_patches=[TextPatch(name="edit", anchor=anchor,
                                   replacement="    return 42\n", required=True)],
            upstream_drift_markers=list(drift or []),
        )

    return types.SimpleNamespace(_make_patcher=_make_patcher)


class TestDryRunReport:
    def test_reports_applied_and_validated_when_anchor_present(self, fake_source):
        from sndr.apply.orchestrator import _dry_run_report

        mod = _module_with_patcher(
            fake_source, anchor="    raise NotImplementedError('no hybrid')\n")
        out = _dry_run_report(mod, "PX fake")

        assert out is not None
        status, reason = out
        assert status == "applied"
        assert "validated" in reason.lower() or "anchor" in reason.lower()
        # dry-run must not mutate the file
        assert Path(fake_source).read_text() == _PRISTINE

    def test_reports_skipped_on_anchor_drift_not_false_applied(self, fake_source):
        from sndr.apply.orchestrator import _dry_run_report

        mod = _module_with_patcher(
            fake_source, anchor="    raise ValueError('long gone')\n")
        out = _dry_run_report(mod, "PX fake")

        assert out is not None
        status, reason = out
        assert status == "skipped"
        assert "anchor" in reason.lower() or "drift" in reason.lower()
        assert Path(fake_source).read_text() == _PRISTINE

    def test_reports_applied_when_marker_already_present(self, fake_source):
        from sndr.apply.orchestrator import _dry_run_report

        Path(fake_source).write_text(
            "# [Genesis wiring marker: DR_MARK]\n" + _PRISTINE)
        mod = _module_with_patcher(
            fake_source, anchor="    raise NotImplementedError('no hybrid')\n")
        out = _dry_run_report(mod, "PX fake")

        assert out is not None
        status, reason = out
        assert status == "applied"
        assert "already" in reason.lower() or "idempot" in reason.lower()

    def test_returns_none_without_make_patcher_so_caller_falls_back(self):
        from sndr.apply.orchestrator import _dry_run_report

        mod = types.SimpleNamespace()  # runtime-rebind patch, no _make_patcher
        assert _dry_run_report(mod, "PX fake") is None

    def test_returns_none_when_make_patcher_returns_none(self):
        from sndr.apply.orchestrator import _dry_run_report

        # e.g. torch-less host: resolve_vllm_file() -> None -> patcher None
        mod = types.SimpleNamespace(_make_patcher=lambda: None)
        assert _dry_run_report(mod, "PX fake") is None

    def test_returns_none_when_make_patcher_raises(self):
        from sndr.apply.orchestrator import _dry_run_report

        def _boom():
            raise RuntimeError("cannot build")

        mod = types.SimpleNamespace(_make_patcher=_boom)
        assert _dry_run_report(mod, "PX fake") is None
