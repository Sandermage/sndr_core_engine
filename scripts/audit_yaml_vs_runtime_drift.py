#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""audit_yaml_vs_runtime_drift.py — Python port of
``tools/audit_yaml_vs_runtime.sh`` (TOOLING-HARDENING.2 L.8, 2026-05-26).

Compares the ``genesis_env:`` block of a builtin model_config YAML
against the actual environment variables of a running vLLM container.
Reports drift between intended (YAML) and actual (live) state.

Background: drift between YAML configs and start-scripts is a recurring
regression source on Genesis (audit 2026-05-11 Wave 8 found 11 drift
sources in one session; PN90 missing from start-script alone cost
−7% TPS until fixed). This audit catches drift before it causes silent
performance loss.

The shell sibling remains the canonical bash entry point (wired as
``make audit-yaml``); this Python port adds:

  * pure-function audit core (``audit(...)``) — testable without docker
  * ``--from-env-file <path>`` test hook — substitute synthetic env input
  * ``--json`` machine-readable output
  * identical CLI positional contract: ``yaml_path container [ssh_host]``
  * identical exit codes: 0 / 1 / 2

Drift classifications:

  * ``ok_disable``      — YAML sets ``KEY: '0'`` and KEY absent from
                          live env. Explicit disable; no drift.
  * ``drift``           — YAML enables KEY but live env lacks it.
  * ``intentional_pn95`` — live env has GENESIS_PN95_* / GENESIS_ENABLE_PN95_*
                          extras (carried by ``start_pn95_*.sh`` experiment
                          scripts on top of canonical YAML). No drift.
  * ``extra``           — live env has GENESIS_* key not in YAML and not
                          matching the PN95 experiment prefix. Drift.

Exit codes:
  0 — no real drift (only ``ok_disable`` / ``intentional_pn95``)
  1 — real drift found
  2 — usage error, YAML missing, or live env unobtainable

Usage::

  python3 scripts/audit_yaml_vs_runtime_drift.py <yaml> <container> [<ssh_host>]
  python3 scripts/audit_yaml_vs_runtime_drift.py <yaml> <container> --json
  python3 scripts/audit_yaml_vs_runtime_drift.py <yaml> CONTAINER \\
      --from-env-file /tmp/live_env.txt   # test hook (skips docker)
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional


# YAML line matcher — mirrors shell ``grep -E "^\s+GENESIS_"`` (any indent,
# anywhere in the file; the sibling shell does NOT scope to ``genesis_env:``).
_YAML_LINE_RE = re.compile(
    r"^\s+(GENESIS_[A-Z0-9_]+):\s*(.*)$",
    re.MULTILINE,
)

# Live-env KEY=VALUE matcher — docker inspect emits one env per line.
_LIVE_LINE_RE = re.compile(
    r"^(GENESIS_[A-Z0-9_]+)=(.*)$",
)

# Intentional extras carried by experiment launch scripts. Preserved
# byte-for-byte from the shell sibling (line 115).
_INTENTIONAL_EXTRA_RE = re.compile(
    r"^(GENESIS_PN95_|GENESIS_ENABLE_PN95_)"
)


@dataclasses.dataclass
class Finding:
    key: str
    yaml_value: Optional[str]
    classification: str   # ok_disable | drift | intentional_pn95 | extra
    note: str

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def _strip_value(raw: str) -> str:
    """Trim inline comment + surrounding quotes/whitespace. Mirrors the
    shell ``sed`` pipeline in lines 92/101 of the sibling."""
    # Inline comment — same heuristic as shell (split on ``  #`` or `` #``).
    if " #" in raw:
        raw = raw.split(" #", 1)[0]
    return raw.strip().strip("'").strip('"')


def parse_yaml_genesis_keys(text: str) -> dict[str, str]:
    """Return ``{KEY: value}`` for every indented ``GENESIS_*: …`` line.

    Picks up GENESIS_* keys at *any* indent level — matches the shell
    sibling's ``grep -E "^\\s+GENESIS_"`` pattern, which does not scope
    to the ``genesis_env:`` block specifically.
    """
    out: dict[str, str] = {}
    for m in _YAML_LINE_RE.finditer(text):
        key = m.group(1)
        out[key] = _strip_value(m.group(2))
    return out


