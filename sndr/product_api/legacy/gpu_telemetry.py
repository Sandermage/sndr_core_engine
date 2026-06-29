# SPDX-License-Identifier: Apache-2.0
"""Comprehensive GPU + host hardware telemetry for the GUI Hardware view.

Pulls a rich ``nvidia-smi`` query — utilisation, memory, temperature, power vs
limits, clocks (gpu/mem/sm + max), fan, PCIe link gen/width, pstate, ECC error
counts, driver/vbios — plus CPU/RAM facts, for the local daemon host or a remote
host over the existing SSH transport. Read-only; no mutation.

The command is built as an argv list (never a shell string) for the local path,
and shell-quoted for the SSH path, so a hostile field name can't inject. The
cleaned output keys mirror the proxy dashboard's schema so a shared visual layer
can render either source.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

# nvidia-smi --query-gpu fields, in order. Output keys are cleaned below.
_QUERY_FIELDS = (
    "name,uuid,serial,driver_version,vbios_version,"
    "memory.used,memory.total,memory.free,"
    "utilization.gpu,utilization.memory,"
    "temperature.gpu,temperature.memory,"
    "power.draw,power.default_limit,power.max_limit,power.min_limit,"
    "fan.speed,"
    "pcie.link.gen.current,pcie.link.gen.max,"
    "pcie.link.width.current,pcie.link.width.max,"
    "clocks.current.graphics,clocks.max.graphics,"
    "clocks.current.memory,clocks.max.memory,clocks.current.sm,"
    "compute_mode,pstate,"
    "ecc.errors.corrected.volatile.total,"
    "ecc.errors.uncorrected.volatile.total"
)

# (clean_key, converter) per field, matched positionally to _QUERY_FIELDS.
_F = "f"   # float
_I = "i"   # int
_S = "s"   # str (pass-through, N/A -> None)
_FIELDS: tuple[tuple[str, str], ...] = (
    ("name", _S), ("uuid", _S), ("serial", _S), ("driver_version", _S), ("vbios_version", _S),
    ("mem_used", _F), ("mem_total", _F), ("mem_free", _F),
    ("gpu_util", _I), ("mem_util", _I),
    ("temp_gpu", _I), ("temp_mem", _S),
    ("power", _F), ("power_default_limit", _F), ("power_max_limit", _F), ("power_min_limit", _F),
    ("fan_speed", _I),
    ("pcie_gen", _I), ("pcie_gen_max", _I),
    ("pcie_width", _I), ("pcie_width_max", _I),
    ("clock_gpu", _I), ("clock_gpu_max", _I),
    ("clock_mem", _I), ("clock_mem_max", _I), ("clock_sm", _I),
    ("compute_mode", _S), ("pstate", _S),
    ("ecc_corrected", _S), ("ecc_uncorrected", _S),
)

_NA = ("", "[N/A]", "N/A", "[Not Supported]", "[Unknown Error]")

# argv for the local subprocess path; the SSH path joins+quotes the same tokens.
GPU_ARGV: tuple[str, ...] = (
    "nvidia-smi", f"--query-gpu={_QUERY_FIELDS}", "--format=csv,noheader,nounits",
)

# A command runner: takes argv, returns (exit_code, stdout, stderr). Lets the
# same parser serve local (subprocess) and remote (SSH) transports.
Runner = Callable[[list[str]], "tuple[int, str, str]"]


def _clean(v: str) -> Optional[str]:
    v = v.strip()
    return v if v and v not in _NA else None


def _f(v: str) -> Optional[float]:
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _i(v: str) -> Optional[int]:
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def parse_gpu_csv(text: str) -> list[dict[str, Any]]:
    """Parse ``nvidia-smi`` CSV (noheader,nounits) rows into cleaned GPU dicts."""
    gpus: list[dict[str, Any]] = []
    for line in text.strip().splitlines():
        cells = [c.strip() for c in line.split(",")]
        if len(cells) < len(_FIELDS):
            continue
        row: dict[str, Any] = {}
        for idx, (key, kind) in enumerate(_FIELDS):
            raw = cells[idx]
            row[key] = _clean(raw) if kind == _S else _f(raw) if kind == _F else _i(raw)
        gpus.append(row)
    return gpus


_CPU_RE = re.compile(r"model name\s*:\s*(.+)")
_MEMTOTAL_RE = re.compile(r"MemTotal:\s+(\d+)")
_MEMAVAIL_RE = re.compile(r"MemAvailable:\s+(\d+)")


def parse_system(cpuinfo: str, meminfo: str, *, hostname: str = "", cpu_count: Optional[int] = None) -> dict[str, Any]:
    """Build a system facts dict from /proc/cpuinfo + /proc/meminfo text."""
    out: dict[str, Any] = {"hostname": hostname or None, "cpu_count": cpu_count}
    m = _CPU_RE.search(cpuinfo or "")
    out["cpu"] = m.group(1).strip() if m else None
    mt = _MEMTOTAL_RE.search(meminfo or "")
    ma = _MEMAVAIL_RE.search(meminfo or "")
    if mt:
        total = int(mt.group(1))
        out["ram_total_gb"] = round(total / 1024 / 1024, 1)
        if ma:
            avail = int(ma.group(1))
            out["ram_available_gb"] = round(avail / 1024 / 1024, 1)
            out["ram_used_gb"] = round((total - avail) / 1024 / 1024, 1)
    return out


def _kb_to_gb(kb: Optional[float]) -> Optional[float]:
    return round(kb / 1024 / 1024, 1) if kb is not None else None


def parse_net(netdev: str, ip_line: str = "") -> dict[str, Any]:
    """Parse /proc/net/dev into per-interface cumulative RX/TX byte counters.

    Counters are cumulative since boot; the GUI diffs successive polls to derive
    live throughput. The first address from ``hostname -I`` is the primary IP.
    """
    ifaces: list[dict[str, Any]] = []
    for line in (netdev or "").splitlines():
        if ":" not in line:
            continue  # skip the two header rows
        name, _, rest = line.partition(":")
        name = name.strip()
        if not name or name == "lo":
            continue
        cols = rest.split()
        if len(cols) < 16:
            continue
        rx, tx = _i(cols[0]), _i(cols[8])
        if rx is None or tx is None:
            continue
        ifaces.append({"name": name, "rx_bytes": rx, "tx_bytes": tx})
    ifaces.sort(key=lambda d: d["rx_bytes"] + d["tx_bytes"], reverse=True)
    parts = (ip_line or "").split()
    return {"interfaces": ifaces[:4], "primary_ip": parts[0] if parts else None}


def parse_disk(df_text: str) -> Optional[dict[str, Any]]:
    """Parse ``df -kP <mount>`` (1K blocks, POSIX) into total/used/free GB."""
    lines = [ln for ln in (df_text or "").splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    cols = lines[1].split()
    if len(cols) < 6:
        return None
    total, used, avail = _f(cols[1]), _f(cols[2]), _f(cols[3])
    if total is None:
        return None
    out: dict[str, Any] = {
        "mount": cols[5],
        "total_gb": _kb_to_gb(total),
        "used_gb": _kb_to_gb(used),
        "free_gb": _kb_to_gb(avail),
    }
    if total and used is not None:
        out["used_pct"] = round(used / total * 100, 1)
    return out


@dataclass(frozen=True)
class HardwareTelemetry:
    gpus: tuple[dict[str, Any], ...]
    system: dict[str, Any]
    error: Optional[str] = None


def collect(run: Runner) -> HardwareTelemetry:
    """Collect GPU + system telemetry through a command runner (local or SSH)."""
    gpus: tuple[dict[str, Any], ...] = ()
    error: Optional[str] = None
    try:
        rc, out, err = run(list(GPU_ARGV))
        if rc == 0 and out.strip():
            gpus = tuple(parse_gpu_csv(out))
        else:
            error = (err or "").strip() or "nvidia-smi returned no GPUs (no device or not permitted)"
    except Exception as exc:  # noqa: BLE001 — best-effort probe
        error = f"{type(exc).__name__}: {exc}"

    system: dict[str, Any] = {}
    try:
        _, cpuinfo, _ = run(["cat", "/proc/cpuinfo"])
        _, meminfo, _ = run(["cat", "/proc/meminfo"])
        _, host_out, _ = run(["hostname"])
        _, nproc_out, _ = run(["nproc"])
        system = parse_system(
            cpuinfo, meminfo,
            hostname=host_out.strip(),
            cpu_count=_i(nproc_out.strip()),
        )
    except Exception:  # noqa: BLE001
        pass

    # OS/kernel string (uname -srm: e.g. "Linux 6.8.0 x86_64").
    try:
        _, uname_out, _ = run(["uname", "-srm"])
        if uname_out.strip():
            system["platform"] = uname_out.strip()
    except Exception:  # noqa: BLE001
        pass

    # Network — best-effort, independent of the CPU/RAM probe above.
    try:
        _, netdev, _ = run(["cat", "/proc/net/dev"])
        _, ip_out, _ = run(["hostname", "-I"])
        net = parse_net(netdev, ip_out)
        if net["interfaces"] or net["primary_ip"]:
            system["net"] = net["interfaces"]
            system["primary_ip"] = net["primary_ip"]
    except Exception:  # noqa: BLE001
        pass

    # Root filesystem free space (the container's / when daemon runs in one).
    try:
        _, df_out, _ = run(["df", "-kP", "/"])
        disk = parse_disk(df_out)
        if disk:
            system["disk"] = disk
    except Exception:  # noqa: BLE001
        pass

    return HardwareTelemetry(gpus=gpus, system=system, error=error)


def _run_in_engine(argv: list[str]) -> "tuple[int, str, str]":
    """Run ``nvidia-smi`` in the RUNNING engine container (which has the GPU
    runtime) when the daemon itself has none — the containerized-daemon case. Only
    the GPU query is delegated; other commands (``/proc`` reads) stay local. A
    fixed read-only exec, not the operator exec endpoint, so no SNDR_ENABLE_EXEC.
    Returns 127 if there is no engine or the command is not nvidia-smi."""
    if not argv or "nvidia-smi" not in str(argv[0]):
        return 127, "", f"{argv[0] if argv else ''}: not found"
    try:
        from . import container_ops as co
        from .patches.apply_summary import _running_engine_name

        name = _running_engine_name()
        if not name:
            return 127, "", "no running engine container with a GPU runtime"
        res = co.SocketContainerControl().exec(name, list(argv), timeout=15.0)
        return res.exit_code, res.stdout, res.stderr
    except Exception as exc:  # noqa: BLE001
        return 127, "", f"{type(exc).__name__}: {exc}"


def _sysctl(key: str) -> str:
    import subprocess

    try:
        p = subprocess.run(["sysctl", "-n", key], capture_output=True, text=True, timeout=4)
        return p.stdout.strip() if p.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


def _collect_macos() -> HardwareTelemetry:
    """macOS hardware facts via sysctl/system_profiler (no nvidia-smi, no /proc).
    Apple Silicon has an integrated GPU sharing unified memory, so the 'GPU' is the
    chip + its unified RAM; live util/temp/power are not exposed without privileged
    powermetrics, so those stay null (the GUI shows them as N/A)."""
    import platform as _pf
    import socket
    import subprocess

    chip = _sysctl("machdep.cpu.brand_string") or _sysctl("hw.model") or "Apple Silicon"
    mem_bytes = _i(_sysctl("hw.memsize"))
    mem_mib = int(mem_bytes / 1024 / 1024) if mem_bytes else None
    ncpu = _i(_sysctl("hw.logicalcpu")) or _i(_sysctl("hw.ncpu"))
    gpu_cores: Optional[int] = None
    try:  # GPU core count — best-effort; system_profiler is slow, so keep it bounded.
        p = subprocess.run(["system_profiler", "SPDisplaysDataType"], capture_output=True, text=True, timeout=6)
        m = re.search(r"Total Number of Cores:\s*(\d+)", p.stdout or "")
        gpu_cores = _i(m.group(1)) if m else None
    except Exception:  # noqa: BLE001
        pass
    apple = chip.startswith("Apple")
    gpu = {
        "name": (f"{chip} GPU" + (f" · {gpu_cores}-core" if gpu_cores else "")) if apple else chip,
        "mem_total": mem_mib, "mem_used": None, "mem_free": None,
        "gpu_util": None, "mem_util": None, "temp_gpu": None, "power": None,
    }
    system: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "cpu": chip, "cpu_count": ncpu,
        "ram_total_gb": round(mem_bytes / 1e9, 1) if mem_bytes else None,
        "platform": f"{_pf.system()} {_pf.release()} {_pf.machine()}".strip(),
        "apple_silicon": apple,
    }
    return HardwareTelemetry(gpus=(gpu,), system=system, error=None)


def collect_local() -> HardwareTelemetry:
    """Collect from the daemon host. macOS → sysctl/system_profiler (Apple Silicon);
    Linux → nvidia-smi via subprocess, falling back to the running engine container
    when the daemon (a management container) has no GPU runtime of its own."""
    import platform
    import subprocess

    if platform.system() == "Darwin":
        return _collect_macos()

    def run(argv: list[str]) -> "tuple[int, str, str]":
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=8)
            if p.returncode == 127:  # not found on the daemon → try the engine
                return _run_in_engine(argv)
            return p.returncode, p.stdout, p.stderr
        except FileNotFoundError:
            return _run_in_engine(argv)
        except subprocess.TimeoutExpired:
            return 124, "", f"{argv[0]}: timed out"

    return collect(run)


def collect_remote(target: dict[str, Any], *, timeout: float = 10.0) -> HardwareTelemetry:
    """Collect from a remote host over SSH. One connection, reused per command;
    each argv token is shell-quoted before it reaches the remote shell."""
    import shlex

    from . import ssh_client

    if not ssh_client.available():
        return HardwareTelemetry(gpus=(), system={}, error="paramiko not installed on the daemon host")
    client = ssh_client._open_client(target, timeout)  # noqa: SLF001 — same-package transport
    try:
        def run(argv: list[str]) -> "tuple[int, str, str]":
            cmd = " ".join(shlex.quote(tok) for tok in argv)
            return ssh_client._exec(client, cmd, timeout)  # noqa: SLF001

        return collect(run)
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass
