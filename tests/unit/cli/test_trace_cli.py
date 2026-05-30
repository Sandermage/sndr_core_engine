# SPDX-License-Identifier: Apache-2.0
"""Tests for `sndr trace list` — §6.H6 of the unified development plan.

Covers:
  * Static catalog output (no --container, both human and JSON).
  * --container with `docker` missing (fallback warning).
  * --container with mocked `docker exec` output (live size + mtime).
  * --category filter.
  * --all flag semantics (with --container).
  * Argparse wiring registered under the top-level `sndr` parser.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]


def _run(*args: str, env_extra: dict | None = None,
         text_in: str | None = None) -> subprocess.CompletedProcess:
    """Run `sndr trace ...` via the package's CLI entry."""
    import os
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "vllm.sndr_core.cli", "trace", *args],
        capture_output=True, text=True, cwd=REPO_ROOT,
        env=env, check=False, input=text_in,
    )


# ─── Argparse registration ───────────────────────────────────────────


def test_trace_subcommand_is_registered() -> None:
    """`sndr trace list --help` must surface our help text — proves the
    add_argparser() was wired into the root CLI."""
    r = _run("list", "--help")
    assert r.returncode == 0, r.stderr
    out = r.stdout
    # The subcommand's own --help renders its argparse options; the
    # description text only appears in the parent (sndr trace --help).
    # The args themselves are sufficient surface to lock.
    assert "--container" in out
    assert "--category" in out
    assert "--json" in out
    assert "--all" in out


def test_trace_top_help_lists_subcommands() -> None:
    r = _run("--help")
    assert r.returncode == 0
    assert "list" in r.stdout


# ─── Default catalog output ──────────────────────────────────────────


def test_list_human_view_lists_every_category_with_specs() -> None:
    r = _run("list")
    assert r.returncode == 0, r.stderr
    # Human view banner.
    assert "sndr trace — known diagnostic traces" in r.stdout
    # Every category that has specs prints its header.
    from vllm.sndr_core.observability.trace_catalog import iter_by_category
    grouped = iter_by_category()
    for cat, specs in grouped.items():
        if specs:
            assert cat.upper() in r.stdout, (
                f"category {cat!r} has specs but its header is missing "
                "from human view"
            )


def test_list_human_view_prints_total_line() -> None:
    r = _run("list")
    assert r.returncode == 0
    assert "Total:" in r.stdout


def test_list_json_payload_matches_catalog() -> None:
    r = _run("list", "--json")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    from vllm.sndr_core.observability.trace_catalog import TRACE_CATALOG
    assert payload["total"] == len(TRACE_CATALOG)
    assert payload["container"] is None
    assert payload["category_filter"] is None
    assert isinstance(payload["traces"], list)
    # Spot-check: every catalog entry surfaces by id.
    payload_ids = {t["id"] for t in payload["traces"]}
    catalog_ids = {s.id for s in TRACE_CATALOG}
    assert payload_ids == catalog_ids


def test_list_json_includes_live_field_as_null_without_container() -> None:
    r = _run("list", "--json")
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    for t in payload["traces"]:
        assert t["live"] is None


# ─── --category filter ───────────────────────────────────────────────


def test_list_category_filter_keeps_only_matching() -> None:
    r = _run("list", "--category", "boot", "--json")
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    assert payload["category_filter"] == "boot"
    assert all(t["category"] == "boot" for t in payload["traces"])
    assert payload["total"] >= 1  # boot always-on entry must be present


def test_list_category_invalid_returns_nonzero_with_message() -> None:
    r = _run("list", "--category", "not_a_category")
    assert r.returncode != 0
    # Either stderr or stdout — depends on the _io.error contract.
    combined = r.stdout + r.stderr
    assert "unknown category" in combined.lower()


# ─── --container with no docker available ────────────────────────────


def test_list_container_without_docker_emits_warning(monkeypatch) -> None:
    """The CLI must fall back to the static catalog with a clear warn
    when docker isn't on PATH — operators may run `sndr trace list`
    on a machine without docker."""
    # Force PATH to a single directory that has no docker.
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        # No docker binary in tmpdir.
        env_extra = {"PATH": tmpdir}
        r = _run("list", "--container", "fake-container",
                 env_extra=env_extra)
    assert r.returncode == 0
    combined = r.stdout + r.stderr
    assert ("docker binary not on $PATH" in combined or
            "docker exec" in combined.lower()), combined


def test_list_container_without_docker_json_carries_warning() -> None:
    """In JSON mode the warning must surface in the
    `container_warning` field so machine consumers can branch on it."""
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        env_extra = {"PATH": tmpdir}
        r = _run("list", "--container", "fake-container", "--all", "--json",
                 env_extra=env_extra)
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    assert payload["container"] == "fake-container"
    assert isinstance(payload["container_warning"], str)
    assert "docker" in payload["container_warning"].lower()


# ─── Live container introspection via mocked docker ──────────────────


