# SPDX-License-Identifier: Apache-2.0
"""GPU power-limit WRITE path for the Hardware view (the cap CONTROL).

The Hardware view already DISPLAYS each GPU's power draw vs its min/default/max
limit (see ``gpu_telemetry.py``). This module is the missing WRITE half: apply a
power cap to one GPU or all of them, mirroring club-3090's ``gpu-mode power-cap``
contract — a numeric wattage validated against each card's ``[min,max]`` range,
or a reset that reads each card's hardware ``default_limit`` and re-applies it
(``nvidia-smi`` has no "reset" flag, so the default value is passed explicitly).

This is a PRIVILEGED host mutation. The HTTP routes that call it are double-gated
(``SNDR_ENABLE_APPLY`` + an explicit ``confirm: true``), exactly like the other
mutating endpoints. The cap is session-scoped: a reboot or driver reload reverts
to whatever the host's own boot policy enforces — applying a cap here never
persists state on the host.

Like ``gpu_telemetry``, the work is expressed against a ``Runner`` abstraction so
the same validation + apply logic serves the local (subprocess, no shell) and the
remote (SSH, shell-quoted) transports. Watts are always validated server-side
against the live per-GPU ``[min,max]`` read from ``nvidia-smi`` — the request's
bounds are never trusted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

# A command runner: argv -> (exit_code, stdout, stderr). Shared with the local
# (subprocess) and remote (SSH) transports, identical to gpu_telemetry.Runner.
Runner = Callable[[list[str]], "tuple[int, str, str]"]

# nvidia-smi query for the per-GPU limits we validate against and report back.
_LIMITS_FIELDS = "index,power.limit,power.default_limit,power.min_limit,power.max_limit"
_LIMITS_ARGV: tuple[str, ...] = (
    "nvidia-smi",
    f"--query-gpu={_LIMITS_FIELDS}",
    "--format=csv,noheader,nounits",
)

_NA = ("", "[N/A]", "N/A", "[Not Supported]", "[Unknown Error]")


class PowerCapError(Exception):
    """A power-cap request that cannot be satisfied (bad value, no GPU, apply
    failure). ``status`` maps to the HTTP code the route should return."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _num(v: str) -> Optional[float]:
    v = v.strip()
    if v in _NA:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class GpuLimits:
    """Live per-GPU power limits read from nvidia-smi (watts; min/max are the
    hard bounds we validate a requested cap against)."""

    index: int
    limit: Optional[float]
    default_limit: Optional[float]
    min_limit: Optional[float]
    max_limit: Optional[float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "limit": self.limit,
            "default_limit": self.default_limit,
            "min_limit": self.min_limit,
            "max_limit": self.max_limit,
        }


@dataclass(frozen=True)
class GpuCapResult:
    """Outcome of applying a cap to one GPU: the value attempted plus the live
    limits read back afterwards (so the GUI can refresh from the truth)."""

    index: int
    requested_watts: int
    applied: bool
    error: Optional[str] = None
    limits: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "requested_watts": self.requested_watts,
            "applied": self.applied,
            "error": self.error,
            "limits": self.limits,
        }


@dataclass(frozen=True)
class PowerCapOutcome:
    """Aggregate result returned to the route: per-GPU results + the live limits
    after the operation, so the caller never has to guess the new state."""

    ok: bool
    action: str  # "set" | "reset"
    results: tuple[GpuCapResult, ...] = ()
    limits: tuple[dict[str, Any], ...] = ()
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "action": self.action,
            "results": [r.to_dict() for r in self.results],
            "limits": list(self.limits),
            "error": self.error,
        }


def read_limits(run: Runner) -> list[GpuLimits]:
    """Read each GPU's enforced/default/min/max power limit (watts) via a runner.

    Raises :class:`PowerCapError` when nvidia-smi is unavailable or reports no
    device — the same failure modes the telemetry path degrades on, but here a
    mutation can't proceed without them, so it is an error rather than a soft
    empty state."""
    try:
        rc, out, err = run(list(_LIMITS_ARGV))
    except Exception as exc:  # noqa: BLE001 — surface as a structured error
        raise PowerCapError(f"failed to run nvidia-smi: {exc}", status=502) from exc
    if rc != 0:
        msg = (err or "").strip() or "nvidia-smi returned no GPUs (no device or not permitted)"
        raise PowerCapError(msg, status=502)
    gpus: list[GpuLimits] = []
    for line in (out or "").strip().splitlines():
        cells = [c.strip() for c in line.split(",")]
        if len(cells) < 5:
            continue
        idx = _num(cells[0])
        if idx is None:
            continue
        gpus.append(
            GpuLimits(
                index=int(idx),
                limit=_num(cells[1]),
                default_limit=_num(cells[2]),
                min_limit=_num(cells[3]),
                max_limit=_num(cells[4]),
            )
        )
    if not gpus:
        raise PowerCapError("nvidia-smi reported no GPUs on this host", status=502)
    return gpus


def _target_gpus(gpus: list[GpuLimits], gpu_index: Optional[int]) -> list[GpuLimits]:
    if gpu_index is None:
        return gpus
    match = [g for g in gpus if g.index == gpu_index]
    if not match:
        raise PowerCapError(f"GPU index {gpu_index} not present on this host", status=404)
    return match


