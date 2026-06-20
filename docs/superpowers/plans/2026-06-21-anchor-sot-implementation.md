# Per-Pin Anchor Source-of-Truth — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make a single per-pin `pins/<pin>/anchors.json` the authoritative store of every patch's anchor address, so a vLLM pin bump = auto-regenerate the still-matching patches + hand-edit only the genuinely-drifted anchors in one file.

**Architecture:** Invert + wire the already-proven engine. Reuse `anchor_manifest.py` (`compute_anchor_meta`: byte_offset+md5) + `text_patch.py` Layer-4.5 splice. Extract the existing 100%-coverage discovery from `check_upstream_drift.py` into a shared module; the generator runs it against a pristine clone of the target pin and writes the per-pin manifest; the boot resolver selects the manifest by auto-detected pin; inline anchors stay as bootstrap/fallback.

**Tech Stack:** Python 3.12, pytest, the Genesis dispatcher (`iter_patch_specs`), TextPatcher engine, `gh` for pristine-pin fetch, rig (`sander@192.168.1.10`, dev148) for R3 server-tests.

**Spec:** `docs/superpowers/specs/2026-06-21-anchor-sot-design.md` (db55a68c).

**Three hard requirements (acceptance gates on every phase):**
- **R1** — discovery covers ALL anchor-bearing patches (count == `iter_patch_specs` anchor-bearing count).
- **R2** — drift classified from the REAL pristine source (synthetic-drift test: exactly the mutated patch reports `anchor_drift`, no false `ok`).
- **R3** — server-tested on the rig: `applied=89 / failed=0` preserved, 7×6→correct, TPS within noise of 216.

---

## File Structure

| File | Responsibility | Phase |
|---|---|---|
| `sndr/engines/vllm/anchor_discovery.py` | NEW. One function `iter_anchor_targets(pristine_root)` yielding `(patch_id, sub, target_rel, anchor, replacement)` for every anchor-bearing patch. Single source of "what to anchor". | Ф1 |
| `tools/check_upstream_drift.py` | Import `anchor_discovery` instead of its private loop (no behavior change). | Ф1 |
| `scripts/build_anchor_manifest.py` | Rewritten generator: run discovery vs a pristine clone, `compute_anchor_meta` per anchor, classify, write `pins/<pin>/anchors.json` + `.rej`. | Ф2 |
| `sndr/engines/vllm/pins/<pin>/anchors.json` | NEW per-pin authoritative manifest (engine JSON schema). | Ф2 |
| `sndr/kernel/text_patch.py` | Extend Layer-4.5 to select the manifest by auto-detected pin; keep exact-match fallback. | Ф3 |
| `sndr/engines/vllm/wiring/anchor_manifest.py` | `load_manifest_for_pins`: pin-mismatch → select a different file (not invalidate-all). | Ф3 |
| `scripts/audit_anchor_fragility.py` | + anchors-per-target-file × `default_on`/`lifecycle` metric + safe-to-merge gate. | Ф0 |
| `Makefile` | `rebuild-pin` / `audit-pin` targets. | Ф4 |
| `sndr/dispatcher/registry.py` | Ф0: flip PN79→v2 default + retire original. | Ф0 |

Tests live under `tests/unit/anchor_sot/` (new dir).

---

## Ф0 — Consolidation-first (shrink the surface before it enters the manifest)

**Goal:** retire the 108-anchor `pn79_inplace_ssm_state.py` in favor of the staged `pn79_v2_md5_chunk*.py` (md5 full-file sentinels), and add the drift-surface metric. `pn118` is deferred (default_on=True, needs prod A/B).

### Task 0.1: Drift-surface metric in the fragility auditor

**Files:**
- Modify: `scripts/audit_anchor_fragility.py`
- Test: `tests/unit/anchor_sot/test_drift_surface_metric.py`

