"""TASK 2 — compare_manifest.py: anchor-level + cross-pin + actionable.

The old comparator was file-level coarse ("changed: <file>"). The upgrade adds a
per-anchor delta (moved / md5-changed / added / removed / merge_status-changed)
and an explicit ``--cross-pin`` mode that prints the new-pin delta + a
``make rebuild-pin`` hint + a concise "re-anchor only these K" list. The
same-pin self-audit (used by audit_pin.sh) must keep working — covered by
test_ph4_pipeline.py; here we cover the new behavior.

Tests both via the importable ``anchor_delta`` helper (fast, precise) and via the
subprocess CLI (the contract audit_pin.sh / a bump invokes).
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
COMPARE = REPO / "scripts" / "anchor_sot" / "compare_manifest.py"


def _import_compare():
    spec = importlib.util.spec_from_file_location("_compare_manifest_t", COMPARE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _anchor(off, md5):
    return {"byte_offset": off, "byte_length": 10, "anchor_md5": md5}


def _manifest(pin, patches_by_file, merge_by_pid=None):
    """patches_by_file: {rel: {pid: {sub: anchor_meta}}}.
    merge_by_pid: {(rel, pid): merge_status}."""
    merge_by_pid = merge_by_pid or {}
    files = {}
    for rel, patches in patches_by_file.items():
        pdict = {}
        for pid, subs in patches.items():
            pe = {"anchors": dict(subs)}
            ms = merge_by_pid.get((rel, pid))
            if ms is not None:
                pe["merge_status"] = ms
            pdict[pid] = pe
        files[rel] = {"md5_pristine": "0" * 32, "size_bytes": 1, "patches": pdict}
    return {"manifest_version": 1, "pins": {"vllm": pin, "genesis": "g"},
            "files": files}


# ─── anchor_delta unit: moved / added / removed / md5 / merge_status ────


def test_anchor_delta_detects_moved_added_removed_and_md5():
    mod = _import_compare()
    old = _manifest("p1", {"f.py": {
        "PA": {"s1": _anchor(100, "aaa"),      # will MOVE (offset only)
               "s2": _anchor(200, "bbb")},     # will MD5-CHANGE
        "PB": {"s1": _anchor(300, "ccc")},     # will be REMOVED
    }})
    new = _manifest("p2", {"f.py": {
        "PA": {"s1": _anchor(150, "aaa"),      # moved: 100 -> 150, md5 same
               "s2": _anchor(200, "ZZZ"),      # md5 changed
               "s3": _anchor(400, "ddd")},     # ADDED
        # PB removed entirely
    }})
    d = mod.anchor_delta(old, new)
    assert any("100 -> 150" in m for m in d["moved"])
    assert any("PA::s2" in m and "bbb -> ZZZ" in m for m in d["md5_changed"])
    assert any("PA::s3" in a for a in d["added"])
    assert any("PB::s1" in r for r in d["removed"])
    # re-anchor list = md5_changed + removed (NOT clean moves)
    assert any("PA::s2" in r for r in d["reanchor"])
    assert any("PB::s1" in r for r in d["reanchor"])
    assert not any("PA::s1" in r for r in d["reanchor"])  # clean move excluded


def test_anchor_delta_detects_merge_status_change():
    mod = _import_compare()
    old = _manifest("p1", {"f.py": {"PA": {"s1": _anchor(10, "aaa")}}},
                    merge_by_pid={("f.py", "PA"): "not_merged"})
    new = _manifest("p2", {"f.py": {"PA": {"s1": _anchor(10, "aaa")}}},
                    merge_by_pid={("f.py", "PA"): "fully_merged"})
    d = mod.anchor_delta(old, new)
    assert any("not_merged -> fully_merged" in m
               for m in d["merge_status_changed"])


def test_anchor_delta_clean_move_is_not_reanchor():
    mod = _import_compare()
    old = _manifest("p1", {"f.py": {"PA": {"s1": _anchor(10, "aaa")}}})
    new = _manifest("p2", {"f.py": {"PA": {"s1": _anchor(99, "aaa")}}})
    d = mod.anchor_delta(old, new)
    assert d["moved"] and not d["reanchor"]


# ─── cross-pin CLI mode ────────────────────────────────────────────────


def _write(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj))
    return str(p)


def test_cross_pin_mode_prints_delta_hint_and_reanchor_list(tmp_path):
    old = _write(tmp_path, "old.json", _manifest("0.22.1rc1.dev1+gda1daf40b",
        {"f.py": {"PA": {"s1": _anchor(10, "aaa"), "s2": _anchor(20, "bbb")}}}))
    new = _write(tmp_path, "new.json", _manifest("0.23.1rc1.dev148+gb4c80ec0f",
        {"f.py": {"PA": {"s1": _anchor(10, "aaa"),     # stable
                         "s2": _anchor(20, "CHANGED")}}}))  # drifted
    r = subprocess.run([sys.executable, str(COMPARE), "--cross-pin", old, new],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    assert "CROSS-PIN delta" in out
    assert "anchor_md5 changed" in out
    assert "PA::s2" in out
    assert "re-anchor only these 1 drifted anchors" in out
    # regeneration hint uses the normalized new pin dir name
    assert "make rebuild-pin PIN=0.23.1_b4c80ec0f" in out


def test_cross_pin_mode_zero_drift_reports_clean(tmp_path):
    old = _write(tmp_path, "old.json", _manifest("p1",
        {"f.py": {"PA": {"s1": _anchor(10, "aaa")}}}))
    new = _write(tmp_path, "new.json", _manifest("p2",
        {"f.py": {"PA": {"s1": _anchor(40, "aaa")}}}))  # clean move only
    r = subprocess.run([sys.executable, str(COMPARE), "--cross-pin", old, new],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "no drifted anchors" in r.stdout


def test_same_pin_drift_now_emits_anchor_level_detail(tmp_path):
    # the same-pin audit path must ALSO surface which anchor drifted, not just
    # the file (back-compat: still prints DRIFT + changed:, exit 1).
    a = _write(tmp_path, "a.json", _manifest("p",
        {"f.py": {"PA": {"s1": _anchor(10, "aaa")}}}))
    b = _write(tmp_path, "b.json", _manifest("p",
        {"f.py": {"PA": {"s1": _anchor(10, "DRIFTED")}}}))
    r = subprocess.run([sys.executable, str(COMPARE), a, b],
                       capture_output=True, text=True)
    assert r.returncode == 1
    assert "DRIFT" in r.stdout
    assert "changed: f.py" in r.stdout          # back-compat line
    assert "anchor-level delta" in r.stdout      # new detail
    assert "PA::s1" in r.stdout
