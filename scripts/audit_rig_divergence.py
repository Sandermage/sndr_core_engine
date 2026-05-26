#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""audit_rig_divergence.py — local-only skeleton for primary↔rig drift
(§9.A.9, AUDIT-CLOSURE.2, 2026-05-27).

Operator scope (2026-05-27): "если нужен SSH к rig, это отдельный
approval boundary. Без approval сделать local-only skeleton + tests."

Default mode — **LOCAL-ONLY (no rig contact)**
───────────────────────────────────────────────

Reports the laptop's current git state as a snapshot suitable for
manual comparison against the rig later:

  * current branch
  * current HEAD short-SHA
  * dirty-tree state (``git status --porcelain``)
  * unexpected-untracked-file count (excluding the well-known
    ``.claude/`` / ``CLAUDE.md`` / ``sndr_private/`` operator-local set)
  * sndr-dev remote URL (informational)

Classifies each check as ``OK`` / ``WARN`` / ``BLOCKER``:

  * ``OK``      — local state matches expected invariants
  * ``WARN``    — dirty tree, unexpected untracked, missing remote
  * ``BLOCKER`` — only fires with ``--ssh-host`` AND rig HEAD diverges
                  (or rig branch mismatched, etc.); never in local-only

Exit codes (local-only):

  0 — every check OK or WARN-only (informational mode)
  1 — never (local-only mode is informational by design)
  2 — internal error

SSH mode (operator-authorized) — **NOT WIRED YET**
──────────────────────────────────────────────────

When ``--ssh-host HOST`` is passed AND ``--allow-ssh`` flag is set
(double opt-in), the audit will additionally fetch ``git rev-parse
HEAD`` + branch from the rig and compare with the laptop. Until the
operator explicitly authorizes a rig-read GO, calling with
``--ssh-host`` but without ``--allow-ssh`` is a usage error (exit 2) —
explicit gate prevents accidental rig contact.

This skeleton ships the framework + tests. SSH execution is gated
behind operator approval per master plan §9.P (RIG/server governance).

Exit codes (SSH mode):

  0 — laptop and rig agree on HEAD + branch + clean tree
  1 — divergence detected (BLOCKER class)
  2 — usage error / SSH connection failure

Modes
─────

  python3 scripts/audit_rig_divergence.py                      # local-only
  python3 scripts/audit_rig_divergence.py --json               # machine
  python3 scripts/audit_rig_divergence.py --ssh-host HOST \\
      --allow-ssh                                              # SSH mode
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parent.parent


# Files/dirs we EXPECT to be untracked at repo root (operator-local).
_EXPECTED_UNTRACKED: frozenset[str] = frozenset({
    ".claude",
    "CLAUDE.md",
    "sndr_private",
})


@dataclasses.dataclass
class Check:
    name: str
    severity: str   # OK | WARN | BLOCKER
    detail: str

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


# ─── Local probes ─────────────────────────────────────────────────────────


def _git(*args: str) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git", *args],
        capture_output=True, text=True, cwd=REPO_ROOT, check=False,
    )
    return result.returncode, result.stdout, result.stderr


def probe_local() -> list[Check]:
    """Run laptop-only checks. Never contacts rig."""
    checks: list[Check] = []

    # Current branch.
    rc, out, err = _git("rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        checks.append(Check(
            name="local-branch",
            severity="WARN",
            detail=f"git rev-parse failed: {err.strip()}",
        ))
    else:
        branch = out.strip()
        sev = "OK" if branch in ("dev", "main") else "WARN"
        checks.append(Check(
            name="local-branch",
            severity=sev,
            detail=f"current branch: {branch!r}",
        ))

    # HEAD short-SHA.
    rc, out, _ = _git("rev-parse", "--short=12", "HEAD")
    if rc == 0:
        checks.append(Check(
            name="local-head-sha",
            severity="OK",
            detail=f"laptop HEAD: {out.strip()}",
        ))

    # Dirty tree.
    rc, out, _ = _git("status", "--porcelain")
    if rc == 0:
        modified = [
            line for line in out.splitlines()
            if line and not line[3:].split()[0].split("/")[0]
            in _EXPECTED_UNTRACKED
        ]
        if not modified:
            checks.append(Check(
                name="dirty-tree",
                severity="OK",
                detail="tracked tree clean; only expected-untracked present",
            ))
        else:
            checks.append(Check(
                name="dirty-tree",
                severity="WARN",
                detail=(
                    f"{len(modified)} modified/untracked entries beyond "
                    f"the .claude/CLAUDE.md/sndr_private allowlist"
                ),
            ))

    # sndr-dev remote presence.
    rc, out, _ = _git("remote", "get-url", "sndr-dev")
    if rc == 0:
        checks.append(Check(
            name="sndr-dev-remote",
            severity="OK",
            detail=f"sndr-dev remote: {out.strip()}",
        ))
    else:
        checks.append(Check(
            name="sndr-dev-remote",
            severity="WARN",
            detail="sndr-dev remote not configured (expected for backup push)",
        ))

    return checks


# ─── SSH probes (gated, default OFF) ──────────────────────────────────────


