# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the shared pin-manifest assertion helper.

The helper (``_pin_manifest_assert``) lets pristine-style anchor byte-checks
resolve against the committed per-pin anchor manifest instead of a /tmp
pristine tree absent on every CI host (audit finding #14). These tests pin the
helper's own contract with synthetic manifests (so the logic is verified in
isolation) AND against the real committed current-pin manifest (so the helper
is proven usable by the migrated per-patch tests).
"""
from __future__ import annotations

import hashlib

import pytest

from tests.unit.anchor_sot import _pin_manifest_assert as pma


def _md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


ANCHOR = "def _get_tile_size(head_size):\n    return 16\n"
REPL = "def _get_tile_size(head_size):\n    return 64\n"


def _synthetic_manifest() -> dict:
    """Minimal well-formed manifest with two patches sharing one file, one of
    them dual-variant (only the active variant recorded)."""
    return {
        "manifest_version": 1,
        "generated_at": "2026-07-05T00:00:00Z",
        "pins": {"vllm": "0.23.1rc1.dev748+g2dfaae752", "genesis": "12.1.0"},
        "files": {
            "a/b/target.py": {
                "md5_pristine": "0" * 32,
                "size_bytes": 4096,
                "patches": {
                    "PNX": {
                        "merge_status": "not_merged",
                        "anchors": {
                            "sub_one": {
                                "byte_offset": 100,
                                "byte_length": len(ANCHOR.encode("utf-8")),
                                "anchor_md5": _md5(ANCHOR),
                                "replacement_md5": _md5(REPL),
                            },
                        },
                    },
                    "PNY": {
                        "merge_status": "fully_merged",
                        "anchors": {
                            "sub_y": {
                                "byte_offset": 500,
                                "byte_length": len(b"some_anchor"),
                                "anchor_md5": _md5("some_anchor"),
                            },
                        },
                    },
                },
            },
        },
    }


# ── assert_anchor_recorded ────────────────────────────────────────────


class TestAssertAnchorRecorded:
    def test_passes_on_matching_anchor(self):
        pma.assert_anchor_recorded(
            "PNX", "sub_one", ANCHOR, manifest=_synthetic_manifest()
        )

    def test_red_on_wrong_anchor_bytes(self):
        """The core strengthening: a patcher whose anchor constant drifts from
        the recorded pristine bytes must fail loud (md5 mismatch)."""
        with pytest.raises(AssertionError, match="anchor_md5"):
            pma.assert_anchor_recorded(
                "PNX", "sub_one", ANCHOR + "  # drifted\n",
                manifest=_synthetic_manifest(),
            )

    def test_red_on_absent_patch(self):
        with pytest.raises(AssertionError, match="not recorded"):
            pma.assert_anchor_recorded(
                "PNZ", "sub_one", ANCHOR, manifest=_synthetic_manifest()
            )

    def test_red_on_absent_sub(self):
        with pytest.raises(AssertionError, match="not recorded"):
            pma.assert_anchor_recorded(
                "PNX", "nope", ANCHOR, manifest=_synthetic_manifest()
            )

    def test_red_on_wrong_merge_status(self):
        """A merge_status flip (upstream absorbed the patch) must redden a test
        that still expects not_merged — the retire signal."""
        with pytest.raises(AssertionError, match="merge_status"):
            pma.assert_anchor_recorded(
                "PNY", "sub_y", "some_anchor",
                manifest=_synthetic_manifest(),
            )

    def test_merge_status_override_accepts_declared_value(self):
        pma.assert_anchor_recorded(
            "PNY", "sub_y", "some_anchor", merge="fully_merged",
            manifest=_synthetic_manifest(),
        )


# ── assert_replacement_recorded ───────────────────────────────────────


class TestAssertReplacementRecorded:
    def test_passes_on_matching_replacement(self):
        pma.assert_replacement_recorded(
            "PNX", "sub_one", REPL, manifest=_synthetic_manifest()
        )

    def test_red_on_wrong_replacement(self):
        with pytest.raises(AssertionError, match="replacement_md5"):
            pma.assert_replacement_recorded(
                "PNX", "sub_one", REPL + "x", manifest=_synthetic_manifest()
            )

    def test_red_when_no_replacement_recorded(self):
        with pytest.raises(AssertionError, match="no replacement_md5"):
            pma.assert_replacement_recorded(
                "PNY", "sub_y", "whatever", manifest=_synthetic_manifest()
            )


# ── assert_cohabits ───────────────────────────────────────────────────


class TestAssertCohabits:
    def test_passes_when_both_present(self):
        pma.assert_cohabits(
            "a/b/target.py", "PNX", "PNY", manifest=_synthetic_manifest()
        )

    def test_red_on_missing_cohabitant(self):
        with pytest.raises(AssertionError, match="missing"):
            pma.assert_cohabits(
                "a/b/target.py", "PNX", "PNZ",
                manifest=_synthetic_manifest(),
            )

    def test_red_on_unknown_file(self):
        with pytest.raises(AssertionError, match="not a target file"):
            pma.assert_cohabits(
                "nope.py", "PNX", manifest=_synthetic_manifest()
            )


# ── assert_variant_inactive ───────────────────────────────────────────


class TestAssertVariantInactive:
    def test_passes_when_variant_not_recorded(self):
        # A different string that is NOT any recorded anchor for PNX.
        pma.assert_variant_inactive(
            "PNX", "def _get_tile_size(head_size):\n    return 32\n",
            manifest=_synthetic_manifest(),
        )

    def test_red_when_supposedly_inactive_variant_is_active(self):
        """If the 'inactive' variant string is in fact the recorded active
        anchor, variant selection drifted — must fail."""
        with pytest.raises(AssertionError, match="variant selection drifted"):
            pma.assert_variant_inactive(
                "PNX", ANCHOR, manifest=_synthetic_manifest()
            )


# ── Against the REAL committed current-pin manifest ───────────────────


class TestAgainstRealManifest:
    def test_current_pin_manifest_loads_and_validates(self):
        man = pma.current_pin_manifest()
        assert man["manifest_version"] == 1
        assert man["files"], "committed manifest has no files"

    def test_known_real_entry_ties_live_patcher_constant(self):
        """PN351's tile anchor constant must be recorded byte-exactly in the
        real manifest — proves the helper works end-to-end against a live
        patcher module (importable without vllm)."""
        from sndr.engines.vllm.patches.attention import (
            pn351_triton_unified_attention_large_head as pn351,
        )

        pma.assert_anchor_recorded(
            "PN351", "pn351_get_tile_size_large_head", pn351.PN351_TILE_OLD
        )
