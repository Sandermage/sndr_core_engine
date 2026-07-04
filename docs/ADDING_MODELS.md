# Adding your own model — end-to-end operator manual

This is the step-by-step path from "I have a checkpoint" to "a named
preset that boots, fits, and has bench numbers". It complements the
compact recipe in [`MODELS.md`](MODELS.md) § "Adding a new model"
(architecture check, VRAM math, `--from-running` capture) with the
full V2 workflow: weights layout, the model YAML schema, the 3-layer
composition, the render check, the pin gate, and the bench-driven
enablement rule.

## Prerequisites

- sndr-platform installed and `~/.sndr/host.yaml` valid
  (`python3 -m sndr.cli.legacy host doctor` → 0 fail; see
  [`HOST_SETUP.md`](HOST_SETUP.md)).
- Architecture compatibility confirmed
  ([`MODELS.md`](MODELS.md) § Step 1 — `model_type` table).
- A rough VRAM fit ([`MODELS.md`](MODELS.md) § Step 2, or jump ahead
  to `sndr kv-calc` below which does the byte-level math for you).

## Step 1 — put the weights under `models_dir`

Weights live in HF-format checkpoint directories under the
`models_dir` your `host.yaml` declares. That directory is mounted
read-only at `/models` inside the container, so the YAML's
`model_path` is always the **container-side** path:

```text
/srv/models/                      # host: ${models_dir}
└── MyOrg-MyModel-32B-FP8/        # one HF checkpoint dir per model
    ├── config.json
    ├── *.safetensors
    ├── tokenizer.json / tokenizer_config.json
    └── chat_template*.jinja      # optional template override
```

→ `model_path: /models/MyOrg-MyModel-32B-FP8` in the model YAML.

Download options:

```bash
# curated registry model (browse keys first)
sndr list-models
sndr pull <model_key> --models-dir /srv/models

# arbitrary HF repo
sndr pull <model_key> --hf-id-override MyOrg/MyModel-32B-FP8
# or plain huggingface-cli download into ${models_dir}
```

For the llama.cpp engine lane (`engine: llama-cpp`) `model_path` is a
single `.gguf` FILE, not a directory, and the model YAML declares an
`artifacts:` block with a `gguf-file` entry so `sndr pull --config
<preset>` can fetch it (see
`sndr/model_configs/builtin/model/qwen3.6-27b-gguf-q4km-mtp.yaml`).

## Step 2 — understand the 3-layer design before writing YAML

The V2 registry (`sndr/model_configs/registry_v2.py`) composes a
runtime config from three orthogonal layers plus a thin alias:

| Layer | File | Owns |
| --- | --- | --- |
| **model** | `sndr/model_configs/builtin/model/<id>.yaml` | identity, checkpoint path, dtype/quant, capabilities (parsers, spec-decode, KV dtype), canonical patches set, version pins |
| **hardware** | `builtin/hardware/<id>.yaml` | rig identity (GPU match keys, VRAM floor, SM), sizing knobs, runtime block (docker image, ports, mounts), rig-stable `system_env` |
| **profile** | `builtin/profile/<id>.yaml` | patches delta (enable/disable/override), `sizing_override`, promotion contract, per-workload `system_env` |
| **preset** | `builtin/presets/<alias>.yaml` | 3 pointers (model+hardware+profile) + the operator card (`card:` with `hardware_fit`, workloads, evidence) |

Which layer changes? Three questions (from [`MODELS.md`](MODELS.md)):
different checkpoint/KV/spec method → new **model**; different rig →
new **hardware**; same model+rig but different patches/sizing → new
**profile**. Cross-layer conflicts on owned fields raise `SchemaError`
at load time — ownership-based merge, not override-based.

## Step 3 — write the model YAML

Clone the closest builtin as a template. Good starting points:
`qwen3.6-7b-dense.yaml` (minimal dense community example, heavily
commented) or `qwen3.6-27b-int4-autoround-tq-k8v4.yaml` (the gold
reference with a full curated patch matrix). The schema is
`sndr/model_configs/schema_v2.py: ModelDef`; the fields that matter:

