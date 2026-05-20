# SPDX-License-Identifier: Apache-2.0
"""proxy — non-streaming request forwarder with default-first fallback.

D2a scope:
  - non-streaming requests: full proxy to chosen upstream
  - streaming requests (stream=true): forced to DEFAULT upstream
    (D2b will add structured-streaming support)
  - on ANY uncertainty (router exception, missing artifact, structured
    down, force-default flag) -> default upstream
  - upstream connection refused / timeout / 5xx → propagated to client
    (no retry); only structured-side failures trigger fallback to default
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from . import metrics
from .upstream import UpstreamState

log = logging.getLogger("genesis.spec_decode.gateway.proxy")


def _is_streaming(body: dict[str, Any]) -> bool:
    if not isinstance(body, dict):
        return False
    v = body.get("stream")
    return bool(v) if v is not None else False


def _decide_route(
    *,
    body: dict[str, Any],
    artifact,                 # FunctionalArtifact | None
    default_state: UpstreamState,
    structured_state: UpstreamState,
    force_default: bool,
) -> tuple[UpstreamState, str, str]:
    """Return (chosen_upstream, decision_label, reason).

    decision_label is one of:
      'structured', 'default', 'fallback_force', 'fallback_streaming',
      'fallback_no_artifact', 'fallback_router_error',
      'fallback_structured_down', 'fallback_router_denied'
    """
    # 1) Hard switch
    if force_default:
        return (default_state, "fallback_force",
                "admin force-default flag is active")

    # 2) Streaming
    if _is_streaming(body):
        return (default_state, "fallback_streaming",
                "stream=true; D2a routes streaming to default only")

    # 3) Artifact present?
    if artifact is None:
        return (default_state, "fallback_no_artifact",
                "no FunctionalArtifact loaded; router has no profile")

    # 4) Ask router
    try:
        from ..request_router import select_profile
        sel = select_profile(request=body, artifact=artifact)
    except Exception as e:  # noqa: BLE001
        log.warning("[gateway.proxy] router exception: %s", e)
        return (default_state, "fallback_router_error",
                f"router raised: {type(e).__name__}: {e}")

    # Update router decision metric
    try:
        metrics.ROUTER_DECISION.labels(
            profile=sel.profile, accepted=str(bool(sel.accepted)).lower(),
        ).inc()
    except Exception:
        pass

    if not sel.accepted:
        return (default_state, "fallback_router_denied",
                f"router denied: {sel.reason}")

    # 5) Structured health check
    if not structured_state.is_routable():
        return (default_state, "fallback_structured_down",
                f"structured upstream is {structured_state.state}: "
                f"{structured_state.last_error}")

    return (structured_state, "structured", sel.reason)


async def proxy_request(
    *,
    method: str,
    path: str,
    headers: dict[str, str],
    body_bytes: bytes,
    body_json: dict[str, Any] | None,
    artifact,
    default_state: UpstreamState,
    structured_state: UpstreamState,
    force_default: bool,
    timeout_s: float = 120.0,
):
    """Forward a request to the chosen upstream and return the
    response (status, headers, body). Returns a FastAPI Response.
    """
    from fastapi import Response

    body = body_json if isinstance(body_json, dict) else {}
    chosen, label, reason = _decide_route(
        body=body, artifact=artifact,
        default_state=default_state,
        structured_state=structured_state,
        force_default=force_default,
    )

    log.info(
        "[gateway.proxy] decision=%s upstream=%s reason=%s",
        label, chosen.name, reason,
    )

    # Update routing metrics
    try:
        if label == "structured":
            metrics.ROUTED_STRUCTURED.inc()
        else:
            metrics.ROUTED_DEFAULT.inc()
            if label.startswith("fallback_"):
                metrics.FALLBACK_TOTAL.labels(
                    reason=label[len("fallback_"):]).inc()
    except Exception:
        pass

    # Forward
    import httpx
    url = chosen.base_url.rstrip("/") + path

    # Strip hop-by-hop headers
    fwd_headers = {
        k: v for k, v in headers.items()
        if k.lower() not in (
            "host", "content-length", "connection", "keep-alive",
            "transfer-encoding", "upgrade", "te", "trailer",
            "proxy-authenticate", "proxy-authorization",
        )
    }

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.request(
                method=method, url=url, content=body_bytes,
                headers=fwd_headers,
            )
        latency = time.perf_counter() - t0
        try:
            metrics.REQUEST_LATENCY.labels(upstream=chosen.name).observe(
                latency)
        except Exception:
            pass

        # Strip response hop-by-hop headers
        resp_headers = {
            k: v for k, v in r.headers.items()
            if k.lower() not in (
                "content-length", "connection", "keep-alive",
                "transfer-encoding", "content-encoding",
            )
        }
        return Response(
            content=r.content,
            status_code=r.status_code,
            headers=resp_headers,
            media_type=r.headers.get("content-type", "application/json"),
        )
    except Exception as e:  # noqa: BLE001
        latency = time.perf_counter() - t0
        try:
            metrics.UPSTREAM_ERROR.labels(
                upstream=chosen.name,
                kind=type(e).__name__,
            ).inc()
            metrics.REQUEST_LATENCY.labels(upstream=chosen.name).observe(
                latency)
        except Exception:
            pass
        log.warning(
            "[gateway.proxy] upstream error to %s: %s: %s",
            chosen.name, type(e).__name__, e,
        )
        return Response(
            content=json.dumps({
                "error": {
                    "message": f"upstream {chosen.name} unreachable",
                    "type": "upstream_error",
                    "code": "upstream_unreachable",
                }
            }).encode("utf-8"),
            status_code=502,
            media_type="application/json",
        )


__all__ = ["proxy_request", "_decide_route", "_is_streaming"]
