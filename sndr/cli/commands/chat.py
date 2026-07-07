# SPDX-License-Identifier: Apache-2.0
"""CLI command: ``sndr chat [preset]`` — a thin REPL over a running engine.

The companion to ``sndr run``: when an engine is already up (launched earlier,
or by ``sndr run --no-input``), ``sndr chat`` drops straight into the minimal
interactive chat loop without re-launching anything. It reuses the product-API
engine client's chat proxy via :mod:`sndr.cli.chat_repl`, so it is the same
chat path the GUI uses — a front-end, not a parallel chat engine.

The preset is used only to resolve the engine's port (and to label the banner);
``--port`` overrides it for an engine on a non-default port. If the engine is
not reachable, a friendly pointer explains how to start it (``sndr run``).

Examples::

    sndr chat                              # default port (8000) on localhost
    sndr chat prod-qwen3.6-35b-balanced    # resolve the preset's port
    sndr chat --port 8102                  # an engine on a non-default port
"""
from __future__ import annotations

import argparse  # noqa: TC003 — Namespace typing on the public execute() seam

from sndr.cli._messages import Emitter


class ChatCommand:
    name = "chat"
    help = "Chat with an already-running engine (thin OpenAI-compatible REPL)."

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "preset", nargs="?", default=None,
            help="Preset whose port to chat against (default port 8000).",
        )
        parser.add_argument(
            "--port", type=int, default=None,
            help="Engine port to chat against (overrides the preset's port).",
        )
        parser.add_argument(
            "--host", default="127.0.0.1",
            help="Engine host (default: 127.0.0.1).",
        )
        parser.add_argument(
            "--api-key", default=None,
            help="Engine API key (else $SNDR_ENGINE_API_KEY when a remote is set).",
        )

    def execute(self, args: argparse.Namespace) -> int:
        em = Emitter()  # advisory output → stderr

        host = args.host
        port = args.port
        preset_id = args.preset
        api_key = getattr(args, "api_key", None)

        # Remote client mode (GAP 2): with no explicit host/port/preset, honor a
        # configured remote engine (SNDR_OPENAI_BASE_URL) so a Mac/Windows client
        # chats against the rig instead of the localhost:8000 default. Explicit
        # --host / --port / preset still WIN (this branch is skipped for them).
        if host == "127.0.0.1" and port is None and preset_id is None:
            remote = _remote_from_env()
            if remote is not None:
                host, port, env_key = remote
                if api_key is None:
                    api_key = env_key

        if port is None:
            port = _port_for_preset(preset_id)

        # Probe first so an unreachable engine gives a friendly pointer instead
        # of failing on the first turn.
        from sndr.product_api.legacy import engine_client

        status = engine_client.engine_status(host, port=port, timeout=3.0, api_key=api_key)
        if not status.get("reachable"):
            detail = status.get("error") or "no /health response"
            em.line(f"sndr chat: no engine reachable at {host}:{port} ({detail}).")
            if preset_id:
                em.line(f"  start it with:  sndr run {preset_id}")
            else:
                em.line("  start one with:  sndr run   (or `sndr` to pick a preset)")
            return 1

        from sndr.cli.chat_repl import chat_loop

        return chat_loop(host, port, preset_id=preset_id)


def _remote_from_env() -> tuple[str, int, str | None] | None:
    """Parse (host, port, api_key) from the remote-engine env, or None.

    Reads ``SNDR_OPENAI_BASE_URL`` (host/port) and ``SNDR_ENGINE_API_KEY``
    (key). Returns None when no remote is configured or the URL is unparseable
    (the caller then keeps the localhost default path)."""
    import os
    from urllib.parse import urlparse

    base = os.environ.get("SNDR_OPENAI_BASE_URL", "").strip()
    if not base:
        return None
    try:
        parsed = urlparse(base)
    except (ValueError, AttributeError):
        return None
    if not parsed.hostname or parsed.port is None:
        return None
    key = os.environ.get("SNDR_ENGINE_API_KEY", "").strip() or None
    return parsed.hostname, int(parsed.port), key


def _port_for_preset(preset_id: str | None) -> int:
    """Resolve a preset's host port; default to 8000 on any miss."""
    if not preset_id:
        return 8000
    try:
        from sndr.model_configs.registry_v2 import load_alias

        cfg = load_alias(preset_id)
        docker = getattr(cfg, "docker", None)
        if docker is not None and hasattr(docker, "effective_host_port"):
            return int(docker.effective_host_port())
        return int(getattr(cfg, "port", None) or 8000)
    except Exception:
        return 8000


__all__ = ["ChatCommand"]
