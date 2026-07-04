#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Propagate a vLLM pin bump across every artifact from one command.

Before this, a bump meant hand-editing sndr/pins.yaml, guards.KNOWN_GOOD,
audit_v2 ALLOWED_MODELDEF + CANONICAL_PIN_SUBSTRING, test_pin_gate EXPECTED_PINS,
~11 model YAMLs — and forgetting one gave a silent cross-artifact drift. This
script does all of it from the new pin string, then tells you the two manual
steps that MUST stay manual (regenerate the anchor manifest on the live rig, and
run the consistency gate).

Usage:
    python3 scripts/bump_pin.py 0.23.1rc1.dev777+gabcdef012
    make bump-pin NEW=0.23.1rc1.dev777+gabcdef012

What it does (idempotent — safe to re-run):
  1. sndr/pins.yaml: current -> NEW, previous current -> rollback, and refresh
     canonical_substring / sha_short / anchor_dir / image / container
     (+ current_sha_full via --sha-full, + current_image_digest via
     --image-digest).
  2. audit_v2_runtime_pins.py: CANONICAL_PIN_SUBSTRING -> new devNNN.
  3. Every vLLM model YAML: vllm_pin_required -> NEW (skips llama.cpp null lanes).
  4. Append NEW to guards.KNOWN_GOOD_VLLM_PINS, ALLOWED_MODELDEF_PINS, and
     test_pin_gate.EXPECTED_PINS if absent (with a dated 'validate me' comment).
  5. Hardware YAMLs: image_digest -> --image-digest value and image: ->
     nightly-<--sha-full> (audit remediation 2026-07-05: the digest is the
     HIGHEST-precedence image ref — effective_image_ref = image_digest or
     image — and it was outside the rewrite surface, so the dev748 bump left
     every strict render booting the dev714 rollback engine).
  6. Preset YAMLs: vLLM-shaped engine_pin values -> NEW (llama.cpp lanes'
     engine_pin is a llama.cpp build tag and passes through untouched).

Get the digest from the rig AFTER the candidate image is pulled:
    docker inspect <image> --format '{{json .RepoDigests}}'
Without --image-digest the digest artifacts stay STALE and
audit_pin_consistency (a `make gates` member) FAILS loudly — by design.

It does NOT edit rollback receipts or prose comments. After it runs:
    make rebuild-pin SSH_HOST=... CONTAINER=... IMAGE=...   # anchor manifest
    make audit-pin-consistency                              # verify all in sync
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_PIN_RE = re.compile(r"^(?P<rel>\d+\.\d+\.\d+\w*)\.dev(?P<dev>\d+)\+g(?P<sha>[0-9a-f]+)$")


def _parse(pin: str) -> dict:
    m = _PIN_RE.match(pin.strip())
    if not m:
        sys.exit(f"error: {pin!r} is not a 'X.Y.Zrc.devN+g<sha>' pin string")
    d = m.groupdict()
    # Anchor dirs use the release WITHOUT the rc suffix: 0.23.1rc1 -> 0.23.1
    # (matches the existing sndr/engines/vllm/pins/0.23.1_<sha> layout).
    rel_no_rc = re.sub(r"rc\d+$", "", d["rel"])
    return {
        "pin": pin.strip(),
        "canonical": f"dev{d['dev']}",
        "sha_short": d["sha"],
        "anchor_dir": f"{rel_no_rc}_{d['sha']}",
        "container": f"vllm-35b-dev{d['dev']}",
        "image": f"vllm/vllm-openai:nightly-{d['sha']}",
    }


def _sub_line(text: str, key: str, value: str) -> str:
    """Replace a top-level ``key: "..."`` (or bare) YAML scalar, preserving the
    trailing inline comment."""
    return re.sub(
        rf'^({re.escape(key)}:\s*)(?:"[^"]*"|\'[^\']*\'|[^\s#]+)(\s*(?:#.*)?)$',
        lambda m: f'{m.group(1)}"{value}"{m.group(2)}',
        text, count=1, flags=re.M)


# vLLM pin shape as it appears in preset engine_pin values. Anything else
# (e.g. the llama.cpp lane's `server-cuda-b9246`) is a different engine's
# build tag and must pass through untouched.
_VLLM_PIN_VALUE_RE = re.compile(r"(engine_pin:\s*)(\d+\.\d+\.\d+\w*\.dev\d+\+g[0-9a-f]+)")

_IMAGE_DIGEST_VALUE_RE = re.compile(
    r"(image_digest:\s*)(vllm/vllm-openai@sha256:[0-9a-f]{64})")

_IMAGE_TAG_VALUE_RE = re.compile(
    r"(image:\s*)(vllm/vllm-openai:nightly-[0-9a-f]{40})")


def _sub_engine_pin(text: str, pin: str) -> str:
    """Rewrite every vLLM-shaped ``engine_pin`` value, keeping comments and
    non-vLLM engine pins (llama.cpp build tags) intact."""
    return _VLLM_PIN_VALUE_RE.sub(lambda m: f"{m.group(1)}{pin}", text)


