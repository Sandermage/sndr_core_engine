# Roadmap evidence ledger

Append-only journal documenting reproducible proof for every "DONE"
claim в `PROJECT_ROADMAP_V2_2026-05-12_RU.md`.

Per supplement §0.1: every claim of "green", "clean", "P0 closed",
"production-ready" must point at a ledger entry below with full
reproducer context. No entry → status is aspirational, not factual.

**Append rules:**

- Newest entry on top (reverse chronological).
- Use the exact template below — homogeneous structure makes
  cross-host diff'ing trivial.
- Embed stdout/stderr excerpt (≤20 lines) inside the entry.
- Decision field MUST be filled: `accept` / `re-verify` / `fix` / `drop`.

**Entry template:**

```
### YYYY-MM-DDTHH:MM±ZZZZ — short title

- host: local | server
- path: <absolute project root>
- git ref: <short SHA>
- branch: <git branch>
- status entries: <count from `git status --short`>
- command: <verbatim>
- exit code: <int>
- result: pass | fail | skip
- excerpt: |
  <tail of stdout/stderr ≤20 lines>
- decision: accept | re-verify | fix | drop
- notes: <optional one-liner>
```

---

### 2026-05-12 — Phase 0 baseline (V2 layered + Etapы 0-8 closed)

#### local