| Field | Required | Notes |
| --- | --- | --- |
| `schema_version` | yes | must be `2` |
| `kind` | yes | `model` |
| `id` | yes | kebab-case, lowercase (`_ID_RE`) |
| `title`, `maintainer`, `last_validated` | yes | identity block |
| `license` | yes | enum: `apache-2.0` \| `gemma-license` (extend `ALLOWED_LICENSES` only with operator review) |
| `model_path` | yes | container path (`/models/...`); a `.gguf` file on the llama-cpp lane |
| `engine` | no (default `vllm`) | enum: `vllm` \| `llama-cpp` |
| `served_model_name`, `quantization`, `dtype`, `trust_remote_code` | no | identity details |
| `capabilities.attention_arch` | yes | enum: `dense`, `hybrid_gdn_moe`, `hybrid_mamba`, `moe`, `gemma4_dense`, `gemma4_moe` |
| `capabilities.tool_call_parser` | no | enum: `qwen3_coder`, `qwen3_xml`, `gemma4`, or null |
| `capabilities.reasoning_parser` | no | enum: `qwen3` or null |
| `capabilities.kv_cache_dtype` | no | enum incl. `auto`, `fp8_e5m2`, `fp8_e4m3`, `turboquant_k8v4`, GGUF `q4_0`/`q5_0`/`q8_0` |
| `capabilities.spec_decode` | no | MTP / draft config, or null |
| `capabilities.shape` | no | architecture dims for `sndr kv-calc` byte-level projection; omit → projection marked PROVISIONAL |
| `requires` | no | `min_total_vram_mib`, `min_gpu_count`, `min_cuda_capability` — composer rejects incompatible (model, hardware) pairs |
| `versions.vllm_pin_required` | strongly | the pin gate — see Step 6 |
| `versions.pin_hold` | no | rationale for holding an older pin (waives the pin-equality audit) |
| `patches` | no | canonical `GENESIS_*`/`VLLM_*` env matrix (string values only) |
| `patches_attribution` | no | per-patch-ID rationale (`load_bearing` / `defensive` / ...) |
| `chat_template` | no | Jinja override; renderer bind-mounts it + emits `--chat-template` |
| `override_generation_config` | no | pins sampling defaults (e.g. Qwen3.6 `temperature=0.6/top_p=0.95/top_k=20`) |
| `extra_vllm_flags` | no | generic `{--flag: value}` pass-through escape hatch |
| `system_env` | no | model-global runtime env (layered hardware < model < profile) |
| `artifacts` | no | weights pull spec consumed by `sndr pull --config <preset>` |

Fill the `shape:` block from the checkpoint's `config.json`
(`num_hidden_layers`, `num_kv_heads`, `head_dim`, ...) — it is what
makes the fit projector answer "will THIS ctx OOM?" instead of only
checking the VRAM floor.

## Step 4 — hardware, profile, preset

- **Hardware**: reuse a builtin
  (`a5000-2x-24gbvram-16cpu-128gbram`, `single-3090-24gbvram`, ...)
  unless your rig differs. A new rig YAML needs `hardware:`
  (gpu_match_keys / n_gpus / min_vram_per_gpu_mib /
  cuda_capability_min), `sizing:` and the `runtime.docker` block with
  the canonical 5-slot symbolic mounts (see
  [`HOST_SETUP.md`](HOST_SETUP.md)).
- **Profile**: start with an EMPTY delta (`enable: {}` / `disable: []`
  / `override: {}`) so the model's canonical patch set applies as-is,
  `status: experimental`. Add `sizing_override` only for this
  (model × rig) pair's tuning, with an `override_policy` justification.
- **Preset alias**: 3 pointers + a card:

```yaml
# sndr/model_configs/builtin/presets/my-model-2x.yaml
model: my-model-32b-fp8
hardware: a5000-2x-24gbvram-16cpu-128gbram
profile: my-model-experimental
card:
  title: "MyModel 32B FP8 — experimental"
  status: community_test
  ...          # see prod-qwen3.6-35b-balanced.yaml for the full card shape
```

## Step 5 — render check (`--dry-run` before any GPU time)

```bash
sndr preflight my-model-2x        # hardware envelope: GPU count / VRAM / SM / pin
sndr kv-calc my-model-2x          # byte-level fit: weights + KV pool + overhead
sndr launch my-model-2x --dry-run # full launcher render, nothing starts
```

Expected `kv-calc` shape (example: the 27B PROD preset projected
against the builtin 2×A5000 rig def):

```text
kv-calc: prod-qwen3.6-27b-tq-k8v4
  point:      ctx=262,144  seqs=4  kv=turboquant_k8v4  util=0.82
  Model weights (÷TP)                  6.52 GiB / card
  KV pool (requested)                  4.50 GiB / card
  Activation + overhead + state        4.31 GiB / card
  TOTAL (committed)                   15.33 GiB / card  / 17.62 budget  (87%)
  VERDICT: ✓ PASS   [calibration PROVISIONAL]
```