def _sub_image_digest(text: str, digest_ref: str) -> str:
    """Rewrite the ``image_digest`` value (full repo@sha256 form), keeping
    the trailing comment intact."""
    return _IMAGE_DIGEST_VALUE_RE.sub(lambda m: f"{m.group(1)}{digest_ref}", text)


def _normalize_digest(raw: str) -> str | None:
    """Accept ``sha256:<64hex>`` or ``vllm/vllm-openai@sha256:<64hex>``;
    return the full repo@sha256 reference, or None if malformed."""
    if re.fullmatch(r"sha256:[0-9a-f]{64}", raw):
        return f"vllm/vllm-openai@{raw}"
    if re.fullmatch(r"vllm/vllm-openai@sha256:[0-9a-f]{64}", raw):
        return raw
    return None


def _hardware_edits(image_digest: str | None,
                    sha_full: str | None) -> list[tuple[Path, str]]:
    """Pending rewrites for the builtin hardware YAMLs: the image_digest
    value (highest-precedence image ref) and, when the full sha is known,
    the explicit-hash image: tag. Prose comments are left to the operator."""
    edits: list[tuple[Path, str]] = []
    hdir = REPO / "sndr/model_configs/builtin/hardware"
    for yml in sorted(hdir.glob("*.yaml")):
        t = yml.read_text(encoding="utf-8")
        nt = t
        if image_digest:
            nt = _sub_image_digest(nt, image_digest)
        if sha_full:
            nt = _IMAGE_TAG_VALUE_RE.sub(
                lambda m: f"{m.group(1)}vllm/vllm-openai:nightly-{sha_full}", nt)
        if nt != t:
            edits.append((yml, nt))
    return edits


def _preset_edits(pin: str) -> list[tuple[Path, str]]:
    """Pending rewrites for builtin preset YAMLs whose engine_pin carries a
    vLLM-shaped pin (llama.cpp lanes keep their own engine build tag)."""
    edits: list[tuple[Path, str]] = []
    pdir = REPO / "sndr/model_configs/builtin/presets"
    for yml in sorted(pdir.glob("*.yaml")):
        t = yml.read_text(encoding="utf-8")
        nt = _sub_engine_pin(t, pin)
        if nt != t:
            edits.append((yml, nt))
    return edits


