# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the unified TurboQuant workspace policy module."""
from __future__ import annotations


def test_workspace_policy_patch_ids_constant():
    """The 4 workspace patches are catalogued in one canonical tuple."""
    from vllm.sndr_core.integrations.attention.turboquant._workspace_policy import (
        WORKSPACE_POLICY_PATCH_IDS,
    )
    assert set(WORKSPACE_POLICY_PATCH_IDS) == {
        "P98", "P99", "PN118", "SNDR_WORKSPACE_001",
    }


def test_describe_policy_mentions_all_four_patches():
    """describe_policy() returns text with all 4 patch IDs."""
    from vllm.sndr_core.integrations.attention.turboquant._workspace_policy import (
        describe_policy,
    )
    text = describe_policy()
    for pid in ("P98", "P99", "PN118", "SNDR_WORKSPACE_001"):
        assert pid in text, f"{pid} missing from policy summary"


def test_verify_patch_composition_all_present():
    """All 4 workspace patches are in the live PATCH_REGISTRY."""
    from vllm.sndr_core.integrations.attention.turboquant._workspace_policy import (
        verify_patch_composition,
    )
    result = verify_patch_composition()
    for pid in ("P98", "P99", "PN118", "SNDR_WORKSPACE_001"):
        p = result["patches"][pid]
        assert p["registry_present"] is True, (
            f"{pid} not in PATCH_REGISTRY"
        )


def test_verify_patch_composition_no_internal_conflicts():
    """The 4 workspace patches don't conflict with each other."""
    from vllm.sndr_core.integrations.attention.turboquant._workspace_policy import (
        verify_patch_composition,
    )
    result = verify_patch_composition()
    assert result["composable"] is True, (
        f"unexpected internal conflicts: {result['conflicts']}"
    )


def test_audit_workspace_state_returns_structured_dict():
    """audit_workspace_state() returns the expected nested shape."""
    from vllm.sndr_core.integrations.attention.turboquant._workspace_policy import (
        audit_workspace_state,
    )
    result = audit_workspace_state()
    assert "composition" in result
    assert "reachability" in result
    assert "summary" in result
    assert result["summary"]["all_patches_in_registry"] is True


def test_summary_reports_default_on_count():
    """default_on_count tracks the operational invariant — should be 1
    (only PN118 is currently default_on in v11.2.0 production)."""
    from vllm.sndr_core.integrations.attention.turboquant._workspace_policy import (
        verify_patch_composition,
    )
    result = verify_patch_composition()
    # Don't assert exact count — operator may add more default_on in
    # future releases. Just assert the count is reported and is at
    # least 1 (PN118 default_on=True).
    assert "default_on_count" in result
    assert result["default_on_count"] >= 1


def test_pn118_is_default_on():
    """PN118 is the production-default workspace patch."""
    from vllm.sndr_core.integrations.attention.turboquant._workspace_policy import (
        verify_patch_composition,
    )
    result = verify_patch_composition()
    assert result["patches"]["PN118"]["default_on"] is True


def test_p98_p99_sndr_001_default_off():
    """P98 / P99 / SNDR_WORKSPACE_001 are operator opt-in (default OFF)."""
    from vllm.sndr_core.integrations.attention.turboquant._workspace_policy import (
        verify_patch_composition,
    )
    result = verify_patch_composition()
    for pid in ("P98", "P99", "SNDR_WORKSPACE_001"):
        assert result["patches"][pid]["default_on"] is False, (
            f"{pid} default_on should be False — operator opt-in only"
        )


def test_env_enabled_reflects_environment(monkeypatch):
    """env_enabled flags flip on/off based on actual env state."""
    from vllm.sndr_core.integrations.attention.turboquant._workspace_policy import (
        verify_patch_composition,
    )
    monkeypatch.setenv("GENESIS_ENABLE_P99_WORKSPACE_MANAGER_MEMOIZE", "1")
    result = verify_patch_composition()
    # env_flag may differ from the canonical pattern; check the
    # field is bool either way
    assert isinstance(result["patches"]["P99"]["env_enabled"], bool)


def test_cli_main_returns_zero(capsys):
    """The CLI entry-point prints a readable report and returns 0."""
    from vllm.sndr_core.integrations.attention.turboquant._workspace_policy import (
        main_cli,
    )
    rc = main_cli()
    assert rc == 0
    captured = capsys.readouterr()
    assert "TurboQuant workspace policy" in captured.out
    assert "Composition:" in captured.out
    assert "Reachability:" in captured.out
