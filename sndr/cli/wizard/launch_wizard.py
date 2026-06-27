# SPDX-License-Identifier: Apache-2.0
"""Pure decision logic for the interactive ``sndr launch`` wizard.

This module holds the I/O-free core of the launch wizard so the logic can be
unit-tested without a TTY, ``nvidia-smi`` or a real terminal. The terminal
orchestration (numbered menus, prompts, hand-off to the launcher) lives in
:mod:`sndr.cli.commands.launch`.

It is the Genesis analogue of club-3090's ``c3/launch.sh`` interactive menu,
adapted to our YAML-preset model and **extended** with metadata club-3090's
bash menu does not have:

  - the typed ``preset card`` (``status`` / ``primary_metric`` / ``hardware_fit``
    / ``fallback_preset``) is rendered inline next to each candidate, so the
    operator sees the measured TPS + production status while choosing — not just
    a bare compose filename;
  - the ``sndr preflight`` fit verdict (``evaluate_fit``) is projected against
    the chosen rig and used both to *filter* the menu (only fitting presets by
    default, with a "show all" toggle) and to render a per-row verdict;
  - the single-card escape hatch: when a multi-GPU preset cannot run on a
    single card, the wizard surfaces the card's ``fallback_preset`` (if any) and
    routes the operator to ``docs/SINGLE_CARD.md`` instead of dead-ending — the
    club-3090 ``launch.sh`` has no such routing.

Everything here is a pure function over the preset corpus and a
:class:`~sndr.model_configs.preflight_fit.Rig`. No prints, no input(), no
subprocess. Side-effectful enumeration of the corpus is injected via the
``card_loader`` / ``cfg_loader`` callables so tests can pass a fake catalog.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from sndr.model_configs.preflight_fit import (
    FitReport,
    Rig,
    evaluate_fit,
    resolve_required_envelope,
)

# ── Status presentation order (mirrors product_api STATUS_RANK intent) ───────
# Lower = listed first. Production presets float to the top of the menu so the
# operator sees the validated, recommended choice before the experiments.
_STATUS_RANK = {
    "production": 0,
    "production_candidate": 1,
    "internal_validated": 2,
    "qa": 3,
    "bench_pending": 4,
    "validated": 5,
    "example": 6,
    "experimental": 7,
    "historical": 8,
    "tombstone": 9,
}

# Statuses never shown in the interactive menu (dead / retired presets).
_HIDDEN_STATUSES = frozenset({"tombstone", "historical"})

# Where single-card operators are routed when a multi-GPU preset can't run.
SINGLE_CARD_DOC = "docs/SINGLE_CARD.md"


@dataclass(frozen=True)
class Candidate:
    """One preset projected against the chosen rig — a menu row.

    Carries everything the menu renderer needs without re-loading the preset:
    the fit verdict, the card-derived display fields (status, measured metric)
    and the escape-hatch pointer.
    """

    preset_id: str
    status: str
    title: str
    can_run: bool
    verdict: str  # FitReport.verdict — "CAN RUN" | "RUNNABLE (with warnings)" | "CANNOT RUN"
    metric_label: Optional[str]  # e.g. "agg_TPS=241.4" or None when unmeasured
    fallback_preset: Optional[str]  # card.fallback_preset (escape hatch target)
    requires_min_gpu_count: Optional[int]
    report: FitReport

    @property
    def status_rank(self) -> int:
        return _STATUS_RANK.get(self.status, 99)


@dataclass
class Catalog:
    """The evaluated preset corpus for one rig.

    ``candidates`` is sorted menu-ready: fitting presets first, then by status
    rank, then by measured metric (desc), then by id (stable).
    """

    rig: Rig
    candidates: list[Candidate] = field(default_factory=list)
    load_errors: list[tuple[str, str]] = field(default_factory=list)  # (preset_id, reason)

    def fitting(self) -> list[Candidate]:
        """Only the presets that can run on the rig (no hard FAIL)."""
        return [c for c in self.candidates if c.can_run]

    def menu(self, *, show_all: bool) -> list[Candidate]:
        """The rows to show: fitting-only by default, everything on show_all."""
        return self.candidates if show_all else self.fitting()


def _metric_label(card) -> Optional[str]:
    """Render a card's primary_metric as a compact label, or None.

    A ``value`` of 0.0 means "declared but not yet measured" (the placeholder
    used by un-benched production_candidate cards) — treated as no metric so
    the menu doesn't advertise a fake "0 TPS".
    """
    pm = getattr(card, "primary_metric", None) if card is not None else None
    if pm is None:
        return None
    value = getattr(pm, "value", None)
    kind = getattr(pm, "kind", None)
    if not value or kind is None:
        return None
    # Trim trailing .0 for whole numbers so "241.0" reads as "241".
    text = f"{value:g}"
    return f"{kind}={text}"


def build_candidate(preset_id: str, preset_def, cfg, rig: Rig) -> Candidate:
    """Project one preset against the rig into a menu-ready :class:`Candidate`.

    Pure: ``preset_def`` (typed card) and ``cfg`` (composed config) are passed
    in already loaded; the only computation is the fit projection.
    """
    env = resolve_required_envelope(cfg, preset_def)
    report = evaluate_fit(preset_id, env, rig)
    card = getattr(preset_def, "card", None)
    status = getattr(card, "status", None) or "unknown"
    title = getattr(card, "title", None) or preset_id
    fallback = getattr(card, "fallback_preset", None) if card is not None else None
    return Candidate(
        preset_id=preset_id,
        status=status,
        title=title,
        can_run=report.can_run,
        verdict=report.verdict,
        metric_label=_metric_label(card),
        fallback_preset=fallback,
        requires_min_gpu_count=env.requires_min_gpu_count,
        report=report,
    )


def _sort_key(c: Candidate) -> tuple:
    """Menu order: fitting first, then status rank, then metric desc, then id.

    ``metric`` is sorted descending (higher TPS first) by negating the parsed
    value; rows without a metric sort after rows with one at the same status.
    """
    metric_value = 0.0
    if c.metric_label is not None:
        try:
            metric_value = float(c.metric_label.split("=", 1)[1])
        except (ValueError, IndexError):
            metric_value = 0.0
    return (
        0 if c.can_run else 1,
        c.status_rank,
        -metric_value,
        c.preset_id,
    )


def build_catalog(
    rig: Rig,
    *,
    preset_ids: list[str],
    card_loader: Callable[[str], object],
    cfg_loader: Callable[[str], object],
    include_hidden: bool = False,
) -> Catalog:
    """Evaluate every preset against ``rig`` into a menu-ready :class:`Catalog`.

    ``card_loader(preset_id) -> PresetDef`` and ``cfg_loader(preset_id) ->
    ModelConfig`` are injected so the corpus source is swappable in tests.
    Presets that fail to load are collected in ``load_errors`` (never crash the
    whole menu over one bad YAML — club-3090's launch.sh skips bad composes
    the same way).
    """
    catalog = Catalog(rig=rig)
    for preset_id in preset_ids:
        try:
            preset_def = card_loader(preset_id)
        except Exception as exc:  # pragma: no cover — defensive, per-row skip
            catalog.load_errors.append((preset_id, f"card load: {exc}"))
            continue
        card = getattr(preset_def, "card", None)
        status = getattr(card, "status", None)
        if not include_hidden and status in _HIDDEN_STATUSES:
            continue
        try:
            cfg = cfg_loader(preset_id)
        except Exception as exc:  # pragma: no cover — defensive, per-row skip
            catalog.load_errors.append((preset_id, f"compose: {exc}"))
            continue
        catalog.candidates.append(build_candidate(preset_id, preset_def, cfg, rig))

    catalog.candidates.sort(key=_sort_key)
    return catalog


@dataclass(frozen=True)
class EscapeHatch:
    """Routing surfaced when a chosen preset cannot run on a single card.

    Extends club-3090's launch.sh, which simply refuses a non-fitting compose.
    Here we point the operator at a concrete fallback preset (when the card
    declares one) and the single-card operator guide.
    """

    triggered: bool
    reason: str
    fallback_preset: Optional[str]
    doc: str = SINGLE_CARD_DOC


def escape_hatch_for(candidate: Candidate, rig: Rig) -> EscapeHatch:
    """Decide whether the single-card escape hatch applies to a candidate.

    Fires when the preset cannot run on the rig **and** the binding reason is a
    GPU-count shortfall on a single-card rig (the canonical club-3090 #58 /
    SINGLE_CARD.md situation — a 2-GPU TP preset on one 3090/4090). A pure
    VRAM warning on a 2-GPU rig is *not* an escape-hatch case (that's the
    tuned-mem-util path, which `can_run` already allows).
    """
    if candidate.can_run:
        return EscapeHatch(triggered=False, reason="preset fits", fallback_preset=None)

    gpu_fail = any(
        c.dimension == "gpu_count" and c.status == "fail"
        for c in candidate.report.checks
    )
    if gpu_fail and rig.gpu_count <= 1:
        need = candidate.requires_min_gpu_count or 2
        reason = (
            f"{candidate.preset_id} needs {need} GPU(s) for tensor-parallel; "
            f"this rig has {rig.gpu_count}"
        )
        return EscapeHatch(
            triggered=True,
            reason=reason,
            fallback_preset=candidate.fallback_preset,
        )

    # Other hard failures (SM floor, etc.) are not single-card escape-hatch
    # cases — there's no fallback preset that fixes an unsupported GPU arch.
    return EscapeHatch(
        triggered=False,
        reason=f"{candidate.preset_id} cannot run (non-GPU-count failure)",
        fallback_preset=candidate.fallback_preset,
    )


def emit_launch_command(preset_id: str, *, port: Optional[int] = None) -> list[str]:
    """Build the argv the wizard resolves to: ``sndr launch <preset> [--port N]``.

    Returned as a token list so the caller can either render it (the
    scriptable ``--dry-run`` path prints ``" ".join(...)``) or hand it straight
    to the launcher. Keeping the wizard's output a plain ``sndr launch`` call
    means the no-args wizard and the flag-based ``sndr launch <preset>`` share
    one execution path — the wizard is a front-end, not a parallel launcher.
    """
    argv = ["sndr", "launch", preset_id]
    if port is not None:
        argv += ["--port", str(port)]
    return argv


__all__ = [
    "Candidate",
    "Catalog",
    "EscapeHatch",
    "SINGLE_CARD_DOC",
    "build_candidate",
    "build_catalog",
    "emit_launch_command",
    "escape_hatch_for",
]
