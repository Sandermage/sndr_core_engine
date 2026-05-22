# SPDX-License-Identifier: Apache-2.0
"""Etap 4.3 (audit 2026-05-12): validation for
`GENESIS_PN26_SPARSE_V_LOG_EVERY` env parsing.

Previously the raw `int(os.environ[...])` call raised ValueError on
non-integer values, aborting PN26 apply() before any kernel hook was
installed. Operators with stale env settings saw a cryptic boot crash
instead of a fallback to the default log frequency.
"""
from __future__ import annotations

import logging

import pytest

from vllm.sndr_core.integrations.attention.turboquant import (
    pn26_sparse_v_kernel as M,
)


class TestParseLogEveryEnv:
    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("GENESIS_PN26_SPARSE_V_LOG_EVERY", raising=False)
        assert M._parse_log_every_env() == M._LOG_EVERY_DEFAULT

    def test_empty_string_uses_default(self, monkeypatch):
        monkeypatch.setenv("GENESIS_PN26_SPARSE_V_LOG_EVERY", "")
        assert M._parse_log_every_env() == M._LOG_EVERY_DEFAULT

    def test_valid_positive_int(self, monkeypatch):
        monkeypatch.setenv("GENESIS_PN26_SPARSE_V_LOG_EVERY", "250")
        assert M._parse_log_every_env() == 250

    def test_invalid_string_falls_back(self, monkeypatch, caplog):
        monkeypatch.setenv("GENESIS_PN26_SPARSE_V_LOG_EVERY", "abc")
        with caplog.at_level(logging.WARNING, logger="genesis"):
            value = M._parse_log_every_env()
        assert value == M._LOG_EVERY_DEFAULT
        assert any("invalid" in r.message.lower() for r in caplog.records)

    def test_zero_falls_back(self, monkeypatch, caplog):
        monkeypatch.setenv("GENESIS_PN26_SPARSE_V_LOG_EVERY", "0")
        with caplog.at_level(logging.WARNING, logger="genesis"):
            value = M._parse_log_every_env()
        assert value == M._LOG_EVERY_DEFAULT

    def test_negative_falls_back(self, monkeypatch, caplog):
        monkeypatch.setenv("GENESIS_PN26_SPARSE_V_LOG_EVERY", "-5")
        with caplog.at_level(logging.WARNING, logger="genesis"):
            value = M._parse_log_every_env()
        assert value == M._LOG_EVERY_DEFAULT
