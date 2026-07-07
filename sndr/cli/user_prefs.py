# SPDX-License-Identifier: Apache-2.0
"""Per-user preference store — ``$SNDR_HOME/defaults.toml`` (never tracked).

The zero-friction CLI needs to REMEMBER two things between invocations so the
operator does not re-type them: their chosen default preset and the last remote
rig they pointed a client at. This mirrors club-3090's DEFAULT-2 ``.env`` pin
cache, adapted to OUR stack — a small stdlib-only TOML file under the existing
``~/.sndr`` state directory (``SNDR_HOME``), so it is per-user and out of the
repo by location.

Two disciplines are baked in:

  * **DEFAULT-2 slug validation** — :func:`set_default_preset` refuses a preset
    that is not in ``registry_v2.list_presets()`` (a typo can never be pinned).
  * **DEFAULT-4 precedence** — a value in the SHELL ENV
    (``SNDR_DEFAULT_PRESET``) WINS over the file; :func:`resolve_default_preset`
    surfaces which source won so a caller can tell the operator.

Reads prefer stdlib ``tomllib`` (Python 3.11+), fall back to ``tomli`` if it
happens to be installed, and otherwise use a tiny built-in reader that
understands exactly the flat ``[section] key = "value"`` subset :func:`_dumps`
emits (Python 3.10 has no ``tomllib``, and the project supports ``>=3.10``).
Writes use a tiny hand-rolled serializer (the values are preset slugs / URLs /
DSNs — no nested structures), so this module adds no new dependency.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:  # Python 3.11+ ships tomllib in the stdlib.
    import tomllib
except ModuleNotFoundError:  # Python 3.10 — try the tomli backport if present.
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:  # neither available → built-in flat reader below.
        tomllib = None  # type: ignore[assignment]

ENV_DEFAULT_PRESET = "SNDR_DEFAULT_PRESET"

_SECTION_DEFAULTS = "defaults"
_SECTION_REMOTE = "remote"
_SECTION_MODELS = "models"


# ── location ─────────────────────────────────────────────────────────────────


def _sndr_home() -> Path:
    """The state directory (``SNDR_HOME`` override, else ``~/.sndr``) — the same
    convention :class:`sndr.config.SndrConfig` resolves."""
    return Path(os.environ.get("SNDR_HOME") or (Path.home() / ".sndr")).expanduser()


def _prefs_path() -> Path:
    """Absolute path to the per-user prefs file (honors ``SNDR_HOME`` for tests)."""
    return _sndr_home() / "defaults.toml"


# ── raw read / write ─────────────────────────────────────────────────────────


def _read() -> dict[str, Any]:
    path = _prefs_path()
    if not path.is_file():
        return {}
    # A corrupt/unreadable prefs file must never crash the CLI — treat it as
    # empty (the caller falls through to auto-detected defaults).
    # ``tomllib.TOMLDecodeError`` subclasses ``ValueError`` in both stdlib and
    # the tomli backport, so ``(OSError, ValueError)`` covers every reader path
    # without referencing the class when ``tomllib`` is None on bare 3.10.
    try:
        if tomllib is not None:
            with path.open("rb") as handle:
                return tomllib.load(handle)
        return _parse_flat_toml(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _unquote(token: str) -> str:
    """Reverse :func:`_quote` for a TOML basic string; pass bare tokens through."""
    if len(token) < 2 or token[0] != '"' or token[-1] != '"':
        return token
    inner = token[1:-1]
    out: list[str] = []
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch == "\\" and i + 1 < len(inner) and inner[i + 1] in ('"', "\\"):
            out.append(inner[i + 1])
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _parse_flat_toml(text: str) -> dict[str, Any]:
    """Built-in reader for the flat ``[section] key = "value"`` files this module
    writes — the Python 3.10 fallback when neither ``tomllib`` nor ``tomli`` is
    installed. Only the subset :func:`_dumps` emits is understood; anything else
    is ignored so a hand-edited file degrades to empty rather than crashing."""
    result: dict[str, dict[str, Any]] = {}
    section: dict[str, Any] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = result.setdefault(line[1:-1].strip(), {})
            continue
        if section is None or "=" not in line:
            continue
        key, _, value = line.partition("=")
        section[_unquote(key.strip())] = _unquote(value.strip())
    return result


def _quote(value: str) -> str:
    """Serialize a string as a TOML basic string (escape backslash + quote)."""
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _bare_key_ok(key: str) -> bool:
    return bool(key) and all(c.isalnum() or c in "-_" for c in key)


def _dumps(data: dict[str, dict[str, Any]]) -> str:
    """Serialize the flat two-level ``{section: {key: value}}`` prefs mapping."""
    lines: list[str] = []
    for section, body in data.items():
        if not isinstance(body, dict) or not body:
            continue
        lines.append(f"[{section}]")
        for key, value in body.items():
            if value is None:
                continue
            rendered_key = key if _bare_key_ok(key) else _quote(key)
            lines.append(f"{rendered_key} = {_quote(str(value))}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _write(data: dict[str, dict[str, Any]]) -> None:
    path = _prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dumps(data), encoding="utf-8")


# ── preset validation ────────────────────────────────────────────────────────


def _known_presets() -> set[str]:
    try:
        from sndr.model_configs.registry_v2 import list_presets

        return set(list_presets())
    except Exception:  # noqa: BLE001 — registry import must never crash prefs I/O
        return set()


# ── default preset ───────────────────────────────────────────────────────────


def resolve_default_preset(model_key: str | None = None) -> tuple[str | None, str]:
    """Resolve the default preset AND the source that won.

    Precedence (DEFAULT-4): shell env ``SNDR_DEFAULT_PRESET`` > per-model file
    entry > global file entry > nothing. Returns ``(value_or_None, source)``
    where ``source`` is one of ``env:SNDR_DEFAULT_PRESET`` / ``file:models`` /
    ``file:defaults`` / ``unset``. The raw value is returned WITHOUT registry
    validation so the caller can surface a stale pin; :func:`get_default_preset`
    applies the validity filter.
    """
    env = os.environ.get(ENV_DEFAULT_PRESET, "").strip()
    if env:
        return env, f"env:{ENV_DEFAULT_PRESET}"

    data = _read()
    if model_key:
        models = data.get(_SECTION_MODELS, {})
        if isinstance(models, dict) and models.get(model_key):
            return str(models[model_key]), "file:models"

    defaults = data.get(_SECTION_DEFAULTS, {})
    if isinstance(defaults, dict) and defaults.get("preset"):
        return str(defaults["preset"]), "file:defaults"
    return None, "unset"


def get_default_preset(model_key: str | None = None) -> str | None:
    """The default preset if one is set AND still a known preset, else None."""
    value, _ = resolve_default_preset(model_key)
    if value and value in _known_presets():
        return value
    return None


def set_default_preset(preset_id: str) -> None:
    """Pin ``preset_id`` as the operator's default. Validates against the
    registry first (DEFAULT-2 slug validation)."""
    if preset_id not in _known_presets():
        raise ValueError("not a known preset — run `sndr preset list`")
    data = _read()
    defaults = data.get(_SECTION_DEFAULTS)
    if not isinstance(defaults, dict):
        defaults = {}
    defaults["preset"] = preset_id
    data[_SECTION_DEFAULTS] = defaults
    _write(data)


def clear_default_preset() -> None:
    """Remove the pinned default preset (no-op when none is set)."""
    data = _read()
    defaults = data.get(_SECTION_DEFAULTS)
    if isinstance(defaults, dict) and "preset" in defaults:
        del defaults["preset"]
        data[_SECTION_DEFAULTS] = defaults
        _write(data)


# ── last-used remote ─────────────────────────────────────────────────────────


def get_last_remote() -> dict[str, Any] | None:
    """The last remote the operator configured (``{url, key, dsn}``) or None."""
    data = _read()
    remote = data.get(_SECTION_REMOTE)
    if isinstance(remote, dict) and remote.get("url"):
        return {
            "url": str(remote.get("url")),
            "key": (str(remote["key"]) if remote.get("key") else None),
            "dsn": (str(remote["dsn"]) if remote.get("dsn") else None),
        }
    return None


def set_last_remote(url: str, key: str | None = None, dsn: str | None = None) -> None:
    """Cache the last-used remote URL/key/DSN (DEFAULT-4 caching)."""
    data = _read()
    remote: dict[str, Any] = {"url": url}
    if key:
        remote["key"] = key
    if dsn:
        remote["dsn"] = dsn
    data[_SECTION_REMOTE] = remote
    _write(data)


__all__ = [
    "ENV_DEFAULT_PRESET",
    "clear_default_preset",
    "get_default_preset",
    "get_last_remote",
    "resolve_default_preset",
    "set_default_preset",
    "set_last_remote",
    "_prefs_path",
]
