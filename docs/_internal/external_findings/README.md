# External findings — early structured tracking

**Status:** active (early Phase-0 deliverable per REFINEMENT_ACTIONS §P2.1).
**Schema:** see `EXTERNAL_FINDINGS_PIPELINE_2026-05-12_RU.md`.

Each `.yaml` file in this directory is a structured external finding —
an upstream vLLM PR, club-3090 issue, paper, or other inference-engine
observation that needs explicit tracking (backport, watch, skip,
benchmark, etc.) instead of getting lost in `research/` ad-hoc notes.

## Status state machine

```
discovered → watch → {skip | needs-reproducer | needs-bench}
                    → {backport-now | doctor-rule | config-recipe}
                    → done → {retire-local-patch}
```

See `EXTERNAL_FINDINGS_PIPELINE_2026-05-12_RU.md` §2 for valid
transitions and §3 for CLI surface (`sndr findings list/add/update/validate`).

## Lifecycle expectations

- Every finding has a `review_cadence` (weekly, biweekly, on-pin-bump,
  retired).
- A finding is **stale** if its `last_reviewed` predates its cadence.
- CLI gate `sndr findings validate` flags stale findings and missing
  acceptance criteria.

## Why this matters

Without structured tracking, `vllm-project/vllm` PRs and club-3090
issues accumulate as URLs in research docs and get re-discovered
months later. Structured findings make external watch:

- a finite, queryable list with explicit status;
- linkable from roadmap and patch manifests;
- a forcing function to write acceptance criteria up front.
