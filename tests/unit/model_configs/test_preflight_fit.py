# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the preset hardware fit-check (`sndr preflight` core).

Pure-logic tests for sndr/model_configs/preflight_fit.py — no nvidia-smi,
no docker. The club-3090 ``preflight_compose_hardware`` semantics we mirror:
GPU-count short = hard FAIL, SM short = hard FAIL, VRAM short = WARN on TP>=2
rigs / FAIL on single card, engine-pin = advisory.
"""
from __future__ import annotations

from sndr.model_configs.preflight_fit import (
    DetectedGpu,
    RequiredEnvelope,
    Rig,
    evaluate_fit,
    parse_nvidia_smi_csv,
    rig_from_fake_spec,
    _parse_compute_cap,
)


def _env(**kw) -> RequiredEnvelope:
    base = dict(
        requires_min_vram_gb=21,
        requires_min_gpu_count=2,
        tensor_parallel=2,
        requires_min_cuda_capability=(8, 6),
        engine_pin="0.23.1rc1.dev424+g3f5a1e173",
        source="card.hardware_fit",
    )
    base.update(kw)
    return RequiredEnvelope(**base)


def _rig(n, vram_mib, cc, source="fake") -> Rig:
    return Rig(
        gpus=[DetectedGpu(i, "gpu", vram_mib, cc) for i in range(n)],
        source=source,
    )


def _check(report, dim):
    return next(c for c in report.checks if c.dimension == dim)


class TestEvaluateFit:
    def test_matching_2gpu_rig_can_run(self):
        report = evaluate_fit("p", _env(), _rig(2, 24576, (8, 6)))
        assert report.can_run
        assert report.verdict == "CAN RUN"
        assert _check(report, "gpu_count").status == "pass"
        assert _check(report, "vram").status == "pass"
        assert _check(report, "cuda_capability").status == "pass"

    def test_single_card_fails_gpu_count(self):
        report = evaluate_fit("p", _env(), _rig(1, 24576, (8, 6)))
        assert not report.can_run
        assert report.verdict == "CANNOT RUN"
        assert _check(report, "gpu_count").status == "fail"

    def test_vram_below_floor_on_tp2_is_warn_not_fail(self):
        # club-3090's tuned-mem-util escape hatch: TP>=2 sub-floor = WARN.
        report = evaluate_fit("p", _env(), _rig(2, 15360, (8, 6)))
        assert report.can_run  # warnings don't block
        assert _check(report, "vram").status == "warn"
        assert report.verdict == "RUNNABLE (with warnings)"

    def test_vram_below_floor_on_single_card_is_fail(self):
        # A TP=1 preset on one too-small card has no headroom to trade → FAIL.
        env = _env(requires_min_gpu_count=1, tensor_parallel=1)
        report = evaluate_fit("p", env, _rig(1, 15360, (8, 6)))
        assert not report.can_run
        assert _check(report, "vram").status == "fail"

    def test_sm_below_floor_is_fail(self):
        report = evaluate_fit("p", _env(), _rig(2, 24576, (7, 5)))
        assert not report.can_run
        assert _check(report, "cuda_capability").status == "fail"

    def test_higher_sm_passes(self):
        # sm_8.9 (Ada) clears an sm_8.6 floor.
        report = evaluate_fit("p", _env(), _rig(2, 24576, (8, 9)))
        assert _check(report, "cuda_capability").status == "pass"

    def test_engine_pin_warns_on_live_rig_skips_offline(self):
        live = evaluate_fit("p", _env(), _rig(2, 24576, (8, 6), source="nvidia-smi"))
        assert _check(live, "engine_pin").status == "warn"
        offline = evaluate_fit("p", _env(), _rig(2, 24576, (8, 6), source="fake"))
        assert _check(offline, "engine_pin").status == "skip"

    def test_unspecified_requirements_skip(self):
        env = RequiredEnvelope(
            requires_min_vram_gb=None, requires_min_gpu_count=None,
            tensor_parallel=None, requires_min_cuda_capability=None,
            engine_pin=None, source="composed_hardware",
        )
        report = evaluate_fit("p", env, _rig(1, 8192, (6, 1)))
        # No requirement declared → all SKIP → can_run True.
        assert report.can_run
        assert all(c.status == "skip" for c in report.checks)

    def test_min_vram_uses_smallest_card(self):
        # Heterogeneous rig: a 24 GB + a 16 GB card → binding floor is 16.
        rig = Rig(gpus=[
            DetectedGpu(0, "big", 24576, (8, 6)),
            DetectedGpu(1, "small", 16380, (8, 6)),
        ], source="fake")
        assert rig.min_vram_gb == 15
        report = evaluate_fit("p", _env(), rig)
        assert _check(report, "vram").status == "warn"  # 15 < 21, TP=2


class TestParsers:
    def test_parse_nvidia_smi_csv(self):
        text = "0, NVIDIA RTX A5000, 24564, 8.6\n1, NVIDIA RTX A5000, 24564, 8.6\n"
        gpus = parse_nvidia_smi_csv(text)
        assert len(gpus) == 2
        assert gpus[0].vram_mib == 24564
        assert gpus[0].compute_cap == (8, 6)
        assert "A5000" in gpus[0].name

    def test_parse_nvidia_smi_skips_blank_and_short_lines(self):
        text = "\n0, RTX 3090, 24576, 8.6\ngarbage\n"
        gpus = parse_nvidia_smi_csv(text)
        assert len(gpus) == 1

    def test_fake_spec_single(self):
        rig = rig_from_fake_spec("RTX 3090:24576:8.6")
        assert rig.gpu_count == 1
        assert rig.gpus[0].compute_cap == (8, 6)
        assert rig.min_vram_gb == 24

    def test_fake_spec_multi(self):
        rig = rig_from_fake_spec("RTX A5000:24564:8.6;RTX A5000:24564:8.6")
        assert rig.gpu_count == 2

    def test_compute_cap_parser(self):
        assert _parse_compute_cap("8.6") == (8, 6)
        assert _parse_compute_cap("9") == (9, 0)
        assert _parse_compute_cap("") is None
        assert _parse_compute_cap("bad") is None
