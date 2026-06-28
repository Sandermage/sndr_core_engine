# SPDX-License-Identifier: Apache-2.0
"""``sndr tui`` — read-only terminal cockpit (Phase 1).

A Textual dashboard over the live engine + the fit-ranked preset catalog. Textual
is an optional ``[tui]`` extra: importing this package is cheap (no textual
import here), but :mod:`sndr.cli.tui.app` requires textual — the ``sndr tui``
command gates on it with a friendly install hint.
"""
