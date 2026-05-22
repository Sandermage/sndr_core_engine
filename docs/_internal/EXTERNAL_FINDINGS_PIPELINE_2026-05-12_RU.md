# External findings pipeline

**Дата:** 2026-05-12
**Owner:** sandermage
**Source:** PROJECT_ROADMAP_V2_REVIEW_NOTES §P2
**Status:** draft (process design; deferred until Phase 10 patch integration)

---

## 0. Зачем

Проект сильно зависит от vLLM upstream, club-3090 issues, других inference
engines (SGLang, LMCache, TGI) и research papers. Без формального процесса
эти источники превращаются в:

- список URL'ов в research/ docs;
- "когда-нибудь посмотреть";
- copy-paste решений без понимания контекста.

Pipeline превращает каждое внешнее наблюдение в **запись с явным
acceptance criterion + status**. Это делает upstream watch управляемым.

---

## 1. Finding YAML schema

`docs/_internal/external_findings/<id>.yaml`:

```yaml
schema_version: 1
id: external-vllm-42102
source: vllm-pr                          # vllm-pr | vllm-issue | club-3090 | sglang | lmcache | paper | blog | reddit
url: https://github.com/vllm-project/vllm/pull/42102
title: "DFlash + TQ k8v4 coexistence (vllm#42102)"
discovered_at: '2026-05-12'

# Relevance to Genesis
category: memory-cache                   # memory-cache | spec-decode | tool-call | sampling | scheduler | tracing | misc
relevance: qwen/dflash/tq                # tags matching Genesis model families
affected_genesis_paths:
  - vllm/sndr_core/dispatch
  - plugins/community/PN94

# Status machine
status: watch                            # backport-now | watch | skip | needs-reproducer | needs-bench | retire-local-patch | doctor-rule | config-recipe
target:
  - patch-backport                       # what we plan to extract
  - doctor-rule
  - config-recipe

# Risk assessment
risk: medium                             # low | medium | high — based on blast radius
risk_notes: |
  Upstream PR touches the same dispatcher we patch in PN94. If it merges,
  PN94 anchors will drift — must re-anchor + re-bench.

# Acceptance
acceptance: "PN94 apply.shadow strict still CLEAN after vLLM pin bump
             AND bench delta <2% on prod-27b-tq-dflash A/B alias"

# Operator notes
notes:
  - "Watch list because upstream PR has not merged yet (2026-05-12)."
  - "If merged, immediate action: re-anchor PN94 + re-bench."

# Lifecycle
last_reviewed: '2026-05-12'
review_cadence: weekly                   # weekly | biweekly | on-pin-bump | retired
```

---

## 2. Status state machine

```
                        ┌────────────────────┐
   discovered ─────────▶│      watch         │
                        └─────────┬──────────┘
                                  │
            ┌─────────────────────┼─────────────────────┐
            ▼                     ▼                     ▼
       skip (close)        needs-reproducer       needs-bench
                                  │                     │
                                  ▼                     ▼
                            reproducer-ok          bench-results
                                  │                     │
                                  └──────────┬──────────┘
                                             │
                              ┌──────────────┼──────────────┐
                              ▼              ▼              ▼
                       backport-now    doctor-rule    config-recipe
                              │              │              │
                              ▼              │              │
                       retire-local-patch    │              │
                              │              │              │
                              └──────────────┴──────────────┘
                                             │
                                             ▼
                                          done
```

**Allowed transitions:**

- `watch → skip` (closed; reason recorded in `notes`)
- `watch → needs-reproducer` (need local repro before commit)
- `watch → needs-bench` (need bench-and-update to measure delta)
- `needs-reproducer → needs-bench | backport-now | skip`
- `needs-bench → backport-now | doctor-rule | config-recipe | skip`
- `backport-now → done` (patch landed in plugins/community or core)
- `done → retire-local-patch` (upstream merged the equivalent; our patch
  becomes redundant — drop with retire note)

---

## 3. CLI surface

```bash
# Add a new finding
sndr findings add --source vllm-pr --url <url> --category <cat>

# List findings (filtered)
sndr findings list                      # all
sndr findings list --status watch       # active watch
sndr findings list --due-for-review     # past review_cadence

# Update a finding
sndr findings update <id> --status needs-bench --notes "..."

# Validate all findings (schema + transitions + acceptance presence)
sndr findings validate
```

---

## 4. Roadmap placement

Phase 10 sub-deliverable (continuous, P2):

1. `docs/_internal/external_findings/` directory.
2. `vllm/sndr_core/cli/findings.py` CLI surface.
3. `scripts/findings_validate.py` schema + state-machine validator.
4. Seed initial findings from existing `docs/_internal/research/*` and
   `SERVER_CHANGE_WATCH_2026-05-12_RU.md`.

**Acceptance:**

```bash
sndr findings validate                  # exit 0 across all findings
sndr findings list --status watch | wc -l   # finite, well-defined active list
```

---

## 5. Связи

- Roadmap Phase 10 (continuous, P2 — deferred deliverable).
- Implements: PROJECT_ROADMAP_V2_REVIEW_NOTES §P2 first half.
- Pairs with: existing `SERVER_CHANGE_WATCH_2026-05-12_RU.md` (which
  is a manual journal; findings pipeline is the structured form).
- Mitigates: rebase pain (R4 — community patches break upstream rebase),
  by surfacing upstream PRs early as `watch` items.
