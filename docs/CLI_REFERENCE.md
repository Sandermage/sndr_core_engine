# `sndr` CLI Reference

Complete command + parameter reference for the `sndr` CLI exposed by
`sndr-platform` (v12). Every subcommand is grouped by operator
workflow: run, fit, inspect, configure, bench, report.

> **Source of truth**: `sndr --help` and the
> per-subcommand `--help` always reflect the installed surface. This
> document tracks the same content with extra context, examples, and
> a stability badge per subcommand.

## Cheatsheet — first day on a rig → weekly maintenance

Top commands, ordered by operator workflow. Long-form per-subcommand
reference follows from §1 below.

```bash
# Install + first boot
curl -sSL https://raw.githubusercontent.com/Sandermage/sndr_core_engine/main/install.sh | bash
sndr run                                        # resolve → pull → launch → wait → chat (top-fit preset)
sndr up                                         # whole stack: engine + Control Center GUI on :8765
sndr tui                                        # interactive cockpit — serve/stop/chat from one screen
sndr launch prod-qwen3.6-35b-balanced           # launch a named preset
sndr launch prod-qwen3.6-35b-balanced --dry-run # render only, no exec
sndr switch prod-gemma4-31b-tq-default          # swap the running model (stop → boot another)
sndr switch                                     # list presets you can switch to

# Will it fit?
sndr kv-calc prod-qwen3.6-35b-balanced          # per-card VRAM/KV projection (PASS/TIGHT/FAIL)
sndr kv-calc --fit-all                          # whole catalog vs 24/48/80 GB cards
sndr preflight prod-qwen3.6-35b-balanced        # hardware envelope gate

# Health + smoke
sndr doctor                                     # full system diagnostic
sndr doctor --json                              # machine-readable
sndr verify --quick                             # ~3 s static checks, no GPU/model needed
sndr verify --full                              # all static + boot checks
sndr model-config verify prod-qwen3.6-35b-balanced   # bench vs reference_metrics

# Browse + diff presets
sndr preset list                                # V2 preset catalog with cards
sndr preset explain prod-qwen3.6-35b-balanced   # card + composed runtime + fit
sndr config list                                # config inventory
sndr config diff prod-qwen3.6-35b-balanced prod-qwen3.6-35b-multiconc
sndr config explain prod-qwen3.6-35b-balanced

# Patches
sndr patches list --default-on                  # opt-out catalogue
sndr patches plan --preset prod-qwen3.6-35b-balanced             # dispatcher simulation
sndr patches explain PN67
sndr patches doctor                             # registry validator

# Bench
sndr bench --mode quick                         # smoke bench against a running engine
sndr bench --mode full --ctx-scale 32K   # + context-scaling (ceiling label)

# Reporting
sndr report bundle                              # tarball for issues

# Keep current (product only — engine pin stays operator-gated)
sndr update                                     # report: version, pin, commits-behind
sndr update --apply                             # fast-forward + reinstall, then `sndr doctor`

# Shut down + uninstall
sndr down                                       # stop engine + GUI daemon
bash ~/.sndr/install.sh --uninstall
```

For env-var knobs see [`CONFIGURATION.md`](CONFIGURATION.md); for the
GUI Control Center see [`GUI.md`](GUI.md).

## Conventions

| Badge | Meaning |
|---|---|
| **stable** | Production-ready, semver-protected. |
| **beta** | Functional, no breaking changes expected, but the JSON schema may grow fields. |
| **experimental** | Surface may change; useful for advanced operators. |
| **legacy** | Retired from the `sndr` top level; reachable via `python3 -m sndr.cli.legacy` (see the Legacy appendix). |

`<preset>` is a **V2 preset key**, e.g. `prod-qwen3.6-35b-balanced` or
`prod-qwen3.6-27b-tq-k8v4` (under `builtin/presets/`). The V1
monolithic preset tier (flat `builtin/<key>.yaml`) was fully retired
2026-06-01 (Phase 10 sunset); operators using a V1 key get a clean
"preset not found" error.

### CLI ergonomics (v12)

- **Bare `sndr`** on a terminal drops into the interactive
  rig→preset→fit **launch wizard**. Non-interactive callers (pipes,
  CI) get `--help` instead — the wizard never fires without a TTY.
- **Dotted verbs + spaced aliases**: `sndr engines.list` and
  `sndr engines list` are the same command; `sndr pins.list` ==
  `sndr pins list`; `sndr model pull` == `sndr pull`.
- **Bare-group defaults**: `sndr engines` → `engines.list`,
  `sndr pins` → `pins.list`, `sndr mem` → `mem.stats`.
- **Global `--output {json,yaml,text}`** selects the output format for
  commands that support structured output (default: `text`).

---

## 1. Run the stack

### `sndr quickstart` — **stable**

The zero-decision front door — the one command to run if you have never
used SNDR before. It detects your GPU(s) and OS, projects VRAM fit,
auto-picks the top-ranked preset for your rig, boots engine **plus** the
GUI daemon, then offers to remember your choice as the default. Everything
else (`sndr run`, `sndr up <preset>`, explicit pins) is still available —
`quickstart` just removes every decision from the first launch.

```bash
sndr quickstart                                 # detect rig → pick + boot → GUI URL
sndr quickstart prod-qwen3.6-35b-balanced       # skip the pick, boot this preset
sndr quickstart --dry-run                        # resolve + project + plan, start nothing
sndr quickstart --no-input                       # headless: auto-pick, no prompts
sndr quickstart --rig single-3090-24gbvram       # project against a builtin rig (offline)
```

