# SNDR Control Center (GUI)

The SNDR Control Center is a read-only operator dashboard over the SNDR Product
API. It turns the CLI/runtime/patch/config/evidence surface into a browsable
control plane: catalog, preset recommendation, launch planning, diagnostics,
patches, benchmarks, evidence, clients, and reports.

The GUI is a **client of a stable API**, never a wrapper that parses CLI stdout.
The same Product API backs the CLI and the GUI.

```text
React + TypeScript UI  ->  sndr gui-api (FastAPI daemon)  ->  Product API  ->  sndr_core
```

## What it does today

- Read-only by design. It never writes V2 YAML, the patch registry, or runtime
  artifacts, and it never starts containers or opens SSH on its own.
- Side-effecting actions are **plan-before-apply**: applies produce dry-run jobs
  with the exact commands an operator would run, not real execution.
- Operator-local writes are limited to your install dir (`$SNDR_HOME`, default
  `~/.sndr`): host profiles, GUI settings, and generated report bundles.

## Install

The GUI daemon needs the optional `gui-api` extra (FastAPI + Uvicorn):

```bash
pip install "vllm-sndr-core[gui-api]"
```

The web assets are built from `gui/web` with Node:

```bash
cd gui/web
npm ci
npm run build      # production assets in gui/web/dist
```

## Run — integrated single-process mode (recommended)

Build the UI into the package once, then the daemon serves **both the UI and the
API on one port** (no separate Node server, same-origin, no CORS hop):

```bash
make gui-build     # npm ci && build, copies dist → vllm/sndr_core/product_api/web_static
python3 -m vllm.sndr_core.cli gui-api --host 127.0.0.1 --port 8765
# open http://127.0.0.1:8765
```

The built assets are bundled into the wheel, so a `pip install` of the package
serves the UI directly. Override the served assets dir with `SNDR_GUI_STATIC`.

## CLI flags (`sndr gui-api`)

```bash
python3 -m vllm.sndr_core.cli gui-api [--host H] [--port P] [--log-level L] [--enable-apply] [--open]
```

| Flag | Default | Purpose |
| --- | --- | --- |
| `--host` | `127.0.0.1` | Bind address. Use `0.0.0.0` only behind a trusted boundary **with auth on**. |
| `--port` | `8765` | Bind port. |
| `--log-level` | `info` | uvicorn log level (`critical`/`error`/`warning`/`info`/`debug`/`trace`). |
| `--enable-apply` | off | Opt into **real** service-action/launch execution (otherwise dry-run). Also set by `SNDR_ENABLE_APPLY=1`. |
| `--open` | off | Open the served UI in a browser shortly after start. |

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `SNDR_HOME` | `~/.sndr` | Operator-local state: host profiles, settings, reports, **auth store** (`$SNDR_HOME/auth`). Mount as a volume in a container. |
| `SNDR_GUI_STATIC` | packaged `web_static` → repo `gui/web/dist` | Override the directory of built UI assets the daemon serves. |
| `SNDR_ENABLE_APPLY` | `0` | Enable real execution of mutating actions (same as `--enable-apply`). |
| `SNDR_GUI_TOKEN` | _(unset)_ | Legacy shared bearer token. When set, `/api/v1/*` requires it (still works alongside user auth). |
| `SNDR_AUTH` | `auto` | User authentication: `on` / `off` / `auto` (auto = on when non-loopback, accounts exist, or a token is set). |
| `SNDR_ADMIN_PASSWORD` | _(generated once)_ | Initial admin password on first bootstrap; otherwise auto-generated and printed once to the log. |
| `SNDR_AUTH_SESSION_TTL` | `86400` | Session lifetime in seconds. |
| `SNDR_AUTH_LOCK_THRESHOLD` / `_WINDOW` / `_SECONDS` | `8` / `300` / `900` | Brute-force throttle: failures before a temporary lockout, the counting window, and the lockout duration (seconds). |
| `SNDR_PUBLIC_URL` | `http://<host>:8765` | Public base URL — used for OAuth redirect URIs and `secure` cookies on HTTPS. |
| `SNDR_AUTH_PAM` | `0` | Enable system-account login via PAM (host deployments; needs the `gui-auth-pam` extra). |
| `SNDR_OAUTH_GOOGLE_CLIENT_ID` / `_SECRET` | _(unset)_ | Enable Google sign-in when both are set. |
| `SNDR_OAUTH_APPLE_CLIENT_ID` / `_SECRET` | _(unset)_ | Enable Apple sign-in when both are set. |
| `SNDR_IN_CONTAINER` | auto-detected | Force container-context detection (otherwise inferred from `/.dockerenv`, cgroups). |

The full authentication model, OAuth setup, container persistence and endpoint
list live in [`docs/GUI_SECURITY.md`](GUI_SECURITY.md).

## Run — dev mode (hot reload)

During frontend development, run the Vite dev server alongside the daemon:

