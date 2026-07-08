# SPDX-License-Identifier: Apache-2.0
"""install.sh must warn when the `sndr` console script lands off PATH.

After a `--user` pip install the `sndr` entry point is written to the Python
user-scripts dir (~/.local/bin on Linux, ~/Library/Python/X.Y/bin on macOS),
which is frequently not on a fresh PATH. Without a guard, a newcomer's first
documented command (`sndr quickstart`) dies with "command not found".
print_next_steps must detect that and print the remediation.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SH = REPO_ROOT / "install.sh"


def test_next_steps_has_path_guard():
    content = INSTALL_SH.read_text()
    assert "command -v sndr" in content, (
        "install.sh does not check whether `sndr` is on PATH after install"
    )


def test_path_guard_offers_remediation():
    content = INSTALL_SH.read_text()
    assert "-m sndr.cli" in content or "export PATH" in content, (
        "install.sh's PATH guard offers no remediation (export PATH / module form)"
    )
