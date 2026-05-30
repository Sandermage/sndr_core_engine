# SPDX-License-Identifier: Apache-2.0
"""§6.H6 (UNIFIED_DEVELOPMENT_PLAN) — `sndr trace list` subcommand.

Foundational verb for the plan's §6.H trace surface:

  * H6 ``sndr trace list`` — this commit. List known traces, optionally
    pull live size/mtime from a running container.
  * H7 ``sndr trace collect --container <name>`` — copy a trace out.
  * H8 ``sndr trace summarize <log-file>`` — quick stat analysis.
  * H9 ``sndr support-bundle`` — bundle all enabled traces.

H6 surfaces the operator-facing question "what diagnostic traces exist
and which are currently being written?" via the catalog at
``vllm.sndr_core.observability.trace_catalog``. ``--container <name>``
runs ``docker exec ls -l`` against the container's ``/tmp/`` and joins
the result with the catalog so the output shows which traces are
actually present and how big they are.

Output modes:

  Default (human view) — categories with a one-line summary per trace
  + per-line annotation when ``--container`` is used.

  ``--json`` — machine-readable; the same structure suitable for the
  H9 support-bundle aggregator.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from dataclasses import asdict
from typing import Any, Optional

from . import _io


__all__ = ["add_argparser", "run_list"]


def add_argparser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "trace",
        help=(
            "Genesis diagnostic-trace catalog (§6.H6) — list known "
            "trace files, optionally introspect a live container."
        ),
        description=(
            "Inspect Genesis's known diagnostic traces. By default "
            "prints the static catalog (every trace emitted by some "
            "patch). With --container, runs `docker exec ls -l` "
            "against the named container's /tmp/ and annotates each "
            "catalog entry with its live size + mtime."
        ),
    )
    sub = p.add_subparsers(dest="trace_cmd", required=True)

    p_list = sub.add_parser(
        "list",
        help="List every known trace + (with --container) live state.",
    )
    p_list.add_argument(
        "--container", default=None,
        help=(
            "Name of a running vLLM container; introspect its /tmp/ "
            "via `docker exec` and annotate each entry with the live "
            "file size + mtime. Requires docker on $PATH."
        ),
    )
    p_list.add_argument(
        "--category", default=None,
        help=(
            "Filter to a single category. Valid: " +
            "/".join(_categories())
        ),
    )
    p_list.add_argument(
        "--json", action="store_true",
        help="Machine-readable JSON instead of the human view.",
    )
    p_list.add_argument(
        "--all", action="store_true",
        help=(
            "With --container: list catalog entries even when the "
            "live file is absent. Default: hide absent files so the "
            "operator only sees what's actually being written."
        ),
    )
    p_list.set_defaults(func=run_list)


# ─── Helpers ──────────────────────────────────────────────────────────


def _categories() -> tuple[str, ...]:
    from vllm.sndr_core.observability.trace_catalog import TRACE_CATEGORIES
    return TRACE_CATEGORIES


def _container_ls_tmp(container: str) -> dict[str, tuple[int, str]]:
    """Run ``docker exec <container> ls -la /tmp/`` and parse the
    matching genesis_* lines into ``{basename: (size_bytes, mtime_str)}``.

    Returns an empty dict on any failure — never raises. Detection
    failure is surfaced via a one-line warning in the CLI, not via
    an exception (the verb must still print the static catalog).
    """
    if not shutil.which("docker"):
        return {}
    try:
        r = subprocess.run(
            ["docker", "exec", container, "ls", "-la", "--time-style=full-iso", "/tmp"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if r.returncode != 0:
        return {}
    out: dict[str, tuple[int, str]] = {}
    # Typical row:
    #   -rw-r--r-- 1 root root  12345  2026-05-30 13:00:00.000000000 +0000 genesis_pn248_acceptance_trace.log
    # ls -la output also includes . / .. / non-matching files; we only
    # care about genesis_* files in /tmp/ root.
    row_re = re.compile(
        r"^\S+\s+\d+\s+\S+\s+\S+\s+(\d+)\s+"
        r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[^\s]*\s+\S+)\s+"
        r"(genesis_\S+)\s*$"
    )
    for line in r.stdout.splitlines():
        m = row_re.match(line.strip())
        if m is None:
            continue
        size, mtime, name = m.group(1), m.group(2), m.group(3)
        out[name] = (int(size), mtime)
    return out


def _spec_to_dict(spec, live: Optional[tuple[int, str]]) -> dict:
    d = asdict(spec)
    if live is None:
        d["live"] = None
    else:
        size, mtime = live
        d["live"] = {"size_bytes": size, "mtime": mtime}
    return d


def _fmt_size(n: int) -> str:
    """Human-friendly size — 1024-based, single decimal for >1KB."""
    if n < 1024:
        return f"{n}B"
    for unit in ("KB", "MB", "GB"):
        n_f = n / 1024.0
        if n_f < 1024 or unit == "GB":
            return f"{n_f:.1f}{unit}"
        n //= 1024
    return f"{n}B"  # unreachable


# ─── Runner ───────────────────────────────────────────────────────────


def run_list(args: argparse.Namespace) -> int:
    from vllm.sndr_core.observability.trace_catalog import (
        TRACE_CATALOG, TRACE_CATEGORIES, iter_by_category,
    )

    if args.category and args.category not in TRACE_CATEGORIES:
        _io.error(
            f"unknown category {args.category!r}. "
            f"Valid: {', '.join(TRACE_CATEGORIES)}"
        )
        return 2

    live_state: dict[str, tuple[int, str]] = {}
    container_warning: Optional[str] = None
    if args.container:
        live_state = _container_ls_tmp(args.container)
        if not live_state and not shutil.which("docker"):
            container_warning = (
                "docker binary not on $PATH — --container ignored, "
                "showing static catalog only."
            )
        elif not live_state:
            container_warning = (
                f"docker exec {args.container} ls /tmp returned no "
                "genesis_* files. Either the container is stopped, the "
                "name is wrong, or no trace flag is enabled."
            )

    grouped = iter_by_category()

    # Filter by --category if requested.
    if args.category:
        grouped = {args.category: grouped[args.category]}

    # When --container is set and --all is NOT, drop catalog entries
    # whose live file is absent (operator wants to see "what's being
    # written right now", not "what could be written").
    if args.container and not args.all:
        new_grouped: dict[str, tuple] = {}
        for cat, specs in grouped.items():
            kept = tuple(
                s for s in specs
                if s.container_path.split("/")[-1] in live_state
            )
            if kept:
                new_grouped[cat] = kept
        grouped = new_grouped

    # ── JSON output ──────────────────────────────────────────────────
    if args.json:
        out_specs = []
        for cat in TRACE_CATEGORIES:
            for s in grouped.get(cat, ()):
                live = live_state.get(s.container_path.split("/")[-1])
                out_specs.append(_spec_to_dict(s, live))
        out_payload = {
            "container": args.container,
            "container_warning": container_warning,
            "category_filter": args.category,
            "all": bool(args.all),
            "total": len(out_specs),
            "traces": out_specs,
        }
        print(json.dumps(out_payload, indent=2, sort_keys=False))
        return 0

    # ── Human view ──────────────────────────────────────────────────
    if container_warning:
        _io.warn(container_warning)

    total_listed = sum(len(v) for v in grouped.values())
    if total_listed == 0:
        if args.container and not args.all:
            print(
                f"No live genesis_* traces in {args.container}:/tmp/. "
                "Pass --all to see the full catalog."
            )
        else:
            print("(no traces match filter)")
        return 0

    print("sndr trace — known diagnostic traces"
          + (f" (container={args.container})" if args.container else ""))
    print("─" * 70)
    for cat in TRACE_CATEGORIES:
        specs = grouped.get(cat, ())
        if not specs:
            continue
        print(f"\n  {cat.upper()}")
        for s in specs:
            basename = s.container_path.split("/")[-1]
            live = live_state.get(basename)
            live_suffix = ""
            if args.container:
                if live is None:
                    live_suffix = "  (not present)"
                else:
                    size, mtime = live
                    live_suffix = f"  [{_fmt_size(size)}, {mtime}]"
            env_suffix = (
                f"  env={s.enable_env}" if s.enable_env else "  (always)"
            )
            print(f"    · {s.id:24s}{env_suffix}{live_suffix}")
            print(f"      patch={s.patch_id}")
            print(f"      path={s.container_path}")
            # Re-wrap description at 72 chars for readability.
            desc = s.description.strip()
            indent = "      "
            wrapped = []
            line = ""
            for word in desc.split():
                if len(line) + len(word) + 1 > 72 and line:
                    wrapped.append(line)
                    line = word
                else:
                    line = f"{line} {word}".strip()
            if line:
                wrapped.append(line)
            for w in wrapped:
                print(f"{indent}{w}")

    print()
    print(f"  Total: {total_listed} trace(s).")
    return 0
