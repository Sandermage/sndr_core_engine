# SPDX-License-Identifier: Apache-2.0
"""Recurrence gate for the 2026-07-06 daemon-wiring incident.

The full-product compose's sndr-daemon must ship the config that makes the
GUI actually find the engine and persist memory. Both silently degrade if
dropped:
  - SNDR_ENGINE_API_KEY: without it the :8102 probe gets 401 -> "no engine".
  - GENESIS_MEMORY_DSN + a pgvector service + psycopg install: without any of
    them memory falls back to the ephemeral in-memory store -> GUI "Memory:
    Error Not Found" and data lost on every restart.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_COMPOSE = (
    Path(__file__).resolve().parents[3] / "compose" / "docker-compose.full.yml"
)


def _compose() -> dict:
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))


def test_daemon_carries_engine_key_and_url():
    env = _compose()["services"]["sndr-daemon"]["environment"]
    assert "SNDR_ENGINE_API_KEY" in env, "daemon must pass the engine API key"
    assert "SNDR_OPENAI_BASE_URL" in env, "daemon must point at the engine URL"


def test_daemon_wires_persistent_memory():
    d = _compose()
    env = d["services"]["sndr-daemon"]["environment"]
    assert "GENESIS_MEMORY_DSN" in env, "daemon must set the pgvector DSN"
    assert "memory-db" in d["services"], "a pgvector memory-db service must exist"
    assert "psycopg" in str(d["services"]["sndr-daemon"]["entrypoint"]), (
        "daemon entrypoint must pip-install psycopg (absent from the vLLM image)"
    )


def test_memory_db_is_pgvector_with_persistent_volume():
    d = _compose()
    mdb = d["services"]["memory-db"]
    assert "pgvector" in mdb["image"]
    assert d.get("volumes"), "memory-db needs a named volume for persistence"
