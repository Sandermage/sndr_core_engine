#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Audit for stale `vllm_version_range` upper bounds in PATCH_REGISTRY.

CLAUDE.md Class 5 known-bug surface: "Anchor drift after vllm pin bump."
This audit catches a softer variant — patches whose `applies_to.vllm_version_range`
upper bound EXCLUDES the current operational pin, causing:

  - `applies_to` constraint check fails on every boot
  - When env_flag is set (opt-in), the patch still applies but logs a
    WARNING about the mismatch — spurious noise in production boot logs
  - When env_flag is unset (default_on path), the patch silently skips
    via the strict-opt-in guard (which fires first), so the version
    range never gets checked — but the range field is still wrong

Behaviour
---------

The audit examines every PATCH_REGISTRY entry's
`applies_to.vllm_version_range` and reports cases where the upper
bound looks stale (would exclude the current operational pin).

Operational pin: read from `vllm.__version__` when available; else from
the `--pin` flag; else assumes `0.21.1rc1+` (current as of v11.3.0).

Severity classification:

  CRITICAL — patch is `default_on=True` + version range excludes current
             pin. Patch silently skips for every operator without
             opt-in override. (As of v11.3.0 audit: 0 entries.)

  WARN     — patch is opt-in (default_on=False) but enabled by some
             prod-* preset. Operator gets spurious WARN noise on boot.

  INFO     — patch is opt-in and not enabled by any preset. Only shows
             up if operator explicitly enables.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
Status: v11.3.0+ audit (CLAUDE.md Class 5 surface).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


# Default current-pin assumption when vllm not importable.
# Update on each pin bump (or pull dynamically when vllm is installed).
DEFAULT_PIN = "0.21.1rc1.dev354+g626fa9bba"


def _resolve_current_pin(override: str | None = None) -> str:
    if override:
        return override
    try:
        import vllm
        ver = getattr(vllm, "__version__", None)
        if ver:
            return ver
    except Exception:
        pass
    return DEFAULT_PIN


def _parse_pep440(spec: str) -> tuple[str | None, str | None]:
    """Best-effort parse of a single PEP 440 specifier like `<0.21.0`
    or `>=0.20.2rc1.dev9`. Returns (operator, version) or (None, None)
    on parse fail."""
    spec = spec.strip()
    m = re.match(r"^(>=|<=|>|<|==|!=|~=)\s*(\S+)$", spec)
    if not m:
        return None, None
    return m.group(1), m.group(2)


def _ver_key(v: str) -> tuple:
    """Loose version-key for ordering. Handles common shapes like
    `0.21.1rc1.dev354+g626fa9bba`. Tokenises on `.`, `+`, `-` and
    converts ints where possible."""
    # Strip local-version suffix (everything after +)
    bare = v.split("+", 1)[0]
    parts = re.split(r"[.\-]", bare)
    key = []
    for p in parts:
        # Split off trailing alpha (e.g. "1rc1" → 1, "rc1")
        m = re.match(r"^(\d+)(.*)$", p)
        if m:
            key.append(int(m.group(1)))
            if m.group(2):
                key.append(m.group(2))
        else:
            key.append(p)
    return tuple(key)


def _excludes_pin(constraint: str, pin: str) -> bool:
    """Does this single PEP 440 specifier EXCLUDE the current pin?

    Returns True iff the constraint is well-formed AND it deterministically
    rejects pin. Conservative: returns False on parse fail.
    """
    op, ver = _parse_pep440(constraint)
    if op is None:
        return False
    try:
        pin_k = _ver_key(pin)
        ver_k = _ver_key(ver)
    except Exception:
        return False
    if op == "<":
        return pin_k >= ver_k
    if op == "<=":
        return pin_k > ver_k
    if op == ">":
        return pin_k <= ver_k
    if op == ">=":
        return pin_k < ver_k
    if op == "==":
        return pin_k != ver_k
    return False