| Flag | Default | Purpose |
|---|---|---|
| `preset` (positional) | auto-pick | Preset to boot. Omit to auto-pick (pinned default, else the top-ranked fitting preset for the detected rig). |
| `--no-input` | off | Headless: never prompt on stdin (auto-pick, skip the make-default offer). |
| `--force` | off | Boot even when the VRAM projection says the preset will not fit (override the FAIL gate). |
| `--gui-port <int>` | 8765 | Port for the product-API + GUI daemon. |
| `--dry-run` | off | Resolve + project + plan without starting anything. |
| `--rig <hardware-id>` | live rig | Resolve the fit against a builtin hardware def (offline). |
| `--fake-gpus <spec>` | live rig | Resolve the fit against a synthetic rig `'name:vram_mib:cc;...'` (offline). |

> First time on any machine? See [QUICKSTART.md](QUICKSTART.md) and your OS
> guide — [RUN_ON_LINUX.md](RUN_ON_LINUX.md), [RUN_ON_MAC.md](RUN_ON_MAC.md),
> or [RUN_ON_WINDOWS_WSL.md](RUN_ON_WINDOWS_WSL.md).

### `sndr run` — **stable**

One command from zero to chat: resolve the top-fit preset for the
detected rig → pull weights → launch → wait for readiness → open an
interactive chat REPL.

```bash
sndr run                                        # top-fit preset for this rig
sndr run prod-qwen3.6-35b-balanced              # explicit preset
sndr run --dry-run                              # resolve + report the plan only
sndr run --no-input                             # headless: print chat pointer, no REPL
```

| Flag | Default | Purpose |
|---|---|---|
| `preset` (positional) | top-fit | Preset to run. Omit to auto-pick the top-ranked fitting preset. |
| `--port <int>` | preset value | Override the preset's port (engine + readiness probe). |
| `--dry-run` | off | Resolve + report the plan without launching, waiting or chatting. |
| `--no-input` | off | Headless: auto-pick the top fit; print the chat pointer instead of a REPL. |
| `--timeout <sec>` | 300 | Seconds to wait for engine readiness. |
| `--rig <hardware-id>` | live rig | Resolve the top fit against a builtin hardware def (offline). |
| `--fake-gpus <spec>` | live rig | Resolve against a synthetic rig `'name:vram_mib:cc;...'` (offline). |

### `sndr up` / `sndr down` — **stable**

Bring up (or stop) the whole stack: engine **plus** the product-API /
GUI daemon (Control Center) on port **8765**.

```bash
sndr up                                         # engine + GUI daemon → prints URL
sndr up prod-qwen3.6-35b-balanced --gui-port 9000
sndr up --no-engine                             # GUI daemon only (engine already runs)
sndr down                                       # stop engine container + GUI daemon
sndr down --dry-run                             # report what would be stopped
```

`sndr up` flags: everything `sndr run` accepts, plus
`--gui-port <port>` (default 8765) and `--no-engine`.
`sndr down` accepts `preset` (default: the same top-fit resolution as
`sndr up`), `--gui-port`, `--dry-run`, `--rig`, `--fake-gpus`.

### `sndr switch` — **stable**

Change which model is running in one stateless step: stop the current
stack and boot another preset. The rig runs one heavy model at a time, so
this is the everyday "give me a different model now" verb. It is a thin
composition over `sndr down` + `sndr up`, so it inherits their weight
checks, readiness wait and GUI-daemon handling. The target preset is
validated **before** anything is stopped — a typo never leaves the rig
with nothing running.

```bash
sndr switch                                     # list the presets you can switch to
sndr switch prod-gemma4-31b-tq-default          # stop current → boot this one
sndr switch prod-qwen3.6-35b-balanced --set-default   # ...and pin it as the default
sndr switch prod-gemma4-26b-default --dry-run   # show the down/up plan, do nothing
```

| Flag | Default | Purpose |
|---|---|---|
| `preset` (positional) | — | Preset to switch to. Omit (or `--list`) to list switchable presets. |
| `--list` | off | List the presets you can switch to and exit. |
| `--set-default` | off | Also pin this preset as the default (so a later bare `sndr up` boots it). |
| `--gui-port <int>` | 8765 | Product-API + GUI daemon port. |
| `--dry-run` | off | Report the down/up plan without stopping or starting anything. |
| `--no-input` | off | Headless: never prompt on stdin. |
| `--timeout <sec>` | 300 | Seconds to wait for the new engine to become ready. |

### `sndr open` — **stable**

Open the local product-API + GUI in your browser.

```bash
sndr open                                       # http://127.0.0.1:8765
sndr open --gui-port 9000
```

### `sndr chat` — **stable**

Thin OpenAI-compatible REPL against an already-running engine.

```bash
sndr chat                                       # default port 8000
sndr chat prod-qwen3.6-35b-balanced             # use the preset's port
sndr chat --port 8102 --host 127.0.0.1
sndr chat --port 8102 --api-key "$SNDR_ENGINE_API_KEY"   # key-protected engine
```

### `sndr remote setup` — **stable**

Client mode: point this machine at an engine running on **another** host —
e.g. a Mac laptop or Windows client talking to your Linux rig. Writes the
remote engine URL, API key and (optional) persistent-memory DSN so `sndr
chat`, `sndr up --no-engine` and the GUI daemon all target the remote
engine instead of `localhost`.

