# Pin-Bump Playbook — candidate readiness without touching PROD

Last updated: 2026-07-04 (pipeline v1 + Phase-4 anchor-SOT + `make
bump-pin` one-command promotion). **This is the canonical pin-bump doc.** Two companions: [`ANCHOR_SOT.md`](ANCHOR_SOT.md)
documents the per-pin anchor source-of-truth + `rebuild-pin` /
`bump-preflight` tooling (the Phase-4 regen + bump-gate that runs alongside
the §2 preflight and feeds the §7 promotion);
[`guides/PIN_UPGRADE.md`](guides/PIN_UPGRADE.md) is the short policy +
launcher-template summary that points here.

> Current pin: `0.23.1rc1.dev748+g2dfaae752` (`dev714` =
> `0.23.1rc1.dev714+g09663abde` = rollback; stable slot: `v0.24.0`). The
> single source of truth is [`sndr/pins.yaml`](../sndr/pins.yaml) — see §-1
> below. The dev301 → dev424 bump (2026-06-25) was the first to run the
> full Phase-4 anchor-SOT path (`make rebuild-pin` → `make bump-preflight`)
> on top of this preflight; dev672 (2026-07-01), dev714 (2026-07-02) and
> dev748 (2026-07-04 — see the worked example in §9) followed the same
> path.

## -1. `sndr/pins.yaml` — the pin single source of truth

Every pin string in this repo derives from **`sndr/pins.yaml`**. Fields:

- `current` — the deployed nightly pin (`0.23.1rc1.dev748+g2dfaae752`).
- `rollback` — the retained previous pin (`0.23.1rc1.dev714+g09663abde`),
  per the ≤2-live-nightly-pin policy.
- `stable_release` — the LTS bucket, the third slot in the pin policy
  (`v0.24.0`).
- `canonical_substring` — the `devNNN` token the drift-watcher version
  gate greps for.
- Derived handles for the current pin: `current_sha_short` /
  `current_sha_full`, `current_image` (the explicit-hash
  `vllm/vllm-openai:nightly-<full-sha>` tag), `current_container`, and
  `current_anchor_dir` (under `sndr/engines/vllm/pins/`).

The pin string used to be hand-copied into `guards.KNOWN_GOOD_VLLM_PINS`,
audit-v2 `ALLOWED_MODELDEF_PINS`, `test_pin_gate.EXPECTED_PINS`,
`CANONICAL_PIN_SUBSTRING`, ~11 model YAMLs and 3 hardware images —
forgetting one gave a silent cross-artifact drift. Two commands close that
class:

- `make bump-pin NEW=<pin>` (`scripts/bump_pin.py`) — propagates a new pin
  from the one string into every downstream artifact (§7).
- `make audit-pin-consistency` (`scripts/audit_pin_consistency.py`, a
  `make gates` member) — asserts the SSOT current pin is present in every
  downstream list, so a half-finished bump fails loudly.

End-to-end procedure for bumping the vLLM pin. The centerpiece is the
**pin-bump preflight pipeline**: given a CANDIDATE image already present
on the server, produce a complete patch-matrix readiness report from the
candidate's PRISTINE tree — no GPU, no PROD container interaction, no
`docker pull`.

Tools:

| Step | Tool |
| --- | --- |
| Candidate acquisition | `tools/extract_candidate_tree.sh` |
| Read-only verdict engine | `tools/pin_preflight.py` (or `make preflight`) |
| Upstream merge-state triage | `scripts/audit_upstream_status.py` |
| Anchor drift vs upstream clone | `tools/check_upstream_drift.py` (daily CI) |
| Anchor-SOT regen + bump gate | `make rebuild-pin` / `make bump-preflight` (`scripts/anchor_sot/`, see [`ANCHOR_SOT.md`](ANCHOR_SOT.md)) |
| One-command bump readiness | `scripts/anchor_sot/new_pin_check.py` (coverage sanity + `summarize_rej` + `bump_preflight` vs the auto-resolved previous pin) |
| Fleet dynamic boot gate (§5a) | `scripts/anchor_sot/fleet_boot_smoke.sh` (`make fleet-boot-smoke`) |
| Promotion propagation (§7) | `scripts/bump_pin.py` (`make bump-pin NEW=<pin>`) |
| Cross-artifact sync gate (§7) | `scripts/audit_pin_consistency.py` (`make audit-pin-consistency`) |
| Gate tests | `tests/unit/dispatcher/test_pin_gate.py` |

