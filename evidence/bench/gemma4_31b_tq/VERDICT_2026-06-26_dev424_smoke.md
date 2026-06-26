# Gemma 4 31B AWQ (dense) — public boot / coherence / tool-call receipt

Public, repo-tracked evidence for the `prod-gemma4-31b-tq-default` preset
(`gemma-4-31b-it-awq` ModelDef, dense AWQ-4bit, TurboQuant-intended,
2x A5000 TP=2, MTP off in the default role).

This file carries ONLY independently re-statable measured facts. The full
internal proof lives in the private evidence layer referenced from the
preset's `external://sndr_private/...` `evidence_ref`.

## Validation pin

- vLLM pin: `0.23.1rc1.dev424+g3f5a1e173` (current canonical, promoted 2026-06-25)
- Hardware: 2x A5000 24GB (Ampere sm_86), TP=2
- ModelDef: `gemma-4-31b-it-awq` (`chat_template: null`, native HF template)

## Boot + correctness (PASS) — dev424

| Check            | Result                                                          |
|------------------|-----------------------------------------------------------------|
| Engine boot      | PASS — Genesis overlay `applied=68/75 failed=0`, no illegal-memory-access |
| Coherence        | PASS — "Paris" + "6x7=42"                                        |
| Tool-call        | PASS — `get_weather`, `finish_reason=tool_calls`                |

Source: CHANGELOG dev424 validation table (Gemma-4-31B-it AWQ TQ + MTP kv-auto
row: "Paris + 6x7=42 + get_weather, applied=68/75 failed=0, no IMA").

## Throughput — INTENTIONALLY OMITTED

No clean single-stream throughput number is published for this preset.
TurboQuant (the backend this `-tq-default` preset is built around) is BLOCKED
on the live dev424 image (the attention-validity gate rejects TURBOQUANT for
Gemma 4 MM), so the engine currently renders kv-auto at this preset's context.
The throughput figures that exist in the journals belong to either a different,
now-archived config (`gemma4-31b-tq-mtp-chat-k3`, ~40 TPS single-stream) or a
degraded non-TQ kv-auto fallback profile on a different pin (78.4 TPS, pin
`303916e93`) — neither is the `-tq-default` single-stream number. Publishing
any of them as this preset's throughput would be a cross-attribution. The card
`primary_metric` therefore stays at `0.0` / pending.

## Promotion note

A `smoke` + `tool_call_eval` public receipt clears the
`production_candidate_public_evidence` audit warning (rule requires >=1 public
`evidence_ref`). It does NOT pre-pay the `production` promotion bar: promoting
this preset to `status: production` will additionally require a substantive
public **bench** ref — which is itself gated on the G4_79/G4_31 TurboQuant
unblock landing on the live pin (see the preset header PIN NOTE).
