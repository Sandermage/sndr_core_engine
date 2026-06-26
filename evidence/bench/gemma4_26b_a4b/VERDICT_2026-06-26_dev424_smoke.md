# Gemma 4 26B-A4B AWQ — public boot / coherence / tool-call receipt

Public, repo-tracked evidence for the `prod-gemma4-26b-default` and
`prod-gemma4-26b-multiconc` presets (same `gemma-4-26b-a4b-it-awq` ModelDef,
128-expert MoE, A=4B active, AWQ-4bit, 2x A5000 TP=2).

This file carries ONLY independently re-statable measured facts. The full
internal proof (per-prompt transcripts, the B4 conc=8 structured-JSON
throughput sweep) lives in the private evidence layer referenced from each
preset's `external://sndr_private/...` `evidence_ref`.

## Validation pin

- vLLM pin: `0.23.1rc1.dev424+g3f5a1e173` (current canonical, promoted 2026-06-25)
- Hardware: 2x A5000 24GB (Ampere sm_86), TP=2
- ModelDef: `gemma-4-26b-a4b-it-awq` (`chat_template: null`, native HF template)

## Boot + correctness (PASS) — dev424

| Check            | Result                                                        |
|------------------|---------------------------------------------------------------|
| Engine boot      | PASS — Genesis overlay `failed=0`, no illegal-memory-access   |
| Coherence        | PASS — "The capital of France is **Paris**." (no thought prefix) |
| Tool-call        | PASS — `get_weather {"city":"Berlin"}`, `finish_reason=tool_calls` |

Source: CHANGELOG dev424 validation table (Gemma-4-26B-A4B AWQ MoE row:
"Paris + get_weather Berlin, failed=0, no IMA") + the `gemma-4-26b-a4b-it-awq`
ModelDef 2026-06-23 live-finding block (clean chat + working `get_weather`
tool-call once the custom G4_11 chat template is disabled).

## Throughput — INFORMATIONAL ONLY, not the card metric

Single-stream wall-throughput has only been measured on **earlier** pins, not
on dev424. It is recorded here for context, NOT as a production SLA. The card
`primary_metric` deliberately stays at `0.0` / pending until a canonical
dev424 single-stream baseline is published.

| Metric            | Value      | Pin / config                                  |
|-------------------|------------|------------------------------------------------|
| single-stream TPS | ~106.4     | `0.23.1rc1.dev101`, K=1 MoE single-stream, CV 0.38 (high MoE-routing variance) |
| decode TPOT       | ~11.8 ms   | same run                                        |

Source: git-tracked journal
`docs/superpowers/journal/2026-06-18-0231-migration-journal.md` (26B-A4B MoE
single-stream, health=200 at 210s, `get_weather{"city":"Kyiv"}` PASS).

## Promotion note

A `smoke` + `tool_call_eval` public receipt clears the
`production_candidate_public_evidence` audit warning (rule requires >=1 public
`evidence_ref`). It does NOT pre-pay the `production` promotion bar: promoting
either preset to `status: production` will additionally require a substantive
public **bench** ref (a canonical dev424 single-stream baseline for
`-default`; a public conc=8 structured-JSON throughput sweep for `-multiconc`).
