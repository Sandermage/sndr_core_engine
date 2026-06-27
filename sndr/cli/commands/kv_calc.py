# SPDX-License-Identifier: Apache-2.0
"""CLI command: ``sndr kv-calc <preset>`` (alias ``sndr fit``).

Byte-level VRAM / KV projection — "given THIS ctx / kv-format / max-num-seqs /
tp, what's my ACTUAL per-card GB and will it OOM?". The Genesis analogue of
club-3090's ``tools/kv-calc.py``, calibrated to OUR hardware (2× A5000 24 GB,
dev424). Where ``sndr preflight`` answers the ENVELOPE question (clears the
declared min-VRAM floor + SM + GPU count?), ``kv-calc`` answers the BYTE-LEVEL
question with a PASS / TIGHT / FAIL verdict + a weights/KV/activation/headroom
breakdown.

Examples::

    sndr kv-calc prod-qwen3.6-35b-balanced
    sndr kv-calc prod-qwen3.6-35b-balanced --rig single-3090-24gbvram
    sndr kv-calc prod-qwen3.6-27b-tq-k8v4 --fake-gpus "RTX A5000:24564:8.6"
    sndr kv-calc prod-qwen3.6-35b-balanced --ctx 131072 --kv-breakdown
    sndr kv-calc prod-qwen3.6-27b-tq-k8v4 --solve-max-ctx
    sndr --output json kv-calc prod-qwen3.6-35b-balanced

    # Whole-catalog fit table — "which of my models fit which card / ctx before
    # I download anything?". Projects EVERY builtin preset against each card.
    sndr kv-calc --fit-all
    sndr kv-calc --fit-all --cards 24,48,80
    sndr --output json kv-calc --fit-all --card 24
"""
from __future__ import annotations

import argparse
import json
from typing import Optional

from sndr.model_configs import kv_projector as kp


_VERDICT_GLYPH = {"PASS": "✓", "TIGHT": "!", "FAIL": "✗"}


