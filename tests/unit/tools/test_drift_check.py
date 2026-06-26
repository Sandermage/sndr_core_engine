"""TASK 3 — tools/drift_check.py reads the authoritative anchors.json.

GAP 4: the daily drift job + tools/drift_check.py read pins/<pin>/manifest.yaml,
but the CURRENT pin (0.23.1_b4c80ec0f) ships only anchors.json -> the job
silently no-op'd on the live pin. drift_check.py now prefers anchors.json
(verified via the engine's md5_pristine + per-anchor-offset check) and keeps
manifest.yaml back-compat for older pins.

Drives the script via subprocess with --install-root / --repo-root pointing at
synthetic fixtures (no vLLM install required), asserting the exit code contract:
0 no drift, 1 drift, 2 invocation error.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DRIFT_CHECK = REPO / "tools" / "drift_check.py"


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _make_pin_dir(repo_root: Path, pin: str) -> Path:
    d = repo_root / "sndr" / "engines" / "vllm" / "pins" / pin
    d.mkdir(parents=True, exist_ok=True)
    return d


def _anchors_json_for(pin: str, rel: str, src: str, anchor: str) -> dict:
    """Build a minimal valid anchors.json recording one anchor in `src`."""
    sb = src.encode("utf-8")
    off = src.index(anchor)
    ab = anchor.encode("utf-8")
    return {
        "manifest_version": 1,
        "generated_at": "2026-01-01T00:00:00Z",
        "generated_by": "test",
        "pins": {"vllm": pin, "genesis": "g"},
        "files": {
            rel: {
                "md5_pristine": _md5(src),
                "size_bytes": len(sb),
                "patches": {
                    "PT": {
                        "merge_status": "not_merged",
                        "anchors": {
                            "s1": {
                                "byte_offset": off,
                                "byte_length": len(ab),
                                "anchor_md5": hashlib.md5(ab).hexdigest(),
                            }
                        },
                    }
                },
            }
        },
    }


def _run(repo_root: Path, install_root: Path, pin: str):
    return subprocess.run(
        [sys.executable, str(DRIFT_CHECK), "--engine", "vllm", "--pin", pin,
         "--install-root", str(install_root), "--repo-root", str(repo_root)],
        capture_output=True, text=True,
    )


# ─── anchors.json path (the authoritative format the live pin ships) ────


def test_anchors_json_no_drift_exit_0(tmp_path):
    pin = "0.23.1_b4c80ec0f"
    rel = "model_executor/foo.py"
    src = "import x\nANCHOR_HERE = 1\ny = 2\n"
    repo, install = tmp_path / "repo", tmp_path / "install"
    pin_dir = _make_pin_dir(repo, pin)
    (pin_dir / "anchors.json").write_text(
        json.dumps(_anchors_json_for(pin, rel, src, "ANCHOR_HERE = 1")))
    # live install matches the manifest exactly -> no drift
    fpath = install / rel
    fpath.parent.mkdir(parents=True, exist_ok=True)
    fpath.write_text(src)

    r = _run(repo, install, pin)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "no drift detected" in r.stdout
    assert "anchors.json" in r.stdout


def test_anchors_json_drift_exit_1(tmp_path):
    pin = "0.23.1_b4c80ec0f"
    rel = "model_executor/foo.py"
    src = "import x\nANCHOR_HERE = 1\ny = 2\n"
    repo, install = tmp_path / "repo", tmp_path / "install"
    pin_dir = _make_pin_dir(repo, pin)
    (pin_dir / "anchors.json").write_text(
        json.dumps(_anchors_json_for(pin, rel, src, "ANCHOR_HERE = 1")))
    # live install MUTATED -> md5_pristine mismatch -> drift
    fpath = install / rel
    fpath.parent.mkdir(parents=True, exist_ok=True)
    fpath.write_text("import x\nANCHOR_HERE = 999\ny = 2\n")

    r = _run(repo, install, pin)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "DRIFT DETECTED" in r.stdout


def test_anchors_json_missing_file_exit_1(tmp_path):
    pin = "0.23.1_b4c80ec0f"
    rel = "model_executor/foo.py"
    src = "ANCHOR_HERE = 1\n"
    repo, install = tmp_path / "repo", tmp_path / "install"
    pin_dir = _make_pin_dir(repo, pin)
    (pin_dir / "anchors.json").write_text(
        json.dumps(_anchors_json_for(pin, rel, src, "ANCHOR_HERE = 1")))
    install.mkdir(parents=True, exist_ok=True)  # file NOT present in install

    r = _run(repo, install, pin)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "missing" in r.stdout.lower()


# ─── manifest.yaml back-compat path (older pins) ───────────────────────


def test_manifest_yaml_backcompat_no_drift_exit_0(tmp_path):
    pin = "0.22.1_da1daf40b"
    rel = "v1/foo.py"
    src = "legacy file contents\n"
    repo, install = tmp_path / "repo", tmp_path / "install"
    pin_dir = _make_pin_dir(repo, pin)
    (pin_dir / "manifest.yaml").write_text(
        "engine: vllm\n"
        f"pin: {pin}\n"
        "files:\n"
        f"  {rel}:\n"
        f"    md5: {_md5(src)}\n"
        f"    size_bytes: {len(src.encode())}\n"
        "    anchors: {}\n"
    )
    fpath = install / rel
    fpath.parent.mkdir(parents=True, exist_ok=True)
    fpath.write_text(src)

    r = _run(repo, install, pin)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "manifest.yaml" in r.stdout


def test_manifest_yaml_backcompat_drift_exit_1(tmp_path):
    pin = "0.22.1_da1daf40b"
    rel = "v1/foo.py"
    repo, install = tmp_path / "repo", tmp_path / "install"
    pin_dir = _make_pin_dir(repo, pin)
    (pin_dir / "manifest.yaml").write_text(
        "engine: vllm\n"
        f"pin: {pin}\n"
        "files:\n"
        f"  {rel}:\n"
        f"    md5: {_md5('original')}\n"
        "    size_bytes: 8\n"
        "    anchors: {}\n"
    )
    fpath = install / rel
    fpath.parent.mkdir(parents=True, exist_ok=True)
    fpath.write_text("MUTATED contents")

    r = _run(repo, install, pin)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "DRIFT DETECTED" in r.stdout


# ─── invocation error (no manifest at all) ─────────────────────────────


def test_no_manifest_exit_2(tmp_path):
    pin = "9.9.9_deadbeef"
    repo, install = tmp_path / "repo", tmp_path / "install"
    _make_pin_dir(repo, pin)  # empty pin dir, no manifest
    install.mkdir(parents=True, exist_ok=True)

    r = _run(repo, install, pin)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "no manifest" in (r.stdout + r.stderr).lower()
