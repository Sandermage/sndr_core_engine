# Quickstart — chatting in 5 minutes

Three commands and you are talking to a local model. No config files, no
preset spelunking — `sndr` auto-detects your GPU, picks a fitting model,
pulls the weights, launches the engine, waits until it is ready, and drops
you into a chat prompt.

> Stack as of 2026-07-04:
> Genesis `v12.0.0` (325 PATCH_REGISTRY entries) ·
> vLLM `0.23.1rc1.dev748+g2dfaae752` (rollback `0.23.1rc1.dev714+g09663abde`,
> stable track `v0.24.0` — single source of truth: `sndr/pins.yaml`) ·
> Reference rig: 2× RTX A5000 24 GB · driver ≥ 580.126 · CUDA 13.

## The 5-minute path

### 1. Install

```bash
curl -sSL https://raw.githubusercontent.com/Sandermage/sndr_core_engine/main/install.sh | bash
```

One paste. The installer detects your OS / Python / GPU / vLLM, clones
Genesis into `~/.sndr/`, and registers the `sndr` command. It asks at most
one question (your workload) and answers `balanced` for you if you are in a
hurry. Full flag matrix: [`INSTALL.md`](INSTALL.md).

**What you get after install:** a clone under `$SNDR_HOME` (default
`~/.sndr/`) with the `sndr` CLI on your PATH, a launch script rendered for
your detected GPU + workload under `~/.sndr/launch/`, and an optional host
profile at `~/.sndr/host.yaml` (create / validate it with
`python3 -m sndr.cli.legacy host init` and `... host doctor` — it tells the
launcher where your model weights live). Two ports matter from here on:
**8000** is the engine's OpenAI-compatible API, **8765** is the browser GUI.

### 2. Run

Pick **one** of these — both end with you chatting.

**A. Terminal chat (simplest):**

```bash
sndr run
```

That single command resolves the best-fitting model for your rig, pulls the
weights if they are missing, launches the engine, waits for it to come up,
and opens a chat prompt. When it is ready you will see:

```text
  ✓ Ready — chat at http://127.0.0.1:8000/v1  (model: …)
```

Type your message and press Enter. `Ctrl-C` to leave the chat.

**B. Browser GUI (LM Studio / Jan style):**

```bash
sndr up        # launch the engine + the GUI server, wait until both are ready
sndr open      # open the GUI in your browser
```

`sndr up` finishes by printing the local address:

```text
  ✓ sndr is up — open http://127.0.0.1:8765 or run `sndr open`
```

The GUI has a first-run Setup wizard that walks you through model choice
and launch. The full GUI manual is [`GUI.md`](GUI.md).

### 3. That's it — you're chatting

A bare `sndr` (no arguments) on a terminal drops straight into a guided
menu, so if you ever forget the verb, just type `sndr` and follow the
prompts.

When you are done:

```bash
sndr down      # stop the engine + GUI started by `sndr up`
```

---

## More — when you outgrow the defaults

Everything above uses the auto-picked model. Once you want a *specific*
model, a different workload, or production tuning, these are the next
commands. The full command list is `sndr --help`; the full reference is
[`CLI_REFERENCE.md`](CLI_REFERENCE.md).

### Run a specific preset

```bash
sndr preset list                         # browse presets for your rig
sndr run prod-qwen3.6-35b-balanced       # run a named preset → chat
sndr up  prod-qwen3.6-35b-balanced       # same, but with the GUI
```

Pick by hardware shape:

| Hardware | Preset | Notes |
| --- | --- | --- |
| 2× RTX A5000 24 GB | `prod-qwen3.6-35b-balanced` | Flagship — Qwen3.6-35B-A3B (MoE), ~242 TPS single-stream (MTP K=5; measured 2026-07-04 on pin `dev748`, AWQ checkpoint). |
| 2× RTX A5000 multi-conc | `prod-qwen3.6-35b-multiconc` | `max_num_seqs=8`, aggregate ~672 TPS (K=3 multi-conc measurement, 2026-05-23 — see [`BENCHMARKS.md`](BENCHMARKS.md)). |
| 2× 24 GB (3090 / 4090 / A5000) | `prod-qwen3.6-27b-tq-k8v4` | Lorbus 27B int4 + TurboQuant k8v4 (long context). |
| 1× RTX A5000 / 3090 | `qa-qwen3.6-27b-tq-1x` | TP=1, 78K context. |

