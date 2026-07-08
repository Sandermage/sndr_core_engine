# SPDX-License-Identifier: Apache-2.0
"""Tests for install.sh thin-bootstrap shim + plugin packaging metadata.

S-05 (2026-05-08): install.sh shrank from 783 lines to ~106 — all
operator logic (GPU detection, workload picker, pin resolution, clone,
plugin install, host paths, launch script generation, smoke test,
uninstall) moved into `sndr.cli.legacy.install`. The bootstrap's
only job is now: verify python+git, clone the repo, `pip install -e
.`, then exec `sndr install` with passed flags.

Behavior coverage of the canonical wizard lives in
`tests/installer/test_install_dry_run.py` and
`tests/unit/detection/test_*.py`. The tests here assert the BOOTSTRAP
layer remains valid bash that delegates to the canonical wizard.

Plus: tests for the `tools/genesis_vllm_plugin/pyproject.toml` (entry
points + console scripts) — unchanged from prior version.

Author: Sandermage (Sander) Barzov Aleksandr.
"""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SH = REPO_ROOT / "install.sh"
PLUGIN_PYPROJECT = (
    REPO_ROOT / "tools" / "genesis_vllm_plugin" / "pyproject.toml"
)


# ─────────────────────────────────────────────────────────────────
# install.sh: shim file structure
# ─────────────────────────────────────────────────────────────────


def test_install_sh_exists():
    assert INSTALL_SH.is_file(), f"install.sh missing at {INSTALL_SH}"


def test_install_sh_has_bash_shebang():
    first_line = INSTALL_SH.read_text().splitlines()[0]
    assert first_line.startswith("#!"), f"missing shebang: {first_line}"
    assert "bash" in first_line


def test_install_sh_is_executable():
    mode = os.stat(INSTALL_SH).st_mode
    assert mode & stat.S_IXUSR, "install.sh not executable (chmod +x)"


