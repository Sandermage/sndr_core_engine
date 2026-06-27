#!/usr/bin/env python3
"""Bump-preflight gate — surface the silent retire-breakage class on a pin bump.

Given the OLD-pin and NEW-pin anchor manifests (each a ``pins/<pin>/`` dir or an
``anchors.json`` with a sibling ``drift.rej.json``), print an ACTIONABLE
checklist and exit NON-ZERO if any HIGH-severity perf dependent is broken on the
new pin. Reports:

  (a) patches NEWLY retired / version-gated-out on the new pin (vs old),
  (b) their BROKEN dependents — the retire-impact detector edges, ranked,
  (c) PERF-tier patches that moved ok -> skip/drift between the two pins
      (the perf-landmine list: a perf optimization that silently went dead),
  (d) a reminder that a canonical A/B (``genesis_bench_suite.py``) MUST be run
      for any perf-tier delta (iron-rule #9).

This is the gate the dev148->dev301 bump lacked: PN353A retired, PN399's anchor
went missing, PN399 SKIPPED as a benign skip, its decode-scratch perf
optimization no-op'd, and a real -5.5% TPS regression hit the 35B with
``genuine_drift=0`` (clean). With this gate the bump fails loudly on the broken
HIGH-severity PERF dependent until a canonical A/B clears it.

Usage:
    bump_preflight.py <old_pin_dir|old_anchors.json> <new_pin_dir|new_anchors.json>

Exit codes:
    0  no HIGH-severity perf dependent broken on the new pin (clean / advisory)
    1  >=1 HIGH-severity perf dependent broken — run a canonical A/B before bump
    2  usage / unreadable input
"""
import json
import os
import sys

# Make the repo root importable so the detector + spec layer resolve when this
# script is invoked directly (mirrors compare_manifest._repo_root()).
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")))


def _resolve_pair(path):
    """Return (anchors.json, drift.rej.json) paths from a dir or anchors file."""
    if os.path.isdir(path):
        return (os.path.join(path, "anchors.json"),
                os.path.join(path, "drift.rej.json"))
    base = os.path.dirname(path)
    return path, os.path.join(base, "drift.rej.json")


def _load(path):
    if not os.path.isfile(path):
        return None
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return None


def _ok_patch_ids(manifest):
    """patch ids with >=1 applied (ok) anchor in a manifest."""
    out = set()
    for fe in (manifest.get("files") or {}).values():
        for pid in ((fe or {}).get("patches") or {}):
            pe = fe["patches"][pid]
            if (pe or {}).get("anchors"):
                out.add(pid)
    return out


def _applied_subs_by_patch(manifest):
    """Map patch_id -> set of APPLIED sub-anchor names in a manifest.

    Sub-patch granularity (the PN399/PN351 no-op class): a patch can keep >=1
    applied anchor (so ``_ok_patch_ids`` still lists it as ``ok``) while an
    INDIVIDUAL sub-patch — often a ``required=False`` perf effect — silently
    drops because its anchor drifted (status optional_absent/anchor_drift). The
    manifest records the surviving subs under ``patches.<pid>.anchors`` keyed by
    sub name, so the SET DIFFERENCE old-subs minus new-subs is exactly the
    sub-patches that went dead on the new pin while the patch stayed ok.
    """
    out: dict[str, set] = {}
    for fe in (manifest.get("files") or {}).values():
        for pid, pe in ((fe or {}).get("patches") or {}).items():
            out.setdefault(pid, set()).update(
                ((pe or {}).get("anchors") or {}).keys())
    return out


def _rej_ids_by_status(rej, statuses):
    """patch ids in the reject set whose status is in ``statuses``."""
    out = set()
    for e in (rej.get("rejected") or []):
        if e.get("status") in statuses:
            out.add(str(e.get("key", "")).split("::", 1)[0])
    return out


def _perf_patch_ids():
    """Set of patch ids that are performance-bearing (live registry)."""
    try:
        from sndr.dispatcher.registry import PATCH_REGISTRY
        from sndr.dispatcher.spec import iter_patch_specs
        from sndr.engines.vllm.retire_impact import is_perf_signal
    except Exception:  # noqa: BLE001 — registry unavailable: empty set
        return set()
    out = set()
    for s in iter_patch_specs():
        credit = (PATCH_REGISTRY.get(s.patch_id) or {}).get("credit", "")
        if is_perf_signal(s.category, s.title, credit):
            out.add(s.patch_id)
    return out