```bash
python3 -m vllm.sndr_core.cli gui-api --host 127.0.0.1 --port 8765
cd gui/web && npm run dev        # http://127.0.0.1:5173
```

In dev the UI calls the API at `http://127.0.0.1:8765` (CORS-allowed). When the
UI is served by the daemon it defaults to the **same origin** automatically.
Override via the top-bar input, the `VITE_SNDR_API_BASE` build var, or the
`sndr.gui.apiBase` localStorage key.

## Run — remote desktop over SSH tunnel (recommended remote mode)

The GPU host is usually Linux; your laptop may be macOS or Windows. Do **not**
expose the daemon on the LAN. Keep it bound to `127.0.0.1` on the host and
forward a port over SSH:

```bash
# on your laptop
ssh -L 8765:127.0.0.1:8765 user@gpu-host
# then open the UI pointed at http://127.0.0.1:8765
```

The Hosts screen stores SSH host profiles (operator-local) and shows a copyable
tunnel command. It never opens the tunnel for you — that stays an explicit step.

## Authentication (server deployments)

For a shared/server install, enable user authentication. The simplest path:

```bash
SNDR_AUTH=on SNDR_ADMIN_PASSWORD="change-me" \
  python3 -m vllm.sndr_core.cli gui-api --host 0.0.0.0 --port 8765
```

On first start an **admin account is bootstrapped** (username = the system user
running the daemon; password from `SNDR_ADMIN_PASSWORD`, else generated and
printed once to the log). The UI then shows a sign-in screen. From **Advanced →
Admin** an admin can create/remove users and everyone can change their password
and enrol **TOTP two-factor**. Optional system login (PAM) and Google/Apple
sign-in are configured via environment variables.

Auth state (accounts, 2FA, session key) persists under `$SNDR_HOME/auth` — mount
that path as a volume so it survives container restarts. Full details, the OAuth
setup, the PAM-in-container caveat and the endpoint list:
[`docs/GUI_SECURITY.md`](GUI_SECURITY.md).

## Screens

| Screen | Purpose |
| --- | --- |
| Overview | Mission control: platform, catalog health, runtime environment/version, coverage |
| Setup | First-run host bootstrap wizard (detect → mode → preset → validate → plan) |
| Hosts | Local/remote host profiles and runtime target matrix |
| Models | Catalog **summary strip + per-model key-facts**, identity/provenance, **capabilities + generation/sampling config**, requirements, hardware fit, patch matrix, cache + Hugging Face search/download |
| Configs | Graphical V2 composition editor (model/hardware/profile/preset) + per-element editor |
| Presets | Catalog, selected card, workload rules, policy graph |
| Launch Plan | Recommendation builder, backend-owned plan, gates, artifacts, CLI mirror |
| Services | Lifecycle planner (read-only/dry-run), **live engine status + live Prometheus metrics with trend sparklines**, engine & dependencies, capability contracts |
| Doctor | Aggregated diagnostics, readiness gates, registry coverage |
| Patches | Registry summary, inventory, lifecycle, bundles, upstream diff, per-patch explain |
| Benchmarks | Baseline, **live benchmark + A/B (real TTFT/TPOT/throughput from the engine)**, capability status, proof coverage, run plan/commands |
| Evidence | Evidence refs, proof artifact status, coverage breakdown, bundle commands |
| Clients | **Live engine status**, **Playground (streaming or one-shot prompt)**, OpenAI-compatible endpoints, copy-paste clients, auth |
| Reports | Generate redacted snapshot bundles into `$SNDR_HOME/reports/` |
| Advanced | Appearance, API/schema explorer, admin matrix, **account & security (password + 2FA)**, **user management (admin)**, feature contracts, config draft, CLI mirror |

## Live updates

The daemon exposes a Server-Sent Events stream at `GET /api/v1/events` plus a
pollable feed at `GET /api/v1/events/recent`. The UI consumes the SSE stream
when the daemon is open and falls back to authenticated polling when a token is
configured (browsers cannot attach an Authorization header to `EventSource`).

## Reports

The Reports screen generates a redacted snapshot bundle (`snapshot.json` +
`summary.md`) into `$SNDR_HOME/reports/<id>/`. Redaction strips your home path
and the GUI token by default. Nothing is written to the repo or a remote host.

## Verifying it works

```bash
curl http://127.0.0.1:8765/api/v1/health        # -> {"status":"ok",...,"read_only":true}
curl http://127.0.0.1:8765/openapi.json | head  # OpenAPI document
```

Frontend checks:

```bash
cd gui/web
npm run typecheck
npm run check:api      # fails if the client/daemon API contract drifts
npm run test:e2e       # Playwright smoke (daemon + dev server must be running)
```

## See also

- `docs/PRODUCT_API.md` — the read-only API contract and full route map.
- `docs/GUI_SECURITY.md` — bind, auth (accounts/2FA/OAuth/PAM), persistence,
  redaction, and dangerous-action policy.
- `docs/GUI_ROADMAP.md` — what is done and what remains (prioritized).
