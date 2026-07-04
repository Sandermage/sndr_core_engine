#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Cross-artifact pin-consistency gate.

The current pin (sndr/pins.yaml → sndr.pins.current()) MUST be present in every
downstream artifact, or a bump silently half-lands (dev672/dev714 were missing
from allowlists for a whole window — the failure this gate exists to catch).

Invariants asserted (all against the SSOT current pin):
  1. current ∈ guards.KNOWN_GOOD_VLLM_PINS
  2. current ∈ audit_v2_runtime_pins.ALLOWED_MODELDEF_PINS
  3. current ∈ test_pin_gate.EXPECTED_PINS
  4. canonical_substring() is a substring of current
  5. audit_v2 CANONICAL_PIN_SUBSTRING == canonical_substring()
  6. per-pin anchor dir sndr/engines/vllm/pins/<current_anchor_dir>/anchors.json exists
  7. every builtin model YAML vllm_pin_required == current
  8. rollback ∈ guards.KNOWN_GOOD_VLLM_PINS  (rollback must stay known-good)
  9. ALLOWED_MODELDEF_PINS ⊆ KNOWN_GOOD_VLLM_PINS  (allowlist is a known-good subset)
 10. pins.yaml current_image_digest is a well-formed repo@sha256:<64-hex> reference
 11. every builtin hardware YAML image_digest == current_image_digest
     (the digest WINS over the image tag at render — effective_image_ref =
     image_digest or image; a stale digest silently boots the rollback pin.
     2026-07-04 audit CRIT: 4/7 fleet lanes booted the rollback engine this
     way while every string-level check stayed green)

Exit 0 = consistent; exit 1 = drift (with the exact fix listed).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _expected_pins() -> set[str]:
    """Parse the EXPECTED_PINS tuple literal from the test (no test import).

    Grab a generous window after the marker and collect pin-like strings (those
    that start ``0.<digit>``) — robust to the tuple's closing paren indentation."""
    txt = (REPO / "tests/unit/dispatcher/test_pin_gate.py").read_text(encoding="utf-8")
    i = txt.find("EXPECTED_PINS = (")
    if i < 0:
        return set()
    # Scan to the tuple's real closing paren (first column-0 ')') — the
    # previous fixed 8000-char window silently truncated the tuple once its
    # per-pin receipt comments outgrew it (caught on the dev748 promotion
    # 2026-07-04: the freshly-added pin was reported missing while present).
    end = txt.find("\n)", i)
    block = txt[i: end if end > 0 else len(txt)]
    return set(re.findall(r'"(0\.\d[\w.+]*)"', block))


_DIGEST_REF_RE = re.compile(r"^vllm/vllm-openai@sha256:[0-9a-f]{64}$")


def _hardware_image_digests() -> list[tuple[str, str]]:
    """(filename, image_digest) for every builtin hardware YAML declaring one."""
    out: list[tuple[str, str]] = []
    hdir = REPO / "sndr/model_configs/builtin/hardware"
    for y in sorted(hdir.glob("*.yaml")):
        m = re.search(r"image_digest:\s*([^\s#]+)", y.read_text(encoding="utf-8"))
        if m:
            out.append((y.name, m.group(1).strip().strip('"').strip("'")))
    return out


def _digest_errors(current_digest: str, hw_digests: list[tuple[str, str]]) -> list[str]:
    """Invariants 10+11 as a pure function (testable without repo state).

    The image_digest is the HIGHEST-precedence image reference at render time
    (types/docker.py effective_image_ref: digest wins over the tag), so a
    stale digest boots the WRONG engine while every pin string looks current."""
    errs: list[str] = []
    if not current_digest:
        errs.append("pins.yaml has no current_image_digest — capture it via "
                    "docker inspect <current_image> --format '{{json .RepoDigests}}'")
        return errs
    if not _DIGEST_REF_RE.match(current_digest):
        errs.append(f"current_image_digest {current_digest!r} is not a full "
                    "vllm/vllm-openai@sha256:<64-hex> reference")
        return errs
    for name, digest in hw_digests:
        if digest != current_digest:
            errs.append(f"hardware {name}: image_digest {digest!r} != current pin digest "
                        f"{current_digest!r} — the digest WINS at render, so a strict "
                        "render boots the WRONG engine; update it with the bump")
    return errs


