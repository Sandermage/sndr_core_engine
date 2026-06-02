# SPDX-License-Identifier: Apache-2.0
"""Unit tests for PN79 v2 — md5+full-file PoC (chunk_delta_h.py scope).

Sibling 2 of pn79's multi-file md5 conversion (companion to the
chunk.py sibling). Drift finding documented in the patch module: 3/4
pn79 anchors apply cleanly on current pin; ``ANCHOR_2B_KERNEL_SIG``
drifted. The md5+full-file pattern prevents the silent partial-apply
by guarding the whole file against ANY drift, not just the per-anchor
view.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

FIXTURE_PRE = (
    Path(__file__).parent
    / "fixtures"
    / "pn79_v2_md5_chunk_delta_h_pre_patch.py.txt"
)
FIXTURE_POST = (
    Path(__file__).parent
    / "fixtures"
    / "pn79_v2_md5_chunk_delta_h_post_patch.py.txt"
)


def _expected_pre_md5() -> str:
    return hashlib.md5(FIXTURE_PRE.read_bytes()).hexdigest()


def test_pn79_v2_md5_chunk_delta_h_constant_matches_fixture():
    """The module's PN79_V2_MD5_CHUNK_DELTA_H_PRE_PATCH_MD5 constant must
    equal the md5 of the bundled pre-patch fixture (rig-extracted
    upstream chunk_delta_h.py at our PROD pin)."""
    from vllm.sndr_core.integrations.attention.gdn.pn79_v2_md5_chunk_delta_h import (  # noqa: E501
        PN79_V2_MD5_CHUNK_DELTA_H_PRE_PATCH_MD5,
    )
    assert PN79_V2_MD5_CHUNK_DELTA_H_PRE_PATCH_MD5 == _expected_pre_md5()


def test_pn79_v2_md5_chunk_delta_h_helper_computes_correct_hash():
    """_file_md5() returns the same hash as stdlib hashlib.md5."""
    from vllm.sndr_core.integrations.attention.gdn.pn79_v2_md5_chunk_delta_h import (  # noqa: E501
        _file_md5,
    )
    assert _file_md5(FIXTURE_PRE) == _expected_pre_md5()


def test_pn79_v2_md5_chunk_delta_h_apply_skips_when_md5_mismatches(tmp_path):
    """When target md5 does not match PRE_PATCH_MD5, _do_apply() returns
    skipped (no write, target unchanged)."""
    from vllm.sndr_core.integrations.attention.gdn import (
        pn79_v2_md5_chunk_delta_h,
    )

    target = tmp_path / "chunk_delta_h.py"
    original = "# not the real chunk_delta_h.py file\n"
    target.write_text(original)

    result = pn79_v2_md5_chunk_delta_h._do_apply(target)
    assert result.status == "skipped"
    assert "md5 mismatch" in result.reason.lower()
    assert target.read_text() == original


def test_pn79_v2_md5_chunk_delta_h_apply_writes_post_patch_when_md5_matches(tmp_path):
    """When target md5 matches PRE_PATCH_MD5, _do_apply() writes
    POST_PATCH_CONTENT + marker, returns applied."""
    from vllm.sndr_core.integrations.attention.gdn import (
        pn79_v2_md5_chunk_delta_h,
    )

    target = tmp_path / "chunk_delta_h.py"
    target.write_bytes(FIXTURE_PRE.read_bytes())

    result = pn79_v2_md5_chunk_delta_h._do_apply(target)
    assert result.status == "applied"
    after = target.read_text()
    assert pn79_v2_md5_chunk_delta_h._GENESIS_PN79_V2_CHUNK_DELTA_H_MARKER in after


def test_pn79_v2_md5_chunk_delta_h_apply_idempotent_via_marker(tmp_path):
    """Second _do_apply() against an already-patched file returns
    skipped(already_applied) via marker detection — does not re-write."""
    from vllm.sndr_core.integrations.attention.gdn import (
        pn79_v2_md5_chunk_delta_h,
    )

    target = tmp_path / "chunk_delta_h.py"
    target.write_text(
        pn79_v2_md5_chunk_delta_h.PN79_V2_MD5_CHUNK_DELTA_H_POST_PATCH_CONTENT
    )
    pre_apply_text = target.read_text()

    result = pn79_v2_md5_chunk_delta_h._do_apply(target)
    assert result.status == "skipped"
    assert "already applied" in result.reason.lower()
    assert target.read_text() == pre_apply_text
