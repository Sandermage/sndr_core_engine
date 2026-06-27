"""PART 1c — NEW-pin readiness orchestrator (new_pin_check.py).

Deterministic, host-runnable: operates only on committed manifests. Pins the
previous-pin resolver (the operator must NOT hand-pick OLD) and the readiness
flow (coverage -> summarize -> bump_preflight) end-to-end on synthetic pins.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ANCHOR_SOT = REPO / "scripts" / "anchor_sot"
NEW_PIN_CHECK = ANCHOR_SOT / "new_pin_check.py"


def _import():
    spec = importlib.util.spec_from_file_location("_new_pin_check", NEW_PIN_CHECK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pin_dir(base, name, pin, *, anchors_patches=None, rejected=None,
             coverage=None, breakage=None):
    d = base / name
    d.mkdir(parents=True)
    anchors = {"pins": {"vllm": pin},
               "files": {"f.py": {"patches": anchors_patches or {
                   "PA": {"anchors": {"s1": {"byte_offset": 1}}}}}}}
    rej = {
        "pin": pin,
        "coverage": coverage or {"discovered": 1, "ok": 1, "rejected": 0},
        "rejected": rejected or [],
        "dependency_breakage": breakage or {
            "high_count": 0, "medium_count": 0, "edges": []},
    }
    (d / "anchors.json").write_text(json.dumps(anchors))
    (d / "drift.rej.json").write_text(json.dumps(rej))
    return d


# ─── parse_pin / resolver ─────────────────────────────────────────────────────

def test_parse_pin_extracts_release_and_dev():
    mod = _import()
    assert mod.parse_pin("0.23.1rc1.dev424+g3f5a1e173") == ("0.23.1", 424)
    assert mod.parse_pin("0.21.1rc0+g626fa9bba566") == ("0.21.1", 0)
    assert mod.parse_pin("garbage") is None
    assert mod.parse_pin(None) is None


def test_resolve_previous_picks_highest_dev_below_new(tmp_path):
    mod = _import()
    pins = tmp_path / "pins"
    _pin_dir(pins, "0.23.1_aaa", "0.23.1rc1.dev148+gaaa111111")
    _pin_dir(pins, "0.23.1_bbb", "0.23.1rc1.dev301+gbbb222222")
    new = _pin_dir(pins, "0.23.1_ccc", "0.23.1rc1.dev424+gccc333333")
    prev = mod.resolve_previous_pin_dir(str(new), pins_dir=str(pins))
    assert prev is not None
    # previous of dev424 is dev301 (highest below), NOT dev148.
    assert mod._pin_of(prev) == "0.23.1rc1.dev301+gbbb222222"


def test_resolve_previous_none_for_first_pin_on_release(tmp_path):
    mod = _import()
    pins = tmp_path / "pins"
    new = _pin_dir(pins, "0.24.0_zzz", "0.24.0rc1.dev1+gzzz999999")
    _pin_dir(pins, "0.23.1_aaa", "0.23.1rc1.dev148+gaaa111111")  # other release
    assert mod.resolve_previous_pin_dir(str(new), pins_dir=str(pins)) is None


def test_most_recent_pin_dir_is_highest_dev(tmp_path):
    mod = _import()
    pins = tmp_path / "pins"
    _pin_dir(pins, "0.23.1_aaa", "0.23.1rc1.dev148+gaaa111111")
    newest = _pin_dir(pins, "0.23.1_ccc", "0.23.1rc1.dev424+gccc333333")
    _pin_dir(pins, "0.23.1_bbb", "0.23.1rc1.dev301+gbbb222222")
    assert mod.most_recent_pin_dir(pins_dir=str(pins)) == str(newest)


# ─── readiness flow ───────────────────────────────────────────────────────────

def _run(new_dir, *extra):
    return subprocess.run(
        [sys.executable, str(NEW_PIN_CHECK), str(new_dir), *extra],
        capture_output=True, text=True)


def test_clean_bump_is_ready(tmp_path):
    pins = tmp_path / "pins"
    _pin_dir(pins, "0.23.1_aaa", "0.23.1rc1.dev148+gaaa111111")
    new = _pin_dir(pins, "0.23.1_ccc", "0.23.1rc1.dev424+gccc333333")
    r = _run(new, "--old", str(pins / "0.23.1_aaa"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "RESULT: READY" in r.stdout
    assert "bump_preflight vs previous pin" in r.stdout


def test_broken_coverage_is_not_ready(tmp_path):
    pins = tmp_path / "pins"
    new = _pin_dir(pins, "0.23.1_ccc", "0.23.1rc1.dev424+gccc333333",
                   coverage={"discovered": 5, "ok": 1, "rejected": 1})
    r = _run(new)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "NOT READY" in r.stdout
    assert "coverage" in r.stdout.lower()


def test_first_pin_no_previous_is_ready(tmp_path):
    pins = tmp_path / "pins"
    new = _pin_dir(pins, "0.24.0_zzz", "0.24.0rc1.dev1+gzzz999999")
    r = _run(new)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "READY (first pin)" in r.stdout
    assert "SKIPPED" in r.stdout


def test_unmitigated_high_break_is_not_ready(tmp_path):
    """An unmitigated HIGH dependency break in the new pin's committed breakage
    (synthetic, registry-independent ids) makes the readiness verdict NOT READY
    — the orchestrator surfaces the bump_preflight failure."""
    pins = tmp_path / "pins"
    _pin_dir(pins, "0.23.1_aaa", "0.23.1rc1.dev148+gaaa111111",
             anchors_patches={"SYNDEP": {"anchors": {"a1": {"byte_offset": 1}}}})
    new = _pin_dir(
        pins, "0.23.1_ccc", "0.23.1rc1.dev424+gccc333333",
        anchors_patches={},
        rejected=[{"key": "SYNRET::s1", "status": "retired"}],
        breakage={
            "high_count": 1, "medium_count": 0,
            "edges": [{
                "retired": "SYNRET", "retired_reason": "retired",
                "dependent": "SYNDEP", "severity": "HIGH", "mitigated": False,
                "via": ["anchor_name", "anchor_text"],
                "dependent_category": "kernel_perf",
                "dependent_lifecycle": "experimental",
                "dependent_default_on": True,
                "detail": ("SYNDEP will skip/no-op — anchor targets the retired "
                           "patch's emitted bytes — physically no-ops (the PN399 "
                           "class)")}]})
    r = _run(new, "--old", str(pins / "0.23.1_aaa"))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "NOT READY" in r.stdout
    assert "SYNDEP" in r.stdout


def test_committed_pins_dev424_ready(tmp_path):
    """End-to-end on the REAL committed pins: dev424 readiness auto-resolves
    dev301 as previous and is READY (the PN353A->PN399 break is live-MITIGATED;
    the stale committed section is reconciled against the live registry)."""
    r = subprocess.run(
        [sys.executable, str(NEW_PIN_CHECK),
         str(REPO / "sndr/engines/vllm/pins/0.23.1_3f5a1e173")],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "RESULT: READY" in r.stdout
    assert "0.23.1rc1.dev301+g04c2a8dea" in r.stdout  # auto-resolved previous
