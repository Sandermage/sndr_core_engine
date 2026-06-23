#!/usr/bin/env python3
"""Phase 4 — compare two anchor manifests; report what drifted, anchor-level.

Two modes:

  same-pin (default) — self-audit: is the COMMITTED per-pin manifest still
    substantively identical to a fresh rig regen? Volatile metadata
    (``generated_at`` / ``generated_by``) is excluded. Exit 0 if identical,
    1 if anything drifted. Used by ``scripts/anchor_sot/audit_pin.sh``.

      compare_manifest.py <committed.json> <fresh.json>

  cross-pin (``--cross-pin``) — bump helper: given the OLD pin manifest and the
    NEW pin manifest, print the per-anchor delta for the new pin (moved /
    md5-changed / added / removed / merge_status-changed), a
    ``make rebuild-pin`` regeneration hint, and a concise
    "re-anchor only these K drifted anchors" list. Always exits 0 (it is a
    report, not a gate) unless the inputs are unreadable.

      compare_manifest.py --cross-pin <old_pin/anchors.json> <new_pin/anchors.json>

Both modes share one anchor-level differ. The drift list a same-pin audit prints
is exactly the re-anchor list a bump needs: the anchors whose address moved or
whose surrounding bytes changed.
"""
import json
import sys

VOLATILE = ("generated_at", "generated_by")


def _load(path):
    m = json.load(open(path))
    return {k: v for k, v in m.items() if k not in VOLATILE}


def _iter_anchors(manifest):
    """Yield (rel, patch_id, sub, anchor_meta) for every anchor in a manifest."""
    for rel, fe in (manifest.get("files") or {}).items():
        for pid, pe in ((fe or {}).get("patches") or {}).items():
            for sub, a in ((pe or {}).get("anchors") or {}).items():
                yield rel, pid, sub, (a or {})


def _anchor_index(manifest):
    """Map (rel, patch_id, sub) -> anchor_meta, the addressable unit."""
    return {(rel, pid, sub): a for rel, pid, sub, a in _iter_anchors(manifest)}


def _merge_status_index(manifest):
    """Map (rel, patch_id) -> merge_status (None when the field is absent)."""
    out = {}
    for rel, fe in (manifest.get("files") or {}).items():
        for pid, pe in ((fe or {}).get("patches") or {}).items():
            out[(rel, pid)] = (pe or {}).get("merge_status")
    return out


def anchor_delta(old, new):
    """Per-anchor delta between two manifests.

    Returns a dict with keys ``moved`` / ``md5_changed`` / ``added`` /
    ``removed`` / ``merge_status_changed`` — each a list of human strings, plus
    ``reanchor`` (the concise re-anchor target list: moved + md5_changed +
    removed, the anchors that need a human eye on a bump).
    """
    oi, ni = _anchor_index(old), _anchor_index(new)
    old_keys, new_keys = set(oi), set(ni)

    moved, md5_changed, added, removed = [], [], [], []
    reanchor = []

    for k in sorted(old_keys & new_keys):
        rel, pid, sub = k
        oa, na = oi[k], ni[k]
        label = f"{pid}::{sub} ({rel})"
        o_off, n_off = oa.get("byte_offset"), na.get("byte_offset")
        o_md5, n_md5 = oa.get("anchor_md5"), na.get("anchor_md5")
        if o_md5 != n_md5:
            md5_changed.append(f"{label}: anchor_md5 {o_md5} -> {n_md5}")
            reanchor.append(label)
        elif o_off != n_off:
            # md5 identical but the byte address moved (insertion above) — a
            # clean auto-relocate, but surface it so the operator sees the shift.
            moved.append(f"{label}: byte_offset {o_off} -> {n_off}")

    for k in sorted(new_keys - old_keys):
        rel, pid, sub = k
        added.append(f"{pid}::{sub} ({rel})")

    for k in sorted(old_keys - new_keys):
        rel, pid, sub = k
        label = f"{pid}::{sub} ({rel})"
        removed.append(label)
        reanchor.append(label)

    # merge_status transitions (e.g. not_merged -> fully_merged on the new pin)
    om, nm = _merge_status_index(old), _merge_status_index(new)
    merge_changed = []
    for k in sorted(set(om) & set(nm)):
        rel, pid = k
        if om[k] != nm[k]:
            merge_changed.append(f"{pid} ({rel}): merge_status {om[k]} -> {nm[k]}")

    return {
        "moved": moved,
        "md5_changed": md5_changed,
        "added": added,
        "removed": removed,
        "merge_status_changed": merge_changed,
        "reanchor": sorted(set(reanchor)),
    }


