# Preset catalog — operator guide

How to find, inspect, and choose between Genesis V2 presets using
`sndr preset list / show / explain / recommend`. Companion to
[`CLI_REFERENCE.md`](CLI_REFERENCE.md) §4 (flag-level surface) and
[`MODELS.md`](MODELS.md) (model-side catalog).

> Quick reference table of the **15 active presets** (9 `prod-*`) is
> in §6 below; archived presets are listed separately. Card schema
> reference lives next to the Python types in
> [`preset_schema.py`](../sndr/model_configs/preset_schema.py).

## What a preset is

A **preset** is the operator-facing entrypoint that resolves to a
specific (model × hardware × profile) triplet plus a piece of
operator-product metadata called a `PresetCard`. The card describes
**what the preset is for** — workload, hardware envelope, K/MTP
policy, evidence, fallback, do-not-use conditions — not how it is
implemented. Implementation lives in the V2 layered config tree
(`model_configs/builtin/{model,hardware,profile}/`).

```text
                ┌───────────────────────────────┐
                │  preset YAML                  │
                │    model    : <ModelDef.id>   │  ← implementation
                │    hardware : <HardwareDef.id>│
                │    profile  : <ProfileDef.id> │
                │    card:    │
                │      title  │
                │      status │  ← operator-product surface
                │      workload_allow / deny
                │      evidence_refs
                │      fallback_preset
                │      ...
                └───────────────────────────────┘
```

The card is optional: legacy 3-pointer presets continue to compose
and run. Annotated cards unlock `list` / `show` / `explain` /
`recommend` operator surfaces.

## When to use which command

Decision tree for the four `sndr preset` leaves:

| You want to... | Use |
|---|---|
| ...see every preset (or filter by status / family / workload / mode / hardware) | `sndr preset list` |
| ...inspect ONE preset's card in full (workload contract, evidence, tradeoffs, do-not-use) | `sndr preset show <id>` |
| ...validate that the YAML triplet composes to the runtime claimed in the card | `sndr preset explain <id>` |
| ...describe a workload and let the CLI pick the right preset for you | `sndr preset recommend --workload <W>` |

Quick distinctions vs neighbouring commands:

- `sndr config explain <id>` dumps the raw composed YAML. `sndr preset show` renders the operator-product card view.
- `python3 -m sndr.cli routing-table --json` emits the workload→preset routing policy at the project level (note: `routing-table` is **not** a top-level `sndr` verb). `sndr preset recommend` queries the same policy per-operator-question with extra filters.
- `sndr launch` (no arguments) opens the interactive fit-ranked wizard, and `sndr kv-calc --fit-all` projects the whole catalog against your cards — the two fastest discovery paths when you don't yet know which preset you want. See [`CLI_REFERENCE.md`](CLI_REFERENCE.md) §2.

## Anatomy of a card

The card sections an operator most often reads:

| Section | What it answers |
|---|---|
| `status` | How production-ready this preset is (see §4 below). |
| `audience` | Who the preset is for (operator / dev / bench / qa / internal). |
| `mode` | Runtime mode shape (throughput / structured_throughput / latency / long_context / tool_agent). |
| `workload_allow` / `workload_deny` | Which workload classes the preset is tuned for (allow) and explicitly hostile to (deny). |
| `concurrency.{min,canonical,max}` | Tested concurrency envelope. Recommend filters on `[min..max]`. |
| `K` | Spec-decode draft tokens (1 = no draft / no speculation). |
| `context.max_model_len` | Context-window cap for this preset's sizing. |
| `routing_family` | Family the preset belongs to (shared cross-preset routing). |
| `default_for_family` | One preset per family is the "if in doubt, use me" default. |
| `fallback_preset` | The conservative alternative if this preset doesn't fit (K>1 presets require one). |
| `primary_metric` + `evidence_refs` | Headline number plus where it came from. Visibility is public / private / mixed. |
| `tradeoffs` | Operator-language statements about cost vs benefit. |
| `do_not_use` | Anti-patterns: condition + reason pairs. |

## Status semantics

`card.status` is the operator-product lifecycle. The ladder, from
strictest to most permissive:

| Status | Meaning |
|---|---|
| `production` | Public baseline cross-validates the preset's runtime; ready for operator-facing production traffic. |
| `production_candidate` | All production-grade fields present but at least one is private-only evidence; promote to `production` once a matching public bench lands. |
| `internal_validated` | Validated by the maintainer for a specific purpose; not a public production claim. |
| `bench_pending` | Loadable preset, primary metric not yet measured. |
| `experimental` | Loose validation; for exploration. |
| `qa` | Lives in the QA harness, not for end-user. |
| `example` | Demonstration / onboarding preset. |
| `historical` | Kept for reproducibility / regression diffs only. |
| `tombstone` | Empirically broken or superseded; `get()` raises with reason. |

