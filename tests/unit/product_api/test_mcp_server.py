# SPDX-License-Identifier: Apache-2.0
"""MCP server over the read-only Product API tool catalog.

A stdlib JSON-RPC 2.0 server (stdio transport) that re-exposes the Copilot tool
catalog (``tool_specs`` / ``execute_tool``) to any MCP client (Claude Desktop,
Cursor, …). These tests pin the protocol surface — initialize / tools.list /
tools.call / notifications / errors — and a full stdio round-trip."""
from __future__ import annotations

import io
import json


def test_initialize_returns_capabilities_and_serverinfo():
    from sndr.product_api.legacy.mcp_server import handle_request

    resp = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2024-11-05", "capabilities": {}}})
    assert resp["jsonrpc"] == "2.0" and resp["id"] == 1
    result = resp["result"]
    assert "tools" in result["capabilities"]
    assert result["serverInfo"]["name"]
    assert result["protocolVersion"]


def test_tools_list_mirrors_the_copilot_catalog():
    from sndr.product_api.legacy import copilot
    from sndr.product_api.legacy.mcp_server import handle_request

    resp = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = resp["result"]["tools"]
    spec_names = {s["function"]["name"] for s in copilot.tool_specs()}
    assert {t["name"] for t in tools} == spec_names
    for t in tools:
        assert t["name"] and "inputSchema" in t and isinstance(t["inputSchema"], dict)


def test_tools_call_dispatches_to_execute_tool():
    from sndr.product_api.legacy.mcp_server import handle_request

    resp = handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                           "params": {"name": "get_overview", "arguments": {}}})
    result = resp["result"]
    assert result["content"][0]["type"] == "text"
    payload = json.loads(result["content"][0]["text"])
    assert isinstance(payload, dict)


def test_tools_call_unknown_tool_is_flagged_error_not_raised():
    from sndr.product_api.legacy.mcp_server import handle_request

    resp = handle_request({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                           "params": {"name": "does-not-exist", "arguments": {}}})
    assert resp["result"]["isError"] is True


def test_initialized_notification_produces_no_response():
    from sndr.product_api.legacy.mcp_server import handle_request

    assert handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_unknown_method_returns_method_not_found():
    from sndr.product_api.legacy.mcp_server import handle_request

    resp = handle_request({"jsonrpc": "2.0", "id": 9, "method": "bogus/method"})
    assert resp["error"]["code"] == -32601


def test_serve_stdio_full_roundtrip():
    from sndr.product_api.legacy.mcp_server import serve_stdio

    requests = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
    ]) + "\n"
    out = io.StringIO()
    serve_stdio(stdin=io.StringIO(requests), stdout=out)

    lines = [ln for ln in out.getvalue().splitlines() if ln.strip()]
    # initialize + tools/list answered; the notification yields nothing.
    assert len(lines) == 2
    init = json.loads(lines[0])
    assert init["id"] == 1 and "result" in init
    listed = json.loads(lines[1])
    assert listed["id"] == 2 and listed["result"]["tools"]