def _validate_watts(watts: int, g: GpuLimits) -> None:
    """Reject a cap outside the card's live [min,max] (club-3090's contract).

    nvidia-smi itself rejects out-of-range values, but validating up front gives
    a precise per-card error and never shells out a doomed command."""
    if g.min_limit is not None and watts < g.min_limit:
        raise PowerCapError(
            f"GPU {g.index}: {watts}W is below the card minimum "
            f"{int(g.min_limit)}W (range {int(g.min_limit)}–"
            f"{int(g.max_limit) if g.max_limit is not None else '?'}W)"
        )
    if g.max_limit is not None and watts > g.max_limit:
        raise PowerCapError(
            f"GPU {g.index}: {watts}W exceeds the card maximum "
            f"{int(g.max_limit)}W (range "
            f"{int(g.min_limit) if g.min_limit is not None else '?'}–"
            f"{int(g.max_limit)}W)"
        )


def _apply_one(run: Runner, index: int, watts: int) -> tuple[bool, Optional[str]]:
    """Apply a single ``nvidia-smi -i <index> -pl <watts>``. Returns (ok, error)."""
    try:
        rc, _out, err = run(["nvidia-smi", "-i", str(index), "-pl", str(watts)])
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    if rc != 0:
        msg = (err or "").strip() or f"nvidia-smi exited {rc}"
        # The classic cause is missing privilege — make it actionable.
        if "permission" in msg.lower() or "privilege" in msg.lower():
            msg += " (the daemon process needs root / CAP_SYS_ADMIN to set power limits)"
        return False, msg
    return True, None


def apply_cap(
    run: Runner,
    *,
    watts: Optional[int] = None,
    reset: bool = False,
    gpu_index: Optional[int] = None,
) -> PowerCapOutcome:
    """Validate and apply a GPU power cap through a runner (local or remote).

    Exactly one of ``watts`` (a custom cap) or ``reset`` (restore each card's
    hardware default) must be given. ``gpu_index`` restricts to one card; omit it
    to apply to every GPU. Always re-reads the live limits afterwards so the
    returned outcome reflects the host's actual state, not the request's intent.
    """
    if reset and watts is not None:
        raise PowerCapError("specify either a watts value or reset, not both")
    if not reset and watts is None:
        raise PowerCapError("a watts value is required unless reset is requested")

    gpus = read_limits(run)
    targets = _target_gpus(gpus, gpu_index)

    # Validate every target up front (set path) so we fail before mutating any
    # card when one value is out of range.
    if not reset:
        assert watts is not None  # narrowed by the guards above
        if watts < 1:
            raise PowerCapError("watts must be a positive integer")
        for g in targets:
            _validate_watts(int(watts), g)

    results: list[GpuCapResult] = []
    for g in targets:
        if reset:
            if g.default_limit is None:
                results.append(GpuCapResult(
                    index=g.index, requested_watts=0, applied=False,
                    error="card reports no default power limit; cannot reset"))
                continue
            value = int(round(g.default_limit))
        else:
            assert watts is not None
            value = int(watts)
        ok, err = _apply_one(run, g.index, value)
        results.append(GpuCapResult(index=g.index, requested_watts=value, applied=ok, error=err))

    # Re-read so the caller gets the truth (and per-GPU limits to attach).
    try:
        after = {g.index: g.to_dict() for g in read_limits(run)}
    except PowerCapError:
        after = {}
    enriched = tuple(
        GpuCapResult(
            index=r.index, requested_watts=r.requested_watts, applied=r.applied,
            error=r.error, limits=after.get(r.index),
        )
        for r in results
    )
    ok = bool(enriched) and all(r.applied for r in enriched)
    return PowerCapOutcome(
        ok=ok,
        action="reset" if reset else "set",
        results=enriched,
        limits=tuple(after.values()),
        error=None if ok else "; ".join(r.error for r in enriched if r.error) or None,
    )


# ── Transports ──────────────────────────────────────────────────────────────

def _local_runner() -> Runner:
    """Subprocess runner (argv list — never a shell string)."""
    import subprocess

    def run(argv: list[str]) -> "tuple[int, str, str]":
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=15)
            return p.returncode, p.stdout, p.stderr
        except FileNotFoundError:
            return 127, "", f"{argv[0]}: not found"
        except subprocess.TimeoutExpired:
            return 124, "", f"{argv[0]}: timed out"

    return run


def apply_cap_local(
    *, watts: Optional[int] = None, reset: bool = False, gpu_index: Optional[int] = None,
) -> PowerCapOutcome:
    """Apply a cap on the daemon host via subprocess."""
    return apply_cap(_local_runner(), watts=watts, reset=reset, gpu_index=gpu_index)


def apply_cap_remote(
    target: dict[str, Any],
    *,
    watts: Optional[int] = None,
    reset: bool = False,
    gpu_index: Optional[int] = None,
    timeout: float = 15.0,
) -> PowerCapOutcome:
    """Apply a cap on a registered host over SSH. One connection reused for the
    read-validate-apply-reread sequence; each argv token is shell-quoted before
    it reaches the remote shell (no field can inject)."""
    import shlex

    from . import ssh_client

    if not ssh_client.available():
        raise PowerCapError("paramiko not installed on the daemon host", status=503)
    client = ssh_client._open_client(target, timeout)  # noqa: SLF001 — same-package transport
    try:
        def run(argv: list[str]) -> "tuple[int, str, str]":
            cmd = " ".join(shlex.quote(tok) for tok in argv)
            return ssh_client._exec(client, cmd, timeout)  # noqa: SLF001

        return apply_cap(run, watts=watts, reset=reset, gpu_index=gpu_index)
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


__all__ = [
    "GpuCapResult",
    "GpuLimits",
    "PowerCapError",
    "PowerCapOutcome",
    "Runner",
    "apply_cap",
    "apply_cap_local",
    "apply_cap_remote",
    "read_limits",
]