class KvCalcCommand:
    name = "kv-calc"
    help = "Project a preset's per-card VRAM/KV bytes against a rig (will it OOM?)."

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "preset", nargs="?", default=None,
            help="Preset alias to project (e.g. prod-qwen3.6-35b-balanced). "
                 "Omit with --fit-all to project the whole catalog.",
        )
        parser.add_argument(
            "--fit-all", action="store_true",
            help="Project EVERY builtin preset against each card into one fit "
                 "table ('which of my models fit which card/ctx?'). Offline; "
                 "uses --cards / --card / --rig or a default 24/48/80 set.",
        )
        parser.add_argument(
            "--cards", default=None, metavar="GB[,GB...]",
            help="Comma-separated per-card VRAM sizes for --fit-all "
                 "(e.g. 24,48,80). Default: 24,48,80.",
        )
        parser.add_argument(
            "--rig", default=None, metavar="HARDWARE_ID",
            help="Project against a builtin hardware definition (offline, no "
                 "nvidia-smi) instead of the live rig.",
        )
        parser.add_argument(
            "--card", default=None, metavar="VRAM_GB",
            help="Per-card VRAM in GiB for a quick ad-hoc rig (e.g. --card 24). "
                 "Overrides --rig / live probe.",
        )
        parser.add_argument(
            "--fake-gpus", default=None, metavar="SPEC",
            help="Synthetic rig, club-3090 style 'name:vram_mib:cc;...' "
                 "(e.g. 'RTX A5000:24564:8.6;RTX A5000:24564:8.6'). Offline.",
        )
        parser.add_argument(
            "--ctx", default=None, type=str, metavar="N",
            help="Context override (e.g. 131072 or 128k). Default: preset's "
                 "max_model_len.",
        )
        parser.add_argument(
            "--max-num-seqs", default=None, type=int, metavar="N",
            help="Concurrency override. Default: preset's max_num_seqs.",
        )
        parser.add_argument(
            "--kv-format", default=None, metavar="FMT",
            help="KV format override (turboquant_k8v4|fp8_e5m2|bf16|...). "
                 "Default: preset's kv_cache_dtype.",
        )
        parser.add_argument(
            "--solve-max-ctx", action="store_true",
            help="Report the largest max_ctx that still PASS/TIGHT-fits, then exit.",
        )
        parser.add_argument(
            "--kv-breakdown", action="store_true",
            help="Show the full per-component byte breakdown (default: summary).",
        )

    # ── execution ──

    def execute(self, args: argparse.Namespace) -> int:
        from sndr.model_configs.registry_v2 import (
            load_alias,
            load_hardware,
            load_model,
            load_preset_def,
        )
        from sndr.model_configs.schema import SchemaError

        # Whole-catalog fit table — no single preset positional needed.
        if args.fit_all:
            return self._do_fit_all(args, load_hardware)

        preset_id = args.preset
        if not preset_id:
            return self._error(
                args, "<none>",
                "a preset alias is required (or pass --fit-all to project the "
                "whole catalog).",
            )

        # Resolve the composed cfg (operating point) + the V2 ModelDef (shape).
        try:
            cfg = load_alias(preset_id)
            preset_def = load_preset_def(preset_id)
            model_def = load_model(preset_def.model)
        except (SchemaError, FileNotFoundError, KeyError, AttributeError) as e:
            return self._error(args, preset_id, f"could not resolve preset: {e}")
        except Exception as e:  # pragma: no cover — unexpected loader error
            return self._error(
                args, preset_id,
                f"unexpected error resolving preset ({type(e).__name__}): {e}",
            )

        shape = model_def.capabilities.shape
        if shape is None or shape.num_attention_layers is None:
            return self._error(
                args, preset_id,
                f"model {preset_def.model!r} declares no byte-level shape "
                "(capabilities.shape) — cannot project. Run `sndr preflight` "
                "for the envelope check instead.",
            )

        # Resolve the rig per-card VRAM: --card > --fake-gpus > --rig > live.
        vram_gib, rig_source = self._resolve_rig(
            args, load_hardware,
        )
        if vram_gib is None:
            return self._error(
                args, preset_id,
                "could not determine a per-card VRAM — pass --card <GB>, "
                "--fake-gpus, --rig <hardware_id>, or run on a rig with "
                "nvidia-smi.",
            )

        ctx_override = _parse_ctx(args.ctx)

        if args.solve_max_ctx:
            return self._do_solve(args, cfg, shape, vram_gib, rig_source, preset_id)

        try:
            projection = kp.project(
                cfg,
                kp.ProjectorRig(vram_gib_per_card=vram_gib, gpu_count=1,
                                name=rig_source),
                shape=shape,
                ctx=ctx_override,
                max_num_seqs=args.max_num_seqs,
                kv_format=args.kv_format,
                preset_id=preset_id,
            )
        except ValueError as e:
            return self._error(args, preset_id, str(e))

        if args.output == "json":
            print(json.dumps(_projection_to_dict(projection, rig_source), indent=2))
        else:
            _print_projection(projection, rig_source, full=args.kv_breakdown)

        # Exit code: 0 = PASS/TIGHT (boots), 1 = FAIL (won't boot).
        return 0 if projection.verdict in ("PASS", "TIGHT") else 1

    # ── rig + solve helpers ──

    def _resolve_rig(self, args, load_hardware) -> tuple[Optional[float], str]:
        if args.card is not None:
            try:
                return float(args.card), f"card:{args.card}GB"
            except ValueError:
                return None, "card:invalid"
        if args.fake_gpus is not None:
            from sndr.model_configs.preflight_fit import rig_from_fake_spec
            return _precise_vram_gib(rig_from_fake_spec(args.fake_gpus)), "fake"
        if args.rig is not None:
            from sndr.model_configs.preflight_fit import rig_from_hardware_def
            try:
                hw_def = load_hardware(args.rig)
            except Exception:  # noqa: BLE001 — surfaced as error below
                return None, f"rig:{args.rig}:load-failed"
            rig = rig_from_hardware_def(hw_def, source=f"rig:{args.rig}")
            return _precise_vram_gib(rig), f"rig:{args.rig}"
        # Live probe.
        from sndr.model_configs.preflight_fit import RigProbe
        return _precise_vram_gib(RigProbe().detect()), "nvidia-smi"

    def _do_solve(self, args, cfg, shape, vram_gib, rig_source, preset_id) -> int:
        op = kp._resolve_operating_point(cfg)
        kv_format = args.kv_format or op["kv_format"]
        # Cap the search at 4× the preset's declared max_model_len (or 1M) so a
        # KV-light hybrid model whose pool never exhausts the budget reports a
        # ceiling tied to the operator's intended envelope, not the raw 1M cap.
        declared = int(op["ctx"] or 0)
        ctx_cap = max(declared * 4, 262_144) if declared else 1_048_576
        max_ctx = kp.solve_max_ctx(
            shape,
            kv_format=kv_format,
            max_num_seqs=(args.max_num_seqs or op["max_num_seqs"]),
            tp=op["tp"],
            mem_util=op["mem_util"],
            vram_gib=vram_gib,
            mtp=op["mtp"],
            mtp_n=op["mtp_n"],
            ctx_cap=ctx_cap,
        )
        if args.output == "json":
            print(json.dumps({
                "preset": preset_id,
                "rig": rig_source,
                "vram_gib_per_card": vram_gib,
                "kv_format": kv_format,
                "tp": op["tp"],
                "max_num_seqs": args.max_num_seqs or op["max_num_seqs"],
                "solved_max_ctx": max_ctx,
                "provisional": kp._is_provisional(shape),
            }, indent=2))
        else:
            print(f"kv-calc solve-max-ctx: {preset_id}")
            print(f"  rig:        {rig_source} ({vram_gib:.0f} GiB/card)")
            print(f"  kv-format:  {kv_format}  TP={op['tp']}  "
                  f"max_num_seqs={args.max_num_seqs or op['max_num_seqs']}")
            print(f"  MAX CTX:    {max_ctx:,} tokens (largest that PASS/TIGHT-fits)")
            if kp._is_provisional(shape):
                print("  NOTE:       calibration PROVISIONAL for this model "
                      "(no live engine anchor) — treat as ±1.5 GiB.")
        return 0 if max_ctx > 0 else 1

    # ── fit-all (whole-catalog table) ──

    def _resolve_fit_all_cards(self, args, load_hardware) -> list[float]:
        """Resolve the list of per-card VRAM sizes for the fit-all table.

        Precedence: --cards (explicit list) > --card (single) > --fake-gpus /
        --rig (the resolved rig's card size) > the default 24/48/80 set. The
        default keeps --fit-all fully offline (no nvidia-smi) so the GUI / CI can
        project the catalog before any host exists.
        """
        if args.cards:
            out: list[float] = []
            for tok in str(args.cards).split(","):
                tok = tok.strip()
                if not tok:
                    continue
                try:
                    out.append(float(tok))
                except ValueError:
                    continue
            if out:
                return out
        if args.card is not None:
            try:
                return [float(args.card)]
            except ValueError:
                pass
        if args.fake_gpus is not None or args.rig is not None:
            vram, _ = self._resolve_rig(args, load_hardware)
            if vram is not None:
                return [vram]
        # Default offline ladder: 24 GiB (3090/A5000), 48 GiB (A6000/L40),
        # 80 GiB (A100/H100).
        return [24.0, 48.0, 80.0]

    def _build_fit_all_entries(self, args) -> tuple[list, list[str]]:
        """Resolve every builtin preset into a ``FitAllEntry`` (skip-with-note
        for shapeless models — handled downstream by ``fit_all``). Returns the
        entries plus a list of resolve-error notes (presets that wouldn't load)."""
        from sndr.model_configs.registry_v2 import (
            list_presets, load_alias, load_model, load_preset_def,
        )
        from sndr.model_configs.schema import SchemaError

        ctx_override = _parse_ctx(args.ctx)
        entries: list = []
        errors: list[str] = []
        for alias in list_presets():
            try:
                cfg = load_alias(alias)
                preset_def = load_preset_def(alias)
                model_def = load_model(preset_def.model)
            except (SchemaError, FileNotFoundError, KeyError, AttributeError) as e:
                errors.append(f"{alias}: could not resolve ({e})")
                continue
            except Exception as e:  # noqa: BLE001 — keep the table going
                errors.append(f"{alias}: unexpected ({type(e).__name__}: {e})")
                continue

            shape = getattr(model_def.capabilities, "shape", None)
            op = kp._resolve_operating_point(cfg)
            entries.append(kp.FitAllEntry(
                preset_id=alias,
                shape=shape,
                engine=getattr(cfg, "engine", "vllm"),
                kv_format=(args.kv_format or op["kv_format"]),
                ctx=(ctx_override if ctx_override is not None else op["ctx"]),
                max_num_seqs=(args.max_num_seqs or op["max_num_seqs"]),
                tp=op["tp"],
                mem_util=op["mem_util"],
                mtp=op["mtp"],
                mtp_n=op["mtp_n"],
            ))
        return entries, errors

    def _do_fit_all(self, args, load_hardware) -> int:
        cards = self._resolve_fit_all_cards(args, load_hardware)
        entries, errors = self._build_fit_all_entries(args)
        rows = kp.fit_all(entries, cards)

        if args.output == "json":
            print(json.dumps({
                "mode": "fit-all",
                "cards_gib": cards,
                "resolve_errors": errors,
                "rows": [_fit_row_to_dict(r) for r in rows],
            }, indent=2))
        else:
            _print_fit_all(rows, cards, errors)

        # Exit 0 whenever the table rendered — --fit-all is a survey, not a gate
        # (a single FAIL row is information, not a command failure). Non-zero
        # only if NOTHING could be projected at all (no entries resolved).
        return 0 if rows else 1

    def _error(self, args, preset_id, msg) -> int:
        if args.output == "json":
            print(json.dumps({"preset": preset_id, "error": msg}, indent=2))
        else:
            print(f"kv-calc {preset_id}: ERROR — {msg}")
        return 2


