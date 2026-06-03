# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the unified NGRAM policy orchestrator module."""
from __future__ import annotations


def test_ngram_policy_patch_ids_constant():
    """The 5 ngram patches are catalogued in one canonical tuple."""
    from vllm.sndr_core.integrations.spec_decode._ngram_policy_orchestrator import (
        NGRAM_POLICY_PATCH_IDS,
    )
    assert set(NGRAM_POLICY_PATCH_IDS) == {"P70", "P77", "P86", "PN72", "PN90"}


def test_describe_policy_mentions_all_five_patches():
    """describe_policy() returns text with all 5 patch IDs."""
    from vllm.sndr_core.integrations.spec_decode._ngram_policy_orchestrator import (
        describe_policy,
    )
    text = describe_policy()
    for pid in ("P70", "P77", "P86", "PN72", "PN90"):
        assert pid in text, f"{pid} missing from policy summary"


def test_verify_patch_composition_all_present():
    """All 5 NGRAM patches are in the live PATCH_REGISTRY."""
    from vllm.sndr_core.integrations.spec_decode._ngram_policy_orchestrator import (
        verify_patch_composition,
    )
    result = verify_patch_composition()
    for pid in ("P70", "P77", "P86", "PN72", "PN90"):
        p = result["patches"][pid]
        assert p["registry_present"] is True, (
            f"{pid} not in PATCH_REGISTRY"
        )


def test_verify_patch_composition_no_conflicts_internally():
    """The 5 ngram patches don't conflict with each other in registry."""
    from vllm.sndr_core.integrations.spec_decode._ngram_policy_orchestrator import (
        verify_patch_composition,
    )
    result = verify_patch_composition()
    assert result["composable"] is True, (
        f"unexpected internal conflicts: {result['conflicts']}"
    )


def test_audit_ngram_stack_state_returns_structured_dict():
    """audit_ngram_stack_state() returns the expected nested shape."""
    from vllm.sndr_core.integrations.spec_decode._ngram_policy_orchestrator import (
        audit_ngram_stack_state,
    )
    result = audit_ngram_stack_state()
    assert "composition" in result
    assert "reachability" in result
    assert "summary" in result
    assert result["summary"]["all_patches_in_registry"] is True


def test_audit_handles_missing_vllm_classes_gracefully():
    """Reachability check returns bool keys even when vllm isn't installed."""
    from vllm.sndr_core.integrations.spec_decode._ngram_policy_orchestrator import (
        audit_ngram_stack_state,
    )
    result = audit_ngram_stack_state()
    assert isinstance(result["reachability"]["ngram_proposer_class"], bool)
    assert isinstance(
        result["reachability"]["speculative_config_class"], bool
    )


def test_env_enabled_reflects_environment(monkeypatch):
    """env_enabled flags flip on/off based on actual env state."""
    from vllm.sndr_core.integrations.spec_decode._ngram_policy_orchestrator import (
        verify_patch_composition,
    )
    monkeypatch.setenv("GENESIS_ENABLE_P70_AUTO_STRICT_NGRAM", "1")
    result = verify_patch_composition()
    assert result["patches"]["P70"]["env_enabled"] is True

    monkeypatch.delenv("GENESIS_ENABLE_P70_AUTO_STRICT_NGRAM", raising=False)
    result = verify_patch_composition()
    assert result["patches"]["P70"]["env_enabled"] is False


def test_summary_any_patch_enabled_tracks_env(monkeypatch):
    """summary.any_patch_env_enabled aggregates across the 5 patches."""
    from vllm.sndr_core.integrations.spec_decode._ngram_policy_orchestrator import (
        audit_ngram_stack_state,
    )
    # Force-disable all
    for flag in (
        "GENESIS_ENABLE_P70_AUTO_STRICT_NGRAM",
        "GENESIS_ENABLE_P77_ADAPTIVE_NGRAM_K",
        "GENESIS_ENABLE_P86_NGRAM_BATCH_PROPOSE_LINEAR",
        "GENESIS_ENABLE_PN72_FREQUENCY_NGRAM_DRAFTER",
        "GENESIS_ENABLE_PN90_PROBABILISTIC_DRAFT",
    ):
        monkeypatch.delenv(flag, raising=False)
    result = audit_ngram_stack_state()
    assert result["summary"]["any_patch_env_enabled"] is False

    monkeypatch.setenv("GENESIS_ENABLE_PN72_FREQUENCY_NGRAM_DRAFTER", "1")
    result = audit_ngram_stack_state()
    assert result["summary"]["any_patch_env_enabled"] is True


def test_cli_main_returns_zero(capsys):
    """The CLI entry-point prints a readable report and returns 0."""
    from vllm.sndr_core.integrations.spec_decode._ngram_policy_orchestrator import (
        main_cli,
    )
    rc = main_cli()
    assert rc == 0
    captured = capsys.readouterr()
    assert "NGRAM speculative-decoding policy" in captured.out
    assert "Composition:" in captured.out
    assert "Reachability:" in captured.out