def _reconcile_breakage(committed, live):
    """Reconcile a committed dependency_breakage section against a fresh live
    detector run. For every committed edge that the LIVE registry also reports
    (same retired->dependent), adopt the live ``severity`` + ``mitigated`` (the
    current truth — the committed snapshot may predate the mitigation flag).
    Committed-only edges (e.g. synthetic offline-test edges the live registry
    can't reproduce) are kept verbatim. Counts are recomputed from the result.

    This makes the gate robust to a stale committed section without discarding
    edges only the manifest knows about (offline determinism preserved).
    """
    live_by_key = {
        (e.get("retired"), e.get("dependent")): e
        for e in (live.get("edges") or [])
    }
    merged = []
    for e in (committed.get("edges") or []):
        key = (e.get("retired"), e.get("dependent"))
        if key in live_by_key:
            le = live_by_key[key]
            e = dict(e)
            e["severity"] = le.get("severity", e.get("severity"))
            e["mitigated"] = le.get("mitigated", e.get("mitigated", False))
            if le.get("detail"):
                e["detail"] = le["detail"]
            if le.get("via"):
                e["via"] = le["via"]
        merged.append(e)
    high = [e for e in merged if e.get("severity") == "HIGH"]
    return {
        "high_count": len(high),
        "high_mitigated_count": len([e for e in high if e.get("mitigated")]),
        "high_unmitigated_count": len([e for e in high
                                       if not e.get("mitigated")]),
        "medium_count": len([e for e in merged
                             if e.get("severity") != "HIGH"]),
        "edges": merged,
    }