def _check_range_excludes_pin(rng, pin: str) -> bool:
    """Given a vllm_version_range (tuple, list, or string), does it
    exclude the current pin?"""
    if isinstance(rng, str):
        # Comma-separated specifier string
        parts = [p.strip() for p in rng.split(",")]
        return any(_excludes_pin(p, pin) for p in parts if p)
    if isinstance(rng, (tuple, list)):
        return any(_excludes_pin(p, pin) for p in rng if isinstance(p, str))
    return False


def _import_registry():
    sys.path.insert(0, str(REPO_ROOT))
    from vllm.sndr_core.dispatcher.registry import PATCH_REGISTRY
    return PATCH_REGISTRY


def _audit(pin: str) -> dict:
    registry = _import_registry()
    rows: list[dict] = []
    for pid, meta in registry.items():
        if not isinstance(meta, dict):
            continue
        lifecycle = meta.get("lifecycle", "")
        if lifecycle in ("retired", "deprecated", "legacy"):
            continue
        applies_to = meta.get("applies_to") or {}
        if not isinstance(applies_to, dict):
            continue
        rng = applies_to.get("vllm_version_range")
        if not rng:
            continue
        if not _check_range_excludes_pin(rng, pin):
            continue
        # Severity classification
        default_on = bool(meta.get("default_on"))
        severity = "CRITICAL" if default_on else "WARN"
        rows.append({
            "patch_id": pid,
            "severity": severity,
            "vllm_version_range": rng,
            "lifecycle": lifecycle,
            "default_on": default_on,
            "env_flag": meta.get("env_flag"),
            "family": meta.get("family"),
        })
    # Sort by severity (CRITICAL first) then patch_id
    rows.sort(key=lambda r: (0 if r["severity"] == "CRITICAL" else 1,
                              r["patch_id"]))
    return {
        "pin": pin,
        "total_stale_ranges": len(rows),
        "critical_count": sum(1 for r in rows if r["severity"] == "CRITICAL"),
        "warn_count": sum(1 for r in rows if r["severity"] == "WARN"),
        "rows": rows,
    }


def _print_human(result: dict) -> None:
    print("=" * 70)
    print(f"Stale vllm_version_range audit — pin = {result['pin']}")
    print("=" * 70)
    print()
    print(f"Total stale ranges:    {result['total_stale_ranges']}")
    print(f"  CRITICAL (default_on, silent skip): {result['critical_count']}")
    print(f"  WARN     (opt-in, WARN log noise):  {result['warn_count']}")
    print()
    if result["critical_count"] > 0:
        print(
            "⚠⚠⚠ CRITICAL entries — default_on=True + range excludes "
            "current pin → patch silently skips for every operator. "
            "Investigate immediately."
        )
        print()
    if result["rows"]:
        print(f"{'Severity':<10} {'Patch':<25} {'Range':<35} {'env_flag':<40}")
        print("-" * 110)
        for r in result["rows"]:
            range_str = str(r["vllm_version_range"])
            if len(range_str) > 34:
                range_str = range_str[:31] + "..."
            print(
                f"{r['severity']:<10} {r['patch_id']:<25} {range_str:<35} "
                f"{r.get('env_flag') or '':<40}"
            )
        print()
    if result["total_stale_ranges"] == 0:
        print(
            "✓ No stale version ranges. All active patches' ranges "
            "include the current pin."
        )
    else:
        print(
            f"Recommendation: bulk-update the {result['total_stale_ranges']} "
            "stale ranges to reflect the current support window. Common "
            "fix: bump upper bound from `<0.21.0` to `<0.22.0` if the "
            "patch is verified working on 0.21.x."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--pin", help="override current pin (defaults to vllm.__version__)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="emit machine-readable JSON",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="exit 1 if any CRITICAL entries found",
    )
    args = parser.parse_args()

    pin = _resolve_current_pin(args.pin)
    result = _audit(pin)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_human(result)

    if args.strict and result["critical_count"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
