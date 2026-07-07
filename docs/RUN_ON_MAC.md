# Run on a Mac — drive a rig from your laptop

**Your Mac cannot run the engine.** The SNDR Core engine needs **Linux +
CUDA + Docker** and an NVIDIA GPU — Apple Silicon and Intel Macs have none of
that, and there is no native-Mac engine (and won't be one). That is the honest
situation, stated up front so you don't spend an afternoon fighting it.

**What your Mac *can* do — fully:** run the `sndr` CLI, the GUI Control Center
(`:8765`), and the memory client as a **remote control** for a Linux rig. You
chat, launch presets, watch the patch summary, and browse the memory graph from
macOS; the tokens are generated on the rig. If you have a Linux + CUDA box on
your LAN (or a cloud GPU host), this is a first-class way to use it.

> No rig yet? You need a Linux machine with an NVIDIA GPU to be the engine —
> set that up with [`RUN_ON_LINUX.md`](RUN_ON_LINUX.md), then come back here to
> point your Mac at it.

## The client path (three commands)

```bash
# 1. install the CLI + GUI in client profile (no engine, no CUDA needed)
curl -sSL https://raw.githubusercontent.com/Sandermage/sndr_core_engine/main/install.sh | bash -s -- --client

# 2. point it at your rig's engine (writes the base URL + prompts for the key)
sndr remote setup http://<rig>:8102/v1

# 3. start the local GUI daemon WITHOUT an engine, then chat
sndr up --no-engine
sndr chat
```

`<rig>` is your rig's hostname or LAN IP; `:8102` is the PROD engine port. The
engine is keyed — the default key is **`genesis-local`** (paste whatever the
rig launched with). `sndr up --no-engine` is the key flag on a client: it
starts only the GUI daemon and never tries to boot a local engine.

## The `.env` alternative

Prefer a file over `sndr remote setup`? Copy the example and fill in the three
values (the **remote-client triplet**):

```bash
cp .env.example .env      # then edit .env
```

```bash
# .env — the three values that define client mode
SNDR_OPENAI_BASE_URL=http://<rig>:8102/v1
SNDR_ENGINE_API_KEY=genesis-local
GENESIS_MEMORY_DSN=postgresql://genesis:<pw>@<rig>:55432/genesis_memory   # optional
```

- **`SNDR_OPENAI_BASE_URL`** — the rig's engine, ending in `/v1`.
- **`SNDR_ENGINE_API_KEY`** — the engine key (`genesis-local` by default). Skip
  it and every request is `401` and the GUI reports "no engine".
- **`GENESIS_MEMORY_DSN`** — optional; set it to the rig's pgvector for
  persistent memory, leave it unset for an ephemeral in-memory store that
  empties on restart.

> **Shell env wins.** A variable exported in your shell (e.g. in `~/.zshrc`)
> overrides both `.env` and what `sndr remote setup` saved. If a value "won't
> take", run `env | grep -E 'SNDR_|GENESIS_MEMORY'` and clear the stale export.

## What you get on the Mac

- `sndr chat` — terminal chat against the remote engine.
- `sndr up --no-engine` → `http://127.0.0.1:8765` — the full GUI Control Center
  in your browser, driving the remote engine (launch presets, live patch
  summary, benches, the 🧠 memory graph).
- `sndr mem …` — remember / recall / search against the rig's memory.

The one thing you cannot do is `sndr up` *with* a local engine — there is no
CUDA on the Mac to run it. Always pass `--no-engine`.

## The deep reference

Everything about client mode — where each of the three values comes from, how
the CLI and GUI consume them, the memory-DSN persistence table, the `:8000` vs
`:8102` port story, and why a missing `Bearer genesis-local` causes a `401` —
lives in **[`REMOTE_ENGINE.md`](REMOTE_ENGINE.md)**.

## See also

- [`REMOTE_ENGINE.md`](REMOTE_ENGINE.md) — the canonical client-mode reference.
- [`RUN_ON_LINUX.md`](RUN_ON_LINUX.md) — stand up the rig that will be your engine.
- [`RUN_ON_WINDOWS_WSL.md`](RUN_ON_WINDOWS_WSL.md) — the Windows equivalent of this page.
- [`GUI.md`](GUI.md) — the Control Center in depth.
- [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) — `401`, "no engine", memory-empty.
