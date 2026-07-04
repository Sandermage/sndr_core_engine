# Workload-Gate Routing Table

The routing-table emitter produces a JSON contract that external
callers (aggregators, proxies, gateways) consume to dispatch incoming
requests to the correct vllm preset based on **workload class**,
**expected output length**, **concurrency mode**, and **model
family**.

**Invocation:** `routing-table` is **not** a top-level `sndr` verb in
v12 — the canonical invocation is:

```bash
python3 -m sndr.cli routing-table --json
```

(`--validate`, `--out FILE` and `--vllm-pin` are the other flags.)
The aggregator flow in one line: **fetch the table → first matching
rule wins → restart-only refresh** (no hot reload). For the
per-question interactive equivalent, use `sndr preset recommend`.

Schema: [`sndr/cli/legacy/routing_schema.json`](../sndr/cli/legacy/routing_schema.json) (v1).

## What this is — and what it is NOT

| | This contract | NOT this contract |
|---|---|---|
| **Audience** | external request routers | the vllm engine |
| **Decision time** | per-request, at the aggregator | n/a — the engine sees K already chosen |
| **Output** | which preset to forward the request to | the actual `--speculative-config` value |
| **K switching** | TWO containers (K=1 default + K=4 structured); request goes to the right one | NOT runtime K switching inside a single engine |
| **Coverage** | only what's been bench-measured + cited evidence | NOT a generic K-policy speculator |

The genesis-vllm-patches repo is **authoritative** for the rules:
each entry cites a bench-source path in its `evidence` field.
Consumers **must not** mutate the rules.

## How to use

### 1. At consumer startup

```bash
python3 -m sndr.cli routing-table --json > /etc/genesis/routing.json
```

(Or, equivalently, run `python3 -m sndr.cli routing-table --json` as
a subprocess on aggregator startup and cache the result.)

### 2. Per request

```pseudocode
table = load_cached_table()
workload = classify(request, table.workload_class_detection)
length   = bucket_length(request, table.length_detection)
conc     = current_concurrency_mode(target_upstream)   # consumer-owned
family   = lookup_model_family(request.model, table.presets)

for rule in table.routing_rules:
    if rule.model_family == family and \
       matches(rule.when, workload=workload, length=length, conc=conc):
        return rule.preset_key

# No rule matched — use the default.
for preset in table.presets:
    if preset.model_family == family and preset.default_for_family:
        return preset.preset_key

# Unknown family — fall back to the model's natural preset
# (V1 model-config lookup, no K=4 override).
return None
```

### 3. Refresh policy

Schema v1 is **restart-only**. Consumers must NOT hot-reload the
table; operators restart the aggregator after a preset change.

## Versioning

`schema_version: 1` is frozen for the lifetime of this schema.
Consumers seeing an unknown version must **warn and degrade gracefully**
(fall back to single-preset routing), not crash. New cells are added
by extending the `routing_rules` list — never by bumping the version.

A future v2 schema would require a coordinated upgrade across the
emitter and every consumer; we'll cross that bridge if a non-additive
contract change is ever needed.

## What's in the table

| Field | Meaning |
|---|---|
| `presets[]` | One entry per builtin preset alias. Each entry exposes `(preset_key, model, model_family, spec_decode_K, max_num_seqs, role, intended_workloads, default_for_family)`. |
| `routing_rules[]` | Evaluated top-to-bottom; **first match wins**. Multi-conc rules precede single-stream rules to avoid ambiguous matches. Each rule cites an `evidence` source and an `evidence_tag` (`measured` for direct A/B; `inferred` for cross-workload reasoning). |
| `workload_class_detection` | Language-neutral detection spec. The aggregator implements these heuristics; the spec is shipped in the table so non-Python consumers can implement the same rules. Order: `tool_call` > `structured_json` > `summarization` > `code_gen` > `free_chat`. |
| `concurrency_mode_detection` | Defines `single_stream` (in-flight ≤ 1) vs `multi_conc` (in-flight ≥ 2). Tracking the counter is the **consumer's** responsibility. |
| `length_detection` | `max_tokens <= 256` ⇒ `short`. Caller hint `expected_length` (if supplied) wins over the `max_tokens` bucket. |
| `fallback` | What to do when no rule matches: use `default_for_family`. When the model family is unknown: skip K=4 overrides, use V1 lookup. **K=1 is the default everywhere.** |
| `coverage_gaps[]` | Known untested cells (e.g. 31B multi-conc structured). Consumers should surface these to operators rather than silently routing to fallback. |

## Current rules (regenerated from the live emitter, 2026-07-04)

The live table carries **one measured rule** — the 2026-06 canonical
preset reorg archived the two K=4 single-stream presets the older
rules routed to, and those cells moved to `coverage_gaps`:

```
gemma4_moe_26b_a4b:
  multi_conc + (structured_json | tool_call) + short  → prod-gemma4-26b-multiconc   (B4 evidence, measured)
  default                                              → prod-gemma4-26b-default    (K=1)

gemma4_dense_31b:
  default                                              → prod-gemma4-31b-tq-default (K=1)
```

`coverage_gaps[]` records the two archived cells explicitly
(single-stream structured on 26B → was `prod-gemma4-26b-mtp-k4`;
single-stream structured on 31B → was
`prod-gemma4-31b-tq-mtp-structured-k4`) with a `next_phase` note:
recreate or re-bench before a measured rule returns.

**Qwen routing is intentionally single-preset.** The rules table is
per-request K-routing between K=1 and K>1 *siblings of the same
family* — a pattern only the Gemma families currently have measured
evidence for. The Qwen 35B/27B PROD presets run MTP K=5 / K=4
*inside* one preset each, so there is no K-sibling to route between;
an aggregator serving Qwen simply forwards to the deployed preset
(the "model's natural preset" fallback). The K=1 policy language
refers to the routing-table default, not to the Qwen engines'
internal spec-decode.

Everything without a matching rule falls back to
`default_for_family` — **effective K=1 by policy** at the routing
layer.

## Operator recipe — verify before deploy

```bash
# 1. Sanity check the schema
python3 -m sndr.cli routing-table --validate

# 2. Inspect the rules + gaps
python3 -m sndr.cli routing-table --json | jq '.routing_rules, .coverage_gaps'

# 3. Pin the table at the deploy boundary
python3 -m sndr.cli routing-table --json --out /etc/genesis/routing.json

# 4. Restart the aggregator to pick up the new table
systemctl restart genesis-aggregator
```

## Phase history

| Phase | What |
|---|---|
| 7.G4.B1.1 / B1.2 | 31B free-chat / structured-JSON bench (foundation evidence) |
| 7.G4.26B-A4B.B2 | 26B-A4B single-stream K=1 vs K=4 (short structured K=4 win) |
| 7.G4.26B-A4B.B3 | 26B-A4B multi-conc free-chat (MIXED band) |
| 7.G4.26B-A4B.B4 | 26B-A4B multi-conc structured-JSON (K=4 +12.8%) |
| 7.G4.WORKLOAD-GATE-POLICY.R / UPDATE | Policy synthesis |
| 7.G4.26B-A4B.PRESET_LABELING | YAML doc-block updates |
| 7.G4.26B-A4B.VARIANT-A-FIX | MTP ownership moved ModelDef → ProfileDef |
| 7.G4.OVERLAY-PATH-CONSISTENCY | Compat shim + audit carve-out |
| 7.G4.WORKLOAD-GATE-POLICY.IMPLEMENT.R | Design (read-only) |
| **7.G4.WORKLOAD-GATE-POLICY.IMPLEMENT** | **This contract.** |