FAIL verdicts tell you the fix (`lower max_ctx, drop the drafter,
raise mem_util, or add a card`); `--solve-max-ctx` reports the largest
context that still fits. On the dry-run render, verify the mount
lines, the `vllm serve` argv (parsers, `--kv-cache-dtype`,
`--speculative-config`), and the patch env block. Then run the
offline compose gate:

```bash
make audit-configs                # every V2 preset alias composes cleanly
```

## Step 6 — the pin gate (`vllm_pin_required`)

`versions.vllm_pin_required` declares the vLLM build this model was
validated on. The SSOT for the current pin is **`sndr/pins.yaml`**
(`current: 0.23.1rc1.dev748+g2dfaae752` as of 2026-07-04; see
[`PIN_BUMP_PLAYBOOK.md`](PIN_BUMP_PLAYBOOK.md) § -1). The rules:

- Set it to the SSOT `current` pin — the value your smoke test
  actually ran on. `make audit-pin-consistency` asserts every builtin
  model YAML carries the current pin.
- If you genuinely cannot validate on the current pin (e.g. no
  checkpoint on the rig yet), declare `pin_hold:` with the rationale —
  it explicitly waives the model-vs-hardware pin equality audit
  instead of silently drifting.
- `sndr preflight` checks the preset's `engine_pin` against the live
  image at launch time (SKIP when projecting offline).

## Step 7 — bench-driven enablement (before calling it PROD)

The iron rule: **no preset is production-labeled without reference
numbers captured by the canonical methodology.** Custom bench scripts
carry a 5–25% systematic offset — use the canonical suite only:

```bash
# boot the preset, wait for the apply summary in docker logs, then:
python3 tools/genesis_bench_suite.py --quick --ctx 8k \
    --model <served_model_name> --out ~/.sndr/bench-results/my-model_dev748.json
```

- Record the result where the card can cite it: the preset card's
  `primary_metric` + `evidence_refs`, and the model YAML's
  `versions.reference_metrics_ref`.
- Compare against the closest validated sibling with
  `sndr preset explain <sibling>` (its card carries the measured
  reference — e.g. the 35B family baseline; current headline numbers
  live in [`BENCHMARKS.md`](BENCHMARKS.md), pin-and-date labeled).
- Patches beyond the template's canonical set are enabled ONE profile
  delta at a time, each with an A/B bench against your own baseline
  (`--compare A.json B.json`), never in bulk.
- Lifecycle: the profile starts `experimental`, moves to `validated`
  only when its `promotion.validation_required` list passes (bench
  within tolerance of baseline, tool-call regression clean, soak CV in
  range — see the builtin profiles for the canonical wording).

## Validation checklist

Run through this before opening a PR / promoting the preset:

1. `python3 -m sndr.cli.legacy host doctor` → 0 fail (mounts resolve).
2. Weights present under `${models_dir}`; `model_path` matches.
3. Model YAML validates: `make audit-configs` green, IDs kebab-case,
   enums within `schema_v2.py` allowed sets.
4. `sndr preflight <preset>` → `CAN RUN` on the target rig.
5. `sndr kv-calc <preset>` → PASS/TIGHT (not FAIL) at the declared
   `max_model_len`.
6. `sndr launch <preset> --dry-run` → mounts + argv + env all correct.
7. Boot: apply summary shows `failed=0`; `/health` returns 200.
8. Smoke: one chat completion + (if the model declares a tool parser)
   one tool-call round trip.
9. Canonical bench captured and referenced from the card
   (`primary_metric`, `evidence_refs`).
10. `versions.vllm_pin_required` = SSOT current pin (or `pin_hold`
    documented); `make audit-pin-consistency` green.
11. Profile `status` honest (`experimental` until the promotion
    contract passes).

## See also

- [`MODELS.md`](MODELS.md) — compatibility table, V2 system deep-dive, community submission pipeline
- [`CONFIGS.md`](CONFIGS.md) — narrative "I want to add a model" recipe (V1 `model-config` surface)
- [`HOST_SETUP.md`](HOST_SETUP.md) — host.yaml + symbolic mounts
- [`KV_PROJECTOR.md`](KV_PROJECTOR.md) — the fit math behind `sndr kv-calc`
- [`BENCHMARKS.md`](BENCHMARKS.md) — canonical methodology + current numbers
- [`OPERATIONS.md`](OPERATIONS.md) — running the result day-2
