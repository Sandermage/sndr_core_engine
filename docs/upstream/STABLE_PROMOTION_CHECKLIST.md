# Stable Lifecycle Promotion Checklist

When promoting a Genesis patch from `experimental` (or `<unspecified>`)
to `lifecycle="stable"`, you take on the contract that this patch is
production-ready and won't drift silently. The patcher framework
enforces this via the ratchet test in
[`tests/unit/infra/test_stable_manifest_policy.py`](../../tests/unit/infra/test_stable_manifest_policy.py).

This is the closure of PR38_PATCHER_REWORK_PLAN_2026-05-07.md §5.5
("anchor manifest mandatory for stable patches"). Closing via ratchet
rather than mass migration: nothing happens until you actually promote
something, but when you do, all the right rituals fire.

---

## Why this exists

Without the ratchet, `lifecycle="stable"` would be a marketing label
with nothing behind it. With the ratchet, marking a patch stable forces
five concrete actions that together guarantee:

- **Drift detection precision** — manifest md5s pinpoint the exact
  anchor that changed, vs vague "anchor missing somewhere".
- **Boot speedup** — manifest fast-path replaces O(N×M) anchor scan
  with O(1) byte-offset splice.
- **Reproducibility** — pristine fixture committed at promotion time
  documents the exact upstream state the patch was validated against.

---

## When to promote

A patch is ready for `lifecycle="stable"` when ALL hold:

1. **A/B validated** on the production rig (not just dev/Mac).
2. **Reference metrics committed** in at least one builtin model_config
   (see `reference_metrics:` block in `*-prod.yaml`).
3. **No open known regressions** in `docs/_internal/` or memory entries
   tagged with the patch ID.
4. **Cross-pin tested** — verified on at least 2 different vllm pins
   (catches anchor brittleness early).
5. **Documented** in `docs/PATCHES.md` or `CHANGELOG.md` with an
   "operating envelope" (what it does, what it doesn't, known
   conflicts).

If any of those is missing, keep the patch at `experimental` (or its
current state) and don't pretend.

---

## The five steps

### 1. Add `patch_id` to every TextPatcher

In the wiring module (`vllm/sndr_core/integrations/<family>/<patch>.py`),
each TextPatcher constructor must declare `patch_id`:

```python
return TextPatcher(
    patch_name="P58 async scheduler placeholder fix",
    target_file=str(target),
    marker=GENESIS_P58_MARKER,
    sub_patches=[
        TextPatch(name="A", anchor=ANCHOR_A_OLD, replacement=ANCHOR_A_NEW),
        TextPatch(name="B", anchor=ANCHOR_B_OLD, replacement=ANCHOR_B_NEW),
        # ...
    ],
    patch_id="P58.Sub-1",  # ← REQUIRED for stable
)
```

Naming convention: `<PatchID>.Sub-<N>` where `<N>` is 1-based across
all TextPatchers in the patch. PN79 is the reference example
(`PN79.Sub-1` … `PN79.Sub-4` across 4 files).

### 2. Add a `register_for_manifest(pristine_root)` function

Mirror PN79's pattern in
[`pn79_inplace_ssm_state.py`](../../vllm/sndr_core/integrations/attention/gdn/pn79_inplace_ssm_state.py):

```python
def register_for_manifest(pristine_root: Path) -> None:
    """Build-mode patcher registration. Called by
    scripts/build_anchor_manifest.py to populate the patcher_registry
    with patchers pointed at pristine fixtures (NOT live vllm)."""
    from vllm.sndr_core.wiring.patcher_registry import register_text_patcher

    register_text_patcher(
        "P58.Sub-1",
        _make_patcher_for_fixture(
            "P58 build-mode", pristine_root / "async_scheduler.py",
            sub_patches, patch_id="P58.Sub-1",
        ),
    )
```

The `_make_patcher_for_fixture` helper is identical to
`_make_patcher` but takes the fixture path instead of the live vllm
file. Copy the helper from PN79 (lines ~1121-1135).

### 3. Commit a pristine fixture

The build script reads pristine source from
`tests/legacy/pristine_fixtures/<basename>.py` (today; will move to
`tests/pristine_fixtures/` post-Phase-2 relocation). Drop a verbatim
copy of the upstream vllm file at the pinned commit:

```bash
cp $VLLM_INSTALL_ROOT/scheduler/async_scheduler.py \
   tests/legacy/pristine_fixtures/async_scheduler.py
```

