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

import argparse
import sys


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

    def execute(self, args: argparse.Namespace) -> int:
        def out(msg: str = "") -> None:
            print(msg, file=sys.stderr)

        host = args.host
        port = args.port
        preset_id = args.preset
        if port is None:
            port = _port_for_preset(preset_id)

        # Probe first so an unreachable engine gives a friendly pointer instead
        # of failing on the first turn.
        from sndr.product_api.legacy import engine_client

        status = engine_client.engine_status(host, port=port, timeout=3.0)
        if not status.get("reachable"):
            detail = status.get("error") or "no /health response"
            out(f"sndr chat: no engine reachable at {host}:{port} ({detail}).")
            if preset_id:
                out(f"  start it with:  sndr run {preset_id}")
            else:
                out("  start one with:  sndr run   (or `sndr` to pick a preset)")
            return 1

        from sndr.cli.chat_repl import chat_loop

        return chat_loop(host, port, preset_id=preset_id)


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
