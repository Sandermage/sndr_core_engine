# Container Management in the SNDR Control Center — Design

**Date:** 2026-06-02
**Status:** approved (Approach A)
**Author:** Sander + Claude

## Problem

1. **Bug:** the GUI reports "docker: not installed" on a node even though vLLM and
   the whole stack run in containers. The node management daemon is itself a
   sidecar container with no docker CLI and no `/var/run/docker.sock` mounted, so
   `shutil.which("docker")` sees nothing. It inspects its own container, not the
   host. Same failure class as the earlier `nvidia-smi` / GPU-inventory gap.

2. **Feature:** there is no way to manage the engine containers from the GUI.
   The operator wants the full lifecycle (list / inspect / logs / stats /
   start / stop / restart) plus the ability to exec **into** a container to pull
   data or apply updates — so the Control Center becomes a complete management
   loop instead of a read-only dashboard.

## Decisions (from brainstorming)

- **Channel:** hybrid — SSH from the central GUI (works immediately, every host,
  no reinstall) **and** a native docker-socket path on the node daemon (fast,
  added on reinstall). Implemented as one contract with two backends.
- **Scope of control:** lifecycle **plus exec into the container**.
- **Targeting:** **only vLLM / engine containers** — a name/label whitelist.
- **v1 scope cut:** lifecycle = start / stop / restart. Full `recreate` / re-run
  is OUT of v1 — engine (re)launch is already owned by `deployment.py` service
  plans; duplicating it here is risky.

## Architecture (Approach A): one contract, two backends

New module `vllm/sndr_core/product_api/container_ops.py` defining a
`ContainerControl` interface:

```
list_managed() -> list[ManagedContainer]
inspect(name) -> dict
logs(name, tail=200) -> str          # snapshot
stream_logs(name) -> Iterator[str]   # for SSE
stats(name) -> dict                  # cpu%, mem, mem_limit, (gpu mem if available)
start(name) / stop(name) / restart(name)
exec(name, argv, timeout) -> ExecResult
```

Two implementations behind it:

- **`SshContainerControl(ssh_target)`** — builds `docker …` argv and runs them via
  the existing `ssh_client` SSH channel (the same path Fleet/Hosts already use for
  `docker ps`/`inspect`). Used by the central GUI for a Host card. No node change,
  no reinstall.
- **`SocketContainerControl(sock_path="/var/run/docker.sock")`** — a minimal
  `http.client.HTTPConnection` subclass over an `AF_UNIX` socket talking the
  Docker Engine API (`GET /containers/json`, `/containers/{id}/json`, `/logs`,
  `/stats?stream=0`, `POST /{id}/start|stop|restart`, `POST /{id}/exec`). No
  third-party dependency — consistent with the project's no-SDK convention.

Both backends call the SAME whitelist guard before any operation.

## Whitelist (security boundary)

Centralized `is_managed_name(name)` — matches prefixes `vllm`, `vllm-*`,
`sndr-daemon`, plus optional label `sndr.managed=true`. Any operation on a
non-whitelisted container returns `403 "container not managed by SNDR"`. Enforced
identically in both backends so neither channel can escape the scope.

## Gating (defense in depth)

| Operation | Requires |
|---|---|
| list / inspect / logs / stats | nothing (read-only by default, as elsewhere) |
| start / stop / restart | `SNDR_ENABLE_APPLY=1` + `confirm` in body |
| **exec into container** | `SNDR_ENABLE_APPLY=1` **+ `SNDR_ENABLE_EXEC=1`** + `confirm` + whitelist + audit log |

`exec` is strictly more dangerous than lifecycle (arbitrary code in prod), so it
sits behind its own env flag that is **off by default even after reinstall** —
the operator turns it on deliberately. Every exec is audit-logged (container,
argv, caller, rc).

## REST endpoints (one shape, both channels)

Local (node daemon, via socket):
- `GET  /api/v1/containers`
- `GET  /api/v1/containers/{name}`
- `GET  /api/v1/containers/{name}/logs?tail=200`
- `GET  /api/v1/containers/{name}/logs/stream`  (SSE)
- `GET  /api/v1/containers/{name}/stats`
- `POST /api/v1/containers/{name}/action`  body `{action, confirm}`  (gated)
- `POST /api/v1/containers/{name}/exec`    body `{argv, confirm}`     (gated + EXEC)

Remote (central GUI → Host card, via SSH): the same set under
`/api/v1/hosts/{host_id}/containers/…`. SSH credentials are resolved server-side
from the stored host profile (existing `secrets_store` pattern, keyed by
`host_id`); the client never sends raw credentials.

Backend selection: local endpoints construct a `SocketContainerControl`; host
endpoints construct `SshContainerControl(resolve_target(host_id))`.

## Detection fix ("docker нет")

`check_docker()` in `deps/checkers.py` additionally detects a mounted
`/var/run/docker.sock` (path exists AND is a socket via `stat.S_ISSOCK`). If the
CLI is absent but the socket is present, report `installed=True, via="socket"` and
ping the socket for `daemon_running`. On a Host card, docker availability already
comes from SSH discovery (truthful). The report carries a `source` note so the GUI
can show "via host socket" vs "via SSH".

## node_setup.py change

Add `-v /var/run/docker.sock:/var/run/docker.sock` to the sidecar `docker run`
(ships on reinstall, like the `--gpus all` / CORS changes). `SNDR_ENABLE_EXEC` is
**not** set automatically — safe default; exec stays off until the operator opts in.

## Frontend

A new **"Containers"** panel in the existing `ModuleCard` style: a grid of
scoped container cards — name, state dot, image, ports, uptime, live stats
(CPU%/mem, refreshed ~3s). Per-card actions: Start / Stop / Restart (disabled
with a tooltip when apply is off), Logs (streaming drawer over SSE), Exec (a
guarded mini-console on the existing xterm component, disabled unless exec is
enabled). The source (local node vs a specific host) follows the current GUI
context (switched-to node → local; Host card → that `host_id`).

## Error handling

- Socket absent on a local request → `503` "docker socket not mounted — reinstall
  node to enable container management".
- SSH failure → surfaced as the host error (existing pattern).
- Non-managed name → `403`.
- Gated op without apply/confirm → `422` with reason (existing pattern).

## Testing (TDD — failing tests first)

- `tests/unit/product_api/test_container_ops.py`:
  - whitelist guard blocks non-managed names (both backends);
  - gating blocks lifecycle when `SNDR_ENABLE_APPLY` off, blocks exec when
    `SNDR_ENABLE_EXEC` off;
  - `SshContainerControl` builds the correct `docker …` argv (inject a fake exec fn);
  - `SocketContainerControl` parses Docker Engine API JSON (inject a fake socket
    transport — no real docker needed).
- `tests/unit/product_api/test_http_app.py` additions: endpoints return the
  scoped list; `403`/`422` on guard/gate violations; `503` when socket absent.
- `tests/unit/.../test_checkers` (or equivalent): `check_docker` detects the
  mounted socket (monkeypatch `os.stat`/`stat.S_ISSOCK`).
- `tests/unit/product_api/test_node_setup.py`: the script mounts `docker.sock`
  and does NOT auto-set `SNDR_ENABLE_EXEC`.

## Out of scope (v1)

- Full container recreate / re-run with stored args (owned by `deployment.py`).
- Image pulls / build.
- Managing non-engine containers.
