# SPDX-License-Identifier: Apache-2.0
"""Genesis PN387 Layer 2 — gateway-edge degenerate structured_outputs guard.

The Genesis extra on top of the PR #45346 source overlay (Layer 1, in
``sndr/engines/vllm/patches/serving/pn387_reject_degenerate_structured_outputs.py``).

Where Layer 1 rejects degenerate ``structured_outputs`` inside
``SamplingParams._validate_structured_outputs`` (deep in request prep),
Layer 2 rejects at the very TOP of ``_create_chat_completion`` — the
gateway edge — so the request never descends toward the engine loop at
all. ``reject_request`` returns an ``ErrorResponse`` (clean 400
``BadRequestError``) which the injected wiring early-returns; on a healthy
request (or when disabled) it returns ``None`` and the request proceeds
unchanged.

DEGENERATE CASES (the exact #45346 DoS triggers):
  • ``request.structured_outputs.json_object is False`` — the flag is set
    but falsy; only ``True`` selects a constraint. Reaches the engine and
    raises ``ValueError`` inside the per-request-isolation-free EngineCore
    step loop → ``EngineDeadError`` → instance-wide DoS.
  • ``request.structured_outputs.json`` is an empty / whitespace-only
    string — passes the ``is not None`` exclusivity check but crashes the
    xgrammar compiler in the same loop.

These arrive via the EXPLICIT ``structured_outputs`` request field. The
``response_format`` convenience path always sets ``json_object=True`` /
a real schema, so it cannot produce these — we therefore inspect
``request.structured_outputs`` directly.

SAFETY MODEL:
  • Opt-in via ``GENESIS_ENABLE_PN387_REJECT_DEGENERATE_STRUCTURED_OUTPUTS``
    (default OFF). Pure safety reject — gate lets us A/B the rejection
    criteria before enabling on PROD. STRONG RECOMMENDATION: enable on
    every single-instance PROD — the unguarded path is a one-request
    kill switch.
  • Never raises: every attribute access is defensive (``getattr``), so a
    malformed request object falls through to ``None`` (request proceeds;
    Layer 1 is the backstop). The wiring wraps the call in try/except too.
  • A legitimate ``json_object=True`` or a non-empty ``json`` schema is
    UNAFFECTED — returns ``None``.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
Original PR: vllm#45346.
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("genesis.middleware.reject_degenerate_structured_outputs")

_ENV_FLAG = "GENESIS_ENABLE_PN387_REJECT_DEGENERATE_STRUCTURED_OUTPUTS"

# Lightweight per-process counters for observability (mirrors the
# lazy_reasoner stats convention). Reset helper provided for tests.
_STATS: dict[str, int] = {
    "rejected_json_object_false": 0,
    "rejected_empty_json": 0,
}


def reset_stats() -> None:
    for k in _STATS:
        _STATS[k] = 0


def get_stats() -> dict[str, int]:
    return dict(_STATS)


def _is_enabled() -> bool:
    """True iff the opt-in env flag is set to a truthy value.

    The dispatcher gate (registry env_flag) controls whether the wiring is
    even injected; this runtime check is the in-band switch so the hook is
    a hard no-op when the flag is unset, even if the wiring is present.
    """
    return os.environ.get(_ENV_FLAG, "").strip().lower() in ("1", "true", "yes", "on")


def _degenerate_reason(structured_outputs: Any) -> tuple[str, str] | None:
    """Return (stat_key, message) if the structured_outputs are degenerate,
    else None. Pure function — does no I/O, never raises."""
    # json_object is a flag: only True selects a constraint. False reaches
    # the engine and dies. (Use `is False` — not `not json_object` — so an
    # unset None / a real json schema is never misread as degenerate.)
    if getattr(structured_outputs, "json_object", None) is False:
        return (
            "rejected_json_object_false",
            "structured_outputs.json_object must be True if set; omit "
            "structured_outputs to disable structured outputs",
        )
    # An empty / whitespace-only json schema string crashes the compiler.
    json_field = getattr(structured_outputs, "json", None)
    if isinstance(json_field, str) and json_field.strip() == "":
        return (
            "rejected_empty_json",
            "structured_outputs.json cannot be an empty string",
        )
    return None


def reject_request(serving: Any, request: Any) -> Any | None:
    """Return an ``ErrorResponse`` (400) iff the request carries degenerate
    ``structured_outputs``, else ``None``. Never raises.

    Called from the top of ``OpenAIServingChat._create_chat_completion``
    via the text-patched hook injection in
    ``patches/middleware/edge_guard_reject_degenerate_structured_outputs.py``.
    The wiring early-returns the ErrorResponse so the request never reaches
    the engine.
    """
    try:
        if not _is_enabled():
            return None
        structured_outputs = getattr(request, "structured_outputs", None)
        if structured_outputs is None:
            return None
        verdict = _degenerate_reason(structured_outputs)
        if verdict is None:
            return None
        stat_key, message = verdict
        _STATS[stat_key] += 1
        log.warning(
            "Genesis PN387 edge guard rejected a degenerate "
            "structured_outputs request at the gateway edge (%s): %s",
            stat_key,
            message,
        )
        # create_error_response builds an ErrorResponse with HTTP 400 /
        # BadRequestError (vllm OpenAIServing base). The serving method's
        # existing `if isinstance(result, ErrorResponse): return result`
        # contract carries it to the client as a clean 400.
        return serving.create_error_response(
            message=message,
            err_type="BadRequestError",
            param="structured_outputs",
        )
    except Exception:
        # Defence: a malformed request / serving object must never turn the
        # edge guard itself into a failure. Fall through — Layer 1
        # (_validate_structured_outputs) remains the backstop.
        log.debug(
            "Genesis PN387 edge guard raised; ignored (Layer 1 backstops)",
            exc_info=True,
        )
        return None