---

## 0. Preconditions

- The candidate image is ALREADY on the server. Pin policy forbids
  automatic pulls: if it is absent, the extractor exits 2 and prints the
  exact `docker pull` command for the **operator** to run deliberately.
- The repo test suite is green (`make gates`).
- An explicit operator instruction to evaluate/bump exists (pin policy
  step 2 — never chase upstream builds proactively).

## 1. Extract the candidate tree (server-side, read-only)

```bash
tools/extract_candidate_tree.sh \
    --image vllm/vllm-openai:nightly-<sha> \
    --staging /tmp/candidate_pin \
    --rsync-to /tmp/candidate_pin --py-only
```

Mechanics: `docker create` → `docker cp <cid>:/usr/local/lib/python3.12/dist-packages/vllm` →
`docker rm <cid>`. The container is never started; the version probe runs
`docker run --rm --entrypoint python3 ... -c "import vllm; print(vllm.__version__)"`
without `--gpus`.

The staging dir receives `PROVENANCE.json` — image ref, content digest
(`docker inspect` RepoDigests), internal `vllm.__version__`, extraction
timestamp. **Every preflight report embeds this block**, which kills the
pin-provenance-mislabeling class (reports that judged one tree while
claiming another).

`--py-only` rsyncs only `*.py` (+ PROVENANCE.json) to the Mac — the
preflight reads Python sources only (~50 MB instead of multi-GB).

## 2. Run the preflight (fully offline)

```bash
make preflight CANDIDATE_ROOT=/tmp/candidate_pin/vllm JSON_OUT=/tmp/preflight.json
# equivalent:
python3 tools/pin_preflight.py /tmp/candidate_pin/vllm --json-out /tmp/preflight.json
```

JSON report on stdout, human table on stderr. Exit 0 = ready;
1 = actionable verdicts; 2 = invocation error.

What it does (verified architecture):

- Sets `GENESIS_NO_PATCH_CACHE=1` BEFORE any sndr import — the Layer-0
  file cache can otherwise report false IDEMPOTENT from a stale entry.
- Redirects target resolution for ALL wiring modules with ONE
  assignment: `guards.vllm_install_root = lambda: <candidate_root>`
  (resolve_vllm_file dispatches through the guards module attribute —
  `sndr/engines/vllm/detection/guards.py`, resolve_vllm_file).
- Enumerates `sndr.dispatcher.spec.iter_patch_specs()`, keeping
  `implementation_status ∈ {live, full, text_patch, runtime_hook}` with
  an `apply_module`, EXCLUDING `lifecycle ∈ {retired, deprecated}`
  (several `_archive` entries carry contradictory explicit
  `implementation_status: full` — they never apply at runtime).
- Builds every `_make*patcher()` (parameterized builders without
  defaults are reported `UNBUILDABLE` — never guessed) and renders a
  READ-ONLY verdict per patcher. `TextPatcher.apply()` is **never**
  called (it writes). The anchor scan is a pure mirror of
  `TextPatcher._apply_layer5_legacy`; parity is pinned by
  `tests/unit/tools/test_pin_preflight.py::TestLayer5Parity`.
- Modules without a text-patcher builder get a static AST pass over
  their `vllm.*` imports (`from vllm.x import y`,
  `importlib.import_module("vllm...")`, `*_MODULE_PATHS` constants) →
  `BINDING_OK / BINDING_FILE_MISSING / BINDING_SYMBOL_MISSING /
  BINDING_UNRESOLVED`. **Static only** — call-site liveness needs the
  in-container leg (v1.1).

Verdict vocabulary:

| Verdict | Meaning | Action |
| --- | --- | --- |
| `OK` | every required anchor matches exactly once | none |
| `DRIFT_ANCHOR` | required anchor absent | re-derive anchor (step 3) |
| `CHAINED_ANCHOR` | anchors target ANOTHER patch's post-apply output (P18B-on-PN119 class) — not upstream drift | verify the provider's verdict instead; `chained_on` names it |
| `AMBIGUOUS_ANCHOR` | anchor matches >1 location | tighten anchor |
| `DRIFT_FILE_MOVED` | target file gone; up to 3 moved-to candidates listed | re-point target |
| `UPSTREAM_MERGED` | patcher-level drift marker present in pristine file | iron-rule-#11 deep diff (step 4) |
| `SUB_UPSTREAM_MERGED` | per-sub merge markers fired | per-sub deep diff |
| `STALE_RESIDUE` | patch marker in a PRISTINE tree | residue or marker collision — investigate |
| `UNBUILDABLE` | builder needs args we refuse to guess | wire an explicit probe |
| `IMPORT_FAIL` | wiring module failed to import | fix module |
| `RUNTIME_BINDING` | no text patcher; static binding result attached | check `binding_ok` |

