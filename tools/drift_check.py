#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compare a live engine install against a committed manifest; report drift.

Authoritative source = the per-pin ``pins/<pin>/anchors.json`` (the anchor-SoT
the runtime apply path also consumes). Drift is checked with the engine's own
``verify_manifest_against_source`` — per-file ``md5_pristine`` AND every anchor
verified at its recorded byte offset. This is the format the CURRENT pin
(0.23.1_b4c80ec0f) ships; the daily drift job used to read ``manifest.yaml``
which that pin does not have, so it silently no-op'd on the live pin (GAP 4).

Back-compat: older pins that only ship the legacy flat ``manifest.yaml``
(``files.<rel>.md5``, no offsets) are still handled — the loader falls back to a
coarse per-file md5 compare when no ``anchors.json`` exists.

Usage::

    # Check current vllm install against the manifest for a specific pin
    python3 tools/drift_check.py --engine vllm --pin 0.23.1_b4c80ec0f

    # Auto-detect the running pin, emit JSON for CI consumption
    python3 tools/drift_check.py --engine vllm --pin auto --output drift.json

Exit codes:
    0  No drift detected
    1  Drift detected (one or more files / anchors changed)
    2  Invocation error (manifest missing, install missing, etc.)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def compute_file_md5(path: Path) -> str:
    h = hashlib.md5()  # noqa: S324
    h.update(path.read_bytes())
    return h.hexdigest()


def _source_loader(install_root: Path):
    """Build the rel_path -> source-text loader verify_manifest_against_source
    expects (None when the file is absent / unreadable)."""

    def _load(rel_path: str):
        p = install_root / rel_path
        try:
            return p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    return _load


def check_drift_anchors_json(manifest: dict, install_root: Path) -> dict:
    """Authoritative drift check against an ``anchors.json`` manifest.

    Uses the engine's ``verify_manifest_against_source`` (md5_pristine +
    per-anchor offset md5). Each mismatch string is attributed to its file so
    the report keeps the per-file ``severity`` shape the CI consumes.
    """
    from sndr.engines.vllm.wiring.anchor_manifest import (
        verify_manifest_against_source,
    )

    errors = verify_manifest_against_source(manifest, _source_loader(install_root))

    files = manifest.get("files", {})
    results: dict[str, dict] = {}
    drift_files: set[str] = set()
    missing_files: set[str] = set()
    for rel in files:
        rel_errors = [e for e in errors if e.startswith(f"{rel}:")]
        if not rel_errors:
            results[rel] = {"severity": "ok"}
        elif any("source not loadable" in e for e in rel_errors):
            results[rel] = {"severity": "blocked", "reason": "file missing in live install"}
            missing_files.add(rel)
        else:
            results[rel] = {"severity": "drift", "errors": rel_errors}
            drift_files.add(rel)

    return {
        "engine": "vllm",
        "pin": (manifest.get("pins") or {}).get("vllm"),
        "format": "anchors.json",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": results,
        "summary": {
            "ok": len(results) - len(drift_files) - len(missing_files),
            "drift": len(drift_files),
            "blocked": len(missing_files),
        },
    }


def check_drift_manifest_yaml(manifest: dict, install_root: Path) -> dict:
    """Back-compat drift check against a legacy flat ``manifest.yaml``.

    Coarse per-file md5 compare (``files.<rel>.md5``); no anchor offsets exist in
    this format. ``missing: true`` files are skipped (they record an upstream
    removal, not a live-install defect).
    """
    results: dict[str, dict] = {}
    drift_count = missing_count = ok_count = 0

    for rel, file_data in manifest.get("files", {}).items():
        if file_data.get("missing"):
            results[rel] = {"severity": "ok", "reason": "recorded as upstream-removed"}
            ok_count += 1
            continue
        abs_path = install_root / rel
        if not abs_path.is_file():
            results[rel] = {"severity": "blocked", "reason": "file missing in live install"}
            missing_count += 1
            continue
        live_md5 = compute_file_md5(abs_path)
        expected_md5 = file_data.get("md5")
        if live_md5 != expected_md5:
            results[rel] = {"severity": "drift", "expected_md5": expected_md5,
                            "actual_md5": live_md5}
            drift_count += 1
        else:
            results[rel] = {"severity": "ok"}
            ok_count += 1

    return {
        "engine": manifest.get("engine"),
        "pin": manifest.get("pin"),
        "format": "manifest.yaml",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": results,
        "summary": {"ok": ok_count, "drift": drift_count, "blocked": missing_count},
    }


