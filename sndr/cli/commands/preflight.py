# SPDX-License-Identifier: Apache-2.0
"""CLI command: ``sndr preflight <preset>``.

Projects a preset's hardware envelope (``card.hardware_fit``, else the composed
hardware) against the live rig — or a ``--rig <hardware_id>`` / ``--fake-gpus``
target — and reports whether the rig can run the preset (VRAM / GPU-count /
SM / engine-pin). This is the Genesis analogue of club-3090's
``scripts/preflight.sh`` ``preflight_compose_hardware`` (noonghunna/club-3090@
master), for our YAML-preset model rather than their per-compose files.

Examples::

    sndr preflight prod-qwen3.6-35b-balanced
    sndr preflight prod-gemma4-26b-default --rig single-3090-24gbvram
    sndr preflight prod-qwen3.6-27b-tq-k8v4 --fake-gpus "RTX 3090:24576:8.6"
    sndr --output json preflight prod-qwen3.6-35b-balanced
"""
from __future__ import annotations

import argparse
import json

from sndr.model_configs.preflight_fit import (
    RigProbe,
    evaluate_fit,
    resolve_required_envelope,
    rig_from_fake_spec,
    rig_from_hardware_def,
)

_GLYPH = {"pass": "✓", "fail": "✗", "warn": "!", "skip": "·"}


class PreflightCommand:
    name = "preflight"
    help = "Project a preset's hardware envelope against a rig (can it run?)."

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "preset",
            help="Preset alias to check (e.g. prod-qwen3.6-35b-balanced).",
        )
        parser.add_argument(
            "--rig",
            default=None,
            metavar="HARDWARE_ID",
            help="Project against a builtin hardware definition instead of the "
                 "live rig (e.g. single-3090-24gbvram). Offline, no nvidia-smi.",
        )
        parser.add_argument(
            "--fake-gpus",
            default=None,
            metavar="SPEC",
            help="Project against a synthetic rig. Spec: "
                 "'name:vram_mib:cc;...' e.g. 'RTX 3090:24576:8.6'. Offline.",
        )

    def execute(self, args: argparse.Namespace) -> int:
        from sndr.model_configs.registry_v2 import (
            load_alias,
            load_hardware,
            load_preset_def,
        )
        from sndr.model_configs.schema import SchemaError

        preset_id = args.preset

        # Resolve the preset (composed cfg + typed preset def with the card).
        try:
            cfg = load_alias(preset_id)
            preset_def = load_preset_def(preset_id)
        except (SchemaError, FileNotFoundError, KeyError) as e:
            self._emit_error(args, preset_id, f"could not resolve preset: {e}")
            return 2
        except Exception as e:  # pragma: no cover — unexpected loader error
            self._emit_error(
                args, preset_id,
                f"unexpected error resolving preset ({type(e).__name__}): {e}",
            )
            return 2

        env = resolve_required_envelope(cfg, preset_def)

        # Resolve the rig: --fake-gpus > --rig > live nvidia-smi.
        if args.fake_gpus is not None:
            rig = rig_from_fake_spec(args.fake_gpus)
        elif args.rig is not None:
            try:
                hw_def = load_hardware(args.rig)
            except (SchemaError, FileNotFoundError, KeyError) as e:
                self._emit_error(
                    args, preset_id, f"could not load --rig {args.rig!r}: {e}",
                )
                return 2
            rig = rig_from_hardware_def(hw_def, source=f"rig:{args.rig}")
        else:
            rig = RigProbe().detect()

        report = evaluate_fit(preset_id, env, rig)

        if args.output == "json":
            print(json.dumps(_report_to_dict(report, env), indent=2))
        else:
            _print_report(report, env, rig)

        # Exit code: 0 = can run (incl. warnings), 1 = cannot run.
        return 0 if report.can_run else 1

    def _emit_error(self, args, preset_id, msg) -> None:
        if args.output == "json":
            print(json.dumps({"preset": preset_id, "error": msg}, indent=2))
        else:
            print(f"preflight {preset_id}: ERROR — {msg}")


def _report_to_dict(report, env) -> dict:
    return {
        "preset": report.preset_id,
        "verdict": report.verdict,
        "can_run": report.can_run,
        "rig_source": report.rig_source,
        "envelope_source": report.envelope_source,
        "required": {
            "min_vram_gb": env.requires_min_vram_gb,
            "min_gpu_count": env.requires_min_gpu_count,
            "tensor_parallel": env.tensor_parallel,
            "min_cuda_capability": (
                list(env.requires_min_cuda_capability)
                if env.requires_min_cuda_capability else None
            ),
            "engine_pin": env.engine_pin,
        },
        "checks": [
            {
                "dimension": c.dimension,
                "status": c.status,
                "required": c.required,
                "detected": c.detected,
                "message": c.message,
            }
            for c in report.checks
        ],
    }


def _print_report(report, env, rig) -> None:
    print(f"preflight: {report.preset_id}")
    print(f"  rig:       {report.rig_source} "
          f"({rig.gpu_count} GPU(s)"
          + (f", {rig.min_vram_gb} GB/GPU" if rig.min_vram_gb else "")
          + (f", sm_{rig.min_compute_cap[0]}.{rig.min_compute_cap[1]}"
             if rig.min_compute_cap else "")
          + ")")
    print(f"  envelope:  {report.envelope_source}")
    print("  " + "─" * 64)
    for c in report.checks:
        glyph = _GLYPH.get(c.status, "?")
        print(f"  {glyph} {c.dimension:<16} {c.status.upper():<5} "
              f"need {c.required} · have {c.detected}")
        print(f"      {c.message}")
    print("  " + "─" * 64)
    print(f"  VERDICT: {report.verdict}")
    if not report.can_run:
        print("           (one or more hard requirements unmet — see ✗ rows; "
              "single-card users → docs/SINGLE_CARD.md)")


__all__ = ["PreflightCommand"]
