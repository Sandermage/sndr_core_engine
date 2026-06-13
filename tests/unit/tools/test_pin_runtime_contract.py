# SPDX-License-Identifier: Apache-2.0
"""TDD for `tools/pin_runtime_contract.py` — the pin-transition runtime-contract
verifier that catches config-referenced component IDENTITY drift across pins
(the class that broke dev259->dev491 streaming tool-calls: qwen3_xml silently
remapped from Qwen3XMLToolParser to Qwen3CoderToolParser).

Only the pure `diff_contracts` logic is unit-tested here — `emit_contract`
resolves against the live vLLM registry and runs inside the pin's container.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

# Load the tool module directly (tools/ is not a package).
_TOOL = pathlib.Path(__file__).resolve().parents[3] / "tools" / "pin_runtime_contract.py"
_spec = importlib.util.spec_from_file_location("pin_runtime_contract", _TOOL)
prc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prc)


def _contract(pin, **comp):
    return {"pin": pin, "components": comp}


class TestDiffContracts:
    def test_identical_contracts_have_no_drift(self):
        base = _contract(
            "dev259",
            tool_call_parser={"qwen3_xml": "vllm.tp.qwen3xml.Qwen3XMLToolParser"},
        )
        cand = _contract(
            "dev491",
            tool_call_parser={"qwen3_xml": "vllm.tp.qwen3xml.Qwen3XMLToolParser"},
        )
        assert prc.diff_contracts(base, cand) == []

    def test_detects_the_qwen3_xml_remap(self):
        """The canonical regression: qwen3_xml -> Qwen3XMLToolParser on the
        validated pin, -> Qwen3CoderToolParser on the candidate. MUST flag."""
        base = _contract(
            "dev259",
            tool_call_parser={
                "qwen3_xml": "vllm.tool_parsers.qwen3xml_tool_parser.Qwen3XMLToolParser",
                "qwen3_coder": "vllm.tool_parsers.qwen3coder_tool_parser.Qwen3CoderToolParser",
            },
        )
        cand = _contract(
            "dev491",
            tool_call_parser={
                "qwen3_xml": "vllm.tool_parsers.qwen3coder_tool_parser.Qwen3CoderToolParser",
                "qwen3_coder": "vllm.tool_parsers.qwen3coder_tool_parser.Qwen3CoderToolParser",
            },
        )
        drifts = prc.diff_contracts(base, cand)
        assert len(drifts) == 1
        d = drifts[0]
        assert d["name"] == "qwen3_xml"
        assert d["category"] == "tool_call_parser"
        assert d["kind"] == "remapped"
        assert "Qwen3XMLToolParser" in d["baseline"]
        assert "Qwen3CoderToolParser" in d["candidate"]
        # qwen3_coder did NOT change identity -> not flagged.
        assert all(x["name"] != "qwen3_coder" for x in drifts)

    def test_detects_deletion_as_unresolved(self):
        base = _contract(
            "dev259",
            tool_call_parser={"qwen3_xml": "vllm.tp.qwen3xml.Qwen3XMLToolParser"},
        )
        cand = _contract(
            "dev491",
            tool_call_parser={"qwen3_xml": prc.UNRESOLVED + " (qwen3_xml not registered)"},
        )
        drifts = prc.diff_contracts(base, cand)
        assert len(drifts) == 1
        assert drifts[0]["kind"] == "deleted"

    def test_name_only_on_one_side_is_not_drift(self):
        """A name present only on one pin (added/removed config) is
        informational, not an identity drift."""
        base = _contract("dev259", tool_call_parser={"hermes": "vllm.tp.h.Hermes"})
        cand = _contract(
            "dev491",
            tool_call_parser={
                "hermes": "vllm.tp.h.Hermes",
                "newparser": "vllm.tp.n.New",
            },
        )
        assert prc.diff_contracts(base, cand) == []

    def test_reasoning_parser_drift_also_caught(self):
        base = _contract("dev259", reasoning_parser={"qwen3": "vllm.r.A"})
        cand = _contract("dev491", reasoning_parser={"qwen3": "vllm.r.B"})
        drifts = prc.diff_contracts(base, cand)
        assert len(drifts) == 1
        assert drifts[0]["category"] == "reasoning_parser"


class TestEmitShape:
    def test_default_components_cover_the_prod_stack(self):
        # The launcher-only qwen3_xml MUST be in the checked set — it is the
        # exact name that remapped. gemma4 + qwen3_coder come from the YAMLs.
        tcp = prc.DEFAULT_COMPONENTS["tool_call_parser"]
        assert "qwen3_xml" in tcp
        assert "qwen3_coder" in tcp
        assert "gemma4" in tcp
        assert "qwen3" in prc.DEFAULT_COMPONENTS["reasoning_parser"]


class TestExitCode:
    def test_check_returns_3_on_drift(self, tmp_path, monkeypatch, capsys):
        base = _contract(
            "dev259",
            tool_call_parser={"qwen3_xml": "vllm.a.Qwen3XMLToolParser"},
        )
        bf = tmp_path / "baseline.json"
        import json

        bf.write_text(json.dumps(base))
        # candidate resolves qwen3_xml differently
        monkeypatch.setattr(
            prc,
            "emit_contract",
            lambda components=None: _contract(
                "dev491",
                tool_call_parser={"qwen3_xml": "vllm.a.Qwen3CoderToolParser"},
            ),
        )
        rc = prc.main(["--check", str(bf)])
        assert rc == 3
        assert "DRIFT" in capsys.readouterr().out

    def test_check_returns_0_when_clean(self, tmp_path, monkeypatch, capsys):
        base = _contract(
            "dev259", tool_call_parser={"qwen3_xml": "vllm.a.Same"}
        )
        bf = tmp_path / "baseline.json"
        import json

        bf.write_text(json.dumps(base))
        monkeypatch.setattr(
            prc,
            "emit_contract",
            lambda components=None: _contract(
                "dev491", tool_call_parser={"qwen3_xml": "vllm.a.Same"}
            ),
        )
        rc = prc.main(["--check", str(bf)])
        assert rc == 0
        assert "CLEAN" in capsys.readouterr().out