# ─── render helpers ──────────────────────────────────────────────────────────


def _precise_vram_gib(rig) -> Optional[float]:
    """Smallest card's VRAM in GiB at MiB precision (the binding TP constraint).

    Uses the raw ``vram_mib`` rather than ``rig.min_vram_gb`` (which floors to
    whole GB and silently under-budgets a 24564 MiB A5000 by ~1 GiB — enough to
    flip a borderline 35B verdict)."""
    if not getattr(rig, "gpus", None):
        return None
    mib = min(g.vram_mib for g in rig.gpus if g.vram_mib)
    return (mib / 1024.0) if mib else None


def _parse_ctx(s: Optional[str]) -> Optional[int]:
    if s is None:
        return None
    s = str(s).strip().lower()
    if s.endswith("k"):
        return int(float(s[:-1]) * 1024)
    if s.endswith("m"):
        return int(float(s[:-1]) * 1024 * 1024)
    return int(s)


def _projection_to_dict(p: kp.Projection, rig_source: str) -> dict:
    return {
        "preset": p.preset_id,
        "rig": rig_source,
        "verdict": p.verdict,
        "provisional": p.provisional,
        "operating_point": {
            "ctx": p.ctx,
            "max_num_seqs": p.max_num_seqs,
            "tp": p.tp,
            "mem_util": p.mem_util,
            "kv_format": p.kv_format,
            "vram_gib_per_card": p.vram_gib,
        },
        "per_card_gib": {
            "weights": round(p.weights_gib, 3),
            "kv_pool_requested": round(p.kv_pool_requested_gib, 3),
            "kv_pool_actual": round(p.kv_pool_actual_gib, 3),
            "recurrent_state": round(p.recurrent_state_gib, 3),
            "activation": round(p.activation_gib, 3),
            "cudagraph_overhead": round(p.cudagraph_overhead_gib, 3),
            "drafter": round(p.drafter_gib, 3),
            "fixed_footprint": round(p.fixed_gib, 3),
            "total": round(p.total_gib, 3),
            "budget": round(p.budget_gib, 3),
            "headroom": round(p.headroom_gib, 3),
            "available_for_kv": round(p.available_for_kv_gib, 3),
        },
        "utilization": round(p.utilization, 4),
        "notes": list(p.notes),
    }