```bash
sndr remote setup http://<rig>:8102/v1               # point at the rig
sndr remote setup http://<rig>:8102/v1 --write-env   # persist to ./.env
sndr remote setup http://<rig>:8102/v1 --key mykey --dsn postgresql://…
```

| Flag | Default | Purpose |
|---|---|---|
| `url` (positional) | — | Remote engine base URL, e.g. `http://<your-host>:8102/v1`. |
| `--key <api-key>` | `genesis-local` | Engine API key for the remote. |
| `--dsn <pgvector-dsn>` | none | Postgres+pgvector DSN for persistent neural-graph memory. |
| `--write-env` | off | Also write the remote block to `./.env` (save-my-choice). |

> Full client-mode walkthrough (Mac / Windows): [REMOTE_ENGINE.md](REMOTE_ENGINE.md),
> [RUN_ON_MAC.md](RUN_ON_MAC.md), [RUN_ON_WINDOWS_WSL.md](RUN_ON_WINDOWS_WSL.md).

### `sndr health` — **stable**

Show sndr-platform version and basic health info.

```bash
sndr health
```

### `sndr update` — **stable**

One command to keep your install current and healthy. By default it is
**read-only**: it reports your version, the engine pin, and whether the
local repo is behind upstream, then tells you the single command to apply
it. Pass `--apply` to actually fast-forward the product code and reinstall.

It deliberately **never upgrades the engine pin** — the vLLM pin is
content-addressed and changing it is an operator decision (bench + patch
re-validation, see [`PIN_BUMP_PLAYBOOK.md`](PIN_BUMP_PLAYBOOK.md)). `sndr
update` moves only the *product* (CLI + GUI + configs).

```bash
sndr update                     # report: version, pin, commits-behind (read-only)
sndr update --apply             # fast-forward the repo + reinstall the package
sndr update --no-fetch          # report from local refs only (offline)
sndr update --json              # machine-readable status
```

| Flag | Default | Purpose |
|---|---|---|
| `--apply` | off | Actually pull the update + reinstall (default: just report). |
| `-y`, `--yes` | off | Non-interactive: assume yes to prompts. |
| `--no-fetch` | off | Skip the network fetch; report from local refs only. |
| `--json` | off | Machine-readable status. |

> Checking health specifically? `sndr doctor` runs the full
> hardware + software + patches + drift diagnostic.

### `sndr tui` — **stable**

Interactive terminal cockpit: one keyboard-driven screen showing the live engine
(tok/s, KV%, TTFT), the fit-ranked preset catalog (`✓`/`✗`), GPU/rig and a status
log — and driving them. `Enter` serves the selected preset (confirm → the same
pull+launch pipeline as `sndr run`), `k` stops it, `d` runs doctor, `c` chats,
`s` opens settings (model dir + HF token); `r` refresh, `?` help, `q` quit. Serve
and stop confirm first.

```bash
sndr tui                                  # detected rig
sndr tui --lean                           # beginner layout (hide operator panes)
sndr tui --rig a5000-2x-24gbvram-16cpu-128gbram   # plan against a builtin rig (offline)
sndr tui --fake-gpus 'RTX A5000:24564:8.6'  # plan against a card you don't have
```

Needs the optional `tui` extra (`pip install 'sndr-platform[tui]'`); without it,
a one-line install hint + clean exit, never a traceback. Full guide:
[`TUI.md`](TUI.md). It owns no logic — a view-and-control over the same seams the
CLI uses.

---

## 2. Launch + fit

### `sndr launch` — **stable**

Launch a preset: interactive rig→preset→fit wizard, or by name.
Renders the launch script, applies patches, and execs it.

```bash
sndr launch                                       # interactive wizard (rig → fitting presets → pick)
sndr launch prod-qwen3.6-35b-balanced             # live launch by name
sndr launch prod-qwen3.6-35b-balanced --dry-run   # render the launch script, no exec
sndr launch --no-input                            # wizard, auto-pick top-ranked fit (CI)
sndr launch --rig=single-3090-24gbvram            # wizard against a builtin rig (offline)
```

| Flag | Default | Purpose |
|---|---|---|
| `preset` (positional) | (wizard) | Preset key to launch. Omit on a TTY to open the interactive wizard. |
| `--port <int>` | preset value | Override the preset's port. |
| `--dry-run` | off | Flag path: render the launch script. Wizard: print the resolved `sndr launch <preset>` command. |
| `--no-input` | off | Wizard without prompts: auto-pick the top-ranked fitting preset. Useful for CI / non-TTY drivers. |
| `--all` | off | Wizard: list non-fitting presets too (default: fitting only). |
| `--rig <hardware-id>` | live rig | Wizard: project against a builtin hardware definition (offline, no nvidia-smi). |
| `--fake-gpus <spec>` | live rig | Wizard: project against a synthetic rig, e.g. `'RTX 3090:24576:8.6'`. Offline. |

For preflight gating use the dedicated `sndr preflight <preset>`; for
policy-filtered env and compose rendering see the legacy
`compose` / `--policy` surfaces in the Legacy appendix.

### `sndr kv-calc` (alias: `sndr fit`) — **stable**

Project a preset's per-card VRAM/KV bytes against a rig — "will it
OOM?" — with a **PASS / TIGHT / FAIL** verdict. Fully offline with
`--rig` / `--card` / `--fake-gpus`.