def test_container_ls_parses_typical_row(monkeypatch) -> None:
    """Unit-test the parser directly so the contract is locked even
    when no live container is reachable from the test env."""
    import vllm.sndr_core.cli.trace as tmod

    typical_ls_output = (
        "total 12\n"
        "drwxrwxrwt 1 root root  4096 2026-05-30 13:00:00.000000000 +0000 .\n"
        "drwxr-xr-x 1 root root  4096 2026-05-30 12:00:00.000000000 +0000 ..\n"
        "-rw-r--r-- 1 root root  1234 2026-05-30 14:00:00.000000000 +0000 "
        "genesis_pn248_acceptance_trace.log\n"
        "-rw-r--r-- 1 root root 99999 2026-05-30 14:30:00.000000000 +0000 "
        "genesis_boot.log\n"
        "-rw-r--r-- 1 root root    42 2026-05-30 14:31:00.000000000 +0000 "
        "unrelated.log\n"
    )

    class FakeRun:
        def __init__(self, stdout):
            self.stdout = stdout
            self.stderr = ""
            self.returncode = 0

    monkeypatch.setattr(tmod.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(
        tmod.subprocess, "run",
        lambda *a, **kw: FakeRun(typical_ls_output),
    )

    out = tmod._container_ls_tmp("any-container-name")
    assert "genesis_pn248_acceptance_trace.log" in out
    assert "genesis_boot.log" in out
    assert "unrelated.log" not in out, (
        "non-genesis files must be filtered out at parse time"
    )
    size, mtime = out["genesis_pn248_acceptance_trace.log"]
    assert size == 1234
    assert mtime.startswith("2026-05-30")


def test_container_ls_returns_empty_on_subprocess_error(monkeypatch) -> None:
    """Subprocess failures (timeout, exec error, container stopped)
    must surface as empty dict — never raise."""
    import vllm.sndr_core.cli.trace as tmod

    class FakeRun:
        returncode = 1
        stdout = ""
        stderr = "Error: container not running\n"

    monkeypatch.setattr(tmod.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(
        tmod.subprocess, "run", lambda *a, **kw: FakeRun()
    )
    assert tmod._container_ls_tmp("any") == {}


def test_container_ls_handles_timeout(monkeypatch) -> None:
    import vllm.sndr_core.cli.trace as tmod

    def raise_timeout(*a, **kw):
        raise tmod.subprocess.TimeoutExpired(cmd=a[0], timeout=10)

    monkeypatch.setattr(tmod.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(tmod.subprocess, "run", raise_timeout)
    assert tmod._container_ls_tmp("any") == {}


# ─── --all semantics ────────────────────────────────────────────────


def test_default_container_view_hides_absent_files(monkeypatch) -> None:
    """Without --all, the human view only lists traces actually present.
    Verified at the run_list level by stubbing _container_ls_tmp to
    return a single hit."""
    import vllm.sndr_core.cli.trace as tmod

    monkeypatch.setattr(
        tmod, "_container_ls_tmp",
        lambda c: {"genesis_boot.log": (12345, "2026-05-30 14:00:00 +0000")},
    )

    import argparse
    args = argparse.Namespace(
        trace_cmd="list", container="any", category=None, json=False,
        all=False, func=tmod.run_list,
    )
    # Capture stdout for the assertion.
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = tmod.run_list(args)
    assert rc == 0
    out = buf.getvalue()
    # Only `boot` shows up — all other traces are absent.
    assert "boot" in out
    assert "pn248_acceptance" not in out


def test_all_flag_shows_full_catalog_with_present_annotations(monkeypatch) -> None:
    import vllm.sndr_core.cli.trace as tmod

    monkeypatch.setattr(
        tmod, "_container_ls_tmp",
        lambda c: {"genesis_boot.log": (12345, "2026-05-30 14:00:00 +0000")},
    )

    import argparse
    args = argparse.Namespace(
        trace_cmd="list", container="any", category=None, json=False,
        all=True, func=tmod.run_list,
    )
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = tmod.run_list(args)
    assert rc == 0
    out = buf.getvalue()
    # boot is present.
    assert "12.1KB" in out or "12345" in out
    # pn248 is in catalog → header line still appears even though
    # its live file is absent.
    assert "pn248_acceptance" in out
    assert "(not present)" in out


# ─── fmt_size helper ────────────────────────────────────────────────


def test_fmt_size_renders_bytes_kb_mb() -> None:
    import vllm.sndr_core.cli.trace as tmod
    assert tmod._fmt_size(0) == "0B"
    assert tmod._fmt_size(1023) == "1023B"
    assert tmod._fmt_size(1024) == "1.0KB"
    assert tmod._fmt_size(1536) == "1.5KB"
    assert tmod._fmt_size(1024 * 1024) == "1.0MB"
    assert tmod._fmt_size(5 * 1024 * 1024) == "5.0MB"
    assert tmod._fmt_size(1024 * 1024 * 1024) == "1.0GB"
