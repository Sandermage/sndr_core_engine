# SPDX-License-Identifier: Apache-2.0
"""Tests для `vllm.sndr_core.dispatcher.registry_metadata` overlay.

Etap 0.3 (audit 2026-05-12): production_default теперь учитывает
test_status. Раньше `lifecycle=stable` автоматически давало
`production_default=eligible`, даже если patch не имел тестов.
Новый помощник `_production_default_for(impl_status, test_status)`
возвращает `review_required` для непротестированных stable/full/live
патчей.

Тесты покрывают:
  • Маппинг impl_status × test_status → production_default (matrix).
  • EXPLICIT_OVERRIDES bypass.
  • Lifecycle fallback.
  • Real registry: количество review_required > 0 (доказывает что
    overlay работает, а не silent eligible-everywhere).
"""
from __future__ import annotations

import pytest

from vllm.sndr_core.dispatcher.registry_metadata import (
    EXPLICIT_OVERRIDES,
    _LIFECYCLE_TO_IMPL,
    _production_default_for,
    derive_metadata,
)


# ─── _production_default_for matrix ─────────────────────────────────────


class TestProductionDefaultMatrix:
    """Etap 0.3: единая функция, которую тестируем по cells."""

    @pytest.mark.parametrize("impl,test,expected", [
        # blocked statuses — независимо от test_status
        ("partial",     "unit", "blocked"),
        ("partial",     "none", "blocked"),
        ("placeholder", "unit", "blocked"),
        ("placeholder", "none", "blocked"),
        ("retired",     "unit", "blocked"),
        ("retired",     "none", "blocked"),
        # research → research_only независимо от test_status
        ("research", "unit", "research_only"),
        ("research", "none", "research_only"),
        # ok statuses без тестов → review_required (Etap 0.3 fix)
        ("full",        "none", "review_required"),
        ("live",        "none", "review_required"),
        ("scaffold",    "none", "review_required"),
        ("coordinator", "none", "review_required"),
        # ok statuses с тестами → eligible
        ("full",        "unit",        "eligible"),
        ("full",        "integration", "eligible"),
        ("full",        "bench",       "eligible"),
        ("live",        "unit",        "eligible"),
        ("scaffold",    "unit",        "eligible"),
        ("coordinator", "unit",        "eligible"),
    ])
    def test_matrix(self, impl, test, expected):
        assert _production_default_for(impl, test) == expected


# ─── derive_metadata flow ───────────────────────────────────────────────


class TestDeriveMetadata:
    def test_explicit_override_wins(self):
        """EXPLICIT_OVERRIDES возвращается as-is, минуя весь pipeline."""
        # PN95 в overrides — partial / blocked
        d = derive_metadata("PN95", {"lifecycle": "stable", "family": "kv_cache"})
        assert d["implementation_status"] == "partial"
        assert d["production_default"] == "blocked"

    def test_explicit_status_in_registry_uses_helper(self):
        """Если registry задаёт implementation_status, production_default
        вычисляется через `_production_default_for`."""
        # Untested full patch → review_required
        d = derive_metadata(
            "ZNEW1",
            {"implementation_status": "full", "family": "spec_decode"},
        )
        assert d["implementation_status"] == "full"
        # ZNEW1 не существует в tests/ → test_status=none → review_required
        assert d["test_status"] == "none"
        assert d["production_default"] == "review_required"

    def test_lifecycle_fallback_uses_helper(self):
        """Lifecycle-based fallback тоже идёт через helper."""
        d = derive_metadata(
            "ZNEW2",
            {"lifecycle": "stable", "family": "spec_decode"},
        )
        # stable → full → review_required (no tests for ZNEW2)
        assert d["implementation_status"] == "full"
        assert d["production_default"] == "review_required"

    def test_lifecycle_retired_blocked(self):
        d = derive_metadata("ZNEW3", {"lifecycle": "retired"})
        assert d["implementation_status"] == "retired"
        assert d["production_default"] == "blocked"

    def test_lifecycle_research_research_only(self):
        d = derive_metadata("ZNEW4", {"lifecycle": "research"})
        assert d["implementation_status"] == "research"
        assert d["production_default"] == "research_only"

    def test_unknown_lifecycle_falls_to_live(self):
        d = derive_metadata("ZNEW5", {"lifecycle": "totally-unknown"})
        assert d["implementation_status"] == "live"
        # Без тестов → review_required
        assert d["production_default"] == "review_required"


# ─── _LIFECYCLE_TO_IMPL canonical mapping ───────────────────────────────


class TestLifecycleMapping:
    def test_all_known_lifecycles_mapped(self):
        """Все lifecycle states, упомянутые в codebase, должны иметь
        запись в _LIFECYCLE_TO_IMPL (или попадать в default 'live')."""
        for lc in ("retired", "deprecated", "research", "stable",
                   "coordinator", "legacy"):
            assert lc in _LIFECYCLE_TO_IMPL

    def test_stable_maps_to_full(self):
        assert _LIFECYCLE_TO_IMPL["stable"] == "full"

    def test_deprecated_maps_to_retired(self):
        assert _LIFECYCLE_TO_IMPL["deprecated"] == "retired"


# ─── Real registry sanity ───────────────────────────────────────────────


class TestRealRegistry:
    """Etap 0.3: на реальном registry должна появиться разница между
    `eligible` и `review_required`. Раньше всё было `eligible`."""

    def test_real_registry_has_review_required_entries(self):
        """Должно быть >0 patches со статусом `review_required` —
        иначе helper не работает (или у нас 100% test coverage 😉).
        """
        from vllm.sndr_core.dispatcher.registry import PATCH_REGISTRY
        review_required = []
        for pid, meta in PATCH_REGISTRY.items():
            if not isinstance(meta, dict):
                continue
            d = derive_metadata(pid, meta)
            if d["production_default"] == "review_required":
                review_required.append(pid)
        # Должно быть много patches без тестов (test_status detection
        # ограничен filesystem-based search).
        assert len(review_required) > 0, (
            "review_required count = 0 — это либо все патчи имеют тесты "
            "(маловероятно), либо helper не работает."
        )

    def test_overrides_not_review_required(self):
        """Все EXPLICIT_OVERRIDES должны быть либо eligible/blocked/
        research_only — никогда не review_required (override = audited)."""
        for pid, override in EXPLICIT_OVERRIDES.items():
            assert override["production_default"] != "review_required", (
                f"EXPLICIT_OVERRIDES[{pid}] should have audited "
                f"production_default, not 'review_required'"
            )
