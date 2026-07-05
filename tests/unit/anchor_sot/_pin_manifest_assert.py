# SPDX-License-Identifier: Apache-2.0
"""Shared assertions: resolve pristine anchor byte-checks against the
committed per-pin anchor manifest instead of a live /tmp pristine tree.

Audit finding #14 (2026-07-04): ~200 patch anchor/behavioral tests gate a
``@pytest.mark.skipif`` on a filesystem pristine-vllm tree that exists on NO
CI host (``/private/tmp/candidate_pin_current/vllm``, ``/tmp/dev301_pristine``,
hardcoded dev148/dev259/dev491 roots). They green-by-skip everywhere, inflating
the suite with dead coverage.

The committed per-pin manifest
``sndr/engines/vllm/pins/<pin>/anchors.json`` (regenerated + round-trip-verified
on every ``make rebuild-pin``) already records, for each registered TextPatcher
sub-patch, the ``anchor_md5`` and ``byte_length`` of the anchor in the pristine
source of the current pin — plus the patch-level ``merge_status`` and each
anchor's ``replacement_md5``. So the byte-checks CAN run in CI against the
manifest.

Why this is STRONGER than the old byte-check (not merely a CI-runnable copy):

  * ``compute_anchor_meta`` (anchor_manifest.py) only emits a manifest entry
    when the anchor occurs EXACTLY ONCE in pristine source. Therefore the mere
    presence of a ``(patch_id, sub)`` entry is the CI-runnable form of the old
    ``src.count(anchor) == 1`` uniqueness check — re-derived at every pin bump.
  * ``anchor_md5`` == ``md5(anchor_bytes)`` and ``byte_length`` ==
    ``len(anchor_bytes)`` (proven in anchor_manifest.py). So tying the LIVE
    patcher's own anchor-string CONSTANT (importable without vllm installed) to
    the recorded md5+length pins the patcher text to the exact pristine bytes.
    Drift in EITHER the patcher constant OR pristine (at the next regen) fails
    loud — the old byte-check only compared a hand-copied fixture to a tree that
    never existed on CI.
  * ``replacement_md5`` == ``md5(replacement_bytes)`` ties the NEW (post-apply)
    text; asserting it is the CI-runnable form of "replacement absent in
    pristine" (a recorded OLD anchor means pristine carried OLD, not NEW).
  * ``merge_status`` distinguishes an anchor recorded from clean pristine
    (``not_merged``) from an upstream-absorbed one — the CI form of "drift
    markers absent in pristine".

Public API (all accept an optional ``manifest`` for unit-testing against a
synthetic dict; default reads the committed current-pin manifest):

  current_pin_manifest()
  assert_anchor_recorded(patch_id, sub, anchor_str, *, merge="not_merged")
  assert_replacement_recorded(patch_id, sub, replacement_str)
  assert_cohabits(rel, *patch_ids)
  assert_variant_inactive(patch_id, inactive_anchor_str)

Author: Sandermage(Sander)-Barzov Aleksandr, Ukraine, Odessa.
"""
from __future__ import annotations

import hashlib

from sndr import pins
from sndr.engines.vllm.wiring.anchor_manifest import (
    load_manifest,
    per_pin_manifest_path,
)


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def current_pin_manifest() -> dict:
    """Load + schema-validate the committed anchors.json for the current pin.

    Fails loud if the pin has no committed manifest or the file is
    corrupt/invalid — a bump that forgot to commit the regen must redden here,
    not skip.
    """
    path = per_pin_manifest_path(pins.current())
    assert path is not None, (
        f"pin {pins.current()!r} does not resolve to a per-pin manifest dir "
        f"(no +g<sha> in the version string?)"
    )
    assert path.is_file(), (
        f"no committed anchors.json at {path} for current pin {pins.current()!r}"
    )
    manifest = load_manifest(path)
    assert manifest is not None, (
        f"anchors.json at {path} failed to load/schema-validate — a regen or "
        f"a schema break left it unreadable"
    )
    return manifest


def _resolve(manifest: dict | None) -> dict:
    return current_pin_manifest() if manifest is None else manifest


def _patch_hits(manifest: dict, patch_id: str) -> list[tuple[str, dict]]:
    """All (rel_path, patch_entry) the manifest records for ``patch_id``.

    A patch may legitimately target more than one file; asserts at least one.
    """
    hits = [
        (rel, fe["patches"][patch_id])
        for rel, fe in manifest.get("files", {}).items()
        if patch_id in fe.get("patches", {})
    ]
    assert hits, (
        f"patch {patch_id!r} not recorded in the current-pin anchor manifest "
        f"({pins.current()!r}) — anchor drifted, the patch was dropped from "
        f"discovery, or the committed manifest is stale/incomplete"
    )
    return hits


