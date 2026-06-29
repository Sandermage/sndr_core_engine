# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the adjacent-service clients (aggregator + proxy) and the
copilot tools that wrap them. No real network — `_request` is stubbed."""
from __future__ import annotations

import io
import json
import urllib.error

import pytest

from sndr.product_api.legacy import external_clients as ext


@pytest.fixture(autouse=True)
def _enable_external_services(monkeypatch):
    """The adjacent-service integration is opt-in (gated by the key). The
    working-path tests below run with it enabled; the gate tests delenv it."""
    monkeypatch.setenv("SNDR_ENABLE_EXTERNAL_SERVICES", "1")


def test_external_services_disabled_by_default(monkeypatch):
    """Off without the key: no network, a clear ServiceError naming the key."""
    monkeypatch.delenv("SNDR_ENABLE_EXTERNAL_SERVICES", raising=False)

    def _no_net(*a, **k):
        raise AssertionError("must not touch the network when disabled")

    monkeypatch.setattr(ext, "_request", _no_net)
    assert ext.external_services_enabled() is False
    with pytest.raises(ext.ServiceError) as ei:
        ext.proxy_health()
    assert "SNDR_ENABLE_EXTERNAL_SERVICES" in str(ei.value)


def test_external_services_enabled_with_key(monkeypatch):
    """With the key set, calls reach the network layer (no disabled error)."""
    monkeypatch.setenv("SNDR_ENABLE_EXTERNAL_SERVICES", "1")
    assert ext.external_services_enabled() is True
    monkeypatch.setattr(ext, "_request", _fake_request({
        "/health/providers": (200, {"providers": []}),
    }))
    out = ext.proxy_health()  # must NOT raise the disabled error
    assert isinstance(out, dict)


def _fake_request(responses):
    """Build a fake `_request`. `responses` maps a URL-substring to either
    (status, json-body) or an Exception to raise."""
    def _req(url, *, method="GET", payload=None, headers=None, timeout=8.0):
        for frag, resp in responses.items():
            if frag in url:
                if isinstance(resp, Exception):
                    raise resp
                status, body = resp
                return status, json.dumps(body)
        raise urllib.error.URLError("no stub for " + url)
    return _req


def test_web_search_uses_aggregator(monkeypatch):
    monkeypatch.setattr(ext, "_request", _fake_request({
        "/v1/search": (200, {"results": [
            {"title": "BTC", "url": "http://x", "content": "price up", "engine": "google"}]}),
    }))
    out = ext.web_search("btc price", limit=5)
    assert out["source"] == "aggregator" and out["count"] == 1
    assert out["results"][0]["url"] == "http://x"
    assert out["results"][0]["snippet"] == "price up"


def test_web_search_falls_back_to_direct_searxng(monkeypatch):
    # The operator chose aggregator-first with a direct-SearXNG fallback.
    monkeypatch.setenv("SNDR_SEARXNG_URL", "http://searx.local:8888")
    monkeypatch.setattr(ext, "_request", _fake_request({
        "/v1/search": urllib.error.URLError("aggregator down"),
        "searx.local": (200, {"results": [{"title": "T", "url": "http://y", "content": "c"}]}),
    }))
    out = ext.web_search("q")
    assert out["source"] == "searxng" and out["results"][0]["url"] == "http://y"


def test_web_search_falls_back_on_empty_aggregator_results(monkeypatch):
    # Live finding: the aggregator's /v1/search wrapper can return 0 results while
    # SearXNG itself has hits — so fall back on EMPTY, not just on a connection error.
    monkeypatch.setenv("SNDR_SEARXNG_URL", "http://searx.local:8888")
    monkeypatch.setattr(ext, "_request", _fake_request({
        "/v1/search": (200, {"results": []}),  # aggregator returns nothing
        "searx.local": (200, {"results": [{"title": "T", "url": "http://z", "content": "c"}]}),
    }))
    out = ext.web_search("q")
    assert out["source"] == "searxng" and out["count"] == 1 and out["results"][0]["url"] == "http://z"


def test_web_search_all_paths_down_raises(monkeypatch):
    # Aggregator down AND the SearXNG fallback down -> a single clean ServiceError.
    monkeypatch.setattr(ext, "_request", _fake_request({
        "/v1/search": urllib.error.URLError("aggregator down"),
        "/search": urllib.error.URLError("searxng down"),  # default 127.0.0.1:8888
    }))
    with pytest.raises(ext.ServiceError):
        ext.web_search("q")


def test_web_search_empty_query_raises():
    with pytest.raises(ext.ServiceError):
        ext.web_search("   ")


def test_market_analysis_shape(monkeypatch):
    monkeypatch.setattr(ext, "_request", _fake_request({
        "/v1/aggregate": (200, {"mode": "aggregate", "result": {
            "synthesized_answer": "BTC bullish", "agreement_score": 0.8, "agreement_level": "high",
            "confidence": 0.7, "aggregator_model": "Local-Qwen", "processing_time_ms": 1234,
            "model_responses": [{"model": "m1"}, {"model": "m2"}]}}),
    }))
    out = ext.market_analysis("analyse btc")
    assert out["answer"] == "BTC bullish" and out["agreement_score"] == 0.8
    assert out["models"] == ["m1", "m2"]


def test_recent_signals_shape(monkeypatch):
    monkeypatch.setattr(ext, "_request", _fake_request({
        "/v1/signals/recent": (200, [
            {"asset": "BTC", "direction": "long", "entry_price": 100, "tp1": 110, "sl": 95,
             "confidence": 0.9, "quality_grade": "A", "created_at": "now"}]),
    }))
    out = ext.recent_signals(limit=10)
    assert out["count"] == 1 and out["signals"][0]["asset"] == "BTC"
    assert out["signals"][0]["entry"] == 100


def test_proxy_routing_shape(monkeypatch):
    monkeypatch.setattr(ext, "_request", _fake_request({
        "/system/models-detail": (200, {"models": [
            {"name": "Local-Qwen", "provider": "vllm", "equivalence_group": "qwen", "banned": False}]}),
    }))
    out = ext.proxy_routing()
    assert out["count"] == 1 and out["models"][0]["provider"] == "vllm"


def test_service_error_on_http_error(monkeypatch):
    def boom(url, **kw):
        raise urllib.error.HTTPError(url, 503, "down", {}, io.BytesIO(b'{"detail":"overloaded"}'))
    monkeypatch.setattr(ext, "_request", boom)
    with pytest.raises(ext.ServiceError, match="overloaded"):
        ext.recent_signals()


def test_base_url_validation(monkeypatch):
    monkeypatch.setenv("GENESIS_AGG_URL", "http://good.host:8330")
    assert ext._base("GENESIS_AGG_URL", ext._DEFAULT_AGG) == "http://good.host:8330"
    monkeypatch.setenv("GENESIS_AGG_URL", "file:///etc/passwd")  # invalid scheme → default
    assert ext._base("GENESIS_AGG_URL", ext._DEFAULT_AGG) == ext._DEFAULT_AGG


# ── copilot tool registration + delegation ───────────────────────────────────


def test_copilot_registers_new_tools():
    from sndr.product_api.legacy import copilot
    cat = {t["name"]: t["category"] for t in copilot.tool_catalog()}
    assert {"web_search", "market_analysis", "recent_signals", "market_patterns",
            "recent_anomalies", "proxy_routing", "proxy_cost", "proxy_health"} <= set(cat)
    assert cat["web_search"] == "search"
    assert cat["market_analysis"] == "analysis"
    assert cat["proxy_routing"] == "observability"
    assert "web_search" in {s["function"]["name"] for s in copilot.tool_specs()}


def test_copilot_web_search_tool_delegates(monkeypatch):
    from sndr.product_api.legacy import copilot, external_clients
    monkeypatch.setattr(external_clients, "web_search", lambda q, **kw: {"query": q, "count": 0, "results": []})
    out = copilot.execute_tool("web_search", {"query": "btc"})
    assert out["ok"] is True and out["result"]["query"] == "btc"


def test_copilot_tool_error_surfaces_not_raises(monkeypatch):
    # A down service must come back as a tool error (loop continues), not a crash.
    from sndr.product_api.legacy import copilot, external_clients

    def boom(*a, **k):
        raise external_clients.ServiceError("aggregator unreachable")
    monkeypatch.setattr(external_clients, "web_search", boom)
    out = copilot.execute_tool("web_search", {"query": "x"})
    assert out["ok"] is False and "unreachable" in out["error"]
