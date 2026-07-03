# ADR 0002 — Maturity-remediation verdicts (2026-07-03)

Status: **Accepted**
Context: the project-maturity audit surfaced four items whose status was
ambiguous ("is this dead? aspirational? load-bearing?"). This ADR records a
verdict for each, backed by the evidence gathered, so they stop being open
questions. Verdicts follow the Study → Verify discipline: each is grounded in
what the code and the live `dev714` pin actually show, not in titles.

---

## 1. P102 / `sndr/runtime/spec_meta.py` — **KEEP as an explicitly-marked design placeholder**

**Evidence.** `spec_meta.py` is 264 LOC exposing `GenesisSpecMeta` plus the
predicate helpers `should_dispatch_p67` / `should_use_perlayer_workspace` /
`should_skip_tolist` / `should_use_workspace_cache` and `get_telemetry`. It has
**zero real import sites**: `runtime/__init__.py` only lists `"spec_meta"` in
`__all__`; no module executes `import … spec_meta`; the predicate helpers have
0–1 non-self references (none of them called). The registry row P102 is honestly
marked `implementation_status=placeholder`, `apply_module=None`,
`default_on=False`. The spec-decode-aware patches (P67/P67b/P78/P98/P99) still
re-derive their state from local hints — the unified dispatcher this module was
designed for was never built.

**Verdict.** Not dead-delete, not pretend-live. It costs nothing at runtime
(never imported), it is a coherent reviewed design worth preserving, and it is
now flagged with a loud `STATUS: NOT WIRED` header in the module. When the
unified spec-decode dispatcher is actually built, route the scattered predicate
sites through it; if a later cleanup still finds it unwired, move it to
`_archive`. The report's "264-LOC never called" was accurate — the fix is honest
labeling, not a rushed delete of a real design.

## 2. PR#42637 Gemma4 TurboQuant overlay (G4_60x / G4_61 / G4_68 / G4_69 / G4_81 / G4_82 — 20 registry rows) — **KEEP as an experimental, opt-in family**

**Evidence.** 20 patches under `patches/attention/turboquant/g4_*`, **all**
`lifecycle=experimental`, only 2 `default_on`, all spec-driven opt-in (members
of `KNOWN_SPEC_ONLY_PATCHES`). Zero PROD-default footprint.

**Verdict.** Keep. This is real TurboQuant overlay-loader engineering for
Gemma 4, default-off so it carries no PROD risk, and usable when opted in. It is
not dead. Consolidating the loader stack into fewer registry rows is a
nice-to-have, not urgent, and must not change the default-off behavior. Do not
retire.

## 3. Phase 11 modular backend (`product_api/server.py`) vs legacy `http_app` — **legacy `http_app` is canonical PROD; the modular server is experimental-not-prod**

**Evidence.** `legacy/http_app.py` (3866 LOC) serves production via `run_server`
— pinned by the Phase-1 GUI contract test through `unified.create_app` →
`legacy_create_app`. `server.py` (191 LOC) is an incomplete modular parallel.

**Verdict.** Keep legacy as the canonical production app until the modular
server reaches route parity; a second divergent app surface otherwise invites
"which one is live?" confusion. Phase 1 already made `run_server` serve the
unified superset (legacy + memory) and gave the modular `server.py` its
`web_static` fallback. The modular server stays experimental; PROD is not routed
through it. Revisit when it can demonstrably serve the full legacy route set.

## 4. v1/v2 model-config schema (`model_configs/registry_v2` + `schema_v2` vs v1 `registry`) — **v2 is the forward path; v1 stays during migration**

**Evidence.** `registry_v2` has 31 importers vs the v1 `registry`'s 19;
`model_configs/_v1_migration_table.json` shows a migration in progress.

**Verdict.** v2 is canonical going forward (higher adoption, the active schema).
v1 still has 19 live importers, so removing it now would break them —
drive that count down incrementally (migrate importers, lean on the migration
table) and retire v1 only once it reaches zero. New config features target v2;
do not dual-maintain them on v1.

---

### Cross-cutting note
Three of the four ("keep, but label / bound it") are deliberately conservative:
each item is either zero-runtime-cost (P102), default-off (G4 TQ overlay), or
load-bearing-for-live-importers (v1 schema, legacy http_app). Rushing a delete
or a default-flip on any of them would trade a documentation gap for a
regression. The value delivered here is closing the ambiguity with a recorded,
evidence-backed decision — not churn.
