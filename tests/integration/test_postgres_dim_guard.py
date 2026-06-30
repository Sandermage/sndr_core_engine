# SPDX-License-Identifier: Apache-2.0
"""Integration: PostgresStore fails fast on an embedding dim mismatch.

Runs only when MEMORY_TEST_DSN points at a live Postgres+pgvector.
"""
from __future__ import annotations

import os
import uuid

import pytest

_DSN = os.environ.get("MEMORY_TEST_DSN")
pytestmark = pytest.mark.skipif(not _DSN, reason="MEMORY_TEST_DSN not set")


def test_dim_mismatch_raises_clear_error():
    import psycopg

    from sndr.memory.postgres import PostgresStore

    schema = "dimtest_" + uuid.uuid4().hex[:10]
    try:
        s8 = PostgresStore(_DSN, dim=8, schema=schema)  # creates vector(8)
        s8.close()
        with pytest.raises(ValueError, match="dim mismatch"):
            PostgresStore(_DSN, dim=16, schema=schema)  # reuse schema, wrong dim
    finally:
        with psycopg.connect(_DSN, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
