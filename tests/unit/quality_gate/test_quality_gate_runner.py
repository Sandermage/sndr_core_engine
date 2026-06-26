# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the Genesis quality-gate runner CLI (tools/quality_gate/runner.py).

The runner is the contract between the bash drivers and the tested core: each
subcommand emits one JSON object on stdout that the shell parses. These tests
exercise the non-network subcommands (payload gen, ladder, scale, verdicts,
soak state) so the shell contract stays stable. The `send` subcommand (live
HTTP) is intentionally not exercised here — it needs an engine.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = REPO_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from quality_gate import runner  # noqa: E402


def _run(capsys, argv):
    rc = runner.main(argv)
    out = capsys.readouterr().out.strip().splitlines()
    obj = json.loads(out[-1]) if out else {}
    return rc, obj


def test_ladder_subcommand(capsys) -> None:
    rc, obj = _run(capsys, ["ladder", "--n-ctx", "262144"])
    assert rc == 0
    assert obj["rungs"][0] == 95_000
    assert obj["rungs"][-1] == int(262_144 * 0.92)


def test_scale_for_subcommand(capsys) -> None:
    rc, obj = _run(
        capsys, ["scale-for", "--target-tokens", "95000", "--tok-per-scale", "65"]
    )
    assert rc == 0
    assert obj["scale"] == 1461


def test_gen_niah_writes_payload_and_secret(tmp_path, capsys) -> None:
    req = tmp_path / "req.json"
    sec = tmp_path / "sec.txt"
    rc, obj = _run(
        capsys,
        [
            "gen-niah",
            "--model",
            "m",
            "--scale",
            "150",
            "--req",
            str(req),
            "--secret-out",
            str(sec),
            "--seed",
            "0",
        ],
    )
    assert rc == 0
    body = json.loads(req.read_text())
    secret = sec.read_text()
    assert obj["secret"] == secret
    assert secret in body["messages"][0]["content"]


def test_gen_probe_kinds(tmp_path, capsys) -> None:
    for kind in ("tool_prefill", "ide_agent", "multiturn", "lcb", "reasoning"):
        req = tmp_path / f"{kind}.json"
        rc, obj = _run(
            capsys, ["gen-probe", "--kind", kind, "--model", "m", "--req", str(req)]
        )
        assert rc == 0
        assert obj["kind"] == kind
        assert json.loads(req.read_text())["model"] == "m"


def test_verdict_probe_silent_empty(capsys) -> None:
    rc, obj = _run(
        capsys,
        [
            "verdict-probe",
            "--kind",
            "tool_prefill",
            "--http",
            "200",
            "--content-len",
            "0",
            "--tool-calls",
            "0",
            "--finish",
            "stop",
        ],
    )
    assert obj["status"] == "FAIL"
    assert obj["cliff"] == "silent-empty"


def test_verdict_probe_500_cliff(capsys) -> None:
    rc, obj = _run(capsys, ["verdict-probe", "--kind", "lcb_coding", "--http", "500"])
    assert obj["status"] == "FAIL"
    assert obj["patch"] == "P103"


def test_verdict_400_disambiguation(capsys) -> None:
    rc, obj = _run(
        capsys,
        [
            "verdict-400",
            "--kind",
            "ceiling",
            "--target-tokens",
            "120000",
            "--n-ctx",
            "262144",
        ],
    )
    assert obj["status"] == "FAIL"  # target < n_ctx -> sizing bug
    rc, obj = _run(
        capsys,
        [
            "verdict-400",
            "--kind",
            "ceiling",
            "--target-tokens",
            "300000",
            "--n-ctx",
            "262144",
        ],
    )
    assert obj["status"] == "SKIP"  # legitimate over-ctx rejection


