# SPDX-License-Identifier: Apache-2.0
"""GUI ↔ backend contract gate.

The GUI's `api.ts` hand-writes the daemon route paths it calls. This test pins
those paths against the FastAPI app's actual routes so a renamed/removed backend
route (or a typo'd GUI path) fails CI instead of 404-ing at runtime — the
structural-compatibility guard for the two halves of the project.

It extracts every ``/api/...`` literal from api.ts, reduces each to its static
prefix (dropping ``${…}`` path params and ``${query(…)}`` suffixes), and checks a
backend route has that prefix segment-wise (``{param}`` segments are wildcards).
Skips cleanly if the GUI source isn't present (e.g. a backend-only checkout)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

# create_app() instantiates the FastAPI application, so the contract gate can
# only run where the gui-api extra is installed. On the dep-free release CI
# (which installs no fastapi) skip cleanly instead of erroring at create_app().
pytest.importorskip("fastapi")


def _api_ts() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        cand = parent / "gui" / "web" / "src" / "api.ts"
        if cand.is_file():
            return cand
    return None


def _gui_paths(text: str) -> set[str]:
    """Static path prefix of every /api/ literal (before the first ${ or ?).

    Matches the literal between an opening quote/backtick and the SAME closing
    delimiter (backreference), so it never runs past the string into trailing code."""
    out: set[str] = set()
    for m in re.finditer(r"""(["'`])(/api/(?:(?!\1).)*)\1""", text):
        raw = m.group(2)
        prefix = re.split(r"\$\{|\?", raw)[0].rstrip("/")
        if prefix and prefix != "/api":
            out.add(prefix)
    return out


def _seg_prefix_match(prefix: str, route: str) -> bool:
    ps = [s for s in prefix.strip("/").split("/") if s]
    rs = [s for s in route.strip("/").split("/") if s]
    if len(ps) > len(rs):
        return False
    return all(p == r or r.startswith("{") for p, r in zip(ps, rs))


def test_every_gui_api_path_has_a_backend_route():
    api_ts = _api_ts()
    if api_ts is None:
        pytest.skip("gui/web/src/api.ts not present (backend-only checkout)")
    from sndr.product_api.legacy.http_app import create_app

    app = create_app()
    routes = [r.path for r in app.routes if isinstance(getattr(r, "path", None), str) and r.path.startswith("/api/")]
    assert routes, "app exposed no /api/ routes"
    gui_paths = _gui_paths(api_ts.read_text(encoding="utf-8"))
    assert len(gui_paths) > 30, f"suspiciously few GUI paths parsed ({len(gui_paths)}) — parser drift?"
    missing = sorted(p for p in gui_paths if not any(_seg_prefix_match(p, r) for r in routes))
    assert not missing, (
        f"GUI api.ts calls {len(missing)} path(s) with no matching backend route "
        f"(drift — fix the route or the GUI):\n  " + "\n  ".join(missing))
