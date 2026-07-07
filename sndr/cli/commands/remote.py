# SPDX-License-Identifier: Apache-2.0
"""CLI command: ``sndr remote setup <url>`` — client-mode onboarding (GAP 1).

The engine needs Linux + CUDA, so Mac/Windows operators drive the ``sndr`` CLI
and the Control Center GUI against a REMOTE rig engine. This command configures
THIS machine to do that in one line: it validates the base URL, probes the
remote (best-effort), remembers the choice, and prints the three canonical
exports the rest of the stack reads.

  sndr remote setup http://192.168.1.10:8102/v1 --key genesis-local

  * URL is validated to the ``http(s)://host:port/v1`` form — a bad URL is a
    loud typed refusal (GUARD-1, exit 64 / ``EX_USAGE``), never a silent
    misconfig.
  * Reachability is probed best-effort — an unreachable rig WARNS but still
    prints the exports (you may be setting up before the rig is on).
  * The choice is cached via :mod:`sndr.cli.user_prefs` (DEFAULT-4); with
    ``--write-env`` the remote block is also written to ``./.env``.
  * The three exports (``SNDR_OPENAI_BASE_URL`` / ``SNDR_ENGINE_API_KEY`` /
    ``GENESIS_MEMORY_DSN``) are printed with a "shell env wins" note. When the
    memory DSN is not reachable, the command says so out loud instead of
    letting the daemon fall back silently to ephemeral in-memory storage.
"""
from __future__ import annotations

import argparse  # noqa: TC003 — Namespace typing on the public execute() seam
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sndr.cli import user_prefs
from sndr.cli._messages import Emitter

_EX_USAGE = 64  # BSD sysexits.h — a usage/typed-refusal error
_DEFAULT_KEY = "genesis-local"


class RemoteSetupCommand:
    name = "remote"
    help = "Configure this machine to drive a remote rig engine (Mac/Windows client mode)."

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        sub = parser.add_subparsers(dest="remote_cmd", metavar="SUBCOMMAND")
        setup = sub.add_parser(
            "setup", help="Point this machine at a remote rig engine URL.",
        )
        setup.add_argument(
            "url", help="Remote engine base URL, e.g. http://192.168.1.10:8102/v1",
        )
        setup.add_argument(
            "--key", default=_DEFAULT_KEY, metavar="API_KEY",
            help=f"Engine API key for the remote (default: {_DEFAULT_KEY}).",
        )
        setup.add_argument(
            "--dsn", default=None, metavar="PGVECTOR_DSN",
            help="Postgres+pgvector DSN for persistent neural-graph memory.",
        )
        setup.add_argument(
            "--write-env", action="store_true",
            help="Also write the remote block to ./.env (save-my-choice).",
        )

    def execute(self, args: argparse.Namespace) -> int:
        em = Emitter()  # advisory output → stderr (stdout carries the exports)

        if getattr(args, "remote_cmd", None) != "setup":
            em.err("usage: sndr remote setup <url> [--key ...] [--dsn ...] [--write-env]")
            return _EX_USAGE

        url = str(getattr(args, "url", "") or "").strip()
        parsed = _validate_url(url)
        if parsed is None:
            em.err(f"not a valid engine URL: {url!r}")
            em.hint("expected form:  http(s)://<host>:<port>/v1")
            em.hint("example:        sndr remote setup http://192.168.1.10:8102/v1")
            return _EX_USAGE

        host, port = parsed
        key = str(getattr(args, "key", None) or _DEFAULT_KEY)
        dsn = getattr(args, "dsn", None)

        # Probe reachability — best-effort; warn (do not fail) so the exports
        # print even when the rig is not up yet.
        em.blank()
        status = _probe_remote(host, port, key)
        if status.get("reachable"):
            em.ok(f"remote engine reachable at {host}:{port}")
        else:
            detail = status.get("error") or "no /health response"
            em.err(f"remote engine not reachable at {host}:{port} ({detail}) — "
                   "printing the exports anyway.")

        # Persist the choice (DEFAULT-4 caching).
        user_prefs.set_last_remote(url, key=key, dsn=dsn)

        # Optionally write ./.env (save-my-choice ladder).
        if getattr(args, "write_env", False):
            written = _write_dotenv(url, key, dsn)
            em.line(f"  wrote remote block to {written}")

        # The three canonical exports (stdout — scriptable / copy-paste).
        em.blank()
        em.line("  add these to your shell (shell env WINS over the prefs file):")
        print(f"export SNDR_OPENAI_BASE_URL={url}")
        print(f"export SNDR_ENGINE_API_KEY={key}")
        if dsn:
            print(f"export GENESIS_MEMORY_DSN={dsn}")
        else:
            print("# GENESIS_MEMORY_DSN=  (unset → ephemeral in-memory memory; "
                  "set a pgvector DSN to persist)")
        return 0


# ── helpers ──────────────────────────────────────────────────────────────────


def _validate_url(url: str) -> tuple[str, int] | None:  # noqa: PLR0911 — one early-return per URL-form guard reads clearer than a compound boolean

    """Validate the ``http(s)://host:port/v1`` form and return (host, port).

    Returns None on any malformed URL (missing scheme/host/port or non-/v1
    path) so the caller can issue a typed refusal.
    """
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except (ValueError, AttributeError):
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    if not parsed.hostname:
        return None
    port = parsed.port
    if port is None:
        return None
    if parsed.path.rstrip("/") and not parsed.path.rstrip("/").endswith("/v1"):
        return None
    return parsed.hostname, int(port)


def _probe_remote(host: str, port: int, key: str | None) -> dict[str, Any]:
    """Best-effort ``/health`` probe of the remote engine (mocked in tests)."""
    try:
        from sndr.product_api.legacy import engine_client

        return engine_client.engine_status(host, port=port, timeout=3.0, api_key=key)
    except Exception as exc:  # noqa: BLE001 — a probe failure is non-fatal here
        return {"reachable": False, "error": f"{type(exc).__name__}: {exc}"}


def _write_dotenv(url: str, key: str, dsn: str | None) -> Path:
    """Append/refresh the remote block in ``./.env`` and return its path.

    Self-contained (does not read the CONFIG group's ``.env.example``) so the
    two file groups stay disjoint; the block below mirrors that template's
    remote section.
    """
    path = Path.cwd() / ".env"
    existing = ""
    if path.is_file():
        existing = path.read_text(encoding="utf-8")

    block_lines = [
        "# --- sndr remote (client mode) ---",
        f"SNDR_OPENAI_BASE_URL={url}",
        f"SNDR_ENGINE_API_KEY={key}",
    ]
    if dsn:
        block_lines.append(f"GENESIS_MEMORY_DSN={dsn}")
    block = "\n".join(block_lines) + "\n"

    # Drop any prior lines we own, then append a fresh block (idempotent-ish).
    owned = ("SNDR_OPENAI_BASE_URL=", "SNDR_ENGINE_API_KEY=", "GENESIS_MEMORY_DSN=",
             "# --- sndr remote (client mode) ---")
    kept = [ln for ln in existing.splitlines() if not ln.startswith(owned)]
    body = "\n".join(kept).rstrip("\n")
    text = (body + "\n\n" if body else "") + block
    path.write_text(text, encoding="utf-8")
    return path


__all__ = ["RemoteSetupCommand"]