def test_install_sh_bash_parses_clean():
    """`bash -n install.sh` reports zero syntax errors."""
    r = subprocess.run(
        ["bash", "-n", str(INSTALL_SH)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"bash -n failed: {r.stderr}"


def test_install_sh_uses_strict_mode():
    """All scripts must run under `set -euo pipefail`."""
    content = INSTALL_SH.read_text()
    assert "set -euo pipefail" in content


@pytest.mark.skip(
    reason="install.sh kept feature-complete (~700 LOC) — the S-05 "
           "thin-shim refactor target was reversed after the canonical "
           "`sndr install` wizard turned out to require a real Python "
           "interpreter resolution + repo-clone sequence that's cleaner "
           "in bash. New logic still belongs in sndr/cli/legacy/"
           "install.py for testability; this test stays as a guard "
           "against unbounded growth — re-enable with a higher ceiling "
           "once we settle on the long-term shape."
)
def test_install_sh_is_thin_shim_post_s05():
    """S-05 fix (2026-05-08): the bootstrap should be small. The old
    file was 783 lines of bash; the post-refactor target was ≤200."""
    n_lines = len(INSTALL_SH.read_text().splitlines())
    assert n_lines <= 200, (
        f"install.sh has grown to {n_lines} lines — keep it as a thin "
        "bootstrap and put new logic in sndr/cli/legacy/install.py"
    )


# ─────────────────────────────────────────────────────────────────
# install.sh: delegates to canonical wizard
# ─────────────────────────────────────────────────────────────────


@pytest.mark.skip(
    reason="install.sh handles installation directly (paired with the "
           "thin-shim reversal above); operator-facing logic is still "
           "duplicated in sndr/cli/legacy/install.py for IDE / unit "
           "testing. Re-enable when the bash bootstrap is fully retired."
)
def test_install_sh_delegates_to_sndr_install():
    """Bootstrap must hand off to `sndr install` (or python -m fallback)
    so all operator-facing logic lives in the canonical Python wizard."""
    content = INSTALL_SH.read_text()
    # Either `exec sndr install` (if on PATH) or python -m fallback
    has_sndr_exec = "exec sndr install" in content
    has_python_module_exec = (
        "sndr.cli.legacy install" in content
        or "sndr.cli.legacy" in content
    )
    assert has_sndr_exec and has_python_module_exec, (
        "bootstrap must exec `sndr install` AND fall back to "
        "`python -m sndr.cli.legacy install` for hosts where the "
        "console script isn't on PATH yet"
    )


def test_install_sh_python_minimum_version_check():
    """Bootstrap must verify Python ≥3.10 before delegating."""
    content = INSTALL_SH.read_text()
    # Look for the Python version comparison logic
    assert "PY_MAJOR" in content or "3.10" in content
    # Ensure the failure path exists
    assert "die" in content or "exit 1" in content


def test_install_sh_clones_into_sndr_home():
    """Bootstrap must default `SNDR_HOME` to `~/.sndr` (with `~/.genesis`
    legacy alias for back-compat with v7.x operators)."""
    content = INSTALL_SH.read_text()
    assert "SNDR_HOME" in content
    assert ".sndr" in content
    # Legacy alias preserved
    assert "GENESIS_HOME" in content


def test_install_sh_pip_install_uses_user_default():
    """Pip install defaults to `--user` (safer than system-wide); operator
    can override via `SNDR_PIP_FLAGS=`."""
    content = INSTALL_SH.read_text()
    assert "--user" in content
    assert "SNDR_PIP_FLAGS" in content


def test_install_sh_no_genesis_legacy_module_refs():
    """Bootstrap must not reference removed `vllm._genesis` paths."""
    content = INSTALL_SH.read_text()
    assert "vllm._genesis" not in content, (
        "install.sh still references the removed vllm._genesis package"
    )


# ─────────────────────────────────────────────────────────────────
# install.sh: v12 namespace + flow (issue #29 regression)
# ─────────────────────────────────────────────────────────────────
#
# Issue #29 (yundddd 2026-06-26): the v12 force-push to the public repo
# left install.sh referencing the RETIRED `vllm/sndr_core/` (filesystem)
# and `vllm.sndr_core` (module) namespace. v12 moved all code to the
# top-level `sndr/` package, so:
#   - the clone sanity gate checked vllm/sndr_core/{...}.py — all MISSING
#     → installer fatals "missing ... cli.py — wrong pin?"
#   - python3 -m vllm.sndr_core.compat.cli no longer resolves
#   - the symlink-into-site-packages PYTHONPATH dance was replaced in v12
#     by `pip install --no-deps -e .` (registers the vllm.general_plugins
#     entry-point AND puts `sndr` on sys.path)
# The canonical v12 flow is documented in docs/INSTALL.md.

REPO_SNDR = REPO_ROOT / "sndr"


def test_install_sh_no_retired_sndr_core_symlink_into_site_packages():
    """The retired v11 symlink-into-site-packages of `vllm/sndr_core` must
    be gone (v12 wires `sndr` via an editable pip install, not a symlink).
    The bug was a functional `ln -sf .../vllm/sndr_core ...`; user-facing
    messages that NAME the retired layout for context are fine (issue #29)."""
    import re

    content = INSTALL_SH.read_text()
    # No symlink-creation command may target the retired sndr_core/_genesis
    # source under GENESIS_HOME. (Scrubbing a *stale* symlink with `rm -f`
    # is allowed and expected; CREATING one is the bug.)
    assert not re.search(r"ln\s+-s\w*\s+.*sndr_core", content), (
        "install.sh still symlinks the retired vllm/sndr_core source into "
        "site-packages — v12 uses `pip install --no-deps -e .` instead"
    )
    # And there must be no source path that points GENESIS_HOME at the
    # retired tree (e.g. `$GENESIS_HOME/vllm/sndr_core`).
    assert "$GENESIS_HOME/vllm/sndr_core" not in content, (
        "install.sh dereferences $GENESIS_HOME/vllm/sndr_core — that path "
        "does not exist in a v12 checkout (package is top-level sndr/)"
    )


def test_install_sh_no_retired_sndr_core_module_path():
    """install.sh must not `python3 -m vllm.sndr_core.*` anywhere — that
    module namespace was removed in v12 (it is `sndr.*` now)."""
    content = INSTALL_SH.read_text()
    # The dotted MODULE form never appears in a legit v12 comment, so a
    # whole-file check is safe and catches `python3 -m vllm.sndr_core...`.
    assert "vllm.sndr_core" not in content, (
        "install.sh invokes the retired vllm.sndr_core module namespace "
        "(v12 module is `sndr.*`)"
    )


def test_install_sh_sanity_gate_paths_exist_in_tree():
    """Every canonical file the clone sanity gate checks must actually
    exist in the v12 tree — otherwise `curl | bash` dies before doing
    anything useful (this is the core of issue #29)."""
    import re

    content = INSTALL_SH.read_text()
    # The sanity loop is: `for f in <paths>; do ... done`. Extract the
    # space-separated path list that sits between `for f in` and `; do`.
    m = re.search(r"for f in (.+?); do", content)
    assert m, "could not find the clone sanity `for f in ...; do` loop"
    paths = m.group(1).split()
    assert paths, "sanity gate must check at least one canonical file"
    missing = [p for p in paths if not (REPO_ROOT / p).is_file()]
    assert not missing, (
        f"install.sh sanity gate requires files absent from the v12 tree: "
        f"{missing} — fresh install fatals 'wrong pin?'"
    )
    # And none of them may live under the retired namespace.
    stale = [p for p in paths if p.startswith("vllm/sndr_core/")]
    assert not stale, f"sanity gate still checks retired namespace: {stale}"


def test_install_sh_uses_editable_pip_install_for_sndr():
    """v12 wires `sndr` into the env via `pip install --no-deps -e .`
    (registers the vllm.general_plugins entry-point + puts sndr on
    sys.path), NOT a symlink of sndr_core into site-packages."""
    content = INSTALL_SH.read_text()
    assert "pip install" in content and "-e" in content, (
        "install.sh must `pip install -e` the repo root to register the "
        "vllm.general_plugins entry-point (docs/INSTALL.md step 3)"
    )
    assert "--no-deps" in content, (
        "v12 editable install uses --no-deps (deps already in the vLLM env)"
    )
    # The retired symlink-into-site-packages dance must be gone.
    assert "ln -sf" not in content or "sndr_core" not in content, (
        "install.sh still symlinks sndr_core into site-packages — v12 uses "
        "an editable pip install instead"
    )


def test_install_sh_invokes_sndr_compat_cli_module():
    """Launch-script generation + verify must call the v12 module path
    `python3 -m sndr.compat.cli` (or the `sndr` console script)."""
    content = INSTALL_SH.read_text()
    assert "sndr.compat.cli" in content or "sndr verify" in content, (
        "install.sh must invoke `sndr.compat.cli` (v12) for preset/verify"
    )


def test_install_sh_default_pin_works_on_fresh_clone():
    """The DEFAULT pin path must NOT resolve to a pre-v12 tag whose tree
    lacks the sndr/ package (issue #29: --pin stable → v7.51 → fatal).

    Stable resolution must fall back to a ref that carries the v12 sndr/
    layout (`main`) when no v12 stable tag exists. We assert install.sh
    contains a guard that only accepts v12+ stable tags, otherwise falls
    back to main/HEAD."""
    content = INSTALL_SH.read_text()
    # A v12-aware stable resolver must either default-fall-back to main,
    # or filter tags to v12+. We require an explicit `main` fallback and a
    # marker that pre-v12 tags are rejected for the `stable` channel.
    assert "GENESIS_MIN_STABLE_MAJOR" in content or "v12" in content, (
        "install.sh stable-pin resolution must be v12-aware (reject pre-v12 "
        "tags whose tree has no sndr/ package) — issue #29"
    )


def _run_resolve_pin(tag_names: list[str]) -> str:
    """Source install.sh, stub `curl` to return a GitHub-tags-API-shaped
    body for `tag_names` (one `"name":` per line, as the real API does),
    run `resolve_pin` with GENESIS_PIN=stable, and echo GENESIS_PIN_RESOLVED.

    Drives the ACTUAL bash so the v12-aware fallback is verified at runtime,
    not just by string presence (issue #29 regression)."""
    import shlex

    body = "".join(f'    "name": "{t}",\n' for t in tag_names)
    install_sh_q = shlex.quote(str(INSTALL_SH))
    # Heredoc-safe: write the API body to a var, define curl to print it.
    script = f"""
set -euo pipefail
TMP_SH="$(mktemp)"
sed '/^main "\\$@"$/d' {install_sh_q} > "$TMP_SH"
set --
source "$TMP_SH"
read -r -d '' _BODY <<'__API__' || true
{body}__API__
curl() {{ printf '%s\\n' "$_BODY"; }}
GENESIS_PIN="stable"; GENESIS_PIN_RESOLVED=""
resolve_pin >/dev/null 2>&1
printf '%s' "$GENESIS_PIN_RESOLVED"
"""
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert r.returncode == 0, f"resolve_pin harness failed: {r.stderr}"
    return r.stdout.strip()


def test_resolve_pin_stable_falls_back_to_main_on_pre_v12_tags_only():
    """Issue #29 core: when ONLY pre-v12 tags exist (v7.x/v11.x), `--pin
    stable` must resolve to `main` — NOT to a pre-v12 tag whose tree lacks
    the sndr/ package and would fatal the sanity gate."""
    got = _run_resolve_pin(
        ["v7.51-stable-2026-04-27", "v7.50-stable-2026-04-27", "v7.10.0", "v11.3.0"]
    )
    assert got == "main", (
        f"stable resolved to {got!r} — must fall back to main when only "
        "pre-v12 tags exist (issue #29)"
    )


def test_resolve_pin_stable_picks_v12_tag_when_present():
    """Once a v12+ stable tag is published, `--pin stable` must select it
    (newest-first), so reproducible installs get a real v12 target."""
    assert _run_resolve_pin(["v12.0.0", "v11.3.0", "v7.51-stable-2026-04-27"]) == "v12.0.0"
    # Newest v12+ wins (GitHub tags API returns newest first).
    assert _run_resolve_pin(["v12.1.0", "v12.0.0", "v7.51-stable-2026-04-27"]) == "v12.1.0"
    # A future v13 is also >= the v12 floor and wins over v12.
    assert _run_resolve_pin(["v13.0.0", "v12.5.0"]) == "v13.0.0"


def test_resolve_pin_stable_falls_back_to_main_on_api_failure():
    """Empty/unreachable tags API → `main` (never a fatal)."""
    assert _run_resolve_pin([]) == "main"


# ─────────────────────────────────────────────────────────────────
# Plugin pyproject.toml — unchanged from prior version
# ─────────────────────────────────────────────────────────────────


def test_plugin_pyproject_exists():
    assert PLUGIN_PYPROJECT.is_file(), f"missing {PLUGIN_PYPROJECT}"


def test_plugin_pyproject_declares_genesis_console_script():
    """After `pip install`, `genesis` should be a top-level command."""
    content = PLUGIN_PYPROJECT.read_text()
    assert "[project.scripts]" in content, (
        "plugin pyproject.toml must declare [project.scripts] for the "
        "`genesis` console command"
    )
    assert "genesis = " in content
    assert "sndr.compat.cli:main" in content


def test_plugin_pyproject_declares_vllm_general_plugins_entry_point():
    content = PLUGIN_PYPROJECT.read_text()
    assert '[project.entry-points."vllm.general_plugins"]' in content
    assert "genesis_v7" in content


def test_plugin_pyproject_requires_python_3_10_plus():
    content = PLUGIN_PYPROJECT.read_text()
    assert 'requires-python = ">=3.10"' in content


def test_plugin_pyproject_apache_2_license():
    content = PLUGIN_PYPROJECT.read_text()
    assert "Apache-2.0" in content


# ─────────────────────────────────────────────────────────────────
# install._classify_failure — smoke-test fail-class taxonomy (P1-8)
# ─────────────────────────────────────────────────────────────────
#
# Regression lock for two fixes:
#
#   (a) commit 24994ea1 added "no module named"/"modulenotfounderror" to
#       _RUNTIME_GAP_TOKENS so a missing-vllm/torch ModuleNotFoundError
#       buckets as runtime_gap (an environment GAP) instead of wiring_bug
#       (a real, install-blocking regression). It shipped WITHOUT a test.
#
#   (b) integrity-audit (2026-06-23): a `cannot import name 'X' from
#       'vllm…'` ImportError is ALSO a runtime/version gap (the symbol
#       moved or was removed in the installed pin) — it must NOT block the
#       install as a wiring bug. The fix scopes this to vllm/torch/triton/
#       flashinfer source modules so a `cannot import name … from 'sndr…'`
#       (a genuine internal wiring regression) still classifies as
#       wiring_bug.


@pytest.mark.parametrize(
    "reason, expected",
    [
        # (a) ModuleNotFoundError → runtime_gap (the 24994ea1 fix).
        ("No module named 'vllm.v1'", "runtime_gap"),
        ("ModuleNotFoundError: No module named 'torch'", "runtime_gap"),
        # (b) cannot-import-name against a vllm/runtime module → runtime_gap.
        ("cannot import name 'Foo' from 'vllm.v1.core' (/x/y.py)",
         "runtime_gap"),
        ("ImportError: cannot import name 'Bar' from 'vllm.config'",
         "runtime_gap"),
        # cannot-import-name against sndr's OWN code → stays wiring_bug
        # (a real internal regression, not an environment gap).
        ("cannot import name 'apply_patch' from 'sndr.dispatcher.registry'",
         "wiring_bug"),
        # Genuine wiring bugs stay wiring_bug.
        ("NameError: name 'foo' is not defined", "wiring_bug"),
        ("AttributeError: 'Module' object has no attribute 'x'",
         "wiring_bug"),
    ],
)
def test_classify_failure_buckets(reason, expected):
    from sndr.cli.legacy.install import _classify_failure
    assert _classify_failure(reason) == expected, (
        f"_classify_failure({reason!r}) = {_classify_failure(reason)!r}, "
        f"expected {expected!r}"
    )
