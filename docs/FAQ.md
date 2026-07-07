# Frequently Asked Questions

Common questions from people who just discovered Genesis and want to know
what they're getting into. If your question isn't here, please open an
issue — the FAQ is updated based on actual user reports.

For deeper topics see also [`GLOSSARY.md`](GLOSSARY.md) (term definitions),
[`HARDWARE.md`](HARDWARE.md) (sizing), and [`CONFIGS.md`](CONFIGS.md)
(per-model launch flags).

### Q: What is Genesis?

A runtime patch package that layers on top of stock vLLM. It applies
text-patches and Triton kernels at boot, plus a small middleware
layer, to optimize Qwen3.6 family models on consumer Ampere/Ada/
Hopper GPUs. Think of it as "vLLM tuning pack" — not a fork.

### Q: Is Genesis a fork of vLLM?

No. Genesis runs against an unmodified vLLM commit (pinned in
[`INSTALL.md`](INSTALL.md)). Patches are applied at runtime via the
dispatcher, anchored to known commits. You can run Genesis-on /
Genesis-off with the same vLLM binary by toggling environment
variables.

### Q: Which vLLM pin does Genesis target today?

`0.23.1rc1.dev748+g2dfaae752` (current pin, v12.1.0, promoted 2026-07-04;
`dev714` = `0.23.1rc1.dev714+g09663abde` is the retained previous /
rollback pin). The pin policy is **two rolling nightly pins (current +
rollback) plus one stable release pin** (`v0.24.0`); the single source of
truth is `sndr/pins.yaml`. Each patch declares an `applies_to` range, so newer
vLLM commits cause patches to print `[SKIP — applies_to mismatch]`
rather than crashing. Bumping the pin is a deliberate release event
documented in [`RELEASE_POLICY.md`](RELEASE_POLICY.md).

### Q: How big is the patch registry today?

**329 entries**: 267 full-implementation, 25 experimental, 22 marker-only,
7 partial, 6 retired, 2 placeholder. The current state is always
in [`PATCHES_AUTO.md`](PATCHES_AUTO.md) (auto-generated from
`sndr/dispatcher/registry.py`) and the narrative
explanations in [`PATCHES.md`](PATCHES.md).

### Q: How do I update vLLM without losing patches?

Bump the `applies_to` range on each affected patch and re-run the
anchor-verification suite. Most text-patches survive minor vLLM
updates because their anchors are short and stable; some need the
anchor adjusted by a few characters. `sndr doctor` tells you which
patches drifted before you boot.

### Q: How do I enable or disable an individual patch?

Each patch is gated by a single environment variable — the **full**
registry name, e.g. `GENESIS_ENABLE_P67_TQ_MULTI_QUERY_KERNEL=1` turns
P67 on, unset or `=0` turns it off. The suffix must match the registry
`env_flag` exactly: short forms like `GENESIS_ENABLE_P67=1` are
**silently ignored** (`sndr/env.py` has typo-detection that warns about
near-miss names). The boot log prints every patch and its decision.
There is no global "enable all" switch — by design.

### Q: Which patches are ON by default?

56 of 325 entries are marked `default_on=True` in the
registry — production-eligible Wave 10 backports + legacy
pre-dispatcher overlays that have been validated against the
v11 baselines. Note that `default_on` is informational: the launcher
still has to set the patch's env flag for it to fire (strict opt-in —
see TROUBLESHOOTING.md Bug Class 12). The full list is in
[`PATCHES_AUTO.md`](PATCHES_AUTO.md);
the policy that decides which subset is allowed in production
presets is in [PATCHES.md § patch-plan policy](PATCHES.md).

A fresh Genesis install without any preset still respects the
per-patch `default_on` flag; production launch scripts under
`scripts/` flip additional opt-in patches on top.

### Q: I have one RTX 3090 — what should I run?

`Qwen3.6-27B-int4-AutoRound` from Lorbus, TP=1. The validated
single-card preset is `qa-qwen3.6-27b-tq-1x` (78K context with
TurboQuant k8v4 KV cache). Run `sndr preset list` or
`sndr preset explain qa-qwen3.6-27b-tq-1x` to see the full card;
[`SINGLE_CARD.md`](SINGLE_CARD.md) has the deep-dive.

### Q: I have 2× 24 GiB cards — should I run 27B or 35B?

Depends on workload. 35B-A3B (MoE) wins on prose quality and
broad-knowledge tasks; 27B-int4 wins on tool-call reliability and
long context (280K envelope since the 2026-05-15 trim; 320K was
validated historically). If you primarily run agentic /
tool-calling pipelines, start with 27B.

### Q: Is LoRA supported?

