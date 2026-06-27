# SPDX-License-Identifier: Apache-2.0
"""Integration tests for `sndr kv-calc <preset>` / `sndr fit` (v12 CLI command).

Drives the real command end-to-end against the live preset corpus using offline
rig sources (--fake-gpus / --card) so there's no nvidia-smi dependency. The
load-bearing assertion is that the 35B at its true A5000 operating point lands
on the TIGHT verdict the dev424 PN403 live engine telemetry shows.
"""
from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

import pytest

pytest.importorskip("pydantic")

from sndr.cli.main import main  # noqa: E402

_A5000_2X = "RTX A5000:24564:8.6;RTX A5000:24564:8.6"


def _run(argv) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(argv)
    return rc, buf.getvalue()


class TestKvCalcRegistered:
    def test_kv_calc_and_fit_in_registry(self):
        from sndr.cli.commands import COMMAND_REGISTRY
        from sndr.cli.main import build_parser
        build_parser()
        assert "kv-calc" in COMMAND_REGISTRY
        assert "fit" in COMMAND_REGISTRY


class TestKvCalcVerdicts:
    def test_35b_on_true_a5000_is_tight(self):
        """35B @280K on real 24564 MiB A5000s reproduces the PN403 TIGHT point."""
        rc, out = _run(["kv-calc", "prod-qwen3.6-35b-balanced",
                        "--fake-gpus", _A5000_2X, "--kv-breakdown"])
        assert rc == 0  # TIGHT still boots → exit 0
        assert "TIGHT" in out
        assert "Model weights" in out
        assert "Available for KV" in out

    def test_35b_on_tiny_budget_fails(self):
        rc, out = _run(["kv-calc", "prod-qwen3.6-35b-balanced",
                        "--card", "12"])
        assert rc == 1  # FAIL → exit 1
        assert "FAIL" in out

    def test_ctx_override_changes_point(self):
        rc, out = _run(["kv-calc", "prod-qwen3.6-35b-balanced",
                        "--fake-gpus", _A5000_2X, "--ctx", "32k"])
        assert rc == 0
        assert "ctx=32,768" in out

    def test_27b_flagged_provisional(self):
        rc, out = _run(["kv-calc", "prod-qwen3.6-27b-tq-k8v4",
                        "--fake-gpus", _A5000_2X])
        assert "PROVISIONAL" in out


class TestKvCalcSolve:
    def test_solve_max_ctx_returns_sane_number(self):
        rc, out = _run(["kv-calc", "prod-qwen3.6-27b-tq-k8v4",
                        "--fake-gpus", _A5000_2X, "--solve-max-ctx"])
        assert rc == 0
        assert "MAX CTX" in out
        # Parse the reported max ctx and assert it's a real, large number.
        line = [ln for ln in out.splitlines() if "MAX CTX" in ln][0]
        digits = line.split(":")[1].split("tokens")[0].replace(",", "").strip()
        assert int(digits) >= 100_000


class TestKvCalcJson:
    def test_json_shape(self):
        rc, out = _run(["--output", "json", "kv-calc",
                        "prod-qwen3.6-35b-balanced", "--fake-gpus", _A5000_2X])
        assert rc == 0
        data = json.loads(out)
        assert data["preset"] == "prod-qwen3.6-35b-balanced"
        assert data["verdict"] in ("PASS", "TIGHT", "FAIL")
        assert data["provisional"] is False
        per = data["per_card_gib"]
        assert {"weights", "kv_pool_requested", "activation", "total",
                "headroom", "available_for_kv"} <= set(per)
        # The 35B available-for-KV must reproduce the live ~0.69 GiB pool.
        assert 0.5 <= per["available_for_kv"] <= 0.9

    def test_fit_alias_json_equivalent(self):
        rc, out = _run(["--output", "json", "fit",
                        "prod-qwen3.6-35b-balanced", "--fake-gpus", _A5000_2X])
        assert rc == 0
        data = json.loads(out)
        assert data["verdict"] in ("PASS", "TIGHT", "FAIL")

    def test_unknown_preset_errors_cleanly(self):
        rc, out = _run(["--output", "json", "kv-calc", "no-such-xyz",
                        "--card", "24"])
        assert rc == 2
        assert "error" in json.loads(out)


class TestKvCalcFitAll:
    """``--fit-all`` projects the WHOLE catalog into one table per card."""

    def test_fit_all_prints_a_table_rc0(self):
        rc, out = _run(["kv-calc", "--fit-all", "--card", "24"])
        assert rc == 0
        # The two anchor presets must each appear as a row.
        assert "prod-qwen3.6-35b-balanced" in out
        assert "prod-qwen3.6-27b-tq-k8v4" in out
        # A verdict glyph/word is printed.
        assert any(v in out for v in ("PASS", "TIGHT", "FAIL"))

    def test_fit_all_iterates_multiple_cards(self):
        rc, out = _run(["kv-calc", "--fit-all", "--cards", "24,48,80"])
        assert rc == 0
        for c in ("24", "48", "80"):
            assert c in out

    def test_fit_all_default_card_set_when_none_given(self):
        """No --card / --cards / --rig → a sensible default 24/48/80 table,
        offline (no nvidia-smi needed)."""
        rc, out = _run(["kv-calc", "--fit-all"])
        assert rc == 0
        assert "24" in out and "48" in out and "80" in out

    def test_fit_all_tiny_card_35b_fails_gguf_passes(self):
        """The load-bearing fixture: on a tiny card the 35B FAILs; the 27B
        single-card GGUF lane PASSes on its real 24 GiB card."""
        rc14, out14 = _run(["--output", "json", "kv-calc", "--fit-all",
                            "--cards", "14"])
        assert rc14 == 0
        rows = {r["preset"]: r for r in json.loads(out14)["rows"]}
        assert rows["prod-qwen3.6-35b-balanced"]["verdict"] == "FAIL"

        rc24, out24 = _run(["--output", "json", "kv-calc", "--fit-all",
                            "--cards", "24"])
        rows24 = {(r["preset"], r["card_gib"]): r
                  for r in json.loads(out24)["rows"]}
        gguf = rows24[("llamacpp-qwen3.6-27b-q4km-1x", 24.0)]
        assert gguf["verdict"] == "PASS"
        assert gguf["engine"] == "llama-cpp"

    def test_fit_all_skips_shapeless_model_with_note_not_error(self):
        """A catalog model with no ModelShape must SKIP (with a note), not crash
        the whole table."""
        rc, out = _run(["--output", "json", "kv-calc", "--fit-all", "--cards", "24"])
        assert rc == 0
        data = json.loads(out)
        rows = data["rows"]
        skipped = [r for r in rows if r["verdict"] == "SKIP"]
        # gemma4 / 7b-dense / fp8kv presets carry no shape → at least one SKIP.
        assert skipped, "expected at least one SKIP row for a shapeless model"
        assert all(r["notes"] for r in skipped)

    def test_fit_all_json_shape(self):
        rc, out = _run(["--output", "json", "kv-calc", "--fit-all", "--cards", "24,48"])
        assert rc == 0
        data = json.loads(out)
        assert data["mode"] == "fit-all"
        assert data["cards_gib"] == [24.0, 48.0]
        assert isinstance(data["rows"], list) and data["rows"]
        row = data["rows"][0]
        assert {"preset", "engine", "card_gib", "verdict", "max_ctx_fit",
                "provisional"} <= set(row)

    def test_fit_all_fit_alias_also_works(self):
        rc, out = _run(["fit", "--fit-all", "--card", "24"])
        assert rc == 0
        assert "prod-qwen3.6-35b-balanced" in out
