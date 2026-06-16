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

The agent then sees tools like `get_overview`, `run_doctor`, `list_presets`,
`get_preset`, `list_patches`, `estimate_vram`, `plan_install`. Tool results are
returned as JSON text content.

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