- [ ] **Step 1: Write the failing test** — `anchors_per_target_file()` returns a dict `{target_rel: [patch_ids]}` joined with registry `default_on`, and `safe_to_merge_clusters()` returns only files with ≥2 patches all `default_on=False`.

```python
# tests/unit/anchor_sot/test_drift_surface_metric.py
from scripts.audit_anchor_fragility import anchors_per_target_file, safe_to_merge_clusters

def test_anchors_per_target_file_covers_all_patches():
    m = anchors_per_target_file()
    # every cluster value is a non-empty list of patch ids
    assert all(isinstance(v, list) and v for v in m.values())
    # gdn_linear_attn.py is a known multi-patch hotspot
    assert any("gdn" in k for k in m)

def test_safe_to_merge_excludes_default_on():
    clusters = safe_to_merge_clusters()
    # P28/P46/P7/P29 (default_on=True) never appear in a safe cluster
    flat = [pid for c in clusters.values() for pid in c]
    for prod in ("P28", "P46", "P7", "P29"):
        assert prod not in flat
```

- [ ] **Step 2: Run → FAIL** (`anchors_per_target_file` not defined). `pytest tests/unit/anchor_sot/test_drift_surface_metric.py -v`
- [ ] **Step 3: Implement** `anchors_per_target_file()` (walk `iter_patch_specs()`, read each patch's `target_rel`/`_TARGET_REL` + sub-anchor count) and `safe_to_merge_clusters()` (filter ≥2 patches/file where all `registry[pid]["default_on"] is False`).
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat(audit): anchors-per-file drift-surface metric + safe-to-merge gate`.

### Task 0.2: Parity-test pn79 original vs v2 before cutover

**Files:**
- Test: `tests/unit/anchor_sot/test_pn79_v2_parity.py`

- [ ] **Step 1: Write the test** — applying PN79-v2 (md5 full-file) to a pristine `chunk.py`/`chunk_delta_h.py` yields byte-identical output to the original PN79 splice on those two files (the v2 scope). Use a pristine fixture from the dev148 container's `fla/ops/chunk.py` (fetched once into `tests/fixtures/pristine_dev148/`).

```python
def test_pn79_v2_matches_original_on_chunk_scope(pristine_chunk_py):
    from sndr.engines.vllm.patches.attention.gdn import pn79_v2_md5_chunk as v2
    from sndr.engines.vllm.patches.attention.gdn import pn79_inplace_ssm_state as orig
    out_v2 = v2.render(pristine_chunk_py)      # full-file replacement
    out_orig = orig.render_chunk_scope(pristine_chunk_py)  # the splice result on chunk.py only
    assert out_v2 == out_orig
```

- [ ] **Step 2: Run → FAIL/adapt** to the actual render entry points (read both modules first).
- [ ] **Step 3: Make it pass** (the v2 was authored to match; fix the test harness, not the patch, unless a real diff surfaces — if a real diff surfaces, STOP and report).
- [ ] **Step 4: Commit** `test(pn79): parity v2 md5 vs original splice on chunk scope`.

### Task 0.3: Cut over — flip default + retire original

**Files:**
- Modify: `sndr/dispatcher/registry.py` (PN79 entry ~line 495: `lifecycle: retired`, `superseded_by: [PN79B1, PN79B2]`, add `vllm_version_range` cap; PN79B1/B2 ~564/597: `default_on` matched to PN79's old value)

- [ ] **Step 1** Update the registry. **Step 2** Run `pytest tests/unit/dispatcher tests/unit/anchor_sot -q` + `python3 -m sndr.cli patches doctor` → green. **Step 3** Regenerate baseline snapshots (`SNDR_SNAPSHOT_REGEN=1`) + reconcile the orphan baseline (PN79 retired). **Step 4** Commit `refactor(gdn): retire pn79 splice (108 anchors) -> pn79_v2 md5 (~4) [Ф0]`.

### Ф0 ACCEPTANCE (R3 server-test)
- [ ] Local: pytest + doctor green; `anchors_per_target_file` shows PN79's 108 anchors gone.
- [ ] **Rig:** PN79 is GDN/Mamba (27B target) + default-OFF, so the live 35B is unaffected — boot the 35B, confirm `applied=89 / failed=0`, 7×6→'42', TPS ~216 (proves the registry edit didn't regress the live model). If the operator wants pn79_v2 exercised, that is a separate 27B A/B (deferred with pn118).

---

## Ф1 — `anchor_discovery.py` (R1: 100% coverage of ALL patches)

**Goal:** one shared enumerator both the generator and the drift-checker import. This is the R1 foundation.

### Task 1.1: The discovery function

**Files:**
- Create: `sndr/engines/vllm/anchor_discovery.py`
- Test: `tests/unit/anchor_sot/test_anchor_discovery.py`

- [ ] **Step 1: Write the R1 test** — discovery yields one record per anchor-bearing sub-patch across ALL patches, and the count equals the dispatcher's anchor-bearing count.

```python
# tests/unit/anchor_sot/test_anchor_discovery.py
from sndr.engines.vllm.anchor_discovery import iter_anchor_targets
from sndr.dispatcher.spec import iter_patch_specs

def test_R1_covers_all_anchor_bearing_patches():
    targets = list(iter_anchor_targets())          # against the installed/pristine tree
    seen_patch_ids = {t.patch_id for t in targets}
    # every spec that builds a patcher with >=1 textual anchor must appear
    expected = set()
    for spec in iter_patch_specs():
        anchors = _anchor_count_for(spec)          # helper builds the patcher, counts sub_patches with .anchor
        if anchors > 0:
            expected.add(spec.patch_id)
    missing = expected - seen_patch_ids
    assert not missing, f"R1 VIOLATION: discovery missed {sorted(missing)}"

def test_record_shape():
    t = next(iter(iter_anchor_targets()))
    assert t.patch_id and t.target_rel and t.anchor is not None
```

- [ ] **Step 2: Run → FAIL** (module not found).
- [ ] **Step 3: Implement** `iter_anchor_targets(pristine_root=None)` by lifting the loop from `tools/check_upstream_drift.py` (`iter_patch_specs()` → `_build_patcher_for_module(mod)` → `patcher.target_file` + `patcher.sub_patches[].anchor`). Yield a `@dataclass AnchorTarget(patch_id, sub, target_rel, anchor, replacement)`. NO hand-typed registry — pure enumeration.
- [ ] **Step 4: Run → PASS** (R1 satisfied).
- [ ] **Step 5: Commit** `feat(anchor): shared anchor_discovery enumerator (R1 100% coverage) [Ф1]`.

### Task 1.2: Re-point check_upstream_drift at the shared module

**Files:**
- Modify: `tools/check_upstream_drift.py` (replace its private discovery loop with `from sndr.engines.vllm.anchor_discovery import iter_anchor_targets`)
- Test: `tests/unit/anchor_sot/test_drift_checker_unchanged.py`

- [ ] **Step 1: Characterization test** — capture `check_upstream_drift` classification output BEFORE the refactor (golden), assert it's identical AFTER. **Step 2** Run → establish golden. **Step 3** Refactor to import the shared module. **Step 4** Run → identical. **Step 5** Commit `refactor(drift): check_upstream_drift uses shared anchor_discovery [Ф1]`.

### Ф1 ACCEPTANCE (R3)
- [ ] Local: `test_R1_covers_all_anchor_bearing_patches` PASS; drift-checker output byte-identical.
- [ ] **Rig:** boot 35B → `applied=89 / failed=0` unchanged (Ф1 is read-time only, must not alter apply). 7×6→'42', TPS ~216.

---

## Ф2 — Generator → `pins/<pin>/anchors.json` (R2: true drift from real source)

**Goal:** the generator runs discovery against a PRISTINE clone of the target pin, computes per-anchor meta, classifies from the REAL source, writes the per-pin manifest + `.rej`.

### Task 2.1: Pristine-pin provider

**Files:**
- Create: `sndr/engines/vllm/pristine_source.py` (fetch/cache the pristine vLLM tree for a given pin sha — from the dev148 container's site-packages via the rig, OR `gh` archive). Test it returns a real `chunk.py` matching the live container md5.

### Task 2.2: True-drift classifier

**Files:**
- Modify: `scripts/build_anchor_manifest.py`
- Test: `tests/unit/anchor_sot/test_true_drift.py`

- [ ] **Step 1: Write the R2 test** — given a pristine tree, mutate ONE file's anchor region; assert the classifier returns `anchor_drift` for exactly the affected patch(es) and `ok` for all others (no false `ok`).

```python
def test_R2_synthetic_drift_isolated(pristine_tree, tmp_path):
    mutated = mutate_anchor_region(pristine_tree, target="model_executor/layers/fla/ops/chunk.py")
    report = classify_all(mutated)              # {patch_id: status}
    affected = patches_targeting("fla/ops/chunk.py")
    for pid, status in report.items():
        if pid in affected:
            assert status == "anchor_drift", f"{pid} should drift"
        else:
            assert status != "anchor_drift", f"R2 false-positive on {pid}"
```

- [ ] **Step 2-4:** implement `classify_all()` using `compute_anchor_meta` + exact anchor lookup against the (mutated) pristine source — `ok` iff the anchor is found uniquely + md5 matches; `anchor_drift` iff not found; `upstream_merged` iff an `upstream_drift_marker` is present; `version_gated` from the dispatcher gate. **No heuristic** — real string search on real source (R2).
- [ ] **Step 5: Commit** `feat(anchor): true-drift classifier from pristine source (R2) [Ф2]`.

### Task 2.3: Write the per-pin manifest

**Files:**
- Modify: `scripts/build_anchor_manifest.py` (write `sndr/engines/vllm/pins/<pin>/anchors.json` via the existing `compute_anchor_meta`/`assemble`/`validate_manifest_schema`; emit `.rej` for the drift set)
- Test: `tests/unit/anchor_sot/test_manifest_roundtrip.py`

- [ ] **Step 1: Round-trip test** — build manifest from pristine → apply via the manifest engine → assert the result is byte-identical to the inline-anchor splice result, for EVERY `ok` entry.

```python
def test_manifest_roundtrip_byte_identical(pristine_tree):
    manifest = build_manifest(pristine_tree)          # writes anchors.json (in tmp)
    for entry in manifest.ok_entries():
        via_manifest = apply_via_manifest(pristine_tree, entry)
        via_inline = apply_via_inline_anchor(pristine_tree, entry)
        assert via_manifest == via_inline, f"{entry.patch_id} round-trip mismatch"
```

- [ ] **Step 2-5:** implement + run + commit `feat(anchor): generator writes pins/<pin>/anchors.json + .rej (Ф2)`.

### Ф2 ACCEPTANCE (R3)
- [ ] Local: dev148 manifest covers 100% of `ok` patches; round-trip byte-identical for every entry; R2 synthetic-drift test passes (no false `ok`).
- [ ] **Rig:** generate the manifest against the LIVE dev148 container's pristine site-packages; assert the manifest's `ok` count + `.rej` set match what `check_upstream_drift` reports live (the generator and the live engine agree).

---

## Ф3 — Boot resolver wiring (the apply path uses the per-pin manifest)

**Goal:** at boot, auto-detect the pin, load `pins/<pin>/anchors.json`, apply via Layer-4.5, fall back to inline on md5 miss. THE R3 100%-apply gate.

### Task 3.1: Complete the pin resolver

**Files:**
- Modify: `sndr/engines/vllm/wiring/anchor_manifest.py` (`is_pin_supported` → dir exists; `list_supported_pins` → glob `pins/`; `load_manifest_for_pins` → select `pins/<pin>/anchors.json`, mismatch selects a different file not invalidate-all)
- Test: `tests/unit/anchor_sot/test_pin_resolver.py`

- [ ] TDD: `is_pin_supported("0.23.1_b4c80ec0f")` True iff the dir exists; `_normalize_pin("0.23.1rc1.dev148+gb4c80ec0f")` == `"0.23.1_b4c80ec0f"`; mismatch falls back without disabling other patches. Commit `feat(anchor): per-pin manifest resolver wired (Ф3)`.

### Task 3.2: Wire Layer-4.5 to the per-pin manifest

**Files:**
- Modify: `sndr/kernel/text_patch.py` (`_try_apply_via_manifest` loads the resolved per-pin manifest; on miss → existing exact-match Layer 5)
- Test: `tests/unit/anchor_sot/test_apply_via_per_pin.py`

- [ ] TDD: with a dev148 `anchors.json` present, a patch applies via Layer-4.5 (md5-verified); with the manifest absent/mismatched, it falls back to inline exact-match and still applies. Authoritative+fallback proven. Commit `feat(anchor): Layer-4.5 applies via per-pin manifest, inline fallback (Ф3)`.

### Ф3 ACCEPTANCE (R3 — the big one)
- [ ] **Rig (must be 100%):** generate `pins/0.23.1_b4c80ec0f/anchors.json`, sync to the rig, boot the 35B with the resolver active → EVERY manifest-covered patch applies via Layer-4.5 (md5-verified in the boot log), the rest fall back cleanly, `applied=89 / failed=0` preserved, 7×6→'42', TPS within noise of 216. A boot-log assertion counts manifest-applied vs fallback vs failed; failed must be 0. **100% or it does not ship.**

---

## Ф4 — Bump pipeline (`make rebuild-pin` / `make audit-pin`)

**Goal:** realize "edit one file on a bump".

### Task 4.1: Makefile targets + the bump report

**Files:**
- Modify: `Makefile` (`rebuild-pin PIN=<pin>`: pristine clone → discovery → classify → write `pins/<pin>/anchors.json` + `.rej`; `audit-pin PIN=<pin>`: round-trip + R1 + R2 checks)
- Test: `tests/unit/anchor_sot/test_bump_pipeline.py`

- [ ] TDD: a dry-run `rebuild-pin` against a second pin produces a correct ok/drift split with zero false-`ok` (R2); `audit-pin` fails if any `ok` entry's round-trip mismatches. Commit `feat(anchor): make rebuild-pin/audit-pin bump pipeline (Ф4)`.

### Ф4 ACCEPTANCE (R3)
- [ ] A dry-run bump against a resident second pin (or a synthetic mutated tree) produces a correct manifest + `.rej`; `audit-pin` green; the `.rej` lists exactly the genuinely-drifted anchors and nothing else.

---

## Self-Review

**Spec coverage:** R1→Ф1 (test_R1), R2→Ф2 (test_R2), R3→every phase's rig gate. Authoritative+fallback→Ф3 Task 3.2. JSON→Ф2. Consolidation-first→Ф0. Auto-detect→Ф3 Task 3.1 (resolver consumes `get_vllm_full_version_string` + model/hw detect already exists). Fuzzy=out of scope (not in any task). ✓
**Placeholder scan:** test bodies are concrete; the few `render()`/`classify_all()` entry-point names are finalized when the implementer reads the two pn79 modules + build_anchor_manifest.py at Task start (noted inline as "read first"). ✓
**Type consistency:** `iter_anchor_targets` → `AnchorTarget(patch_id, sub, target_rel, anchor, replacement)` used consistently in Ф1/Ф2/Ф3. `classify_all` → status ∈ {ok, anchor_drift, upstream_merged, version_gated} consistent. ✓

**Execution note:** each phase is independently shippable + rig-gated. Ф1 (discovery/R1) is the safest foundation; Ф0 (consolidation) is the operator's chosen first win. Ф2-Ф4 task code is finalized against Ф1's emergent `AnchorTarget` API at execution time.
