# SPDX-License-Identifier: Apache-2.0
"""Canonicalization contract test (v12 sndr-platform residual pass).

Proves the SNDR_↔GENESIS_ env-flag alias layer in ``sndr.env`` so the
``GENESIS_ENABLE_*`` public contract (321 patches + rig start-scripts +
downstream consumers, per club-3090 discussion #19) keeps working AFTER
``SNDR_ENABLE_*`` became the canonical prefix.

Invariants under test (all four reader families in ``sndr.env``):

  1. ``is_enabled``        — ``SNDR_ENABLE_X`` and ``GENESIS_ENABLE_X``
                             resolve identically; SNDR_ wins when both set.
  2. ``is_disabled``       — same for ``*_DISABLE_X``.
  3. ``is_legacy_active``  — same for ``*_LEGACY_X``.
  4. ``get_sndr_env`` &    — generic suffix reader (gateway / spec-decode
     ``get_sndr_env_bool``   env vars that don't fit ENABLE/DISABLE/LEGACY);
                             GENESIS_ alias still resolves AND emits a
                             one-shot deprecation warning naming SNDR_.

The mechanism already existed (``is_enabled`` checks SNDR_ then
GENESIS_); this test pins the contract so a future hard-rename of the
GENESIS_ alias cannot land silently — both names MUST resolve until the
deprecation window closes.
"""
from __future__ import annotations

import logging

import pytest

from sndr.env import (
    Flags,
    get_sndr_env,
    get_sndr_env_bool,
    is_disabled,
    is_enabled,
    is_legacy_active,
    known_flags,
)

# A representative sample spanning every flag family + tier so the alias
# contract is exercised across the actual registry, not a synthetic name.
_SAMPLE_FLAGS = [
    Flags.P15,                                  # backport, tool_parsing
    Flags.P61C_QWEN3CODER_DEFERRED_COMMIT,      # backport, tool_parsing
    Flags.PN95_TIER_AWARE_CACHE,                # backport, cache
    Flags.SNDR_MTP_DYNAMIC_K_001,               # Sander-original (engine)
    Flags.G4_19_GEMMA4_TURBOQUANT_KV,           # gemma4, engine
    Flags.PN401_TQ_PREFILL_CONTINUATION_GUARD,  # 2026-06 vendor wave
]

_TRUTHY = ("1", "true", "yes", "on", "TRUE", "On")
_FALSEY = ("0", "false", "no", "off", "")


@pytest.mark.parametrize("flag", _SAMPLE_FLAGS)
@pytest.mark.parametrize("val", _TRUTHY)
def test_enable_both_prefixes_resolve_true(monkeypatch, flag, val):
    """SNDR_ENABLE_X and GENESIS_ENABLE_X each resolve True identically."""
    monkeypatch.delenv(f"SNDR_ENABLE_{flag}", raising=False)
    monkeypatch.delenv(f"GENESIS_ENABLE_{flag}", raising=False)

    # Canonical prefix.
    monkeypatch.setenv(f"SNDR_ENABLE_{flag}", val)
    assert is_enabled(flag) is True
    monkeypatch.delenv(f"SNDR_ENABLE_{flag}")

    # Legacy alias — MUST behave identically (public contract).
    monkeypatch.setenv(f"GENESIS_ENABLE_{flag}", val)
    assert is_enabled(flag) is True


@pytest.mark.parametrize("flag", _SAMPLE_FLAGS)
@pytest.mark.parametrize("val", _FALSEY)
def test_enable_both_prefixes_resolve_false(monkeypatch, flag, val):
    """Falsey values resolve False under either prefix."""
    monkeypatch.delenv(f"SNDR_ENABLE_{flag}", raising=False)
    monkeypatch.delenv(f"GENESIS_ENABLE_{flag}", raising=False)

    monkeypatch.setenv(f"SNDR_ENABLE_{flag}", val)
    assert is_enabled(flag) is False
    monkeypatch.delenv(f"SNDR_ENABLE_{flag}")

    monkeypatch.setenv(f"GENESIS_ENABLE_{flag}", val)
    assert is_enabled(flag) is False


@pytest.mark.parametrize("flag", _SAMPLE_FLAGS)
def test_enable_default_when_neither_set(monkeypatch, flag):
    """With neither prefix set, the passed default is returned."""
    monkeypatch.delenv(f"SNDR_ENABLE_{flag}", raising=False)
    monkeypatch.delenv(f"GENESIS_ENABLE_{flag}", raising=False)
    assert is_enabled(flag) is False
    assert is_enabled(flag, default=True) is True


@pytest.mark.parametrize("flag", _SAMPLE_FLAGS)
def test_enable_sndr_wins_when_both_set(monkeypatch, flag):
    """SNDR_ takes precedence over GENESIS_ when both are set.

    Per brand decision Q2 (2026-05-07): SNDR_ wins so a Sander-IP
    override is consistent on community deployments where GENESIS_ may
    already be baked into the launcher.
    """
    # SNDR_ on, GENESIS_ off → SNDR_ wins (True).
    monkeypatch.setenv(f"SNDR_ENABLE_{flag}", "1")
    monkeypatch.setenv(f"GENESIS_ENABLE_{flag}", "0")
    assert is_enabled(flag) is True

    # SNDR_ off, GENESIS_ on → SNDR_ wins (False).
    monkeypatch.setenv(f"SNDR_ENABLE_{flag}", "0")
    monkeypatch.setenv(f"GENESIS_ENABLE_{flag}", "1")
    assert is_enabled(flag) is False