```bash
sndr kv-calc prod-qwen3.6-35b-balanced            # against the live rig
sndr kv-calc prod-qwen3.6-35b-balanced --card 24  # quick ad-hoc 24 GiB card
sndr kv-calc --fit-all                            # whole catalog vs 24/48/80 GB
sndr kv-calc --fit-all --cards 24,48              # custom card set
sndr kv-calc prod-qwen3.6-27b-tq-k8v4 --solve-max-ctx   # largest ctx that still fits
sndr kv-calc prod-qwen3.6-35b-balanced --kv-breakdown   # per-component byte breakdown
sndr fit prod-qwen3.6-35b-balanced                # same command, shorter name
```

| Flag | Default | Purpose |
|---|---|---|
| `preset` (positional) | — | Preset to project. Omit with `--fit-all` to project the whole catalog. |
| `--fit-all` | off | Project EVERY builtin preset against each card into one fit table. |
| `--cards GB[,GB...]` | `24,48,80` | Per-card VRAM sizes for `--fit-all`. |
| `--rig <hardware-id>` | live rig | Builtin hardware definition (offline). |
| `--card <vram-gb>` | — | Quick ad-hoc rig; overrides `--rig` / live probe. |
| `--fake-gpus <spec>` | — | Synthetic rig `'name:vram_mib:cc;...'` (offline). |
| `--ctx N` | preset's `max_model_len` | Context override (e.g. `131072` or `128k`). |
| `--max-num-seqs N` | preset value | Concurrency override. |
| `--kv-format FMT` | preset value | KV format override (`turboquant_k8v4`, `fp8_e5m2`, `bf16`, ...). |
| `--solve-max-ctx` | off | Report the largest max_ctx that still PASS/TIGHT-fits, then exit. |
| `--kv-breakdown` | off | Full per-component byte breakdown (default: summary). |

### `sndr preflight` — **stable**

Project a preset's hardware envelope against a rig — "can it run?".

```bash
sndr preflight prod-qwen3.6-35b-balanced
sndr preflight prod-qwen3.6-35b-balanced --rig single-3090-24gbvram
sndr preflight prod-qwen3.6-27b-tq-k8v4 --fake-gpus 'RTX 3090:24576:8.6'
```

### `sndr tune` — **stable**

GPU power/clock tuning from a preset's Y8 `gpu_tuning` block. Default
is dry-run; pass `--yes` to actually run `nvidia-smi`.

```bash
sndr tune plan prod-qwen3.6-35b-balanced          # print planned nvidia-smi commands
sndr tune apply prod-qwen3.6-35b-balanced --yes   # apply Y8 gpu_tuning settings
sndr tune revert prod-qwen3.6-35b-balanced        # best-effort restore to defaults (config required)
sndr tune report prod-qwen3.6-35b-balanced        # current state vs Y8 declared
sndr tune sweep prod-qwen3.6-35b-balanced --low 200 --high 300 --bench-cmd '...'   # power-limit sweep
```

---

## 3. Models

### `sndr pull` — **stable**

Download a Genesis-supported model from HuggingFace + generate a
launch script tailored to the chosen workload.

```bash
sndr pull qwen3.6-35b-a3b-fp8
sndr pull qwen3.6-27b-int4 --models-dir /models --workload long_ctx_tool_call
sndr pull qwen3.6-27b-int4 --dry-run              # pre-flight + plan + fit verdict only
```

| Flag | Default | Purpose |
|---|---|---|
| `model_key` (positional) | — | Model key from `sndr list-models` (optional when `--config` used). |
| `--models-dir <dir>` | `SNDR_MODELS_DIR` / `GENESIS_MODELS_DIR` / HF cache | Where to put weights. |
| `--workload <w>` | — | `long_ctx_tool_call` / `interactive` / `throughput`. |
| `--tp <int>` | auto | Tensor-parallel size override. |
| `--launch-out <dir>` | — | Directory for the generated launch script. |
| `--no-launch` | off | Skip launch-script generation (just download). |
| `--dry-run` | off | Print pre-flight + plan + fit verdict; do not download. |
| `--card <vram-gb>` / `--fake-gpus <spec>` | live rig | Offline fit projection. |
| `--revision <rev>` / `--hf-id-override <id>` / `--config <key>` | — | Advanced source selection. |

### `sndr list-models` — **stable**

Browse the curated model registry.

```bash
sndr list-models
sndr list-models --status PROD
sndr list-models --json
```

`--status` filters by `PROD` / `SUPPORTED` / `EXPERIMENTAL` / `PLANNED`.

---

## 4. Presets + configs

### `sndr preset list` — **stable**

List V2 presets with their `PresetCard` metadata. Operator-product
surface — distinct from `sndr config list` (config-key inventory).
See [`PRESETS.md`](PRESETS.md) for the card schema and when to use
which command.

```bash
sndr preset list                                       # all presets, table view
sndr preset list --json                                # machine-readable
sndr preset list --status production_candidate          # filter by card.status
sndr preset list --family qwen3_6_35b                  # filter by card.routing_family
sndr preset list --workload free_chat                  # workload_allow intersection
sndr preset list --hardware a5000-2x-24gbvram-16cpu-128gbram
sndr preset list --mode throughput                     # filter by card.mode
```

Unannotated presets (no `card:` block in YAML) are shown but tagged
`(unannotated)`. They are skipped by `sndr preset recommend`.

### `sndr preset show <preset_id>` — **stable**

Card-formatted view of one preset: identity, workload contract,
operating envelope, evidence, tradeoffs, "do not use". For raw YAML
dump use `sndr config explain <preset_id>`.