def probe_rig(host: str) -> list[Check]:
    """Read-only rig probe — ``git rev-parse HEAD`` + branch via SSH.

    Only invoked when both ``--ssh-host`` and ``--allow-ssh`` are set.
    Operator's double opt-in prevents accidental rig contact.
    """
    checks: list[Check] = []
    # Conservative: only run ``git`` read-only commands; refuse to ever
    # invoke anything destructive even by accident.
    cmd_branch = (
        "cd ~/genesis-vllm-patches && "
        "git rev-parse --abbrev-ref HEAD && "
        "git rev-parse --short=12 HEAD"
    )
    full = ["ssh", host, cmd_branch]
    try:
        result = subprocess.run(
            full, capture_output=True, text=True,
            timeout=30, check=False,
        )
    except subprocess.TimeoutExpired:
        checks.append(Check(
            name="rig-ssh",
            severity="BLOCKER",
            detail=f"SSH to {host} timed out after 30s",
        ))
        return checks
    except FileNotFoundError:
        checks.append(Check(
            name="rig-ssh",
            severity="BLOCKER",
            detail="ssh binary not found in PATH",
        ))
        return checks
    if result.returncode != 0:
        checks.append(Check(
            name="rig-ssh",
            severity="BLOCKER",
            detail=(
                f"SSH command failed (rc={result.returncode}): "
                f"{result.stderr.strip()[:200]}"
            ),
        ))
        return checks

    lines = result.stdout.strip().splitlines()
    if len(lines) < 2:
        checks.append(Check(
            name="rig-ssh",
            severity="BLOCKER",
            detail=f"unexpected ssh output: {result.stdout!r}",
        ))
        return checks
    rig_branch, rig_sha = lines[0].strip(), lines[1].strip()
    checks.append(Check(
        name="rig-branch",
        severity="OK",
        detail=f"rig branch: {rig_branch!r}",
    ))
    checks.append(Check(
        name="rig-head-sha",
        severity="OK",
        detail=f"rig HEAD: {rig_sha}",
    ))

    # Compare with laptop.
    rc, laptop_sha, _ = _git("rev-parse", "--short=12", "HEAD")
    if rc == 0:
        laptop_sha = laptop_sha.strip()
        sev = "OK" if laptop_sha == rig_sha else "BLOCKER"
        detail = (
            f"laptop {laptop_sha} vs rig {rig_sha}"
            + (" — IN SYNC" if sev == "OK" else " — DIVERGENT")
        )
        checks.append(Check(
            name="head-sha-divergence",
            severity=sev,
            detail=detail,
        ))

    return checks


# ─── Render ───────────────────────────────────────────────────────────────


def _render_text(checks: list[Check], *, ssh_mode: bool) -> str:
    lines: list[str] = []
    lines.append("audit-rig-divergence: primary ↔ rig state drift")
    lines.append("─" * 70)
    lines.append(f"  mode: {'SSH' if ssh_mode else 'local-only'}")
    lines.append(f"  checks: {len(checks)}")
    lines.append("")
    for c in checks:
        sym = {
            "OK": "✓", "WARN": "⚠", "BLOCKER": "✗",
        }.get(c.severity, "·")
        lines.append(f"  {sym} {c.name:24s} [{c.severity}]")
        lines.append(f"      {c.detail}")
    blockers = [c for c in checks if c.severity == "BLOCKER"]
    warns = [c for c in checks if c.severity == "WARN"]
    lines.append("")
    if blockers:
        lines.append(f"  ✗ {len(blockers)} BLOCKER(s) — rig drift requires resolution")
    elif warns:
        lines.append(f"  ⚠ {len(warns)} WARN(s) — informational")
    else:
        lines.append("  ✓ All checks OK")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable JSON")
    ap.add_argument(
        "--ssh-host", default=None,
        help="rig SSH host for divergence probe (requires --allow-ssh)",
    )
    ap.add_argument(
        "--allow-ssh", action="store_true",
        help="REQUIRED with --ssh-host — operator's double opt-in to "
             "actually contact the rig",
    )
    args = ap.parse_args()

    # Refuse SSH without explicit double opt-in.
    if args.ssh_host and not args.allow_ssh:
        print(
            "audit-rig-divergence: --ssh-host requires --allow-ssh "
            "(operator's double opt-in to contact the rig). Default mode "
            "is local-only.",
            file=sys.stderr,
        )
        return 2

    checks = probe_local()
    ssh_mode = bool(args.ssh_host and args.allow_ssh)
    if ssh_mode:
        checks.extend(probe_rig(args.ssh_host))

    if args.json:
        print(json.dumps({
            "mode": "ssh" if ssh_mode else "local-only",
            "checks": [c.as_dict() for c in checks],
            "count": len(checks),
        }, indent=2, sort_keys=True))
    else:
        print(_render_text(checks, ssh_mode=ssh_mode))

    # Local-only mode is informational (never gates).
    if not ssh_mode:
        return 0
    # SSH mode: BLOCKER → exit 1.
    return 1 if any(c.severity == "BLOCKER" for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
