# SPDX-License-Identifier: Apache-2.0
"""Read-only apply-summary for the Product API.

The real patch-apply state lives in the ENGINE (patches are spliced at engine
boot, not in the daemon). The robust source — not log-parsing — is the engine's
own self-test: it reports the in-process applied/skipped/failed/warned state.

The daemon runs a FIXED, read-only command in the running engine via the docker
exec API (``python3 -m vllm.sndr_core.compat.cli self-test --json``). This is a
hard-coded diagnostic, NOT the operator-facing arbitrary-exec endpoint, so it
does not require (and does not open) ``SNDR_ENABLE_EXEC``.

Fail-safe: a missing engine or any error yields a structured empty payload with
an ``error`` tag, never a 500.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

_SELF_TEST_ARGV = ["python3", "-m", "vllm.sndr_core.compat.cli", "self-test", "--json"]


def _running_engine_name() -> Optional[str]:
    from .. import container_ops as co
    from .. import engine_client as ec

    eng = ec.resolve_engine()
    port = ec._engine_port_from_base_url(eng.get("base_url", ""))
    if not port:
        return None
    ctl = co.SocketContainerControl()
    return next(
        (c.name for c in ctl._raw_list()
         if co.is_managed_name(c.name) and re.search(rf"(^|[ ,]){port}->", c.ports or "")),
        None,
    )


def apply_summary() -> dict[str, Any]:
    """Return ``{summary{passed,failed,warned,skipped,total}, checks[], container}``
    from the running engine's patch self-test. Each check is ``{name, status,
    message}``."""
    try:
        from .. import container_ops as co

        name = _running_engine_name()
        if not name:
            return {"summary": {}, "checks": [], "container": None, "error": "no_running_engine"}
        ctl = co.SocketContainerControl()
        res = ctl.exec(name, _SELF_TEST_ARGV, timeout=60.0)
        if res.exit_code != 0:
            return {"summary": {}, "checks": [], "container": name,
                    "error": f"self_test_rc_{res.exit_code}"}
        data = json.loads(res.stdout or "{}")
        return {"summary": data.get("summary") or {},
                "checks": data.get("checks") or [], "container": name}
    except Exception as exc:  # noqa: BLE001 - best-effort; never break the API
        return {"summary": {}, "checks": [], "container": None, "error": type(exc).__name__}