# llama.cpp / gguf lanes run a different engine (no vLLM pin) and set
# vllm_pin_required: null — exclude those from the "== current pin" check.
_NON_VLLM_PIN = {"null", "none", "~", ""}


def _model_yaml_pins() -> list[tuple[str, str]]:
    """(path, vllm_pin_required) for every builtin model YAML with a vLLM pin.

    Skips llama.cpp lanes whose pin is null (they run no vLLM, so no pin)."""
    out: list[tuple[str, str]] = []
    mdir = REPO / "sndr/model_configs/builtin/model"
    for y in sorted(mdir.glob("*.yaml")):
        m = re.search(r"vllm_pin_required:\s*([^\s#]+)", y.read_text(encoding="utf-8"))
        if m:
            pin = m.group(1).strip().strip('"').strip("'")
            if pin.lower() not in _NON_VLLM_PIN:
                out.append((y.name, pin))
    return out


def main() -> int:
    sys.path.insert(0, str(REPO))
    from sndr import pins
    from sndr.engines.vllm.detection.guards import KNOWN_GOOD_VLLM_PINS
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "audit_v2_runtime_pins", REPO / "scripts/audit_v2_runtime_pins.py")
    av2 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(av2)

    cur = pins.current()
    roll = pins.rollback()
    canon = pins.canonical_substring()
    kg = set(KNOWN_GOOD_VLLM_PINS)
    al = set(av2.ALLOWED_MODELDEF_PINS)
    ep = _expected_pins()

    errs: list[str] = []

    if cur not in kg:
        errs.append(f"current pin {cur!r} NOT in guards.KNOWN_GOOD_VLLM_PINS — add it")
    if cur not in al:
        errs.append(f"current pin {cur!r} NOT in ALLOWED_MODELDEF_PINS (audit_v2_runtime_pins.py) — add it")
    if cur not in ep:
        errs.append(f"current pin {cur!r} NOT in EXPECTED_PINS (test_pin_gate.py) — add it")
    if canon not in cur:
        errs.append(f"canonical_substring {canon!r} is not a substring of current pin {cur!r}")
    if av2.CANONICAL_PIN_SUBSTRING != canon:
        errs.append(f"audit_v2 CANONICAL_PIN_SUBSTRING={av2.CANONICAL_PIN_SUBSTRING!r} != pins.yaml {canon!r}")

    anchor = REPO / "sndr/engines/vllm/pins" / pins.current_anchor_dir() / "anchors.json"
    if not anchor.is_file():
        errs.append(f"anchor manifest missing for current pin: {anchor.relative_to(REPO)} "
                    f"— run `make rebuild-pin` on the live rig and commit it")

    bad_yaml = [(n, p) for n, p in _model_yaml_pins() if p != cur]
    if bad_yaml:
        errs.append(f"{len(bad_yaml)} model YAML(s) declare a pin != current {cur!r}: "
                    + ", ".join(f"{n}={p}" for n, p in bad_yaml[:6]))

    if roll not in kg:
        errs.append(f"rollback pin {roll!r} NOT in guards.KNOWN_GOOD_VLLM_PINS — a rollback target must stay known-good")

    errs.extend(_digest_errors(pins.current_image_digest(), _hardware_image_digests()))

    stray = al - kg
    if stray:
        errs.append(f"ALLOWED_MODELDEF_PINS not a subset of KNOWN_GOOD: {sorted(stray)}")

    print("=== pin-consistency audit ===")
    print(f"  SSOT current : {cur}")
    print(f"  SSOT rollback: {roll}")
    print(f"  KNOWN_GOOD={len(kg)}  ALLOWED_MODELDEF={len(al)}  EXPECTED={len(ep)}  "
          f"model_yaml={len(_model_yaml_pins())}  hw_digest={len(_hardware_image_digests())}")
    if errs:
        print(f"\n✗ {len(errs)} cross-artifact inconsistency(ies):")
        for e in errs:
            print(f"    - {e}")
        return 1
    print("✓ current + rollback pins consistent across all artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
