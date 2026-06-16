# SPDX-License-Identifier: Apache-2.0
"""MCP (Model Context Protocol) server over the read-only Product API.

Re-exposes the Copilot tool catalog (:func:`copilot.tool_specs` /
:func:`copilot.execute_tool`) to any MCP client — Claude Desktop, Cursor, IDE
agents — so an external AI agent can query this inference control plane (catalog,
presets, the running model, doctor, patches, capacity, …) over the standard
protocol instead of bespoke HTTP.

Dependency-free by design: a minimal JSON-RPC 2.0 server over the stdio transport
(newline-delimited JSON), matching the project's lean-deps philosophy. The
handler is a pure function so the protocol is fully unit-testable without a live
transport. Read-only — it inherits the Product API's no-mutation guarantee; the
tools never write YAML, the registry or runtime artifacts.

Run it:  ``python3 -m sndr.product_api.legacy.mcp_server``
MCP client config (e.g. Claude Desktop):
    {"command": "python3", "args": ["-m", "sndr.product_api.legacy.mcp_server"]}
"""
from __future__ import annotations

import json
import sys
from typing import Any, Optional, TextIO

from . import copilot

SERVER_NAME = "sndr-product-api"
SERVER_VERSION = "1.0.0"
# Default MCP protocol revision we advertise; we echo the client's requested
# version when it sends one, for forward/backward compatibility.
PROTOCOL_VERSION = "2024-11-05"


def _ok(rid: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def _mcp_tools() -> list[dict[str, Any]]:
    """Map the Copilot OpenAI-style tool specs to MCP tool definitions."""
    tools: list[dict[str, Any]] = []
    for spec in copilot.tool_specs():
        fn = spec.get("function", {})
        tools.append({
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "inputSchema": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return tools


def handle_request(request: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Handle one JSON-RPC request. Returns the response, or ``None`` for
    notifications (no ``id``) and ignored notification methods."""
    method = request.get("method")
    rid = request.get("id")
    params = request.get("params") or {}

    if method == "initialize":
        return _ok(rid, {
            "protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return _ok(rid, {})
    if method == "tools/list":
        return _ok(rid, {"tools": _mcp_tools()})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if not name:
            result: dict[str, Any] = {"ok": False, "error": "missing tool name"}
        else:
            result = copilot.execute_tool(name, args)
        is_error = isinstance(result, dict) and result.get("ok") is False
        return _ok(rid, {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}],
            "isError": is_error,
        })

    # Unknown method: error for a request, silence for a notification.
    if rid is None:
        return None
    return _err(rid, -32601, f"method not found: {method}")


def serve_stdio(stdin: Optional[TextIO] = None, stdout: Optional[TextIO] = None) -> None:
    """Serve MCP over newline-delimited JSON on stdio until stdin closes."""
    src = stdin if stdin is not None else sys.stdin
    dst = stdout if stdout is not None else sys.stdout
    for line in src:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            dst.write(json.dumps(_err(None, -32700, "parse error")) + "\n")
            dst.flush()
            continue
        response = handle_request(request)
        if response is not None:
            dst.write(json.dumps(response, ensure_ascii=False, default=str) + "\n")
            dst.flush()


def main() -> None:
    serve_stdio()


if __name__ == "__main__":
    main()
