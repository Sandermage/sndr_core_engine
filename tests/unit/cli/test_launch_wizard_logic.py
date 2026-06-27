# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the pure ``sndr launch`` wizard decision logic.

Exercises the I/O-free core (:mod:`sndr.cli.wizard.launch_wizard`) with fake
preset cards / composed configs and synthetic rigs — no TTY, no nvidia-smi, no
pydantic, no torch. Covers the three contract points the wizard must guarantee:

  1. fit-filtering — only fitting presets appear in the default menu, with a
     "show all" toggle; production presets float to the top.
  2. escape-hatch — a 2-GPU preset on a single card triggers the SINGLE_CARD
     route and surfaces the card's ``fallback_preset``.
  3. command emission — the wizard resolves to a plain ``sndr launch <preset>``
     argv (optionally with ``--port``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sndr.cli.wizard.launch_wizard import (
    SINGLE_CARD_DOC,
    build_catalog,
    emit_launch_command,
    escape_hatch_for,
)
from sndr.model_configs.preflight_fit import rig_from_fake_spec


# ── Fakes: minimal stand-ins for the typed card / composed cfg ───────────────


@dataclass
class _FakeMetric:
    kind: str
    value: float


@dataclass
class _FakeHardwareFit:
    requires_min_vram_gb: Optional[int] = None
    tensor_parallel: Optional[int] = None
    requires_min_gpu_count: Optional[int] = None
    requires_min_cuda_capability: Optional[tuple] = None
    engine_pin: Optional[str] = None


@dataclass
class _FakeCard:
    title: str
    status: str
    hardware_fit: Optional[_FakeHardwareFit] = None
    primary_metric: Optional[_FakeMetric] = None
    fallback_preset: Optional[str] = None


@dataclass
class _FakePresetDef:
    card: Optional[_FakeCard]


@dataclass
class _FakeCfg:
    """Composed config — only the attrs resolve_required_envelope reads."""
    hardware: object = None
    vllm_pin_required: Optional[str] = None


def _corpus():
    """A small fake catalog covering the menu's interesting cases."""
    return {
        # 2-GPU production preset, measured 241 TPS, declares a single-card fallback
        "prod-35b-balanced": _FakePresetDef(
            _FakeCard(
                title="35B balanced (2x A5000)",
                status="production",
                hardware_fit=_FakeHardwareFit(
                    requires_min_vram_gb=22, tensor_parallel=2,
                    requires_min_gpu_count=2,
                    requires_min_cuda_capability=(8, 6),
                ),
                primary_metric=_FakeMetric("agg_TPS", 241.4),
                fallback_preset="example-3090-single",
            )
        ),
        # 2-GPU experimental, lower TPS — should sort BELOW the production one
        "exp-35b-multiconc": _FakePresetDef(
            _FakeCard(
                title="35B multi-conc (experimental)",
                status="experimental",
                hardware_fit=_FakeHardwareFit(
                    requires_min_gpu_count=2, tensor_parallel=2,
                    requires_min_cuda_capability=(8, 6),
                ),
                primary_metric=_FakeMetric("agg_TPS", 180.0),
                fallback_preset=None,
            )
        ),
        # 1-GPU example — runs on a single 3090, no fallback needed
        "example-3090-single": _FakePresetDef(
            _FakeCard(
                title="Single 3090 hybrid-GDN",
                status="example",
                hardware_fit=_FakeHardwareFit(
                    requires_min_gpu_count=1, tensor_parallel=1,
                    requires_min_cuda_capability=(8, 6),
                ),
                primary_metric=None,  # unmeasured → no metric label
            )
        ),
        # tombstone — must never appear in the menu
        "dead-preset": _FakePresetDef(
            _FakeCard(title="retired", status="tombstone")
        ),
    }


def _loaders(corpus):
    def card_loader(pid):
        return corpus[pid]

    def cfg_loader(_pid):
        return _FakeCfg()

    return card_loader, cfg_loader


def _build(rig_spec):
    corpus = _corpus()
    card_loader, cfg_loader = _loaders(corpus)
    rig = rig_from_fake_spec(rig_spec)
    return build_catalog(
        rig,
        preset_ids=list(corpus),
        card_loader=card_loader,
        cfg_loader=cfg_loader,
    )


# ── 1. fit-filtering ─────────────────────────────────────────────────────────


class TestFitFiltering:
    def test_single_card_default_menu_excludes_2gpu_presets(self):
        cat = _build("RTX 3090:24576:8.6")
        menu_ids = [c.preset_id for c in cat.menu(show_all=False)]
        # Only the 1-GPU preset fits a single 3090.
        assert "example-3090-single" in menu_ids
        assert "prod-35b-balanced" not in menu_ids
        assert "exp-35b-multiconc" not in menu_ids

    def test_show_all_includes_non_fitting_but_not_tombstone(self):
        cat = _build("RTX 3090:24576:8.6")
        all_ids = [c.preset_id for c in cat.menu(show_all=True)]
        assert "prod-35b-balanced" in all_ids  # non-fitting, shown on toggle
        assert "exp-35b-multiconc" in all_ids
        assert "dead-preset" not in all_ids  # tombstone hidden even on show_all

    def test_two_card_rig_fits_the_2gpu_presets(self):
        cat = _build("RTX A5000:24564:8.6;RTX A5000:24564:8.6")
        fitting = [c.preset_id for c in cat.fitting()]
        assert "prod-35b-balanced" in fitting
        assert "exp-35b-multiconc" in fitting

    def test_production_sorts_above_experimental(self):
        cat = _build("RTX A5000:24564:8.6;RTX A5000:24564:8.6")
        order = [c.preset_id for c in cat.fitting()]
        assert order.index("prod-35b-balanced") < order.index("exp-35b-multiconc")

    def test_metric_label_rendered_and_unmeasured_is_none(self):
        cat = _build("RTX A5000:24564:8.6;RTX A5000:24564:8.6")
        by_id = {c.preset_id: c for c in cat.candidates}
        assert by_id["prod-35b-balanced"].metric_label == "agg_TPS=241.4"
        assert by_id["example-3090-single"].metric_label is None

    def test_verdict_string_present_per_row(self):
        cat = _build("RTX A5000:24564:8.6;RTX A5000:24564:8.6")
        by_id = {c.preset_id: c for c in cat.candidates}
        assert by_id["prod-35b-balanced"].verdict in (
            "CAN RUN", "RUNNABLE (with warnings)",
        )


# ── 2. escape-hatch ──────────────────────────────────────────────────────────


class TestEscapeHatch:
    def test_2gpu_preset_on_single_card_triggers_with_fallback(self):
        cat = _build("RTX 3090:24576:8.6")
        cand = next(c for c in cat.candidates if c.preset_id == "prod-35b-balanced")
        rig = cat.rig
        hatch = escape_hatch_for(cand, rig)
        assert hatch.triggered is True
        assert hatch.fallback_preset == "example-3090-single"
        assert hatch.doc == SINGLE_CARD_DOC
        assert "needs 2" in hatch.reason or "needs 2 GPU" in hatch.reason

    def test_no_fallback_still_triggers_but_fallback_none(self):
        cat = _build("RTX 3090:24576:8.6")
        cand = next(c for c in cat.candidates if c.preset_id == "exp-35b-multiconc")
        hatch = escape_hatch_for(cand, cat.rig)
        assert hatch.triggered is True
        assert hatch.fallback_preset is None

    def test_fitting_preset_does_not_trigger(self):
        cat = _build("RTX 3090:24576:8.6")
        cand = next(c for c in cat.candidates if c.preset_id == "example-3090-single")
        hatch = escape_hatch_for(cand, cat.rig)
        assert hatch.triggered is False

    def test_2gpu_preset_on_two_cards_does_not_trigger(self):
        cat = _build("RTX A5000:24564:8.6;RTX A5000:24564:8.6")
        cand = next(c for c in cat.candidates if c.preset_id == "prod-35b-balanced")
        hatch = escape_hatch_for(cand, cat.rig)
        assert hatch.triggered is False


# ── 3. command emission ──────────────────────────────────────────────────────


class TestCommandEmission:
    def test_basic_command(self):
        assert emit_launch_command("prod-35b-balanced") == [
            "sndr", "launch", "prod-35b-balanced",
        ]

    def test_command_with_port(self):
        assert emit_launch_command("prod-35b-balanced", port=8101) == [
            "sndr", "launch", "prod-35b-balanced", "--port", "8101",
        ]

    def test_command_is_plain_sndr_launch_front_end(self):
        # The wizard must resolve to the SAME entrypoint as the flag path —
        # never a parallel launcher.
        argv = emit_launch_command("x")
        assert argv[:2] == ["sndr", "launch"]
