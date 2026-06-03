# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the unified GDN contiguity policy module.

Phase 6 P3.2 — shared policy + runtime audit for PN11/PN54/PN50.
"""
from __future__ import annotations


def test_contiguity_patch_ids_constant():
    """The 3 contiguity patches are catalogued in one canonical place."""
    from vllm.sndr_core.integrations.attention.gdn._contiguity_policy import (
        CONTIGUITY_PATCH_IDS,
    )
    assert set(CONTIGUITY_PATCH_IDS) == {"PN11", "PN54", "PN50"}


def test_describe_policy_returns_human_summary():
    """describe_policy() returns the long-form operator-facing summary."""
    from vllm.sndr_core.integrations.attention.gdn._contiguity_policy import (
        describe_policy,
    )
    text = describe_policy()
    assert isinstance(text, str)
    assert "GDN contiguity policy" in text
    assert "PN11" in text and "PN54" in text and "PN50" in text
    assert "default_on=False" in text


def test_verify_patch_composition_all_present_in_registry():
    """All 3 patches are in the live PATCH_REGISTRY."""
    from vllm.sndr_core.integrations.attention.gdn._contiguity_policy import (
        verify_patch_composition,
    )
    result = verify_patch_composition()
    for pid in ("PN11", "PN54", "PN50"):
        p = result["patches"][pid]
        assert p["registry_present"] is True, (
            f"{pid} should be in PATCH_REGISTRY but isn't"
        )
        assert p["family"] == "attention.gdn"


def test_verify_patch_composition_no_internal_conflicts():
    """The 3 patches don't list each other in conflicts_with."""
    from vllm.sndr_core.integrations.attention.gdn._contiguity_policy import (
        verify_patch_composition,
    )
    result = verify_patch_composition()
    assert result["composable"] is True
    assert result["conflicts"] == [], (
        f"unexpected internal conflicts: {result['conflicts']}"
    )


def test_audit_contiguity_state_runs_without_vllm():
    """audit_contiguity_state() returns a structured dict even when
    vllm isn't installed in the env (reachability gets an error key)."""
    from vllm.sndr_core.integrations.attention.gdn._contiguity_policy import (
        audit_contiguity_state,
    )
    result = audit_contiguity_state()
    assert "composition" in result
    assert "reachability" in result
    assert "summary" in result
    assert result["summary"]["all_patches_in_registry"] is True


def test_env_enabled_reflects_environment(monkeypatch):
    """env_enabled in the composition report follows real env."""
    from vllm.sndr_core.integrations.attention.gdn._contiguity_policy import (
        verify_patch_composition,
    )
    monkeypatch.setenv("GENESIS_ENABLE_PN11_GDN_AB_CONTIGUOUS", "1")
    result = verify_patch_composition()
    assert result["patches"]["PN11"]["env_enabled"] is True

    monkeypatch.delenv("GENESIS_ENABLE_PN11_GDN_AB_CONTIGUOUS", raising=False)
    result = verify_patch_composition()
    assert result["patches"]["PN11"]["env_enabled"] is False


def test_cli_main_returns_zero_on_clean_audit(capsys):
    """The CLI entry-point returns 0 and prints a readable report."""
    from vllm.sndr_core.integrations.attention.gdn._contiguity_policy import (
        main_cli,
    )
    rc = main_cli()
    assert rc == 0
    captured = capsys.readouterr()
    assert "GDN contiguity policy" in captured.out
    assert "Composition:" in captured.out
    assert "Reachability" in captured.out
    assert "Summary:" in captured.out