md5-gated diff patches (PN119 class) are evaluated natively when the
module follows the convention `<NAME>_PRE_PATCH_MD5` +
`<NAME>_DIFF_PATH` + `_target_path()` (resolving through
`resolve_vllm_file` so the alternate-root seam redirects it): md5
match → `OK`, mismatch → `DRIFT_ANCHOR` (the patch self-retires —
regenerate diff + md5), marker in pristine → `STALE_RESIDUE`. The
diff's post-apply text also feeds the chain pass, so dependents like
P18B_TEXT classify as `CHAINED_ANCHOR` instead of false drift. New
md5+diff patches MUST follow this attribute convention.

Plus three tree-wide passes:

- **`UPSTREAM_MARKERS`** (24-entry table in
  `sndr/engines/vllm/upstream_compat.py`) — `newly_merged` hits feed the
  iron-rule-#11 queue and count as actionable.
- **Version ranges** — every spec's `applies_to.vllm_version_range`
  evaluated against the candidate's internal version with the SAME
  evaluator the dispatcher uses (`sndr.compat.version_check`).
  Enforcement is two-tier (`dispatcher/decision.py` `should_apply`
  rule 1, verified live 2026-06-10): `default_on=True` out-of-range →
  STRICT_SKIP (silently disabled on the candidate); opt-in patches
  with a truthy env flag STILL APPLY — operator override wins over
  `applies_to`, the stale range only degrades doctor/recommend
  diagnostics. The report splits the list accordingly
  (`out_of_range_detail`). **A long list usually means the registry
  ranges were not bumped during the previous promotion.** Corollary:
  retiring a patch by capping its range does NOT stop it on rigs whose
  launchers still export its env flag — set `lifecycle: retired` (and
  remove the flag from launch configs) for a real retirement.
- **SELF_COLLISION lint** (the PN369 class) — a patcher's own
  replacement text or marker containing one of its
  `upstream_drift_markers` produces deterministic false
  "upstream merged" skips. Reported regardless of candidate content;
  `[Genesis`-prefixed markers are tagged `defended` (custom apply()
  wrappers skip them by convention — stock `TextPatcher.apply()` does
  NOT).

Also reported: anchor-manifest staleness (`sndr/manifests/anchor_manifest.json`
`pins.vllm` vs candidate version) — regenerate the manifest before
promotion if stale.

## 3. Fix-drifts loop (verified-anchor workflow)

For each `DRIFT_ANCHOR` / `AMBIGUOUS_ANCHOR` / `DRIFT_FILE_MOVED`:

1. Open the candidate file (the extracted tree IS the ground truth —
   never trust the patched PROD container: its rw layer carries markers
   applied by older repo states and masks anchor rot).
2. Re-derive the anchor from the pristine candidate source; keep it
   minimal but unique (1 match). For moved files start from the
   report's `moved_to_candidates`.
3. Update the wiring module; re-run `make preflight` until the row
   flips to `OK`.
4. One patch per commit, with the candidate version in the message.

## 4. Iron-rule-#11 deep-diff queue

For every `UPSTREAM_MERGED` / `SUB_UPSTREAM_MERGED` row and every
`newly_merged` marker:

1. List merged PRs in the window:
   `gh api repos/vllm-project/vllm/compare/<current_sha>...<candidate_sha>`.
2. Cross-reference `upstream_pr` via `scripts/audit_upstream_status.py`
   (offline mode: `--skip-network`).
3. READ both sides — our patch source AND the candidate file — and diff
   line-by-line. Three outcomes (never title-match):
   - byte-identical → retire (`lifecycle="retired"` + upper-bound
     `vllm_version_range` + `superseded_by`),
   - ours does MORE → update patch, keep the extras,
   - different approach → keep, verify anchors clean.

## 5. Boot smoke on a THROWAWAY container

Never on PROD. Start a disposable container from the candidate image
with the Genesis tree mounted, watch the boot apply summary
(`applied=N skipped=M failed=0`), then remove it. Compare the
skip/apply sets against the preflight prediction — disagreements are
pipeline bugs or env-conditional patches; investigate both.

