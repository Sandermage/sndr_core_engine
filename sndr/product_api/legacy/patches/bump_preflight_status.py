# SPDX-License-Identifier: Apache-2.0
"""Read-only pin-bump preflight for the Product API.

A daemon-side reimplementation of ``scripts/anchor_sot/bump_preflight.py`` (the
script lives outside the mounted ``sndr/`` tree, so the daemon cannot import it —
but the per-pin manifests it reads ARE in the tree). Compares two pin manifests
(default: the previous pin -> the active/latest pin) and reports what a bump
changed:

  (a) newly retired / version-gated-out patches on the new pin
  (b) retire-broken dependents (HIGH unmitigated = the gate-fail signal — the
      dev301-class silent perf regression)
  (c) perf-bearing patches that went applied -> dropped between the pins

Read-only; fail-safe (``error`` tag, never a 500).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

_RETIRE_STATUSES = ("retired", "version_gated")
_EMPTY: dict[str, Any] = {
    "old_pin": None, "new_pin": None, "newly_retired": [],
    "high_count": 0, "medium_count": 0, "high_unmitigated": [], "high_mitigated": [],
    "perf_landmines": [], "edges": [], "gate_pass": True,
}


def _load(p: Path) -> Optional[dict]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _pin_version(manifest: dict) -> str:
    return str((manifest.get("pins") or {}).get("vllm", "?"))


def _dev_num(pin: str) -> int:
    m = re.search(r"dev(\d+)", pin or "")
    return int(m.group(1)) if m else -1


def _rej_ids_by_status(rej: dict, statuses: tuple[str, ...]) -> set[str]:
    out: set[str] = set()
    for e in (rej.get("rejected") or []):
        if e.get("status") in statuses:
            out.add(str(e.get("key", "")).split("::", 1)[0])
    return out


def _ok_patch_ids(manifest: dict) -> set[str]:
    """Patch ids with >=1 applied (spliced) anchor in a manifest."""
    out: set[str] = set()
    for fe in (manifest.get("files") or {}).values():
        for pid, pe in ((fe or {}).get("patches") or {}).items():
            if (pe or {}).get("anchors"):
                out.add(pid)
    return out


def _perf_patch_ids() -> set[str]:
    try:
        from sndr.dispatcher.registry import PATCH_REGISTRY
        from sndr.dispatcher.spec import iter_patch_specs
        from sndr.engines.vllm.retire_impact import is_perf_signal
    except Exception:  # noqa: BLE001
        return set()
    out: set[str] = set()
    for s in iter_patch_specs():
        credit = (PATCH_REGISTRY.get(s.patch_id) or {}).get("credit", "")
        if is_perf_signal(s.category, s.title, credit):
            out.add(s.patch_id)
    return out


def _select_pins(entries: list[tuple[Path, str, dict]], old: Optional[str],
                 new: Optional[str], running: Optional[str]):
    """Pick (old_entry, new_entry). new = active(running) else latest dev;
    old = highest dev below new. Explicit ``old``/``new`` substrings override."""
    new_e = next((e for e in entries if e[1] == running), entries[-1])
    below = [e for e in entries if _dev_num(e[1]) < _dev_num(new_e[1])]
    old_e = below[-1] if below else entries[0]
    if new:
        new_e = next((e for e in entries if new in e[1] or new in e[0].name), new_e)
    if old:
        old_e = next((e for e in entries if old in e[1] or old in e[0].name), old_e)
    return old_e, new_e


def bump_preflight_status(old: Optional[str] = None, new: Optional[str] = None) -> dict[str, Any]:
    try:
        from .anchor_status import _pins_dir, _running_vllm

        pins_dir = _pins_dir()
        if pins_dir is None:
            return {**_EMPTY, "error": "no_pins_dir"}
        entries: list[tuple[Path, str, dict]] = []
        for d in sorted(pins_dir.iterdir()):
            f = d / "anchors.json"
            if f.is_file():
                m = _load(f)
                if m:
                    entries.append((d, _pin_version(m), m))
        if len(entries) < 2:
            return {**_EMPTY, "error": "need_two_pins"}
        entries.sort(key=lambda e: _dev_num(e[1]))
        (old_dir, old_pin, old_m), (new_dir, new_pin, new_m) = _select_pins(
            entries, old, new, _running_vllm())

        old_rej = _load(old_dir / "drift.rej.json") or {}
        new_rej = _load(new_dir / "drift.rej.json") or {}

        # (a) newly retired / version-gated-out
        newly_retired = sorted(
            _rej_ids_by_status(new_rej, _RETIRE_STATUSES)
            - _rej_ids_by_status(old_rej, _RETIRE_STATUSES))

        # (b) retire-broken dependents. Use the LIVE, mitigation-aware detector:
        # its report exposes high_unmitigated/high_mitigated (the native-form
        # auto-downgrade — PN399 has a fallback independent of the retired id),
        # which the baked dependency_breakage and the flat to_dict() edges drop.
        # Fall back to the baked snapshot only if the live detector is absent.
        breakage: dict[str, Any] = {"high_count": 0, "medium_count": 0, "edges": []}
        high_unmitigated: list[str] = []
        high_mitigated: list[str] = []
        try:
            from sndr.engines.vllm.retire_impact import detect_on_live_registry
            gated = _rej_ids_by_status(new_rej, ("version_gated",))
            try:
                report = detect_on_live_registry(gated_out=gated)
            except TypeError:
                report = detect_on_live_registry()
            breakage = report.to_dict()
            high_unmitigated = [f"{e.retired}->{e.dependent}" for e in report.high_unmitigated]
            high_mitigated = [f"{e.retired}->{e.dependent}" for e in report.high_mitigated]
        except Exception:  # noqa: BLE001 - fall back to the manifest's baked snapshot
            breakage = new_rej.get("dependency_breakage") or breakage
            for e in (breakage.get("edges") or []):
                if e.get("severity") == "HIGH":
                    (high_mitigated if e.get("mitigated") else high_unmitigated).append(
                        f"{e.get('retired')}->{e.get('dependent')}")
        edges = breakage.get("edges") or []

        # (c) perf-bearing patches dropped between pins
        perf_landmines = sorted((_ok_patch_ids(old_m) - _ok_patch_ids(new_m)) & _perf_patch_ids())

        return {
            "old_pin": old_pin, "new_pin": new_pin,
            "newly_retired": newly_retired,
            "high_count": int(breakage.get("high_count", 0)),
            "medium_count": int(breakage.get("medium_count", 0)),
            "high_unmitigated": high_unmitigated,
            "high_mitigated": high_mitigated,
            "perf_landmines": perf_landmines,
            "edges": edges,
            "gate_pass": len(high_unmitigated) == 0,
        }
    except Exception as exc:  # noqa: BLE001 - best-effort; never break the API
        return {**_EMPTY, "error": type(exc).__name__}
