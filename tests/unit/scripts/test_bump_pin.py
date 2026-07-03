# SPDX-License-Identifier: Apache-2.0
"""Unit tests for scripts/bump_pin.py — the pin-bump propagation helper."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


def _load():
    spec = importlib.util.spec_from_file_location("bump_pin", REPO / "scripts/bump_pin.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_parse_derives_all_handles_and_strips_rc():
    bp = _load()
    info = bp._parse("0.23.1rc1.dev714+g09663abde")
    assert info["pin"] == "0.23.1rc1.dev714+g09663abde"
    assert info["canonical"] == "dev714"
    assert info["sha_short"] == "09663abde"
    # anchor dir drops the rc suffix — matches sndr/engines/vllm/pins/0.23.1_<sha>
    assert info["anchor_dir"] == "0.23.1_09663abde"
    assert info["container"] == "vllm-35b-dev714"
    assert info["image"] == "vllm/vllm-openai:nightly-09663abde"


def test_anchor_dir_matches_the_committed_pin_dir():
    """The derived anchor dir for the current pin must be the one on disk —
    otherwise audit_pin_consistency's anchor-dir check can never pass."""
    bp = _load()
    from sndr import pins
    info = bp._parse(pins.current())
    assert (REPO / "sndr/engines/vllm/pins" / info["anchor_dir"]).is_dir(), (
        f"derived anchor dir {info['anchor_dir']} not found on disk")


def test_parse_rejects_malformed_pin():
    bp = _load()
    with pytest.raises(SystemExit):
        bp._parse("not-a-pin")


def test_sub_line_preserves_inline_comment():
    bp = _load()
    line = 'current: "0.23.1rc1.dev714+g09663abde"    # deployed pin\n'
    out = bp._sub_line(line, "current", "0.23.1rc1.dev777+gabc")
    assert '"0.23.1rc1.dev777+gabc"' in out
    assert "# deployed pin" in out  # trailing comment kept
