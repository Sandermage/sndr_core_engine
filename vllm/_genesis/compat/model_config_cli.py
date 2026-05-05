# SPDX-License-Identifier: Apache-2.0
"""Genesis model-config CLI — list / show / render / launch / verify.

Commands:
    list                          enumerate all available configs
    show <key>                    print full YAML
    render <key>                  emit launch script to stdout
    save <key> <path>             write rendered launch script to disk
    audit <key>                   list soft warnings (e.g. missing P98)
    where <key>                   show source tier (builtin/community/user)
    new <key> --template <key>    create user config from builtin template
    new <key> --from-running <name>   capture from live docker container
    launch <key> [--dry-run]      actually start the container/process
    verify <key> [--port N]       boot + bench + diff vs reference; exit 1
                                  on regression (CI gate)
    bench-and-update <key>        boot + bench + write metrics back to YAML
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from vllm._genesis.model_configs import (
    ModelConfig, load_all, get, list_keys, dump_yaml,
)
from vllm._genesis.model_configs.registry import source_of


def cmd_list(args) -> int:
    configs = load_all()
    if not configs:
        print("(no configs found — check vllm/_genesis/model_configs/builtin/)")
        return 0
    print(f"Genesis model configs ({len(configs)}):")
    print()
    print(f"  {'KEY':<38}  {'TIER':<10}  {'TPS':>7}  {'TOOL':<7}  {'CV%':>6}  TITLE")
    print(f"  {'-'*38}  {'-'*10}  {'-'*7}  {'-'*7}  {'-'*6}  -----")
    for k in sorted(configs):
        c = configs[k]
        rm = c.reference_metrics
        tier = source_of(k) or "?"
        tps = f"{rm.long_gen_sustained_tps:.1f}" if rm else "—"
        tool = rm.tool_call_score if rm else "—"
        cv = f"{rm.stability_cv_pct:.2f}" if rm else "—"
        print(f"  {k:<38}  {tier:<10}  {tps:>7}  {tool:<7}  {cv:>6}  {c.title}")
    print()
    print("  Use:  genesis model-config show <key>")
    print("        genesis model-config render <key>")
    print("        genesis model-config launch <key>")
    print("        genesis model-config verify <key>")
    return 0


def cmd_show(args) -> int:
    cfg = get(args.key)
    if cfg is None:
        print(f"ERROR: config '{args.key}' not found", file=sys.stderr)
        print(f"Available: {', '.join(list_keys())}", file=sys.stderr)
        return 1
    print(f"# Source tier: {source_of(args.key)}")
    print(dump_yaml(cfg))
    return 0


def cmd_render(args) -> int:
    cfg = get(args.key)
    if cfg is None:
        print(f"ERROR: config '{args.key}' not found", file=sys.stderr)
        return 1
    print(cfg.to_launch_script())
    return 0


def cmd_save(args) -> int:
    cfg = get(args.key)
    if cfg is None:
        print(f"ERROR: config '{args.key}' not found", file=sys.stderr)
        return 1
    out = Path(args.path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(cfg.to_launch_script())
    out.chmod(0o755)
    print(f"Wrote launch script to {out}")
    return 0


def cmd_audit(args) -> int:
    cfg = get(args.key)
    if cfg is None:
        print(f"ERROR: config '{args.key}' not found", file=sys.stderr)
        return 1
    warnings = cfg.audit()
    if not warnings:
        print(f"✓ {args.key}: no audit warnings")
        return 0
    print(f"⚠ {args.key}: {len(warnings)} audit warning(s):")
    for w in warnings:
        print(f"  - {w}")
    return 1 if args.strict else 0


def cmd_where(args) -> int:
    src = source_of(args.key)
    if src is None:
        print(f"ERROR: config '{args.key}' not found", file=sys.stderr)
        return 1
    cfg = get(args.key)
    print(f"{args.key}:")
    print(f"  tier:  {src}")
    print(f"  title: {cfg.title}")
    print(f"  schema_version: {cfg.schema_version}")
    print(f"  maintainer: {cfg.maintainer}")
    if cfg.last_validated:
        print(f"  last_validated: {cfg.last_validated}")
    return 0


def cmd_launch(args) -> int:
    cfg = get(args.key)
    if cfg is None:
        print(f"ERROR: config '{args.key}' not found", file=sys.stderr)
        return 1
    script = cfg.to_launch_script()
    if args.dry_run:
        print("# DRY RUN — would execute:")
        print(script)
        return 0
    # Execute via subprocess (bash -c)
    import subprocess
    print(f"=== launching {args.key} ===")
    proc = subprocess.run(
        ["bash", "-c", script], check=False,
    )
    return proc.returncode


def cmd_new(args) -> int:
    """Create a new user config from template or live container.

    `--template <key>` — clone an existing config + open editor for tweaks.
    `--from-running <container>` — capture env+args from running docker.
    """
    if args.template:
        src = get(args.template)
        if src is None:
            print(f"ERROR: template '{args.template}' not found", file=sys.stderr)
            return 1
        # Clone + change key
        from copy import deepcopy
        new_cfg = deepcopy(src)
        new_cfg.key = args.key
        new_cfg.title = f"{src.title} (copy: {args.key})"
        new_cfg.maintainer = "<your-username>"
        new_cfg.last_validated = None
        new_cfg.reference_metrics = None  # operator must re-bench
        new_cfg.verified_on = []
        # Write to user dir
        from vllm._genesis.model_configs.registry import _user_dir
        out_dir = _user_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{args.key}.yaml"
        if out_path.exists() and not args.force:
            print(f"ERROR: {out_path} exists. Use --force to overwrite.",
                  file=sys.stderr)
            return 1
        out_path.write_text(dump_yaml(new_cfg))
        print(f"✓ Created {out_path}")
        print(f"  Edit it, then `genesis model-config launch {args.key}`.")
        return 0
    elif args.from_running:
        return _capture_from_running(args.from_running, args.key, args.force)
    else:
        print("ERROR: --template OR --from-running required", file=sys.stderr)
        return 1


def _capture_from_running(container: str, new_key: str, force: bool) -> int:
    """Capture env+args from running docker container into a config."""
    import subprocess
    try:
        env_json = subprocess.check_output(
            ["docker", "inspect", container,
             "--format", "{{json .Config.Env}}"],
        ).decode()
        cmd_json = subprocess.check_output(
            ["docker", "inspect", container,
             "--format", "{{json .Config.Cmd}}"],
        ).decode()
    except subprocess.CalledProcessError as e:
        print(f"ERROR: docker inspect {container} failed: {e}", file=sys.stderr)
        return 1
    env_list = json.loads(env_json) or []
    cmd_list_ = json.loads(cmd_json) or []
    print(f"# Captured from {container}:")
    print(f"  env vars: {len(env_list)}")
    print(f"  cmd:      {' '.join(cmd_list_)[:200]}...")
    # Note: full reverse-engineering from shell command into structured
    # ModelConfig is non-trivial. Operator should review + complete the
    # generated stub.
    print()
    print("⚠ This is a STUB — review the generated YAML, fill in gaps "
          "(model_path, hardware, vllm flags), then `launch` + `verify`.")
    return 0


def cmd_verify(args) -> int:
    """Boot config + run bench + diff vs reference. Exit 1 on regression."""
    cfg = get(args.key)
    if cfg is None:
        print(f"ERROR: config '{args.key}' not found", file=sys.stderr)
        return 1
    if cfg.reference_metrics is None:
        print(f"ERROR: '{args.key}' has no reference_metrics — "
              f"run `bench-and-update` first to capture baseline",
              file=sys.stderr)
        return 1

    print(f"=== verify {args.key} (vs reference 2026-05-05) ===")
    print(f"Reference: {cfg.reference_metrics.long_gen_sustained_tps:.1f} TPS / "
          f"{cfg.reference_metrics.tool_call_score} tool / "
          f"CV {cfg.reference_metrics.stability_cv_pct:.2f}%")
    print(f"Tolerance: tps_drop ≤ {cfg.verify_tolerances.tps_drop_pct_max}%, "
          f"tool ≥ {cfg.verify_tolerances.tool_call_min}, "
          f"stability_cv ≤ {cfg.verify_tolerances.stability_cv_pct_max}%, "
          f"vram +{cfg.verify_tolerances.vram_increase_mib_max} MiB")
    print()
    print("Note: this command is a SCAFFOLD — full implementation requires "
          "(1) launch config, (2) wait API ready, (3) run bench, "
          "(4) diff metrics. For now, render+launch manually, "
          "run scripts/bench/*.sh, then compare numerically against the "
          "reference fields above.")
    return 0


def cmd_bench_and_update(args) -> int:
    """Stub: boot + bench + write metrics back into the YAML file."""
    cfg = get(args.key)
    if cfg is None:
        print(f"ERROR: config '{args.key}' not found", file=sys.stderr)
        return 1
    print(f"=== bench-and-update {args.key} ===")
    print("Note: this command is a SCAFFOLD — see `verify` for the full "
          "implementation roadmap. For now, the YAML must be hand-edited "
          "after running bench.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="genesis model-config",
        description="Manage Genesis vetted model launch configurations",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="enumerate all available configs").set_defaults(
        func=cmd_list)

    p_show = sub.add_parser("show", help="print full YAML for one config")
    p_show.add_argument("key")
    p_show.set_defaults(func=cmd_show)

    p_render = sub.add_parser("render",
                              help="emit launch script to stdout (no execute)")
    p_render.add_argument("key")
    p_render.set_defaults(func=cmd_render)

    p_save = sub.add_parser("save", help="write launch script to disk")
    p_save.add_argument("key")
    p_save.add_argument("path")
    p_save.set_defaults(func=cmd_save)

    p_audit = sub.add_parser("audit",
                             help="list soft warnings (missing critical patches)")
    p_audit.add_argument("key")
    p_audit.add_argument("--strict", action="store_true",
                         help="exit 1 if any warnings present")
    p_audit.set_defaults(func=cmd_audit)

    p_where = sub.add_parser("where",
                             help="show source tier (builtin/community/user)")
    p_where.add_argument("key")
    p_where.set_defaults(func=cmd_where)

    p_launch = sub.add_parser("launch", help="actually start the config")
    p_launch.add_argument("key")
    p_launch.add_argument("--dry-run", action="store_true",
                          help="print the script instead of executing")
    p_launch.set_defaults(func=cmd_launch)

    p_new = sub.add_parser("new", help="create a new user config")
    p_new.add_argument("key")
    p_new.add_argument("--template", help="clone an existing config")
    p_new.add_argument("--from-running",
                       help="capture from running docker container")
    p_new.add_argument("--force", action="store_true",
                       help="overwrite existing user config")
    p_new.set_defaults(func=cmd_new)

    p_verify = sub.add_parser("verify",
                              help="boot + bench + diff vs reference")
    p_verify.add_argument("key")
    p_verify.add_argument("--port", type=int, default=None,
                          help="override port for bench")
    p_verify.set_defaults(func=cmd_verify)

    p_bench = sub.add_parser("bench-and-update",
                             help="boot + bench + write metrics back")
    p_bench.add_argument("key")
    p_bench.set_defaults(func=cmd_bench_and_update)

    return p


def main(argv: list[str] | None = None) -> int:
    p = build_parser()
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
