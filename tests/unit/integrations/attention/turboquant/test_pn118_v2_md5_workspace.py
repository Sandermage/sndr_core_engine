# SPDX-License-Identifier: Apache-2.0
"""Unit tests for PN118 v2 — md5+full-file PoC (workspace.py scope only).

Validates the PN119 single-file md5 + full-file replacement pattern
applied to pn118's `v1/worker/workspace.py` target. The original PN118
(anchor-based) still ships and still patches the other pn118 target
(`v1/attention/backends/turboquant_attn.py`); v2 composes with pn118
via the marker pn118 already self-detects.

Scope correction from the v11.1.0 spec: pn118 patches TWO files, not
one. This v2 PoC covers only workspace.py — turboquant_attn.py is left
to the original pn118 anchors.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

FIXTURE_PRE = (
    Path(__file__).parent
    / "fixtures"
    / "pn118_v2_md5_workspace_pre_patch.py.txt"
)
FIXTURE_POST = (
    Path(__file__).parent
    / "fixtures"
    / "pn118_v2_md5_workspace_post_patch.py.txt"
)


def _expected_pre_md5() -> str:
    return hashlib.md5(FIXTURE_PRE.read_bytes()).hexdigest()


def test_pn118_v2_md5_workspace_constant_matches_fixture():
    """The module's PN118_V2_MD5_WORKSPACE_PRE_PATCH_MD5 constant must
    equal the md5 of the bundled pre-patch fixture (rig-extracted
    upstream workspace.py at our PROD pin). If the fixture is
    regenerated against a new pin, the constant must be regenerated
    alongside it."""
    from vllm.sndr_core.integrations.attention.turboquant.pn118_v2_md5_workspace import (  # noqa: E501
        PN118_V2_MD5_WORKSPACE_PRE_PATCH_MD5,
    )
    assert PN118_V2_MD5_WORKSPACE_PRE_PATCH_MD5 == _expected_pre_md5()


def test_pn118_v2_md5_workspace_helper_computes_correct_hash():
    """_file_md5() returns the same hash as stdlib hashlib.md5 on
    the same bytes."""
    from vllm.sndr_core.integrations.attention.turboquant.pn118_v2_md5_workspace import (  # noqa: E501
        _file_md5,
    )
    assert _file_md5(FIXTURE_PRE) == _expected_pre_md5()


def test_pn118_v2_md5_workspace_apply_skips_when_md5_mismatches(tmp_path):
    """When the target file md5 does not match
    PN118_V2_MD5_WORKSPACE_PRE_PATCH_MD5, _do_apply() returns
    skipped (no write, no error). Target file is unchanged."""
    from vllm.sndr_core.integrations.attention.turboquant import (
        pn118_v2_md5_workspace,
    )

    target = tmp_path / "workspace.py"
    original = "# not the real workspace file\n"
    target.write_text(original)

    result = pn118_v2_md5_workspace._do_apply(target)
    assert result.status == "skipped"
    assert "md5 mismatch" in result.reason.lower()
    # Target file is unchanged
    assert target.read_text() == original


def test_pn118_v2_md5_workspace_apply_writes_post_patch_when_md5_matches(tmp_path):
    """When the target file md5 matches the pre-patch md5, _do_apply()
    overwrites with PN118_V2_MD5_WORKSPACE_POST_PATCH_CONTENT and the
    Genesis marker, then returns applied."""
    from vllm.sndr_core.integrations.attention.turboquant import (
        pn118_v2_md5_workspace,
    )

    target = tmp_path / "workspace.py"
    target.write_bytes(FIXTURE_PRE.read_bytes())

    result = pn118_v2_md5_workspace._do_apply(target)
    assert result.status == "applied"
    after = target.read_text()
    assert pn118_v2_md5_workspace._GENESIS_PN118_V2_WORKSPACE_MARKER in after


def test_pn118_v2_md5_workspace_apply_idempotent_via_marker(tmp_path):
    """Second _do_apply() against an already-patched file returns
    skipped(already_applied) via marker detection — does not re-write."""
    from vllm.sndr_core.integrations.attention.turboquant import (
        pn118_v2_md5_workspace,
    )

    target = tmp_path / "workspace.py"
    # Pre-populate with the post-patch content (which includes marker)
    target.write_text(
        pn118_v2_md5_workspace.PN118_V2_MD5_WORKSPACE_POST_PATCH_CONTENT
    )
    pre_apply_text = target.read_text()

    result = pn118_v2_md5_workspace._do_apply(target)
    assert result.status == "skipped"
    assert "already applied" in result.reason.lower()
    # Target file is unchanged (marker-guard fires before any write)
    assert target.read_text() == pre_apply_text
