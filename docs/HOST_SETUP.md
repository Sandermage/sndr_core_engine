# Host setup — the `~/.sndr/host.yaml` manual

Every launch config in this repo references host paths symbolically —
`${models_dir}`, `${hf_cache}`, `${plugin_src}` — so the same preset
YAML renders on any operator's rig. The file that resolves those
symbols into real directories is **`host.yaml`**: a small per-host
mapping that the launch renderer reads at render time
(`sndr/model_configs/host.py: load_host_config()`).

This manual covers where the file lives, what every key means, how
auto-detection and env overrides interact, the CLI verbs that manage
it, and the failure modes that actually bit us — including the
2026-07-04 stale-`plugin_src` incident.

## Prerequisites

- sndr-platform installed (`install.sh` or `pip install -e .` — see
  [`INSTALL.md`](INSTALL.md)).
- You know where your model weights and caches live on this host.

## Where the file lives

Resolution order (first hit wins; from
`sndr/model_configs/host.py: _default_host_yaml_path()`):

1. `$SNDR_HOME/host.yaml` — canonical env override
2. `$GENESIS_HOME/host.yaml` — legacy alias, honored for back-compat
3. `~/.sndr/host.yaml` — canonical default
4. `~/.genesis/host.yaml` — legacy default (read-fallback only; new
   files are always written to the canonical layout)

The `sndr host` CLI verbs additionally honor `$SNDR_HOST_YAML` as a
direct file-path override — useful for testing a candidate file
without touching the live one.

## The `paths:` schema

`host.yaml` is a single top-level `paths:` mapping. The keys, their
semantics, and the container mount target each one feeds (the
canonical 5-slot mount schema from the builtin hardware YAMLs):

| Key | What it points at | Container target | Mode |
| --- | --- | --- | --- |
| `models_dir` | Model weights root (HF-format checkpoint dirs) | `/models` | ro |
| `hf_cache` | HuggingFace cache root (downloaded files) | `/root/.cache/huggingface` | ro |
| `triton_cache` | Triton kernel cache — persist to skip a +30–60 s recompile on every boot | `/root/.triton/cache` | rw |
| `compile_cache` | vLLM `torch.compile` cache — persist compile artifacts across restarts | `/root/.cache/vllm/torch_compile_cache` | rw |
| `plugin_src` | The sndr **repo ROOT** (the dir with the root `pyproject.toml`) | `/plugin` | ro |
| `sndr_src` | The repo's `sndr/` **package dir** — RO overlay source for launchers that bind-mount the package into `dist-packages/sndr` directly | (legacy/manual launchers) | ro |
| `cache_root` | Parent of per-config cache subdirs (e.g. `triton-cache-<config>` for bench reproducibility) | (per-config) | rw |

Two keys deserve emphasis because getting them wrong disables the
whole patch stack silently:

- **`plugin_src` must be the repo root**, NOT the empty legacy
  `tools/genesis_vllm_plugin` subdir. The renderer bind-mounts it at
  `/plugin` and (under `SNDR_DEV_INSTALL_PLUGIN=1`) pip-installs it
  editable inside the container, so the `vllm.general_plugins`
  entry-point (`genesis_v7 = sndr.plugin:register`) registers
  in-process and runtime monkey-patches fire in `vllm serve`. The
  rendered launcher even asserts this at boot and prints a pointed
  error if `/plugin` is not the repo root.
- **`sndr_src` must end at the v12 `sndr/` package dir**
  (`.../genesis-vllm-patches/sndr`), not the retired
  `vllm/sndr_core` overlay path. The legacy key name `genesis_src` is
  aliased onto `sndr_src` at load time, so pre-v12 host.yaml files
  keep working unchanged.

### Env-var overrides

Each key can be pre-empted by an env var. An override only wins when
the env is set to an **absolute path that exists as a directory** —
a missing or relative path is silently ignored (the loader falls back
to probing), so double-check the value actually resolves.