def _print_projection(p: kp.Projection, rig_source: str, *, full: bool) -> None:
    glyph = _VERDICT_GLYPH.get(p.verdict, "?")
    print(f"kv-calc: {p.preset_id}")
    print(f"  rig:        {rig_source} ({p.vram_gib:.0f} GiB/card, TP={p.tp})")
    print(f"  point:      ctx={p.ctx:,}  seqs={p.max_num_seqs}  "
          f"kv={p.kv_format}  util={p.mem_util}")
    print("  " + "─" * 60)
    rows = [
        ("Model weights (÷TP)", p.weights_gib),
        ("KV pool (requested)", p.kv_pool_requested_gib),
    ]
    if full:
        rows += [
            ("KV pool (actual, capped)", p.kv_pool_actual_gib),
            ("Recurrent state (GDN/Mamba)", p.recurrent_state_gib),
            ("Activation peak", p.activation_gib),
            ("Cudagraph + workspace", p.cudagraph_overhead_gib),
            ("Drafter (MTP/DFlash)", p.drafter_gib),
        ]
    else:
        rows += [
            ("Activation + overhead + state",
             p.activation_gib + p.cudagraph_overhead_gib
             + p.recurrent_state_gib + p.drafter_gib),
        ]
    for label, val in rows:
        print(f"  {label:<32s} {val:>8.2f} GiB / card")
    print("  " + "─" * 60)
    print(f"  {'FIXED footprint':<32s} {p.fixed_gib:>8.2f} GiB / card")
    print(f"  {'Available for KV':<32s} {p.available_for_kv_gib:>8.2f} GiB / card")
    print(f"  {'TOTAL (committed)':<32s} {p.total_gib:>8.2f} GiB / card  "
          f"/ {p.budget_gib:.2f} budget  ({p.utilization * 100:.0f}%)")
    print(f"  {'Headroom':<32s} {p.headroom_gib:>8.2f} GiB / card")
    print("  " + "─" * 60)
    print(f"  VERDICT: {glyph} {p.verdict}"
          + ("   [calibration PROVISIONAL]" if p.provisional else ""))
    for n in p.notes:
        print(f"    · {n}")


