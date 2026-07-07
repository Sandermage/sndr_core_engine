# Remote engine — drive a rig from anywhere (client mode)

This is the canonical reference for **client mode**: running the `sndr` CLI,
the GUI Control Center, and the persistent memory *against an engine that
lives on another machine*. If your laptop can't run the engine (Mac, or
Windows without a GPU), or you simply keep the GPU box in a closet, this is
how you point everything at it.

> **The honest hardware truth.** The SNDR Core engine runs on **Linux +
> CUDA + Docker** only — the reference rig is 2× RTX A5000 / 3090 (Ampere
> `sm_86`), one heavy model at a time. macOS and Windows **cannot** run the
> engine. What they *can* do — fully — is run the `sndr` CLI, the GUI daemon
> (`:8765`), and the memory client as a **remote control** for a Linux rig.
> Per-OS front doors: [`RUN_ON_MAC.md`](RUN_ON_MAC.md) ·
> [`RUN_ON_WINDOWS_WSL.md`](RUN_ON_WINDOWS_WSL.md) ·
> [`RUN_ON_LINUX.md`](RUN_ON_LINUX.md) (full local stack).

## The triplet

Everything client-mode needs collapses to three environment variables:

| Variable | Example | What it points at |
| --- | --- | --- |
| `SNDR_OPENAI_BASE_URL` | `http://<rig>:8102/v1` | The engine's OpenAI-compatible API on the rig. `<rig>` is the rig's hostname or LAN IP; `8102` is the PROD serving port. |
| `SNDR_ENGINE_API_KEY` | `genesis-local` | The engine's API key. `genesis-local` is the shipped default; whatever the rig launched with (`--api-key`) is what you paste here. |
| `GENESIS_MEMORY_DSN` | `postgresql://genesis:<pw>@<rig>:55432/genesis_memory` | The rig's pgvector Postgres for persistent neural-graph memory. Optional — see [Memory DSN behavior](#memory-dsn-behavior) below. |

Set them once (a `.env` next to your clone, or exported in your shell) and the
CLI, the GUI, and `sndr mem` all read the same three values.

### Where each value comes from