The fixture is "frozen at the pinned commit" — as soon as you bump
`KNOWN_GOOD_VLLM_PINS`, the manifest will detect the md5 mismatch and
fall back to legacy O(N×M) anchor scan (graceful), and operators
re-run the builder to refresh the fixture + manifest.

### 4. Extend `_KNOWN_REL_PATHS`

In [`scripts/build_anchor_manifest.py`](../../scripts/build_anchor_manifest.py),
add the fixture basename → vllm rel_path mapping:

```python
_KNOWN_REL_PATHS = {
    # existing PN79 entries...
    "async_scheduler.py": "v1/core/scheduler/async_scheduler.py",
}
```

Without this, the builder doesn't know where in the vllm tree the
fixture maps to and skips it with a warning.

### 5. Build + commit the manifest

```bash
python scripts/build_anchor_manifest.py
git add vllm/sndr_core/manifests/anchor_manifest.json
```

Verify the new file appears in the JSON. Run pytest — the ratchet
test (`test_stable_manifest_policy.py`) must PASS for the new stable
patch.

---

## Verification

```bash
# Full pytest — ratchet test exercises every lifecycle=stable patch
python -m pytest tests/unit/infra/test_stable_manifest_policy.py -v

# Drift detection: simulate upstream rename of an anchor by editing
# the fixture, re-running the builder. Manifest builder should warn.
python scripts/build_anchor_manifest.py --dry-run --verbose
```

Final: bump `lifecycle` in the registry from old value → `"stable"`.
Don't do this BEFORE steps 1-5 — the ratchet test will fail and
rollback your commit.

---

## What NOT to do

- **Do not** mark a patch stable just to clear the experimental
  label. The lifecycle field tells operators what to expect; lying
  about it leaks tech debt into PROD.
- **Do not** skip the pristine fixture by reading from live vllm at
  build time. The fixture is the contract — what the patch was
  validated against. Live vllm drifts.
- **Do not** add `patch_id` to a patcher without the manifest entry.
  The runtime fast-path will abstain via gate G3 and the patcher
  silently uses the legacy path — fine functionally, but you've
  added complexity without benefit.
- **Do not** demote a stable patch back to experimental without
  also removing the `patch_id` and manifest entry. Stale manifest
  entries are noise and confuse drift diagnosis.

---

## Today's status

- **0 patches** are `lifecycle="stable"` as of 2026-05-12.
- **PN79** (4 sub-patches across 4 files, 31 anchors) is the only
  patch wired through the full ratchet (registered in patcher_registry,
  covered by manifest). Currently `lifecycle="experimental"`.
- The ratchet test passes vacuously today.
- When PN79 is promoted to stable (after multi-turn validation per
  memory `feedback_pn59_streaming_almost_dead_code.md`), it will be
  the first stable patch and the ratchet test will exercise it.

### Ratchet architectural gap (audit 2026-05-12)

The five-step ratchet assumes STABLE = TextPatcher. Two categories of
production-validated runtime-hook patches (PN35, PN33) are blocked from
STABLE not by lack of evidence but by infrastructure mismatch:

- **PN35** (text-only inputs_embeds skip) — runtime hook, no
  `_make_patcher`. Validated default_on across Wave 6–9 + dev93/dev209.
- **PN33** (spec-decode warmup K) — has `_make_patcher` (text-patch
  shape) but no `register_text_patcher` call + no manifest entry.

Two paths forward to close this gap:

1. **Build manifest infrastructure for both** — easy for PN33 (real
   text-patch; needs `register_text_patcher` in wiring + 1 manifest
   entry via `build_anchor_manifest.py` on a vllm-installed host),
   harder for PN35 (would need conversion from runtime hook to
   text-patch + pristine fixture).
2. **Extend the ratchet for runtime-hook STABLE** — add a sub-track
   `stable_kind = "runtime-hook"` that requires `apply_module` +
   structured production-validation evidence (e.g.
   `production_validated_pins: [("v11.0.0+wave8", "0.20.2rc1.dev93"),
   ("v11.0.0+stale_ref_cleanup", "0.20.2rc1.dev209")]`) instead of
   manifest coverage. Skips manifest checks because there's no anchor
   to drift-detect.

PN33 + PN35 carry `experimental_note` documenting full production
validation evidence so the operational signal isn't lost.

Reference: PR38_PATCHER_REWORK_PLAN_2026-05-07.md §5.5.
