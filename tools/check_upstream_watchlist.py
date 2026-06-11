#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate the ``sweep:`` section of ``tools/upstream_watchlist.yaml``.

Added 2026-06-11 with the 50-PR upstream sweep (see
docs/superpowers/journal/2026-06-11-pr-sweep-50-roadmap.md). The
watchlist file carries TWO top-level sections:

  * ``watch:``  — legacy entries (upstream/status/action/since/notes),
                  validated by ``scripts/audit_upstream_watchlist.py``
                  (``make audit-upstream-watchlist``). Untouched here.
  * ``sweep:``  — one row per deep-studied upstream PR that needs
                  merge-event bookkeeping. Validated by THIS script
                  (``make watchlist-check``).

``sweep:`` row schema (all keys required):

  pr            int  — upstream vllm PR number
  genesis_patch str  — existing Genesis patch id(s) tied to the PR,
                       ``planned: <id>`` for a not-yet-vendored patch,
                       or ``watch-only`` when no code is involved
  trigger       str  — what to do when the PR merges into a pin:
                       retire-on-merge   (deep-diff, then retire vendor)
                       reanchor-on-merge (anchors break; re-derive)
                       review-on-merge   (re-read; no automatic action)
  note          str  — non-empty context (duplicates, clusters, plans)

Exit codes: 0 = clean, 2 = schema error or missing/unreadable file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WATCHLIST = REPO_ROOT / "tools" / "upstream_watchlist.yaml"

REQUIRED_KEYS = ("pr", "genesis_patch", "trigger", "note")
ALLOWED_TRIGGERS = frozenset({
    "retire-on-merge",
    "reanchor-on-merge",
    "review-on-merge",
})


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        print("ERROR: pyyaml not installed (`pip install pyyaml`)",
              file=sys.stderr)
        raise SystemExit(2)
    if not path.is_file():
        print(f"ERROR: watchlist not found at {path}", file=sys.stderr)
        raise SystemExit(2)
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_sweep(path: Path) -> list[dict[str, Any]]:
    """Return the raw ``sweep:`` rows (no validation)."""
    data = _load_yaml(path)
    rows = data.get("sweep")
    return rows if isinstance(rows, list) else []


def validate_rows(rows: list[Any]) -> list[str]:
    """Return a list of schema errors; empty list = clean."""
    errors: list[str] = []
    seen_prs: set[int] = set()
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"row #{idx}: must be a mapping")
            continue
        for key in REQUIRED_KEYS:
            if key not in row:
                errors.append(f"row #{idx}: missing required key `{key}`")
        pr = row.get("pr")
        if not isinstance(pr, int) or isinstance(pr, bool):
            errors.append(f"row #{idx}: `pr` must be an int "
                          f"(got {pr!r})")
        else:
            if pr in seen_prs:
                errors.append(f"row #{idx}: duplicate pr {pr}")
            seen_prs.add(pr)
        trigger = row.get("trigger")
        if "trigger" in row and trigger not in ALLOWED_TRIGGERS:
            errors.append(
                f"row #{idx} (pr={pr!r}): trigger={trigger!r} must be "
                f"one of {sorted(ALLOWED_TRIGGERS)}"
            )
        for key in ("genesis_patch", "note"):
            val = row.get(key)
            if key in row and (not isinstance(val, str) or not val.strip()):
                errors.append(
                    f"row #{idx} (pr={pr!r}): `{key}` must be a "
                    f"non-empty string"
                )
    return errors


def _render_text(rows: list[dict[str, Any]]) -> str:
    by_trigger: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_trigger.setdefault(r["trigger"], []).append(r)
    out = ["Upstream sweep watchlist", "=" * 60]
    for trig in sorted(ALLOWED_TRIGGERS):
        items = by_trigger.get(trig, [])
        if not items:
            continue
        out.append(f"\n[{trig}] {len(items)} rows")
        for r in sorted(items, key=lambda x: x["pr"]):
            out.append(f"  - vllm#{r['pr']:<7} -> {r['genesis_patch']}")
    out.append("")
    out.append(f"Total: {len(rows)} rows")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watchlist", type=Path,
                        default=DEFAULT_WATCHLIST,
                        help="Path to upstream_watchlist.yaml")
    parser.add_argument("--json", action="store_true",
                        help="Emit machine-readable JSON")
    args = parser.parse_args(argv)

    try:
        rows = load_sweep(args.watchlist)
    except SystemExit as exc:
        return int(exc.code or 2)

    if not rows:
        print(f"ERROR: no `sweep:` rows found in {args.watchlist}",
              file=sys.stderr)
        return 2

    errors = validate_rows(rows)
    if errors:
        if args.json:
            print(json.dumps({"schema_errors": errors}, indent=2))
        else:
            print("Schema errors:", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"rows": rows, "schema_errors": []},
                         indent=2, sort_keys=False, default=str))
    else:
        print(_render_text(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