def test_soak_state_lifecycle(tmp_path, capsys) -> None:
    state = tmp_path / "state.json"
    req = tmp_path / "req.json"
    metrics = tmp_path / "metrics.json"

    _run(capsys, ["soak-init", "--state", str(state), "--session", "1"])
    st0 = json.loads(state.read_text())
    assert st0["messages"][0]["role"] == "system"

    _run(
        capsys,
        [
            "soak-request",
            "--state",
            str(state),
            "--model",
            "m",
            "--turn",
            "1",
            "--req",
            str(req),
        ],
    )
    body = json.loads(req.read_text())
    assert body["messages"][-1]["role"] == "user"

    metrics.write_text(
        json.dumps({"content": "reading the handler", "completion_tokens": 40})
    )
    _run(
        capsys,
        [
            "soak-ingest",
            "--state",
            str(state),
            "--metrics",
            str(metrics),
            "--turn",
            "1",
        ],
    )
    st1 = json.loads(state.read_text())
    # After ingest the assistant reply + a synthetic tool result for turn 2 are
    # appended, so accumulated context grows (Cliff-2b ramp).
    roles = [m["role"] for m in st1["messages"]]
    assert "tool" in roles
    assert len(json.dumps(st1)) > len(json.dumps(st0))


def test_soak_verdict_and_attribute_exit_codes(tmp_path, capsys) -> None:
    rows = tmp_path / "rows.jsonl"
    on = tmp_path / "on.json"
    stripped = tmp_path / "strip.json"

    rows.write_text(
        json.dumps(
            {
                "session_id": 1,
                "turn_id": 1,
                "t_ms": 2000,
                "vram_mib": 21000,
                "ttft_ms": 500,
                "decode_tps": 110,
                "status": 200,
                "error": "",
                "completion_tokens": 300,
            }
        )
        + "\n"
        + json.dumps(
            {
                "session_id": 5,
                "turn_id": 1,
                "t_ms": 2000,
                "vram_mib": 21100,
                "ttft_ms": 500,
                "decode_tps": 108,
                "status": 200,
                "error": "",
                "completion_tokens": 300,
            }
        )
        + "\n"
    )
    rc, obj = _run(
        capsys,
        ["soak-verdict", "--rows", str(rows), "--boot-vram", "21000", "--out", str(on)],
    )
    assert rc == 0
    assert obj["verdict"] == "PASS"

    # A stripped run that OOMs.
    rows2 = tmp_path / "rows2.jsonl"
    rows2.write_text(
        json.dumps(
            {
                "session_id": 1,
                "turn_id": 1,
                "t_ms": 2000,
                "vram_mib": 21000,
                "ttft_ms": 500,
                "decode_tps": 110,
                "status": 200,
                "error": "",
                "completion_tokens": 300,
            }
        )
        + "\n"
        + json.dumps(
            {
                "session_id": 5,
                "turn_id": 1,
                "t_ms": 2000,
                "vram_mib": 24000,
                "ttft_ms": 500,
                "decode_tps": 110,
                "status": 500,
                "error": "OOM",
                "completion_tokens": 0,
            }
        )
        + "\n"
    )
    rc, _ = _run(
        capsys,
        [
            "soak-verdict",
            "--rows",
            str(rows2),
            "--boot-vram",
            "21000",
            "--out",
            str(stripped),
        ],
    )
    assert rc == 1  # FAIL exit code

    rc, obj = _run(
        capsys,
        [
            "soak-attribute",
            "--on",
            str(on),
            "--stripped",
            str(stripped),
            "--patch",
            "PN59",
            "--tp",
            "1",
        ],
    )
    assert obj["verdict"] == "LOAD_BEARING"


def test_unknown_probe_kind_returns_error(tmp_path, capsys) -> None:
    rc = runner.main(
        [
            "gen-probe",
            "--kind",
            "tool_prefill",
            "--model",
            "m",
            "--req",
            str(tmp_path / "r.json"),
        ]
    )
    assert rc == 0
    # argparse rejects an out-of-choice kind before our code runs.
    with pytest.raises(SystemExit):
        runner.main(
            [
                "gen-probe",
                "--kind",
                "bogus",
                "--model",
                "m",
                "--req",
                str(tmp_path / "r.json"),
            ]
        )