```bash
sndr preset show prod-qwen3.6-35b-balanced
sndr preset show prod-qwen3.6-35b-balanced --json
sndr preset show prod-qwen3.6-35b-balanced --field card.evidence_refs.0.path
```

`--field <dot.path>` walks nested attributes / list indices / dict
keys (e.g. `card.evidence_refs.0.path`, `card.concurrency.canonical`).
Errors include the failed segment for self-correction.

### `sndr preset explain <preset_id>` — **stable**

Operator walkthrough: card narrative + composed runtime dry-run +
projected fit + measured bench + single-row diff vs
`card.fallback_preset`. Used to validate that the preset's YAML
triplet actually composes to the runtime claimed in the card.

```bash
sndr preset explain prod-qwen3.6-35b-balanced
sndr preset explain prod-gemma4-26b-multiconc --json
```

The "Composed runtime (dry-run)" section reports `composed_key`,
`kv_cache_dtype`, `max_model_len`, `max_num_seqs`,
`gpu_memory_utilization`, `spec_decode_method`, `spec_decode_K`, and
`enabled_patches_count` — the field-set most operators care about.

### `sndr preset recommend` — **stable**

Inverse lookup: operator declares a workload (with optional hardware
and concurrency constraints), CLI ranks matching presets. Ranking order:

1. `card.status` priority (production > production_candidate > internal_validated > others)
2. `card.default_for_family` (true sorts before false)
3. `card.primary_metric.value` descending
4. preset id ascending (deterministic tie-break)

```bash
sndr preset recommend --workload free_chat \
                      --hardware a5000-2x-24gbvram-16cpu-128gbram \
                      --concurrency 8
sndr preset recommend --workload structured_json.short --top 3
sndr preset recommend --workload custom:my-task --json
```

Workload values are from a frozen taxonomy: `free_chat`,
`structured_json.short`, `structured_json.long`, `tool_call.short`,
`tool_call.long`, `summarization`, `code_gen`, `long_context_qa`.
Custom workloads are accepted via the `custom:<slug>` escape (slug
matches `[a-z0-9._-]+`).

Safety rule: a preset is **excluded** from results when the queried
workload is in its `card.workload_deny`, even if `workload_allow` is
broad or empty.

### `sndr config` — **stable**

Native config inspection + scaffold generator. Subcommands:
`diff` / `explain` / `new` / `checksum` / `list`. (There is no
`config show` — use `sndr config explain` or
`sndr model-config show`.)

```bash
sndr config list                                # config inventory (alias of model-config list)
sndr config diff prod-qwen3.6-35b-balanced prod-qwen3.6-35b-multiconc   # field-by-field
sndr config explain prod-qwen3.6-35b-balanced   # plain-English preset walkthrough
sndr config checksum prod-qwen3.6-35b-balanced  # deterministic SHA256 of the preset YAML
sndr config new my-rig --from-detect            # detect host + scaffold a starter YAML
sndr config new my-rig --from-template prod-qwen3.6-35b-balanced
```

`sndr config new` writes to the user model-config dir (default
`~/.sndr/model_configs/<key>.yaml`); `--from-detect` probes the host
(deps.inspect_host) and auto-fills the hardware + system_env sections;
`--out <path>` and `--force` control the destination.

### `sndr model-config` — **stable**

Vetted model launch configurations. Fourteen subcommands:

| Subcommand | Purpose |
|---|---|
| `list` | Enumerate all configs. |
| `show <key>` | Print full YAML. |
| `render <key>` | Emit launch script. `--runtime {docker,podman,kubernetes,lxc_proxmox,bare_metal}`, `--mode {wheel,dev,dev_legacy}`, `--force`. |
| `save <key>` | Write launch script to file. |
| `audit <key>` | Run audit_rules (cross-patch checks). |
| `validate <key>` | Schema + audit (recommended pre-launch). |
| `preflight <key>` | Pre-launch environment checks. |
| `diagnose <key>` | Runtime diagnose — query a running container. |
| `verify <key>` | Bench vs `reference_metrics` (CI gate). |
| `where <key>` | Show source tier. |
| `new <key>` | Create a user config. |
| `promote <key>` | Promote a community config along `community-test → -dev → -prod`. |
| `launch <key>` | Execute the rendered script. |
| `bench-and-update <key>` | Bench + write metrics back into YAML. |

```bash
sndr model-config show prod-qwen3.6-35b-balanced
sndr model-config render prod-qwen3.6-35b-balanced --runtime kubernetes
sndr model-config validate prod-qwen3.6-35b-balanced
sndr model-config verify prod-qwen3.6-35b-balanced      # bench vs reference_metrics
sndr model-config promote my-preset --to community-dev --rig-tag rtx-a5000 --handle you
```

`promote` flags: `--to {community-dev,community-prod}` (required),
`--rig-tag <tag>`, `--handle <github-handle>`, `--force`. Schema gates
(cross-rig validation, reference_metrics, cooling-off window) enforce
safe progression.

---

## 5. Patches

### `sndr patches list` — **stable**

Browse the patch registry with filters.

```bash
sndr patches list
sndr patches list --tier community --lifecycle stable
sndr patches list --family attention.turboquant --json
sndr patches list --default-on
sndr patches list --opt-in
sndr patches list --has-upstream
sndr patches list --no-upstream
```

The JSON output carries an extra `production_default` field with
honest values: `applied` / `marker` / `opt-in` / `blocked`.

### `sndr patches explain <patch_id>` — **stable**

Detailed view of a single registry entry: family, env_flag,
applies_to, dependencies, conflicts, lifecycle, upstream PR, evidence.

