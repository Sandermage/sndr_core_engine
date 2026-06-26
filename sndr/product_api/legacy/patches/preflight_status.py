# SPDX-License-Identifier: Apache-2.0
"""Read-only runtime preflight status for the Product API.

Runs ``sndr.compat.preflight_checks.run_all_preflight_checks`` against the RUNNING
engine: the PN60 quantization-arg validator (reads the model's config.json) plus
the club#43 grammar-rejection and club#34 spec-decode token-loop log scans. The
daemon resolves the engine container + its model dir from the live process argv
(the model files are visible via the read-only /models mount).

Fail-safe: a missing engine, an unreadable model dir, or any check error yields a
structured payload with an ``error`` tag, never a 500 — same contract as the
other read-only patches endpoints.
"""
from __future__ import annotations

import dataclasses
import json
import re
import urllib.parse
from typing import Any, Optional


def _running_engine_target() -> tuple[Optional[str], Optional[str]]:
    """Resolve (container_name, model_dir) for the engine on the configured port.

    container from the managed-container list on the port; model_dir from the
    running ``vllm serve <path>`` argv (the launcher is bind-mounted and the
    archive API cannot export it, but the final argv is on the live process)."""
    from .. import container_ops as co
    from .. import engine_client as ec

    eng = ec.resolve_engine()
    port = ec._engine_port_from_base_url(eng.get("base_url", ""))
    if not port:
        return None, None
    ctl = co.SocketContainerControl()
    name = next(
        (c.name for c in ctl._raw_list()
         if co.is_managed_name(c.name) and re.search(rf"(^|[ ,]){port}->", c.ports or "")),
        None,
    )
    if not name:
        return None, None
    model_dir: Optional[str] = None
    try:
        q = urllib.parse.quote(name, safe="")
        status, raw = ctl._transport("GET", f"/containers/{q}/top?ps_args=aux")
        if status == 200 and raw:
            text = raw if isinstance(raw, str) else raw.decode("utf-8", "replace")
            rows = json.loads(text).get("Processes") or []
            joined = "\n".join(" ".join(str(c) for c in row) for row in rows)
            m = re.search(r"serve\s+(/\S+)", joined)
            model_dir = m.group(1) if m else None
    except Exception:  # noqa: BLE001 - best-effort; model_dir stays None
        model_dir = None
    return name, model_dir


def preflight_status() -> dict[str, Any]:
    """Return ``{checks[], counts{severity:n}, container, model_dir}`` for the
    running engine. Each check is ``{name, severity, message, remediation}``."""
    try:
        from sndr.compat.preflight_checks import run_all_preflight_checks

        container, model_dir = _running_engine_target()
        if not container:
            return {"checks": [], "counts": {}, "container": None,
                    "model_dir": None, "error": "no_running_engine"}
        results = run_all_preflight_checks(
            cli_quantization=None, model_dir=model_dir, container_name=container,
        )
        checks = [dataclasses.asdict(r) for r in results]
        counts: dict[str, int] = {}
        for c in checks:
            sev = str(c.get("severity") or "OK")
            counts[sev] = counts.get(sev, 0) + 1
        return {"checks": checks, "counts": counts,
                "container": container, "model_dir": model_dir}
    except Exception as exc:  # noqa: BLE001 - best-effort; never break the API
        return {"checks": [], "counts": {}, "container": None,
                "model_dir": None, "error": type(exc).__name__}
