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


def test_sha_full_arg_updates_pins_yaml_line():
    """--sha-full must rewrite current_sha_full (dev748 promotion 2026-07-04
    caught bump_pin silently leaving the PREVIOUS pin's full sha in place —
    the script cannot derive the 40-char sha from the version string's short
    g-hash, so the operator passes it explicitly)."""
    bp = _load()
    line = 'current_sha_full: "09663abde0f50944a8d5ea30120666024b503faa"  # for git fetch@sha (CI drift)\n'
    out = bp._sub_line(line, "current_sha_full",
                       "2dfaae752b4db0d43cfc0715c780e33be030d0f1")
    assert '2dfaae752b4db0d43cfc0715c780e33be030d0f1' in out
    assert "# for git fetch@sha" in out


def test_sub_engine_pin_replaces_vllm_pin_only():
    """Preset engine_pin propagation (audit remediation 2026-07-05: the
    dev748 bump left preset engine_pin to a hand-fix). Only vLLM-shaped
    pins are rewritten — the llama.cpp lane's engine_pin (a llama.cpp
    build tag) must pass through untouched."""
    bp = _load()
    vllm_line = "    engine_pin: 0.23.1rc1.dev714+g09663abde        # validated vLLM build\n"
    out = bp._sub_engine_pin(vllm_line, "0.23.1rc1.dev777+gabcdef012")
    assert "0.23.1rc1.dev777+gabcdef012" in out
    assert "# validated vLLM build" in out
    llama_line = "    engine_pin: server-cuda-b9246                 # llama.cpp image build\n"
    assert bp._sub_engine_pin(llama_line, "0.23.1rc1.dev777+gabcdef012") == llama_line


def test_sub_image_digest_replaces_value_keeps_comment():
    """Hardware image_digest propagation (audit CRIT #1/#5: the digest is
    the highest-precedence image ref and was NOT in bump_pin's rewrite
    surface — every strict render booted the rollback engine)."""
    bp = _load()
    line = ("    image_digest: vllm/vllm-openai@sha256:" + "b" * 64 +
            "  # pinned digest\n")
    new = "vllm/vllm-openai@sha256:" + "a" * 64
    out = bp._sub_image_digest(line, new)
    assert new in out
    assert "# pinned digest" in out
    assert "b" * 64 not in out


def test_main_accepts_image_digest_flag():
    """CLI contract: --image-digest takes sha256:<64hex> or the full
    repo@sha256 form; malformed values are rejected before any writes."""
    bp = _load()
    rc = bp.main(["0.23.1rc1.dev748+g2dfaae752", "--dry-run",
                  "--image-digest",
                  "sha256:" + "a" * 64])
    assert rc == 0
    rc = bp.main(["0.23.1rc1.dev748+g2dfaae752", "--dry-run",
                  "--image-digest",
                  "vllm/vllm-openai@sha256:" + "a" * 64])
    assert rc == 0
    with pytest.raises(SystemExit):
        bp.main(["0.23.1rc1.dev748+g2dfaae752", "--dry-run",
                 "--image-digest", "not-a-digest"])


def test_dry_run_plan_covers_digest_and_presets(capsys):
    """The bump plan must enumerate the new propagation surfaces so the
    operator sees them in DRY mode: hardware digests + preset engine_pin."""
    bp = _load()
    bp.main(["0.23.1rc1.dev748+g2dfaae752", "--dry-run",
             "--image-digest", "sha256:" + "a" * 64])
    out = capsys.readouterr().out
    assert "hardware" in out.lower()
    assert "preset" in out.lower()


def test_default_pin_edit_rewrites_stale_audit_literal():
    """bump_pin must auto-maintain the DEFAULT_PIN last-ditch literal in
    scripts/audit_stale_vllm_version_ranges.py so 'auto-adapts to the fresh
    pin' is uniform (2026-07-05 integrity audit). Idempotent: a bump to the
    already-current pin yields no edit."""
    bp = _load()
    edit = bp._default_pin_edit("0.99.9rc1.dev999+gdeadbeef")
    assert edit is not None, "a new pin must produce a DEFAULT_PIN rewrite"
    path, txt = edit
    assert path.name == "audit_stale_vllm_version_ranges.py"
    assert 'DEFAULT_PIN = "0.99.9rc1.dev999+gdeadbeef"' in txt
    # idempotent — bumping to the value already in the file is a no-op
    from sndr import pins
    assert bp._default_pin_edit(pins.current()) is None


def test_dry_run_plan_mentions_default_pin(capsys):
    """The bump plan must surface the DEFAULT_PIN fallback update so the
    operator sees every propagated surface in DRY mode."""
    bp = _load()
    bp.main(["0.99.9rc1.dev999+gdeadbeef", "--dry-run"])
    out = capsys.readouterr().out.lower()
    assert "default_pin" in out or "default pin" in out


def test_main_accepts_sha_full_flag():
    """CLI contract: bump_pin.py <pin> --sha-full <40-hex> parses; a
    malformed value is rejected before any file writes."""
    bp = _load()
    # parse-only check via main --dry-run (no file writes)
    rc = bp.main(["0.23.1rc1.dev748+g2dfaae752", "--dry-run",
                  "--sha-full", "2dfaae752b4db0d43cfc0715c780e33be030d0f1"])
    assert rc == 0
    with pytest.raises(SystemExit):
        bp.main(["0.23.1rc1.dev748+g2dfaae752", "--dry-run",
                 "--sha-full", "not-a-sha"])