- **`SNDR_OPENAI_BASE_URL`** — the rig's address plus the engine port. The
  PROD 35B lane serves on **`:8102`** (see the [port story](#the-8000-vs-8102-port-story)
  below for why it is not `:8000`). Always end the URL in `/v1`.
- **`SNDR_ENGINE_API_KEY`** — the key the engine was booted with. Genesis
  ships **`genesis-local`** as the default; if the operator overrode
  `--api-key` on the launch, use that string. This is the single most common
  cause of a "can't find engine" symptom — see [401](#the-401-story-missing-bearer)
  below.
- **`GENESIS_MEMORY_DSN`** — the connection string for the rig's
  `genesis-memory-db` pgvector container (default dim 256 = the built-in hash
  embedder; schema tables `mem_node` / `mem_edge`). Deployment recipe for that
  container: [`memory/MANUAL.md`](memory/MANUAL.md).

> **Shell env wins.** If a variable is exported in your shell, it overrides
> the value in a `.env` file and the value `sndr remote setup` wrote. This is
> deliberate — a one-off `SNDR_OPENAI_BASE_URL=… sndr chat` beats your saved
> default — but it also means a stale export in your `~/.zshrc` silently wins
> over the `.env` you just edited. When a value "won't take", check
> `env | grep -E 'SNDR_|GENESIS_MEMORY'` first.

## How the CLI consumes it

```bash
# 1. one-shot setup — writes the base URL (and prompts for the key) into your
#    client profile so you don't re-type it
sndr remote setup http://<rig>:8102/v1

# 2. start ONLY the GUI daemon locally; do NOT try to launch an engine
sndr up --no-engine

# 3. chat straight against the remote engine
sndr chat
```

- **`sndr remote setup <base-url>`** records the remote engine as your default
  target (base URL + key) so subsequent commands need no flags.
- **`sndr up --no-engine`** starts the local GUI daemon **without** attempting
  to boot an engine — because the engine already runs on the rig. The daemon
  then talks to `SNDR_OPENAI_BASE_URL`. (On a Mac/Windows client you always
  want `--no-engine`; there is no local engine to start.)
- **`sndr chat`** opens a terminal chat against whatever
  `SNDR_OPENAI_BASE_URL` + `SNDR_ENGINE_API_KEY` resolve to — remote or local,
  it is the same command.

A raw `curl` works too, and shows exactly what the CLI sends under the hood —
note the **`Authorization: Bearer genesis-local`** header, which is not
optional:

```bash
curl -s -X POST http://<rig>:8102/v1/chat/completions \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer genesis-local" \
    -d '{"model":"qwen3.6-35b-a3b",
         "messages":[{"role":"user","content":"Say hello in one word."}],
         "max_tokens":16,"temperature":0}'
```

## How the GUI consumes it

The GUI daemon (`sndr-daemon`, port **`:8765`**) reads the same triplet from
its environment:

- It probes the engine's `/v1/models` at `SNDR_OPENAI_BASE_URL` using
  `SNDR_ENGINE_API_KEY`. A keyless probe against a keyed engine returns
  `401`, which the daemon reads as **"no engine"** and then falls back to an
  empty `:8000` — the classic "GUI says no engine" trap. Passing the key fixes
  it.
- Its Memory panel uses `GENESIS_MEMORY_DSN` to reach pgvector; unset means an
  ephemeral in-memory store (below).

The full daemon config, security model, and screenshots are in
[`GUI.md`](GUI.md); the typed daemon route map is in
[`PRODUCT_API.md`](PRODUCT_API.md).

## Memory DSN behavior

The memory backend is chosen **entirely** by whether `GENESIS_MEMORY_DSN` is
set:

| `GENESIS_MEMORY_DSN` | Backend | Persistence |
| --- | --- | --- |
| **set** (points at pgvector) | Postgres + pgvector (`PostgresStore`) | **Persistent** — nodes/edges survive restarts; this is what you want for a real memory. |
| **unset** | `InMemoryStore` (RAM) | **Ephemeral** — every daemon restart starts empty. Fine for a quick try, useless as a long-term brain. |

Two gotchas the rig launcher already handles, worth knowing when you self-host
the memory container: the DSN must point at the `genesis-memory-db` pgvector
instance (dim 256, tables `mem_node` / `mem_edge`), and `psycopg` is **not** in
the vLLM base image — the daemon `pip install psycopg[binary]>=3.1` at boot,
otherwise `PostgresStore` import fails and it *silently* falls back to
in-memory. Full deployment: [`memory/MANUAL.md`](memory/MANUAL.md).

## The `:8000` vs `:8102` port story

You will see both ports in the wild:

- **`:8000`** is vLLM's stock default and what a bare `vllm serve` binds. Some
  older GUI engine-detect paths still probe `:8000` first.
- **`:8102`** is where the Genesis **PROD 35B lane actually serves** on the
  reference rig. When you drive a remote rig, `SNDR_OPENAI_BASE_URL` must name
  the port the engine really listens on — **`:8102`** for the canonical PROD
  stack. If you launched a bring-up engine on the vanilla `:8000`, point the
  URL there instead. The launcher varies the port, so always confirm with the
  rig operator or `docker ps` on the rig rather than assuming.

## The 401 story (missing Bearer)

By far the most common client-mode failure: the engine is up and healthy, but
every request comes back `401 Unauthorized` — and the GUI reports **"no
engine"**. The engine is **keyed**. The fix is to send the key:

- CLI / curl: `Authorization: Bearer genesis-local` (or your override).
- GUI daemon: set `SNDR_ENGINE_API_KEY=genesis-local`.
- Env: make sure `SNDR_ENGINE_API_KEY` is actually exported / in `.env` and
  not shadowed by an empty shell export (see *shell env wins* above).

`genesis-local` is the shipped default key. More failure modes and their cures
are in [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).

## See also

- [`RUN_ON_MAC.md`](RUN_ON_MAC.md) — the Mac client front door (uses this triplet).
- [`RUN_ON_WINDOWS_WSL.md`](RUN_ON_WINDOWS_WSL.md) — Windows: GPU passthrough or client mode.
- [`RUN_ON_LINUX.md`](RUN_ON_LINUX.md) — run the **full** stack locally on a Linux + CUDA box.
- [`GUI.md`](GUI.md) · [`PRODUCT_API.md`](PRODUCT_API.md) · [`memory/MANUAL.md`](memory/MANUAL.md).
