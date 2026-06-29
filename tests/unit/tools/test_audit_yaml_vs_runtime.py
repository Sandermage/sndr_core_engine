# SPDX-License-Identifier: Apache-2.0
"""Regression guard for ``tools/audit_yaml_vs_runtime.sh`` V2-preset resolution.

The drift tool used to extract a config's ``genesis_env`` by grepping
``^\\s+GENESIS_`` straight out of the YAML file. That worked for the old
monolithic configs but yields **zero** keys for a V2 *composed* preset
(``prod-qwen3.6-35b-balanced.yaml`` is a thin resolver that references
``model`` / ``hardware`` / ``profile`` — the actual ``GENESIS_*`` flags are
composed at launch time). Zero keys silently turned the audit into a false
"all-drift" report AND, worse, made the dangerous direction (YAML enables X,
container lacks it) impossible to ever detect — the safety net was broken.

The tool now resolves the EFFECTIVE env the way the launcher does
(``sndr launch --dry-run <key>``) when the inline grep finds nothing. This test
exercises that path through the tool's ``--dump-config-keys`` mode (no docker /
ssh needed) and asserts a V2 preset resolves to its full composed flag set.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[3]
_TOOL = _REPO / "tools" / "audit_yaml_vs_runtime.sh"
_V2_PRESET = _REPO / "sndr/model_configs/builtin/presets/prod-qwen3.6-35b-balanced.yaml"


def _dump_keys(yaml_path: pathlib.Path) -> tuple[list[str], str]:
    proc = subprocess.run(
        ["bash", str(_TOOL), "--dump-config-keys", str(yaml_path)],
        capture_output=True, text=True, timeout=180, cwd=str(_REPO),
    )
    keys = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip().startswith("GENESIS_")]
    return keys, proc.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
@pytest.mark.skipif(not _TOOL.is_file(), reason="audit tool missing")
@pytest.mark.skipif(not _V2_PRESET.is_file(), reason="V2 preset fixture missing")
def test_dump_config_keys_resolves_v2_composed_preset():
    """A V2 composed preset must resolve to its full effective genesis_env —
    NOT zero keys (the false-'all drift' regression)."""
    # sndr must be importable for the dry-run resolution the tool falls back to.
    pytest.importorskip("sndr.model_configs.compose")

    keys, stderr = _dump_keys(_V2_PRESET)

    assert len(keys) > 50, (
        f"V2 preset resolved to only {len(keys)} GENESIS_ keys — the tool is "
        f"grepping the thin resolver instead of composing the effective env.\n"
        f"stderr: {stderr[:500]}"
    )
    names = {k.split("=", 1)[0] for k in keys}
    # P67 (TurboQuant multi-query KV kernel) is the canonical 35B tune — a stable
    # anchor that proves the composed profile env came through, not just any text.
    assert "GENESIS_ENABLE_P67_TQ_MULTI_QUERY_KERNEL" in names
