# Terminal cockpit (`sndr tui`)

The cockpit is the friendliest way to drive SNDR Core: **one keyboard screen**
that shows what's running and lets you serve, stop, chat and diagnose — no
commands to memorise.

```bash
sndr tui
```

If you prefer the web UI instead, that is `sndr up` then `sndr open`. The cockpit
is the no-browser, SSH-friendly equivalent.

> The cockpit needs the optional `tui` extra (the [Textual](https://textual.textualize.io/)
> library). If it isn't installed, `sndr tui` prints a one-line install hint and
> exits cleanly — never a traceback:
>
> ```bash
> pip install 'vllm-sndr-core[tui]'
> ```

## What you see

Four panes on one screen:

| Pane | Shows |
| --- | --- |
| **Engine / health** | Is a model serving? Live tok/s, KV-cache %, TTFT, running/waiting requests. |
| **Catalog** | Every preset, ranked, with a `✓` (fits your GPUs) or `✗` (doesn't) — the same ranking `sndr` and `sndr run` use. |
| **GPU / rig** | The detected card(s): count, VRAM, compute capability. |
| **Log** | A rolling status line for what you just did. |

## Keys

| Key | Does |
| --- | --- |
| `↑` / `↓` | Move the catalog cursor |
| `Enter` | **Serve** the selected preset (asks to confirm, then pulls if needed + launches; watch the engine pane come up) |
| `k` | **Stop** the selected preset's engine (asks to confirm) |
| `d` | **Doctor** — full system diagnostic (drops to the terminal, returns to the cockpit on exit) |
| `c` | **Chat** with the running engine (drops to the terminal, returns on exit) |
| `s` | **Settings** — set your model directory + Hugging Face token (applied now and remembered for next time) |
| `r` | Refresh the engine + catalog |
| `?` | Help overlay |
| `q` | Quit |

Serve and stop always ask to confirm first — pressing a key never silently
launches or kills a container.

## Beginner mode

New to all this? Hide the operator detail and keep just the essentials — the
catalog (what can I run) and the engine status:

```bash
sndr tui --lean
```

## No GPU on this box?

The cockpit still opens — plan against a card you *don't* have, to see what
would fit:

```bash
sndr tui --fake-gpus 'RTX A5000:24564:8.6'
```

## Next

- The three-command path from install to a chat prompt: [`QUICKSTART.md`](QUICKSTART.md)
- Every CLI verb in one place: [`CLI_REFERENCE.md`](CLI_REFERENCE.md)
- The web UI equivalent: `sndr up` → `sndr open` (see [`USAGE.md`](USAGE.md))