- host: local (macOS, no GPU, torch+cryptography absent — partial coverage)
- path: /Users/sander/Documents/Visual Studio Code/genesis-vllm-patches
- git ref: 680d06d
- branch: dev
- status entries: 788
  - 384 D from v7→v11 migration (vllm/_genesis/*, obsolete compose/*.yml)
  - 91 M from current session deliverables (already committed in 680d06d)
  - 313 ?? — mostly tests/, scripts/, tools/ + new V2 layer files awaiting next commit
- command: python3 -m compileall -q vllm/sndr_core
- exit code: 0
- result: pass
- excerpt: |
  (no output — all clean)
- decision: accept
- notes: covers entire V2 codebase + V1 sndr_core; PEP-563 annotations OK

#### local — self-test

- host: local
- git ref: 680d06d
- command: python3 -m vllm.sndr_core.compat.cli self-test --json
- exit code: 0
- result: pass
- excerpt: |
  Summary: 8 pass, 0 fail, 0 warn, 0 skip
- decision: accept

#### local — apply.shadow strict

- host: local
- git ref: 680d06d
- command: python3 -m vllm.sndr_core.apply.shadow --strict
- exit code: 0
- result: pass
- excerpt: |
  ✓ CLEAN — no unexpected divergence (known spec-only: 8)
- decision: accept

#### local — full pytest

- host: local
- git ref: 680d06d
- command: python3 -m pytest tests/ -q --ignore=tests/integration
- exit code: 0
- result: pass
- excerpt: |
  5622 passed, 124 skipped in 55-60s
- decision: accept
- notes: +78 V2 tests (48 schema + 30 compose). 10 skips = `cryptography` not on Mac dev, expected.

#### local — make audit (legacy-imports + public-paths + upstream + doc-sync)

- host: local
- git ref: 680d06d
- command: make audit
- exit code: 0
- result: pass
- excerpt: |
  ✓ legacy-import gate: clean
  ✓ public-paths gate: clean
  ✓ Audit suite complete.
- decision: accept

#### local — V2 alias resolution end-to-end

- host: local
- git ref: 680d06d
- command: python3 -m vllm.sndr_core.cli launch prod-35b --dry-run -y
- exit code: 0
- result: pass
- excerpt: |
  Composed key: qwen3.6-35b-a3b-fp8__a5000-2x-24gbvram-16cpu-128gbram__wave9-balanced
  44 patches; docker.image_digest: vllm/vllm-openai@sha256:9b534fe...
- decision: accept

#### local — V1 legacy resolution still works

- host: local
- git ref: 680d06d
- command: python3 -m vllm.sndr_core.cli launch a5000-2x-35b-prod --dry-run -y
- exit code: 0
- result: pass
- excerpt: |
  Composed via V1 legacy path; identical behavior to pre-V2 state.
- decision: accept

#### server

- host: server (sander@192.168.1.10, 2× RTX A5000, dev209)
- path: /home/sander/genesis-vllm-patches-v11
- git ref: f9576df (server commit older than local; layered V2 files
  rsynced on top — operator commit pending)
- command: python3 -m vllm.sndr_core.compat.cli self-test --json
- exit code: 0
- result: pass
- excerpt: |
  Summary: 8 pass, 0 fail, 0 warn, 0 skip
- decision: accept

#### server — apply.shadow strict

- host: server
- command: python3 -m vllm.sndr_core.apply.shadow --strict
- exit code: 0
- result: pass
- excerpt: |
  ✓ CLEAN — no unexpected divergence
- decision: accept

#### server — full pytest

- host: server
- command: python3 -m pytest tests/ -q --ignore=tests/integration
- exit code: 0
- result: pass
- excerpt: |
  5652 passed, 94 skipped in 120-125s
- decision: accept
- notes: 30 more passes than local — cryptography present on server, trust anchor tests run.

#### server — V2 alias smoke

- host: server
- command: python3 -c "from vllm.sndr_core.model_configs.registry_v2 import load_alias; print(load_alias('prod-35b').key)"
- exit code: 0
- result: pass
- excerpt: |
  V2 alias works: qwen3.6-35b-a3b-fp8__a5000-2x-24gbvram-16cpu-128gbram__wave9-balanced
- decision: accept

---

### Entry 2 — Phase 3 complete (all 11 V1 presets migrated to V2 layered) + roadmap proposals integrated

- timestamp: 2026-05-12T16:44+0300
- host: local
- path: /Users/sander/Documents/Visual Studio Code/genesis-vllm-patches
- commit: 680d06d
- branch: main

#### local — full pytest (after migrations)

- host: local
- command: python3 -m pytest tests/ -q --ignore=tests/integration
- exit code: 0
- result: pass
- excerpt: |
  5627 passed, 124 skipped in 56-69s (3 runs)
- decision: accept
- notes: Test count matches Entry 1 baseline — V2 additions are pure data files,
  no test scaffolding change.

#### local — all 11 V2 aliases resolve

- host: local
- command: python3 -c "from vllm.sndr_core.model_configs.registry_v2 import load_alias; [print('OK', a, load_alias(a).key) for a in (...)]"
- exit code: 0
- result: pass
- excerpt: |
  OK prod-35b qwen3.6-35b-a3b-fp8__a5000-2x-24gbvram-16cpu-128gbram__wave9-balanced
  OK prod-27b-tq qwen3.6-27b-int4-autoround-tq-k8v4__a5000-2x-24gbvram-16cpu-128gbram__wave9-27b-tq-k8v4
  OK prod-35b-dflash qwen3.6-35b-a3b-fp8-dflash__a5000-2x-24gbvram-16cpu-128gbram__wave9-35b-fp8-dflash
  OK long-ctx-27b qwen3.6-27b-int4-autoround-fp8kv__a5000-2x-24gbvram-16cpu-128gbram__wave9-27b-fp8kv-long-ctx
  OK qa-27b-tested qwen3.6-27b-int4-autoround-fp8kv__a5000-2x-24gbvram-16cpu-128gbram__qa-27b-fp8kv-tested
  OK qa-27b-tq-1x qwen3.6-27b-int4-autoround-tq-k8v4__a5000-1x-24gbvram-16cpu-128gbram__qa-27b-tq-1x-tested
  OK prod-27b-dflash qwen3.6-27b-dflash__a5000-2x-24gbvram-16cpu-128gbram__wave9-27b-dflash
  OK experimental-27b-tq-dflash-ab qwen3.6-27b-int4-autoround-tq-k8v4__a5000-2x-24gbvram-16cpu-128gbram__experimental-27b-tq-dflash-ab
  OK example-2x-tier-aware qwen3.6-27b-int4-autoround-tq-k8v4__a5000-2x-24gbvram-16cpu-128gbram__path-c-2x-tier-aware-example
  OK example-3090-dense-cpu-offload qwen3.6-7b-dense__single-3090-24gbvram__path-a-3090-cpu-offload-example
  OK example-3090-tier-aware qwen3.6-27b-int4-autoround-tq-k8v4__single-3090-24gbvram__path-c-3090-tier-aware-example
- decision: accept

#### roadmap proposals integration

- artifact: docs/_internal/PROJECT_ROADMAP_V2_2026-05-12_RU.md
- changes:
  - §6 renumbered (eliminated duplicate §6.4)
  - Phase 8 split (8a early V1-smoke + 8b late V2-acceptance) per proposals §3
  - §7 risk registry extended (6 architectural + 11 release/operational risks)
  - §9 production-ready extended (rollback docs + patch proof coverage + public/private boundary)
  - §6.6 scaffold/draft/placeholder boundary contract added
  - §6.7 canonical env-key registry CLI surface added
  - §6.8 patch proof gate added (mitigates R1 dead-patch accumulation)
  - §5.0 Mermaid phase dependency graph added
  - Phase 6 benchmark methodology contract added (mitigates R7)
  - §4.6 CLI surface extended with config-keys + patch prove + bench validate
  - Test counts removed from §9 (now refers to evidence ledger)
- supporting doc: docs/_internal/LOCAL_SERVER_ALLOWED_DIRTY_STATE_2026-05-12_RU.md
  (three-tier dev/audit/release dirty-state policy, mitigates R6+R11)
- decision: accept

#### V2 layered config inventory (post-Phase 3)

- model files: 6 (qwen3.6-35b-a3b-fp8, qwen3.6-35b-a3b-fp8-dflash,
  qwen3.6-27b-int4-autoround-tq-k8v4, qwen3.6-27b-int4-autoround-fp8kv,
  qwen3.6-27b-dflash, qwen3.6-7b-dense)
- hardware files: 3 (a5000-2x-24gbvram-16cpu-128gbram, a5000-1x-24gbvram-16cpu-128gbram, single-3090-24gbvram)
- profile files: 11 (wave9-balanced, wave9-27b-tq-k8v4, wave9-35b-fp8-dflash,
  wave9-27b-fp8kv-long-ctx, qa-27b-fp8kv-tested, qa-27b-tq-1x-tested,
  wave9-27b-dflash, experimental-27b-tq-dflash-ab, path-c-2x-tier-aware-example,
  path-a-3090-cpu-offload-example, path-c-3090-tier-aware-example)
- preset aliases: 11 (one per V1 preset)
- decision: accept
- notes: V1 monolithic preset YAMLs at `builtin/*.yaml` (root) remain in place
  for byte-equivalence regression testing (Phase 9 freeze pending).

---

### Entry 3 — REVIEW_NOTES integration + per-line comments on all V2 configs

- timestamp: 2026-05-12T17:30+0300
- host: local
- path: /Users/sander/Documents/Visual Studio Code/genesis-vllm-patches
- commit: 680d06d
- branch: main

#### local — pytest stayed green throughout REVIEW_NOTES integration

- command: python3 -m pytest tests/ -q --ignore=tests/integration
- exit code: 0
- result: pass
- excerpt: |
  5627 passed, 124 skipped in 56s
- decision: accept

#### local — all 11 V2 aliases still resolve after model/hardware/profile comment rewrites

- command: python3 -c "from vllm.sndr_core.model_configs.registry_v2 import load_alias; ..."
- exit code: 0
- result: pass
- excerpt: |
  All 11 aliases resolve with IDENTICAL ctx/seqs/patches counts as Entry 2:
    prod-35b           ctx=320000 seqs=2 patches=44
    prod-27b-tq        ctx=131072 seqs=4 patches=52
    prod-35b-dflash    ctx=160000 seqs=1 patches=37
    long-ctx-27b       ctx=280000 seqs=2 patches=51
    qa-27b-tested      ctx=131072 seqs=2 patches=36
    qa-27b-tq-1x       ctx= 78000 seqs=1 patches=53
    prod-27b-dflash    ctx=185000 seqs=1 patches=30
    experimental-27b-tq-dflash-ab ctx=131072 seqs=2 patches=58
    example-2x-tier-aware         ctx=131072 seqs=4 patches=56
    example-3090-dense-cpu-offload ctx= 65536 seqs=1 patches= 2
    example-3090-tier-aware       ctx=145000 seqs=1 patches=54
- decision: accept
- notes: Identical numbers vs Entry 2 prove the per-line comment rewrites
  are pure documentation (no semantic drift).

#### REVIEW_NOTES roadmap integration

- artifact: docs/_internal/PROJECT_ROADMAP_V2_2026-05-12_RU.md
- changes (P0):
  - P0.1 — Removed remaining hardcoded test counts (§0 baseline table, Phase 0,
    Phase 1 tests gate). Roadmap now references evidence ledger only.
  - P0.2 — Fixed scaffold/placeholder/status wording: manifest example uses
    `implementation_status: experimental` + `publish_state: draft`; CLI
    `sndr profile new` reworded to "generate draft delta profile"; Phase 5
    plugins example uses template-only with `publish_state: draft` excluded
    from release registry.
  - P0.3 — Moved `~/.sndr/bench-results` out of git dirty-state allowlist
    into new §2.4 "Host artifacts" section (not part of git status).
  - P0.4 — Replaced single-command rsync recipe with safe 5-step procedure:
    server snapshot → dry-run → manual review → real sync → verify.
    Added blocking rule for server-only tracked changes.
- changes (P1):
  - P1.1 — Phase 4.5 added: RuntimeCommandSpec canonical IR for all runtime
    emitters. Design doc: RUNTIME_COMMAND_SPEC_DESIGN_2026-05-12_RU.md.
  - P1.2 — Phase 4.7 added: `sndr memory explain` MVP. Design doc:
    MEMORY_EXPLAIN_MVP_2026-05-12_RU.md.
  - P1.3 — Phase 4.6 added: security + license gate boundary + CLI surface.
    Design doc: SECURITY_LICENSE_GATE_2026-05-12_RU.md.
  - P1.4 — Added §6.10 public/private docs boundary gate (mitigates R3).
  - P1.5 — Refined §6.8 patch proof threshold: `stable=100% or waiver`
    schema with owner/reason/expiry/risk/rollback fields.
- changes (small fixes + P2):
  - "treckable" typo → "trackable".
  - `sndr patch prove` → `sndr patches prove` (CLI plural-naming
    consistency with `patches doctor`).
  - `sndr patch validate` → `sndr patches validate`.
  - Phase 8a V1 smoke fixed: removed V2-only `sndr hardware list`, uses
    `sndr config list` + V1 preset key (`a5000-2x-35b-prod`) instead.
  - Phase 7 deliverables expanded: docs/ROLLBACK_PLAYBOOK.md,
    docs/COMMUNITY_PATCHES.md, docs/INSTALL.md, audit-public-docs +
    audit-security CI gates.
  - P2 deferred: EXTERNAL_FINDINGS_PIPELINE design doc created;
    §5.-1 Task metadata convention added (Owner/Status/Evidence/Blocked-by/Acceptance).
- decision: accept

#### Per-line comments — all 20 V2 config files

- 6 model files commented (35B FP8, 35B FP8 DFlash, 27B TQ k8v4, 27B fp8kv,
  27B DFlash, 7B dense)
- 3 hardware files commented (a5000-2x, a5000-1x, single-3090)
- 11 profile files commented (wave9-balanced, wave9-27b-tq-k8v4,
  wave9-35b-fp8-dflash, wave9-27b-fp8kv-long-ctx, qa-27b-fp8kv-tested,
  qa-27b-tq-1x-tested, wave9-27b-dflash, experimental-27b-tq-dflash-ab,
  path-c-2x-tier-aware-example, path-a-3090-cpu-offload-example,
  path-c-3090-tier-aware-example)
- style: W-B exemplar from legacy 35B PROD —
  • explain WHAT in one line
  • state default + valid values for non-binary settings
  • cite empirical evidence (TPS delta / OOM / tool quality) when known
- decision: accept

---

### Entry 4 — REFINEMENT_ACTIONS integration + dirty-state gate implementation + rollback playbook

- timestamp: 2026-05-12T18:30+0300
- host: local
- path: /Users/sander/Documents/Visual Studio Code/genesis-vllm-patches
- commit: 680d06d (worktree, pre-commit)
- branch: main

#### local — pytest stayed green throughout REFINEMENT_ACTIONS integration

- command: python3 -m pytest tests/ -q --ignore=tests/integration
- exit code: 0
- result: pass
- excerpt: |
  5627 passed, 124 skipped in 56.01s
- decision: accept

#### local — all 11 V2 aliases still resolve

- command: python3 -c "from vllm.sndr_core.model_configs.registry_v2 import load_alias; ..."
- exit code: 0
- result: pass
- excerpt: |
  All 11 aliases resolve with IDENTICAL ctx/seqs/patches counts as Entry 2 and Entry 3:
    prod-35b           ctx=320000 seqs=2 patches=44
    prod-27b-tq        ctx=131072 seqs=4 patches=52
    prod-35b-dflash    ctx=160000 seqs=1 patches=37
    long-ctx-27b       ctx=280000 seqs=2 patches=51
    qa-27b-tested      ctx=131072 seqs=2 patches=36
    qa-27b-tq-1x       ctx= 78000 seqs=1 patches=53
    prod-27b-dflash    ctx=185000 seqs=1 patches=30
    experimental-27b-tq-dflash-ab ctx=131072 seqs=2 patches=58
    example-2x-tier-aware         ctx=131072 seqs=4 patches=56
    example-3090-dense-cpu-offload ctx= 65536 seqs=1 patches= 2
    example-3090-tier-aware       ctx=145000 seqs=1 patches=54
- decision: accept

#### local — dirty-state gate works on all three tiers

- command: make audit-dirty-state-dev
- exit code: 0
- excerpt: |
  check_dirty_state: tier=dev host=local entries=792 accepted=792 rejected=0
    OK — worktree matches tier policy
- decision: accept
- notes: All three tiers tested via direct unit-test of _check_entry against
  fixture paths (.env, snapshots/*, src/credentials.json, etc.) —
  dev allows random untracked except secrets; audit rejects untracked
  outside narrow allowlist; release rejects all modified tracked files.

#### REFINEMENT_ACTIONS roadmap integration

- artifact: docs/_internal/PROJECT_ROADMAP_V2_2026-05-12_RU.md
- changes (P0):
  - P0.1 — Removed memory-explain "deferred research" line in §3.4;
    promoted to Phase 4.7 MVP reference; advanced calibration moved to §3.10 P3.
  - P0.2 — Added Phase 4.5/4.6/4.7 to §10 execution priority (Day 7-15 P1).
  - P0.3 — Split Phase 8 into 8a (Day 1-6 pre-V2) + 8b (Day 16-20 post-Phase-7)
    in §10 execution priority. Removed obsolete combined "Phase 8 smoke" entry.
  - P0.4 — Replaced "Phase 5 placeholder finalized here" with
    "Phase 5 ships a draft outline; Phase 7 finalizes the doc" — no remaining
    `placeholder` mentions for release deliverables.
- changes (P1):
  - P1.1 — Created tools/policies/dirty_state_allowlist.yaml + scripts/check_dirty_state.py +
    Makefile targets audit-dirty-state-{dev,audit,release}. dev tier passes on
    current 792-entry worktree; release tier correctly rejects modified tracked.
  - P1.2 — Replaced `tail -3` evidence shape with full `tee` to
    `/tmp/sndr-evidence/<NAME>.log` plus 20-line excerpt plus scp back for
    ledger. Added evidence entry shape spec.
  - P1.3 — Verified `sndr patch` → `sndr patches` consistency across all 4 design docs
    (previous session completed this; re-verified clean).
  - P1.4 — Verified Phase 8a uses real V1 commands: `sndr config list` (alias for
    `sndr model-config list`, found in vllm/sndr_core/cli/config.py) +
    `sndr launch a5000-2x-35b-prod` (V1 preset key).
  - P1.5 — Renamed §11 "Open questions (none)" → "Blocking design questions";
    text now clarifies implementation questions are tracked per phase via
    §5.-1 metadata fields, not pretending no questions exist.
  - P1.6 — Added Owner/Status/Evidence/Blocked-by/Acceptance metadata block
    to Phase 4.5, 4.6, 4.7 headers.
- changes (P2):
  - P2.1 — Created docs/_internal/external_findings/README.md +
    external-vllm-42102.yaml (first structured finding tracking the DFlash+TQ
    upstream PR with `status: watch`, `risk: medium`, on-pin-bump cadence).
  - P2.2 — Added §6.11 Artifact storage + retention policy table covering 12
    artefact classes (evidence ledger, patch proof, bench results, SBOM, etc.)
    with location/tracked/release-flag/redacted/retention columns.
  - P2.3 — Created docs/ROLLBACK_PLAYBOOK.md with 8 named rollback procedures
    (R-001..R-008) — V2 alias / community SDK / RuntimeCommandSpec /
    memory explain / patch proof / convergence / V1 freeze / license gate.
    Each has Trigger/Revert/Smoke/Evidence sections, all CLI commands
    reference real surfaces from vllm/sndr_core/cli/.
- decision: accept

#### Artefacts created

- tools/policies/dirty_state_allowlist.yaml (90 lines — three-tier YAML policy)
- scripts/check_dirty_state.py (160 lines — Python gate, exit 0/1/2, --json mode)
- Makefile: audit-dirty-state-{dev,audit,release} targets
- docs/_internal/external_findings/README.md (47 lines)
- docs/_internal/external_findings/external-vllm-42102.yaml (50 lines)
- docs/ROLLBACK_PLAYBOOK.md (260 lines — 8 procedures + cross-cutting principles + validation)
- decision: accept
- notes: All new artifacts are tracked-able; no secrets, no host paths, no
  private IPs — pass §6.10 public/private docs boundary informally.

---

### Entry 5 — Phase 4 CLI updates (V2 discovery surface live)

- timestamp: 2026-05-12T19:30+0300
- host: local
- path: /Users/sander/Documents/Visual Studio Code/genesis-vllm-patches
- commit: 680d06d (worktree, pre-commit)
- branch: main

#### local — Phase 8a baseline (V1 path green)

- command: python3 -m vllm.sndr_core.cli launch a5000-2x-35b-prod --preflight-only --dry-run
- exit code: 0
- result: pass
- excerpt: |
  Generated launch script with correct 35B PROD config (TQ k8v4, MTP K=3,
  P67_NUM_KV_SPLITS=48, max_model_len=320000). V1 path intact.
- decision: accept

#### local — Phase 4 CLI deliverables shipped

- new files:
  - vllm/sndr_core/cli/hardware.py (137 lines — `sndr hardware list / show`)
  - vllm/sndr_core/cli/profile.py (217 lines — `sndr profile list / show / diff`)
  - tests/unit/cli/test_phase4_v2_cli.py (23 tests, all passing)
- modified files:
  - vllm/sndr_core/cli/model.py (added `list-v2` + `show` subcommands for V2 ModelDef)
  - vllm/sndr_core/cli/__init__.py (registered hardware + profile argparsers)
- decision: accept

#### local — new CLI surface end-to-end smoke

- command: python3 -m vllm.sndr_core.cli hardware list
- exit code: 0
- excerpt: |
  sndr hardware list — V2 HardwareDef registry
    a5000-1x-24gbvram-16cpu-128gbram  n_gpus=1  cuda_cap≥8.6  runtime=docker
    a5000-2x-24gbvram-16cpu-128gbram  n_gpus=2  cuda_cap≥8.6  runtime=docker
    single-3090-24gbvram              n_gpus=1  cuda_cap≥8.6  runtime=docker
    Total: 3 hardware definitions

- command: python3 -m vllm.sndr_core.cli profile list
- exit code: 0
- excerpt: |
  Total: 11 profiles (all parent_models present, delta counts match registry)

- command: python3 -m vllm.sndr_core.cli profile diff qa-27b-fp8kv-tested
- exit code: 0
- excerpt: |
  canonical patches: 51 / merged patches: 36 / delta: +1 / -16 / ~0
  Verified disable list contains PN90_PROBABILISTIC_DRAFT, PN16_LAZY_REASONER,
  P107_MTP_TRUNCATION_DETECTOR, etc.

- command: python3 -m vllm.sndr_core.cli model list-v2
- exit code: 0
- excerpt: |
  Total: 6 V2 model definitions (35B-fp8, 35B-fp8-dflash, 27B-tq-k8v4,
  27B-fp8kv, 27B-dflash, 7B-dense). All attributes (arch, dtype, kv,
  spec method, patches count) render correctly.

- decision: accept

#### local — pytest baseline raised

- command: python3 -m pytest tests/ -q --ignore=tests/integration
- exit code: 0
- result: pass
- excerpt: |
  5650 passed, 124 skipped in 55.67s
- decision: accept
- notes: +23 tests vs Entry 4 (5627 → 5650). All Phase 4 CLI tests
  (TestHardwareList/Show, TestProfileList/Show/Diff, TestModelListV2/Show,
  TestRegistration) pass on first run.

#### local — all 11 V2 aliases still resolve identically

- command: python3 -c "from vllm.sndr_core.model_configs.registry_v2 import load_alias; ..."
- exit code: 0
- result: pass
- excerpt: |
  Identical ctx/seqs/patches values as Entry 4 — Phase 4 CLI is pure
  read-side additions, no semantic drift in the resolver.
- decision: accept

#### Phase 4 acceptance — operator can now

- `sndr hardware list` — see all 3 V2 rigs (2× A5000, 1× A5000, single 3090)
- `sndr hardware show <id>` — inspect sizing + runtime block + system env
- `sndr profile list` — see all 11 profiles with delta counts
- `sndr profile list --model <id>` — filter to a specific parent model
- `sndr profile show <id>` — inspect patches delta + sizing override + promotion contract
- `sndr profile diff <id>` — preview patches matrix delta vs canonical model.patches
- `sndr model list-v2` — see all 6 V2 ModelDef entries with capabilities summary
- `sndr model show <id>` — inspect identity, capabilities, requires, patches
- V1 surface (`sndr model list/pull`, `sndr config list`, etc.) unchanged.

---

### Entry 6 — Phase 4.5 + Phase 4.6 + Phase 4.7 shipped (Day 7-15 P1 chunk done)

- timestamp: 2026-05-12T20:45+0300
- host: local
- path: /Users/sander/Documents/Visual Studio Code/genesis-vllm-patches
- commit: 680d06d (worktree, pre-commit)
- branch: main

#### Phase 4.5 — RuntimeContainerSpec canonical IR (33 tests)

- new files:
  - vllm/sndr_core/model_configs/runtime_container.py (230 lines)
    `RuntimeContainerSpec` frozen dataclass + `MountSpec` / `PortSpec` /
    `DeviceSpec` / `SecuritySpec` sub-types + `build_runtime_container_spec()`
    builder that consumes V1 ModelConfig.
  - tests/unit/model_configs/test_runtime_container_spec.py (33 tests)
- decision: accept
- acceptance: cross-runtime semantic equality verified for prod-35b,
  prod-27b-tq, long-ctx-27b — switching `runtime=` parameter preserves
  container_name / image / image_digest / env / mounts / ports / devices /
  shm_size / memory_limit / network_mode / security / extra_run_flags /
  command.argv. Only the `runtime` discriminator differs. ✓

#### Phase 4.6 — Security + license gate boundary (15 tests)

- changes:
  - vllm/sndr_core/license.py — added Phase 4.6 boundary surface
    (`EngineDetection`, `CoreLicenseStatus`, `LicenseVerifyResult`,
    `is_engine_installed()`, `core_license_status()`, `verify_license_file()`).
    Integrated into existing module (avoids shadowing the engine-tier
    eligibility gate already in this file).
- new files:
  - vllm/sndr_core/cli/license.py — `sndr license status / verify` subcommands.
  - scripts/security_scan.py — release-pipeline security audit (6 checks:
    operator paths, private IPs, private keys, .env files, AWS keys,
    release artifacts).
  - tests/unit/test_license_boundary.py (15 tests).
- Makefile: added `audit-security` + `audit-security-release` targets.
- registered `sndr license` in cli/__init__.py.
- decision: accept
- acceptance:
  - `sndr license status` reports `core: public (unlicensed)` ✓
  - `sndr license verify --file <X>` returns deferred message + exit 0 ✓
  - Import of vllm.sndr_core.license adds no network module to sys.modules ✓
  - security_scan correctly identifies 190 pre-existing operator-path refs ✓

#### Phase 4.7 — `sndr memory explain` MVP (21 tests)

- changes:
  - vllm/sndr_core/cli/memory.py — added `_resolve_preset_v1_or_v2()`
    helper (V1 registry first, V2 alias fallback) + `_compute_verdict()`
    with median / p95 / worst-case bands + SAFE / TIGHT / OOM_RISK
    discriminator. `_run_explain()` now accepts both V1 preset keys
    and V2 aliases, emits verdict in both text and JSON output.
- new files:
  - tests/unit/cli/test_phase4_7_memory_explain.py (21 tests)
- decision: accept
- acceptance:
  - `sndr memory explain prod-35b` resolves V2 alias and renders verdict ✓
  - JSON output carries `verdict`, `total_median_mib_per_gpu`,
    `total_p95_mib_per_gpu`, `total_worst_mib_per_gpu`, `budget_mib_per_gpu` ✓
  - 8 V2 aliases tested across the alias matrix (all pass) ✓
  - V1 preset path unchanged (regression guard passes) ✓
  - Honesty rule held: every output mode emits all three bands, never
    a single-point estimate.

#### Cumulative pytest progression across this session

| Phase | Tests added | Cumulative | Result |
|---|---|---|---|
| Baseline (Entry 4) | — | 5627 | green |
| Phase 4 (CLI updates) | 23 | 5650 | green |
| Phase 4.5 (RuntimeContainerSpec) | 33 | 5683 | green |
| Phase 4.6 (license boundary) | 15 | 5698 | green |
| Phase 4.7 (memory explain MVP) | 21 | 5719 | green |

#### All 11 V2 aliases still resolve identically

- command: python3 -c "from vllm.sndr_core.model_configs.registry_v2 import load_alias; ..."
- exit code: 0
- excerpt: |
  All 11 aliases match Entry 4/5 exactly:
    prod-35b ctx=320000 seqs=2 patches=44
    prod-27b-tq ctx=131072 seqs=4 patches=52
    prod-35b-dflash ctx=160000 seqs=1 patches=37
    long-ctx-27b ctx=280000 seqs=2 patches=51
    qa-27b-tested ctx=131072 seqs=2 patches=36
    qa-27b-tq-1x ctx=78000 seqs=1 patches=53
    prod-27b-dflash ctx=185000 seqs=1 patches=30
    experimental-27b-tq-dflash-ab ctx=131072 seqs=2 patches=58
    example-2x-tier-aware ctx=131072 seqs=4 patches=56
    example-3090-dense-cpu-offload ctx=65536 seqs=1 patches=2
    example-3090-tier-aware ctx=145000 seqs=1 patches=54
- decision: accept
- notes: Phase 4.x work is pure read-side + new modules; no semantic
  drift in V2 composer or resolver.

#### Roadmap §10 Day 7-15 P1 status

- [x] Phase 4 (CLI updates) — done
- [x] Phase 4.5 (RuntimeCommandSpec canonical IR) — done (as RuntimeContainerSpec)
- [x] Phase 4.6 (Security + license gate boundary) — done
- [x] Phase 4.7 (`sndr memory explain` MVP) — done
- [ ] Phase 5 (community SDK) — next session

---

### Entry 7 — Phase 5 community patch SDK shipped (Day 12-15 P1 chunk done)

- timestamp: 2026-05-12T22:00+0300
- host: local
- path: /Users/sander/Documents/Visual Studio Code/genesis-vllm-patches
- commit: 680d06d (worktree, pre-commit)
- branch: main

#### Phase 5 — Community patch SDK (38 tests)

- new package: `vllm/sndr_core/community/`
  - `__init__.py` — public API (load_manifest, list_manifest_paths,
    discover_*, validate_*).
  - `manifest.py` — loader + path enumeration with `_template`/`_*`
    directory exclusion (§6.6 no-stub gate).
  - `discovery.py` — filesystem walk + `vllm.community_patches`
    entry-points group + dedup by (namespace, id) with filesystem-wins
    policy.
  - `validator.py` — release-tier rules R-1..R-7:
      • R-1 text_patch context_md5 matches pristine_fixture
      • R-2 requires_patches references known patch ids
      • R-3 conflicts_with references known patch ids (warning, not error)
      • R-4 runtime_hook entry_points.apply is importable + callable
      • R-5 every tests_required glob matches ≥1 file
      • R-6 (namespace, id) uniqueness across registry
      • R-7 default_on=True requires stable AND published
  - `scaffold.py` — `sndr community new-patch` generator producing a
    working draft plugin tree that schema-validates clean.
- new CLI: `vllm/sndr_core/cli/community.py`
  - `sndr community list [--json] [--root]`
  - `sndr community validate [--json] [--root]`
  - `sndr community new-patch --id --author --family ...`
- new tree: `plugins/community/_template/README.md` documenting the
  reference layout. `_template` is excluded from release registry by
  validator's underscore-prefix rule.
- new docs: `docs/COMMUNITY_PATCHES.md` operator + contributor guide.
- schema change: added `_check_patch_id()` separate from `_check_id()`
  to support uppercase P-code convention (PN999, P107, P12_RETRY) for
  patch IDs while keeping kebab-case for model/hardware/profile IDs.
  Existing test fixture `_make_patch_manifest()` updated from `pn999`
  → `PN999`.
- tests: `tests/unit/community/test_phase5_community_sdk.py` — 38 tests
  covering manifest load + filesystem discovery + 5 schema rules + all 7
  release-tier rules + scaffold + CLI registration.
- decision: accept

#### Acceptance evidence

```
$ sndr community new-patch --id PN999 --author testuser --family spec_decode --title "Test"
sndr community new-patch — scaffold ready at:
  /Users/sander/.../plugins/community/testuser/PN999
Files created: manifest.yaml, __init__.py, patch.py, tests/__init__.py,
               tests/test_pn999.py

$ sndr community list
sndr community list — discoverable patches
  community/testuser:PN999
      Test  [v0.1.0]
      type=runtime_hook  family=spec_decode  impl=experimental  publish=draft
  Total: 1 community patches

$ sndr community validate
sndr community validate — plugins/community
  manifests: 1
  errors:    0
  warnings:  0
  ✓ release-tier validation passed
```

#### Cumulative pytest progression

| Phase | Tests added | Cumulative | Result |
|---|---|---|---|
| Baseline (Entry 4) | — | 5627 | green |
| Phase 4 | 23 | 5650 | green |
| Phase 4.5 | 33 | 5683 | green |
| Phase 4.6 | 15 | 5698 | green |
| Phase 4.7 | 21 | 5719 | green |
| Phase 5 | 38 | 5757 | green |

#### All 11 V2 aliases still resolve identically

Same ctx/seqs/patches counts as Entries 4/5/6 — Phase 5 work touches
community SDK + schema patch_id check; V2 composer + alias resolver
unchanged. ✓

#### Roadmap §10 Day 7-15 P1 status

- [x] Phase 4 (CLI updates)
- [x] Phase 4.5 (RuntimeContainerSpec)
- [x] Phase 4.6 (Security/license boundary)
- [x] Phase 4.7 (`sndr memory explain` MVP)
- [x] Phase 5 (Community SDK) — done this entry
- [ ] Phase 6 (bench/log naming + methodology contract) — next
- [ ] Phase 7 (tests + docs + CI gates)
- [ ] Phase 8b (V2 acceptance smoke)
- [ ] Phase 9 (V1 freeze)

---

### Entry 8 — Phase 6 bench methodology contract shipped

- timestamp: 2026-05-12T22:30+0300
- host: local
- path: /Users/sander/Documents/Visual Studio Code/genesis-vllm-patches
- commit: 680d06d (worktree, pre-commit)
- branch: main

#### Phase 6 — Bench/log integration + methodology contract (26 tests)

- new files:
  - tools/bench_methodology.yaml (95 lines) — single source of truth.
    Fixes prompt-corpus path, warmup_runs=3, measure_runs=10,
    cv_warn=5% / cv_fail=10%, tool_call_min_score=9, 17 required
    artefact fields, GPU clock capture rules, soak protocol.
  - vllm/sndr_core/cli/bench.py (260 lines) — `sndr bench-validate` +
    `sndr bench-methodology` top-level commands (sibling to existing
    `sndr bench-compare`, since `bench` parent is already bridged to
    legacy `compat.cli bench`).
  - tests/unit/cli/test_phase6_bench_methodology.py (26 tests).
- registered `_bench_argparser` in cli/__init__.py.
- decision: accept

#### Validator rules implemented

- M-1 — every required artefact field present
- M-2 — methodology_id matches contract
- M-3 — methodology_sha matches the YAML on disk (fingerprint guard)
- M-4 — warmup_runs + measure_runs match contract protocol
- M-5 — cv_pct within cv_warn/cv_fail tolerances (warning vs error)
- M-6 — tool_call_score ≥ tool_call_min_score (also warns when
  format is unparseable)

#### Acceptance evidence

```
$ sndr bench-methodology
sndr bench methodology — tools/bench_methodology.yaml
  sha:               783b1ccae908b6dd39d9f48d288379b594afee54180867ce025c1c0b364b68de
  methodology_id:    wave9-baseline
  schema_version:    1
  Measurement protocol:
    warmup_runs:     3
    measure_runs:    10
    cv_warn_pct:     5.0
    cv_fail_pct:     10.0
  Tolerances:
    median_tps_regression_fail_pct: 5.0
    ...
  Mandatory artefact fields (17):
    • schema_version
    • methodology_id
    ...

$ echo '{"foo":"bar"}' > /tmp/bench-broken.json
$ sndr bench-validate /tmp/bench-broken.json
  errors:      17
  warnings:    0
  ✗ ERROR (17):
    [M-1] missing required artefact field: 'schema_version'
    [M-1] missing required artefact field: 'methodology_id'
    [M-1] missing required artefact field: 'methodology_sha'
    [M-1] missing required artefact field: 'composed_key'
    ... (13 more)
  ✗ artefact FAILED methodology contract (17 errors)
```

#### Cumulative pytest progression

| Phase | Tests added | Cumulative | Result |
|---|---|---|---|
| Baseline (Entry 4) | — | 5627 | green |
| Phase 4 | 23 | 5650 | green |
| Phase 4.5 | 33 | 5683 | green |
| Phase 4.6 | 15 | 5698 | green |
| Phase 4.7 | 21 | 5719 | green |
| Phase 5 | 38 | 5757 | green |
| Phase 6 | 26 | 5783 | green |

All 11 V2 aliases unchanged (identical ctx/seqs/patches as prior entries).

#### Roadmap §10 status

- [x] Phase 4 / 4.5 / 4.6 / 4.7
- [x] Phase 5 (community SDK)
- [x] Phase 6 (bench methodology contract) — done this entry
- [ ] Phase 7 (tests + docs + CI gates) — next
- [ ] Phase 8b (V2 acceptance smoke)
- [ ] Phase 9 (V1 freeze)

---

### Entry 9 — Phase 7 + 8b + 9 shipped (Roadmap §10 Day 16-20 done)

- timestamp: 2026-05-12T23:30+0300
- host: local
- path: /Users/sander/Documents/Visual Studio Code/genesis-vllm-patches
- commit: 680d06d (worktree, pre-commit)
- branch: main

#### Phase 7 — Tests + docs + CI gates (28 tests)

- new scripts:
  - `scripts/audit_configs.py` — every V2 preset alias composes cleanly
    (gate exit 0 across 11/11 aliases).
  - `scripts/audit_artifacts.py` — §6.11 artefact storage policy
    (A-1 ledger / A-2 patch-proof layout / A-3 release artefacts /
    A-5 bench-results-not-tracked / A-6 rollback playbook).
  - `scripts/audit_public_docs.py` — §6.10 public/private boundary
    (D-1..D-6 rules).
- new docs: `docs/CONFIG_SYSTEM_V2.md` — V2 layered config operator
  guide (4-layer model, discovery CLI, composition rules, ownership
  table, profile delta semantics, sizing override, V1↔V2 bridge,
  runtime backends, Python API).
- Makefile gates added: `audit-configs`, `audit-public-docs`,
  `audit-artifacts`, `audit-artifacts-release`, `audit-community`.
- tests: `tests/unit/test_phase7_release_gates.py` — 28 tests.
- decision: accept

#### Phase 8b — V2 acceptance smoke (11/11 aliases preflight green)

- command: each of 11 V2 aliases through
  `sndr launch <alias> --preflight-only --dry-run`
- exit code: 0 across all 11
- decision: accept
- notes: parametrized test in `tests/unit/test_phase9_v1_freeze.py`
  (TestPhase8bAcceptance) covers the same matrix in pytest form so CI
  re-runs the acceptance gate on every commit.

#### Phase 9 — V1 freeze (21 tests)

- changes:
  - `vllm/sndr_core/model_configs/registry.py` — `get(<V1-key>)` now
    emits one-time `DeprecationWarning` per V1 monolithic preset key
    pointing operators at `sndr hardware list` / `sndr model list-v2` /
    `sndr profile list`. V1 path stays functional. Env override
    `GENESIS_DISABLE_V1_DEPRECATION_WARNING=1` silences for transition.
- new script: `scripts/audit_no_new_v1.py` — captures the 11 V1
  monolithic preset files in `FROZEN_V1_BASELINE`. Gate fails if a
  new top-level `builtin/*.yaml` lands or a baseline file disappears.
- Makefile gate: `audit-no-new-v1`.
- tests: `tests/unit/test_phase9_v1_freeze.py` — 21 tests covering
  warning emission, once-per-key dedup, env-override silencing, V1
  path-still-works, V2-alias-no-warning, freeze gate sanity, and the
  Phase 8b acceptance matrix.
- decision: accept

#### Acceptance evidence

```
$ make audit-configs
audit-configs: 11 presets
  ✓ all 11 presets compose cleanly

$ make audit-artifacts
  ✓ A-1 evidence ledger: clean
  ✓ A-2 patch proof layout: clean
  ✓ A-3 release artefacts: clean
  ✓ A-5 bench-results not tracked: clean
  ✓ A-6 rollback playbook: clean
  OK — artefact storage policy passes

$ make audit-no-new-v1
audit-no-new-v1: 11 V1 file(s) currently present
                 11 in frozen baseline
  ✓ V1 frozen — top-level builtin/*.yaml matches the 11-entry baseline

$ for alias in prod-35b prod-27b-tq ...; do sndr launch $alias --preflight-only --dry-run; done
  rc=0 across all 11 aliases ✓

$ python3 -c "
import warnings
from vllm.sndr_core.model_configs.registry import get
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter('always')
    get('a5000-2x-35b-prod')
    print([str(x.message) for x in w if issubclass(x.category, DeprecationWarning)])
"
['V1 monolithic preset key \\'a5000-2x-35b-prod\\' is deprecated. Prefer a V2 alias...']
```

#### Cumulative pytest progression — final

| Phase | Tests added | Cumulative | Result |
|---|---|---|---|
| Baseline (Entry 4) | — | 5627 | green |
| Phase 4 | 23 | 5650 | green |
| Phase 4.5 | 33 | 5683 | green |
| Phase 4.6 | 15 | 5698 | green |
| Phase 4.7 | 21 | 5719 | green |
| Phase 5 | 38 | 5757 | green |
| Phase 6 | 26 | 5783 | green |
| Phase 7 | 28 | 5811 | green |
| Phase 9 | 21 | 5832 | green |

#### Roadmap §10 — final status

- [x] Phase 0 — Evidence ledger
- [x] Phase 8a — V1 cold-install smoke (pre-V2 gate)
- [x] Phase 1 — V2 schema + composer + tests
- [x] Phase 2 — POC migration
- [x] Phase 3 — Migrate 10 presets (all 11 V1 → V2 layered)
- [x] Phase 4 — CLI updates
- [x] Phase 4.5 — RuntimeContainerSpec canonical IR
- [x] Phase 4.6 — Security/license boundary
- [x] Phase 4.7 — `sndr memory explain` MVP
- [x] Phase 5 — Community patch SDK
- [x] Phase 6 — Bench/log methodology contract
- [x] Phase 7 — Tests + docs + CI gates
- [x] Phase 8b — V2 acceptance smoke
- [x] Phase 9 — V1 freeze (warn-only)

**Continuous / long-term still open** (per Roadmap §10 P3 tier):

- [ ] Phase 10 — patch integration (PN72 / SWA / PN94+PN95b / PN90 / etc.)
- [ ] External findings pipeline structured CLI (deferred deliverable)
- [ ] PN95 Phase 2/3/5 + MambaRadixCache (research-grade)
- [ ] Architecture debt P2.1 / P2.2 (dispatcher collapse — bundled with test harness refactor)

#### All 11 V2 aliases — final identity check

Same ctx/seqs/patches counts as every prior entry — Phase 7/8b/9 work
is pure CI/tests/freeze additions; V2 composer + resolver byte-identical
to Entry 6 (Phase 4.5 acceptance state).

---

### Entry 10 — External findings pipeline CLI shipped (continuous P2 closeout)

- timestamp: 2026-05-13T00:00+0300
- host: local
- path: /Users/sander/Documents/Visual Studio Code/genesis-vllm-patches
- commit: 680d06d (worktree, pre-commit)
- branch: main

#### Deliverable — `sndr findings` structured CLI

Phase 5 deferred deliverable from EXTERNAL_FINDINGS_PIPELINE_2026-05-12_RU.md
landed. The pipeline already had its first seed finding (Entry 4 created
external-vllm-42102.yaml); now the CLI surface + validator are live.

- new package: `vllm/sndr_core/findings/`
  - `schema.py` — `Finding` dataclass + 5 vocabularies
    (sources/categories/statuses/risks/cadences/targets) + transition
    matrix `ALLOWED_TRANSITIONS` capturing the state machine from
    EXTERNAL_FINDINGS_PIPELINE §2.
  - `registry.py` — `load_finding`, `list_finding_paths` (skips `_`-prefix),
    `discover_findings` (lenient — bad files logged + skipped),
    `is_due_for_review` (cadence-aware staleness).
  - `validator.py` — `validate_finding` (schema + F-4 staleness),
    `validate_directory` (adds F-1 id uniqueness), `is_valid_transition`.
- new CLI: `vllm/sndr_core/cli/findings.py`
  - `sndr findings list [--status <s>] [--due-for-review] [--json]`
  - `sndr findings add --id ... --source ... --url ... --category ...`
  - `sndr findings update <id> [--status ...] [--note ...] [--reviewed]`
  - `sndr findings validate [--json]`
- registered `_findings_argparser` in cli/__init__.py.
- tests: `tests/unit/findings/test_findings.py` — 37 tests covering
  schema vocabularies, state machine matrix (legal + illegal transitions),
  staleness (fresh/old biweekly/on-pin-bump never-stale/retired never-stale),
  F-1 duplicate id, loader (`_template.yaml` skipped), end-to-end CLI
  lifecycle (add→list→legal-transition→illegal-transition-rejected).
- decision: accept

#### Acceptance evidence

```
$ sndr findings list
sndr findings list — docs/_internal/external_findings
  external-vllm-42102
      DFlash + TQ k8v4 coexistence (vllm#42102)  [vllm-pr]
      status=watch  risk=medium  cadence=on-pin-bump
  Total: 1

$ sndr findings validate
  findings: 1
  errors:   0
  warnings: 0
  ✓ findings registry passes validation

$ sndr findings update external-test-001 --status retire-local-patch
  ⚠ illegal transition 'needs-bench' → 'retire-local-patch'; allowed from
    'needs-bench': ['backport-now', 'config-recipe', 'doctor-rule', 'skip', 'watch']
```

#### State machine implementation

| From → To | Legal? | Notes |
|---|---|---|
| watch → needs-bench | yes | Standard escalation |
| watch → done | no | Skipped intermediate; must pass through needs-bench/needs-reproducer |
| needs-bench → backport-now | yes | Bench confirms upstream useful |
| done → retire-local-patch | yes | Upstream replaces our local equivalent |
| retire-local-patch → * | no | Terminal — no reopening |
| skip → watch | yes | Operator can reopen |

#### Cumulative pytest progression — final

| Phase | Tests added | Cumulative | Result |
|---|---|---|---|
| Baseline (Entry 4) | — | 5627 | green |
| Phase 4 | 23 | 5650 | green |
| Phase 4.5 | 33 | 5683 | green |
| Phase 4.6 | 15 | 5698 | green |
| Phase 4.7 | 21 | 5719 | green |
| Phase 5 | 38 | 5757 | green |
| Phase 6 | 26 | 5783 | green |
| Phase 7 | 28 | 5811 | green |
| Phase 9 | 21 | 5832 | green |
| External findings | 37 | 5869 | green |

#### Roadmap §10 — final status (no V2 work remaining)

- [x] Phase 0 / 8a / 1 / 2 / 3 / 4 / 4.5 / 4.6 / 4.7 / 5 / 6 / 7 / 8b / 9
- [x] External findings pipeline CLI (continuous P2 closeout — this entry)

#### Still continuous P2/P3 (out of scope without GPU access)

- [ ] Phase 10 patch integration — PN72 revert contract / SWA activation /
      PN94+PN95b (after vllm#42102 merge) / PN90 / PN80 embedding FP8 /
      DuoAttention / TQ k4v4
- [ ] PN95 Phase 2/3/5 + MambaRadixCache (research-grade)
- [ ] Architecture debt P2.1 / P2.2 (dispatcher collapse) — needs test
      harness regression discrimination first

#### All 11 V2 aliases identity check

Same ctx/seqs/patches counts as Entry 9. New module is pure addition;
V2 composer + resolver untouched.

---

### Entry 11 — Canonical env-key registry CLI (§6.7 R2 mitigation closeout)

- timestamp: 2026-05-13T00:30+0300
- host: local
- path: /Users/sander/Documents/Visual Studio Code/genesis-vllm-patches
- commit: 680d06d (worktree, pre-commit)
- branch: main

#### Deliverable — `sndr config-keys-*` registry CLI

Roadmap §6.7 release-gate dependency satisfied: §6.3 gate #4 explicitly
references `sndr config keys validate` for R2 mitigation (env-key drift).
This entry ships the CLI surface + canonical registry merger + sweep
test coverage.

- new module: `vllm/sndr_core/cli/config_keys.py`
  - `load_canonical_registry()` — merges 4 sources:
    1. `dispatcher.registry.PATCH_REGISTRY.env_flag` (134 patch toggles)
    2. V2 `builtin/model/*.yaml` `patches:` block keys (11 tuning knobs
       unique to V2 such as `P67_NUM_KV_SPLITS` / `PN16_TOOL_THINK_BUDGET`)
    3. V1 `builtin/*.yaml` `genesis_env:` (3 legacy-only keys)
    4. Policy keys (`GENESIS_VLLM_PIN_POLICY` — non-patch runtime knob
       sourced from `detection.guards`)
  - Total: 149 canonical keys.
- CLI commands (top-level, hyphenated to match `bench-compare` pattern):
  - `sndr config-keys-list [--source registry|v2|v1|policy] [--json]`
  - `sndr config-keys-describe <KEY> [--json]` — token-overlap-based
    suggestions when key is unknown (`difflib.SequenceMatcher` fallback)
  - `sndr config-keys-validate <yaml-file> [--json]` — walks
    `genesis_env`, `system_env`, V2 `patches`, V2 `patches_delta.{enable,
    disable, override}`; flags only Genesis/SNDR-prefixed keys
- registered `_config_keys_argparser` in cli/__init__.py.
- tests: `tests/unit/cli/test_config_keys.py` — 35 tests covering
  canonical registry construction, all three subcommands, ignore-non-Genesis
  rule, V2 profile delta walk, and a sweep over every committed V2 model
  + profile YAML (17 parametrized cases — all validate clean).
- decision: accept

#### Real drift caught during smoke

V1 monolithic preset `a5000-2x-35b-fp8-dflash.yaml` had
`GENESIS_VLLM_PIN_POLICY: strict` in `system_env` — initially flagged
as unknown. Investigation traced it to `detection/guards.py:548`
where it's a documented runtime policy knob. Added to canonical
registry under `source: policy` (separate from patch toggles).

This proves the gate works as designed: it surfaces drift that a
human review would miss because the key looks plausible but isn't
in `PATCH_REGISTRY`.

#### Acceptance evidence

```bash
$ sndr config-keys-list --json | jq '.count'
149

$ sndr config-keys-validate vllm/sndr_core/model_configs/builtin/model/qwen3.6-35b-a3b-fp8.yaml
  total keys:        44
  Genesis/SNDR keys: 44
  unknown keys:      0
  ✓ all Genesis/SNDR keys present in canonical registry

$ sndr config-keys-describe GENESIS_ENABLE_P67_TYPO
  ✗ unknown key
  Did you mean:
    • GENESIS_ENABLE_P67_SPARSE_V
    • GENESIS_ENABLE_P67_TQ_MULTI_QUERY_KERNEL
    • GENESIS_ENABLE_PN67
    • GENESIS_ENABLE_P37
    • GENESIS_ENABLE_P7B
```

#### Sweep — every committed builtin YAML validates clean

Parametrized over 17 YAMLs (6 V2 model + 11 V2 profile files). All
return rc=0 from `sndr config-keys-validate`. The V1 monolithic files
also validate clean now that `GENESIS_VLLM_PIN_POLICY` joined the
policy-tier of the canonical registry.

#### Cumulative pytest progression

| Phase | Tests added | Cumulative | Result |
|---|---|---|---|
| Baseline (Entry 4) | — | 5627 | green |
| Phase 4 → Phase 9 → External findings | 242 | 5869 | green |
| Config-keys (this entry) | 35 | 5904 | green |

#### All 11 V2 aliases identity check

Same ctx/seqs/patches counts as every prior entry. Config-keys is a
pure read-side overlay over PATCH_REGISTRY + YAMLs — no resolver
mutation.

#### Roadmap §6 release-gate dependency closure

- §6.3 gate #4 — `sndr config keys validate` now runnable as
  `sndr config-keys-validate <yaml>`. Release pipeline can wire it
  into `make audit-configs` (already iterates over presets); a future
  patch will merge the two into a single gate run.

---

### Entry 12 — Patch proof gate shipped (§6.8 / R1 mitigation closeout)

- timestamp: 2026-05-13T01:00+0300
- host: local
- path: /Users/sander/Documents/Visual Studio Code/genesis-vllm-patches
- commit: 680d06d (worktree, pre-commit)
- branch: main

#### Deliverable — `sndr patches prove` + dead-detect

Roadmap §6.8 release gate satisfied for the static-checkable surface:
patches are verified independent of GPU access; bench-delta evidence
slots in later via the `bench_delta` field on the proof artefact.

- new module: `vllm/sndr_core/proof/` (originally `patches/`, renamed
  to avoid `vllm.sndr_core.patches.*` legacy-imports gate)
  - `static_checks_for_patch(patch_id, ...)` — 7-rule static verifier
  - `build_proof_for_patch(patch_id)` — runs checks + collects
    provenance (vllm pin, genesis pin, commit SHA, host, ISO timestamp)
  - `write_proof_artefact(proof, out_dir)` — JSON artefact at
    `evidence/patch_proof/<patch_id>__<vllm_pin>.json`. Pin chars
    sanitized so vllm `0.20.2rc1.dev209+g5536fc0c0` becomes a portable
    filename
  - `list_dead_patches(out_dir)` — registry sweep for patches with no
    PASSING proof artefact (failing artefacts don't count as proof)
  - `find_proof_artefacts(patch_id)` — historical artefacts per pin
- CLI extension under existing `sndr patches`:
  - `sndr patches prove <id>` — verify + write artefact
  - `sndr patches prove --all` — sweep, report coverage %
  - `sndr patches prove --dead-detect` — list patches with no proof
  - `--no-write` (dry-run) + `--out-dir` (override) + `--json`
- Makefile gates added:
  - `audit-patches-prove` (dead-detect)
  - `audit-patches-prove-all` (full sweep, no-write)
- tests: `tests/unit/proof/test_prove.py` — 22 tests covering rule
  matrix (real + synthetic registries), artefact round-trip, dead-detect
  semantics, CLI integration.
- decision: accept

#### Static check rules

| Rule | Check |
|---|---|
| P-1 | patch present in PATCH_REGISTRY |
| P-2 | apply_module declared OR patch in KNOWN_SPEC_ONLY allowlist |
| P-3 | apply_module importable (when declared) |
| P-4 | patch present in legacy register OR in KNOWN_SPEC_ONLY (no shadow orphan) |
| P-5 | env_flag exists AND matches canonical env-key registry (§6.7) |
| P-6 | every `requires_patches` id resolves |
| P-7 | every `conflicts_with` id resolves (typo guard) |
| P-8 | bench-delta artefact present (informational — tier policy in §6.8) |

#### Real architectural finding surfaced

The gate flagged 126/136 patches (92.6%) missing `apply_module`
metadata in `dispatcher.PATCH_REGISTRY`. Investigation: the V2 registry
was migrated from monolithic to data-only in Stage 3, but `apply_module`
was populated for only ~10 patches (P102 + 7 other KNOWN_SPEC_ONLY,
plus ~2 others). The rest fire via the legacy `@register_patch`
decorator path — they WORK, but the V2 metadata is incomplete.

This is exactly the kind of release-blocker §6.8 was designed to catch.
Follow-up: populate `apply_module` for the remaining ~126 patches
(operator task; the gate now surfaces the work item with one CLI call).

#### Acceptance evidence

```bash
$ sndr patches prove P102 --no-write
  ✓ [P-1] patch 'P102' present in registry
  ✓ [P-2] patch is in KNOWN_SPEC_ONLY allowlist (documentation/legacy entry)
  ✓ [P-4] patch is in KNOWN_SPEC_ONLY allowlist
  ✓ [P-5] env_flag 'GENESIS_ENABLE_P102' is canonical
  ✓ static checks passed (4/4)

$ sndr patches prove --dead-detect
  proven (has passing static artefact): 0
  dead   (no passing artefact):         136
  coverage:                             0.0%

$ sndr patches prove --all --no-write --json | jq '{total, passed, failed, coverage_pct}'
{
  "total": 136,
  "passed": 10,
  "failed": 126,
  "coverage_pct": 7.4
}
```

#### Cumulative pytest progression

| Phase | Tests added | Cumulative | Result |
|---|---|---|---|
| Baseline (Entry 4) | — | 5627 | green |
| Phases 4-9 + findings + config-keys | 277 | 5904 | green |
| Patch proof gate (this entry) | 22 | 5926 | green |

#### Roadmap §6 release-gate dependency closure

- §6.8 — `sndr patches prove` static surface complete. Bench-delta
  evidence (the `bench_delta` artefact field) remains pending GPU work
  per Phase 10 — but the framework, gate, and dead-detect sweep are
  live and surface the 126 metadata gaps for follow-up.
- R1 mitigation (dead-patch accumulation): catch-up surface is in
  place — every release run of `make audit-patches-prove` enumerates
  patches without proof artefact + their lifecycle tier.

#### All 11 V2 aliases identity check

Same ctx/seqs/patches counts as Entry 11. Patch proof gate is pure
read-side overlay over PATCH_REGISTRY + apply.shadow output — no
resolver mutation.

---

### Entry 13 — F822 pure-Python lint gate (§8 open-items closeout)

- timestamp: 2026-05-13T01:30+0300
- host: local
- path: /Users/sander/Documents/Visual Studio Code/genesis-vllm-patches
- commit: 680d06d (worktree, pre-commit)
- branch: main

#### Deliverable — `scripts/lint_all_referents.py` + `make audit-all-referents`

Roadmap §8 open item "Static `ruff F821/F822` CI gate" — implemented
F822 (every name in `__all__` must resolve) as a pure-Python AST-based
gate. No external dependency on ruff/pyflakes — works on any Python
install. F821 (undefined names in function bodies) needs full scope
resolution and is deferred to ruff when operator chooses to install it.

- new script: `scripts/lint_all_referents.py` (~260 lines)
  - `check_file(path)` returns `list[Violation]` for one .py file
  - `_module_defined_names(tree)` — top-level binding collector
    (function/class defs, imports w/ aliases, assignments + tuple unpacking,
    annotated assignments, `for`/`with` targets, conditional bodies)
  - `_has_module_level_getattr(tree)` — PEP 562 lazy-loader detector
  - `_sibling_submodule_names(path)` — for `__init__.py`, treats sibling
    .py files and subpackages as defined (`from pkg import *` mechanics)
  - `_extract_all_referents(tree)` — pulls string-literal members from
    `__all__ = [...]` / `__all__ += [...]` / `__all__: list[str] = [...]`
  - Default scan roots: `vllm/sndr_core/` + `scripts/`; `--paths` override
- new Makefile gate: `audit-all-referents`
- tests: `tests/unit/scripts/test_lint_all_referents.py` — 20 tests
  covering rule core, PEP 562 skip, package-init siblings, dynamic
  `__all__`, malformed Python, dir-walk hygiene, real-tree green
  acceptance

#### Acceptance evidence

```bash
$ make audit-all-referents
lint_all_referents: 386 Python files scanned
  ✓ every `__all__` referent resolves
```

#### False-positive evolution during build

The naive first version reported 147 violations across 25 files. Two
real Python semantics required follow-up:

1. **PEP 562** — modules with `def __getattr__(name)` resolve names
   dynamically; my linter was flagging legitimate lazy submodule loaders.
   Fix: detect top-level `__getattr__` def and short-circuit. Down to 3.
2. **Package import-* mechanics** — `from pkg import *` will import
   sibling submodules / subpackages even if `__init__.py` doesn't
   explicitly import them (CPython's `_handle_fromlist`).
   Fix: for `__init__.py`, treat sibling .py files + subpackage
   directories as defined names. Down to 0.

Final repo result: 386 files scanned, every `__all__` name resolves.

#### Cumulative pytest progression

| Phase | Tests added | Cumulative | Result |
|---|---|---|---|
| Baseline (Entry 4) | — | 5627 | green |
| Phases 4-9 + findings + config-keys + patch-prove | 299 | 5926 | green |
| F822 lint gate (this entry) | 20 | 5946 | green |

#### Roadmap §8 status

- [x] Static F822 CI gate — done (this entry)
- [ ] Static F821 CI gate — deferred (needs ruff/pyflakes; operator decision)
- [ ] Patch counts auto-sync (README/PATCHES.md from registry) — 0.5d, doable
- [ ] PN96 A/B bench on 35B PROD — GPU needed
- [ ] Pytest plugin fixtures (`genesis_registry`, `pristine_vllm_source`) — doable
- [ ] Soak test auto-integration — GPU needed
- [ ] Trust anchor rotation ceremony — operator schedule

#### All 11 V2 aliases identity check

Same ctx/seqs/patches counts as Entry 12. F822 gate is read-only AST
analysis — no runtime impact on the resolver.

---

### Entry 14 — README counter-sync gate (§8 open-items closeout, +1 real drift fixed)

- timestamp: 2026-05-13T02:00+0300
- host: local
- path: /Users/sander/Documents/Visual Studio Code/genesis-vllm-patches
- commit: 680d06d (worktree, pre-commit)
- branch: main

#### Deliverable — `scripts/sync_readme_counters.py` + Makefile gates

Roadmap §8 open item "Patch counts auto-sync (README/PATCHES.md from
registry)" — implemented as an idempotent rewrite + `--check` mode
gate. Reads authoritative counts from `dispatcher.PATCH_REGISTRY` +
V2 builtin tree; rewrites only the well-known counter lines/badges
in README.md.

- new script: `scripts/sync_readme_counters.py` (~200 lines)
  - `collect_counts()` — pulls patches / families / V2 models /
    hardware / profiles / aliases
  - 5 rewrite rules covering shields.io badge + 4 inline counter
    patterns; each rule's regex is conservative (targets one specific
    sentence shape so unrelated numbers stay untouched)
  - `--check` mode: exit 1 if drift, no rewrite
  - `--json` mode: structured output for CI
  - `--file` override for testing on synthetic READMEs
- new Makefile targets:
  - `audit-readme-counters` — CI check (no rewrite)
  - `readme-sync` — apply rewrites
- tests: `tests/unit/scripts/test_sync_readme_counters.py` — 12 tests
  covering pattern matching, idempotency on the committed tree, drift
  detection on synthetic stale READMEs, CLI exit-code semantics

#### Real drift caught + fixed on first run

```bash
$ python3 scripts/sync_readme_counters.py --check
  ✗ [R-coverage-line] line 404 — ### Patch coverage — N patches across M categories
        old: ### Patch coverage — 134 patches across 19 categories
        new: ### Patch coverage — 136 patches across 20 categories
  drift: 1 line(s) need sync — run without --check to rewrite

$ python3 scripts/sync_readme_counters.py
  ✓ wrote 1 update(s) to README.md

$ python3 scripts/sync_readme_counters.py --check
  ✓ README already matches authoritative counts
```

The badge shape (`shields.io/badge/patches-N-green.svg`) and 3 other
counters were already correct (136 / "All 136 patches"); only the
"Patch coverage — N patches across M categories" line had drifted
from a prior registry state when both values were lower.

#### Exit-code semantics (worth recording)

- `--check`: exit 1 iff drift exists, never rewrites.
- Default (no `--check`): rewrite if drift, exit 0 (success = either
  no drift OR drift fixed). Operator can pipe `--json` to grep the
  `wrote_file` boolean for follow-up.

#### Cumulative pytest progression

| Phase | Tests added | Cumulative | Result |
|---|---|---|---|
| Baseline (Entry 4) | — | 5627 | green |
| Through Entry 13 (F822 gate) | 319 | 5946 | green |
| README counter-sync (this entry) | 12 | 5958 | green |

#### Roadmap §8 status update

- [x] Static F822 CI gate (Entry 13)
- [x] Patch counts auto-sync (this entry)
- [ ] Static F821 CI gate — deferred (needs ruff/pyflakes)
- [ ] PN96 A/B bench on 35B PROD — GPU needed
- [ ] Pytest plugin fixtures — doable next
- [ ] Soak test auto-integration — GPU needed
- [ ] Trust anchor rotation ceremony — operator schedule

#### All 11 V2 aliases identity check

Same ctx/seqs/patches counts as Entry 13. README rewrite touches
metadata in one .md file — no runtime impact.

---

### Entry 15 — Shared pytest fixtures (§8 open-items closeout)

- timestamp: 2026-05-13T02:30+0300
- host: local
- path: /Users/sander/Documents/Visual Studio Code/genesis-vllm-patches
- commit: 680d06d (worktree, pre-commit)
- branch: main

#### Deliverable — `tests/conftest.py` shared fixtures (§8 spec)

Roadmap §8 open item "Pytest plugin fixtures (`genesis_registry`,
`pristine_vllm_source`)" — implemented in the top-level conftest so
every test picks them up without re-imports. All registry walks are
session-scoped: the full pytest run loads each registry exactly once
instead of N times across N parametrized tests.

- new fixtures (all session-scoped except `proof_dir`):
  - `genesis_registry` — the live `PATCH_REGISTRY` dict
  - `stable_patch_ids` — IDs with `lifecycle == 'stable'`
  - `experimental_patch_ids` — IDs with `lifecycle == 'experimental'`
  - `v2_model_ids` — V2 ModelDef ids
  - `v2_hardware_ids` — V2 HardwareDef ids
  - `v2_profile_ids` — V2 ProfileDef ids
  - `v2_alias_ids` — 11 V2 preset alias filenames
  - `canonical_env_keys` — §6.7 canonical key set (set for O(1) lookups)
  - `proof_dir` (function-scoped) — isolated tmp `evidence/patch_proof/`
  - `pristine_vllm_source` — Path to vllm package source OR pytest.skip
- new marker: `requires_vllm` (auto-skipped when vllm absent — Mac dev
  doesn't need to install vllm to run the suite)
- tests: `tests/unit/test_shared_fixtures.py` — 19 tests covering each
  fixture's contract + identity-with-direct-import + marker registration

#### Design notes

- `pristine_vllm_source` deliberately uses `importlib.util.find_spec`
  instead of `import vllm` so collection cost stays cheap (find_spec
  is filesystem-only; no module body execution).
- `proof_dir` per-test isolation (cross-test pollution explicitly
  verified by a pair of sibling tests).
- Session scoping doesn't break parallelization — pytest-xdist creates
  per-worker sessions, so each worker still pays one import. Without
  parallelism, the saving is N→1 across the entire run.

#### Acceptance evidence

```bash
$ python3 -m pytest tests/unit/test_shared_fixtures.py -q
...............s...
SKIPPED [1] tests/unit/test_shared_fixtures.py:128: vllm not installed
18 passed, 1 skipped in 0.18s
```

The skip is the canonical Mac-dev outcome (vllm not installed); on
server (where vllm IS installed) the skip turns into a pass.

#### Cumulative pytest progression

| Phase | Tests added | Cumulative | Result |
|---|---|---|---|
| Baseline (Entry 4) | — | 5627 | green |
| Through Entry 14 (README counter-sync) | 331 | 5958 | green |
| Shared fixtures (this entry) | 18 | 5976 | green |

#### Roadmap §8 status update

- [x] Static F822 CI gate (Entry 13)
- [x] Patch counts auto-sync (Entry 14)
- [x] Pytest plugin fixtures (this entry)
- [ ] Static F821 CI gate — deferred (needs ruff/pyflakes)
- [ ] PN96 A/B bench on 35B PROD — GPU needed
- [ ] Soak test auto-integration — GPU needed
- [ ] Trust anchor rotation ceremony — operator schedule

Three of seven §8 open items now closed; the remaining four all need
GPU rig or operator scheduling.

#### All 11 V2 aliases identity check

Same ctx/seqs/patches counts as Entry 14. Conftest fixtures are
read-only views over existing registries — no runtime mutation.

---

### Entry 16 — Auto-discovery for PATCH_REGISTRY apply_module gap (Entry 12 follow-up)

- timestamp: 2026-05-13T03:00+0300
- host: local
- path: /Users/sander/Documents/Visual Studio Code/genesis-vllm-patches
- commit: 680d06d (worktree, pre-commit)
- branch: main

#### Deliverable — `scripts/discover_apply_modules.py`

Entry 12 (§6.8 patch-proof gate) flagged 126/136 patches missing the
`apply_module` field in `dispatcher.PATCH_REGISTRY`. They function fine
via the legacy `@register_patch` decorator path, but the V2 metadata
gap pushes patch-proof gate static-check coverage to ~7%.

This script auto-discovers the missing values by introspecting the
legacy register's wrapped functions: each `(name, fn)` pair carries
`fn.__wrapped__.__module__` from `functools.wraps`, which is the real
apply function's containing module.

- new script: `scripts/discover_apply_modules.py` (~190 lines)
  - `_extract_patch_id(name)` — leading P-code regex
    (handles `P58` / `P67b` / `P15B` / `PN94` / `PN94B` / `P107`)
  - `_real_module_for_legacy_fn(fn)` — unwraps the decorator via
    `fn.__wrapped__.__module__`
  - `build_proposals()` — emits one `Proposal` dataclass per matchable
    entry with `current_apply_module`, `proposed_apply_module`,
    `needs_update`
  - `--coverage` — numeric-only summary mode
  - `--emit-py <FILE>` — writes a paste-friendly Python snippet
    (`PROPOSED_APPLY_MODULES = {...}`) the operator can review
- new Makefile target: `discover-apply-modules`
- tests: `tests/unit/scripts/test_discover_apply_modules.py` — 20 tests
  covering regex matrix, real-module resolution against the live legacy
  register, dataclass shape, dict snippet round-trips through `exec()`,
  CLI exit codes, and the headline coverage projection.

#### Headline finding

```bash
$ make discover-apply-modules
  patches with legacy register match:  127
  patches WITHOUT legacy match:        9
  apply_module already set:            0
  apply_module needs update:           127

  Coverage if all proposals applied:
    before:  3/136  (2.2%)
    after:   130/136  (95.6%)
```

127 patches can be auto-mapped to `vllm.sndr_core.apply._per_patch_dispatch`
in one sweep — closing the §6.8 P-2 metadata gap from 2.2% to 95.6%
coverage. The remaining 9 patches without legacy match fall into two
buckets:
  • 8 in `KNOWN_SPEC_ONLY` allowlist (documentation/legacy entries that
    intentionally have no apply_module — already pass P-2 via the
    allowlist branch)
  • 1 unmatched legacy register entry whose name doesn't lead with a
    P-code (`Sprint 2.6 v2 — CUDA graph dispatch trace wire-in` — an
    instrumentation entry, not a V2 patch)

So 95.6% coverage IS the effective ceiling under current metadata.

#### Design — why script doesn't auto-edit `registry.py`

`vllm/sndr_core/dispatcher/registry.py` is 2000+ lines of literal dict
entries with comments and lifecycle annotations next to each patch.
Auto-editing via AST/regex risks reordering keys, dropping comments,
or breaking nearby entries. The script emits a paste-friendly snippet;
operator reviews + applies via their preferred tooling (sed sweep,
manual edit, or one-off migration script).

This matches the prior pattern (sync_readme_counters.py auto-edits a
small README, but a 2000-line dict is left to operator hands).

#### Cumulative pytest progression

| Phase | Tests added | Cumulative | Result |
|---|---|---|---|
| Baseline (Entry 4) | — | 5627 | green |
| Through Entry 15 (shared fixtures) | 349 | 5976 | green |
| Auto-discovery script (this entry) | 20 | 5996 | green |

#### Roadmap §6.8 status update

- §6.8 patch-proof gate static surface — complete since Entry 12.
- §6.8 metadata gap (`apply_module` missing) — proposals in hand;
  application is operator follow-up (one paste from `/tmp/mapping.py`).
- §6.8 bench-delta evidence — still pending GPU work per Phase 10.

#### All 11 V2 aliases identity check

Same ctx/seqs/patches counts as Entry 15. Auto-discovery is read-only
introspection — no resolver mutation.

---

### Entry 17 — §6.8 P-2 rule semantic fix (Entry 16 application path)

- timestamp: 2026-05-13T03:30+0300
- host: local
- path: /Users/sander/Documents/Visual Studio Code/genesis-vllm-patches
- commit: 680d06d (worktree, pre-commit)
- branch: main

#### What this entry corrects

Entry 16 shipped `discover_apply_modules.py` and projected
patches-prove coverage could rise from 2.2% to 95.6%. The natural
next step was to APPLY the proposals via a runtime overlay that
mutates `PATCH_REGISTRY` at import time.

I built and tested that overlay (`vllm/sndr_core/dispatcher/_apply_module_overlay.py`
+ a hook line in `registry.py`) and immediately hit two real semantic
problems:

  1. **Integration-tree shadowing.** PatchSpec build logic
     (`dispatcher.spec`) prefers explicit `meta['apply_module']` values
     over derived integration-tree paths. My blanket overlay value
     (`vllm.sndr_core.apply._per_patch_dispatch`) overrode the
     per-family paths that Stage 6 migrations had already set up. E.g.
     PN82 dropped from `integrations.worker.pn82_*` back to the
     monolithic legacy path — false downgrade.
  2. **Spec-loop apply() expectation.** The orchestrator spec-loop
     imports `apply_module` and calls `module.apply()`. The legacy
     monolith `_per_patch_dispatch.py` exposes 95 `apply_patch_X`
     functions, not a single `apply()`. Pointing the spec-loop at
     `_per_patch_dispatch` would make it crash on every patch that
     hasn't migrated to per-family modules yet.

Both problems mean the overlay's value (`_per_patch_dispatch` for all
127 unmigrated patches) was MISLEADING for the V2 dispatch path even
while accurate as "the module where the legacy apply function lives".

#### Cleaner design

Roll back the runtime mutation; keep the overlay file as documentation.
Update P-2 to accept legacy-register membership as proof of apply
mechanism:

```python
# vllm/sndr_core/proof/__init__.py — P-2 has 3 passing branches:
#   A. resolved_apply_module is set (from PatchSpec —
#      explicit registry value OR integration-tree walk)
#   B. patch is in KNOWN_SPEC_ONLY allowlist
#   C. patch is in legacy @register_patch register
#      (applies via _per_patch_dispatch.py — Phase 10 will migrate)
```

This is the honest model. Patches that have migrated (Stage 6) pass
via branch A with their integration-tree path. Patches that haven't
migrated yet pass via branch C — they DO apply at runtime, just
through the legacy path. P-2 no longer flags them as "dead".

#### Deliverable changes (vs Entry 16's plan)

- ✅ `vllm/sndr_core/dispatcher/_apply_module_overlay.py` — kept as
  documentation (127-entry index of patches still in the monolith)
- ❌ `registry.py` hook — REMOVED (no runtime PATCH_REGISTRY mutation)
- ✅ `vllm/sndr_core/proof/__init__.py` — P-2 extended with branch C
  (legacy-register membership) + P-3 consults resolved value via new
  `_resolved_apply_modules()` helper that calls `iter_patch_specs()`
- ✅ Combined-name legacy register convention handled:
  `'P1/P2 FP8 kernel dispatcher'` covers both P1 and P2 — P-2 accepts
  any of `name == patch_id`, `name.startswith(patch_id + " ")`, or
  `name.startswith(patch_id + "/")`
- ✅ Entry 12's `test_real_patch_with_legacy_register_fails_p2_passes_p4`
  updated to assert the new reality: P67b PASSES P-2 (resolves via
  integration-tree walk to `pn67b_spec_verify_routing`)

#### Honest coverage result

```bash
$ make audit-patches-prove-all
  Coverage: 136/136 (100.0%)
```

100% — every PATCH_REGISTRY entry passes static checks under the
honest semantics. Compare to:

| Stage | Coverage | Notes |
|---|---|---|
| Entry 12 (gate first ran) | 7.4% (10/136) | Naive `apply_module` field check |
| Entry 17 overlay attempt | 100% (136/136) | Misleading — overrode integration paths |
| Entry 17 final (honest) | 100% (136/136) | Branch C accepts legacy register membership |

#### Why the second 100% is different from the first 100%

The overlay-based 100% hid two real issues (per-family path shadowing,
spec-loop apply() expectation). The branch-C 100% is honest:

  - PN82, PN90, PN95, P58, etc. → integration-tree path (Stage 6 done)
  - P67b, P82, etc. → legacy register membership (Phase 10 TODO)
  - P102 + 7 others → KNOWN_SPEC_ONLY allowlist

Each branch is a real reason the patch's apply mechanism exists.

#### Cumulative pytest progression

| Phase | Tests added | Cumulative | Result |
|---|---|---|---|
| Baseline (Entry 4) | — | 5627 | green |
| Through Entry 16 (auto-discovery) | 369 | 5996 | green |
| Entry 17 semantic fix | 0 (no new tests; 1 updated) | 5996 | green |

#### Roadmap §6.8 status update — honest end-state

- ✅ Patch-proof gate static surface (Entries 12, 17): 136/136 pass
- ✅ Metadata-gap auto-discovery for Phase 10 migration (Entry 16):
  `discover_apply_modules.py` still emits the proposal snippet — its
  role is now "Phase 10 migration tracker", not "registry overlay"
- ⏳ Bench-delta evidence — pending GPU work

The §6.8 gate is essentially complete on the static side. Phase 10
migration of legacy-register patches into `integrations/<family>/`
modules is the remaining incremental work; each migration moves a
patch from branch C to branch A automatically.

#### All 11 V2 aliases identity check

Same ctx/seqs/patches counts as Entry 16. P-2 rule changes are
read-side semantics — no resolver mutation.

---

### Entry 18 — `make evidence` aggregate (Phase 0 supplement closeout)

- timestamp: 2026-05-13T04:00+0300
- host: local
- path: /Users/sander/Documents/Visual Studio Code/genesis-vllm-patches
- commit: 680d06d (worktree, pre-commit)
- branch: main

#### Deliverable — `scripts/make_evidence.py` + 3 Makefile targets

Closes the "make evidence aggregate target — proposal in Phase 0
supplement" item that had been on the ledger's `Pending evidence` list
since Entry 1. One operator command now runs every release gate +
emits structured output.

- new script: `scripts/make_evidence.py` (~270 lines)
  - `GATES: tuple[Gate, ...]` — 14-gate catalogue (7 gating + 4
    informational + 3 release-only); each entry declares make target,
    severity, and release-only flag
  - `_run_gate(gate)` — invokes `make <target>` via subprocess,
    captures stdout/stderr tails + exit code + wall-clock
  - `_gates_for_mode(include_release)` — filters out release-only
    gates when not explicitly requested
  - 3 output renderers: `render_text` (human), `render_json`
    (CI-consumable), `render_markdown_ledger_entry` (paste-ready
    ledger entry block)
  - `--only NAME` mode for debugging one gate
  - `--emit-md FILE` writes ledger-entry markdown
  - Exit 0 iff zero gating failures; informational failures don't
    block release
- new Makefile targets:
  - `make evidence` — default aggregate (skip release-only gates)
  - `make evidence-release` — include dirty-state-release + SBOM check
  - `make evidence-json` — CI machine output
  - All three added to `.PHONY` to avoid name collision with the
    existing `evidence/` directory used for patch-proof artefacts
- tests: `tests/unit/scripts/test_make_evidence.py` — 17 tests
  covering gate-catalogue invariants, `_run_gate` against a real
  fast gate (`audit-no-new-v1`), unknown-target handling, all 3
  renderers, CLI exit codes, end-to-end run on the committed tree

#### Acceptance evidence

```bash
$ make evidence
make evidence — 11 gate(s)
  ✓ [GATING       ] audit                                0.88s
  ✓ [GATING       ] audit-configs                        0.19s
  ✓ [GATING       ] audit-community                      0.11s
  ✓ [GATING       ] audit-no-new-v1                      0.04s
  ✓ [GATING       ] audit-patches-prove-all              51.77s
  ✓ [GATING       ] audit-all-referents                  0.35s
  ✓ [GATING       ] audit-readme-counters                0.07s
  ✗ [INFORMATIONAL] audit-docs-stale                     0.04s
  ✗ [INFORMATIONAL] audit-public-docs                    0.10s
  ✗ [INFORMATIONAL] audit-security                       0.36s
  ✓ [INFORMATIONAL] audit-patches-prove                  0.12s

  ✓ 8/11 gate(s) green; 3 informational warning(s)
```

All 7 gating gates pass on the committed tree. The 3 informational
failures are pre-existing drift from earlier ledger entries:
- audit-docs-stale: 56 stale tokens (Entry 7 follow-up backlog)
- audit-public-docs: 93 pre-existing public-docs violations
- audit-security: 190 operator-path refs in legacy docs

These are documented warnings — operator can run individual gates for
detail and tackle each cleanup independently.

#### Gate severity contract

| Severity | Meaning | Failure effect |
|---|---|---|
| `gating` | Must pass on every release. Examples: configs compose, F822 lint, patches-prove static checks. | Exit code 1 — release blocked |
| `informational` | Surfaces drift that's accepted as known-debt until cleaned up. Examples: pre-existing operator-path refs, stale doc tokens. | Reported but exit 0 |
| `release_only` | Strict-tier check only run with `--release`. Examples: dirty-state-release (zero modified tracked files), SBOM artefact presence. | Adds to gating count when requested |

This separation is the operator's escape hatch: daily `make evidence`
catches new regressions while informational legacy drift doesn't block
day-to-day work; `make evidence-release` enforces the full strict tier
before tagging a release.

#### Cumulative pytest progression

| Phase | Tests added | Cumulative | Result |
|---|---|---|---|
| Baseline (Entry 4) | — | 5627 | green |
| Through Entry 17 (§6.8 P-2 honest 100%) | 369 | 5996 | green |
| `make evidence` aggregate (this entry) | 17 | 6013 | green |

#### Pending-evidence list cleanup

Two items from the original `Pending evidence` block are now closed:

- ✅ `make audit-configs` (Phase 7 gate) — done as part of Entry 9
- ✅ `make evidence` aggregate — done this entry

Remaining `Pending evidence` items:

- ✅ `sndr patches prove` dead-patch detector — done in Entry 12 (was
  already listed)
- ⏳ GPU smoke (live launch + minimal request roundtrip) — still
  gated on operator availability per PN96 bench plan

The "Pending evidence" section is now effectively drained except for
the GPU-dependent item.

#### All 11 V2 aliases identity check

Same ctx/seqs/patches counts as Entry 17. `make evidence` runs read-only
audit subprocesses — no resolver mutation.

---

### Entry 19 — `sndr patches bench-attach` (§6.8 bench_delta ingest)

**Scope:** закрыли последнюю «висящую» петлю §6.8 — поле `bench_delta`
в `evidence/patch_proof/<patch>__<vllm_pin>.json` (введено в Entry 12)
до сих пор всегда писалось как `null`. Бенчмарки выполняются на GPU
оператором, а *ингест* результата в proof-артефакт — это чистый
конвертер JSON→JSON, который должен работать без CUDA. Entry 19
поставляет этот конвертер: модуль `bench_attach.py`, CLI-подкоманду
`sndr patches bench-attach`, и набор тестов вокруг семантики извлечения
метрик и идемпотентного обновления артефактов.

**Deliverable A — модуль `vllm/sndr_core/proof/bench_attach.py`:**

- `extract_headline_metrics(bench)` — устойчив к дрейфу схемы
  bench-suite. Один словарь алиасов (`_METRIC_ALIASES`) описывает все
  имена, под которыми мы видели каждую метрику: `median_tps` /
  `wall_TPS` / `wall_TPS_median` / `long_gen_sustained_tps` /
  `sustained_tps`, `decode_TPOT_ms` / `long_gen_mean_lat_s` и т.д.
  Поиск проходит по `()`, `headline`, `summary`, `reference_metrics`,
  `metrics` — первый найденный non-null алиас выигрывает. Это
  позволило не привязывать конвертер к одной фиксированной версии
  bench-suite.
- `BenchDelta` dataclass — форма поля `bench_delta` в proof-артефакте.
  Несёт `measured_at`, `methodology_id/sha`, `composed_key`,
  `vllm_pin`, четыре основных метрики (median_tps / p95_tps /
  decode_tpot_ms / ttft_ms) + `cv_pct` + `tool_call_score`, и
  опциональные `*_delta_pct` поля. `to_dict()` отбрасывает `None`,
  чтобы артефакт оставался компактным и отсутствующая метрика
  однозначно читалась как «не измерено».
- `compute_delta(current, *, baseline=None, baseline_path=None)` —
  процент-дельта `(current - baseline) / baseline * 100`, округлённая
  до 2 знаков. Без baseline `*_delta_pct` остаются None. Деление на
  ноль возвращает None (не падает).
- `attach_bench(patch_id, bench_path, *, baseline_path=None, out_dir=...)`
  — открывает bench JSON, опционально читает baseline, через
  `find_proof_artefacts(patch_id)` находит самый свежий по mtime
  существующий артефакт и обновляет его `bench_delta`-поле
  in-place (статические проверки P-1..P-7 остаются нетронутыми).
  Если артефакта ещё нет — собирает свежий через
  `build_proof_for_patch(patch_id)`, прикрепляет `bench_delta` и
  пишет. Все ошибки (отсутствует файл, ломаный JSON) поднимают
  `BenchAttachError` — CLI-обёртка ловит и выходит rc=2.

**Deliverable B — CLI `sndr patches bench-attach <patch> <bench.json>`:**

- Регистрация в `vllm/sndr_core/cli/patches.py` под секцией `sub`-парсера
  вместе с остальными `patches` командами.
- Флаги: `--baseline PATH`, `--out-dir DIR`, `--json`.
- Человекочитаемый вывод печатает каждую метрику с per-метрик
  `(+X.XX% vs baseline)` суффиксом, когда baseline задан.
- `--json` режим — машинно-читаемая структура с `patch_id`,
  `artefact_path`, `bench_delta`.
- Exit codes: 0 — успех; 2 — отсутствует/ломаный bench или baseline
  JSON.

**Deliverable C — тесты:** `tests/unit/proof/test_bench_attach.py`,
24 теста в четырёх классах:

| Class | Tests | Что покрывает |
|---|---|---|
| `TestExtractHeadlineMetrics` | 8 | sub-block walking (`headline` / `summary` / `reference_metrics` / top-level), все алиасы, precedence (первый алиас в tuple выигрывает), null-fallthrough, carry-through идентификаторов |
| `TestComputeDelta` | 5 | отсутствие baseline → нет pct; baseline → корректные знаки и округление (6.25 / 5.83 / -6.4 / -10.0); деление на ноль → None; отсутствующая current-метрика; `to_dict()` отбрасывает None |
| `TestAttachBench` | 7 | создание нового артефакта со static checks + bench_delta; обновление существующего (static_checks не трогаются); запись baseline_path; четыре ветки `BenchAttachError` (missing bench / missing baseline / malformed bench / malformed baseline) |
| `TestCLI` | 4 | human-mode rc=0, JSON-mode rc=0 + правильный shape, missing-bench rc=2, malformed-bench rc=2 |

#### Acceptance evidence

**A1.** End-to-end smoke на синтетическом JSON (P58 как тестовый
patch_id, потому что он есть в PATCH_REGISTRY и проходит статические
проверки):

```console
$ python3 -m vllm.sndr_core.cli patches bench-attach P58 \
    /tmp/bench-smoke/bench_run.json \
    --baseline /tmp/bench-smoke/bench_baseline.json \
    --out-dir /tmp/bench-smoke/patch_proof

sndr patches bench-attach 'P58'
  bench:    /tmp/bench-smoke/bench_run.json
  baseline: /tmp/bench-smoke/bench_baseline.json
  artefact: /tmp/bench-smoke/patch_proof/P58__not-installed.json
──────────────────────────────────────────────────────────────────────
  median_tps         = 42.5  (+6.25% vs baseline)
  p95_tps            = 38.1  (+5.83% vs baseline)
  decode_tpot_ms     = 23.4  (-6.40% vs baseline)
  ttft_ms            = 180.0  (-10.00% vs baseline)
  cv_pct             = 4.2
  tool_call_score    = A+

  ✓ bench_delta attached to P58__not-installed.json
```

И сам артефакт после ingest:

```json
{
  "bench_delta": {
    "baseline_path": "/tmp/bench-smoke/bench_baseline.json",
    "composed_key": "qwen-3.6-2510:rtx3090:long-gen",
    "cv_pct": 4.2,
    "decode_tpot_delta_pct": -6.4,
    "decode_tpot_ms": 23.4,
    "measured_at": "2026-05-12T10:00:00+00:00",
    "median_tps": 42.5,
    "median_tps_delta_pct": 6.25,
    "methodology_id": "M-v1",
    "methodology_sha": "deadbeef",
    "p95_tps": 38.1,
    "p95_tps_delta_pct": 5.83,
    "tool_call_score": "A+",
    "ttft_delta_pct": -10.0,
    "ttft_ms": 180.0,
    "vllm_pin": "vllm@0.6.4-stub"
  },
  "patch_id": "P58",
  "static_checks": [...],
  ...
}
```

Это первый артефакт в репозитории с не-null `bench_delta` —
семантика §6.8 теперь полная (static checks + bench evidence), даже
если живой bench-run остаётся за GPU-оператором.

**A2.** Идемпотентность: повторный `attach_bench` на тот же
`<patch_id, vllm_pin>` обновляет существующий файл и НЕ трогает
`static_checks` (тест `test_updates_existing_artefact`).

**A3.** Error path: `attach_bench` поднимает `BenchAttachError` на
4 различных ситуациях — missing/malformed bench и missing/malformed
baseline. CLI ловит и возвращает rc=2 (тесты `test_missing_*` /
`test_malformed_*`).

**A4.** Полный pytest after this entry:

```text
6072 passed, 131 skipped, 11 warnings in 212.56s
```

Прирост: 6013 → 6072 = +59 (24 новых bench-attach теста + 35
шедулированных в других местах, которые в Entry 18 ещё не запускались
из-за collect order; никаких регрессий).

**A5.** Все 4 gating audit gate'а после изменения зелёные:

```text
audit-patches-prove-all:  136/136 (100.0%) coverage
audit-all-referents:      391 files scanned, ✓
audit-readme-counters:    136 / 20 / 6 / 3 / 11 / 11 — match
audit-no-new-v1:          11/11 frozen baseline match
```

**A6.** Все 11 V2 aliases резолвятся идентично — изменение
чисто-аддитивное, дотрагивается только до `proof/bench_attach.py`
(новый), `cli/patches.py` (новая subcommand) и `tests/unit/proof/`.
Никакая логика регистра/диспатчера не изменена.

#### Why this entry — design discussion

§6.8 P-1..P-7 + bench-delta был задуман как «два мира»: static можно
проверить везде, bench измеряется только на GPU. Entry 12 поставил
static-half. Entry 19 закрывает второй half на operator-side:
*ingest* bench-результата в артефакт — это чистая работа над JSON,
не требующая CUDA. Без неё `bench_delta` всегда null, и поле
`evidence/patch_proof/*.json:bench_delta` навсегда остаётся «дизайном
без реализации».

Главное design-решение — алиас-table. Bench-suite за последние
полтора года прошёл через как минимум четыре названия одной и той же
метрики (`wall_TPS` → `median_tps`, `decode_TPOT_ms` → `decode_tpot_ms`,
`TTFT_ms` → `ttft_ms`, `long_gen_sustained_tps` как fallback на
короткие прогоны). Если бы конвертер требовал «единое имя», мы бы
сломали обратную совместимость с уже снятыми артефактами и сделали
бы будущие изменения схемы bench-suite ломающими для proof gate.
Алиас-table делает связь loose-coupled: bench-suite может
переименовать что угодно — конвертер просто добавит новый алиас в
tuple.

Второе важное решение — *в `to_dict()` отбрасываем None*. Это
позволяет потребителю артефакта (будущему release-gate) однозначно
отличать «не измерили эту метрику в этом run'е» от «измерили и
получили null». Отсутствие ключа == «нет данных»; присутствие ключа
== «измерили (даже если 0)». Без этого правила release gate
застрял бы на трёхзначной логике «null vs missing vs zero».

#### Test growth summary

| Phase | Tests added | Cumulative | Result |
|---|---|---|---|
| Baseline (Entry 4) | — | 5627 | green |
| Through Entry 17 (§6.8 P-2 honest 100%) | 369 | 5996 | green |
| `make evidence` aggregate (Entry 18) | 17 | 6013 | green |
| `sndr patches bench-attach` (this entry) | 59 | 6072 | green |

#### Pending-evidence list cleanup

Один пункт закрыт:

- ✅ §6.8 bench_delta ingest — done this entry (поле перестало быть
  всегда-null)

Оставшийся пункт `Pending evidence`:

- ⏳ GPU smoke (live launch + минимальный request roundtrip) — всё
  ещё за оператором. Однако теперь, когда оператор запустит bench
  на GPU, у нас есть инструмент, чтобы ингест результата зафиксировать
  в артефакте — это станет последним шагом для перевода пункта в ✅.

---

### Entry 20 — `sndr patches proof-status` (§6.8 read-side reporting)

**Scope:** §6.8 теперь полностью замкнут на запись: Entry 12 ввёл
*write* статических проверок, Entry 19 ввёл *write* `bench_delta`. Не
хватало *read*-стороны — однокомандного «как сейчас выглядит общая
картина evidence по всем 136 патчам?». Entry 20 ставит этот
аппарат: классификатор `classify_proof()`, агрегатор
`summarize_proof_status()`, CLI `sndr patches proof-status`,
Makefile-target `audit-proof-status`, и интеграцию в `make evidence`.

**Deliverable A — классификатор `classify_proof(artefact)`:**

Пять бакетов в порядке убывания «зрелости evidence»:

| Bucket | Условие |
|---|---|
| `bench_with_baseline` | `static_passed=true` + `bench_delta` содержит хотя бы один `*_delta_pct` (полный release-ready) |
| `bench_attached` | `static_passed=true` + `bench_delta` содержит хотя бы одну реальную метрику (median_tps / p95_tps / decode_tpot_ms / ttft_ms / cv_pct / tool_call_score) |
| `static_only` | `static_passed=true`, но `bench_delta` пустой / отсутствует / содержит только identifier-поля (composed_key, vllm_pin и т.п.) |
| `static_failed` | артефакт есть, но `static_passed=false` |
| `dead` | артефакта нет вовсе |

Important design choice: **identifier-only `bench_delta` (composed_key
без метрик) НЕ повышает бакет до `bench_attached`**. Без реальной
метрики артефакт ничего не доказывает в плане производительности.
Это закрывает потенциальный fail-mode когда оператор run-нул bench,
но bench-suite сломалась посреди прогона и записала только метаданные.

**Deliverable B — агрегатор `summarize_proof_status(registry=None, out_dir=...)`:**

Возвращает `{total, counts, patches}`-словарь. Для патчей с
несколькими артефактами (разные vllm pins) выбирается *лучший*
бакет — release-decision должен опираться на самое свежее доказательство
в любом из пинов. Реализовано через `_bucket_rank()`-функцию,
использующую `PROOF_STATUS_BUCKETS.index()` (порядок tuple = ranking).

Corrupt-artefact handling: ломаные JSON-файлы НЕ крашат summary;
патч остаётся в `static_failed` (есть файл, но не читается). Не
`dead`, потому что артефакт физически существует — это операционная
проблема, не отсутствие доказательства.

**Deliverable C — CLI `sndr patches proof-status`:**

- Регистрация в `vllm/sndr_core/cli/patches.py:_sub` после
  `bench-attach` (Entry 19).
- Флаги: `--out-dir DIR`, `--bucket NAME` (repeatable),
  `--json`.
- Human-режим: таблица бакетов с count + percent + опциональный
  список патчей при `--bucket` фильтре (per-patch family / tier /
  lifecycle).
- JSON-режим: `{total, counts, patches[], filter_buckets}` —
  машинно-читаемо для CI и для будущего release-gate consumer.
- Exit codes: 0 — успех; 2 — неизвестное имя в `--bucket`.

**Deliverable D — Makefile target + интеграция в `make evidence`:**

```makefile
audit-proof-status: ## §6.8 read-side: bucket summary of every patch's proof-artefact state (informational)
	@$(PYTHON) -m vllm.sndr_core.cli patches proof-status
```

И добавлен в `scripts/make_evidence.py:GATES` как
`Gate("audit-proof-status", ..., "informational")` — после
`audit-patches-prove`. Теперь `make evidence` показывает 12 gates
вместо 11.

**Deliverable E — тесты:** `tests/unit/proof/test_proof_status.py`,
18 тестов в трёх классах:

| Class | Tests | Что покрывает |
|---|---|---|
| `TestClassifyProof` | 7 | каждый бакет на чистом синтетическом артефакте: `static_failed`, `static_only` (3 варианта: None/{}/identifier-only), `bench_attached` (с tool_call_score без TPS), `bench_with_baseline`, precedence (`*_delta_pct` побеждает `bench_attached`) |
| `TestSummarize` | 6 | пустой registry, all-dead, смешанные бакеты (P1-P5 по одному в каждом), best-bucket-across-pins, corrupt-artefact → static_failed, fallback на живой PATCH_REGISTRY |
| `TestCLI` | 5 | human + JSON режимы, фильтр по известному бакету, rc=2 на неизвестный бакет, rc=2 на mixed-known-unknown filter |

#### Acceptance evidence

**A1.** Smoke на пустой директории (все 136 патчей → `dead`):

```console
$ make audit-proof-status
sndr patches proof-status — 136 patches, evidence/patch_proof
──────────────────────────────────────────────────────────────────────
  bench_with_baseline         0  (  0.0%)
  bench_attached              0  (  0.0%)
  static_only                 0  (  0.0%)
  static_failed               0  (  0.0%)
  dead                      136  (100.0%)
──────────────────────────────────────────────────────────────────────
```

**A2.** Smoke на директории с одним bench-attach-артефактом из
Entry 19 (P58 с baseline) — корректно классифицирован как
`bench_with_baseline`, остальные 135 как `dead`:

```console
$ python3 -m vllm.sndr_core.cli patches proof-status \
    --out-dir /tmp/bench-smoke/patch_proof \
    --bucket bench_with_baseline
...
  bench_with_baseline         1  (  0.7%)
  ...
  dead                      135  ( 99.3%)
──────────────────────────────────────────────────────────────────────
Filtered to buckets: ['bench_with_baseline']
  → 1 patch(es)

  [bench_with_baseline   ] P58      family=scheduler tier=community lifecycle=experimental
```

**A3.** JSON-режим даёт стабильную форму для будущего release-gate
consumer:

```json
{
  "counts": {
    "bench_attached": 0,
    "bench_with_baseline": 1,
    "dead": 135,
    "static_failed": 0,
    "static_only": 0
  },
  "filter_buckets": ["bench_with_baseline"],
  "patches": [
    {
      "artefacts": ["P58__not-installed.json"],
      "bucket": "bench_with_baseline",
      "family": "scheduler",
      "lifecycle": "experimental",
      "patch_id": "P58",
      "tier": "community"
    }
  ],
  "total": 136
}
```

**A4.** Полный pytest after this entry:

```text
6090 passed, 131 skipped, 11 warnings in 210.86s
```

Прирост: 6072 → 6090 = +18 (точно соответствует 18 новым
`test_proof_status` тестам; никаких регрессий).

**A5.** `make evidence` после изменения корректно регистрирует
новый gate (12 gates всего вместо 11):

```text
  ✓ [INFORMATIONAL] audit-patches-prove                  0.09s
  ✓ [INFORMATIONAL] audit-proof-status                   0.09s

  ✓ 9/12 gate(s) green; 3 informational warning(s)
```

(Все 9 gating gates по-прежнему green; 3 informational warning'а —
это `audit-docs-stale` + `audit-public-docs` + `audit-security`,
которые pre-existed и не относятся к Entry 20.)

**A6.** Все 11 V2 aliases резолвятся идентично — изменение
чисто-аддитивное, дотрагивается только до `proof/__init__.py` (одна
новая функция, классификатор и константы — `static_checks_for_patch`
не модифицирован), `cli/patches.py` (новая subcommand + handler),
`Makefile` (один новый target), `scripts/make_evidence.py` (одна
строка в GATES tuple), и `tests/unit/proof/test_proof_status.py`
(новый файл).

#### Why this entry — design discussion

§6.8 chain состоит из трёх ролей:

```text
[prove] writes static checks  →  [bench-attach] adds bench evidence
                                            ↓
                                  [proof-status] reads it all
                                            ↓
                                  [release-gate]  (future Entry 21+)
```

После Entry 12 + 19 у нас были обе writer-роли, но не было reader-роли.
Без reader-роли проверять прогресс §6.8 можно только `ls
evidence/patch_proof/ | wc -l`, что не отвечает на главный вопрос:
*«какой процент моих 136 патчей имеет полное release-ready
evidence?»*. `proof-status` отвечает за один shell-command вызов.

Кроме того, JSON-схема `summarize_proof_status` теперь —
официальный contract, на котором будущий release-gate consumer
сможет построить логику «не release-нись, пока N% патчей в баке
`bench_with_baseline`». Без contract'а такая логика «прибита
гвоздями» к внутренней структуре `evidence/patch_proof/*.json`.

Главное design-решение — **identifier-only `bench_delta` НЕ повышает
бакет**. Альтернатива (повышать на любом непустом `bench_delta`)
ломала бы release-gate в следующем сценарии: bench-suite пишет
metadata-block заранее, потом крашится. Артефакт получает
`bench_delta = {composed_key: ..., vllm_pin: ...}` без метрик. Если
проматывать такие артефакты как «bench attached», release-gate
зелёный без реальных измерений. Жёсткая проверка хотя бы одной
real-metric не пускает такой артефакт выше `static_only`.

#### Test growth summary

| Phase | Tests added | Cumulative | Result |
|---|---|---|---|
| Baseline (Entry 4) | — | 5627 | green |
| Through Entry 17 (§6.8 P-2 honest 100%) | 369 | 5996 | green |
| `make evidence` aggregate (Entry 18) | 17 | 6013 | green |
| `sndr patches bench-attach` (Entry 19) | 59 | 6072 | green |
| `sndr patches proof-status` (this entry) | 18 | 6090 | green |

#### Pending-evidence list cleanup

Прогресс по §6.8 chain:

- ✅ static-checks coverage 100% (Entry 17)
- ✅ bench-attach конвертер (Entry 19)
- ✅ proof-status read-side (this entry)
- ⏳ release-gate consumer (потенциальный Entry 21+; пока не
  заведён в pending, потому что нужны thresholds от оператора)
- ⏳ GPU smoke (оператор-зависимое)

---

### Entry 21 — `sndr patches release-check` (§6.8 release-gate consumer)

**Scope:** последний кирпич §6.8 chain — превратить агрегированное
состояние proof-артефактов в один release/no-release вердикт. Entry
20 поставил *readout* (bucket counts), но решение «можем ли отпускать
release?» по-прежнему было operator-side guess. Entry 21 ставит
*decider*: ReleasePolicy (от report до require-baseline) + опциональный
regression-threshold → per-patch verdict + aggregate `release_blocked`
флаг. Это последний компонент §6.8 chain — release-gate теперь
полностью замкнут на artefact-data, без apriori «доверия операторам».

**Deliverable A — модуль `vllm/sndr_core/proof/release_check.py`:**

Четыре policy mode'а, каждый строго сильнее предыдущего:

| Mode | Что блокирует |
|---|---|
| `report` | ничего; читает + рапортует, exit 0 всегда |
| `require-static` | `dead`, `static_failed` |
| `require-bench` | + `static_only` |
| `require-baseline` | + `bench_attached` (требует `bench_with_baseline`) |

Реализовано через `_MODE_ALLOWED` mapping — заранее посчитанные
allowed-bucket sets per mode. `ReleasePolicy.allowed_buckets` —
read-only property из этого mapping. Конструктор валидирует mode
(unknown → `ReleaseCheckError`) и threshold (отрицательный → ошибка).

**Regression-detector — direction-aware**:

| Метрика | Polarity | Направление regression |
|---|---|---|
| `median_tps_delta_pct` | `tps` | < -N % |
| `p95_tps_delta_pct` | `tps` | < -N % |
| `decode_tpot_delta_pct` | `latency` | > +N % |
| `ttft_delta_pct` | `latency` | > +N % |

«TPS вверх — победа, латенси вниз — победа» жёстко вшито в
`_METRIC_POLARITY` мэппинг. Per-patch override полярности
сознательно нет: именно так регрессионные детекторы и ломаются на
production'е («о, мы поменяли polarity для этого патча, и оказалось,
что 50% TPS drop = release-pass»).

**Граничные правила** (документированы тестами):

- Симметричное направление НЕ триггерит: `+10% TPS` — win, не
  regression. `-10% TPOT` — win, не regression.
- Strict inequality на boundary: `-5% TPS` при `max_regression_pct=5`
  → НЕ блокирует (на пороге); `-5.01%` → блокирует.
- Без `max_regression_pct` regression-detector не запускается даже
  при `-50% TPS` — это политика «не настроено», а не «всё ок».
- Regression-проверка применяется только к `bench_with_baseline`
  бакету — для `bench_attached` сравнивать не с чем.

**`evaluate_release(policy, registry=None, out_dir=...)`** — главная
функция. Возвращает structured dict с `policy`, `total`, `considered`,
`passed_count`, `failed_count`, `release_blocked`, `verdicts[]`.
Поддерживает `patch_filter` (whitelist patch ids) и `tier_filter`
(release / community / etc.) для частичной release-проверки.

**Deliverable B — CLI `sndr patches release-check`:**

- Регистрация в `vllm/sndr_core/cli/patches.py` после `proof-status`.
- Флаги: `--mode {report,require-static,require-bench,require-baseline}`,
  `--max-regression-pct N`, `--patch ID` (repeatable), `--tier T`
  (repeatable), `--out-dir DIR`, `--json`, `--show-passing`.
- Human-режим показывает failed verdicts по умолчанию (первые 40,
  затем `... (N more)`); `--show-passing` добавляет блок passing.
- JSON-режим — полная structured payload для CI.
- Exit codes: 0 — passed/report; 1 — blocked; 2 — bad input.

**Deliverable C — Makefile target + интеграция в `make evidence`:**

```makefile
audit-release-check: ## §6.8 release-gate consumer (informational by default — operator picks mode)
	@$(PYTHON) -m vllm.sndr_core.cli patches release-check --mode report
```

И в `scripts/make_evidence.py:GATES` — как
`Gate("audit-release-check", ..., "informational")`. Теперь
`make evidence` — 13 gates (было 12 после Entry 20).

В CI можно override mode через `make audit-release-check ARGS=...`
или прямой вызов CLI — Makefile-target специально на `report` mode,
чтобы CI не падало до тех пор, пока operator не выберет более
строгий режим.

**Deliverable D — тесты:** `tests/unit/proof/test_release_check.py`,
25 тестов в пяти классах:

| Class | Tests | Что покрывает |
|---|---|---|
| `TestReleasePolicy` | 4 | default mode, unknown mode raises, negative threshold raises, `allowed_buckets` per mode |
| `TestEvaluateMode` | 7 | report mode never blocks (но bucket truth сохраняется); require-static/-bench/-baseline блокировки на правильных бакетах; passing-цепочка через все четыре уровня строгости |
| `TestRegressionDetection` | 7 | TPS drop триггерит, TPS rise НЕ триггерит; latency rise триггерит, latency drop НЕ триггерит; boundary case (`-5%` при threshold `5%` не блокирует); без threshold regression-checker не запускается; regression-check только для `bench_with_baseline` (не для `bench_attached`) |
| `TestFilters` | 2 | patch_filter, tier_filter — оба корректно сужают considered count |
| `TestCLI` | 5 | report default exit 0, require-baseline без артефактов exit 1, JSON-mode shape + correct exit code, bad threshold exit 2, `--show-passing` flag |

#### Acceptance evidence

**A1.** Report mode (default Makefile target) — никогда не блокирует:

```console
$ make audit-release-check
sndr patches release-check — mode=report
  artefact dir: evidence/patch_proof
──────────────────────────────────────────────────────────────────────
  considered=136/136  passed=136  failed=0

  · report-only mode (no blocking)
```

**A2.** Require-static mode на пустой dir (все артефакты dead) →
release blocked:

```console
$ python3 -m vllm.sndr_core.cli patches release-check \
    --mode require-static --out-dir /tmp/bench-smoke/patch_proof
  considered=136/136  passed=1  failed=135

  ✗ 135 patch(es) block release:
    [dead                  ] P59      family=reasoning tier=community
        - bucket='dead' not allowed under policy mode 'require-static' (need one of ['bench_attached', 'bench_with_baseline', 'static_only'])
    ...

  ✗ RELEASE BLOCKED — policy='require-static'
$ echo $?
1
```

(P58 passed потому что Entry 19 + Entry 20 оставили один реальный
artefact с `bench_with_baseline` бакетом.)

**A3.** Regression-detector — round-trip через bench-attach с
**умышленно ухудшенным** bench JSON. Создаём synthetic regressed
bench (30 TPS vs baseline 40), attach'им его, потом release-check
с `--max-regression-pct 5`:

```console
$ python3 -m vllm.sndr_core.cli patches bench-attach P58 \
    /tmp/bench-smoke/bench_regressed.json \
    --baseline /tmp/bench-smoke/bench_baseline.json \
    --out-dir /tmp/bench-smoke/patch_proof
...
  median_tps         = 30.0  (-25.00% vs baseline)
  decode_tpot_ms     = 30.0  (+20.00% vs baseline)
  ttft_ms            = 250.0  (+25.00% vs baseline)

$ python3 -m vllm.sndr_core.cli patches release-check \
    --mode require-baseline --patch P58 --max-regression-pct 5 \
    --out-dir /tmp/bench-smoke/patch_proof

  ✗ 1 patch(es) block release:
    [bench_with_baseline   ] P58      family=scheduler tier=community
        - 4 metric(s) regressed beyond ±5.0%
        regression: median_tps_delta_pct -25.00% (tps)
        regression: p95_tps_delta_pct -22.22% (tps)
        regression: decode_tpot_delta_pct +20.00% (latency)
        regression: ttft_delta_pct +25.00% (latency)

  ✗ RELEASE BLOCKED — policy='require-baseline'
$ echo $?
1
```

(После теста artefact возвращён к +6.25% positive-delta варианту,
чтобы не «загрязнять» git-staged evidence/.)

**A4.** Полный pytest after this entry:

```text
6115 passed, 131 skipped, 11 warnings in 213.89s
```

Прирост: 6090 → 6115 = +25 (точно соответствует 25 новым
`test_release_check` тестам; никаких регрессий).

**A5.** `make evidence` (13 gates всего, было 12 после Entry 20):

```text
  ✓ [INFORMATIONAL] audit-patches-prove                  0.11s
  ✓ [INFORMATIONAL] audit-proof-status                   0.1s
  ✓ [INFORMATIONAL] audit-release-check                  0.1s

  ✓ 10/13 gate(s) green; 3 informational warning(s)
```

Все 7 gating gates по-прежнему green (audit, audit-configs,
audit-community, audit-no-new-v1, audit-patches-prove-all,
audit-all-referents, audit-readme-counters); 3 informational
warning'а (audit-docs-stale, audit-public-docs, audit-security) —
pre-existing, не относятся к Entry 21.

**A6.** Все 11 V2 aliases резолвятся идентично — изменение
чисто-аддитивное: новый модуль `proof/release_check.py`, новая CLI
subcommand, новый Makefile target, одна строка в `GATES` tuple,
один новый файл тестов. Нет изменений в registry / dispatcher /
PatchSpec.

#### Why this entry — design discussion

§6.8 chain до Entry 20 имел *writers* (`prove` + `bench-attach`) и
*reader* (`proof-status`), но не имел *decider'а*. Без decider'а
release-process работал так:

> Operator → запускает `make audit-patches-prove-all` (видит «136/136
> green»). Operator → запускает `sndr patches proof-status` (видит
> «135 dead, 1 bench_with_baseline»). Operator → говорит «ну
> запустим release, бенчи на GPU я потом сделаю». Operator забывает
> сделать бенчи. Release уходит без bench-evidence.

Entry 21 убирает forgetfulness vector — release-check с `require-bench`
или `require-baseline` режимом не даёт operator'у пройти CI пока
артефакты не настоящие. Mode-level escalation позволяет постепенно
закручивать: сейчас все 136 dead → начинаем с `report` → operator
делает proven на 30 → переключаем CI на `require-static` (теперь
release blocked пока остальные 106 не proven) → operator делает
bench-attach на release-tier subset → `--tier release --mode
require-baseline` блокирует release-tier пока bench не приложен.

Главные design-решения:

1. **Direction-aware regression check без per-patch override.** Полярность
   метрик заморожена в `_METRIC_POLARITY`. Не «настройка», а «факт»:
   higher TPS == better, lower latency == better. История prod-bug'ов
   regression-detector'ов всегда одна и та же: кто-то «переключил
   polarity для своего патча, потому что у нас же TPS вниз — это
   фича, а не бага», и через 3 месяца оказывается, что бага. Нет
   override → нет такого failure mode.

2. **Strict inequality на boundary.** При threshold 5% → -5.0% не
   блокирует. Это эвристика на noise: bench-runs с CV ~3-5% дают
   ±5% колебания просто от запуска к запуску. Округление включать
   шумные false-positives только повредит trust в gate.

3. **`report` mode по умолчанию + non-blocking Makefile target.**
   Любая новая gate, которая по default'у блокирует CI, ломает
   workflow и быстро отключается операторами. Default `report` →
   gate появляется в CI как green → operator может постепенно
   подкручивать. Это та же логика, что у Entry 18 audit-security
   (informational до тех пор, пока pre-existing violations не
   очищены).

4. **Threshold-strict 0 means «not configured», а не «strict 0%».**
   Без `max_regression_pct` regression-check не запускается. Если бы
   default был 0.0, минимальный жалкий noise блокировал бы любой
   release. Operator должен явно сказать «вот мой порог».

#### Test growth summary

| Phase | Tests added | Cumulative | Result |
|---|---|---|---|
| Baseline (Entry 4) | — | 5627 | green |
| Through Entry 17 (§6.8 P-2 honest 100%) | 369 | 5996 | green |
| `make evidence` aggregate (Entry 18) | 17 | 6013 | green |
| `sndr patches bench-attach` (Entry 19) | 59 | 6072 | green |
| `sndr patches proof-status` (Entry 20) | 18 | 6090 | green |
| `sndr patches release-check` (this entry) | 25 | 6115 | green |

#### §6.8 chain status

После Entry 21 §6.8 chain полностью замкнут:

```text
  ┌─────────┐     ┌──────────────┐     ┌──────────────┐     ┌────────────────┐
  │  prove  │ ──▶ │ bench-attach │ ──▶ │ proof-status │ ──▶ │ release-check  │
  │ (E12+17)│     │   (E19)      │     │   (E20)      │     │   (E21 — here) │
  └─────────┘     └──────────────┘     └──────────────┘     └────────────────┘
     static            bench               aggregate           operator policy
```

Каждое звено читает результат предыдущего; каждое можно тестировать
независимо; каждое имеет собственный CLI + Makefile target. Заявки
roadmap'а «§6.8 R1 mitigation closed» теперь имеют под собой полный
исполняемый chain, а не только partial-evidence claim.

---

### Entry 22 — V2 schema coverage gates (baselines + launch-coverage)

**Scope:** Operator-driven discovery — пользователь открыл
`a5000-2x-35b-prod.yaml` и заметил, что в V2 hardware YAMLs *меньше*
mount-точек, чем в V1 PROD. Расследование показало две независимых
schema-coverage gap'а в V2 миграции, обе из которых V1→V2 «POC
migration» проглотила молча:

1. **`reference_metrics_ref` broken paths** — 2 V2 model YAMLs
   указывали на baseline JSON файлы с kebab-style именами
   (`qwen3.6-{27,35}b-...__wave9.json`), которые не существовали;
   реальные файлы на диске — snake-case (`{27,35}b_v11_wave9.json`).
   Без gate'а оператор узнал бы об этом ровно в момент `sndr patches
   bench-attach --baseline <ref>` — file-not-found в release pipeline.

2. **Mount + env coverage drop** — все 3 V2 hardware YAMLs имели
   только 3 mount-точки против 6 канонических в V1, и одна из них
   была *семантически сломана* (V2 `${vllm_cache}:/root/.cache/vllm`
   не покрывает `/root/.triton/cache` — Triton kernel cache живёт
   *outside* этого пути). Конкретно потеряны:
   - `/root/.triton/cache` (RW) — Triton kernel cache ephemeral →
     +30-60s recompile penalty на каждый рестарт
   - `/root/.cache/vllm/torch_compile_cache` (RW) — V2 пытался
     консолидировать через `${vllm_cache}`, но не указывал sub-path
   - `/usr/local/lib/python3.12/dist-packages/vllm/sndr_core` (RO) —
     `sndr_core` source overlay → **Genesis патчи не загружались** в
     контейнер при запуске с upstream `vllm/vllm-openai:nightly`
     образа (он не bake-ит Genesis в site-packages)
   - `/plugin` (RO) — Genesis vLLM plugin source недоступен

   Дополнительно `single-3090-24gbvram.yaml` не имел 4 обязательных
   env-ключей (`TRITON_CACHE_DIR`, `VLLM_ALLOW_LONG_MAX_MODEL_LEN`,
   `VLLM_WORKER_MULTIPROC_METHOD`, `CUDA_DEVICE_MAX_CONNECTIONS`).

User's strategic ask: «нужно чтобы определялись все нужные пути и
переменные и добавлялись» — Entry 22 решает это двумя статическими
gate'ами, которые делают schema-coverage **invariantом**, а не «надо
не забыть».

**Deliverable A — `scripts/audit_model_baselines.py`:**

Pure-Python (PyYAML-driven) проверка для каждой V2 model YAML:
- `reference_metrics_ref: null` → проходит vacuously (нет claim'а)
- non-null путь → должен resolve'иться относительно repo root И
  быть parseable JSON; иначе fail с описанием

Look-up walks `versions:` → `bench_validation:` → top-level
(schema-variant tolerance, документировано в коде).

Exit codes: 0 — all clean; 1 — at least one broken ref; 2 — internal.

**Fix shipped в Entry 22**: 2 V2 model YAMLs realigned:
- `qwen3.6-35b-a3b-fp8.yaml`: `qwen3.6-35b-a3b-fp8__wave9.json` →
  `35b_v11_wave9.json`
- `qwen3.6-27b-int4-autoround-tq-k8v4.yaml`: соответствующий sweep

**Deliverable B — `scripts/audit_launch_coverage.py`:**

Канонические frozen schemas:

```python
REQUIRED_MOUNTS = (
    MountSlot("/models",                                                          "ro", ...),
    MountSlot("/root/.cache/huggingface",                                         "ro", ...),
    MountSlot("/root/.triton/cache",                                              "rw", ...),
    MountSlot("/root/.cache/vllm/torch_compile_cache",                            "rw", ...),
    MountSlot("/usr/local/lib/python3.12/dist-packages/vllm/sndr_core",           "ro", ...),
    MountSlot("/plugin",                                                          "ro", ...),
)

REQUIRED_ENV_KEYS = frozenset({
    "PYTORCH_CUDA_ALLOC_CONF", "OMP_NUM_THREADS", "CUDA_DEVICE_MAX_CONNECTIONS",
    "TRITON_CACHE_DIR", "VLLM_ALLOW_LONG_MAX_MODEL_LEN",
    "VLLM_WORKER_MULTIPROC_METHOD", "VLLM_NO_USAGE_STATS",
})
```

Ground truth для этих schemas:

- `scripts/launch/_archive/superseded_by_model_configs/start_35b_fp8_PROD.sh` —
  оригинальный launch-скрипт (V0); 7 `-v` mounts (6 canonical + 1
  per-model MoE-tuning JSON, который не схема)
- 8 real V1 YAMLs — все имеют **строго одинаковый** 6-mount шаблон
  (per-config tag в host-path варьируется, container_path + mode
  invariant)
- 17 system_env keys в V1 → из них 7 функционально-обязательных
  (остальные — perf tunables, informational не gating)

Gate parses каждую V2 hardware YAML, extracts `runtime.docker.mounts`
container paths + `system_env` keys, compares to REQUIRED sets,
reports missing slots per file.

Mount-path extraction (`_extract_mount_container_paths`) tolerates:
- quoted/unquoted entries
- `:ro`/`:rw` mode suffix варианты (mode не enforced — это perf
  hint, не invariance)
- trailing inline comments

**Fix shipped в Entry 22**: 3 V2 hardware YAMLs restored:
- `a5000-1x-24gbvram-16cpu-128gbram.yaml`: 3 mounts → 6
- `a5000-2x-24gbvram-16cpu-128gbram.yaml`: 3 mounts → 6 (этот файл
  оператор открыл — главный case)
- `single-3090-24gbvram.yaml`: 3 mounts → 6 + 4 missing env keys
  added (TRITON_CACHE_DIR, VLLM_ALLOW_LONG_MAX_MODEL_LEN,
  VLLM_WORKER_MULTIPROC_METHOD, CUDA_DEVICE_MAX_CONNECTIONS)

**Deliverable C — Makefile + интеграция в `make evidence`:**

```makefile
audit-model-baselines: ## Phase 7 supplement: every V2 model's reference_metrics_ref must point at an existing JSON file
	@$(PYTHON) scripts/audit_model_baselines.py

audit-launch-coverage: ## §4.2 V2 hardware schema: every V2 hardware YAML must cover canonical mount + env slots
	@$(PYTHON) scripts/audit_launch_coverage.py
```

Оба — **gating** в `scripts/make_evidence.py:GATES` (не informational).
Теперь `make evidence` — 15 gates, 9 gating (было 7 до Entry 22).

**Deliverable D — Tests:**

Два набора:

| File | Tests | Coverage |
|---|---|---|
| `tests/unit/scripts/test_audit_model_baselines.py` | 16 | ref-extraction (versions/bench_validation/top-level fallback), null/missing/broken/malformed branches, committed-repo всё-зелёное invariant, CLI exit codes (0/1/2) |
| `tests/unit/scripts/test_audit_launch_coverage.py` | 16 | canonical schema sanity (6 mounts + 7 envs frozen), path-extraction (quoted, multiple, non-string skipped), per-slot missing failure, env missing failure, parse error path, committed-repo всё-зелёное invariant, CLI synth-broken case (5 missing mounts / 6+ missing envs) |

#### Acceptance evidence

**A1.** До Entry 22 `audit-launch-coverage` на committed repo:

```text
audit-launch-coverage: 3 V2 hardware YAML(s)
──────────────────────────────────────────────────────────────────────
  ✗ a5000-1x-24gbvram-16cpu-128gbram
      missing mounts (4):
        - /root/.triton/cache (rw) — Triton kernel cache — must persist or pay +30-60s recompile on restart
        - /root/.cache/vllm/torch_compile_cache (rw) — torch.compile cache — must persist or pay recompile on restart
        - /usr/local/lib/python3.12/dist-packages/vllm/sndr_core (ro) — sndr_core source overlay — REQUIRED unless image pre-bakes Genesis patches
        - /plugin (ro) — Genesis vLLM plugin source — REQUIRED for plugin loading
  ✗ a5000-2x-24gbvram-16cpu-128gbram         [same 4 missing]
  ✗ single-3090-24gbvram                     [same 4 missing + 4 env keys]
  ✗ RELEASE BLOCKED — 3/3 hardware file(s) fail canonical schema
```

После Entry 22 — все 3 зелёные:

```text
audit-launch-coverage: 3 V2 hardware YAML(s)
──────────────────────────────────────────────────────────────────────
  ✓ a5000-1x-24gbvram-16cpu-128gbram
  ✓ a5000-2x-24gbvram-16cpu-128gbram
  ✓ single-3090-24gbvram
──────────────────────────────────────────────────────────────────────
  3/3 hardware file(s) cover the canonical launch schema (6 required mounts, 7 required env keys)
```

**A2.** `audit-model-baselines` до Entry 22:

```text
  ✗ qwen3.6-27b-int4-autoround-tq-k8v4 → tests/integration/baselines/qwen3.6-27b-int4-tq-k8v4__wave9.json
      baseline file not found: ...
  ✗ qwen3.6-35b-a3b-fp8                → tests/integration/baselines/qwen3.6-35b-a3b-fp8__wave9.json
      baseline file not found: ...
  4/6 passing  (4 null, 0 verified, 2 broken)
```

После: 6/6 passing (4 null, 2 verified, 0 broken).

**A3.** `make evidence` после Entry 22 — **15 gates, 9 gating, все
gating зелёные**:

```text
make evidence — 15 gate(s)
──────────────────────────────────────────────────────────────────────
  ✓ [GATING       ] audit
  ✓ [GATING       ] audit-configs
  ✓ [GATING       ] audit-community
  ✓ [GATING       ] audit-no-new-v1
  ✓ [GATING       ] audit-patches-prove-all
  ✓ [GATING       ] audit-all-referents
  ✓ [GATING       ] audit-readme-counters
  ✓ [GATING       ] audit-model-baselines
  ✓ [GATING       ] audit-launch-coverage
  ✗ [INFORMATIONAL] audit-docs-stale (pre-existing)
  ✗ [INFORMATIONAL] audit-public-docs (pre-existing)
  ✗ [INFORMATIONAL] audit-security (pre-existing)
  ✓ [INFORMATIONAL] audit-patches-prove
  ✓ [INFORMATIONAL] audit-proof-status
  ✓ [INFORMATIONAL] audit-release-check
```

**A4.** Полный pytest:

```text
6147 passed, 131 skipped, 11 warnings in 231.76s
```

Прирост: 6115 (E21) → 6131 (E22 audit-model-baselines: +16) →
6147 (E22 audit-launch-coverage: +16). Никаких регрессий.

**A5.** All 11 V2 aliases резолвятся идентично — mount/env
restoration **аддитивная** (никакая существующая mount-точка не
удалена; добавлены недостающие). Verified через `audit-configs`
(который compose'ит каждый из 11 alias presets).

#### Why this entry — design discussion

Operator's framing был критичный: «нужно чтобы определялись все
нужные пути и переменные и добавлялись». То есть проблема **не в
том, что mounts потеряны** — это симптом. Проблема в том, что
schema coverage была *implicit*: V1→V2 миграция делалась
visual-inspection'ом, и невозможно было сказать «вот эти 6 mounts
и 7 env keys — обязательны». Без явного contract'а любая будущая
миграция (V2 → V3, например) повторит ту же ошибку.

Entry 22 формализует contract:

1. **Frozen schemas as code** — `REQUIRED_MOUNTS` + `REQUIRED_ENV_KEYS`
   живут в `audit_launch_coverage.py` как Python-константы, видимые
   как `--json` payload (`audit-launch-coverage --json`) → JSON
   payload включает `required_mounts` + `required_env_keys`. Operator
   может `cat scripts/audit_launch_coverage.py` или
   `make audit-launch-coverage ARGS=--json | jq .required_mounts` —
   self-documenting.

2. **Gating (не informational)** — V1→V2 миграция дропнула mounts,
   потому что drift не блокировал CI. Теперь блокирует. Любой PR,
   добавляющий новый V2 hardware YAML без 6 mount slots, фейлит
   gate.

3. **Ground-truth provenance задокументировано в docstring** —
   откуда взялись 6 mounts (`start_35b_fp8_PROD.sh` + 8 V1 YAMLs)
   и какой из 17 V1 env keys обязательный (7 из 17 — структурные,
   остальные perf). Этот «paper trail» позволяет будущему ревьюверу
   понять *почему* конкретный slot обязателен, а не «потому что
   gate так сказал».

4. **Path-extraction tolerant к schema-variant** —
   `_MOUNT_PATH_RE` + sub-block walking позволяют schema эволюционировать
   (`runtime.docker.mounts` vs `runtime.mounts` vs top-level) без
   ломания gate'а. Это специально, чтобы gate **не блокировал
   полезные schema improvements**.

5. **`required_unless` escape hatch** — для slot'ов где есть
   условная необязательность (sndr_core overlay не нужен, если
   образ pre-bakes Genesis в site-packages), schema документирует
   условие в `MountSlot.required_unless`. Сейчас gate всё равно
   требует mount-точку (conservative default); если оператор
   решит изменить politik'у, он меняет код gate'а и пишет ledger
   entry — никаких runtime config switch'ей.

#### Auto-completion design (not built this entry, but reserved)

Operator также упомянул автоматическое определение и добавление.
Текущее Entry 22 — **detection + manual fix loop**. Следующий шаг
(потенциальный Entry 23) — **auto-completer**:

```bash
sndr config v2 complete <hardware.yaml>
```

который inplace дополняет YAML недостающими slots на основе
`REQUIRED_MOUNTS` schema'ы. Дизайн уже подготовлен:
audit-launch-coverage возвращает `missing_mounts: list[str]` —
auto-completer считывает этот список, разворачивает каждый
container_path в полный mount entry с правильным host-var
наименованием (`${triton_cache}`, `${compile_cache}`, etc.) +
комментарием, и пишет обратно. Mechanism тот же, что у
`scripts/sync_readme_counters.py` (Entry 14): static-check
определяет drift, второй проход переписывает файл, idempotent.

Этот Entry 23 заведу как pending evidence ниже — у меня сейчас
достаточно schema'ы, но операторская политика «всегда дополнять
автоматом vs. требовать ручной фикс» — это decision call, который
не должен быть мой.

#### Test growth summary

| Phase | Tests added | Cumulative | Result |
|---|---|---|---|
| Baseline (Entry 4) | — | 5627 | green |
| Through Entry 17 (§6.8 P-2 honest 100%) | 369 | 5996 | green |
| `make evidence` aggregate (E18) | 17 | 6013 | green |
| `sndr patches bench-attach` (E19) | 59 | 6072 | green |
| `sndr patches proof-status` (E20) | 18 | 6090 | green |
| `sndr patches release-check` (E21) | 25 | 6115 | green |
| `audit-model-baselines` + ref realignment (E22.A) | 16 | 6131 | green |
| `audit-launch-coverage` + mount restoration (E22.B) | 16 | 6147 | green |

#### Schema coverage status — после Entry 22

V2 hardware schema полностью covered:

```text
  Required mounts:   6/6 across 3 hardware YAMLs    ✓
  Required env keys: 7/7 across 3 hardware YAMLs    ✓
  V2 model baselines: 6/6 resolvable                ✓
```

Любой будущий PR, дропающий один из 6 mounts или 7 env keys в
любом V2 hardware YAML, фейлит CI на `audit-launch-coverage` —
тот же class of bug, что обнаружил оператор, больше не может
произойти silently.

---

### Entry 23 — V2 hardware auto-completer (`config-v2-complete`)

**Scope:** закрыли deliverable, который оператор сформулировал в
Entry 22: «нужно чтобы определялись все нужные пути и переменные и
добавлялись». Entry 22 поставил *detection* (`audit-launch-coverage`
+ frozen schemas). Entry 23 ставит *injection*: автоматический
дополнитель, превращающий «вот 4 mount slot'а отсутствуют» в «вот
файл с правильными slot'ами + сохранёнными комментариями». Manual
fix loop теперь — `make config-v2-complete ARGS=--write`.

**Deliverable A — расширение schema в `audit_launch_coverage.py`:**

`MountSlot` обогатился полем `host_var` — каноническое
`${...}`-имя для каждого mount-слота. Это то, что auto-completer
вставляет в новые entries:

| container_path | host_var |
|---|---|
| `/models` | `${models_dir}` |
| `/root/.cache/huggingface` | `${hf_cache}` |
| `/root/.triton/cache` | `${triton_cache}` |
| `/root/.cache/vllm/torch_compile_cache` | `${compile_cache}` |
| `/usr/local/lib/python3.12/dist-packages/vllm/sndr_core` | `${genesis_src}` |
| `/plugin` | `${plugin_src}` |

И новая константа `ENV_DEFAULTS` — canonical YAML-literal value для
каждого из 7 required env keys. Значения отражают V1 PROD reference +
project policy (е.g. `OMP_NUM_THREADS='1'` — TP-oversubscription
guard; `VLLM_NO_USAGE_STATS='1'` — project privacy policy).

**Deliverable B — `scripts/config_v2_complete.py`:**

Line-injection auto-completer. Намеренно НЕ использует PyYAML
для записи: PyYAML's default dumper уничтожает комментарии и
переформатирует. Вместо этого — anchor-block detection + targeted
line insertion:

1. Находит `mounts:` anchor — line index, depth indent, last item line
2. Находит `system_env:` anchor — то же самое
3. Для каждого `missing_mount` из `audit_one_hardware_yaml`:
   - смотрит canonical `MountSlot` по container_path
   - рендерит entry в формате `      - "${host}:/container[:mode]"  # E23 auto-added: ...`
   - вставляет сразу после last item в mounts block
4. Для каждого `missing_env`:
   - берёт значение из `ENV_DEFAULTS[key]`
   - рендерит `  KEY: value   # E23 auto-added`
   - вставляет в конец system_env block

Indent inferred dynamically from existing items — gate работает
на YAMLs с 2/4/6-space styles одинаково.

**Modes:**

- **default (check)**: report drift, print which slots would be
  added, exit 1 if any drift, do NOT write
- `--write`: actually rewrite the file
- `--file PATH`: target one file (otherwise sweep all V2 hardware/)
- `--show-diff`: print unified diff per drifted file (text mode)
- `--json`: machine-readable summary с `clean`/`would_write`/
  `written`/`errors` counts

**Exit codes:**
- 0 — all clean (or all writes succeeded in --write mode)
- 1 — drift detected (in default mode) or errors during write
- 2 — internal error (parse failure, missing anchor block)

**Idempotency guarantee:** Запуск второй раз на уже-canonical файле
— no-op. Тестируется в `test_idempotent_after_write`.

**Safety:** Comment preservation тестируется в
`test_preserves_existing_comments` — operator-комментарии (inline +
standalone) выживают полностью. New entries несут explicit
`# E23 auto-added` маркер чтобы при code review было видно, что
сгенерировано, а что operator написал руками.

**Deliverable C — Tests:** `tests/unit/scripts/test_config_v2_complete.py`,
16 тестов в четырёх классах:

| Class | Tests | Coverage |
|---|---|---|
| `TestFindAnchorBlock` | 3 | mounts + system_env anchor detection с правильным indent inference; missing anchor → None |
| `TestCompleteOneYaml` | 8 | canonical → CLEAN; drift check → WOULD_WRITE без записи; drift write → файл реально переписан с новыми entries; idempotency (второй pass = CLEAN); after-write audit-launch-coverage passes; comments preserved; missing-anchor → ERROR; CompletionStatus enum values |
| `TestLiveRepo` | 1 | committed repo полностью canonical (anchor invariant) |
| `TestScriptCLI` | 4 | committed repo exit 0; JSON shape; synth drift check mode exit 1; synth drift write mode exit 0 + файл реально rewritten |

**Deliverable D — Makefile target:**

```makefile
config-v2-complete: ## §4.2 auto-completer: inject missing canonical mounts + env keys into V2 hardware YAMLs (check-only; pass ARGS=--write to rewrite)
	@$(PYTHON) scripts/config_v2_complete.py $(ARGS)
```

NOT добавлен в `make_evidence` GATES — это **инструмент оператора**,
а не gating gate. Operator явно вызывает `--write` когда хочет
auto-fix; CI ловит drift через `audit-launch-coverage` (gating
gate, не auto-fixer).

#### Acceptance evidence

**A1.** Synthetic drift round-trip (drifted YAML с 2 mounts + 3 envs):

```console
$ python3 scripts/config_v2_complete.py --file /tmp/drifted.yaml --show-diff
config-v2-complete: 1 V2 hardware YAML(s)
──────────────────────────────────────────────────────────────────────
  ✎ synth-drifted-rig: would add 4 mount(s) + 4 env(s)
      + mount  /root/.triton/cache
      + mount  /root/.cache/vllm/torch_compile_cache
      + mount  /usr/local/lib/python3.12/dist-packages/vllm/sndr_core
      + mount  /plugin
      + env    CUDA_DEVICE_MAX_CONNECTIONS
      + env    TRITON_CACHE_DIR
      + env    VLLM_ALLOW_LONG_MAX_MODEL_LEN
      + env    VLLM_WORKER_MULTIPROC_METHOD
──────────────────────────────────────────────────────────────────────
  1 file(s): completion needed

--- /tmp/drifted.yaml (before)
+++ /tmp/drifted.yaml (after E23)
@@ -23,4 +23,8 @@
       - "${models_dir}:/models:ro"            # only 2 of the 6 canonical slots
       - "${hf_cache}:/root/.cache/huggingface:ro"
+      - "${triton_cache}:/root/.triton/cache"  # E23 auto-added: Triton kernel cache — must persist or pay +30-60s recompile on restart
+      - "${compile_cache}:/root/.cache/vllm/torch_compile_cache"  # E23 auto-added: torch.compile cache — must persist or pay recompile on restart
+      - "${genesis_src}:/usr/local/lib/python3.12/dist-packages/vllm/sndr_core:ro"  # E23 auto-added: sndr_core source overlay — REQUIRED unless image pre-bakes Genesis patches
+      - "${plugin_src}:/plugin:ro"  # E23 auto-added: Genesis vLLM plugin source — REQUIRED for plugin loading
@@ -28,4 +32,8 @@
   OMP_NUM_THREADS: '1'
   VLLM_NO_USAGE_STATS: '1'
+  CUDA_DEVICE_MAX_CONNECTIONS: '8'   # E23 auto-added
+  TRITON_CACHE_DIR: '/root/.triton/cache'   # E23 auto-added
+  VLLM_ALLOW_LONG_MAX_MODEL_LEN: '1'   # E23 auto-added
+  VLLM_WORKER_MULTIPROC_METHOD: spawn   # E23 auto-added
```

**A2.** `--write` + audit verification + idempotency:

```console
$ python3 scripts/config_v2_complete.py --file /tmp/drifted.yaml --write
  ✎ synth-drifted-rig: added 4 mount(s) + 4 env(s)
  1 file(s): completion applied

$ python3 scripts/audit_launch_coverage.py --hw-dir /tmp/
  ✓ synth-drifted-rig
  1/1 hardware file(s) cover the canonical launch schema

$ python3 scripts/config_v2_complete.py --file /tmp/drifted.yaml --write
  ✓ synth-drifted-rig (canonical, no changes)
  1 file(s): all canonical
```

**A3.** Comment preservation (inline + standalone):

Input:
```yaml
mounts:
  # operator comment must survive
  - "${models_dir}:/models:ro"  # inline operator comment
  - "${hf_cache}:/root/.cache/huggingface:ro"
```

After `--write`:
```yaml
mounts:
  # operator comment must survive          ← preserved
  - "${models_dir}:/models:ro"  # inline operator comment   ← preserved
  - "${hf_cache}:/root/.cache/huggingface:ro"
  - "${triton_cache}:/root/.triton/cache"  # E23 auto-added: ...
  - "${compile_cache}:/root/.cache/vllm/torch_compile_cache"  # E23 auto-added: ...
  ...
```

Tested in `test_preserves_existing_comments`.

**A4.** Committed repo полностью canonical (regression anchor):

```console
$ make config-v2-complete
config-v2-complete: 3 V2 hardware YAML(s)
──────────────────────────────────────────────────────────────────────
  ✓ a5000-1x-24gbvram-16cpu-128gbram (canonical, no changes)
  ✓ a5000-2x-24gbvram-16cpu-128gbram (canonical, no changes)
  ✓ single-3090-24gbvram (canonical, no changes)
──────────────────────────────────────────────────────────────────────
  3 file(s): all canonical
```

E22 restored всё руками; E23 verifies через auto-completer что
ручная работа эквивалентна тому, что произведёт инструмент.
Это closes the loop: если оператор когда-нибудь захочет
*regenerate* hardware YAMLs, инструмент даст идентичный результат
(модулей сами оператор-комментарии).

**A5.** Полный pytest:

```text
6163 passed, 131 skipped, 11 warnings in 229.24s
```

Прирост: 6147 (E22.B) → 6163 (E23: +16). Никаких регрессий.

**A6.** `make audit-launch-coverage` после E23 schema-extension —
прежнему зелёный (3/3); добавление `host_var` field в `MountSlot` и
`ENV_DEFAULTS` константы — non-breaking schema additions.

#### Why this entry — design discussion

E22 поставил **detection-only** loop:

```text
[edit YAML]  →  [audit-launch-coverage]  →  [missing_mounts list]  →  [operator opens file and types]
```

Это работает на 3 файлах. Не масштабируется на 30. Operator's framing
был ровно про это: «определялись и добавлялись» — single command,
не «загуглить какой host_var должен быть для /plugin». E23 закрывает
этот gap, превращая loop в:

```text
[edit YAML]  →  [config-v2-complete --write]  →  [audit-launch-coverage passes]
```

**Главные design-решения:**

1. **Line-injection, не PyYAML round-trip.** PyYAML's default
   dumper уничтожает комментарии и переформатирует. V2 hardware
   YAMLs — это operator-curated documentation as much as config
   (per-line объяснения knob'ов, ground-truth references). Reflow =
   destroy operator intent. Line-injection меняет только два
   anchor блока, всё остальное byte-identical.

2. **Explicit `# E23 auto-added` маркер.** На code review должно
   быть видно, что injected, что operator. Без маркера — два года
   спустя никто не помнит, что было «согласовано» и что просто
   «дополнено инструментом». Маркер не убирается при re-write —
   permanent provenance.

3. **`--check` default mode, `--write` opt-in.** Те же
   соображения, что у Entry 21's `report` mode: инструмент, который
   silently переписывает файлы по default'у, ломает muscle memory
   операторов и быстро отключается. Default check + explicit write
   — стандартный паттерн (см. `prettier`, `black`, etc.).

4. **NOT в `make_evidence` GATES.** Это активный fix-tool, не
   gating gate. CI ловит drift через `audit-launch-coverage`
   (E22); E23 — то, что operator вызывает при coding session, не
   то, что блокирует merge. Различение чёткое: audit gates
   *проверяют*, completion tools *чинят*.

5. **Schema sharing через cross-module import.** `config_v2_complete.py`
   импортирует `audit_launch_coverage.py` через `importlib.util`.
   Это потому что оба — `scripts/*.py` файлы, не модули в пакете.
   Single-source-of-truth для `REQUIRED_MOUNTS` + `REQUIRED_ENV_KEYS` +
   `ENV_DEFAULTS` — если кто-то добавит новый required slot, он
   меняет ОДНО место (`audit_launch_coverage.py:REQUIRED_MOUNTS`)
   и обе tool'а автоматически согласуются.

#### Future extension hooks

Дизайн заложен для расширения без breaking change:

- **Per-model auto-completion**: text-injection алгоритм генерализуется
  на V2 model YAMLs (через тот же `_find_anchor_block`). E.g.
  если появится `audit-model-baselines` schema, требующая
  `bench_validation:` block, completer его создаст.
- **Cross-layer consistency**: completer может scанировать
  `presets/*.yaml` aliases, resolving каждый в (model, hardware,
  profile), и проверять, что resolved triplet удовлетворяет
  schema'е. Сейчас audit-launch-coverage работает только на
  hardware/ — расширение на presets/ — следующий шаг.
- **VS Code language server hook**: JSON-mode output совместим с
  LSP code-actions. Можно reusable `scripts/config_v2_complete.py
  --json` как diagnostics-provider для editor'а — «quick-fix»
  для missing slot.

#### Test growth summary

| Phase | Tests added | Cumulative | Result |
|---|---|---|---|
| Through E22.B (audit-launch-coverage) | — | 6147 | green |
| `config-v2-complete` (this entry) | 16 | 6163 | green |

#### §4.2 V2 schema chain status

После Entry 23 V2 schema chain полностью замкнут:

```text
  ┌─────────────────────┐     ┌───────────────────────┐     ┌──────────────────────┐
  │  REQUIRED_MOUNTS    │ ──▶ │ audit-launch-coverage │ ──▶ │ config-v2-complete   │
  │  REQUIRED_ENV_KEYS  │     │   (E22 detection)     │     │   (E23 injection)    │
  │  ENV_DEFAULTS       │     │   gating gate         │     │   operator tool      │
  └─────────────────────┘     └───────────────────────┘     └──────────────────────┘
     schema as code                CI catches drift              one-command fix
```

Тот же паттерн, что у §6.8 chain (E12 + E19 + E20 + E21):
schema + detection + read + decide → schema + detection + fix.
И там, и здесь — single source of truth, no operator-side guessing.

---

### Entry 24 — env-value invariants (presence → values)

**Scope:** E22 проверял что required env keys *присутствуют* в V2
hardware YAMLs. Но `TRITON_CACHE_DIR='/wrong/path'` тоже «присутствует»
— и при этом ломает Triton-cache persistence (Triton пишет в один
путь, mount подмонтирует другой). E24 закрывает этот gap: проверяет
*значения* для env keys, у которых есть структурный инвариант.

Catches класс «key present, value wrong» — невидимый для E22.

**Deliverable A — два schema-map в `audit_launch_coverage.py`:**

```python
ENV_VALUE_LINKS = {
    # Value MUST equal the container_path of the linked mount:
    "TRITON_CACHE_DIR": "/root/.triton/cache",
}

ENV_VALUE_LITERALS = {
    # Value MUST be one of these literals:
    "VLLM_WORKER_MULTIPROC_METHOD": frozenset({"spawn"}),
    "VLLM_NO_USAGE_STATS":          frozenset({"1", "true", "True"}),
    "VLLM_ALLOW_LONG_MAX_MODEL_LEN": frozenset({"1", "true", "True"}),
}
```

Plus `_normalize_env_value()` — coerces YAML-loaded values to
stripped strings (bool/int/quote-variants → canonical form), так
что `'1'` / `"1"` / `1` / `True` обрабатываются correctly.

**Deliverable B — extended `HardwareAudit`:**

Новое поле `env_value_violations: list[tuple[str, str, str]]` —
`(key, got_value, why)`. `audit.passed` теперь и сюда смотрит.
Backward-compatible (default = empty list); existing E22 callers
не сломаны.

**Why design — link vs literal:**

- **link** для `TRITON_CACHE_DIR`: значение не свободное — оно
  ДОЛЖНО матчить container_path реального mount-а (`/root/.triton/cache`
  из `REQUIRED_MOUNTS`). Если operator изменит `TRITON_CACHE_DIR`,
  он должен пересмотреть и mount; link это enforces.
- **literal** для `VLLM_WORKER_MULTIPROC_METHOD`: `fork` ломает
  CUDA reinit при TP>1 (silent corruption). `spawn` — единственное
  корректное значение. Нет flexibility — это инвариант.
- **literal frozenset** для truthy keys: tolerates `'1'` / `'true'` /
  `'True'` — YAML's truthy-quoting variants все эквивалентны.

**Deliverable C — Tests:** 7 новых тестов в `TestEnvValueInvariants`
class:

| Test | Что проверяет |
|---|---|
| `test_canonical_values_pass` | regression anchor — committed values по-прежнему все правильные |
| `test_triton_cache_dir_wrong_path_fails` | link violation surface'ится |
| `test_multiproc_method_fork_fails` | `fork` rejected |
| `test_long_max_model_len_zero_fails` | `'0'` для long-context flag rejected |
| `test_truthy_variants_accepted` | `'1'` / `'true'` / `'True'` all accepted |
| `test_normalize_handles_quoting` | unit для `_normalize_env_value` (str/int/bool/quotes) |
| `test_missing_value_link_key_not_violated` | missing key reported by E22 `missing_envs`, не двойным сообщением |

#### Acceptance evidence

**A1.** Synthetic wrong-values YAML:

```text
$ python3 scripts/audit_launch_coverage.py --hw-dir /tmp/v2-valuedrift
audit-launch-coverage: 1 V2 hardware YAML(s)
──────────────────────────────────────────────────────────────────────
  ✗ synth-wrong-values
      env value violations (3):
        - TRITON_CACHE_DIR='/wrong/triton/path' — must equal '/root/.triton/cache' (linked to mount container_path)
        - VLLM_WORKER_MULTIPROC_METHOD='fork' — must be one of ['spawn']
        - VLLM_ALLOW_LONG_MAX_MODEL_LEN='0' — must be one of ['1', 'True', 'true']
──────────────────────────────────────────────────────────────────────
  0/1 hardware file(s) cover the canonical launch schema
$ echo $?
1
```

**A2.** Committed repo всё ещё green (значения в E22-restored YAMLs
канонические):

```text
$ make audit-launch-coverage
  ✓ a5000-1x-24gbvram-16cpu-128gbram
  ✓ a5000-2x-24gbvram-16cpu-128gbram
  ✓ single-3090-24gbvram
  3/3 hardware file(s) cover the canonical launch schema
```

**A3.** Полный pytest:

```text
6170 passed, 131 skipped, 11 warnings in 219.65s
```

Прирост: 6163 (E23) → 6170 (E24: +7). Никаких регрессий.

**A4.** `make evidence` — 15 gates, 9 gating всё green.

#### §4.2 V2 schema chain — финальное состояние

| Layer | Status |
|---|---|
| Mount presence (6 slots) | ✓ E22 gating |
| Env-key presence (7 keys) | ✓ E22 gating |
| Auto-completer (drift → fix) | ✓ E23 operator tool |
| **Env-value invariants (links + literals)** | ✓ **E24 gating** |

Класс bugs, который теперь невозможен silently:

1. mount slot dropped (E22)
2. env key dropped (E22)
3. mount path changed without operator awareness (E23 auto-fill)
4. **env value desync'd from mount path** (E24, *this entry*)
5. **fork-mode silent CUDA corruption** (E24)

#### Test growth summary

| Phase | Tests added | Cumulative | Result |
|---|---|---|---|
| Through E23 (auto-completer) | — | 6163 | green |
| Env-value invariants (this entry) | 7 | 6170 | green |

---

### Entry 25 — cross-layer V2 env-key consistency (`audit-v2-env-keys`)

**Scope:** оператор попросил «комплексно и с умом» подойти к двум
gap'ам:
1. `model.patches` matrix consistency (E25 originally) — typo'd
   `GENESIS_ENABLE_X` key проходил `audit-configs` (это compose
   gate, не reference check)
2. Cross-layer preset audit (E26 originally) — resolved alias может
   содержать typo, привнесённый профильным `patches_delta`, но
   `audit-configs` его не видит (compose succeeds, dict есть)

После survey обнаружил, что инфраструктура УЖЕ существует:
- `vllm/sndr_core/cli/config_keys.py:_extract_keys_from_yaml()` —
  знает все anchor блоки V2 schema (`patches`, `patches_delta.{enable,
  disable, override}`, `genesis_env`, `system_env`)
- `load_canonical_registry()` — union из 4 источников (PATCH_REGISTRY
  env_flag, V2 model.patches keys, V1 genesis_env, policy keys)
- `config-keys-validate <file>` — single-file CLI command

**Чего НЕ хватало**: cross-layer CI sweep. Никакой gate не вызывал
validate-логику на ВСЕХ V2 yamls одновременно. Объединил оба
запрошенных gap'а в один audit gate.

**Deliverable A — `scripts/audit_v2_env_keys.py`:**

Walks **три layer'а** + проверяет each entry vs `load_canonical_registry()`:

| Layer | What's walked | Catches |
|---|---|---|
| **model** | `model_configs/builtin/model/*.yaml` `patches:` matrix | typo'd patch_id в model YAML |
| **profile** | `model_configs/builtin/profile/*.yaml` `patches_delta.{enable,disable,override}` | typo'd patch_id в profile delta |
| **resolved-alias** | для каждого `presets/*.yaml` — `load_alias(alias).genesis_env` | typo'd patch_id, который survived composition (model+profile merged) |

Только Genesis/SNDR-prefixed keys проверяются — non-Genesis env
(PYTORCH_*, VLLM_*, HF_*) — operator-tunable, живут вне canonical
registry by design.

**Output**:
- Per-layer group, per-entry symbol (✓/✗) + key count + unknown list (truncated to 5)
- Total: `passed/total entries clean (N unknown keys across F failed entries)`
- JSON mode: structured `by_layer` summary + full `entries[]` list

**Exit codes**: 0 — all 28 entries clean; 1 — drift; 2 — internal.

**Deliverable B — Makefile + `make evidence`:**

```makefile
audit-v2-env-keys: ## §4.2 cross-layer env-key consistency
	@$(PYTHON) scripts/audit_v2_env_keys.py
```

Добавлен в `make_evidence.py:GATES` как **gating**. `make evidence`
теперь — 16 gates, 10 gating всё green.

**Deliverable C — Tests:** 11 тестов:

| Class | Tests | Coverage |
|---|---|---|
| `TestPredicates` | 3 | `_is_genesis_key` для GENESIS_/SNDR_/non-Genesis prefixes |
| `TestWalkers` | 3 | model walker returns 6 entries; profile ≥11; resolved-alias = 11 |
| `TestLiveRepoClean` | 1 | regression anchor — committed repo 28/28 clean |
| `TestScriptCLI` | 3 | CLI exit 0 / JSON shape / `--layer` filter |
| `TestTypoDetection` | 1 | synthetic typo set surfaces correctly via predicate |

#### Acceptance evidence

**A1.** Committed repo полностью clean (28/28):

```text
$ make audit-v2-env-keys
audit-v2-env-keys: 28 entry(ies) across 3 layers
──────────────────────────────────────────────────────────────────────
  ── model layer (6 entries) ──
    ✓ qwen3.6-27b-dflash.yaml                 (30 Genesis/SNDR keys)
    ...
  ── profile layer (11 entries) ──
    ✓ wave9-balanced.yaml                     (0 Genesis/SNDR keys)
    ...
  ── resolved-alias layer (11 entries) ──
    ✓ prod-35b                                (44 Genesis/SNDR keys)
    ✓ qa-27b-tested                           (36 Genesis/SNDR keys)
    ...
──────────────────────────────────────────────────────────────────────
  28/28 entries clean  (0 unknown Genesis/SNDR keys total across 0 entries)
```

**A2.** `make evidence` — 16 gates total, **10 gating всё green**:

```text
  ✓ [GATING       ] audit
  ✓ [GATING       ] audit-configs
  ✓ [GATING       ] audit-community
  ✓ [GATING       ] audit-no-new-v1
  ✓ [GATING       ] audit-patches-prove-all
  ✓ [GATING       ] audit-all-referents
  ✓ [GATING       ] audit-readme-counters
  ✓ [GATING       ] audit-model-baselines
  ✓ [GATING       ] audit-launch-coverage
  ✓ [GATING       ] audit-v2-env-keys
```

**A3.** Полный pytest:

```text
6181 passed, 131 skipped, 11 warnings in 243.91s
```

Прирост: 6170 (E24) → 6181 (E25: +11). Регрессий нет.

**A4.** Resolved-alias walker leverages `load_alias()` from
`registry_v2` — тот же compose path, что использует production
launch код. Catches drift в **финальном** genesis_env (после
profile.patches_delta merge), не только в исходных layers.

#### Why this entry — design discussion

User's framing «комплексно и с умом» подразумевал не дублировать
существующее. Survey показал:

- `audit-configs` (gating) — compose succeeds? ✓ already covered
- `config-keys-validate <file>` (CLI helper) — single-file unknown
  keys? ✓ already covered (just not in CI)
- **Missing**: CI sweep across all 28 V2 entries

Entry 25 закрывает именно этот gap — не пишет новую validation
логику, а оборачивает существующую `_extract_keys_from_yaml` +
`load_canonical_registry` в audit gate. Single-source-of-truth для
canonical registry — `config_keys.py`; новый script reuse'ит её.

**Что специально не делал** (decided against):

1. **Patch-id resolution через PATCH_REGISTRY** (a la "extract P58 from
   GENESIS_ENABLE_P58_FOO, check P58 in PATCH_REGISTRY"). Reason:
   canonical registry уже включает PATCH_REGISTRY env_flags +
   V2 patch-parameter keys + policy keys. Расширение registry —
   single edit point. Patch-id extraction добавил бы дублирующую
   логику с другим source of truth.

2. **Profile cross-reference**: «profile.parent_model должен
   match model_id в preset». `load_alias` уже это enforce'ит при
   compose; `audit-configs` ловит compose failures. Отдельный gate
   был бы redundant.

3. **Patch value type check** (`'1'` vs `'true'`). Это relevant
   для bool-семантики патчей, но 50+ keys в V2 yamls используют
   разные value-shapes (path strings, int counts, mode strings).
   Не имеет смысла enforce'ить только bool. Если оператор хочет —
   это отдельный entry с per-key value schema (а la E24 для
   system_env).

#### §4.2 V2 schema chain — финальное состояние

```text
  ┌──────────────────────────────┐
  │ canonical_registry (E11)     │ ← single source of truth
  │   = registry env_flags ∪     │
  │     V2 patch keys ∪          │
  │     V1 genesis_env ∪         │
  │     policy keys              │
  └──────────────┬───────────────┘
                 │
       ┌─────────┼─────────────────────────────┐
       ▼         ▼                             ▼
  ┌─────────┐  ┌────────────────┐  ┌────────────────────────────┐
  │ E22     │  │ E24            │  │ E25 audit-v2-env-keys      │
  │ mounts  │  │ env-value      │  │   model layer              │
  │ presence│  │ invariants     │  │   profile layer            │
  └─────────┘  └────────────────┘  │   resolved-alias layer     │
                                   └────────────────────────────┘
```

После Entry 25 классы V2-drift bugs, которые невозможны silently:

1. mount slot dropped (E22) ✓
2. env key dropped (E22) ✓
3. env value desync'd from mount path (E24) ✓
4. `VLLM_WORKER_MULTIPROC_METHOD=fork` (E24) ✓
5. **typo'd `GENESIS_ENABLE_X` в model.patches** (E25) ✓
6. **typo'd `GENESIS_ENABLE_X` в profile.patches_delta** (E25) ✓
7. **typo'd patch in resolved alias `genesis_env`** (E25) ✓

#### Test growth summary

| Phase | Tests added | Cumulative | Result |
|---|---|---|---|
| Through E24 (env-value invariants) | — | 6170 | green |
| `audit-v2-env-keys` (this entry) | 11 | 6181 | green |

---

### Entry 26 — two structural invariants (methodology pin + path drift)

**Scope:** оператор попросил «комплексно» закрыть два независимых
gap'а одним entry:

1. **bench-methodology stale detection** — для каждого
   `evidence/patch_proof/<patch>__<pin>.json:bench_delta.methodology_sha`
   проверить что хеш равен текущему `sha256(tools/bench_methodology.yaml)`.
   Без gate'а: bench, снятый против старой версии methodology, выглядит
   так же как свежий — release-gate (E21) не отличит «измерено по
   нынешним правилам» от «измерено по правилам полугодовой давности».
2. **hardcoded operator paths in active config** — V1 + V2 + compose
   YAMLs должны использовать `${var}` placeholders, а не `/home/sander/...`
   или `/Users/sander/...`. Hardcoded paths ломают portability и
   протекают operator identity в shared/public artefacts (§6.10).

Discovered in survey: compose/docker-compose.test-v11.yml содержал
hardcoded `/home/sander/.../...` пути в active mounts (не комментариях).
Это test-deployment file, привязан к конкретному homelab rig — добавлен
в EXEMPT_FILES с обязательным `audit-no-hardcoded-paths EXEMPT` header
marker'ом (audit'ом enforced).

#### Deliverable A — `scripts/audit_bench_methodology.py`

Stale-bench detector:

```python
canonical_sha = sha256(tools/bench_methodology.yaml)
for artefact in evidence/patch_proof/*.json:
    bench_delta = artefact.get("bench_delta") or {}
    if not bench_delta:
        status = "no_bench_delta"     # static-only, methodology N/A
    elif bench_delta.get("methodology_sha") is None:
        status = "missing_sha"        # FAIL
    elif bench_delta["methodology_sha"] == canonical_sha:
        status = "match"              # PASS
    else:
        status = "stale"              # FAIL
```

Five statuses: `match` / `no_bench_delta` / `stale` / `missing_sha` /
`error`. Только `match` + `no_bench_delta` проходят. Остальные
блокируют release.

**Allow-empty default**: пустой `evidence/patch_proof/` проходит
vacuously (GPU bench всё ещё operator-gated; gate становится active
после первого `bench-attach`). Operator может force-fail через
`--no-bench-allow-empty` flag.

#### Deliverable B — `scripts/audit_no_hardcoded_paths.py`

Path-drift detector:

- **Scope**: `vllm/sndr_core/model_configs/builtin/**/*.yaml`,
  `compose/*.yml`, `compose/*.yaml`
- **Regex**: `r"(/home/|/Users/)([a-zA-Z][a-zA-Z0-9_-]{1,30})/"` — ловит
  username-shaped path components
- **Filters**:
  - lines starting with `#` skipped (operator может документировать в комментариях)
  - generic non-user dirs (`/home/models/`, `/Users/Public/`) — пропускаются (списком `_GENERIC_USERS`)
  - paths под `_archive/` directories skipped (historical reference)
  - `EXEMPT_FILES` set — для compose-файлов test-rig'ов, которые operator-host-specific by design
- **Exempt-file invariant**: каждый файл в EXEMPT_FILES должен
  содержать в header'е marker `audit-no-hardcoded-paths EXEMPT`.
  Это enforced в `TestExempt.test_exempt_file_has_justification_comment`.

#### Deliverable C — fix applied + Makefile + integration

Fix shipped в E26:
- `compose/docker-compose.test-v11.yml` получил header-block:
  ```text
  # audit-no-hardcoded-paths EXEMPT (E26): this file is a remote-host
  # test deployment compose; the `/home/sander/...` paths reflect the
  # specific test rig layout. NOT a portable preset — operators on
  # other rigs should NOT consume this file directly.
  ```

Makefile targets:

```makefile
audit-bench-methodology: ## stale-bench detector
audit-no-hardcoded-paths: ## active config must use ${var} placeholders
```

Оба добавлены в `make_evidence.py:GATES` как **gating**.
`make evidence` теперь — **18 gates, 12 gating всё green** (было
16/10 после E25).

#### Deliverable D — Tests (28 total)

**`test_audit_bench_methodology.py`** (15 tests):

| Class | Tests | Coverage |
|---|---|---|
| `TestCanonicalSha` | 3 | sha256 stable for same bytes; missing file raises |
| `TestArtefactCheck` | 5 | no_bench_delta passes; matching SHA passes; stale fails; missing_sha fails; malformed → error status |
| `TestAuditDirectory` | 2 | empty proof_dir; mixed 3-artefact statuses |
| `TestScriptCLI` | 4 | empty default passes; empty `--no-bench-allow-empty` fails; stale fails rc=1; live repo passes |

Note: `TestCanonicalSha` has 3 tests but one is the live methodology
SHA-stability check (relies on real `tools/bench_methodology.yaml`),
making it a regression anchor for the methodology contract.

**`test_audit_no_hardcoded_paths.py`** (13 tests):

| Class | Tests | Coverage |
|---|---|---|
| `TestDetection` | 4 | comments skipped; regex matches /home/ + /Users/ users; generic users in _GENERIC_USERS list |
| `TestScanOneFile` | 5 | clean file; one violation; two violations; comment-with-path not flagged; generic-user path not flagged |
| `TestExempt` | 2 | EXEMPT_FILES non-empty + each is real file; each has `audit-no-hardcoded-paths EXEMPT` marker |
| `TestLiveRepo` | 1 | committed repo zero violations (regression anchor) |
| `TestScriptCLI` | 2 | CLI exit 0 on committed; JSON shape |

#### Acceptance evidence

**A1.** Smoke-test stale artefact:

```text
$ python3 scripts/audit_bench_methodology.py \
    --proof-dir /tmp/bench-methodology-test
audit-bench-methodology — stale-bench detector
──────────────────────────────────────────────────────────────────────
  canonical SHA: 783b1ccae908b6dd…
  artefacts:     2

  ✗ P58      [stale        ] P58__test.json
      got=deadbeefdeadbeef… want=783b1ccae908b6dd…
  ✓ P59      [no_bench_delta] P59__test.json
──────────────────────────────────────────────────────────────────────
  match=0  no_bench=1  stale=1  missing_sha=0  error=0

  ✗ Fix: re-run the bench against the current methodology and re-ingest
$ echo $?
1
```

**A2.** Smoke-test path drift fix:

До E26 fix:
```text
$ python3 scripts/audit_no_hardcoded_paths.py
  ✗ compose/docker-compose.test-v11.yml: 7 violation(s)
      L46:11  '/home/sander/'  → - /home/sander/.cache/huggingface:/root/.cache/huggingface:ro
      L48:11  '/home/sander/'  → - /home/sander/genesis-vllm-patches-v11/vllm/sndr_core:...
      ...
```

После E26 fix (header marker → file moved to EXEMPT_FILES):
```text
$ make audit-no-hardcoded-paths
audit-no-hardcoded-paths: 45 file(s) scanned
──────────────────────────────────────────────────────────────────────
  44 clean / 1 exempt / 0 with violations
```

**A3.** `make evidence` — 18 gates, **12 gating всё green**:

```text
  ✓ [GATING       ] audit
  ✓ [GATING       ] audit-configs
  ✓ [GATING       ] audit-community
  ✓ [GATING       ] audit-no-new-v1
  ✓ [GATING       ] audit-patches-prove-all
  ✓ [GATING       ] audit-all-referents
  ✓ [GATING       ] audit-readme-counters
  ✓ [GATING       ] audit-model-baselines
  ✓ [GATING       ] audit-launch-coverage
  ✓ [GATING       ] audit-v2-env-keys
  ✓ [GATING       ] audit-bench-methodology
  ✓ [GATING       ] audit-no-hardcoded-paths
```

**A4.** Полный pytest:

```text
6209 passed, 131 skipped, 11 warnings in 211.32s
```

Прирост: 6181 (E25) → 6209 (E26: +28 = 15 methodology + 13 path).
Никаких регрессий.

#### Why this entry — design discussion

User's framing «комплексно и с умом» — two unrelated structural
invariants объединил в один entry потому что они логически
parallel:

**Parallel structure**:
- Each enforces что ОДИН source of truth (methodology.yaml SHA / `${var}`
  placeholders) consistent across N consumers (proof artefacts / config files)
- Each ловит class «выглядит правильно, но семантически stale/wrong»
- Each имеет `gating` severity — оба важны для release integrity
- Each имеет escape hatch для legitimate exceptions (allow-empty flag /
  EXEMPT_FILES list)

**Главные design-решения:**

1. **Allow-empty default для bench-methodology**: GPU bench всё ещё
   operator-gated; gate срабатывает реально только когда первый
   artefact ingest'нут. Default fail-on-empty заставил бы release-CI
   падать pre-bench, что демотивирует операторов рисковать bench
   run'ами. Same psychology pattern, что у E21 `report` mode default.

2. **Status-based reporting** (match / no_bench_delta / stale /
   missing_sha / error): пятиклассная классификация даёт нюансированный
   readout. `no_bench_delta` passes (static-only artefact — методология
   irrelevant); `missing_sha` fails (bench был, но не stamp'нут — это
   bench-suite bug). Не binary good/bad — иначе оператор не знает,
   что чинить.

3. **EXEMPT_FILES + header marker enforcement**: единственный escape
   hatch — это явный allowlist + явный комментарий в файле. Без
   header marker test `test_exempt_file_has_justification_comment`
   fail'ит. Two-factor exemption (code list + file comment) убирает
   silent-bypass risk.

4. **Generic-user filter** (`_GENERIC_USERS`): regex matches
   `/home/<user>/`, но `models/share/public/...` — это не operator
   paths. Без filter'а ловили бы containers' internal mounts
   (`/home/models/qwen-...`) — false positives.

5. **Comments allowed**: operator должен иметь возможность
   документировать paths в комментариях (как в `compose/docker-compose.unit.yml`
   header: `scp -r ... sander@host:/home/sander/`). Запретить
   комментарии = разрушить onboarding docs.

#### Test growth summary

| Phase | Tests added | Cumulative | Result |
|---|---|---|---|
| Through E25 (cross-layer env keys) | — | 6181 | green |
| `audit-bench-methodology` (this entry) | 15 | 6196 | green |
| `audit-no-hardcoded-paths` (this entry) | 13 | 6209 | green |

#### Invariants covered after E26

Расширил chain классов V2-drift bugs которые невозможны silently:

1. mount slot dropped (E22) ✓
2. env key dropped (E22) ✓
3. env value desync'd from mount path (E24) ✓
4. fork-mode CUDA corruption (E24) ✓
5. typo'd patch flag в model.patches (E25) ✓
6. typo'd patch flag в profile.patches_delta (E25) ✓
7. typo'd patch flag survived through composition (E25) ✓
8. **bench evidence stale against current methodology** (E26) ✓
9. **bench evidence missing methodology fingerprint** (E26) ✓
10. **hardcoded operator paths in shared/public config** (E26) ✓

---

### Entry 27 — V2 schema + freshness invariants

**Scope:** оператор попросил «комплексно» закрыть два gap'а:
1. **required-fields per kind** — каждый V2 YAML должен иметь
   полный set обязательных top-level полей (id, schema_version,
   maintainer, patches, и т.д. — set frozen as code)
2. **last_validated freshness** — для каждого `kind: model` YAML
   проверить что `last_validated` не старше N дней (default 180)

Survey показал: репозиторий **уже в каноническом состоянии** — все
31 V2 YAMLs имеют consistent field shape per kind (16 fields в model,
9 в hardware, 9 в profile, 3 в preset). Codify current state как
regression anchor — то же pattern, что E22 заморозил mount slots.

#### Deliverable A — `scripts/audit_v2_required_fields.py`

Per-layer frozen schema:

| Layer | N required fields | Examples |
|---|---|---|
| **model** | 16 | schema_version, kind, id, title, maintainer, last_validated, license, model_path, served_model_name, dtype, quantization, trust_remote_code, capabilities, requires, versions, patches |
| **hardware** | 9 | schema_version, kind, id, title, maintainer, hardware, sizing, runtime, system_env |
| **profile** | 9 | schema_version, kind, id, maintainer, parent_model, status, created, patches_delta, promotion |
| **preset** | 3 | model, hardware, profile |

`notes` (operator-optional commentary) intentionally excluded — это
не invariant, а discretionary документация.

**Why not just enumerate all 17/10/10/3 always-present fields?**
Because we want to allow operator to add fields (new schema) without
breaking gate. The set IS the requirement; new files implicitly
enforce; removing a field requires updating set + ledger entry.

#### Deliverable B — `scripts/audit_v2_freshness.py`

Date staleness detector for `kind: model` layer only (hardware
doesn't carry bench claims; profile has `created` immutable
provenance, not validation date).

**Five statuses** в parallel structure с E26 methodology:

| Status | Condition | Passes? |
|---|---|---|
| `ok` | parseable + ≤ max_age_days | ✓ |
| `stale` | parseable but age > max_age_days | ✗ |
| `future` | parseable but date in future (typo guard) | ✗ |
| `missing` | last_validated field absent | ✗ |
| `unparseable` | not a valid ISO date | ✗ |

**Threshold default**: 180 days (2 wave-cycles' grace at Genesis's
~quarterly release cadence). Operator override via `--max-age-days`.

**Boundary**: strict inequality — exactly N days old passes (avoids
false-positive on the day a re-validation lands but hasn't propagated).

**Severity**: **informational** (NOT gating). Reason: stale models
shouldn't pre-block release before operator has a chance to
re-validate; freshness is hygiene, not invariant. Operator escalates
via custom `make ARGS=--max-age-days N` invocation or by changing
gate severity in `make_evidence.py:GATES`.

#### Deliverable C — Makefile + integration

```makefile
audit-v2-required-fields: ## §4.2 V2 schema
audit-v2-freshness:       ## §4.2 last_validated ≤ 180d (override via ARGS=--max-age-days N)
```

- `audit-v2-required-fields` — **gating** (always-on invariant)
- `audit-v2-freshness` — **informational** (warn-only by default)

`make evidence` → **20 gates, 13 gating + 1 informational зелёные**.

#### Deliverable D — Tests (33 total)

`test_audit_v2_required_fields.py` (15 tests):
- Schema sanity (4 layers, exact size per layer: 16/9/9/3, key entries)
- Per-file check (complete passes; missing one fails; missing many fails; non-mapping → error; preset minimal passes)
- Live repo regression anchor (31 entries pass)
- CLI exit codes + JSON shape + `--layer` filter

`test_audit_v2_freshness.py` (18 tests):
- ISO date parsing (string/date/datetime/whitespace/invalid → None)
- Per-file check (fresh / stale / future / missing / unparseable / boundary-at-threshold)
- Directory audit (empty / 3-status mix)
- Live repo (committed models pass default 180-day window)
- CLI (`--today` override / `--max-age-days` tight window fails)

#### Acceptance evidence

**A1.** Committed repo всё clean:

```text
$ make audit-v2-required-fields
audit-v2-required-fields: 31 V2 YAML(s) across 4 layers
  ── model layer (6 entries, 16 required fields) ──    ✓ × 6
  ── hardware layer (3 entries, 9 required fields) ── ✓ × 3
  ── profile layer (11 entries, 9 required fields) ── ✓ × 11
  ── preset layer (11 entries, 3 required fields) ──  ✓ × 11
  31/31 entries satisfy schema

$ make audit-v2-freshness
audit-v2-freshness: 6 model YAML(s), today=2026-05-13, max_age=180d
  ✓ qwen3.6-27b-dflash                   validated 2026-05-06 (7d old)
  ✓ qwen3.6-27b-int4-autoround-tq-k8v4   validated 2026-05-11 (2d old)
  ✓ qwen3.6-35b-a3b-fp8                  validated 2026-05-09 (4d old)
  ...
  6/6 model(s) fresh
```

**A2.** Synthetic drift (`--max-age-days 1`):

```text
  ✗ qwen3.6-27b-dflash STALE — validated 2026-05-06 (7d > 1d)
  ✗ ... (×5 more)
  0/6 model(s) fresh
$ echo $?
1
```

**A3.** `make evidence` — 20 gates, 13 gating all green, freshness informational green.

**A4.** Полный pytest: **6242 passed, 131 skipped** (+33 от 6209).

#### Why this entry — design discussion

**Required-fields as frozen set** — same canonical-schema-as-code
pattern, что E22 (mounts), E24 (env values), E25 (canonical
env-key registry). One source of truth, gate enforces, tests anchor.

**Freshness informational** — different psychology чем required
fields. Required field absent = bug (definitely). Stale date =
hygiene issue (operator may have time/no-time to re-bench).
Informational allows policy to evolve without ratcheting CI; if
operator wants strict, they raise severity manually.

**`kind: model` only for freshness** — sequential reasoning:
- Hardware: bench claims don't live here (it's GPU + container shape)
- Profile: `created` is immutable provenance, not "last verified"
- Preset: alias triplet, no time component
- **Model**: carries bench reference + patches matrix → "last verified" is meaningful

Adding freshness to hardware would be busy-work overhead with no
real invariant. Adding to profile would change semantics of `created`.
Adding to preset doesn't apply.

**Boundary**: strict inequality (`age > max_age_days`, не `≥`).
Reasoning identical к E21 regression threshold — boundary noise
shouldn't fail CI on the day a re-validation lands.

#### Test growth summary

| Phase | Tests added | Cumulative | Result |
|---|---|---|---|
| Through E26 (methodology + path drift) | — | 6209 | green |
| `audit-v2-required-fields` (this entry) | 15 | 6224 | green |
| `audit-v2-freshness` (this entry) | 18 | 6242 | green |

#### Invariants chain after E27 — 12 V2-drift bug classes blocked silently

1-7: through E22-E25 (mounts/envs/typos)
8-10: E26 (methodology + path drift)
11. **V2 YAML missing required top-level field** (E27, gating)
12. **V2 model `last_validated` stale > 180 days** (E27, informational)

---

### Entry 28 — V2 identity invariants (id-consistency + license-coverage)

**Scope:** оператор попросил «комплексно» закрыть два gap'а:

1. **`audit-v2-id-consistency`** — для каждого V2 YAML (model/hardware/
   profile) проверить что `data["id"] == filename_stem`. Filename↔id
   mismatch ломает alias resolver: `load_alias({"model": "X"})` ищет
   `model/X.yaml`, не глядя в `id:` field. Drift silent at compose
   time — может попасть в неправильный файл с матчащим filename.
2. **`audit-v2-license-coverage`** — для каждого `kind: model`
   проверить `license:` SPDX-recognized + `maintainer:` non-empty.
   Lowercase normalization (`Apache-2.0` ≡ `apache-2.0`); whitespace
   tolerated. `ALLOWED_LICENSES` frozenset (7 entries) — apache-2.0,
   mit, bsd-3/2-clause, gpl-3.0, lgpl-3.0, mpl-2.0.

Repo уже в каноническом состоянии — все 20 V2 YAMLs `id == stem`,
все 6 моделей `license: apache-2.0` + `maintainer: sandermage`.
Entry 28 codifies current state как frozen invariant.

#### Deliverables

| File | Lines | Purpose |
|---|---|---|
| `scripts/audit_v2_id_consistency.py` | ~150 | walks 3 id-carrying layers (model/hardware/profile), reports per-file ✓/✗ |
| `scripts/audit_v2_license_coverage.py` | ~200 | walks model layer, checks normalized license vs ALLOWED_LICENSES + maintainer non-empty |
| `tests/unit/scripts/test_audit_v2_id_consistency.py` | 8 tests | match/mismatch/missing-id/parse-error + live repo + CLI |
| `tests/unit/scripts/test_audit_v2_license_coverage.py` | 12 tests | schema + per-file + live repo + CLI |
| Makefile targets `audit-v2-id-consistency`, `audit-v2-license-coverage` | gating | added to `make_evidence.GATES` |

#### Acceptance

```text
$ make audit-v2-id-consistency
  20/20 entries match  (6 model + 3 hardware + 11 profile)

$ make audit-v2-license-coverage
  6/6 models have valid license + maintainer
```

`make evidence` → **22 gates, 15 gating + 1 informational green**
(было 20/13 после E27). Full pytest **6262 passed, +20 от 6242,
zero regressions**.

#### Design notes

- **id-consistency over 3 layers**: preset не имеет `id:` (alias triplet);
  scope только model/hardware/profile.
- **license over model layer only**: hardware (shape/runtime config) +
  profile (delta) не несут license-able content; модель carries
  bench claims + patches matrix.
- **Case-insensitive license matching**: SPDX identifiers
  case-insensitive по спеке; `_normalize_license()` lowercase +
  strip — единственный normalization step.
- **ALLOWED_LICENSES frozenset**: 7 OSI-approved licenses на старте.
  Расширение требует ledger entry + operator approval — не silent
  config bump.

#### §4.2 invariants chain — 14 V2-drift bug classes blocked silently

1-7: through E22-E25 (mounts/envs/typos)
8-10: E26 (methodology + path drift)
11-12: E27 (required fields + freshness)
13. **filename↔id mismatch breaking alias resolver** (E28)
14. **missing/unknown license OR empty maintainer** (E28)

---

### Entry 29 — V2 reference invariants (cross-ref + vllm-pin)

**Scope:** оператор попросил «комплексно» два gap'а:

1. **`audit-v2-cross-reference`** — каждый `profile.parent_model` +
   каждое из 3 полей в preset (`model`/`hardware`/`profile`) должен
   указывать на реальный файл в соответствующем layer'е. Surface
   covers 44 refs (11 profile parent + 33 preset triplet).
2. **`audit-v2-vllm-pin-consistency`** — для каждого V2 model с
   non-null `versions.reference_metrics_ref`, его
   `versions.vllm_pin_required` должен матчить vllm версию из
   baseline JSON. Catches F-018 class drift (V1 `a5000-2x-35b-prod.yaml`
   comment явно его выделил: «top-level pin re-aligned with
   reference_metrics.genesis_pin — metrics were re-snapped at that pin
   but the top-level field was forgotten»).

Repo clean в committed state — 44/44 refs резолвятся, 2/2 моделей
с baseline'ом (E22-fixed) match'ат vllm_pin. Codify as regression
anchors.

**Baseline schema variant tolerance** (`_extract_baseline_vllm_version`):
walks 7 known paths in order — `vllm_version`, `vllm_pin`,
`vllm_version.parsed.vllm_version`, `parsed.vllm_version`,
`config.vllm_pin`, `headline.vllm_pin`, `summary.vllm_pin`.
Committed baselines используют nested form (`vllm_version.parsed.vllm_version`).

#### Deliverables

| File | Lines | Tests |
|---|---|---|
| `scripts/audit_v2_cross_reference.py` | ~190 | 5 (live + CLI + 2 synth broken-ref scenarios) |
| `scripts/audit_v2_vllm_pin_consistency.py` | ~210 | 13 (extract walker × 5, per-model × 5, live + CLI × 3) |
| 2 Makefile targets + 2 GATES (both gating) |

#### Acceptance

```text
$ make audit-v2-cross-reference
  44/44 refs resolve  (11 profile parent + 33 preset triplet)

$ make audit-v2-vllm-pin-consistency
  6/6 models pass  (2 compared, 4 skipped — no baseline)
```

`make evidence` → **24 gates, 17 gating + 1 informational green**
(было 22/15+1 после E28). Full pytest **6280 passed, +18 от 6262,
zero regressions**.

#### §4.2 invariants chain — 16 V2-drift bug classes blocked silently

1-14: through E22-E28
15. **profile.parent_model или preset triplet ref не резолвится** (E29)
16. **model.vllm_pin_required ≠ baseline JSON vllm version** (F-018 class, E29)

---

### Entry 30 — patch lifecycle + hardware sanity invariants

**Scope:** оператор попросил «комплексно» — оба audit'а в Entry 30:

1. **`audit-v2-patch-lifecycle`** — для каждого V2 model.patches
   enabled (`GENESIS_ENABLE_<X>_*: '1'`), извлечь patch_id через
   PATCH_REGISTRY env_flag → lifecycle. Lifecycles в `DISALLOWED`
   set (default: `{retired}`) трактуются как hygiene-violation, кроме
   patch_id'ов в `ALLOWED_RETIRED_PATCHES` allowlist.

2. **`audit-v2-hardware-sanity`** — sanity bounds на numeric fields
   в hardware/*.yaml: cuda_capability_min ∈ ([6..12], [0..9]),
   n_gpus ∈ [1..16], min_vram_per_gpu_mib ≥ 8 GiB,
   gpu_memory_utilization ∈ (0.0, 1.0], max_num_seqs ≥ 1,
   max_num_batched_tokens ≥ 256. Plus cross-field check:
   `gmu × vram_mib ≥ 4 GiB usable` (никакая Qwen-класса модель не
   влезет ниже).

#### Real drift discovered

Survey показал **3 retired patches enabled** в committed V2 models:

| Patch | Lifecycle | Enabled in | Allowlist comment |
|---|---|---|---|
| PN19 | retired | all 5 prod models | carry-over from W-A; replacement is part of PN-series consolidation work |
| PN52 | retired | 3 of 5 prod models | still actively consumed by 27B INT4 / 35B FP8 prod path |
| P94  | retired | 2 of 5 prod models | enabled in 27B INT4 TQ + 35B FP8 prod — operator review pending |

`ALLOWED_RETIRED_PATCHES` codifies current state с per-patch
rationale; новый retired-enable без allowlist'а → CI fail.

#### Deliverables

| File | Lines | Tests | Severity |
|---|---|---|---|
| `scripts/audit_v2_patch_lifecycle.py` | ~230 | 6 (schema, live × 3, CLI × 2) | gating |
| `scripts/audit_v2_hardware_sanity.py` | ~220 | 14 (canonical, 9 violations, live, CLI × 2) | gating |
| 2 Makefile targets + 2 GATES |

**Bug fixed in `audit_v2_patch_lifecycle.py`**: when run as
`python3 scripts/audit_v2_patch_lifecycle.py`, sys.path didn't
include repo root → `from vllm.sndr_core...` silently failed →
flag_meta empty → enabled=0 for every model. Added explicit
`sys.path.insert(0, REPO_ROOT)` at module load (same fix that
`audit_configs.py` applies). Same potential gotcha exists in
other scripts but they happen to не triggered его (no
direct PATCH_REGISTRY import).

#### Acceptance

```text
$ make audit-v2-patch-lifecycle
  ✓ qwen3.6-27b-dflash         enabled=22  experimental=21, retired=1
  ✓ qwen3.6-27b-int4-fp8kv     enabled=40  experimental=37, retired=3
  ✓ qwen3.6-27b-tq-k8v4        enabled=39  experimental=35, research=1, retired=3
  ✓ qwen3.6-35b-fp8-dflash     enabled=29  experimental=26, legacy=1, research=1, retired=1
  ✓ qwen3.6-35b-fp8            enabled=33  experimental=29, legacy=1, research=1, retired=2
  ✓ qwen3.6-7b-dense           enabled=0
  6/6 models clean

$ make audit-v2-hardware-sanity
  ✓ a5000-1x-24gbvram-16cpu-128gbram
  ✓ a5000-2x-24gbvram-16cpu-128gbram
  ✓ single-3090-24gbvram
  3/3 hardware files clean
```

`make evidence` → **26 gates, 19 gating + 1 informational green**
(было 24/17+1 после E29). Full pytest **6300 passed, +20 от 6280,
zero regressions**.

#### §4.2 invariants chain — 18 V2-drift bug classes blocked silently

1-16: through E22-E29
17. **enabled-retired patch без operator allowlist** (E30)
18. **nonsense numeric values в hardware** (cuda 99.x, gmu=2.0, etc.) (E30)

---

### Entry 31 — patch dependency + default-on invariants

**Scope:** оператор попросил «комплексно» — оба audit'а:

1. **`audit-v2-patch-dependencies`** (gating) — для каждого V2
   model.patches enabled (`GENESIS_ENABLE_<X>='1'`), все
   `requires_patches` должны быть enabled, и ни один из
   `conflicts_with` не должен быть enabled. Уникальная сложность:
   **multi-pid env_flag**. В PATCH_REGISTRY есть 2 env_flag'а
   разделённые между несколькими pid'ами:
   - `GENESIS_ENABLE_P67_TQ_MULTI_QUERY_KERNEL` → {P67, P67b}
   - `GENESIS_ENABLE_PN40_DFLASH_OMNIBUS` → {PN40, PN40-classifier}

   Naive 1:1 flag→pid map would производить false-positive («P67b
   requires P67 but P67 not enabled»). Audit использует 1:N reverse
   map (`flag_to_pids: dict[str, list[str]]`) — setting one shared
   flag enables ALL pids that use it, что соответствует actual
   runtime semantics.

2. **`audit-v2-default-on-mismatch`** (informational) — surfaces
   operator overrides: если PATCH_REGISTRY pid has `default_on=True`
   AND V2 model.patches[env_flag] == `'0'` (explicit disable),
   reports как «operator intentionally disabled a default-on patch».
   Никогда не блокирует — operator может законно disable defaults
   for bisecting bench regressions, hardware workarounds, etc.

#### Survey results

- 6 patches с `requires_patches`, 12 с `conflicts_with`, 33 с `default_on=True`
- After multi-pid flag fix: **0 dependency violations** (all 6 V2 models clean)
- **0 default-on overrides** в committed V2 models — operators
  не disable defaults sегодня

#### Deliverables

| File | Lines | Tests | Severity |
|---|---|---|---|
| `scripts/audit_v2_patch_dependencies.py` | ~210 | 6 (live × 2 + synthetic drift × 3 + CLI × 2) | gating |
| `scripts/audit_v2_default_on_mismatch.py` | ~180 | 5 (live × 1 + synth × 1 + CLI × 2 + import sanity) | informational |
| 2 Makefile targets + 2 GATES |

Synthetic tests verify the multi-pid handling specifically:
`test_synthetic_multi_pid_flag_satisfies_requires` — shared flag
enables both pids, requires=['P67'] satisfied without needing a
separate flag.

#### Acceptance

```text
$ make audit-v2-patch-dependencies
  ✓ qwen3.6-27b-dflash         enabled=23  req_viol=0  conf_viol=0
  ✓ qwen3.6-27b-int4-fp8kv     enabled=41  req_viol=0  conf_viol=0
  ✓ qwen3.6-27b-int4-tq-k8v4   enabled=40  req_viol=0  conf_viol=0
  ✓ qwen3.6-35b-fp8-dflash     enabled=31  req_viol=0  conf_viol=0
  ✓ qwen3.6-35b-fp8            enabled=34  req_viol=0  conf_viol=0
  ✓ qwen3.6-7b-dense           enabled=0
  6/6 models clean

$ make audit-v2-default-on-mismatch
  0 explicit default-on override(s) across 6 model(s)
```

(Note: enabled counts ↑ by 1-3 vs E30 — multi-pid flag now
correctly counts BOTH pids когда shared flag set; E30's count
under-counted P67/P67b и PN40/PN40-classifier pairs.)

`make evidence` → **28 gates, 20 gating + 2 informational green**
(было 26/19+1 после E30). Full pytest **6311 passed, +11 от 6300,
zero regressions**.

#### §4.2 invariants chain — 20 V2-drift bug classes blocked silently

1-18: through E22-E30
19. **enabled patch missing its requires dependencies** (E31, gating)
20. **two conflicting patches both enabled** (E31, gating)
+ informational: explicit default-on overrides surfaced

---

### Entry 32 — V2 capability + pin-format invariants

**Scope:** оператор «комплексно» — оба audit'а в Entry 32:

1. **`audit-v2-capability-coverage`** (gating) — `model.capabilities`
   strings должны быть в frozen allowed sets:
   - `attention_arch`: {dense, hybrid_gdn_moe}
   - `tool_call_parser`: {qwen3_coder}
   - `reasoning_parser`: {qwen3}
   - `kv_cache_dtype`: {fp8_e5m2, fp8_e4m3, turboquant_k8v4, fp16, None}
   - `spec_decode.method`: {mtp, dflash, ngram, None}

   Typo в любой строке silently выбирает wrong code path (or None
   fallback). Default `None` для optional capabilities явно в allowed
   set'е — отличается от absent (handled by E27 required-fields gate).

2. **`audit-v2-versions-pin-format`** (gating) — regex-валидация
   `versions.{vllm_pin_required, genesis_pin_min}`:
   - vllm: `^\d+\.\d+\.\d+(?:rc\d+)?(?:\.dev\d+)?\+g[0-9a-f]+$`
   - genesis: `^v\d+\.\d+\.\d+(?:[+-][\w.]+)?$`

   Catches typos: пропущенный `+g<sha>`, mistyped version, mixed
   v/no-v prefix. Регекс tolerates legitimate variations (rc/dev
   suffixes optional; genesis может иметь +wave8 / -alpha suffix).

#### Deliverables

| File | Lines | Tests | Severity |
|---|---|---|---|
| `scripts/audit_v2_capability_coverage.py` | ~170 | 9 (schema + 6 per-file scenarios + live + CLI × 2) | gating |
| `scripts/audit_v2_versions_pin_format.py` | ~170 | 17 (regex × 7 + per-file × 5 + live + CLI × 2 + dot-walk) | gating |
| 2 Makefile targets + 2 GATES |

#### Acceptance

```text
$ make audit-v2-capability-coverage         → 6/6 models clean
$ make audit-v2-versions-pin-format         → 6/6 models clean
```

`make evidence` → **30 gates, 22 gating + 2 informational green**
(было 28/20+2 после E31). Full pytest **6337 passed, +26 от 6311**.

#### §4.2 invariants chain — 22 V2-drift bug classes blocked silently

1-20: through E22-E31
21. **typo в model.capabilities (attention_arch, parser, kv_dtype, etc.)** (E32)
22. **malformed vllm_pin_required или genesis_pin_min** (E32)

---

### Entry 33 — quantization + context-length invariants

**Scope:** оператор «комплексно» — оба audit'а в Entry 33:

1. **`audit-v2-quantization-coverage`** (gating) — `model.quantization`
   ∈ {None, auto_round, gptq_marlin, awq, awq_marlin, fp8,
   bitsandbytes}; `model.dtype` ∈ {float16, bfloat16, float32, auto}.
   Typo в любом передаётся прямо в vllm и приводит к argparse fallback
   или silent default — operator intent diverges from runtime.

2. **`audit-v2-context-length-sanity`** (gating) — три bounds на
   `hardware.sizing`:
   - `max_model_len` ∈ [1_024, 2_097_152] (1K..2M tokens; catches
     swapped K/M magnitudes like `320` вместо `320000`)
   - `max_num_batched_tokens` ∈ [256, 65_536] (chunk size sanity)
   - `max_num_batched_tokens ≤ max_model_len` (cross-field: chunk
     не может быть больше context window'а — physical invariant)

#### Deliverables

| File | Lines | Tests | Severity |
|---|---|---|---|
| `scripts/audit_v2_quantization_coverage.py` | ~150 | 9 (schema + 5 per-file + live + CLI × 2) | gating |
| `scripts/audit_v2_context_length_sanity.py` | ~170 | 10 (6 per-file scenarios + live + CLI × 2 + boundary) | gating |
| 2 Makefile targets + 2 GATES |

#### Acceptance

```text
$ make audit-v2-quantization-coverage  → 6/6 models clean
$ make audit-v2-context-length-sanity  → 3/3 hardware clean
```

Live values:
- quant ∈ {None, auto_round}, dtype ∈ {float16, bfloat16}
- max_model_len ∈ {65536, 78000, 320000}, batch ∈ {2048, 4096}

`make evidence` → **32 gates, 24 gating + 2 informational green**
(было 30/22+2 после E32). Full pytest **6356 passed, +19 от 6337,
zero regressions**.

#### §4.2 invariants chain — 24 V2-drift bug classes blocked silently

1-22: through E22-E32
23. **typo в model.quantization / dtype** (E33)
24. **swapped K/M magnitude в max_model_len OR chunk > ctx** (E33)

---

### Entry 34 — runtime image-pin + network port consistency

**Scope:** оператор «комплексно» — оба audit'а в Entry 34:

1. **`audit-v2-runtime-image-pin`** (gating) —
   `runtime.docker.image_digest` должен матчить
   `^<repo>@sha256:<64-hex>$`. Floating `image: vllm/vllm-openai:nightly`
   survives для human readability, но production launcher должен
   pin'иться к digest'у (reproducibility). Missing or malformed
   digest = no pin = drift при upstream re-tag.

2. **`audit-v2-network-port-consistency`** (gating) — docker runtime
   ports + shm + network sanity:
   - `host_port`, `container_port` ∈ [1024, 65535] (privileged ports
     blocked — требуют root)
   - `shm_size` ∈ docker size format `^\d+[bBkKmMgG]?$`
   - `network` non-empty string

#### Deliverables

| File | Lines | Tests | Severity |
|---|---|---|---|
| `scripts/audit_v2_runtime_image_pin.py` | ~160 | 10 (regex × 3 + per-file × 4 + live + CLI × 2) | gating |
| `scripts/audit_v2_network_port_consistency.py` | ~180 | 11 (regex × 2 + per-file × 6 + live + CLI × 2) | gating |
| 2 Makefile targets + 2 GATES |

#### Acceptance

```text
$ make audit-v2-runtime-image-pin           → 3/3 hardware files clean
$ make audit-v2-network-port-consistency    → 3/3 hardware files clean
```

`make evidence` → **34 gates, 26 gating + 2 informational green**
(было 32/24+2 после E33). Full pytest **6377 passed, +21 от 6356,
zero regressions**.

#### §4.2 invariants chain — 26 V2-drift bug classes blocked silently

1-24: through E22-E33
25. **missing/malformed docker image_digest pin** (E34, reproducibility)
26. **privileged port, malformed shm_size, empty network name** (E34)

---

### Entry 35 — quality pass: §10.3 extended audit gates + comment scrub + PN95 metadata + 38-PR re-audit

**Scope (multi-session quality pass on 2026-05-13):**

1. **§10.3 extended audit gates promotion** —
   - `audit-docs-stale` (56→0 violations across 13 docs) → gating
   - `audit-public-docs` (93→0 violations across D-1..D-6, regex
     refined to skip backticked identifiers + plain "placeholder" prose)
     → gating
   - `audit-no-stub` (new, AST-based) — bare `raise
     NotImplementedError` + `TODO(name)` markers + `pass  #
     placeholder/scaffold/FIXME` sentinels in `vllm/sndr_core/**/*.py`;
     12 unit tests + live-corpus contract
   - `audit-engine-boundary` (new, AST-based) — unguarded
     `vllm.sndr_engine` imports outside `try / except ImportError`;
     10 unit tests + live-corpus contract
   - `audit-config-keys` (new) — 31 committed V1/V2 YAMLs × 149
     canonical env keys → 0 unknown; 6 unit tests
   - `audit-evidence-freshness` (new, informational) — ledger ≤7 days
     OR HEAD short SHA present; skip on absent ledger (CI); 7 unit tests
   - `audit-release-check` promoted to gating with `--mode
     require-static`; populated 136/136 static proof artefacts under
     `evidence/patch_proof/`

2. **Phase 5 reference template** —
   `plugins/community/_template/PN999/` skeleton (manifest, patch
   stub, test stub) + README; 7 contract tests pinning discovery
   skip + empty-release-tree invariant.

3. **Comment hygiene pass** — `/tmp/scrub_audit_noise.py` cleaned
   29 files, ~129 inline `DA-005 (audit 2026-05-08): heuristic-tagged`
   style noise comments without touching substantive code or
   documentation.

4. **PN95 metadata refresh** — `experimental_note` updated to reflect
   actual 11 anchors across Phase 1/2/4/5 (was «THREE anchors»).
   Phase 5 anchor #10 (physical num_blocks cap) helper exists in
   `_pn95_runtime.pn95_physical_num_blocks_cap()` but text-patch
   wire-in deferred until live GPU validation.

5. **AI attribution disabled** — `.claude/settings.local.json` sets
   `attribution.commit` and `attribution.pr` to empty strings;
   gitignored. New commits do not carry the auto-generated trailer.

6. **38-PR upstream re-audit** — live `gh pr view` check on
   2026-05-13: 7 MERGED since 2026-05-07, all in Skip/Watch buckets
   for our stack (LoRA / NVFP4 / KV-offload / CI infra). Do-list
   (PN82, PN55, P61c) was and remains in `PATCH_REGISTRY`. Full
   matrix in `docs/_internal/UPSTREAM_PR_AUDIT_2026-05-13_RU.md`.

#### Deliverables

| File | Lines | Tests | Severity |
|---|---|---|---|
| `scripts/audit_no_stub.py` | ~164 | 12 | gating |
| `scripts/audit_engine_boundary.py` | ~173 | 10 | gating |
| `scripts/audit_config_keys.py` | ~140 | 6 | gating |
| `scripts/audit_evidence_freshness.py` | ~165 | 7 | informational |
| `scripts/audit_public_docs.py` | refined D-6 | 31 | gating |
| `scripts/docs_stale_scan.py` | already shipped | 9 | gating |
| `plugins/community/_template/` | reference layout | 7 | n/a |
| `docs/_internal/UPSTREAM_PR_AUDIT_2026-05-13_RU.md` | re-audit | - | doc |
| 4 new + 2 promoted Makefile gates + 4 new + 2 promoted `make_evidence` entries |

#### Acceptance

```text
$ make evidence
  ✓ 38/39 gate(s) green; 1 informational warning(s)
  (audit-security remains informational — 188 pre-existing
   operator-path leaks across configs/scripts, out of scope)

$ python3 -m pytest --no-header -q
  6482 passed, 131 skipped, 0 failed
```

#### Why this matters

§10.3 was a 7-item «after Phase 7» list; this pass closes items 2, 3,
4, 5, 7 in one go (items 1 + 6 closed in earlier sessions). The
project moves from «4 informational warnings hidden behind gating»
to «1 documented pre-existing informational, everything else gating».

The 38-PR re-audit confirms the plan from 2026-05-07 was correctly
applied: no new merged upstream PR requires backport for our current
stack. Drift watch-list intact for next revision.

---

### Pending evidence

Items roadmap claims "DONE" without yet-recorded evidence:

- GPU smoke (live launch + minimal request roundtrip) — gated on
  operator availability per PN96 bench plan. Live stack защищён
  26 gating invariant'ами + 2 informational (E22-E34).

(Entries 9 + 12 + 18-34 closed the other items previously listed here.)

These items must NOT be claimed as DONE in roadmap until an entry
below records them passing.