## 5a. Fleet boot-smoke gate (all models, automated) — `make fleet-boot-smoke`

The static preflight (steps 2–4) and the single-model boot (step 5) miss a whole
class: a **runtime boot regression where Genesis `apply=failed=0` but the engine
still crashes on upstream config validation**. Concrete case (dev424 → dev672):
upstream began forcing `disable_chunked_mm_input` for Gemma-4 (mm-prefix-lm),
which then asserts `max_num_batched_tokens >= max_tokens_per_mm_item (2496)` —
but **G4_09**'s #39914 SWA-prefill clamp was 2048. Both Gemma-4 failed to boot;
apply was failed=0, so no static gate flagged it. Only a live boot surfaced it
(fixed: G4_09 default 2048 → 3072 + MM-item-aware floor).

`make fleet-boot-smoke` automates the fleet-wide dynamic gate — it serially boots
every prod preset on the candidate image and per model asserts health-200 +
`apply failed=0` + `boot_smoke_probe.py` (coherent generation + streaming
tool-call, no content-leak). Non-zero exit ⇒ a model regressed at runtime ⇒ do
NOT promote:

```bash
make fleet-boot-smoke SSH_HOST=<user@host> IMAGE=<candidate-tag> \
  FLEET='prod-qwen3.6-27b-tq-k8v4:qwen3.6-27b \
         prod-gemma4-31b-tq-default:gemma-4-31b \
         prod-gemma4-26b-multiconc:gemma-4-26b-a4b:notool \
         prod-diffusiongemma-tp2:diffusiongemma'
```

It stops the live engine for the window and always restores it (trap EXIT). Run
after the static preflight passes and before promotion (step 7). The `:notool`
suffix skips the tool-call check for throughput presets that omit a tool parser.

## 5b. Tokenizer-fingerprint gate (in-container, BEFORE any bench)

Lesson from upstream #45109 (AWQ expected outputs changed under the
Transformers v5 tokenizer): a silent tokenizer-behavior change across
a pin bump produces output diffs that get misattributed to Genesis
patches — hours of misdirected bisection. AWQ/AutoRound checkpoints
are exactly the affected class. <1 min check; run it on every bump
for every affected model BEFORE step 6:

```bash
# Inside the throwaway container from step 5 (transformers available):
#   first bump for a model -> store the baseline
python3 tools/tokenizer_fingerprint.py --model-path /models/<model> \
    --json-out evidence/tokenizer_fp_<model>_<pin>.json
#   subsequent bumps -> compare against the previous pin's baseline
python3 tools/tokenizer_fingerprint.py --model-path /models/<model> \
    --compare evidence/tokenizer_fp_<model>_<prev_pin>.json
# equivalent: make tokenizer-fingerprint MODEL_PATH=... [COMPARE=...]
```

Exit 0 (MATCH) — the tokenizer is not the variable; any output diff in
steps 5-6 is patch-attributable. Exit 1 (MISMATCH, drifted prompt
classes named) — STOP: re-baseline expected outputs and check the
model's `tokenizer_class` against the pin's
`_MODEL_TYPES_WITH_INCORRECT_TOKENIZER_CLASS` hook
(`transformers_utils/tokenizer.py` lineage) before blaming patches.
The canonical prompt set is embedded and versioned
(`genesis-canonical-v1`); fingerprints are only comparable within the
same prompt set.

## 6. Canonical bench vs reference_metrics

`tools/genesis_bench_suite.py --quick` per affected model, compared
against the YAML `reference_metrics` (canonical methodology ONLY —
custom scripts carry a 5-25% systematic offset). One config at a time.

## 7. Promotion — `make bump-pin` is the canonical step

Only after steps 2-6 are clean. The propagation that used to be five
hand-edits is now **one command** (idempotent — safe to re-run):

```bash
make bump-pin NEW=0.23.1rc1.devNNN+g<sha>    # add DRY=1 for a dry run
# equivalent: python3 scripts/bump_pin.py 0.23.1rc1.devNNN+g<sha> \
#     --sha-full <40-hex upstream sha>
```

Pass `--sha-full` (added 2026-07-04 after the dev748 promotion left it
stale): the full upstream SHA cannot be derived from the version
string's short hash, so without the flag `current_sha_full` in
`sndr/pins.yaml` is NOT updated and the script prints a loud WARN.
Source it from the image label `org.opencontainers.image.revision`.