@pytest.mark.parametrize("flag", _SAMPLE_FLAGS)
def test_disable_both_prefixes_resolve_identically(monkeypatch, flag):
    """SNDR_DISABLE_X and GENESIS_DISABLE_X both flip is_disabled True."""
    monkeypatch.delenv(f"SNDR_DISABLE_{flag}", raising=False)
    monkeypatch.delenv(f"GENESIS_DISABLE_{flag}", raising=False)
    assert is_disabled(flag) is False

    monkeypatch.setenv(f"SNDR_DISABLE_{flag}", "1")
    assert is_disabled(flag) is True
    monkeypatch.delenv(f"SNDR_DISABLE_{flag}")

    monkeypatch.setenv(f"GENESIS_DISABLE_{flag}", "1")
    assert is_disabled(flag) is True

    # SNDR_ precedence: SNDR_DISABLE=0 overrides GENESIS_DISABLE=1.
    monkeypatch.setenv(f"SNDR_DISABLE_{flag}", "0")
    assert is_disabled(flag) is False


def test_legacy_both_prefixes_resolve_identically(monkeypatch):
    """SNDR_LEGACY_X and GENESIS_LEGACY_X both gate is_legacy_active.

    Legacy default-on patches stay on unless explicitly disabled, so the
    DEFAULT is True; setting either prefix to 0 turns the patch off.
    """
    bare = Flags.LEGACY_P5  # "P5"
    monkeypatch.delenv(f"SNDR_LEGACY_{bare}", raising=False)
    monkeypatch.delenv(f"GENESIS_LEGACY_{bare}", raising=False)
    assert is_legacy_active(bare) is True  # default-on

    monkeypatch.setenv(f"GENESIS_LEGACY_{bare}", "0")
    assert is_legacy_active(bare) is False
    monkeypatch.delenv(f"GENESIS_LEGACY_{bare}")

    monkeypatch.setenv(f"SNDR_LEGACY_{bare}", "0")
    assert is_legacy_active(bare) is False

    # SNDR_ precedence: SNDR_LEGACY=1 overrides GENESIS_LEGACY=0.
    monkeypatch.setenv(f"GENESIS_LEGACY_{bare}", "0")
    monkeypatch.setenv(f"SNDR_LEGACY_{bare}", "1")
    assert is_legacy_active(bare) is True


def test_get_sndr_env_alias_and_precedence(monkeypatch):
    """Generic suffix reader: SNDR_<name> wins; GENESIS_<name> still works."""
    name = "GATEWAY_PROFILE"
    monkeypatch.delenv(f"SNDR_{name}", raising=False)
    monkeypatch.delenv(f"GENESIS_{name}", raising=False)
    assert get_sndr_env(name, default="fallback") == "fallback"

    # Canonical wins.
    monkeypatch.setenv(f"SNDR_{name}", "canonical")
    monkeypatch.setenv(f"GENESIS_{name}", "legacy")
    assert get_sndr_env(name) == "canonical"

    # Legacy-only still resolves (alias kept working).
    monkeypatch.delenv(f"SNDR_{name}")
    assert get_sndr_env(name, warn_deprecated=False) == "legacy"


def test_get_sndr_env_warns_once_on_legacy_alias(monkeypatch, caplog):
    """Reading only the GENESIS_ alias emits a one-shot deprecation warning
    that names the canonical SNDR_ form. The alias still RESOLVES — the
    warning is advisory, not a behavior change."""
    # Use a unique name so the module-level one-shot dedup set is clean.
    name = "ALIAS_WARN_PROBE_UNIQUE"
    monkeypatch.delenv(f"SNDR_{name}", raising=False)
    monkeypatch.setenv(f"GENESIS_{name}", "v")

    # Clear the per-name dedup so the warning fires in this test run.
    import sndr.env as _env
    _env._deprecation_warned.discard(name)

    with caplog.at_level(logging.WARNING, logger="sndr.env"):
        assert get_sndr_env(name) == "v"  # alias resolves
    assert any(
        f"GENESIS_{name}" in rec.message and f"SNDR_{name}" in rec.message
        for rec in caplog.records
    ), "expected a one-shot deprecation warning naming both env-var forms"


def test_get_sndr_env_bool_alias(monkeypatch):
    """Boolean generic reader honors the same alias semantics."""
    name = "GATEWAY_ADMIN_ALLOW_REMOTE"
    monkeypatch.delenv(f"SNDR_{name}", raising=False)
    monkeypatch.delenv(f"GENESIS_{name}", raising=False)
    assert get_sndr_env_bool(name) is False

    monkeypatch.setenv(f"GENESIS_{name}", "1")
    assert get_sndr_env_bool(name) is True
    monkeypatch.setenv(f"SNDR_{name}", "0")  # SNDR_ wins
    assert get_sndr_env_bool(name) is False


def test_every_known_flag_resolves_under_both_prefixes(monkeypatch):
    """Exhaustive sweep: for EVERY flag in the registry, both
    SNDR_ENABLE_<flag> and GENESIS_ENABLE_<flag> must resolve True.

    This is the broad backstop behind the curated _SAMPLE_FLAGS cases —
    it guarantees no flag in the 300+ registry is reachable under only
    one prefix. Guards against a future flag landing with a hand-rolled
    os.environ.get() that forgets the alias.
    """
    flags = known_flags()
    assert len(flags) >= 300, f"expected the full registry, got {len(flags)}"
    for flag in flags:
        sndr_var = f"SNDR_ENABLE_{flag}"
        genesis_var = f"GENESIS_ENABLE_{flag}"
        monkeypatch.setenv(sndr_var, "1")
        assert is_enabled(flag) is True, f"{sndr_var} did not resolve"
        monkeypatch.delenv(sndr_var)

        monkeypatch.setenv(genesis_var, "1")
        assert is_enabled(flag) is True, f"{genesis_var} did not resolve"
        monkeypatch.delenv(genesis_var)