Not sure which fits? `sndr preset recommend` proposes presets for the
workload you describe, and `sndr preset explain <key>` tells one preset's
full story (card + composed runtime + projected fit + measured bench).

For other rigs (single-card, 5090, A6000, H100, mixed) see
[`HARDWARE.md`](HARDWARE.md) and [`SINGLE_CARD.md`](SINGLE_CARD.md). The full
model lineup and chosen-default rationale is in [`MODELS.md`](MODELS.md).

### Inspect before you launch

```bash
sndr run prod-qwen3.6-35b-balanced --dry-run   # show the plan, launch nothing
sndr launch prod-qwen3.6-35b-balanced --dry-run # render the docker command + patch plan
sndr config diff prod-qwen3.6-35b-balanced prod-qwen3.6-27b-tq-k8v4  # field-by-field diff of two presets
sndr config explain prod-qwen3.6-35b-balanced   # plain-English walkthrough
```

First boot takes 2–5 minutes (Triton kernel JIT + CUDA graph capture); warm
restarts are ~30–90 seconds.

### Check your system

```bash
sndr doctor              # full diagnostic: GPU, driver, vllm, plugin, patches
sndr verify --quick      # fast static checks, no GPU/model needed (~3 s); --boot / --full go deeper
sndr model-config list   # vetted model launch configs
sndr report bundle       # diagnostic bundle to attach to an issue
```

`sndr doctor` is the first thing to run if anything looks off — most
problems are environment drift it names directly.

### Chat against an already-running engine

If the engine is already up (you launched it earlier, or on another host):

```bash
sndr chat prod-qwen3.6-35b-balanced
```

Or hit the OpenAI-compatible endpoint directly:

```bash
curl -s -X POST http://localhost:8000/v1/chat/completions \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer genesis-local" \
    -d '{
        "model": "qwen3.6-35b-a3b",
        "messages": [{"role":"user","content":"Say hello in one word."}],
        "max_tokens": 16,
        "temperature": 0
    }'
```

### Stopping cleanly

Use `sndr down` to stop the stack `sndr up` started. Avoid a plain
`docker stop` + `docker start`: that recycles the same writable layer, and
Genesis text-patches applied to that layer fail to re-apply on the next boot
(anchors don't match). The recovery for a stuck container is a full
`docker compose down` → `docker compose up -d`. The "R/W layer trap" and
other cliffs are catalogued in [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).

## What's next

| Topic | Where |
| --- | --- |
| Tune Genesis env flags (P67 splits, P82 threshold, …) | [`CONFIGURATION.md`](CONFIGURATION.md) |
| Browse the patch system + dispatcher | [`PATCHES.md`](PATCHES.md) |
| Fix common OOM patterns + named cliffs | [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) |
| Common questions (pins, patches, hardware, licensing) | [`FAQ.md`](FAQ.md) |
| Add a custom model preset | [`MODELS.md`](MODELS.md) |
| Author a new patch | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| Compare your rig to validated baselines | [`BENCHMARKS.md`](BENCHMARKS.md) |
| Look up a specific `sndr` command | [`CLI_REFERENCE.md`](CLI_REFERENCE.md) |
| Single-card / low-VRAM setups | [`SINGLE_CARD.md`](SINGLE_CARD.md) |

## If something broke

1. `sndr doctor` — most issues are environment drift; re-run.
2. `docker logs <container>` — last 200 lines for the actual error.
3. [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) — named cliffs, OOM recipes, rollback playbook.
4. Open an issue with `sndr doctor --json` output attached.