| Key | Env vars (first set + valid wins) |
| --- | --- |
| `models_dir` | `SNDR_MODELS_DIR`, `GENESIS_MODELS_DIR` |
| `hf_cache` | `SNDR_HF_CACHE`, `HF_HOME`, `HUGGINGFACE_HUB_CACHE` |
| `triton_cache` | `SNDR_TRITON_CACHE`, `GENESIS_TRITON_CACHE` |
| `compile_cache` | `SNDR_COMPILE_CACHE`, `GENESIS_COMPILE_CACHE` |
| `sndr_src` | `SNDR_CORE_SRC`, `GENESIS_SRC` |
| `plugin_src` | `SNDR_PLUGIN_SRC`, `GENESIS_PLUGIN_SRC` |
| `cache_root` | `SNDR_CACHE_ROOT`, `GENESIS_CACHE_ROOT` |

### Auto-detection

`install.sh` (and first run) auto-detects paths by probing
OS-conventional locations, first-found wins: `models_dir` tries
`/srv/models`, `/data/models`, `/opt/models`, `/var/lib/models`,
`~/models`, ...; caches try `~/.cache/triton`,
`~/.cache/vllm/torch_compile_cache`, `~/.sndr/cache/...`;
`sndr_src`/`plugin_src` try `~/genesis-vllm-patches` and
`/opt/genesis-vllm-patches` checkouts. Anything not found is omitted —
you fill it in by hand. Re-run detection any time:

```bash
python3 -c "from sndr.model_configs.host import detect_and_save; detect_and_save()"
```

## A complete worked example

```yaml
# ~/.sndr/host.yaml — operator host profile for the sndr launcher.
paths:
  models_dir: /srv/models
  hf_cache: /home/operator/.cache/huggingface
  triton_cache: /home/operator/.cache/triton
  compile_cache: /home/operator/.cache/vllm/torch_compile_cache
  sndr_src: /home/operator/genesis-vllm-patches/sndr
  plugin_src: /home/operator/genesis-vllm-patches
```

Rendered into the launcher (`sndr launch <preset> --dry-run` output),
those values become the mount block:

```text
docker run -d \
  --name vllm-qwen3.6-35b-a3b-fp8 \
  ...
  -v /srv/models:/models:ro \
  -v /home/operator/.cache/huggingface:/root/.cache/huggingface:ro \
  -v /home/operator/.cache/triton:/root/.triton/cache \
  -v /home/operator/.cache/vllm/torch_compile_cache:/root/.cache/vllm/torch_compile_cache \
  -v /home/operator/genesis-vllm-patches:/plugin:ro \
  ...
```

> **Schema gotcha:** the keys MUST sit under a top-level `paths:`
> mapping. A flat file (`models_dir:` at the top level) is silently
> ignored and the launcher falls back to the default candidate dirs —
> this cost ~30 minutes of debugging on 2026-05-22, so the loader now
> prints a loud `[host.yaml] WARN: top-level path-like key(s) ...`
> to stderr when it detects the mistake.

## CLI verbs — `sndr host`

The host profile manager lives on the legacy CLI surface (it was not
promoted to the `sndr` top level in v12; see the Legacy appendix in
[`CLI_REFERENCE.md`](CLI_REFERENCE.md)):

```bash
python3 -m sndr.cli.legacy host detect   # probe host (GPUs, dirs, runtimes); writes nothing
python3 -m sndr.cli.legacy host init     # write a starter host.yaml from detection (--force, --path)
python3 -m sndr.cli.legacy host doctor   # validate the current host.yaml (--json)
python3 -m sndr.cli.legacy host edit     # open in $EDITOR (--print = just print the path)
python3 -m sndr.cli.legacy host show     # print the current file content
```

(The soft-deprecated `genesis host ...` console alias runs the same
tree.) `init` refuses to overwrite an existing file without
`--force`, and its output tells you the two keys detection cannot
guess:

```text
  ✓ wrote /home/operator/.sndr/host.yaml
    next steps:
      1. fill in sndr_src + plugin_src paths (operator-specific)
      2. validate: sndr host doctor
      3. launch:   sndr launch <preset>
```

`doctor` checks that the file parses, that the three launch-critical
keys (`models_dir`, `sndr_src`, `plugin_src`) are present and exist
(FAIL if missing from the file, WARN if the path does not exist), and
that the optional cache keys resolve. Exit codes: `0` clean, `1` any
FAIL, `2` warnings only. A fresh unfilled file looks like this:

```text
  ┌──────────────────────────────┐
  │  sndr host doctor            │
  │  4 checks · 3 fail · 0 warn  │
  └──────────────────────────────┘
  ✓ [PASS] host_yaml_present        /home/operator/.sndr/host.yaml
  ✗ [FAIL] paths.models_dir         missing — launcher cannot resolve mounts
  ✗ [FAIL] paths.sndr_src           missing — launcher cannot resolve mounts
  ✗ [FAIL] paths.plugin_src         missing — launcher cannot resolve mounts
```

## Verifying end-to-end

The real test is a render. A dry run resolves every `${var}` through
your host.yaml and prints the full launcher script without starting
anything:

```bash
sndr launch prod-qwen3.6-35b-balanced --dry-run
```

Expect a `docker run` block whose five `-v` lines contain your real
paths (see the worked example above). A `${var}` that survives into
the output, or an audit error like the one below, means the key is
missing from `paths:`:

```text
ERROR (R-019): symbolic mounts reference ['unknwn_dir'] but host.yaml only
defines ['models_dir', 'hf_cache', 'triton_cache', 'compile_cache',
'sndr_src', 'plugin_src']. Add these vars to ~/.sndr/host.yaml
`paths:` section.
```

## Cautionary tale — the 2026-07-04 stale `plugin_src`

During the dev748 fleet-validation window (2026-07-04), the rig's
`host.yaml` still carried a `plugin_src` pointing at a stale pre-v12
checkout layout. Every rendered launcher booted a container whose
`/plugin` mount had no installable `sndr` package, so the in-container
editable install found nothing to register and the boot loop died with:

```text
ModuleNotFoundError: No module named 'sndr'
```

Every render crashed the same way — the preset YAMLs, the pin, and the
image were all fine; the single stale line in `host.yaml` took out the
whole launch path. The fix took one minute once diagnosed:

```bash
# point plugin_src at the CURRENT repo root, sndr_src at its sndr/ package dir
$EDITOR ~/.sndr/host.yaml
python3 -m sndr.cli.legacy host doctor      # expect 0 fail
sndr launch <preset> --dry-run              # confirm the -v /plugin line
```

Lessons encoded since: `host doctor` FAILs on a missing `plugin_src`,
the rendered launcher asserts the entry-point registration at boot
with an explicit "is /plugin the sndr repo ROOT?" message, and the
default probe lists were retargeted to the v12 layout (commits
`13123814`, `ef0df091`). If you move or re-clone the repo, re-check
`host.yaml` — it does not follow you.

## Common failure modes

| Symptom | Cause | Fix |
| --- | --- | --- |
| `No module named 'sndr'` at container boot | `plugin_src` stale / points at `tools/genesis_vllm_plugin` | Point at the repo root; see the cautionary tale above |
| Render uses `/opt/models` instead of your dir | Flat schema (no `paths:` block) or key missing → probe fallback | Wrap keys under `paths:`; heed the stderr WARN |
| `R-019` unresolved `${var}` at validate time | Key referenced by the config absent from `host.yaml` | Add the key to `paths:` |
| Env override "doesn't work" | Env points at a missing or relative path — strict validation ignores it | Use an absolute, existing dir |
| +30–60 s boot penalty every restart | `triton_cache` / `compile_cache` unset (no persistence) | Set both keys; keep the mounts rw |
| Old rig works, new checkout fails | `host.yaml` still points at the old clone | Update `sndr_src` + `plugin_src`, run `host doctor` |

## See also

- [`INSTALL.md`](INSTALL.md) — the installer that writes the first host.yaml
- [`MODEL_CONFIG_LAUNCHER.md`](MODEL_CONFIG_LAUNCHER.md) — symbolic mounts + render CLI
- [`ADDING_MODELS.md`](ADDING_MODELS.md) — weights layout under `models_dir`
- [`OPERATIONS.md`](OPERATIONS.md) — day-2 runbook
- [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) — boot failures beyond mounts
