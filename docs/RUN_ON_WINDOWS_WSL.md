# Run on Windows — WSL2 with a GPU, or client mode

There is **no native-Windows engine**, and there won't be one — the SNDR Core
engine needs **Linux + CUDA + Docker**. On Windows you have two honest lanes,
depending on whether the machine has an NVIDIA GPU you can pass through:

- **Lane A — WSL2 + NVIDIA GPU passthrough.** Your Windows box *has* a
  supported NVIDIA card. WSL2 gives you a real Linux userland with CUDA, so you
  run the **full engine** inside WSL2 exactly like a native Linux rig.
- **Lane B — no usable GPU.** No NVIDIA card (or a laptop iGPU). You run the
  `sndr` CLI + GUI as a **remote client** and drive a Linux rig elsewhere,
  exactly like a Mac.

Pick your lane below.

## Lane A — WSL2 + NVIDIA GPU passthrough

This is the full local stack, running inside a WSL2 Linux distro.

**Prerequisites (on Windows):**

1. Recent NVIDIA Windows driver (the WSL CUDA passthrough is built into modern
   drivers — do **not** install a separate CUDA driver *inside* WSL).
2. WSL2 with a Linux distro (Ubuntu 24.04 recommended) and Docker with the
   NVIDIA container toolkit inside that distro.
3. Verify the GPU is visible inside WSL: `nvidia-smi` from the WSL shell must
   list your card.

**Then, inside the WSL2 shell, follow [`RUN_ON_LINUX.md`](RUN_ON_LINUX.md)
verbatim** — it *is* Linux from here on:

```bash
curl -sSL https://raw.githubusercontent.com/Sandermage/sndr_core_engine/main/install.sh | bash
sndr quickstart        # auto-detect GPU → fit a preset → download → boot → GUI
```

> **WSL2 quirk (handled for you).** WSL2's GPU stack needs a
> `gptq_marlin_repack` environment override for the quantized-MoE kernels to
> load correctly. `install.sh` **auto-detects WSL2 and writes that override**
> for you — you don't set it by hand. If you install the plugin some other way,
> this override is the one WSL-specific thing to carry over; see
> [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).

Everything else — presets, the one-heavy-model-at-a-time rule, `sndr down` as
the safe stop — is identical to the Linux front door.

## Lane B — no usable GPU (client mode)

No NVIDIA card to pass through? Don't fight it — drive a Linux rig remotely,
exactly like a Mac. Install the client profile and point it at the rig:

```bash
# in WSL2 or Git-Bash / PowerShell with the CLI installed (client profile)
sndr remote setup http://<rig>:8102/v1
sndr up --no-engine
sndr chat
```

The three values that define client mode (the **remote-client triplet**):

```bash
SNDR_OPENAI_BASE_URL=http://<rig>:8102/v1
SNDR_ENGINE_API_KEY=genesis-local
GENESIS_MEMORY_DSN=postgresql://genesis:<pw>@<rig>:55432/genesis_memory   # optional
```

`<rig>` is the rig's hostname or LAN IP; the engine is keyed (`genesis-local`
by default — a missing key surfaces as `401` / "no engine"). The full walk —
where each value comes from, GUI vs CLI consumption, memory persistence, the
`:8000` vs `:8102` port story — is [`REMOTE_ENGINE.md`](REMOTE_ENGINE.md), and
the Mac page [`RUN_ON_MAC.md`](RUN_ON_MAC.md) covers the same client flow
step-by-step.

> **Shell env wins.** An exported shell variable overrides `.env` and the
> value `sndr remote setup` saved. If a value won't take, check
> `env | grep -E 'SNDR_|GENESIS_MEMORY'`.

## Which lane am I in?

| Situation | Lane |
| --- | --- |
| Desktop / workstation with a supported NVIDIA card | **A** — WSL2 + passthrough, follow [`RUN_ON_LINUX.md`](RUN_ON_LINUX.md) |
| Laptop with only an integrated GPU, or no NVIDIA card | **B** — client mode, see [`REMOTE_ENGINE.md`](REMOTE_ENGINE.md) |
| Have a separate Linux GPU box you want to use | **B** from Windows + [`RUN_ON_LINUX.md`](RUN_ON_LINUX.md) on the box |

## See also

- [`RUN_ON_LINUX.md`](RUN_ON_LINUX.md) — the full local stack (Lane A follows this).
- [`REMOTE_ENGINE.md`](REMOTE_ENGINE.md) — the canonical client-mode reference (Lane B).
- [`RUN_ON_MAC.md`](RUN_ON_MAC.md) — the same client flow, Mac-flavored.
- [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) — WSL2 GPU visibility, `401`, kernel-load issues.
