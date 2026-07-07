# SPDX-License-Identifier: Apache-2.0
"""GROUP-CONFIG (2026-07-06) — install.sh CLIENT PROFILE + zero-config seams.

Bash-harness tests that RUN the real `install.sh` (in `--dry-run`, so no live
clone / pip / launch) and assert on stdout + emitted files:

  * a host with no `nvidia-smi` takes the CLIENT branch — CLI + GUI only, NO
    engine/plugin install — and emits a prefilled Section-B `.env`;
  * a faked-GPU host takes the LOCAL FULL-STACK branch — auto-copies a
    Section-A `.env` from `.env.example` and runs the host.yaml auto-init;
  * both are idempotent on re-run (DOWNLOAD-2) and dry-run safe (no `.git`).

The controlled PATH (only the real python3/git/curl symlinked in, plus an
optional fake nvidia-smi) makes GPU presence deterministic on any host — the
rig has a real nvidia-smi, a laptop does not; the harness decides.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = REPO_ROOT / "install.sh"
ENV_EXAMPLE = REPO_ROOT / ".env.example"


def _make_toolbin(tmp_path: Path, *, with_gpu: bool) -> Path:
    """Build a shim dir PREPENDED to the real PATH. It carries only an
    `nvidia-smi` shim so GPU presence is deterministic on any host (the rig
    has a real nvidia-smi; the shim always wins because it is first on PATH):
      * with_gpu=True  -> reports 2× RTX A5000
      * with_gpu=False -> reports NO GPUs (empty), so N_GPUS=0 -> client
    All other tools (cut/sed/git/python3/...) resolve via the inherited PATH.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    smi = bindir / "nvidia-smi"
    if with_gpu:
        smi.write_text('#!/bin/bash\nprintf "NVIDIA RTX A5000\\nNVIDIA RTX A5000\\n"\n')
    else:
        # Present but reports zero GPUs -> N_GPUS=0 -> client profile.
        smi.write_text('#!/bin/bash\nexit 0\n')
    smi.chmod(0o755)
    return bindir


def _run_installer(tmp_path: Path, args: list[str], *, with_gpu: bool,
                   extra_env: dict | None = None) -> subprocess.CompletedProcess:
    bindir = _make_toolbin(tmp_path, with_gpu=with_gpu)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    genesis_home = tmp_path / "genesis_home"
    genesis_home.mkdir(exist_ok=True)
    workdir = tmp_path / "work"
    workdir.mkdir(exist_ok=True)
    env = dict(os.environ)
    env.pop("SNDR_HOST_AUTOINIT", None)
    env.update({
        "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(home),
        "SNDR_HOME": str(genesis_home),
        "GENESIS_HOME": str(genesis_home),
    })
    if extra_env:
        env.update({k: str(v) for k, v in extra_env.items()})
    return subprocess.run(
        ["bash", str(INSTALL_SH), "--dry-run", "-y", *args],
        cwd=str(workdir),
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )


# ─── Client profile (no GPU) ───────────────────────────────────────────────


def test_no_gpu_takes_client_branch(tmp_path):
    """No nvidia-smi -> CLIENT branch: CLI+GUI only, Section-B .env emitted,
    NO engine/plugin install attempted, points at docs/RUN_ON_MAC.md."""
    r = _run_installer(tmp_path, [], with_gpu=False)
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    assert "client profile auto-selected" in out
    assert "engine cannot run here" in out
    assert "docs/RUN_ON_MAC.md" in out
    # Engine/plugin bits must NOT run.
    assert "Editable install" not in out
    assert "Generate launch script" not in out
    assert "generate_launch" not in out
    assert "clone/pip not run" in out

    env_file = (tmp_path / "work" / ".env")
    assert env_file.is_file(), "client profile must emit a .env"
    body = env_file.read_text()
    assert "SNDR_OPENAI_BASE_URL=" in body
    assert "SNDR_ENGINE_API_KEY=genesis-local" in body
    assert "GENESIS_MEMORY_DSN=" in body


def test_explicit_client_flag(tmp_path):
    """--client forces the client branch even where a GPU exists."""
    r = _run_installer(tmp_path, ["--client"], with_gpu=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "client profile (forced" in r.stdout
    assert (tmp_path / "work" / ".env").is_file()


def test_client_env_honors_rig_env(tmp_path):
    """A preset SNDR_OPENAI_BASE_URL is baked into the emitted .env."""
    r = _run_installer(
        tmp_path, ["--client"], with_gpu=False,
        extra_env={"SNDR_OPENAI_BASE_URL": "http://rig.local:8102/v1"},
    )
    assert r.returncode == 0, r.stdout + r.stderr
    body = (tmp_path / "work" / ".env").read_text()
    assert "SNDR_OPENAI_BASE_URL=http://rig.local:8102/v1" in body


def test_client_idempotent_rerun(tmp_path):
    """Re-running the client install leaves an existing .env untouched."""
    r1 = _run_installer(tmp_path, ["--client"], with_gpu=False)
    assert r1.returncode == 0
    env_file = tmp_path / "work" / ".env"
    original = env_file.read_text()
    # Second run: same tmp tree (so .env already exists in workdir).
    r2 = _run_installer(tmp_path, ["--client"], with_gpu=False)
    assert r2.returncode == 0
    assert "left untouched" in r2.stdout
    assert env_file.read_text() == original


# ─── Local full stack (faked GPU) ──────────────────────────────────────────


def test_faked_gpu_takes_full_stack_and_autocopies_env(tmp_path):
    """A GPU host takes the full-stack branch: auto-copy Section-A .env from
    .env.example + run host.yaml auto-init. Dry-run => no clone/pip."""
    genesis_home = tmp_path / "genesis_home"
    genesis_home.mkdir(exist_ok=True)
    shutil.copy(ENV_EXAMPLE, genesis_home / ".env.example")

    models = tmp_path / "models"
    models.mkdir()
    r = _run_installer(
        tmp_path, [], with_gpu=True,
        extra_env={"SNDR_MODELS_DIR": str(models)},
    )
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    assert "local full-stack profile" in out
    assert "engine cannot run here" not in out
    assert "Host paths auto-init" in out
    assert "seams exercised" in out

    env_file = genesis_home / ".env"
    assert env_file.is_file(), "full-stack path must auto-copy .env from example"
    # It is the Section-A scaffold (has the SECTION A banner), not Section-B.
    assert "SECTION A" in env_file.read_text()


def test_dry_run_is_safe_no_clone(tmp_path):
    """Dry-run performs no live clone: GENESIS_HOME has no .git."""
    r = _run_installer(tmp_path, [], with_gpu=False)
    assert r.returncode == 0
    assert not (tmp_path / "genesis_home" / ".git").exists()


def test_installer_script_syntax_valid():
    """`bash -n install.sh` — the script parses (guards the whole file)."""
    r = subprocess.run(["bash", "-n", str(INSTALL_SH)],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
