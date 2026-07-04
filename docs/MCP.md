<!-- SPDX-License-Identifier: Apache-2.0 -->
# SNDR MCP server

Exposes the **read-only Product API** to any [Model Context
Protocol](https://modelcontextprotocol.io) client — Claude Desktop, Cursor, IDE
agents — so an external AI agent can query this inference control plane over the
standard protocol instead of bespoke HTTP.

It re-exposes the same tool catalog the in-app **Ops Copilot** uses
(`sndr.product_api.legacy.copilot`): catalog overview, doctor, presets, patches,
VRAM/capacity estimation, install planning, plus the market/news/proxy tools.
Read-only — it inherits the Product API's no-mutation guarantee.

## Run

```bash
python3 -m sndr.product_api.legacy.mcp_server
```

It speaks JSON-RPC 2.0 over stdio (newline-delimited JSON) — no extra
dependencies, no network port. The client launches it as a subprocess.

## Connect a client

Claude Desktop (`claude_desktop_config.json`) / Cursor / any MCP client:

```json
{
  "mcpServers": {
    "sndr": {
      "command": "python3",
      "args": ["-m", "sndr.product_api.legacy.mcp_server"]
    }
  }
}
```

Tool results are returned as JSON text content.

## Tool catalog

The 18 tools mirrored from `copilot.tool_specs()` (as of v12.0.0, 2026-07 —
`tools/list` is always the live source):

| Tool | What it returns |
| --- | --- |
| `get_overview` | Catalog + capability snapshot: model/preset/profile counts, preset status breakdown, engine install state |
| `run_doctor` | Read-only doctor findings (warning/blocked/info) with suggested actions |
| `list_presets` | List/filter preset configs in the catalog |
| `get_preset` | One preset's full record (model, hardware, runtime, card with reference metrics) |
| `list_patches` | List/filter the Genesis patch registry |
| `estimate_vram` | Per-GPU VRAM fit + max context for a known model at a given context / TP / GPU VRAM / KV config |
| `plan_install` | DRY-RUN install plan for a preset on a target (compose, proxmox, proxmox_vm, …) |
| `web_search` | Live web search (via the Genesis aggregator's search backend) |
| `market_analysis` | Multi-model consensus market analysis via the Genesis aggregator |
| `recent_signals` | Latest trading signals from the aggregator |
| `market_patterns` | Mined market patterns with win-rate and average PnL |
| `recent_anomalies` | Recently detected market anomalies / reversals |
| `proxy_routing` | How the Genesis proxy routes models: provider, equivalence group, fallback chain, ban status |
| `proxy_cost` | Cost metrics from the Genesis proxy (spend per model/provider) |
| `proxy_health` | Per-provider health / circuit-breaker state |
| `crypto_market_overview` | Live crypto market snapshot (top coins, global cap, dominance, Fear & Greed) |
| `coin_data` | Detailed live data for specific coins (comma-separated symbols) |
| `news_analysis` | Crypto news field grouped into classes (ETF flows, liquidations, geopolitics, regulation), via the web-search backend |

Example `tools/call` round-trip over stdio (one JSON-RPC message per line):

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
 "params": {"name": "get_preset",
            "arguments": {"preset_id": "prod-qwen3.6-35b-balanced"}}}
```

```json
{"jsonrpc": "2.0", "id": 1,
 "result": {"content": [{"type": "text", "text": "{\"preset\": …}"}],
            "isError": false}}
```

## Prerequisites & environment coupling

- **Catalog / doctor / preset / patch / VRAM / install tools** read the local
  `sndr` package's static project state — no running engine, no network. The
  server must run in a Python environment where `sndr` is importable (the same
  install the CLI uses); the client's `command`/`args` above assume that.
- **Adjacent-service tools are OFF by default.** The aggregator/proxy
  integration is opt-in behind `SNDR_ENABLE_EXTERNAL_SERVICES=1` (same
  discipline as `SNDR_ENABLE_APPLY` / `SNDR_ENABLE_EXEC`) — a default install
  never reaches out to them, and the tools report a tool error explaining the
  key until it is set.
- **`web_search`, `market_analysis`, `recent_signals`, `market_patterns`,
  `recent_anomalies`, `news_analysis`** call the Genesis **aggregator**:
  `GENESIS_AGG_URL` (default `http://127.0.0.1:8330`), optional
  `GENESIS_AGG_API_KEY`. Without a reachable aggregator these tools return a
  structured error result, not a crash.
- **`proxy_routing`, `proxy_cost`, `proxy_health`** call the Genesis **proxy**:
  `GENESIS_PROXY_URL` (default `http://127.0.0.1:8318`).
- **`crypto_market_overview`, `coin_data`** call the public CoinGecko API —
  outbound network required.

The MCP tool catalog does not talk to the live vLLM engine — engine status and
metrics stay on the HTTP Product API (`/api/v1/engine/*`, see
[`PRODUCT_API.md`](PRODUCT_API.md)).

## Troubleshooting

- **Client shows no tools.** Check the client's MCP server log: the usual cause
  is `python3` not on the client's `PATH`, or `python3` resolving to an
  environment without `sndr` installed. Use an absolute interpreter path in
  `command` (e.g. the venv's `bin/python3`).
- **`ModuleNotFoundError: sndr`.** The subprocess inherits the client's
  environment, not your shell profile. Point `command` at the Python that has
  the package, or add `"env": {"PYTHONPATH": "/path/to/repo"}` to the server
  entry for a source checkout.
- **Market/news tools error out.** First check `SNDR_ENABLE_EXTERNAL_SERVICES=1`
  is set in the server's `env` — the integration is off by default. Then check
  the aggregator/proxy services are running and reachable; set
  `GENESIS_AGG_URL` / `GENESIS_PROXY_URL` if they live on another host. The
  catalog tools keep working regardless.
- **Working directory.** The server reads packaged catalog data, so no specific
  cwd is required; only source checkouts run via `PYTHONPATH` need the repo
  path visible.

## Protocol surface

| Method | Behaviour |
| --- | --- |
| `initialize` | Advertises `tools` capability + `serverInfo`; echoes the client's `protocolVersion`. |
| `tools/list` | Mirrors `copilot.tool_specs()` → MCP tool defs (`name`, `description`, `inputSchema`). |
| `tools/call` | Dispatches `{name, arguments}` to `copilot.execute_tool`; result wrapped as text content, `isError` set when the tool reports `ok:false`. Unknown/failing tools degrade to an error result (never crash the session). |
| `ping` | `{}` |
| `notifications/initialized` | Accepted, no response. |

The handler (`handle_request`) is a pure function, so the protocol is unit-tested
without a live transport (`tests/unit/product_api/test_mcp_server.py`).

## Security

Same posture as the GUI daemon: read-only by default, no writes to YAML / the
registry / runtime artifacts. The MCP server adds no network surface — it runs as
a stdio subprocess of the client. Anything that would mutate state (service
actions, container recreate, node setup) is **not** exposed here.

## See also

- `docs/GUI.md` — the in-app Ops Copilot that shares this tool catalog.
- `docs/PRODUCT_API.md` — the underlying read-only API contract.