```bash
sndr patches explain PN204
sndr patches explain P67 --json
```

### `sndr patches doctor` — **stable**

Validator over `PATCH_REGISTRY` + apply layer wiring.

```bash
sndr patches doctor
sndr patches doctor --json
```

### `sndr patches plan` — **stable**

Simulate dispatcher decisions for a preset, optionally filtered by
the `patch_plan` resolver policy.

```bash
sndr patches plan --preset prod-qwen3.6-35b-balanced                        # legacy simulator
sndr patches plan --preset prod-qwen3.6-35b-balanced --policy compat        # resolver view
sndr patches plan --preset prod-qwen3.6-35b-balanced --policy safe --explain
sndr patches plan --preset prod-qwen3.6-35b-balanced --policy minimal --json
sndr patches plan --preset prod-qwen3.6-35b-balanced --profile production   # block partial/placeholder
```

Flags:

| Flag | Default | Purpose |
|---|---|---|
| `--preset <key>` | (required) | V2 preset key. |
| `--json` | off | Machine-readable output. |
| `--profile {any,production}` | `any` | `production` blocks the plan when any included patch has `implementation_status ∈ {partial, placeholder}` or `lifecycle ∈ {research, retired}`. |
| `--policy {compat,safe,minimal}` | unset | Add resolver view to output. |
| `--explain` | off | Include `role`, `note`, `bench_evidence` per decision. Only meaningful with `--policy`. |

When `--policy` is **not** passed, the legacy simulator output still
runs, **and** the resolver runs silently for warnings only (advisory
section surfaces `conflicts_with` + `candidate_when` mismatches).

### `sndr patches pn95-status` — **stable**

Live PN95 (tier-aware KV cache) runtime stats: ticks, pressure checks,
demote count, prefix store size — and a self-diagnosis of common gaps
(multiproc TM gap, no eligible attention layers, etc.).

```bash
sndr patches pn95-status
```

### `sndr patches prove` — **stable**

Run static proof checks over every registry entry (+ proof-artefact
writer).

```bash
sndr patches prove --all
sndr patches prove --all --no-write
sndr patches prove PN95                                 # prove a single patch (positional)
```

### `sndr patches release-check` — **stable**

Decide release-readiness from proof artefacts.

```bash
sndr patches release-check                              # default (report mode)
sndr patches release-check --mode require-static       # CI gate
sndr patches release-check --mode require-bench        # require an attached bench
sndr patches release-check --mode require-baseline     # strict
sndr patches release-check --show-passing
```

### `sndr patches bench-attach` — **stable**

Attach bench output to a patch's proof artifact. `bench_path` is a
positional; the vLLM pin is auto-derived into the artefact filename.

```bash
sndr patches bench-attach PN119 out/bench.json                      # attach a bench run
sndr patches bench-attach PN119 out/bench.json --baseline base.json # + a baseline to diff
```

### `sndr patches proof-status` — **stable**

Bucket every entry by proof tier (`static_only`,
`bench_with_baseline`, `dead`).

```bash
sndr patches proof-status
sndr patches proof-status --json
```

### `sndr patches diff-upstream` — **stable**

Surface patches whose upstream PR has merged and may be retire-ready.

```bash
sndr patches diff-upstream
sndr patches diff-upstream --json
```

### `sndr patches bundles` — **stable**

Predefined patch bundles for common workloads.

```bash
sndr patches bundles list
sndr patches bundles explain long-context-stack
```

---

## 6. Engines + pins

### `sndr engines.list` / `sndr engines.info` — **stable**

Multi-engine registry: vLLM is the primary engine; llama.cpp and
sglang are registered engine backends.

```bash
sndr engines.list                               # NAME / STATUS / VERSION / PIN table
sndr engines list                               # spaced alias, same command
sndr engines                                    # bare group → engines.list
sndr engines.info vllm                          # detailed info about one engine
```

### `sndr pins.list` — **stable**

List pins available for an engine. The current/rollback/stable pins
live in `sndr/pins.yaml` (SSOT).

```bash
sndr pins.list                                  # default engine: vllm
sndr pins.list --engine vllm
sndr pins                                       # bare group → pins.list
```

### Pin bump propagation — `scripts/bump_pin.py` — **stable** (maintainer surface)

Not a `sndr` verb — the repo-side script behind `make bump-pin` that
propagates a new pin from `sndr/pins.yaml` into every downstream
artifact (see [`PIN_BUMP_PLAYBOOK.md`](PIN_BUMP_PLAYBOOK.md) §7).

```bash
make bump-pin NEW=0.23.1rc1.devNNN+g<sha>       # add DRY=1 for a dry run
python3 scripts/bump_pin.py 0.23.1rc1.devNNN+g<sha> \
    --sha-full <40-hex upstream sha>            # equivalent direct call
```

| Flag | Default | Purpose |
|---|---|---|
| `--dry-run` | off | Report the propagation without writing. |
| `--sha-full <40-hex>` | unset | Update `current_sha_full` in `sndr/pins.yaml`. Added 2026-07-04 (dev748 promotion): the full SHA cannot be derived from the version string's short hash, so omitting the flag leaves `current_sha_full` stale — the script prints a loud WARN. Source it from the image label `org.opencontainers.image.revision`. |

---

## 7. Memory daemon (`mem.*`)

