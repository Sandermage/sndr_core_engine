# SPDX-License-Identifier: Apache-2.0
"""The ``sndr tui`` Textual application — read-only cockpit (Phase 1).

One keyboard-driven screen with four panes that map the discover → operate →
validate journey onto a single view:

  * ENGINE / HEALTH — live status + KPIs (tok/s, KV%, TTFT, running/waiting)
    from :func:`engine_client.engine_metrics`/``engine_status``;
  * CATALOG — the fit-ranked preset rows from ``launch_wizard.build_catalog``
    (a ``✓``/``✗`` fit glyph + preset + status + measured metric);
  * GPU / RIG — the resolved rig (GPUs, VRAM, compute capability);
  * LOG — a rolling status line.

It owns no business logic: every value flows through :mod:`sndr.cli.tui.data`,
the thin facade over the same seams the CLI uses. Blocking probes run in Textual
thread workers so the UI never stalls. Phase 1 is READ-ONLY — refresh / filter /
help / quit; serve/stop actions are Phase 2.

``textual`` is imported here (the optional ``[tui]`` extra); the ``sndr tui``
command gates on it before importing this module.
"""
from __future__ import annotations

from typing import Any, Optional

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, RichLog, Static

from sndr.cli.tui import data as _data

# Pure render helpers live in the textual-free render module so they unit-test
# without the optional [tui] extra; the app imports them rather than redefining
# the same wording. Re-exported below for back-compat with any caller that
# imported them from this module.
from sndr.cli.tui.render import (
    HELP_TEXT as _HELP_TEXT,
    catalog_rows,
    render_engine,
    render_gpu,
)


class HelpScreen(ModalScreen):
    """A dismissible help overlay (Esc / ? / q to close)."""

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("question_mark", "dismiss", "Close"),
        ("q", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        yield Static(_HELP_TEXT, id="help-body")


class SndrCockpit(App):
    """Read-only sndr cockpit."""

    TITLE = "sndr"
    CSS = """
    #top { height: 1fr; }
    #left { width: 38%; }
    #right { width: 62%; }
    #engine, #gpu { border: round $primary; padding: 0 1; height: 1fr; }
    #catalog { height: 60%; border: round $primary; }
    #log { height: 40%; border: round $secondary; padding: 0 1; }
    HelpScreen { align: center middle; }
    #help-body { width: 64; border: round $primary; padding: 1 2; background: $surface; }
    """

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("slash", "filter", "Filter"),
        ("question_mark", "help", "Help"),
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        *,
        rig: Optional[str] = None,
        fake_gpus: Optional[str] = None,
        loader: Any = _data,
    ) -> None:
        super().__init__()
        self._rig = rig
        self._fake_gpus = fake_gpus
        self._data = loader  # the facade — injectable so tests fake one surface
        self._catalog: Any = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="top"):
            with Vertical(id="left"):
                yield Static("loading…", id="engine")
                yield Static("", id="gpu")
            with Vertical(id="right"):
                yield DataTable(id="catalog")
                yield RichLog(id="log", max_lines=200, wrap=True, markup=False)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#catalog", DataTable)
        table.add_columns("fit", "preset", "status", "metric")
        table.cursor_type = "row"
        self._log("sndr cockpit — read-only (Phase 1).  r refresh · ? help · q quit")
        self._load_catalog()
        self._refresh_engine()
        # Live KPIs refresh on a gentle cadence; catalog is static-ish (manual r).
        self.set_interval(3.0, self._refresh_engine)

    # ── workers (blocking probes off the UI thread) ──────────────────────────

    @work(thread=True, exclusive=True)
    def _load_catalog(self) -> None:
        try:
            catalog = self._data.load_catalog(rig=self._rig, fake_gpus=self._fake_gpus)
        except Exception as exc:  # pragma: no cover — defensive
            self.call_from_thread(self._log, f"catalog error: {exc}")
            return
        self.call_from_thread(self._apply_catalog, catalog)

    @work(thread=True, exclusive=False)
    def _refresh_engine(self) -> None:
        try:
            snap = self._data.engine_snapshot()
        except Exception as exc:  # pragma: no cover — defensive
            self.call_from_thread(self._log, f"engine probe error: {exc}")
            return
        self.call_from_thread(self._apply_engine, snap)

    # ── apply (UI thread) ────────────────────────────────────────────────────

    def _apply_catalog(self, catalog: Any) -> None:
        self._catalog = catalog
        table = self.query_one("#catalog", DataTable)
        table.clear()
        rows = catalog_rows(catalog)
        fitting = 0
        for fit, preset_id, status, metric in rows:
            fitting += 1 if fit == "✓" else 0
            table.add_row(fit, preset_id, status, metric)
        rig = getattr(catalog, "rig", None)
        self.query_one("#gpu", Static).update(render_gpu(rig))
        try:
            self.sub_title = self._data.rig_summary(rig) if rig is not None else ""
        except Exception:  # pragma: no cover — cosmetic only
            self.sub_title = ""
        self._log(f"catalog: {len(rows)} presets · {fitting} fit this rig")

    def _apply_engine(self, snap: dict[str, Any]) -> None:
        self.query_one("#engine", Static).update(render_engine(snap))

    # ── actions ──────────────────────────────────────────────────────────────

    def action_refresh(self) -> None:
        self._log("refreshing…")
        self._load_catalog()
        self._refresh_engine()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_filter(self) -> None:
        # Phase 1: a focused-row jump hint; full filter input lands with actions.
        self._log("filter: type a preset name then ↑/↓ (full filter in Phase 2)")
        self.query_one("#catalog", DataTable).focus()

    # ── helpers ──────────────────────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        self.query_one("#log", RichLog).write(msg)


def run_tui(rig: Optional[str] = None, fake_gpus: Optional[str] = None) -> int:
    """Launch the cockpit. Returns a process exit code."""
    SndrCockpit(rig=rig, fake_gpus=fake_gpus).run()
    return 0


__all__ = ["SndrCockpit", "HelpScreen", "run_tui", "render_engine", "render_gpu"]