def preflight(old_dir, new_dir):
    old_anchors_p, old_rej_p = _resolve_pair(old_dir)
    new_anchors_p, new_rej_p = _resolve_pair(new_dir)
    old_anchors, new_anchors = _load(old_anchors_p), _load(new_anchors_p)
    old_rej, new_rej = _load(old_rej_p) or {}, _load(new_rej_p)
    if old_anchors is None or new_anchors is None or new_rej is None:
        miss = [p for p, v in (
            (old_anchors_p, old_anchors), (new_anchors_p, new_anchors),
            (new_rej_p, new_rej)) if v is None]
        print("FATAL: missing/unreadable input: %s" % miss, file=sys.stderr)
        return 2

    old_pin = (old_anchors.get("pins") or {}).get("vllm", "?")
    new_pin = (new_anchors.get("pins") or {}).get("vllm", "?")
    print("=== bump preflight: %s -> %s ===" % (old_pin, new_pin))

    _RETIRE_STATUSES = ("retired", "version_gated")
    old_retired = _rej_ids_by_status(old_rej, _RETIRE_STATUSES)
    new_retired = _rej_ids_by_status(new_rej, _RETIRE_STATUSES)
    newly_retired = sorted(new_retired - old_retired)

    # (a) newly retired / gated-out on the new pin
    print("\n(a) newly retired / version-gated-out on %s (%d):"
          % (new_pin, len(newly_retired)))
    for pid in newly_retired:
        print("    - %s" % pid)
    if not newly_retired:
        print("    (none)")

    # (b) broken dependents. The new pin's committed dependency_breakage section
    # is a POINT-IN-TIME snapshot — it can go STALE as the retire-impact detector
    # evolves (the committed dev424 section predates the apply-state-aware
    # ``mitigated`` flag, so it labels the live-MITIGATED PN353A->PN399 edge as a
    # FAIL). The dependency graph + mitigation state are a LIVE-REGISTRY property,
    # so we RECONCILE the committed section against a fresh live detector run:
    # for any edge the live registry also knows (same retired->dependent), adopt
    # the live severity/mitigated (the current truth); committed-only edges
    # (synthetic/offline-test edges the registry can't reproduce) are kept as-is.
    # Falls back to the committed section verbatim when the registry can't import.
    breakage = new_rej.get("dependency_breakage")
    live = None
    try:
        from sndr.engines.vllm.retire_impact import detect_on_live_registry
        live = detect_on_live_registry(
            gated_out=_rej_ids_by_status(new_rej, ("version_gated",))
        ).to_dict()
    except Exception:  # noqa: BLE001 — registry unavailable: use committed only
        live = None
    if breakage is None:
        breakage = live or {"high_count": 0, "medium_count": 0, "edges": []}
    elif live is not None:
        breakage = _reconcile_breakage(breakage, live)
    edges = breakage.get("edges") or []
    high_edges = [e for e in edges if e.get("severity") == "HIGH"]
    # APPLY-STATE-AWARE: a HIGH edge flagged ``mitigated`` is already handled (the
    # dependent has a working fallback anchor independent of the retired id — the
    # PN399 native-form C2 sibling). It is still LISTED, but the gate fails ONLY on
    # genuinely-UNMITIGATED HIGH edges (the real PN399-incident class: a dependent
    # whose only path references the retired id).
    high_unmitigated = [e for e in high_edges if not e.get("mitigated")]
    high_mitigated = [e for e in high_edges if e.get("mitigated")]
    print("\n(b) retire-broken dependents (HIGH=%d [mitigated=%d unmitigated=%d] "
          "MEDIUM=%d):" % (breakage.get("high_count", 0), len(high_mitigated),
                           len(high_unmitigated), breakage.get("medium_count", 0)))
    for e in edges:
        if e.get("severity") == "HIGH":
            mark = "HIGH-MITIGATED" if e.get("mitigated") else "HIGH"
        else:
            mark = "med "
        print("    [%s] %s" % (mark, e.get("detail")))
    if not edges:
        print("    (none)")

    # (c) perf-tier patches that moved ok -> skip/drift between the two pins
    perf_ids = _perf_patch_ids()
    old_ok = _ok_patch_ids(old_anchors)
    new_ok = _ok_patch_ids(new_anchors)
    new_skipped = _rej_ids_by_status(
        new_rej, ("anchor_drift", "retired", "version_gated",
                  "ambiguous", "optional_absent", "upstream_merged"))
    perf_landmines = sorted(
        pid for pid in (old_ok - new_ok)
        if pid in perf_ids and pid in new_skipped
    )
    print("\n(c) PERF-tier patches that went ok -> skip/drift on %s (%d) "
          "— perf landmines:" % (new_pin, len(perf_landmines)))
    for pid in perf_landmines:
        print("    * %s (was applied on %s, now skipped/drifted)"
              % (pid, old_pin))
    if not perf_landmines:
        print("    (none)")

    # (c2) SUB-PATCH no-op landmines — the PN399/PN351 class (c) cannot see.
    # A perf-bearing patch can keep >=1 applied anchor (so it stays out of (c)'s
    # ok->skip set) while an INDIVIDUAL sub-patch — typically a required=False
    # perf EFFECT — silently drops because its anchor drifted. The patch reports
    # ``ok``, genuine_anchor_drift stays 0, but the optimization is dead. This is
    # the literal dev148->dev301 PN399 incident at sub granularity. Detect by the
    # set difference of APPLIED sub-anchors per perf patch across the two pins.
    old_subs = _applied_subs_by_patch(old_anchors)
    new_subs = _applied_subs_by_patch(new_anchors)
    sub_landmines = []  # (pid, [lost_subs])
    for pid in sorted(perf_ids):
        # only patches that REMAIN ok on both pins — a fully-dropped patch is
        # already covered by (c); here we want the patch that LOOKS healthy.
        if pid not in old_ok or pid not in new_ok:
            continue
        lost = sorted(old_subs.get(pid, set()) - new_subs.get(pid, set()))
        if lost:
            sub_landmines.append((pid, lost))
    print("\n(c2) PERF sub-patch no-op landmines on %s (%d) — patch still ok but "
          "a perf sub-patch went dead (the PN399 class):" % (
              new_pin, len(sub_landmines)))
    for pid, lost in sub_landmines:
        print("    * %s lost applied sub-patch(es): %s (patch still reports ok "
              "on both pins — effect silently no-op'd)" % (pid, ", ".join(lost)))
    if not sub_landmines:
        print("    (none)")

    # (d) iron-rule #9 reminder + verdict
    perf_delta = (bool(high_unmitigated) or bool(perf_landmines)
                  or bool(sub_landmines))
    print("\n(d) iron-rule #9 — bench methodology:")
    if perf_delta:
        print("    A canonical A/B (genesis_bench_suite.py --quick) is REQUIRED "
              "for the perf-tier delta above before promoting this pin. "
              "Custom/temp=0 single-prompt benches give a systematic offset — "
              "apples-to-apples only.")
    else:
        print("    No perf-tier delta detected — no A/B gate triggered "
              "(still bench-validate the pin per the bump playbook).")

    if high_unmitigated:
        print("\nRESULT: FAIL — %d UNMITIGATED HIGH-severity PERF dependent(s) "
              "broken on %s (no working fallback anchor). Re-anchor the dependent "
              "against the new pin OR run a canonical A/B proving no regression "
              "before promoting." % (len(high_unmitigated), new_pin))
        return 1
    # Advisory perf-delta tail (perf_landmines + sub_landmines): NOT a hard fail
    # on its own (a perf patch/sub can legitimately drop when upstream merges the
    # fix), but it MUST be surfaced loudly with the iron-rule-#9 A/B gate so the
    # PN399 silent-no-op class never passes unnoticed. Reported in the PASS line.
    if perf_delta:
        print("\nRESULT: PASS (with A/B gate) — no UNMITIGATED HIGH dependency "
              "break, but a perf-tier delta on %s (perf_landmines=%d "
              "sub_landmines=%d high_mitigated=%d) REQUIRES a canonical A/B "
              "before promoting (iron-rule #9). Re-anchor the dead sub-patch(es) "
              "above OR prove no regression with genesis_bench_suite.py."
              % (new_pin, len(perf_landmines), len(sub_landmines),
                 len(high_mitigated)))
        return 0
    if high_mitigated:
        print("\nRESULT: PASS — %d HIGH-severity edge(s) are MITIGATED (the "
              "dependent has a working fallback anchor independent of the retired "
              "id — already handled); no unmitigated HIGH on %s."
              % (len(high_mitigated), new_pin))
        return 0
    print("\nRESULT: PASS — no HIGH-severity perf dependent broken on %s."
          % new_pin)
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print("usage: bump_preflight.py <old_pin_dir|anchors.json> "
              "<new_pin_dir|anchors.json>", file=sys.stderr)
        return 2
    return preflight(argv[0], argv[1])


if __name__ == "__main__":
    sys.exit(main())
