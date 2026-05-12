# SPDX-License-Identifier: Apache-2.0
"""Метадата-overlay для PATCH_REGISTRY (audit P1-2 closure, 2026-05-12).

Зачем
-----
Реестр в `registry.py` содержит 136 entries, и многие поля метадаты
(implementation_status, test_status, production_default) одинаковы
для целых групп патчей. Чтобы не дублировать их в каждом entry,
этот overlay декларирует группы:

  - Все `lifecycle=stable` → `implementation_status=full`,
    `production_default=eligible`.
  - Все `lifecycle=experimental` + `default_on=True` → `full`,
    `eligible`. Если default_on=False, скорее `full` тоже, но
    осторожнее.
  - `lifecycle=legacy` → `live` (pre-dispatcher, работает),
    `eligible`.
  - `lifecycle=retired` → `retired`, `blocked`.
  - `lifecycle=research` → `research`, `research_only`.

Сверху накладываются explicit overrides per-patch (например,
PN95.implementation_status=partial — wiring неполный).

API
---

- `derive_metadata(patch_id, registry_meta)` → dict с полями
  `implementation_status`, `test_status`, `production_default`.
- `EXPLICIT_OVERRIDES`: dict[patch_id, dict] — точечные исключения.

Связано
-------

- `dispatcher/spec.py::infer_implementation_status` (старый inference,
  теперь делегирует сюда).
- `cli/patches.py::_run_plan --profile production` (использует
  production_default для блока).
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, TypedDict

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_DIR = REPO_ROOT / "tests" / "unit" / "integrations"


ImplStatus = Literal[
    "full", "partial", "scaffold", "placeholder",
    "retired", "research", "live", "coordinator",
]
TestStatus = Literal["unit", "integration", "bench", "none"]
# Etap 0.3 (audit 2026-05-12): `review_required` добавлен для патчей,
# у которых impl_status=stable/full/live, но test_status=none. Раньше
# такие патчи получали `eligible` (production-ready), что завышало
# готовность и могло пропустить непротестированный код в production.
ProductionDefault = Literal[
    "eligible", "blocked", "research_only", "review_required",
]


class DerivedMetadata(TypedDict):
    implementation_status: ImplStatus
    test_status: TestStatus
    production_default: ProductionDefault


# Etap 0.3: единый mapping impl_status × test_status → production_default.
# Раньше это правило было размазано по 6 веткам derive_metadata; теперь
# одна функция — один источник правды, тесты её покрывают независимо.
_BLOCKED_STATUSES = frozenset({"partial", "placeholder", "retired"})
_RESEARCH_STATUSES = frozenset({"research"})


def _production_default_for(
    impl_status: str, test_status: str,
) -> ProductionDefault:
    """Compute production_default из (implementation_status, test_status).

    Правила:
      - partial/placeholder/retired → blocked (известно сломаны/устарели)
      - research → research_only (требует explicit research flag)
      - всё остальное (full/live/scaffold/coordinator):
          - test_status=none → review_required (нужен test coverage или
            audited override через EXPLICIT_OVERRIDES)
          - иначе → eligible
    """
    if impl_status in _BLOCKED_STATUSES:
        return "blocked"
    if impl_status in _RESEARCH_STATUSES:
        return "research_only"
    if test_status == "none":
        return "review_required"
    return "eligible"


# Точечные overrides для патчей, чей derived status неверен.
EXPLICIT_OVERRIDES: dict[str, DerivedMetadata] = {
    # Audit P1-2 — известно partial wiring:
    "PN95": {
        "implementation_status": "partial",
        "test_status": "unit",
        "production_default": "blocked",
    },
    "PN64": {
        # Marlin MoE SM 12.0 placeholder — нет реальной tuning data.
        "implementation_status": "placeholder",
        "test_status": "none",
        "production_default": "blocked",
    },
    "PN26b": {
        # Sparse-V research kernel — есть код, но без production
        # validation на Ampere.
        "implementation_status": "scaffold",
        "test_status": "unit",
        "production_default": "research_only",
    },
    # Coordinator-only entries (нет actual wiring файла):
    "P5b": {
        "implementation_status": "coordinator",
        "test_status": "unit",
        "production_default": "eligible",
    },
}


def _file_based_test_status(patch_id: str, family: str = "") -> TestStatus:
    """Best-effort: ищем `tests/unit/integrations/<family>/test_<id>_*.py`
    или `tests/legacy/test_<id>*.py`. Возвращаем `unit` если есть,
    иначе `none`. Integration / bench требуют ручного override через
    EXPLICIT_OVERRIDES.
    """
    pid_lower = patch_id.lower()
    # Прямо в integrations
    if family:
        fam_dir = TESTS_DIR / family.replace(".", "/")
        if fam_dir.is_dir():
            for f in fam_dir.rglob(f"test_{pid_lower}_*.py"):
                if f.is_file():
                    return "unit"
            for f in fam_dir.rglob(f"test_{pid_lower}.py"):
                if f.is_file():
                    return "unit"
    # Глобально в integrations/
    if TESTS_DIR.is_dir():
        for f in TESTS_DIR.rglob(f"test_{pid_lower}_*.py"):
            return "unit"
        for f in TESTS_DIR.rglob(f"test_{pid_lower}.py"):
            return "unit"
    # Legacy bucket
    legacy = REPO_ROOT / "tests" / "legacy"
    if legacy.is_dir():
        for f in legacy.rglob(f"test_{pid_lower}*.py"):
            return "unit"
        # Numeric forms (test_pn33_* vs test_pN33_*)
        for f in legacy.rglob(f"test_p{pid_lower.lstrip('p')}*.py"):
            return "unit"
    return "none"


_LIFECYCLE_TO_IMPL: dict[str, ImplStatus] = {
    "retired":     "retired",
    "deprecated":  "retired",
    "research":    "research",
    "stable":      "full",
    "coordinator": "coordinator",
    "legacy":      "live",
    # experimental / unknown → fallback `live` (см. derive_metadata).
}


def derive_metadata(
    patch_id: str, registry_meta: dict,
) -> DerivedMetadata:
    """Возвращает derived metadata для патча.

    Порядок resolution:
      1. EXPLICIT_OVERRIDES — audited per-patch исключения.
      2. registry `implementation_status` (если задан явно) →
         test_status + production_default через `_production_default_for`.
      3. Lifecycle-based fallback (тоже через `_production_default_for`).

    Etap 0.3 (2026-05-12): production_default теперь учитывает test_status.
    Stable/full/live патчи без тестов получают `review_required` вместо
    автоматического `eligible` — это закрывает риск пропуска
    непротестированного кода в production matrix.
    """
    # 1. Explicit override (точечная коррекция, audited)
    override = EXPLICIT_OVERRIDES.get(patch_id)
    if override is not None:
        return override

    test = _file_based_test_status(
        patch_id, str(registry_meta.get("family", "")),
    )

    # 2. registry уже задаёт implementation_status — уважаем
    explicit = registry_meta.get("implementation_status")
    if isinstance(explicit, str) and explicit:
        return {
            "implementation_status": explicit,  # type: ignore[typeddict-item]
            "test_status": test,
            "production_default": _production_default_for(explicit, test),
        }

    # 3. Lifecycle-based fallback
    lc = str(registry_meta.get("lifecycle", "")).lower()
    impl: ImplStatus = _LIFECYCLE_TO_IMPL.get(lc, "live")
    return {
        "implementation_status": impl,
        "test_status": test,
        "production_default": _production_default_for(impl, test),
    }


__all__ = [
    "EXPLICIT_OVERRIDES",
    "DerivedMetadata",
    "ImplStatus",
    "TestStatus",
    "ProductionDefault",
    "derive_metadata",
]
