"""TASK 4 — commit-coverage hygiene: build_manifest emits both files +
asserts discovered == ok + rejected; summarize_rej.py prints a human summary.

Drives build_manifest.py end-to-end via subprocess with synthetic targets.json /
pristine.json envelopes (matching discover.py / pristine_dump.py), since the real
pipeline needs a rig. Then summarizes the emitted drift.rej.json.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ANCHOR_SOT = REPO / "scripts" / "anchor_sot"
BUILD = ANCHOR_SOT / "build_manifest.py"
SUMMARIZE = ANCHOR_SOT / "summarize_rej.py"


def _target(pid, sub, rel, anchor, repl, required=True, markers=None):
    return {
        "patch_id": pid, "sub": sub, "target_rel": rel,
        "anchor": anchor, "replacement": repl, "required": required,
        "vllm_version_range": None,
        "upstream_merged_markers": list(markers or []),
    }


def _run_build(tmp_path, targets, files, pin="0.23.1rc1.dev1+gdeadbeef0"):
    repo = tmp_path / "repo"
    (repo / "sndr" / "engines" / "vllm" / "pins").mkdir(parents=True)
    tjson = tmp_path / "targets.json"
    pjson = tmp_path / "pristine.json"
    tjson.write_text(json.dumps({"pin": pin, "genesis_pin": "g", "targets": targets}))
    pjson.write_text(json.dumps({"pin": pin, "files": files}))
    r = subprocess.run(
        [sys.executable, str(BUILD), str(tjson), str(pjson), str(repo), pin, "g"],
        capture_output=True, text=True,
    )
    return r, repo


def _pin_dir(repo, pin="0.23.1_deadbeef0"):
    return repo / "sndr" / "engines" / "vllm" / "pins" / pin


def test_build_emits_both_files_and_passes_coverage(tmp_path):
    targets = [
        _target("PA", "s1", "f.py", "ANCHOR_A", "REPL_A"),
        _target("PB", "s1", "f.py", "MISSING_ANCHOR", "R"),  # -> anchor_drift
    ]
    files = {"f.py": "x ANCHOR_A y"}
    r, repo = _run_build(tmp_path, targets, files)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "coverage: discovered=2 == ok=1 + rejected=1" in r.stdout

    pin_dir = _pin_dir(repo)
    assert (pin_dir / "anchors.json").is_file()
    rej_path = pin_dir / "drift.rej.json"
    assert rej_path.is_file()
    rej = json.loads(rej_path.read_text())
    # coverage block + full rejected set are recorded (no silent loss)
    assert rej["coverage"] == {"discovered": 2, "ok": 1, "rejected": 1}
    assert any(e["key"] == "PB::s1" and e["status"] == "anchor_drift"
               for e in rej["rejected"])
    # merge tri-state roll-up present
    assert rej["merge_status"]["PA"]["merge_status"] == "not_merged"


def test_build_rej_records_fully_merged_patch(tmp_path):
    targets = [
        _target("PM", "s1", "f.py", "A1", "R1", markers=["def native_one"]),
        _target("PM", "s2", "f.py", "A2", "R2", markers=["def native_two"]),
    ]
    files = {"f.py": "A1 A2 def native_one def native_two"}
    r, repo = _run_build(tmp_path, targets, files)
    assert r.returncode == 0, r.stdout + r.stderr
    rej = json.loads((_pin_dir(repo) / "drift.rej.json").read_text())
    assert rej["merge_status"]["PM"]["merge_status"] == "fully_merged"
    # the fully-merged patch is VISIBLE in anchors.json (not silently dropped)
    m = json.loads((_pin_dir(repo) / "anchors.json").read_text())
    assert m["files"]["f.py"]["patches"]["PM"]["merge_status"] == "fully_merged"


def test_summarize_rej_prints_human_summary(tmp_path):
    targets = [
        _target("PA", "s1", "f.py", "ANCHOR_A", "REPL_A"),
        _target("PB", "s1", "f.py", "MISSING_ANCHOR", "R"),
        _target("PM", "s1", "f.py", "A1", "R1", markers=["def native_one"]),
    ]
    files = {"f.py": "x ANCHOR_A y A1 def native_one"}
    _, repo = _run_build(tmp_path, targets, files)
    pin_dir = _pin_dir(repo)
    r = subprocess.run([sys.executable, str(SUMMARIZE), str(pin_dir)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    assert "rejected by status:" in out
    assert "anchor_drift" in out
    assert "upstream_merged" in out
    assert "merge_status roll-up:" in out
    assert "fully_merged" in out
    assert "PB::s1" in out  # the genuine drift is named for re-anchoring


def test_summarize_rej_missing_file_exit_2(tmp_path):
    r = subprocess.run([sys.executable, str(SUMMARIZE), str(tmp_path / "nope")],
                       capture_output=True, text=True)
    assert r.returncode == 2


def test_summarize_rej_importable_helper():
    # the status-order constant covers the four statuses the task names
    spec = importlib.util.spec_from_file_location("_summarize_rej_t", SUMMARIZE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for s in ("anchor_drift", "upstream_merged", "ambiguous", "version_gated"):
        assert s in mod._STATUS_ORDER