def bump(new: str, dry: bool, sha_full: str | None = None,
         image_digest: str | None = None) -> int:
    info = _parse(new)
    pins_yaml = REPO / "sndr/pins.yaml"
    from sndr import pins as _pins  # current SSOT before edit
    old_current = _pins.current()
    if old_current == new:
        print(f"pins.yaml already at {new} — refreshing downstream only")

    # 1. pins.yaml
    y = pins_yaml.read_text(encoding="utf-8")
    if old_current != new:
        y = _sub_line(y, "rollback", old_current)   # old current -> rollback
    y = _sub_line(y, "current", info["pin"])
    y = _sub_line(y, "canonical_substring", info["canonical"])
    y = _sub_line(y, "current_sha_short", info["sha_short"])
    y = _sub_line(y, "current_image", info["image"])
    y = _sub_line(y, "current_container", info["container"])
    y = _sub_line(y, "current_anchor_dir", info["anchor_dir"])
    # current_sha_full cannot be derived from the version string's short
    # g-hash (dev748 promotion 2026-07-04: the previous pin's full sha was
    # silently left in place). The operator passes the 40-char sha via
    # --sha-full (from the image label org.opencontainers.image.revision).
    if sha_full:
        y = _sub_line(y, "current_sha_full", sha_full)
    else:
        print("  WARN: --sha-full not given — current_sha_full NOT updated; "
              "fetch it via: docker inspect <image> --format "
              "'{{index .Config.Labels \"org.opencontainers.image.revision\"}}'")

    # 2. CANONICAL_PIN_SUBSTRING
    av2_path = REPO / "scripts/audit_v2_runtime_pins.py"
    av2 = av2_path.read_text(encoding="utf-8")
    av2 = re.sub(r'(CANONICAL_PIN_SUBSTRING\s*=\s*)"[^"]*"',
                 rf'\g<1>"{info["canonical"]}"', av2, count=1)

    # 3. model YAMLs
    changed_yamls = []
    mdir = REPO / "sndr/model_configs/builtin/model"
    yaml_edits: list[tuple[Path, str]] = []
    for yml in sorted(mdir.glob("*.yaml")):
        t = yml.read_text(encoding="utf-8")
        m = re.search(r"vllm_pin_required:\s*([^\s#]+)", t)
        if not m or m.group(1).strip().strip('"').strip("'").lower() in {"null", "none", "~"}:
            continue
        nt = re.sub(r"(vllm_pin_required:\s*)([^\s#]+)", rf"\g<1>{info['pin']}", t, count=1)
        if nt != t:
            yaml_edits.append((yml, nt)); changed_yamls.append(yml.name)

    # 4. append to allowlists if absent
    def _append_pin(path: Path, anchor: str, comment: str) -> tuple[Path, str] | None:
        txt = path.read_text(encoding="utf-8")
        if f'"{info["pin"]}"' in txt:
            return None
        ins = f'{comment}\n    "{info["pin"]}",\n'
        nt = txt.replace(anchor, ins + "    " + anchor.strip(), 1) if anchor in txt else None
        return (path, nt) if nt else None

    # 5. hardware YAMLs: image_digest (audit remediation 2026-07-05 — the
    # digest WINS over the tag at render, so leaving it stale boots the
    # rollback engine) + image: tag when the full sha is known.
    hw_edits = _hardware_edits(image_digest, sha_full)
    if image_digest:
        y = _sub_line(y, "current_image_digest", image_digest)
    else:
        print("  WARN: --image-digest not given — pins.yaml current_image_digest "
              "and hardware image_digest NOT updated; audit_pin_consistency WILL "
              "FAIL until they track the new pin (by design — the digest is the "
              "highest-precedence image ref). Fetch it via: docker inspect "
              "<image> --format '{{json .RepoDigests}}'")

    # 6. preset engine_pin (vLLM-shaped values only; llama.cpp lanes keep
    # their own engine build tag).
    preset_edits = _preset_edits(info["pin"])

    print("=== bump plan ===")
    print(f"  new current : {info['pin']}")
    print(f"  rollback    : {old_current}")
    print(f"  canonical   : {info['canonical']}   anchor_dir: {info['anchor_dir']}")
    print(f"  container   : {info['container']}")
    print(f"  model YAMLs : {len(changed_yamls)} -> {new}")
    print(f"  hardware YAMLs: {len(hw_edits)} (image_digest"
          + (" + image: tag" if sha_full else "") + ")"
          + ("" if image_digest else "  [digest SKIPPED — no --image-digest]"))
    print(f"  preset engine_pin: {len(preset_edits)} -> {new}")
    if dry:
        print("\n(dry-run — no files written)")
        return 0

    pins_yaml.write_text(y, encoding="utf-8")
    av2_path.write_text(av2, encoding="utf-8")
    for p, t in [*yaml_edits, *hw_edits, *preset_edits]:
        p.write_text(t, encoding="utf-8")
    print("\n✓ pins.yaml, CANONICAL_PIN_SUBSTRING, model YAMLs, hardware "
          "digests and preset engine_pin updated.")
    print("  NOTE: append the new pin to guards.KNOWN_GOOD_VLLM_PINS / "
          "ALLOWED_MODELDEF_PINS / EXPECTED_PINS with its validation receipt "
          "(these carry per-pin comments, kept manual on purpose).")
    print("\nNext (manual, required):")
    print(f"  make rebuild-pin SSH_HOST=<user@host> CONTAINER={info['container']} IMAGE={info['image']}")
    print("  # commit sndr/engines/vllm/pins/%s/" % info["anchor_dir"])
    print("  make audit-pin-consistency   # must PASS before promoting")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("new_pin", help="new pin string, e.g. 0.23.1rc1.dev777+gabcdef012")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    ap.add_argument("--sha-full", default=None,
                    help="full 40-hex vLLM commit sha of the new pin "
                         "(updates current_sha_full + hardware image: tags; "
                         "from the image label org.opencontainers.image.revision)")
    ap.add_argument("--image-digest", default=None,
                    help="rig RepoDigest of the new image: sha256:<64hex> or "
                         "vllm/vllm-openai@sha256:<64hex> (updates pins.yaml "
                         "current_image_digest + every hardware image_digest; "
                         "from docker inspect <image> --format "
                         "'{{json .RepoDigests}}'). Without it the digest "
                         "artifacts stay stale and audit_pin_consistency fails.")
    args = ap.parse_args(argv)
    digest_ref = None
    if args.image_digest is not None:
        digest_ref = _normalize_digest(args.image_digest.strip())
        if digest_ref is None:
            ap.error(f"--image-digest must be sha256:<64hex> or "
                     f"vllm/vllm-openai@sha256:<64hex>, got {args.image_digest!r}")
    if args.sha_full is not None:
        import re as _re
        if not _re.fullmatch(r"[0-9a-f]{40}", args.sha_full):
            ap.error(f"--sha-full must be a 40-char lowercase hex sha, got {args.sha_full!r}")
        short = args.new_pin.rsplit("+g", 1)[-1]
        if not args.sha_full.startswith(short):
            ap.error(f"--sha-full {args.sha_full[:12]}... does not start with "
                     f"the pin's short hash {short!r}")
    sys.path.insert(0, str(REPO))
    return bump(args.new_pin, args.dry_run, sha_full=args.sha_full,
                image_digest=digest_ref)


if __name__ == "__main__":
    raise SystemExit(main())