At the time of writing, 8 of the 9 active prod-\* presets sit at
`production_candidate` (`prod-diffusiongemma-tp2` is `experimental`) —
public baseline JSONs in
[`tests/integration/baselines/`](../tests/integration/baselines/) cover
the model family but lack the per-preset `config` block cross-validation
that `production` requires. Promotion to `production` is a CONFIG-UX.4
audit-driven decision (separate from card annotation).

### Card status vs profile `override_policy` — two separate ladders

The card's `status` describes **operator-product maturity** of the
*preset*. The profile's `override_policy.class` describes **evidence
maturity** of any `sizing_override` block on the underlying *profile*
(see `docs/CONFIGURATION.md` → "Override policy"). They are independent:

- A `production_candidate` preset CAN compose a profile carrying
  `override_policy.class: bench` (sizing override has bench evidence
  but not full production cross-validation). This is the common state
  for the prod-\* presets today.
- A `production` preset MUST compose a profile carrying
  `override_policy.class: production` (or no `sizing_override` at all).
  This is the gating contract for the promotion step.

`audit_override_policy.py` (default-on at Stage 1) flags any
`sizing_override` block lacking a matching `override_policy`. Class-4
forbidden override predicates fire unconditionally — see
`docs/CONFIGURATION.md` → "Class-4 forbidden overrides".

### Browse cards via the derived catalog

The derived config catalog (`config-catalog`, now on the legacy
entrypoint — see the Legacy appendix in
[`CLI_REFERENCE.md`](CLI_REFERENCE.md)) exposes the same card data
as `sndr preset show` plus the underlying profile / model / hardware
/ baseline rows. Use it for **read-only inspection** when scripting or
when the operator-facing CLI is too narrow:

```bash
# Show a preset's full card + composed config
python3 -m sndr.cli.legacy config-catalog show preset/prod-qwen3.6-35b-balanced

# Find every profile with bench-class override_policy expiring soon
python3 -m sndr.cli.legacy config-catalog query --row-type profile \
                          --field override_expires_at \
                          --expires-before 2026-09-01
```

The catalog is a derived API (rebuilt on demand, no committed JSON);
`sndr preset` remains the operator-facing surface for daily use.

## Evidence visibility

`card.evidence_visibility` (and per-`evidence_refs[].visibility`)
classifies how reproducible the claim is:

- `public` — committed artefact (e.g. `tests/integration/baselines/*.json`); any operator can re-run.
- `private` — lives in the maintainer-private archive (gitignored; see [`CORE_ENGINE_BOUNDARY.md`](CORE_ENGINE_BOUNDARY.md) for the three-zone namespace policy). Operator-side reproduction requires the maintainer's bench rig.
- `mixed` — at least one ref of each visibility.

Operator rule (per [`CORE_ENGINE_BOUNDARY.md`](CORE_ENGINE_BOUNDARY.md)
+ [`LICENSE_POLICY.md`](LICENSE_POLICY.md)): public docs may not link
into the private maintainer tree; the audit gate
[`audit_public_docs.py`](../scripts/audit_public_docs.py) enforces.
Private evidence in a card is fine because cards live next to source.

## Quick reference — 15 active presets (9 prod-\*)

Manually curated from the cards (last refresh 2026-07-04, after the
DFlash/Gemma-K-variant archive wave and the PN520/PN521 pin work).
All 15 active builtin presets carry operator cards:

