# SPDX-License-Identifier: Apache-2.0
"""V2 layered config — `sndr profile` subcommand (Phase 4, P1).

Subcommands surface the V2 ProfileDef layer:

  sndr profile list [--model <id>]
      List every ProfileDef under `builtin/profile/*.yaml`. With --model,
      filter to profiles whose `parent_model` matches.

  sndr profile show <id>
      Print the resolved ProfileDef: parent model, patches delta
      (enable/disable/override), sizing override, promotion contract.

  sndr profile diff <id>
      Show what would change vs the canonical parent ModelDef.patches —
      a preview of the patches matrix after compose(model, hw, profile).

Read-only. Does not run any patch or modify any file. Promotion CLI
(`sndr profile new/promote/validate`) ships in Phase 5 community SDK.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

from . import _io


__all__ = ["add_argparser", "run_list", "run_show", "run_diff"]


def add_argparser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "profile",
        help="V2 profile layer — list/show/diff ProfileDef definitions.",
        description=(
            "Inspect V2 ProfileDef layer (model_configs/builtin/profile/*.yaml). "
            "Sister command of `sndr hardware` and `sndr model` (V2 layered config)."
        ),
    )
    sub = p.add_subparsers(dest="profile_cmd", required=True)

    p_list = sub.add_parser("list", help="List ProfileDef ids; optionally filter by parent model.")
    p_list.add_argument("--model", default=None,
                        help="Filter to profiles targeting this parent_model id.")
    p_list.add_argument("--json", action="store_true",
                        help="Emit machine-readable JSON.")
    p_list.set_defaults(func=run_list)

    p_show = sub.add_parser("show",
                            help="Print resolved ProfileDef (delta, sizing override, promotion).")
    p_show.add_argument("profile_id", help="profile id (e.g. 'wave9-balanced')")
    p_show.add_argument("--json", action="store_true",
                        help="Emit machine-readable JSON.")
    p_show.set_defaults(func=run_show)

    p_diff = sub.add_parser("diff",
                            help="Show patches matrix delta vs parent ModelDef.patches.")
    p_diff.add_argument("profile_id", help="profile id")
    p_diff.add_argument("--json", action="store_true",
                        help="Emit machine-readable JSON.")
    p_diff.set_defaults(func=run_diff)


def _profile_summary(profile_id: str) -> dict:
    from vllm.sndr_core.model_configs.registry_v2 import load_profile
    p = load_profile(profile_id)
    delta = p.patches_delta
    sz = p.sizing_override
    return {
        "id": p.id,
        "parent_model": p.parent_model,
        "status": p.status,
        "created": p.created,
        "delta_enable_count": len(delta.enable),
        "delta_disable_count": len(delta.disable),
        "delta_override_count": len(delta.override),
        "has_sizing_override": sz is not None,
        "promote_to": p.promotion.promote_to if p.promotion else None,
    }


# ─── list

def run_list(args: argparse.Namespace) -> int:
    from vllm.sndr_core.model_configs.registry_v2 import list_profiles
    from vllm.sndr_core.model_configs.schema import SchemaError

    ids = list_profiles(parent_model=args.model)
    summaries: list[dict] = []
    errors: list[tuple[str, str]] = []
    for pid in ids:
        try:
            summaries.append(_profile_summary(pid))
        except (SchemaError, Exception) as e:
            errors.append((pid, f"{type(e).__name__}: {e}"))

    if args.json:
        out = {
            "filter_model": args.model,
            "profiles": summaries,
            "errors": errors,
        }
        print(json.dumps(out, indent=2, sort_keys=True))
        return 1 if errors else 0

    title = "sndr profile list — V2 ProfileDef registry"
    if args.model:
        title += f"  (filter: parent_model={args.model})"
    print(title)
    print("─" * 60)
    if not summaries and not errors:
        msg = "  (no V2 profile files found"
        if args.model:
            msg += f" with parent_model={args.model!r}"
        msg += ")"
        print(msg)
        return 0
    for s in summaries:
        sz_marker = " sizing-override" if s["has_sizing_override"] else ""
        print(f"  {s['id']}")
        print(f"      parent: {s['parent_model']}  status: {s['status']}  "
              f"delta: +{s['delta_enable_count']}/-{s['delta_disable_count']}"
              f"/~{s['delta_override_count']}{sz_marker}")
    if errors:
        print()
        print("  Errors loading these IDs:")
        for pid, msg in errors:
            print(f"    {pid}: {msg}")
    print()
    print(f"  Total: {len(summaries)} profiles"
          + (f" ({len(errors)} errors)" if errors else ""))
    return 1 if errors else 0


# ─── show

def run_show(args: argparse.Namespace) -> int:
    from vllm.sndr_core.model_configs.registry_v2 import load_profile
    from vllm.sndr_core.model_configs.schema import SchemaError

    try:
        p = load_profile(args.profile_id)
    except SchemaError as e:
        _io.warn(f"profile id {args.profile_id!r}: {e}")
        return 2

    if args.json:
        from dataclasses import asdict
        print(json.dumps(asdict(p), indent=2, sort_keys=True, default=str))
        return 0

    print(f"sndr profile show '{p.id}'")
    print("─" * 60)
    print(f"  parent_model:  {p.parent_model}")
    print(f"  maintainer:    {p.maintainer}")
    print(f"  status:        {p.status}")
    print(f"  created:       {p.created}")
    print()
    d = p.patches_delta
    print("  Patches delta:")
    if d.enable:
        print(f"    enable ({len(d.enable)}):")
        for k, v in sorted(d.enable.items()):
            print(f"      + {k} = {v!r}")
    if d.disable:
        print(f"    disable ({len(d.disable)}):")
        for k in sorted(d.disable):
            print(f"      - {k}")
    if d.override:
        print(f"    override ({len(d.override)}):")
        for k, v in sorted(d.override.items()):
            print(f"      ~ {k} = {v!r}")
    if not (d.enable or d.disable or d.override):
        print("    (empty — uses parent model.patches as-is)")
    print()
    sz = p.sizing_override
    if sz is not None:
        print("  Sizing override (operator tuning for (model × hardware) pair):")
        print(f"    max_model_len:            {sz.max_model_len}")
        print(f"    gpu_memory_utilization:   {sz.gpu_memory_utilization}")
        print(f"    max_num_seqs:             {sz.max_num_seqs}")
        print(f"    max_num_batched_tokens:   {sz.max_num_batched_tokens}")
        print(f"    enable_chunked_prefill:   {sz.enable_chunked_prefill}")
        print(f"    enforce_eager:            {sz.enforce_eager}")
        print(f"    disable_custom_all_reduce:{sz.disable_custom_all_reduce}")
    else:
        print("  Sizing override: none (uses hardware.sizing defaults)")
    print()
    promo = p.promotion
    if promo is not None:
        print("  Promotion:")
        print(f"    promote_to: {promo.promote_to}")
        if promo.validation_required:
            print(f"    validation_required ({len(promo.validation_required)}):")
            for v in promo.validation_required:
                print(f"      • {v}")
    return 0


# ─── diff

def run_diff(args: argparse.Namespace) -> int:
    """Show what the patches matrix looks like AFTER apply_patches_delta
    is run on the parent model's canonical patches. This is the
    same delta the composer applies in compose()."""
    from vllm.sndr_core.model_configs.compose import apply_patches_delta
    from vllm.sndr_core.model_configs.registry_v2 import load_model, load_profile
    from vllm.sndr_core.model_configs.schema import SchemaError

    try:
        p = load_profile(args.profile_id)
        m = load_model(p.parent_model)
    except SchemaError as e:
        _io.warn(f"profile {args.profile_id!r} diff failed: {e}")
        return 2

    canonical = dict(m.patches)
    merged = apply_patches_delta(canonical, p.patches_delta)

    added: list[tuple[str, str]] = []
    removed: list[tuple[str, str]] = []
    changed: list[tuple[str, str, str]] = []

    canonical_keys = set(canonical.keys())
    merged_keys = set(merged.keys())
    for k in sorted(merged_keys - canonical_keys):
        added.append((k, merged[k]))
    for k in sorted(canonical_keys - merged_keys):
        removed.append((k, canonical[k]))
    for k in sorted(canonical_keys & merged_keys):
        if canonical[k] != merged[k]:
            changed.append((k, canonical[k], merged[k]))

    if args.json:
        out = {
            "profile_id": p.id,
            "parent_model": p.parent_model,
            "canonical_count": len(canonical),
            "merged_count": len(merged),
            "added": [{"key": k, "value": v} for k, v in added],
            "removed": [{"key": k, "value": v} for k, v in removed],
            "changed": [
                {"key": k, "canonical": cv, "merged": mv}
                for k, cv, mv in changed
            ],
        }
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0

    print(f"sndr profile diff '{p.id}' vs '{p.parent_model}'")
    print("─" * 60)
    print(f"  canonical patches: {len(canonical)}")
    print(f"  merged patches:    {len(merged)}")
    print(f"  delta: +{len(added)} / -{len(removed)} / ~{len(changed)}")
    print()
    if added:
        print("  Added (profile enable on top of canonical):")
        for k, v in added:
            print(f"    + {k} = {v!r}")
    if removed:
        print("  Removed (profile disable):")
        for k, v in removed:
            print(f"    - {k}  (canonical was {v!r})")
    if changed:
        print("  Changed (profile override):")
        for k, cv, mv in changed:
            print(f"    ~ {k}: {cv!r} → {mv!r}")
    if not (added or removed or changed):
        print("  (no delta — profile matches canonical model.patches)")
    return 0