Persistent memory (graph + vector) served by the running product-API
daemon (`sndr up`, port 8765). Every verb shares `--url` (else
`$SNDR_MEMORY_URL` / `$SNDR_GUI_URL`, default `http://127.0.0.1:8765`),
`--owner` (else `$SNDR_MEMORY_OWNER`, default 1) and `--token` (else
`$GENESIS_MEMORY_API_KEY`, sent as Bearer).

```bash
# store / retrieve
sndr mem.remember "the 27B rig uses TP=2"       # store a memory
sndr mem.remember "Paris is the capital of France" --kind semantic   # typed (slow-decay) fact
sndr mem.recall "27B rig"                       # graph expand + reinforce
sndr mem.search "TP settings"                   # vector/hybrid search, no side effects
sndr mem.stats                                  # node/edge/community counts
sndr mem                                        # bare group → mem.stats

# brain tier (was GUI/API-only before)
sndr mem.consolidate                            # auto-link + detect communities + rank importance
sndr mem.reflect                                # generative: synthesize insight nodes from clusters
sndr mem.neighbors 42                           # graph connections of node 42
sndr mem.forget 42                              # delete a memory + its edges
sndr mem.import MyVault                          # import an Obsidian vault (notes+wikilinks)
sndr mem.export MyVaultOut                        # export memory back out as an Obsidian vault
```

`mem.reflect` clusters related memories and has the running engine synthesize a
higher-level insight per cluster, stored as a new `semantic` node linked to its
sources (needs `SNDR_OPENAI_BASE_URL` pointed at the engine).

`--kind` selects the cognitive memory type — `working` (~30 min), `episodic`
(~1 day), `semantic` (~1 week), `procedural` (~1 month) — which sets how fast
the memory decays. `mem.import` reads a vault under the daemon's
`GENESIS_MEMORY_VAULT_ROOT`.

---

## 8. Bench

### `sndr bench` — **stable**

Genesis benchmark suite — measures tool-call quality, decode TPOT,
wall TPS, TTFT, stability, and context window against a running
engine.

```bash
sndr bench --mode quick                         # smoke
sndr bench --mode standard --port 8102
sndr bench --mode full --out bench.json --md bench.md
sndr bench --compare A.json B.json --compare-out delta.json
sndr bench --ablate-against baseline.json --ablate-tag pn521-off
sndr bench --mode full --ctx-scale 32K                # context-scaling up to a 32K ceiling
```

| Flag | Default | Purpose |
|---|---|---|
| `--host` / `--port` / `--scheme {http,https}` / `--api-key` | localhost | Target endpoint (https for RunPod / TLS-fronted). |
| `--model <name>` | auto-detect | Override model name (default: from `/v1/models`). |
| `--mode {quick,standard,full}` (or `--quick`) | — | Suite depth. |
| `--runs N` | by mode | Bench iterations per prompt. |
| `--prompts {short,standard,long,structured,code}` | — | Prompt set. |
| `--max-tokens N` | — | Generation cap. |
| `--ctx {1K..256K,all}` | — | Max context size to probe. |
| `--stress N` | by mode | Stability stress iterations. |
| `--ttft-turns N` / `--ctx-timeout N` | — | TTFT multi-turn count / ctx probe timeout. |
| `--out PATH` / `--md PATH` / `--name NAME` | derived | Output JSON / Markdown / arm name. |
| `--skip-toolcall` / `--skip-stress` / `--skip-ctx-probe` / `--skip-multi-turn` / `--skip-ctx-scaling` | off | Skip individual suite sections. |
| `--ctx-scale CEIL` | by mode (quick=16K, standard=32K, full=64K) | Ceiling label for the context-scaling sweep (`1K`..`512K`, a single value). The suite auto-generates the ladder of tiers up to the ceiling, measures decode TPS at each, and issues a LINEAR_OK / cliff verdict. |
| `--ctx-scale-gen-tokens N` | suite default | Tokens generated per ctx-scaling step. |
| `--ctx-scale-step-drop X` / `--ctx-scale-endpoint-floor X` | suite default | Cliff-detection thresholds (max per-step drop / min endpoint ratio). |
| `--accept-rate-floor RATE` | — | Fail the MTP acceptance-rate gate below RATE. |
| `--probe-output-length` | off | Extra output-length probe. |
| `--compare A.json B.json` (+ `--compare-out`) | — | Delta two prior runs. |
| `--ablate-against BASELINE.json` (+ `--ablate-tag`) | — | A/B a run against a baseline. |
| `--quiet` / `--verbose` | off | Output verbosity. |

---

## 9. Diagnostics + reporting

### `sndr doctor` — **stable**

Single-command "is my Genesis healthy" check — hardware + software +
model + patches + validator + lifecycle.

```bash
sndr doctor                            # human report
sndr doctor --json                     # machine-readable
sndr doctor --quiet                    # only critical issues
sndr doctor --full                     # +6 extended sections: wsl, image, mounts, license, engine, remote
sndr doctor --container vllm-35b      # inspect a container's image digest
sndr doctor --remote user@host        # remote capability probe
sndr doctor --redact                   # mask IPs / hostnames / tokens
```

### `sndr verify` — **stable**

Post-install smoke test. **Not** a bench — for bench-vs-reference use
`sndr model-config verify <preset>`.

```bash
sndr verify --quick                    # fast static checks, no GPU/model (default, ~3 sec)
sndr verify --boot                     # quick + apply_all dry-run + chunk.py hook check
sndr verify --full                     # all static + boot checks; live-boot probes reported as SKIP with run-it-yourself guidance
sndr verify --json
```