- 8 `production_candidate` — listed below by family
- 7 non-production (2 `qa`, 3 `example`, 2 `experimental`) — listed
  under [Non-production presets](#non-production-presets-7-carded)
- 11 **archived** presets moved to `builtin/presets/_archive/` — see
  [Archived presets](#archived-presets) below; do not route users to
  them.

K values below are read from the live routing table
(`python3 -m sndr.cli routing-table --json`, 2026-07-04). Verify any
cell with `sndr preset explain <id>`.

### Qwen 3.6 27B INT4 TQ family — `qwen3_6_27b_int4_tq`

| Preset | K | Concurrency | Mode | Best for |
|---|---:|---:|---|---|
| `prod-qwen3.6-27b-tq-k8v4` ★default | 4 | 1..4 | throughput | Long-context single-stream; 262K context cap. K=5→4 coherence re-tune 2026-07-03 (K=5 broke tool-call structure; K=4 is the max coherent K at ~0 speed cost). |
| `prod-qwen3.6-27b-tq-multiconc` | 4 | 1..8 | throughput | Multi-conc throughput (379 TPS @ conc=8, measured at the K=3 era); 131K context. |

### Qwen 3.6 35B-A3B family — `qwen3_6_35b_a3b_fp8`

| Preset | K | Concurrency | Mode | Best for |
|---|---:|---:|---|---|
| `prod-qwen3.6-35b-balanced` ★default | 5 | 1..2 | throughput | Balanced single-stream; 280K context. K=3→5 re-tune 2026-06-19 (+15.8 % TPS). Canonical suite on dev714 (2026-07-04): wall_TPS 234.2 / TPOT 4.04 ms / tool 8/8. |
| `prod-qwen3.6-35b-multiconc` | 5 | 1..8 | throughput | **Reference free-chat multi-conc** — 689 TPS @ conc=8 (dev148-era measurement). |

### Gemma 4 26B-A4B MoE family — `gemma4_moe_26b_a4b`

| Preset | K | Concurrency | Mode | Best for |
|---|---:|---:|---|---|
| `prod-gemma4-26b-default` ★default | 1 | 1..2 | throughput | K=1 control / MTP off baseline; family fallback. |
| `prod-gemma4-26b-multiconc` | 4 | 1..8 | structured_throughput | K=4 multi-conc structured (235.9 TPS @ conc=8 Mode A). Falls back to `prod-gemma4-26b-default`. |

### Gemma 4 31B dense family — `gemma4_dense_31b_tq`

| Preset | K | Concurrency | Mode | Best for |
|---|---:|---:|---|---|
| `prod-gemma4-31b-tq-default` ★default | 1 | 1..2 | throughput | Dense 31B, MTP off, broad workload coverage. |
| `prod-gemma4-31b-kvauto-chat` | 3 | 1..2 | throughput | kv-auto (uniform fp16 KV, no TurboQuant), 32K ctx, MTP K=3. ~+70% chat TPS (70.1 vs TQ 41.4) and better tool-call (7/7 vs 6/7) than the archived TQ chat sibling, in exchange for 64K→32K context. `fallback_preset` → `prod-gemma4-31b-tq-default` for requests above 32K. |

### DiffusionGemma family — `diffusiongemma_26b_a4b` (experimental)

| Preset | K | Concurrency | Mode | Best for |
|---|---:|---:|---|---|
| `prod-diffusiongemma-tp2` | 1 | 1..2 | long_context | Block-diffusion text (no AR draft/verify loop), TP=2, 128K max safe context. Status `experimental` — coherent-serve PASS, speed bench pending. |

### llama.cpp engine lane — `qwen3_6_27b_llamacpp_1x` (multi-engine)

| Preset | K | Concurrency | Mode | Best for |
|---|---:|---:|---|---|
| `llamacpp-qwen3.6-27b-q4km-1x` | 2 | 1 | long_context | The only non-vLLM engine preset: Qwen 3.6 27B Q4_K_M GGUF on **llama.cpp**, single 24 GB card, 131K context, Cliff-immune. Max-context / multi-platform lane, not raw throughput (vLLM is ~2.5× faster on the same card). Terminal fallback lane for `prod-qwen3.6-27b-tq-k8v4`. |

### Non-production presets (7 carded)

These cards exist so the operator product surface (`sndr preset
list/show/explain/recommend`) covers the full builtin catalog. They
are NOT eligible for production routing — `card.status` and
`workload_deny` keep them out of the production allow-set.

| Preset | Status | Audience | Mode | Best for |
|---|---|---|---|---|
| `qa-qwen3.6-27b-tested` | qa | qa | throughput | Regression baseline vs `prod-qwen3.6-27b-tq-k8v4` (fp8 KV variant). |
| `qa-qwen3.6-27b-tq-1x` | qa | qa | throughput | Single-card 78K context; 27B TQ k8v4 QA. |
| `example-2x-tier-aware` | example | dev | throughput | Path C tier-aware cache demo (PN95). |
| `example-3090-dense-cpu-offload` | example | dev | latency | club-3090 Path A dense + CPU offload demo. |
| `example-3090-tier-aware` | example | dev | long_context | club-3090 Path C tier-aware demo (145K ctx). |
| `llamacpp-qwen3.6-27b-q4km-1x` | experimental | operator | long_context | llama.cpp lane (see table above). |
| `prod-diffusiongemma-tp2` | experimental | bench | long_context | Block-diffusion bring-up (see table above). |

### Archived presets

Eleven presets were moved to
`sndr/model_configs/builtin/presets/_archive/` (2026-06/07 archive
wave): the four DFlash presets
(`prod-qwen3.6-27b-dflash`, `prod-qwen3.6-27b-dflash-multiconc`,
`prod-qwen3.6-35b-dflash`, `prod-qwen3.6-35b-dflash-multiconc` —
archived pending DFlash re-validation on the 0.23.x pins), the Gemma
K-variant siblings (`prod-gemma4-26b-mtp-k4`,
`prod-gemma4-26b-mtp-chat-k3`, `prod-gemma4-26b-multiconc-k1`,
`prod-gemma4-31b-tq-mtp-structured-k4`,
`prod-gemma4-31b-tq-mtp-chat-k3` — consolidated onto the `-default` /
`-multiconc` / `-kvauto-chat` survivors), plus
`experimental-qwen3.6-27b-tq-dflash-ab` and `long-ctx-qwen3.6-27b`.
Archived presets do not resolve on the operator surface; their bench
rows remain in [`BENCHMARKS.md`](BENCHMARKS.md) as historical
evidence. To resurrect one, move its YAML back out of `_archive/` and
re-validate against the current pin.

## Workload taxonomy

The `card.workload_allow` / `workload_deny` fields use a frozen
canonical taxonomy. `sndr preset recommend --workload <W>` accepts
only these strings (or a `custom:<slug>` escape):

| Workload | What it covers |
|---|---|
| `free_chat` | Open-ended conversational generation. |
| `structured_json.short` | JSON / structured output ≤ ~200 tokens (tool args, small schemas). |
| `structured_json.long` | JSON output > ~200 tokens (large schema responses). |
| `tool_call.short` | Single-step tool invocation. |
| `tool_call.long` | Multi-step / nested tool-call sequences. |
| `summarization` | Document summarization. |
| `code_gen` | Code generation / autocompletion. |
| `long_context_qa` | Long-context retrieval / QA. |

Custom workloads use `custom:<slug>` (slug matches `[a-z0-9._-]+`).
Recommend ranks them only when a card's `workload_allow` lists the
exact same string.

## Examples

Find the best preset for short structured JSON at concurrency 4 on
the homelab rig:

```bash
sndr preset recommend \
  --workload structured_json.short \
  --hardware a5000-2x-24gbvram-16cpu-128gbram \
  --concurrency 4
```

Inspect what `prod-qwen3.6-35b-multiconc` actually does at runtime (composed
config + fallback diff vs `prod-qwen3.6-35b-balanced`):

```bash
sndr preset explain prod-qwen3.6-35b-multiconc
```

Drill into a specific evidence path:

```bash
sndr preset show prod-qwen3.6-35b-balanced --field card.evidence_refs.0.path
# tests/integration/baselines/35b_v11_wave9.json
# (historical Wave-9 baseline; the model YAML marks it no-longer-authoritative —
#  current per-pin evidence lives in e.g. prod-35b_gbf610c2f5_2026-05-23.json
#  and the model YAML's vllm_pin_required promotion notes)
```

List all production_candidate presets for a specific family:

```bash
sndr preset list --status production_candidate --family qwen3_6_35b_a3b_fp8
```

Confirm a workload-deny is honoured (Gemma4 K=4 must NOT appear for
free_chat queries — its `workload_deny` lists `free_chat`):

```bash
sndr preset recommend --workload free_chat \
                      --hardware a5000-2x-24gbvram-16cpu-128gbram \
                      --concurrency 8
# Returns Qwen 35B multi-conc presets first; Gemma4 K=4 is excluded.
```

## See also

- [`CLI_REFERENCE.md`](CLI_REFERENCE.md) §4 — flag-level surface for `sndr preset`
- [`CLI_REFERENCE.md`](CLI_REFERENCE.md) Legacy appendix — derived config catalog (`config-catalog` via `python3 -m sndr.cli.legacy`)
- [`CONFIGURATION.md`](CONFIGURATION.md) — `override_policy`, `SNDR_V1_ROLLOUT_STAGE`, Class-4 forbidden overrides
- [`MODELS.md`](MODELS.md) — model-side catalog (one row per ModelDef)
- [`PATCHES.md`](PATCHES.md) — patch taxonomy (referenced by `profile.patches_delta`)
- [`CORE_ENGINE_BOUNDARY.md`](CORE_ENGINE_BOUNDARY.md) — three-zone namespace policy that governs evidence visibility
- [`BENCHMARKS.md`](BENCHMARKS.md) — bench methodology that produces the evidence_refs targets
