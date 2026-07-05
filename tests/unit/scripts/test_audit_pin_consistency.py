# SPDX-License-Identifier: Apache-2.0
"""Unit tests for scripts/audit_pin_consistency.py — the cross-artifact gate.

Born from the 2026-07-04 post-release audit CRIT finding: all 3 hardware YAMLs
carried the ROLLBACK pin's image_digest while `image:` said dev748. Because
`effective_image_ref()` gives the digest precedence ("digest wins"), every
rendered launcher booted the rollback engine — and NO gate audited the digest
(audit_pin_consistency covered strings only, R-PIN-2 checked presence/format
only). These tests pin the new invariant: the highest-precedence pin artifact
(image_digest) must match the SSOT current pin digest.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

_DIGEST_RE = re.compile(r"^vllm/vllm-openai@sha256:[0-9a-f]{64}$")


def _load():
    spec = importlib.util.spec_from_file_location(
        "audit_pin_consistency", REPO / "scripts/audit_pin_consistency.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_pins_yaml_declares_current_image_digest():
    """sndr/pins.yaml must carry a current_image_digest handle — the digest is
    the HIGHEST-precedence image reference at render time, so the SSOT must
    own it like every other pin handle."""
    sys.path.insert(0, str(REPO))
    from sndr import pins
    digest = pins.current_image_digest()
    assert digest, "pins.current_image_digest() is empty — add it to sndr/pins.yaml"
    assert _DIGEST_RE.match(digest), (
        f"current_image_digest {digest!r} is not a full "
        "vllm/vllm-openai@sha256:<64-hex> reference")


def test_hardware_yaml_digests_match_current_pin_digest():
    """Every builtin hardware YAML image_digest must equal the SSOT current
    digest. A stale digest silently boots the rollback pin (digest wins over
    the image tag at render) — the exact CRIT that poisoned the 2026-07-04
    fleet sweep."""
    sys.path.insert(0, str(REPO))
    from sndr import pins
    cur = pins.current_image_digest()
    hw_dir = REPO / "sndr/model_configs/builtin/hardware"
    yamls = sorted(hw_dir.glob("*.yaml"))
    assert yamls, "no hardware YAMLs found"
    for y in yamls:
        m = re.search(r"image_digest:\s*([^\s#]+)", y.read_text(encoding="utf-8"))
        if not m:
            continue  # no docker image_digest — out of scope (R-PIN-2 covers presence)
        assert m.group(1) == cur, (
            f"{y.name}: image_digest {m.group(1)!r} != SSOT current digest "
            f"{cur!r} — a strict render boots the WRONG engine")


def test_digest_errors_flags_mismatch_and_passes_match():
    """The audit's digest check is a pure function: mismatch -> error naming
    the file; all-match -> no errors; missing SSOT digest -> error."""
    apc = _load()
    good = "vllm/vllm-openai@sha256:" + "a" * 64
    bad = "vllm/vllm-openai@sha256:" + "b" * 64
    # all-match: no errors
    assert apc._digest_errors(good, [("hw-a.yaml", good)]) == []
    # mismatch: error names the offending file
    errs = apc._digest_errors(good, [("hw-a.yaml", good), ("hw-b.yaml", bad)])
    assert len(errs) == 1
    assert "hw-b.yaml" in errs[0]
    # missing SSOT digest: error
    assert apc._digest_errors("", [("hw-a.yaml", good)])
    # malformed SSOT digest: error
    assert apc._digest_errors("not-a-digest", [("hw-a.yaml", good)])


def test_audit_pin_consistency_exits_zero_on_repo_state():
    """The committed repo state must pass the full gate (including the new
    digest invariant) — this is the `make gates` member contract."""
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts/audit_pin_consistency.py")],
        capture_output=True, text=True, cwd=str(REPO), check=False)
    assert proc.returncode == 0, (
        f"audit_pin_consistency failed:\n{proc.stdout}\n{proc.stderr}")