def _anchor_entry(manifest: dict, patch_id: str, sub: str) -> dict:
    """The recorded anchor entry for ``patch_id.sub``. Its mere presence is
    the CI-runnable form of ``src.count(anchor) == 1`` (compute_anchor_meta
    emits an entry ONLY when the anchor is unique in pristine)."""
    for _rel, patch_entry in _patch_hits(manifest, patch_id):
        anchors = patch_entry.get("anchors", {})
        if sub in anchors:
            return anchors[sub]
    raise AssertionError(
        f"sub-patch {sub!r} of {patch_id!r} not recorded in the current-pin "
        f"manifest — the anchor is not unique in pristine, drifted, or the "
        f"committed manifest is stale/incomplete"
    )


def _merge_status(manifest: dict, patch_id: str) -> str:
    """Patch-level merge_status (consistent across a patch's files).
    Absent field defaults to ``not_merged`` per the manifest schema."""
    _rel, patch_entry = _patch_hits(manifest, patch_id)[0]
    return patch_entry.get("merge_status", "not_merged")


def assert_anchor_recorded(
    patch_id: str,
    sub: str,
    anchor_str: str,
    *,
    merge: str = "not_merged",
    manifest: dict | None = None,
) -> None:
    """Assert the LIVE patcher anchor string is recorded byte-exactly for the
    current pin. Replaces the pristine trio:

      (1) entry present            <=> pristine src.count(anchor) == 1
      (2) anchor_md5 == md5(anchor_str)   [ties the live patcher text to the
          exact pristine bytes — stronger than a hand-copied fixture]
      (3) byte_length == len(anchor_str bytes)
      (4) patch merge_status == merge     [not_merged == recorded from clean
          pristine, i.e. drift markers absent]
    """
    man = _resolve(manifest)
    entry = _anchor_entry(man, patch_id, sub)
    ab = anchor_str.encode("utf-8")
    got_md5 = hashlib.md5(ab).hexdigest()
    assert entry["anchor_md5"] == got_md5, (
        f"{patch_id}.{sub}: manifest anchor_md5 {entry['anchor_md5']} != "
        f"md5 of the live patcher anchor constant {got_md5} — the patcher OR "
        f"pristine drifted since the manifest was regenerated"
    )
    assert entry["byte_length"] == len(ab), (
        f"{patch_id}.{sub}: manifest byte_length {entry['byte_length']} != "
        f"live anchor byte length {len(ab)}"
    )
    ms = _merge_status(man, patch_id)
    assert ms == merge, (
        f"{patch_id}: manifest merge_status {ms!r} != expected {merge!r} "
        f"(a flip means upstream absorbed the patch — retire it)"
    )


def assert_replacement_recorded(
    patch_id: str,
    sub: str,
    replacement_str: str,
    *,
    manifest: dict | None = None,
) -> None:
    """Tie the LIVE patcher replacement (post-apply NEW text) to the recorded
    ``replacement_md5`` — the CI-runnable form of "replacement absent in
    pristine" (a recorded OLD anchor proves pristine carried OLD, not NEW)."""
    man = _resolve(manifest)
    entry = _anchor_entry(man, patch_id, sub)
    exp = entry.get("replacement_md5")
    assert exp is not None, (
        f"{patch_id}.{sub}: no replacement_md5 recorded — regenerate the pin "
        f"manifest with the replacement captured"
    )
    got = _md5(replacement_str)
    assert exp == got, (
        f"{patch_id}.{sub}: manifest replacement_md5 {exp} != md5 of the live "
        f"patcher replacement {got}"
    )


def assert_cohabits(
    rel: str,
    *patch_ids: str,
    manifest: dict | None = None,
) -> None:
    """Same-file non-collision proxy: all ``patch_ids`` are anchored in the
    same file ``rel``. Coexistence in the manifest means every anchor
    round-trip-verified at regen against the same pristine source without
    colliding — the CI form of the old positional "P24 anchors survive PN377
    splice" byte-check."""
    man = _resolve(manifest)
    assert rel in man.get("files", {}), (
        f"{rel!r} not a target file in the current-pin manifest"
    )
    pats = set(man["files"][rel].get("patches", {}))
    missing = set(patch_ids) - pats
    assert not missing, (
        f"{rel}: expected {sorted(patch_ids)} co-anchored without collision; "
        f"missing {sorted(missing)} (recorded: {sorted(pats)})"
    )


def assert_variant_inactive(
    patch_id: str,
    inactive_anchor_str: str,
    *,
    manifest: dict | None = None,
) -> None:
    """A dual/multi-variant patch records ONLY the variant active on the
    current pin. Assert the given (inactive) variant's anchor is recorded under
    NO sub of this patch — the CI form of ``count(INACTIVE_OLD) == 0`` in
    pristine. Ties the live inactive-variant CONSTANT, so a variant-selection
    drift at the next regen fails loud."""
    man = _resolve(manifest)
    absent = _md5(inactive_anchor_str)
    for _rel, patch_entry in _patch_hits(man, patch_id):
        for sub, entry in patch_entry.get("anchors", {}).items():
            assert entry["anchor_md5"] != absent, (
                f"{patch_id}: an inactive-variant anchor (md5 {absent}) is "
                f"recorded as the active anchor {sub!r} for the current pin — "
                f"variant selection drifted"
            )
