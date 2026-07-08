# SPDX-License-Identifier: Apache-2.0
"""CLI/client coherence: the brain-tier memory verbs must be reachable from the
terminal, not just the GUI/API.

Before this the `sndr mem` surface was remember/recall/search/stats only — an
operator could not consolidate, inspect a node's neighbours, forget a memory, or
import an Obsidian vault without hand-rolling HTTP. These four verbs close that
gap over the EXISTING API routes (POST /consolidate, GET /neighbors/{id},
DELETE /node/{id}, POST /import/obsidian).
"""
from __future__ import annotations

import argparse

import pytest

pytest.importorskip("pydantic")

from sndr.cli.commands import COMMAND_REGISTRY  # noqa: E402
from sndr.memory.client import MemoryHTTPClient  # noqa: E402


@pytest.fixture(autouse=True)
def _registry():
    from sndr.cli.main import build_parser

    build_parser()


# ── client methods construct the right (method, path, body) ───────────────────


def _spy_client():
    calls = []
    c = MemoryHTTPClient("http://x", owner_id=1)

    def fake_call(method, path, body=None, owner=None):
        calls.append((method, path, body, owner))
        # Return shapes the methods expect.
        if "consolidate" in path:
            return {"linked": 2, "communities": 1, "nodes": 5}
        if "neighbors" in path:
            return [{"id": 2, "rel": "similar_to", "weight": 0.9}]
        if "reflect" in path:
            return {"reflections": 2}
        if "export" in path:
            return {"notes": 5, "links": 6}
        if "import" in path:
            return {"notes": 3, "links": 4}
        return {"deleted": True, "id": 7}

    c._call = fake_call
    return c, calls


def test_client_consolidate_posts():
    c, calls = _spy_client()
    out = c.consolidate(owner_id=1, tau=0.7, k=5)
    assert out["communities"] == 1
    method, path, body, owner = calls[0]
    assert method == "POST"
    assert path.endswith("/memory/consolidate")
    assert body == {"tau": 0.7, "k": 5}


def test_client_neighbors_gets():
    c, calls = _spy_client()
    out = c.neighbors(owner_id=1, node_id=7)
    assert out[0]["rel"] == "similar_to"
    method, path, _body, _o = calls[0]
    assert method == "GET"
    assert path.endswith("/memory/neighbors/7")


def test_client_forget_deletes():
    c, calls = _spy_client()
    out = c.forget(owner_id=1, node_id=7)
    assert out["deleted"] is True
    method, path, _b, _o = calls[0]
    assert method == "DELETE"
    assert path.endswith("/memory/node/7")


def test_client_import_obsidian_posts_path():
    c, calls = _spy_client()
    out = c.import_obsidian(owner_id=1, path="MyVault")
    assert out["notes"] == 3
    method, path, body, _o = calls[0]
    assert method == "POST"
    assert path.endswith("/memory/import/obsidian")
    assert body == {"path": "MyVault"}


def test_client_reflect_posts():
    c, calls = _spy_client()
    out = c.reflect(owner_id=1, min_cluster=3, max_reflections=4)
    assert out["reflections"] == 2
    method, path, body, _o = calls[0]
    assert method == "POST"
    assert path.endswith("/memory/reflect")
    assert body == {"min_cluster": 3, "max_reflections": 4}


def test_client_export_obsidian_posts_path():
    c, calls = _spy_client()
    out = c.export_obsidian(owner_id=1, path="OutVault")
    assert out["notes"] == 5
    method, path, body, _o = calls[0]
    assert method == "POST"
    assert path.endswith("/memory/export/obsidian")
    assert body == {"path": "OutVault"}


# ── CLI verbs registered + wired to the client ────────────────────────────────


@pytest.mark.parametrize("verb", ["mem.consolidate", "mem.neighbors", "mem.forget", "mem.import", "mem.export", "mem.reflect"])
def test_verb_registered(verb):
    assert verb in COMMAND_REGISTRY


def _run_cli(verb: str, ns_extra: dict, fake):
    """Invoke a mem command with a faked client factory; return exit code."""
    import sndr.cli.commands.mem as m

    orig = m._make_client
    m._make_client = lambda args: fake
    try:
        base = {"url": None, "owner": None, "token": None}
        base.update(ns_extra)
        return COMMAND_REGISTRY[verb].execute(argparse.Namespace(**base))
    finally:
        m._make_client = orig


class _Fake:
    def __init__(self):
        self.seen = []

    def consolidate(self, **k):
        self.seen.append(("consolidate", k))
        return {"linked": 1, "communities": 1, "nodes": 3}

    def neighbors(self, **k):
        self.seen.append(("neighbors", k))
        return [{"id": 2, "rel": "similar_to", "weight": 0.9}]

    def forget(self, **k):
        self.seen.append(("forget", k))
        return {"deleted": True, "id": k.get("node_id")}

    def import_obsidian(self, **k):
        self.seen.append(("import_obsidian", k))
        return {"notes": 3, "links": 4}

    def export_obsidian(self, **k):
        self.seen.append(("export_obsidian", k))
        return {"notes": 5, "links": 6}

    def reflect(self, **k):
        self.seen.append(("reflect", k))
        return {"reflections": 2}


def test_cli_consolidate_invokes_client():
    f = _Fake()
    rc = _run_cli("mem.consolidate", {"tau": 0.8, "k": 10}, f)
    assert rc == 0
    assert f.seen[0][0] == "consolidate"


def test_cli_forget_invokes_client():
    f = _Fake()
    rc = _run_cli("mem.forget", {"node_id": 7}, f)
    assert rc == 0
    assert f.seen[0] == ("forget", {"owner_id": 1, "node_id": 7}) or f.seen[0][0] == "forget"


def test_cli_import_invokes_client():
    f = _Fake()
    rc = _run_cli("mem.import", {"path": "Vault"}, f)
    assert rc == 0
    assert f.seen[0][0] == "import_obsidian"


def test_cli_neighbors_invokes_client():
    f = _Fake()
    rc = _run_cli("mem.neighbors", {"node_id": 7}, f)
    assert rc == 0
    assert f.seen[0][0] == "neighbors"


def test_cli_export_invokes_client():
    f = _Fake()
    rc = _run_cli("mem.export", {"path": "OutVault"}, f)
    assert rc == 0
    assert f.seen[0][0] == "export_obsidian"


def test_cli_reflect_invokes_client():
    f = _Fake()
    rc = _run_cli("mem.reflect", {"min_cluster": 3, "max_reflections": 5}, f)
    assert rc == 0
    assert f.seen[0][0] == "reflect"