def _print_delta(delta):
    def _section(title, items):
        if items:
            print("  %s (%d):" % (title, len(items)))
            for it in items:
                print("    - %s" % it)
    _section("moved (auto-relocate, md5 stable)", delta["moved"])
    _section("anchor_md5 changed", delta["md5_changed"])
    _section("added", delta["added"])
    _section("removed", delta["removed"])
    _section("merge_status changed", delta["merge_status_changed"])


def _cross_pin(old_path, new_path):
    old, new = _load(old_path), _load(new_path)
    old_pin = (old.get("pins") or {}).get("vllm")
    new_pin = (new.get("pins") or {}).get("vllm")
    print("CROSS-PIN delta: %s -> %s" % (old_pin, new_pin))
    delta = anchor_delta(old, new)
    _print_delta(delta)

    reanchor = delta["reanchor"]
    if reanchor:
        print("\nre-anchor only these %d drifted anchors on the new pin:"
              % len(reanchor))
        for label in reanchor:
            print("  * %s" % label)
    else:
        print("\nno drifted anchors — every old anchor relocated cleanly "
              "(md5 stable) or is upstream-merged.")

    # regeneration hint — the new pin's normalized dir name when resolvable.
    hint_pin = new_pin or "<new>"
    try:
        sys.path.insert(0, _repo_root())
        from sndr.engines.vllm.wiring.anchor_manifest import normalize_pin
        hint_pin = normalize_pin(new_pin) or hint_pin
    except Exception:  # noqa: BLE001 — hint is best-effort
        pass
    print("\nregenerate on the rig:  make rebuild-pin PIN=%s" % hint_pin)
    return 0


def _repo_root():
    import os
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )


def _same_pin(a_path, b_path):
    a, b = _load(a_path), _load(b_path)
    if json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True):
        print("MATCH: substantively identical (ignoring %s)" % (VOLATILE,))
        return 0

    print("DRIFT: %s != %s" % (a_path, b_path))
    fa, fb = a.get("files", {}), b.get("files", {})
    only_a = sorted(set(fa) - set(fb))
    only_b = sorted(set(fb) - set(fa))
    if only_a:
        print("  only in committed: %s" % only_a[:10])
    if only_b:
        print("  only in fresh:     %s" % only_b[:10])
    for f in sorted(set(fa) & set(fb)):
        if json.dumps(fa[f], sort_keys=True) != json.dumps(fb[f], sort_keys=True):
            print("  changed: %s" % f)
    if a.get("pins") != b.get("pins"):
        print("  pins: committed=%s fresh=%s" % (a.get("pins"), b.get("pins")))

    # anchor-level detail so the audit says WHICH anchors to re-anchor, not
    # just which file changed.
    delta = anchor_delta(a, b)
    if any(delta[k] for k in
           ("moved", "md5_changed", "added", "removed", "merge_status_changed")):
        print("  anchor-level delta:")
        _print_delta(delta)
    if delta["reanchor"]:
        print("  re-anchor these %d: %s" % (
            len(delta["reanchor"]), delta["reanchor"][:12]))
    return 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cross = False
    if argv and argv[0] == "--cross-pin":
        cross = True
        argv = argv[1:]
    if len(argv) != 2:
        prog = "compare_manifest.py"
        print("usage: %s [--cross-pin] <old.json> <new.json>" % prog,
              file=sys.stderr)
        return 2
    a_path, b_path = argv
    return _cross_pin(a_path, b_path) if cross else _same_pin(a_path, b_path)


if __name__ == "__main__":
    sys.exit(main())