What it propagates from the one pin string:

1. `sndr/pins.yaml`: `current` → NEW, previous current → `rollback`, and
   refreshes `canonical_substring` / `current_sha_short` /
   `current_anchor_dir` / `current_image` / `current_container`.
2. `scripts/audit_v2_runtime_pins.py`: `CANONICAL_PIN_SUBSTRING` → the new
   `devNNN`.
3. Every vLLM model YAML: `vllm_pin_required` → NEW (llama.cpp null lanes
   skipped).
4. Appends NEW to `guards.KNOWN_GOOD_VLLM_PINS`
   (`sndr/engines/vllm/detection/guards.py`), `ALLOWED_MODELDEF_PINS`, and
   `test_pin_gate.EXPECTED_PINS` if absent (with a dated "validate me"
   comment). Run `make test-pin-gate` to confirm the paired update.

Then the two steps its docstring keeps deliberately manual:

1. `make rebuild-pin SSH_HOST=… [CONTAINER=…] [IMAGE=…]` — regenerate the
   per-pin anchor manifest on the rig (the manifest's `pins.vllm` must
   equal the new pin; see [`ANCHOR_SOT.md`](ANCHOR_SOT.md)).
2. `make audit-pin-consistency` — the cross-artifact sync gate
   (`scripts/audit_pin_consistency.py`): asserts the SSOT current pin is
   present in `KNOWN_GOOD_VLLM_PINS` / `ALLOWED_MODELDEF_PINS` /
   `EXPECTED_PINS` / `CANONICAL_PIN_SUBSTRING` / every builtin model YAML,
   and that the anchor dir exists and the rollback pin stays known-good.
   Exit 1 lists the exact fix. It is a `make gates` member, so CI catches
   a half-finished bump too.

Remaining manual editorial steps (not covered by `bump_pin.py`):

1. README badge + CHANGELOG entry.
2. Hardware `image_digest` (content-addressed — capture separately).
3. **Bump the `applies_to.vllm_version_range` upper bounds** for
   patches validated on the new pin. Evidence bar (iron rule #11 —
   no blanket bumps): a patch earns a bump only with boot-log proof
   of `applied` (or `already applied (marker present)`) on the new
   pin. Worked example from the 0.22.1 promotion backfill
   (2026-06-10): the validation run surfaced 34 stale `<0.22.0`
   ranges → boot-log triage split them 26 applied (bumped to
   `<0.23.0`) / 7 disabled-by-env (caps kept — they honestly record
   the last validated window) / 1 upstream-merged PN90 (cap kept —
   intentional retirement gate, double-defended by its drift marker).

## 8. Tag rotation (pin policy)

- Re-tag `vllm/vllm-openai:nightly` → the new canonical pin.
- Keep the explicit-hash tag for the new pin; keep the PREVIOUS pin
  (one tag) for rollback during the validation window.
- After full validation: delete the oldest pin. The server holds at
  most current + previous. Pin by immutable digest in YAMLs (class-10:
  Docker Hub purges nightly tags).

## 9. Worked example — dev714 → dev748 (2026-07-04, the newest promotion)

The full playbook executed against the live rig in one
operator-authorized maintenance window:

1. **Preflight (pre-window)** — 34-rev bump; 27/34 anchors intact on
   the 10 changed files. The only 2 genuinely drifted patches — **P100**
   (6 anchors) and **PN351** (launch variant) — were re-anchored
   **dual-variant**, spanning both pins, so the same tree applies
   cleanly on dev714 (rollback) and dev748.
2. **Boot** — `vllm-35b-dev748` from `nightly-2dfaae752`: health 200 in
   330 s, boot apply **applied=87 / failed=0** — an apply profile
   identical to dev714's.
3. **Bench (§6)** — canonical suite vs the same-day dev714 reference
   (234.16): wall_TPS **242.55** (CV 6.9%) — **parity within CV, no
   regression** (the raw +3.5% is not significant per the BENCHMARKS
   CV rules), decode_TPOT
   3.9 ms, TTFT 84.5 ms, tool-call 7/7, MTP K=5 accept 0.653,
   ctx-scaling 1K→32K LINEAR_OK (endpoint 0.84).
4. **Promotion receipts ×3 (§7)** — the new pin recorded in
   `guards.KNOWN_GOOD_VLLM_PINS`, `ALLOWED_MODELDEF_PINS` and
   `test_pin_gate.EXPECTED_PINS` (plus `sndr/pins.yaml` rotation and
   the 11 model YAMLs via `make bump-pin`).