### `sndr report bundle` — **stable**

Collect a redacted tar.gz of diagnostic artifacts.

```bash
sndr report bundle                                  # ~/.sndr/reports/<ts>.tar.gz
sndr report bundle --output /tmp/report.tar.gz
sndr report bundle --preset prod-qwen3.6-35b-balanced
sndr report bundle --container vllm-server
sndr report bundle --no-redact                      # internal use only
sndr report bundle --scope all                      # default
sndr report bundle --scope deps
sndr report bundle --scope launch
sndr report bundle --scope quality
sndr report bundle --scope patches
```

Scope filters the artifacts collected:

| Scope | Artifacts |
|---|---|
| `all` | doctor.json + patches.json + patch_plan.json + launch_dryrun.sh + vllm_boot.log + host_yaml.txt + nvidia_smi.txt + pip_freeze.txt + git_log.txt + image_inspect.json |
| `deps` | doctor + host_yaml + nvidia_smi + pip_freeze + git_log |
| `launch` | doctor + launch_dryrun + vllm_boot + host_yaml + image_inspect + patch_plan |
| `quality` | doctor + patches + patch_plan + launch_dryrun + vllm_boot + git_log |
| `patches` | doctor + patches + patch_plan + git_log |

### `sndr report cudagraph-coverage` — **stable**

CUDA-graph dispatch hit-rate snapshot for the running process.

```bash
sndr report cudagraph-coverage
sndr report cudagraph-coverage --json
```

Requires `GENESIS_CUDAGRAPH_DISPATCH_TRACE=1` at boot.

---

## Legacy appendix — `python3 -m sndr.cli.legacy`

The pre-v12 verb set was retired from the `sndr` top level but remains
reachable through the legacy entrypoint for back-compat:

```bash
python3 -m sndr.cli.legacy <verb> [args...]
```

Retired verbs (all **legacy** badge; no new features land here):

| Legacy verb | Replacement on the v12 surface |
|---|---|
| `install` | `install.sh` one-liner (see [INSTALL.md](INSTALL.md)). |
| `doctor-system` | `sndr doctor --full`. |
| `memory` | `sndr kv-calc` (plan projection) + product-API memory views. |
| `caveats` | `sndr patches explain <id>` carries caveat info. |
| `self-test` | `sndr verify --quick/--boot`. |
| `compose render/up/down/logs/plan-diff` | `sndr model-config render --runtime docker` + `docker compose`. |
| `quadlet`, `k8s render` | `sndr model-config render --runtime podman/kubernetes`. |
| `service install/start/stop/status/logs/uninstall` | `sndr up` / `sndr down` or your init system. |
| `proxmox doctor/render/status` | `sndr model-config render --runtime lxc_proxmox`. |
| `hardware list`, `profile list/show/diff` | `sndr preset list/show/explain`, `sndr list-models`. (`model list-v2` is currently broken on the legacy path — use the Python Discovery API in [MODELS.md](MODELS.md).) |
| `deps inspect` | `sndr doctor --full`. |
| `upstream list/check` | `sndr pins.list` + `sndr patches diff-upstream`. |
| `community list/validate/new-patch` | unchanged under legacy (community SDK). |
| `config-catalog build/verify/show/query` | unchanged under legacy (derived catalog + `make config-catalog`). |

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Operation failed (non-blocker) |
| `2` | Validation / preflight failed; user action required |
| `>2` | Specific subcommand error code (see `--help`) |

## Environment variables affecting the CLI

| Variable | Purpose |
|---|---|
| `SNDR_ENABLE_<FULL_NAME>=1` / `GENESIS_ENABLE_<FULL_NAME>=1` | Enable an opt-in patch. `<FULL_NAME>` must be the full registry name (e.g. `GENESIS_ENABLE_P67_TQ_MULTI_QUERY_KERNEL`); short forms are silently ignored. |
| `SNDR_DISABLE_<FULL_NAME>=1` / `GENESIS_DISABLE_<FULL_NAME>=1` | Force-disable a patch even when its env_flag is enabled. DISABLE wins over ENABLE. |
| `SNDR_DISABLE_BOOT_PATCHES=1` | Skip the whole boot-time apply phase (meta flag). |
| `SNDR_FORCE_REAPPLY=1` / `SNDR_NO_PATCH_CACHE=1` / `SNDR_NO_VERIFY=1` / `SNDR_TIER_OVERRIDE=<tier>` | Apply-behavior meta flags — see [CONFIGURATION.md](CONFIGURATION.md). |
| `VLLM_USE_FLASHINFER_SAMPLER=1` | Routes top-k/top-p through FlashInfer; PN132 then becomes a no-op fallback guard. |
| `VLLM_LOGGING_LEVEL=WARNING` | Cuts uvicorn access-log noise; recommended for prod. |

For the full env-knob reference (patch flags + runtime tunables) see
[`CONFIGURATION.md`](CONFIGURATION.md) and the inline comments inside
each model YAML.

---

## See also

- [PATCHES.md § patch-plan policy](PATCHES.md) — `--policy compat|safe|minimal` deep dive
- [CONFIGURATION.md](CONFIGURATION.md) — runtime env knobs + preset selection
- [PATCHES.md](PATCHES.md) — patch taxonomy + lifecycle
- [INSTALL.md](INSTALL.md) — first-time install walkthrough
- [GUI.md](GUI.md) — Control Center (product-API daemon on :8765)
- [BENCHMARKS.md § methodology](BENCHMARKS.md) — bench methodology + reproduction