def _fit_row_to_dict(r: kp.FitAllRow) -> dict:
    return {
        "preset": r.preset_id,
        "engine": r.engine,
        "card_gib": r.card_gib,
        "verdict": r.verdict,
        "projected_total_gib": (round(r.projected_total_gib, 3)
                                if r.projected_total_gib is not None else None),
        "max_ctx_fit": r.max_ctx_fit,
        "provisional": r.provisional,
        "notes": list(r.notes),
    }


def _fmt_ctx(n: int) -> str:
    """Compact ctx for the table: 131072 → '128k', 0 → '—'."""
    if not n:
        return "—"
    if n >= 1024 and n % 1024 == 0:
        return f"{n // 1024}k"
    if n >= 1000:
        return f"{n / 1000:.0f}k"
    return str(n)


def _print_fit_all(rows, cards, errors) -> None:
    """Render the whole-catalog fit table grouped by card size."""
    card_set = [float(c) for c in cards]
    print("kv-calc --fit-all  (which of my models fit which card / ctx?)")
    print(f"  cards: {', '.join(f'{c:.0f} GiB' for c in card_set)}")
    print("  verdict: " + "  ".join(
        f"{g} {v}" for v, g in _VERDICT_GLYPH.items()) + "   ? SKIP (no shape)")

    by_card: dict[float, list] = {c: [] for c in card_set}
    for r in rows:
        by_card.setdefault(r.card_gib, []).append(r)

    hdr = (f"  {'PRESET':<34s} {'ENGINE':<10s} {'VERDICT':<8s} "
           f"{'TOTAL':>9s}  {'MAX-CTX-FIT':>12s}")
    for card in card_set:
        print()
        print(f"  ═══ {card:.0f} GiB / card " + "═" * 40)
        print(hdr)
        print("  " + "─" * 78)
        for r in sorted(by_card.get(card, []), key=lambda x: x.preset_id):
            glyph = _VERDICT_GLYPH.get(r.verdict, "?")
            total = (f"{r.projected_total_gib:>6.1f} GiB"
                     if r.projected_total_gib is not None else "      —   ")
            prov = " *" if (r.provisional and r.verdict != "SKIP") else ""
            print(f"  {r.preset_id:<34s} {r.engine:<10s} "
                  f"{glyph} {r.verdict:<6s} {total}  "
                  f"{_fmt_ctx(r.max_ctx_fit):>12s}{prov}")
    print()
    print("  * = calibration PROVISIONAL (no live engine anchor) — ±1.5 GiB.")
    print("  MAX-CTX-FIT = largest ctx that still PASS/TIGHT-fits that card "
          "at the preset's concurrency.")
    if errors:
        print()
        print("  resolve notes (presets that could not be loaded):")
        for e in errors:
            print(f"    · {e}")


__all__ = ["KvCalcCommand"]