Not actively tested. vLLM's LoRA system should work because Genesis
patches are mostly orthogonal to LoRA loading, but no Genesis-
validated LoRA recipe exists. Try it and report results.

### Q: Does streaming work?

Yes. Patch P61b adds a streaming overlap guard that fixes a slice
bug in upstream Qwen3 streaming output. Enable
`GENESIS_ENABLE_P61B_STREAMING_OVERLAP=1` together with the rest of
the tool-call family if you stream tool calls.

### Q: Does tool-call work reliably?

Yes — this is one of Genesis's main focus areas. The P59 / P61 /
P62 / P64 / P68 / P69 patch family fixes upstream regressions in
Qwen3 tool-call generation, especially around `<think>` tags,
multi-tool prompts, and streaming. Enable them together via the
`tool_call_safe` recipe in [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).

### Q: The 27B answers normally but sometimes loops forever in thinking mode — is that a Genesis bug?

No. Endless `<think>` loops on the INT4 27B are a pre-existing trait of
the model's thinking mode (the same model-class behaviour tracked as
club-3090 #226), re-confirmed during the dev748 fleet sweep
(2026-07-04) — not a patch regression. Workaround: disable thinking
per request via the chat template kwargs:

```json
{"chat_template_kwargs": {"enable_thinking": false}}
```

With thinking off the model answers cleanly. Tool-agent workloads are
unaffected either way: the 27B PROD preset sets
`GENESIS_P68_FORCE_ON_ALL_TOOLS=1` (see
[`CONFIGURATION.md`](CONFIGURATION.md)), which forces
`tool_choice=required` so generation is grammar-constrained to a valid
tool call.

### Q: How do I download the DFlash draft model?

> **Historical** — all 4 DFlash presets are archived as of v12
> (pending re-validation); MTP K=5 is the shipped default. The
> download info below applies only if you re-enable DFlash yourself.

It's a gated HuggingFace repo (`z-lab/Qwen3.6-27B-DFlash`,
`z-lab/Qwen3.6-35B-A3B-DFlash`). Accept the license on the model
page, then `huggingface-cli login` with a token that has read
access. Genesis will not auto-download it for you.

### Q: What if patches break my boot?

