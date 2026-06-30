# SPDX-License-Identifier: Apache-2.0
"""Integration: MemoryHTTPClient against a live memory service (the external-model
path). Runs only when MEMORY_API_URL points at a running unified container, e.g.

    MEMORY_API_URL=http://192.168.1.10:8811 pytest tests/integration/test_memory_http_client.py

Verifies the exact flow the proxy uses for external models: remember/recall over
HTTP, and ConversationMemory augment/capture driving the remote engine.
"""
from __future__ import annotations

import os

import pytest

_API = os.environ.get("MEMORY_API_URL")
_KEY = os.environ.get("MEMORY_API_KEY")  # required if the server enforces auth
pytestmark = pytest.mark.skipif(not _API, reason="MEMORY_API_URL not set")


def test_http_client_remember_and_recall():
    from sndr.memory.client import MemoryHTTPClient

    client = MemoryHTTPClient(_API, owner_id=9001, token=_KEY)
    client.remember(owner_id=9001, text="the canary fact is xyzzy-42")
    hits = client.recall(owner_id=9001, query="canary fact", limit=5, reinforce=False)
    assert any("xyzzy-42" in h.node.content for h in hits)


def test_conversation_memory_over_http():
    from sndr.memory.client import MemoryHTTPClient
    from sndr.memory.middleware import ConversationMemory

    client = MemoryHTTPClient(_API, owner_id=9002, token=_KEY)
    cm = ConversationMemory(engine=client)
    cm.capture(owner_id=9002, messages=[{"role": "user", "content": "my port is 8811 exactly"}])
    out = cm.augment(owner_id=9002, messages=[{"role": "user", "content": "which port do I use"}])
    assert out[0]["role"] == "system"
    assert "8811" in out[0]["content"]
