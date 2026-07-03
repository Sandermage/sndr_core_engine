# SPDX-License-Identifier: Apache-2.0
"""TDD for TextPatcher.validate() — the read-only dry-run primitive.

`validate()` answers "would this patch apply cleanly on the current source?"
WITHOUT mutating the file. It runs the same idempotency / upstream-drift /
anchor checks as `apply()` (Layers 1/2/3/5) but never writes (no Layer 7).

The whole point of the method is that dry-run stops reporting a bare "applied"
(which only proved the module imported) and instead reports a result grounded
in the actual anchors: APPLIED = would-apply, IDEMPOTENT = already-there,
SKIPPED = drift / upstream-merged / target-missing.

Every test asserts the file is byte-for-byte unchanged after validate().

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_PRISTINE = (
    "# fake module for tests\n"
    "\n"
    "def foo():\n"
    "    return 1\n"
    "\n"
    "def bar():\n"
    "    raise NotImplementedError('no hybrid')\n"
    "\n"
    "def baz():\n"
    "    return 3\n"
)


@pytest.fixture
def fake_source(tmp_path):
    path = tmp_path / "fake_module.py"
    path.write_text(_PRISTINE)
    return str(path)


def _patcher(target, *, marker="VALIDATE_MARK", anchor, required=True,
             drift_markers=None):
    from sndr.kernel.text_patch import TextPatch, TextPatcher
    return TextPatcher(
        patch_name="test-validate",
        target_file=target,
        marker=marker,
        sub_patches=[
            TextPatch(name="edit", anchor=anchor,
                      replacement="    return 42\n", required=required),
        ],
        upstream_drift_markers=list(drift_markers or []),
    )


class TestTextPatcherValidate:
    def test_would_apply_reports_applied_and_leaves_file_untouched(self, fake_source):
        from sndr.kernel.text_patch import TextPatchResult

        p = _patcher(fake_source,
                     anchor="    raise NotImplementedError('no hybrid')\n")
        result, failure = p.validate()

        assert result == TextPatchResult.APPLIED
        assert failure is None
        # The core contract: NOTHING was written.
        assert Path(fake_source).read_text() == _PRISTINE

    def test_idempotent_when_marker_already_present(self, fake_source):
        from sndr.kernel.text_patch import TextPatchResult

        marked = "# [Genesis wiring marker: ALREADY]\n" + _PRISTINE
        Path(fake_source).write_text(marked)
        p = _patcher(fake_source, marker="ALREADY",
                     anchor="    raise NotImplementedError('no hybrid')\n")

        result, _ = p.validate()
        assert result == TextPatchResult.IDEMPOTENT
        assert Path(fake_source).read_text() == marked  # untouched

    def test_skips_on_required_anchor_missing_instead_of_false_applied(self, fake_source):
        from sndr.kernel.text_patch import TextPatchResult

        # Anchor that does NOT exist in the source -> would be drift.
        p = _patcher(fake_source, anchor="    raise ValueError('drifted away')\n")
        result, failure = p.validate()

        assert result == TextPatchResult.SKIPPED
        assert failure is not None
        assert failure.reason == "required_anchor_missing"
        assert Path(fake_source).read_text() == _PRISTINE

    def test_skips_when_upstream_drift_marker_present(self, fake_source):
        from sndr.kernel.text_patch import TextPatchResult

        p = _patcher(
            fake_source,
            anchor="    raise NotImplementedError('no hybrid')\n",
            drift_markers=["def baz():"],  # present in source -> upstream merged
        )
        result, failure = p.validate()

        assert result == TextPatchResult.SKIPPED
        assert failure is not None
        assert failure.reason == "upstream_merged"
        assert Path(fake_source).read_text() == _PRISTINE

    def test_skips_when_target_file_missing(self, tmp_path):
        from sndr.kernel.text_patch import TextPatchResult

        missing = str(tmp_path / "does_not_exist.py")
        p = _patcher(missing, anchor="whatever\n")
        result, failure = p.validate()

        assert result == TextPatchResult.SKIPPED
        assert failure is not None
        assert failure.reason == "target_file_missing"

    def test_skips_on_ambiguous_anchor(self, fake_source):
        from sndr.kernel.text_patch import TextPatchResult

        # "    return " appears more than once (foo/baz) -> ambiguous.
        p = _patcher(fake_source, anchor="    return 1\n", required=True)
        # Make it genuinely ambiguous by duplicating the anchor line.
        dup = _PRISTINE + "def qux():\n    return 1\n"
        Path(fake_source).write_text(dup)
        result, failure = p.validate()

        assert result == TextPatchResult.SKIPPED
        assert failure is not None
        assert failure.reason == "ambiguous_anchor"
        assert Path(fake_source).read_text() == dup

    def test_optional_anchor_absent_still_would_apply_if_a_sibling_matches(self, fake_source):
        """required=False anchor missing is a soft-skip; as long as some
        sub-patch matched, validate() reports APPLIED (would apply)."""
        from sndr.kernel.text_patch import TextPatch, TextPatcher, TextPatchResult

        p = TextPatcher(
            patch_name="test-optional",
            target_file=fake_source,
            marker="OPT_MARK",
            sub_patches=[
                TextPatch(name="present", required=True,
                          anchor="    raise NotImplementedError('no hybrid')\n",
                          replacement="    return 42\n"),
                TextPatch(name="absent_optional", required=False,
                          anchor="    return 999\n",
                          replacement="    return 1000\n"),
            ],
        )
        result, failure = p.validate()
        assert result == TextPatchResult.APPLIED
        assert failure is None
        assert Path(fake_source).read_text() == _PRISTINE