5. **Anchor-manifest rebuild** — `sndr/engines/vllm/pins/0.23.1_2dfaae752/`
   (48 files) regenerated from the live container + bare image via
   `rebuild_pin.sh`, run against the rig-side main-sync tree
   (`$HOME/gvp-mainsync`) — the `REPO` tree **must be
   container-visible** for the rebuild (see
   [`ANCHOR_SOT.md`](ANCHOR_SOT.md) §5 for the pitfalls hit).
6. **Tag rotation (§8)** — `:nightly` re-tagged to dev748 (+ full-sha
   tag), dev714 kept as rollback, dev672 tag + image dropped per the
   ≤2-pin policy.
7. **Gate bug found + fixed during the window** —
   `audit_pin_consistency`'s `EXPECTED_PINS` parser used a fixed
   8000-char window from a bare `EXPECTED_PINS` marker; the receipt
   comments outgrew it AND the marker first matched the module
   docstring. It now anchors on `EXPECTED_PINS = (` and scans to the
   tuple's real closing paren.
8. **Tooling follow-up** — `scripts/bump_pin.py` gained `--sha-full`
   (§7): the promotion had silently left `current_sha_full` stale.

---

## The ten empirical failure classes this pipeline guards against

1. **Anchor drift** (skill class 5) — upstream refactor moves/changes
   the anchored region → `DRIFT_ANCHOR` / `AMBIGUOUS_ANCHOR`.
2. **File move/split** — e.g. the gdn/-split:
   `model_executor/layers/mamba/gdn_linear_attn.py` →
   `gdn/{qwen,olmo,kimi}_gdn_linear_attn.py` → `DRIFT_FILE_MOVED` with
   moved-to candidates.
3. **Unnoticed upstream merge** (skill class 4) — duplicate application
   risk / silent redundancy → `UPSTREAM_MERGED` + `UPSTREAM_MARKERS`
   pass + iron-rule-#11 queue.
4. **False idempotent from Layer-0 cache** — preflight forces
   `GENESIS_NO_PATCH_CACHE=1` before any sndr import.
5. **Patched-layer masking** ("works on PROD" illusion) — the PROD rw
   layer carries markers from older repo states; P18B_TEXT shows
   "idempotent" live while its anchors are GONE from the pristine
   tree. Preflight always judges the pristine extraction.
6. **Pin-provenance mislabeling** — PROVENANCE.json (digest + internal
   version) embedded in every report.
7. **Self-colliding drift markers** (PN369 class) — own replacement
   text fires the patch's drift marker → deterministic false
   "upstream merged" skip → SELF_COLLISION lint.
8. **Version-range staleness** — registry ranges not bumped at
   promotion. Silently disables `default_on=True` patches
   (STRICT_SKIP); opt-in patches keep applying via env override but
   doctor/recommend diagnostics degrade → out-of-range list computed
   with the dispatcher's own evaluator, split by enforcement tier.
9. **Runtime-binding breakage** — monkey-patch modules whose
   `vllm.*` import targets were renamed/removed (e.g.
   `v1/spec_decode/eagle3`, `apply_fp8_block_linear`) →
   `BINDING_FILE_MISSING` / `BINDING_SYMBOL_MISSING`.
10. **Tokenizer-behavior drift** (the #45109 class) — the candidate
    image ships a different Transformers major whose tokenizer
    segments the same prompts differently; output diffs then get
    misattributed to Genesis patches → step 5b
    `tools/tokenizer_fingerprint.py --compare` (exit 1 = re-baseline
    first, AWQ/AutoRound checkpoints are the proven-affected class).

## v1 limitations / v1.1 roadmap

- **SHA-window gh triage**: auto-join `compare/<old>...<new>` PR list
  with registry `upstream_pr` fields to pre-sort the iron-rule-#11
  queue (v1 leaves this to `scripts/audit_upstream_status.py`).
- **In-container liveness leg** (`VERIFY_IN_CONTAINER`): binding checks
  are static; a symbol may exist while its call-site contract changed.
  v1.1 adds a throwaway-container `python3 -c "import …"` probe per
  binding.
- Env-conditional builders (anchors derived from
  `resolve_decode_tune()` etc.) are evaluated with Mac-side defaults;
  the boot smoke (step 5) covers server-env divergence.
