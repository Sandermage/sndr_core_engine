#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Extract the IN-CONTAINER command from a `sndr launch --dry-run` render.

The dry-run render is a HOST `docker run` launcher: it boots the container
itself and passes the real work as the `-c 'payload'` argument to an in-image
`/bin/bash` entrypoint. Tooling that wants to run that payload under a DIFFERENT
image/mounts (the fleet boot-smoke gate does) must extract the payload, not run
the host script — running the whole render inside a container tries
docker-in-docker and dies with `docker: command not found`.

Reads the render on stdin, prints one TAB-separated line: `<inner_port>\t<payload>`.
Exits non-zero if no `docker run ... -c <payload>` is found.

`--env-out PATH`: ALSO write every `-e KEY=VAL` env var the render passes to the
container as a docker `--env-file`-compatible file at PATH (one KEY=VAL per line).
This is REQUIRED for a faithful boot: the render carries ~100 `-e GENESIS_ENABLE_*`
opt-in flags (P67/P67b/PN521/...); a boot that keeps the payload but drops the env
runs a stripped stack (opt-in patches SKIP), which silently mis-tests the pin. The
`-e` extraction is skipped from the stdout line for backward compatibility.
"""
from __future__ import annotations

import argparse
import shlex
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--env-out",
        help="write the render's `-e KEY=VAL` vars to this docker --env-file path",
    )
    args = ap.parse_args()

    text = sys.stdin.read()
    lines = text.splitlines()
    try:
        start = next(
            i for i, ln in enumerate(lines) if ln.strip().startswith("docker run")
        )
    except StopIteration:
        print("no 'docker run' in render", file=sys.stderr)
        return 2
    # Join the backslash-continued docker-run invocation into one command line.
    joined = " ".join(ln.rstrip().rstrip("\\") for ln in lines[start:])
    try:
        toks = shlex.split(joined)
    except ValueError as e:
        print(f"shlex parse failed: {e}", file=sys.stderr)
        return 2
    payload = None
    inner_port = "8000"
    env_pairs: list[str] = []
    for i, t in enumerate(toks):
        if t == "-c" and i + 1 < len(toks):
            payload = toks[i + 1]
        elif t in ("-p", "--publish") and i + 1 < len(toks):
            inner_port = toks[i + 1].split(":")[-1]
        elif t in ("-e", "--env") and i + 1 < len(toks) and "=" in toks[i + 1]:
            env_pairs.append(toks[i + 1])
    if not payload or "vllm serve" not in payload:
        print("no in-container '-c' payload with a vllm serve found", file=sys.stderr)
        return 2
    if args.env_out:
        # docker --env-file: one KEY=VAL per line, value is the raw rest of the
        # line (no shell quoting). shlex already stripped the render's quotes.
        with open(args.env_out, "w", encoding="utf-8") as f:
            f.write("\n".join(env_pairs) + ("\n" if env_pairs else ""))
        print(f"wrote {len(env_pairs)} env vars to {args.env_out}", file=sys.stderr)
    # Single logical line already (shlex collapsed it); guard against stray NLs.
    payload = payload.replace("\n", " ")
    sys.stdout.write(f"{inner_port}\t{payload}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
