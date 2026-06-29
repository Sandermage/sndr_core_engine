# SPDX-License-Identifier: Apache-2.0
"""Clients for the operator's adjacent Genesis services — the AI **aggregator**
(multi-model market-analysis consensus + self-hosted SearXNG web search) and the
AI **proxy** (OpenAI-compatible smart-router with cost/health observability).

These let the SNDR ops-copilot do real search & analysis: web search with **no
external paid API** (via the aggregator's self-hosted SearXNG, with a direct
SearXNG fallback), market analysis / signals / patterns, and proxy routing / cost
insight.

Same discipline as :mod:`engine_client`: stdlib ``urllib`` only; the base URLs
are **operator-set from env** and validated (never an arbitrary client-supplied
URL — anti-SSRF); short timeouts; an unreachable service raises a clean
:class:`ServiceError` (the copilot loop turns that into a tool-error fed back to
the model) instead of a 500.

Config (env):
  GENESIS_AGG_URL      aggregator base, default ``http://127.0.0.1:8330``
  GENESIS_AGG_API_KEY  aggregator ``X-API-Key`` (optional; many routes are public)
  GENESIS_PROXY_URL    proxy base, default ``http://127.0.0.1:8318``
  SNDR_SEARXNG_URL     direct SearXNG fallback for web search (optional)
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

# scheme://host[:port] only — operator-set and validated; no path/credentials in
# the base, so a crafted env value can't redirect requests to an arbitrary URL.
_URL_RE = re.compile(r"^https?://[A-Za-z0-9._-]{1,253}(:\d{1,5})?$")
_DEFAULT_AGG = "http://127.0.0.1:8330"
_DEFAULT_PROXY = "http://127.0.0.1:8318"
# Direct SearXNG fallback, default matching the operator's published instance.
_DEFAULT_SEARXNG = "http://127.0.0.1:8888"


class ServiceError(RuntimeError):
    """A reachable-but-failed or unreachable adjacent service. Carries an
    operator-friendly message; the copilot surfaces it as a tool error."""


_TRUTHY = {"1", "true", "yes", "on"}


def external_services_enabled() -> bool:
    """Whether the adjacent-service (proxy + aggregator) integration is unlocked.

    Opt-in by the operator key ``SNDR_ENABLE_EXTERNAL_SERVICES`` — OFF by default,
    matching the ``SNDR_ENABLE_EXEC`` / ``SNDR_ENABLE_APPLY`` discipline. A default
    SNDR install never reaches out to proxy/aggregator; the GUI and copilot only
    expose this functionality when the key is set. Both projects stay external —
    SNDR only *connects* to them, and only when the operator turns it on.
    """
    return str(os.environ.get("SNDR_ENABLE_EXTERNAL_SERVICES", "")).strip().lower() in _TRUTHY


def _base(env_name: str, default: str) -> str:
    raw = (os.environ.get(env_name) or default).strip().rstrip("/")
    return raw if _URL_RE.match(raw) else default


def _agg_headers() -> dict[str, str]:
    key = (os.environ.get("GENESIS_AGG_API_KEY") or "").strip()
    return {"X-API-Key": key} if key else {}


def _request(url: str, *, method: str = "GET", payload: Optional[dict] = None,
             headers: Optional[dict[str, str]] = None, timeout: float = 8.0) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    hdrs = {"Accept": "application/json"}
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed scheme, env-set host
        return resp.status, resp.read().decode("utf-8", "replace")


def _json_or_error(status: int, text: str) -> tuple[Any, Optional[str]]:
    try:
        data = json.loads(text) if text else {}
    except json.JSONDecodeError:
        data = {}
    if not (200 <= status < 300):
        msg = ""
        if isinstance(data, dict):
            msg = str(data.get("detail") or data.get("error") or "")
        return None, (msg or f"HTTP {status}")
    return data, None


def _call(env_name: str, default_base: str, path: str, *, method: str = "GET",
          payload: Optional[dict] = None, headers: Optional[dict[str, str]] = None,
          timeout: float = 8.0, service: str = "service") -> Any:
    if not external_services_enabled():
        raise ServiceError(
            "external services are disabled — set SNDR_ENABLE_EXTERNAL_SERVICES=1 "
            "to enable the proxy/aggregator integration"
        )
    base = _base(env_name, default_base)
    url = f"{base}{path}"
    try:
        status, text = _request(url, method=method, payload=payload, headers=headers, timeout=timeout)
    except urllib.error.HTTPError as exc:  # 4xx/5xx — read the body for the message
        status, text = exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ServiceError(f"{service} unreachable at {base}: {getattr(exc, 'reason', exc)}") from exc
    data, err = _json_or_error(status, text)
    if err:
        raise ServiceError(f"{service} error: {err}")
    return data


# ── aggregator: web search + market analysis ─────────────────────────────────


def _searxng_direct(query: str, *, limit: int, language: str, timeout: float) -> list[dict[str, Any]]:
    base = (os.environ.get("SNDR_SEARXNG_URL") or _DEFAULT_SEARXNG).strip().rstrip("/")
    if not _URL_RE.match(base):
        raise ServiceError("no valid SearXNG fallback configured (SNDR_SEARXNG_URL)")
    qs = urllib.parse.urlencode({"q": query, "format": "json", "language": language, "safesearch": 1})
    try:
        status, text = _request(f"{base}/search?{qs}", timeout=timeout)
    except urllib.error.HTTPError as exc:
        status, text = exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ServiceError(f"SearXNG unreachable at {base}: {getattr(exc, 'reason', exc)}") from exc
    data, err = _json_or_error(status, text)
    if err:
        raise ServiceError(f"SearXNG error: {err}")
    return (data.get("results") or [])[:limit] if isinstance(data, dict) else []


def web_search(query: str, *, limit: int = 8, categories: str = "general",
               language: str = "en", timeout: float = 12.0) -> dict[str, Any]:
    """Live web search with no external paid API: the aggregator's self-hosted
    SearXNG (``POST /v1/search``), falling back to a direct SearXNG instance
    (``SNDR_SEARXNG_URL``, default ``:8888``) if the aggregator is unreachable
    **or returns nothing** — its wrapper can come back empty even when SearXNG
    itself has hits."""
    q = str(query or "").strip()
    if not q:
        raise ServiceError("query is required")
    limit = max(1, min(20, int(limit)))
    results: list[Any] = []
    source = "aggregator"
    try:
        data = _call("GENESIS_AGG_URL", _DEFAULT_AGG, "/v1/search", method="POST",
                     payload={"query": q, "limit": limit, "categories": categories, "language": language},
                     headers=_agg_headers(), timeout=timeout, service="aggregator")
        results = (data.get("results") or []) if isinstance(data, dict) else []
    except ServiceError:
        results = []
    if not results:  # aggregator down OR empty → direct SearXNG (raises if it too fails)
        results = _searxng_direct(q, limit=limit, language=language, timeout=timeout)
        source = "searxng"
    return {
        "query": q, "source": source, "count": len(results[:limit]),
        "results": [
            {"title": r.get("title"), "url": r.get("url"),
             "snippet": (str(r.get("content") or "")[:500]).strip(), "engine": r.get("engine")}
            for r in results[:limit] if isinstance(r, dict)
        ],
    }


def market_analysis(prompt: str, *, mode: str = "aggregate", providers: Optional[list[str]] = None,
                    system_prompt: Optional[str] = None, timeout: float = 90.0) -> dict[str, Any]:
    """Multi-model consensus analysis via the aggregator (``POST /v1/aggregate``).
    Auto-prefetches live market data + RAG context. mode: aggregate|compare|debate."""
    p = str(prompt or "").strip()
    if not p:
        raise ServiceError("prompt is required")
    body: dict[str, Any] = {"prompt": p, "mode": str(mode or "aggregate")}
    if providers:
        body["providers"] = providers
    if system_prompt:
        body["system_prompt"] = system_prompt
    data = _call("GENESIS_AGG_URL", _DEFAULT_AGG, "/v1/aggregate", method="POST",
                 payload=body, headers=_agg_headers(), timeout=timeout, service="aggregator")
    res = (data.get("result") or {}) if isinstance(data, dict) else {}
    responses = res.get("model_responses") or []
    return {
        "mode": data.get("mode", body["mode"]) if isinstance(data, dict) else body["mode"],
        "answer": res.get("synthesized_answer"),
        "agreement_score": res.get("agreement_score"), "agreement_level": res.get("agreement_level"),
        "confidence": res.get("confidence"), "aggregator_model": res.get("aggregator_model"),
        "models": [m.get("model") if isinstance(m, dict) else m for m in responses][:8],
        "processing_ms": res.get("processing_time_ms"),
    }


def recent_signals(*, limit: int = 15, timeout: float = 10.0) -> dict[str, Any]:
    """Latest trading signals from the aggregator (``GET /v1/signals/recent``)."""
    limit = max(1, min(200, int(limit)))
    data = _call("GENESIS_AGG_URL", _DEFAULT_AGG, f"/v1/signals/recent?limit={limit}",
                 headers=_agg_headers(), timeout=timeout, service="aggregator")
    rows = data if isinstance(data, list) else (data.get("signals") or [] if isinstance(data, dict) else [])
    return {"count": len(rows[:limit]), "signals": [
        {"asset": s.get("asset"), "direction": s.get("direction"), "entry": s.get("entry_price"),
         "tp1": s.get("tp1"), "sl": s.get("sl"), "confidence": s.get("confidence"),
         "grade": s.get("quality_grade"), "created_at": s.get("created_at")}
        for s in rows[:limit] if isinstance(s, dict)]}


def market_patterns(*, timeout: float = 10.0) -> dict[str, Any]:
    """Mined market patterns with win-rate / avg PnL (``GET /v1/dashboard/patterns``)."""
    data = _call("GENESIS_AGG_URL", _DEFAULT_AGG, "/v1/dashboard/patterns",
                 headers=_agg_headers(), timeout=timeout, service="aggregator")
    pats = (data.get("patterns") or []) if isinstance(data, dict) else []
    return {"count": len(pats), "patterns": [
        {"name": p.get("name"), "win_rate": p.get("win_rate"), "avg_pnl_pct": p.get("avg_pnl_pct"),
         "confidence": p.get("confidence_level"), "assets": p.get("asset_classes")}
        for p in pats[:20] if isinstance(p, dict)]}


def recent_anomalies(*, hours: int = 24, timeout: float = 10.0) -> dict[str, Any]:
    """Recently detected market anomalies/reversals (``GET /v1/anomalies/recent``)."""
    hours = max(1, min(168, int(hours)))
    data = _call("GENESIS_AGG_URL", _DEFAULT_AGG, f"/v1/anomalies/recent?hours={hours}",
                 headers=_agg_headers(), timeout=timeout, service="aggregator")
    rows = data if isinstance(data, list) else (data.get("anomalies") or [] if isinstance(data, dict) else [])
    return {"count": len(rows), "anomalies": [
        {"type": a.get("type"), "severity": a.get("severity"),
         "description": a.get("description"), "detected_at": a.get("detected_at")}
        for a in rows[:20] if isinstance(a, dict)]}


# ── proxy: routing / cost / health observability ─────────────────────────────


def proxy_routing(*, timeout: float = 8.0) -> dict[str, Any]:
    """Proxy model routing detail — provider, equivalence group, fallback chain,
    ban status per model (``GET /system/models-detail``)."""
    data = _call("GENESIS_PROXY_URL", _DEFAULT_PROXY, "/system/models-detail", timeout=timeout, service="proxy")
    models = data.get("models") if isinstance(data, dict) else data
    if not isinstance(models, list):
        models = []
    return {"count": len(models), "models": [
        {"name": m.get("name") or m.get("model"), "provider": m.get("provider"),
         "group": m.get("equivalence_group") or m.get("group"),
         "fallback_chain": m.get("fallback_chain"),
         "banned": m.get("banned") if "banned" in m else m.get("ban_status")}
        for m in models[:40] if isinstance(m, dict)]}


def proxy_cost(*, timeout: float = 8.0) -> dict[str, Any]:
    """Cost metrics from the proxy (``GET /metrics/cost``) — passed through trimmed."""
    data = _call("GENESIS_PROXY_URL", _DEFAULT_PROXY, "/metrics/cost", timeout=timeout, service="proxy")
    return data if isinstance(data, dict) else {"cost": data}


def proxy_health(*, timeout: float = 8.0) -> dict[str, Any]:
    """Per-provider health / circuit state from the proxy (``GET /health/providers``)."""
    data = _call("GENESIS_PROXY_URL", _DEFAULT_PROXY, "/health/providers", timeout=timeout, service="proxy")
    return data if isinstance(data, dict) else {"providers": data}


__all__ = [
    "ServiceError", "web_search", "market_analysis", "recent_signals", "market_patterns",
    "recent_anomalies", "proxy_routing", "proxy_cost", "proxy_health",
]