def resolve_manifest(pin_dir: Path):
    """Return ``(format, manifest_dict)`` preferring the authoritative
    ``anchors.json`` and falling back to the legacy ``manifest.yaml``. Returns
    ``(None, None)`` when neither exists."""
    anchors = pin_dir / "anchors.json"
    if anchors.is_file():
        return "anchors.json", json.loads(anchors.read_text(encoding="utf-8"))
    legacy = pin_dir / "manifest.yaml"
    if legacy.is_file():
        import yaml  # local import: only needed for the legacy path
        return "manifest.yaml", yaml.safe_load(legacy.read_text(encoding="utf-8"))
    return None, None


def check_drift_for_pin(pin_dir: Path, install_root: Path):
    """Dispatch to the right checker by manifest format. Returns the report dict
    or None when the pin dir has no manifest at all."""
    fmt, manifest = resolve_manifest(pin_dir)
    if fmt is None:
        return None
    if fmt == "anchors.json":
        return check_drift_anchors_json(manifest, install_root)
    return check_drift_manifest_yaml(manifest, install_root)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--engine", default="vllm")
    p.add_argument("--pin", required=True, help="Pin identifier OR 'auto' to use the current detected pin")
    p.add_argument("--install-root", help="Path to engine install (default: import the package)")
    p.add_argument("--output", type=Path, help="Write JSON report to this path")
    p.add_argument("--repo-root", type=Path, help="Repo root (default: derived from this file)")
    args = p.parse_args()

    repo_root = args.repo_root or Path(__file__).parent.parent

    # Resolve install root
    if args.install_root:
        install_root = Path(args.install_root)
    else:
        if args.engine == "vllm":
            try:
                import vllm  # type: ignore
                install_root = Path(vllm.__file__).parent
            except ImportError:
                print("ERROR: vllm not installed; use --install-root", file=sys.stderr)
                return 2
        else:
            print(f"ERROR: --install-root required for engine '{args.engine}'", file=sys.stderr)
            return 2

    # Resolve pin
    pin = args.pin
    if pin == "auto":
        try:
            from sndr.config import SndrConfig
            from sndr.engines import get_engine
            EngineCls = get_engine(args.engine)
            config = SndrConfig.from_env()
            engine = EngineCls(config=config)
            pin = engine._normalize_pin(engine.detect_version())  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001
            print(f"ERROR: auto-detection failed: {e}", file=sys.stderr)
            return 2

    pin_dir = repo_root / "sndr" / "engines" / args.engine / "pins" / pin
    fmt, _ = resolve_manifest(pin_dir)
    if fmt is None:
        print(f"ERROR: no manifest (anchors.json or manifest.yaml) at {pin_dir}", file=sys.stderr)
        print("       Run: make rebuild-pin SSH_HOST=<user@host>", file=sys.stderr)
        return 2

    report = check_drift_for_pin(pin_dir, install_root)

    if args.output:
        args.output.write_text(json.dumps(report, indent=2))

    summary = report["summary"]
    if summary["drift"] > 0 or summary["blocked"] > 0:
        print(f"DRIFT DETECTED ({report['format']}): "
              f"{summary['drift']} files drifted, {summary['blocked']} missing")
        if not args.output:
            print(json.dumps(report, indent=2))
        return 1

    print(f"OK ({report['format']}): {summary['ok']} files match manifest; no drift detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
