# SPDX-License-Identifier: Apache-2.0
"""Module-run entry point: ``python -m sndr ...`` mirrors the ``sndr`` console
script.

Lets callers invoke the CLI without the installed console entry on PATH — used
by ``sndr run`` to launch a preset in a child process (so the orchestrator
survives the launcher's ``os.execvp`` and can poll readiness + open the chat).
"""
from __future__ import annotations

import sys

from sndr.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
