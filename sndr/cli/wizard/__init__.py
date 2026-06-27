# SPDX-License-Identifier: Apache-2.0
"""Interactive terminal wizards for the ``sndr`` CLI.

The pure decision logic lives in :mod:`sndr.cli.wizard.launch_wizard` (no I/O,
fully unit-testable). The terminal-facing orchestration (numbered menus,
prompts, hand-off to the launcher) lives in
:mod:`sndr.cli.commands.launch`.
"""
from __future__ import annotations

__all__: list[str] = []