def parse_live_env(text: str) -> dict[str, str]:
    """Parse docker inspect output (one ``KEY=VALUE`` per line)."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = _LIVE_LINE_RE.match(line.strip())
        if m:
            out[m.group(1)] = m.group(2)
    return out


def audit(
    yaml_keys: dict[str, str],
    live_keys: dict[str, str],
) -> tuple[list[Finding], int]:
    """Pure-function audit core.

    Returns ``(findings, exit_code)`` where ``exit_code`` is 0 if every
    delta is ``ok_disable`` or ``intentional_pn95``, else 1. Findings
    are sorted by classification then key for deterministic output.
    """
    findings: list[Finding] = []
    real_drift = False

    yaml_set = set(yaml_keys)
    live_set = set(live_keys)

    # YAML keys NOT in live env
    for key in sorted(yaml_set - live_set):
        val = yaml_keys[key]
        if val == "0":
            findings.append(Finding(
                key=key,
                yaml_value=val,
                classification="ok_disable",
                note="explicit disable in YAML, default-off in env",
            ))
        else:
            findings.append(Finding(
                key=key,
                yaml_value=val,
                classification="drift",
                note="YAML enables but container doesn't have",
            ))
            real_drift = True

    # Live env keys NOT in YAML
    for key in sorted(live_set - yaml_set):
        if _INTENTIONAL_EXTRA_RE.match(key):
            findings.append(Finding(
                key=key,
                yaml_value=None,
                classification="intentional_pn95",
                note="PN95 experiment additions (see start_pn95_*.sh)",
            ))
        else:
            findings.append(Finding(
                key=key,
                yaml_value=None,
                classification="extra",
                note="container has env not specified in YAML",
            ))
            real_drift = True

    return findings, (1 if real_drift else 0)


def fetch_live_env(container: str, ssh_host: Optional[str] = None) -> str:
    """Run ``docker inspect`` (locally or via SSH) and return raw env block.

    Mirrors the sibling shell's docker invocation. Raises ``RuntimeError``
    on non-zero exit or empty output. The caller decides whether to surface
    that as exit code 2 or to retry.
    """
    docker_cmd = [
        "docker", "inspect", container,
        "--format", "{{range .Config.Env}}{{println .}}{{end}}",
    ]
    if ssh_host:
        # Mirror the shell ``ssh "$SSH_HOST" "docker inspect …"`` form —
        # concatenate the docker args as a single remote shell string.
        cmd = ["ssh", ssh_host, " ".join(docker_cmd)]
    else:
        cmd = docker_cmd

    result = subprocess.run(
        cmd, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"docker inspect failed (rc={result.returncode}): "
            f"{result.stderr.strip()}"
        )
    if not result.stdout.strip():
        raise RuntimeError(
            f"docker inspect returned empty env for container "
            f"{container!r}; is it running?"
        )
    return result.stdout


def render_text(
    yaml_path: Path,
    container: str,
    ssh_host: Optional[str],
    yaml_keys: dict[str, str],
    live_keys: dict[str, str],
    findings: list[Finding],
) -> str:
    """Human-readable banner + sections — mirrors the shell sibling layout."""
    lines: list[str] = []
    lines.append("═" * 71)
    lines.append(" YAML vs Runtime Drift Audit")
    lines.append(f"  YAML:      {yaml_path} ({len(yaml_keys)} keys)")
    suffix = f" via {ssh_host}" if ssh_host else ""
    lines.append(f"  Container: {container} ({len(live_keys)} keys){suffix}")
    lines.append("═" * 71)
    lines.append("")

    yaml_only = [f for f in findings if f.yaml_value is not None]
    live_only = [f for f in findings if f.yaml_value is None]

    lines.append("─── YAML keys NOT in live env ───")
    if not yaml_only:
        lines.append("  (none)")
    else:
        for f in yaml_only:
            if f.classification == "ok_disable":
                lines.append(
                    f"  {f.key}  [OK — explicit disable in YAML, "
                    "default-off in env]"
                )
            else:
                lines.append(
                    f"  {f.key} = {f.yaml_value}  "
                    "⚠ DRIFT: YAML enables but container doesn't have"
                )
    lines.append("")

    lines.append("─── Live env keys NOT in YAML ───")
    if not live_only:
        lines.append("  (none)")
    else:
        for f in live_only:
            if f.classification == "intentional_pn95":
                lines.append(
                    f"  {f.key}  [INTENTIONAL — PN95 experiment "
                    "additions, see start_pn95_*.sh]"
                )
            else:
                lines.append(
                    f"  {f.key}  ⚠ EXTRA: container has env not "
                    "specified in YAML"
                )
    lines.append("")

    real_drift = any(
        f.classification in ("drift", "extra") for f in findings
    )
    lines.append("─── Summary ───")
    if not real_drift:
        lines.append("  ✓ No real drift detected. YAML and live env are aligned.")
    else:
        lines.append("  ✗ Real drift detected. See above for details.")
        lines.append(
            "  Action: update start-script to match YAML genesis_env, "
            "restart container, re-audit."
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("yaml_path", help="Path to V1 builtin model_config YAML")
    ap.add_argument("container", help="Container name to inspect")
    ap.add_argument(
        "ssh_host", nargs="?", default=None,
        help="Optional SSH host for remote docker inspect",
    )
    ap.add_argument(
        "--from-env-file", default=None, dest="env_file",
        help="(test hook) read live env from file instead of docker inspect",
    )
    ap.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON instead of human-readable output",
    )
    args = ap.parse_args()

    yaml_path = Path(args.yaml_path)
    if not yaml_path.is_file():
        print(f"ERROR: YAML file not found: {yaml_path}", file=sys.stderr)
        return 2

    yaml_text = yaml_path.read_text(encoding="utf-8")
    yaml_keys = parse_yaml_genesis_keys(yaml_text)

    if args.env_file:
        env_path = Path(args.env_file)
        if not env_path.is_file():
            print(f"ERROR: --from-env-file path not found: {env_path}",
                  file=sys.stderr)
            return 2
        env_text = env_path.read_text(encoding="utf-8")
    else:
        try:
            env_text = fetch_live_env(args.container, args.ssh_host)
        except (RuntimeError, FileNotFoundError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2

    live_keys = parse_live_env(env_text)
    if not live_keys:
        print(
            f"ERROR: no GENESIS_* env vars in container "
            f"{args.container} env output",
            file=sys.stderr,
        )
        return 2

    findings, exit_code = audit(yaml_keys, live_keys)

    if args.json:
        print(json.dumps({
            "yaml_path": str(yaml_path),
            "container": args.container,
            "ssh_host": args.ssh_host,
            "yaml_count": len(yaml_keys),
            "live_count": len(live_keys),
            "findings": [f.as_dict() for f in findings],
            "real_drift": bool(exit_code),
        }, indent=2, sort_keys=True))
    else:
        print(render_text(
            yaml_path, args.container, args.ssh_host,
            yaml_keys, live_keys, findings,
        ))

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