First, look at the boot log — Genesis prints `[APPLY]` / `[SKIP]` /
`[FAIL]` for every patch with a reason string. Disable the failing
patch by unsetting its `GENESIS_ENABLE_*` flag. If you can't find a
working subset, file an issue with the full boot log; include your
vLLM commit hash, GPU model, and the model checkpoint. The
[`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) walks through the
recovery procedure step by step.

### Q: How do I capture a running container into a config?

`sndr model-config new <key> --from-running <container>` (audit
C2 closure 2026-05-16). The CLI runs `docker inspect`, reverse-
engineers a `ModelConfig` YAML from the live container's
Entrypoint+Cmd+Env+Mounts, and writes it to
`~/.sndr/configs/<key>.yaml`. Review the GPU id placeholder, the
image digest, and the symbolic-mount references before launching.

### Q: How do I add my own model to Genesis?

The canonical guide is [`MODELS.md` § "Adding a model"](MODELS.md)
(V2 layered schema); [`CONFIGS.md`](CONFIGS.md) covers the
per-flag launch details. Short version:
copy a base config via `sndr model-config new <key> --template
<existing-key>`, update model path + env vars, test boot + tool-call
sanity, submit PR with bench numbers.

### Q: MoE backend — Triton or FlashInfer?

Workload-dependent. Triton MoE is more stable on consumer Ampere/
Ada and is the Genesis default for 35B-A3B-FP8. FlashInfer MoE is
faster on Hopper/Blackwell but has had stability regressions (see
vLLM #41306). On 2× A5000, Triton wins.

### Q: Why DFlash instead of MTP?

> **Historical** — the DFlash presets are archived as of v12; the
> shipped default is MTP with K=5 (`num_speculative_tokens: 5`,
> re-tuned 2026-06-19). The comparison below reflects the pre-archive
> measurements.

DFlash is trained for code-heavy workloads and produces longer
accepted runs on programming tasks. MTP is built into Qwen3.6
itself and works better for chat/prose. Run both, measure
acceptance rate on your real traffic, pick the winner. Genesis
empirical numbers (measured pre-archive): MTP K=3 won prose by ~30%,
DFlash N=5 won code by ~50%.

### Q: Where do I see which patches were applied at boot?

The Genesis dispatcher prints a structured log block right after
vLLM model load. Look for lines starting with
`[INFO:genesis.apply_all] [Genesis] applied: P67 ...` or
`[INFO:genesis.apply_all] [Genesis] skipped: P40 (reason)`. The
full registry status with `APPLY`/`SKIP`/`FAIL` summary is also
printed at boot end. `sndr patches plan <preset>` also previews
the decision without booting.

### Q: A patch shows "SKIP" — is something broken?

Almost always no. SKIP means either you didn't enable the patch
(default), or the dispatcher decided it doesn't apply to your
environment (wrong GPU, wrong KV dtype, wrong model family).
Patches are opt-in and self-gated. Only `[FAIL]` is a real
problem.

### Q: Can I run Genesis without Docker?

Yes. Genesis is a regular Python package and patches a vLLM
installed in the same environment. The Genesis reference
deployment uses Docker for repeatability, but bare-metal pip
works too. Just remember that text-patches mutate files inside
`site-packages/vllm/` — back them up or use a venv per Genesis
version. `sndr model-config render <key> --runtime bare_metal`
emits a venv launch script.

### Q: How do I run Genesis on Kubernetes or Proxmox?

`python3 -m sndr.cli.legacy service install <key>` wires both
backends end-to-end (audit C3 closure 2026-05-16; the `service`
verb lives on the legacy CLI surface in v12). For k8s it renders a
Deployment+Service+ConfigMap manifest under `~/.sndr/k8s/` and
applies it with `kubectl apply` when invoked with `--yes`. For
Proxmox it emits a runnable LXC bootstrap script under
`~/.sndr/proxmox/<key>.sh` that handles `pct create` + GPU
passthrough + venv bootstrap + launch.sh in one pass.

### Q: How much performance should I expect over stock vLLM?

On the Genesis reference rig (2× A5000) with the recommended patch
set: roughly **≈1.5× single-stream TPS** versus the same vLLM commit
with no patches — measured +53% on 35B and +46% on 27B (`dev148`,
2026-06-19) — plus tool-call reliability improvements that don't
show up in TPS numbers. The latest canonical single-stream figure is
**242.5 wall TPS** on the 35B PROD stack (pin `dev748`, 2026-07-04).
Your numbers will differ by GPU and workload — always benchmark. The
current canonical numbers are in [`BENCHMARKS.md`](BENCHMARKS.md).

### Q: How do I use the GUI?

```bash
sndr up      # start the engine + the GUI daemon (port 8765)
sndr open    # open http://127.0.0.1:8765 in your browser
```

The GUI (Control Center) has a first-run Setup wizard, a launch
panel, a live patch summary, and a bench panel. It is auth-gated by
default. Full manual: [`GUI.md`](GUI.md); security model:
[`GUI_SECURITY.md`](GUI_SECURITY.md). Stop everything with
`sndr down`.

### Q: Where do model weights go, and how do I download them?

`sndr pull <model>` downloads a curated model from HuggingFace and
writes a launch script tailored to your rig (`sndr list-models`
shows the catalogue; `sndr pull --models-dir <path>` overrides the
target directory). At install time, `install.sh --models-dir <path>`
(or the `GENESIS_MODELS_DIR` env var) records where your weights
live; the launcher also reads `~/.sndr/host.yaml` (manage it with
`python3 -m sndr.cli.legacy host init` / `... host doctor`) to
resolve model mounts.

### Q: What is the stable pin vs the nightly pin?

Genesis tracks vLLM with **two rolling nightly pins** (current
`0.23.1rc1.dev748+g2dfaae752` + rollback `0.23.1rc1.dev714+g09663abde`)
plus **one stable release pin** (`v0.24.0`). The nightly current pin
is what the PROD presets are validated against; the stable pin is the
conservative LTS slot for operators who prefer tagged releases over
nightlies. `sndr/pins.yaml` is the single source of truth, and
`sndr pins list` shows what your install targets.

### Q: Does it run on a single card, or without an NVIDIA GPU?

Single card: yes — `qa-qwen3.6-27b-tq-1x` is the validated 1× 24 GB
preset (78K context); see [`SINGLE_CARD.md`](SINGLE_CARD.md).
Without an NVIDIA GPU: not today. Patches graceful-skip on AMD ROCm
and Intel XPU rather than crash, but nothing is validated there, and
the performance work (Triton kernels, TurboQuant, CUDA graphs)
targets NVIDIA Ampere and newer. You can still install on a
GPU-less host for offline preset browsing and `--fake-gpus`
projections.

### Q: Is Genesis free? What does the license gate do?

Everything in this repo — `sndr/**`, tests, docs, bench data — is
**Apache 2.0**. The Ed25519 license gate in `sndr/license.py` exists
for a commercial engine overlay that is currently absent from the
public tree; it does not restrict the community tier. Details:
[`LICENSE_POLICY.md`](LICENSE_POLICY.md) and
[`CORE_ENGINE_BOUNDARY.md`](CORE_ENGINE_BOUNDARY.md). Check your
install's status with `python3 -m sndr.cli.legacy license status`.
