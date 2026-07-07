# SPDX-License-Identifier: Apache-2.0
"""Situation-doc presence + honesty gate.

The UX-simplification wave (2026-07-06) added four per-hardware "front door"
docs so a Mac / Windows / remote user is never left at a dead-end reading a
Linux-only quickstart. This gate makes the wave's contract executable so it
cannot silently rot:

  1. all four situation docs exist;
  2. every client-facing doc (Mac / Windows-WSL / remote) states the honest
     hardware truth — the engine needs **Linux + CUDA** — so nobody is
     promised a native-Mac / native-Windows engine;
  3. every client-facing doc shows the remote-client env (at least
     ``SNDR_OPENAI_BASE_URL``), and the canonical remote reference spells out
     the full triplet;
  4. each situation doc is reachable from BOTH the top-level ``README.md`` and
     the ``docs/README.md`` index (an unlinked doc is dead weight).
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_DOCS = _REPO / "docs"

# The four situation docs the wave introduced.
_SITUATION_DOCS = (
    "RUN_ON_LINUX.md",
    "RUN_ON_MAC.md",
    "RUN_ON_WINDOWS_WSL.md",
    "REMOTE_ENGINE.md",
)

# Docs whose whole point is: you are NOT on a Linux+CUDA box, drive a rig.
_CLIENT_DOCS = (
    "RUN_ON_MAC.md",
    "RUN_ON_WINDOWS_WSL.md",
    "REMOTE_ENGINE.md",
)

_TRIPLET = ("SNDR_OPENAI_BASE_URL", "SNDR_ENGINE_API_KEY", "GENESIS_MEMORY_DSN")


def test_situation_docs_exist():
    missing = [d for d in _SITUATION_DOCS if not (_DOCS / d).is_file()]
    assert not missing, f"missing situation docs: {missing}"


def test_client_docs_state_the_linux_cuda_truth():
    """No client doc may imply a native Mac/Windows engine."""
    bad = []
    for d in _CLIENT_DOCS:
        text = (_DOCS / d).read_text(encoding="utf-8")
        if "Linux + CUDA" not in text:
            bad.append(d)
    assert not bad, (
        "client docs must state the engine needs 'Linux + CUDA' verbatim: "
        f"{bad}"
    )


def test_client_docs_show_the_remote_base_url():
    bad = [
        d
        for d in _CLIENT_DOCS
        if "SNDR_OPENAI_BASE_URL" not in (_DOCS / d).read_text(encoding="utf-8")
    ]
    assert not bad, f"client docs missing SNDR_OPENAI_BASE_URL: {bad}"


def test_remote_engine_doc_documents_the_full_triplet():
    text = (_DOCS / "REMOTE_ENGINE.md").read_text(encoding="utf-8")
    missing = [k for k in _TRIPLET if k not in text]
    assert not missing, f"REMOTE_ENGINE.md missing triplet env vars: {missing}"


def test_situation_docs_linked_from_readme_and_docs_index():
    root_readme = (_REPO / "README.md").read_text(encoding="utf-8")
    docs_index = (_DOCS / "README.md").read_text(encoding="utf-8")
    unlinked = []
    for d in _SITUATION_DOCS:
        if d not in root_readme:
            unlinked.append(f"README.md -> {d}")
        if d not in docs_index:
            unlinked.append(f"docs/README.md -> {d}")
    assert not unlinked, f"situation docs not linked: {unlinked}"
