# SPDX-License-Identifier: Apache-2.0
"""Regression: shell renderers must shell-quote JSON-valued CLI args.

Bug (rig, 2026-06-22): `sndr launch prod-qwen3.6-35b-balanced` died with

    vllm serve: error: argument --override-generation-config:
    Value temperature:0.6 cannot be converted to <function loads ...>

Root cause: the rendered docker `-c '...; exec vllm serve ...
--override-generation-config {"temperature":0.6,"top_k":20,"top_p":0.95}'`
left the JSON value UNQUOTED. Because it contains commas inside `{...}`,
bash performs BRACE EXPANSION → it splits into the separate words
`temperature:0.6 top_k:20 top_p:0.95` → vllm's argparse gets the fragment
`temperature:0.6` and json.loads fails. Presets WITHOUT
override_generation_config booted fine.

`--override-generation-config` arrives via `cfg.vllm_extra_args` (raw
JSON token from compose); `--speculative-config` via `to_vllm_arg()` (raw
JSON). Both must be shell-quoted by the shell renderers so the value
survives as ONE argument.

These tests prove, by re-tokenizing the rendered command the way bash
would, that:
  • the JSON value is one intact argument (parses as JSON);
  • no brace-split fragment (`temperature:0.6`) leaks;
  • spec-config JSON survives simultaneously (no double-quoting);
  • a preset without override_generation_config renders unchanged.
"""
from __future__ import annotations

import json
import re
import shlex

import pytest

from sndr.model_configs.schema import (
    DockerConfig, HardwareSpec, ModelConfig, SpecDecodeConfig,
)


def _make_cfg(**overrides) -> ModelConfig:
    base = dict(
        key="test-quote", title="Test Quote",
        description="d", schema_version=1, maintainer="x",
        model_path="/models/Test-7B",
        hardware=HardwareSpec(
            gpu_match_keys=["test"], n_gpus=2,
            min_vram_per_gpu_mib=24576,
        ),
        max_model_len=8192,
        gpu_memory_utilization=0.92,
        max_num_seqs=4,
        max_num_batched_tokens=4096,
        served_model_name="test-7b",
        tool_call_parser="qwen3_xml",
        reasoning_parser="qwen3",
        docker=DockerConfig(
            image="vllm/vllm-openai:nightly",
            container_name="vllm-test",
            port=8000,
        ),
    )
    base.update(overrides)
    return ModelConfig(**base)


# Canonical Qwen sampling defaults — the exact payload that broke on the rig.
_OGC = {"temperature": 0.6, "top_k": 20, "top_p": 0.95}
_SPEC = SpecDecodeConfig(method="mtp", num_speculative_tokens=5)


def _extract_exec_cmd_from_docker_c(script: str) -> str:
    """Pull the `exec vllm serve ...` command out of the docker `-c '...'`
    body, undoing the outer POSIX single-quote escaping (`'\\''`)."""
    line = next(
        l for l in script.splitlines() if l.strip().startswith("-c '")
    )
    m = re.search(r"-c '(.*)'\s*$", line)
    assert m, f"could not parse -c body from: {line!r}"
    body = m.group(1).replace("'\\''", "'")
    assert "exec " in body, "no exec step in -c body"
    return body.split("exec ", 1)[1]


def _bash_tokenize(exec_cmd: str) -> list[str]:
    """Tokenize exactly as bash word-splitting/quote-removal would.

    `shlex.split` (POSIX mode) matches bash for the quoting forms we
    emit. If a JSON value were left unquoted, brace-expansion would have
    happened in a real shell; here we additionally assert no token looks
    like a brace-split fragment, which catches that class directly.
    """
    return shlex.split(exec_cmd)


class TestDockerCBodyQuoting:
    def test_override_generation_config_is_single_json_arg(self):
        cfg = _make_cfg(vllm_extra_args=[
            "--override-generation-config",
            json.dumps(_OGC, separators=(",", ":"), sort_keys=True),
        ])
        script = cfg.to_launch_script()
        # (a) full JSON intact in the raw rendered text
        assert '{"temperature":0.6,"top_k":20,"top_p":0.95}' in script
        # (b) brace-expansion-safe: after bash tokenization the JSON is ONE arg
        toks = _bash_tokenize(_extract_exec_cmd_from_docker_c(script))
        i = toks.index("--override-generation-config")
        assert json.loads(toks[i + 1]) == _OGC
        # no brace-split fragment leaked as its own token
        assert not any(
            re.fullmatch(r"(temperature|top_k|top_p):[\d.]+", t) for t in toks
        ), f"brace-split fragment leaked into tokens: {toks}"

    def test_spec_config_json_survives_simultaneously(self):
        """Both JSON args quoted at once — proves no double-quoting of
        spec-config (the previously-prequoted arg)."""
        cfg = _make_cfg(
            spec_decode=_SPEC,
            vllm_extra_args=[
                "--override-generation-config",
                json.dumps(_OGC, separators=(",", ":"), sort_keys=True),
            ],
        )
        toks = _bash_tokenize(
            _extract_exec_cmd_from_docker_c(cfg.to_launch_script())
        )
        si = toks.index("--speculative-config")
        assert json.loads(toks[si + 1]) == {
            "method": "mtp", "num_speculative_tokens": 5,
        }
        oi = toks.index("--override-generation-config")
        assert json.loads(toks[oi + 1]) == _OGC

    def test_no_override_render_unchanged(self):
        """A preset WITHOUT override_generation_config (26B-style) must
        not gain any extra quoting; spec-config still parses as one arg."""
        with_extra = _make_cfg(
            spec_decode=_SPEC,
            vllm_extra_args=[
                "--override-generation-config",
                json.dumps(_OGC, separators=(",", ":"), sort_keys=True),
            ],
        )
        without = _make_cfg(spec_decode=_SPEC)
        s_with = with_extra.to_launch_script()
        s_without = without.to_launch_script()
        # The no-override render must NOT contain the OGC flag at all.
        assert "--override-generation-config" not in s_without
        # spec-config still a single intact JSON arg in the no-override case.
        toks = _bash_tokenize(_extract_exec_cmd_from_docker_c(s_without))
        si = toks.index("--speculative-config")
        assert json.loads(toks[si + 1]) == {
            "method": "mtp", "num_speculative_tokens": 5,
        }
        # Sanity: the override flag is the only structural difference.
        assert "--override-generation-config" in s_with


class TestSystemdAndBareMetalQuoting:
    """The systemd-unit (ExecStart=) and bare-metal (`exec`) renderers in
    product_api.legacy.deployment join raw argv tokens; each must be
    shell-quoted so JSON values survive."""

    def _params(self, cfg):
        from sndr.product_api.legacy.deployment import _runtime_argv
        return {
            "image": "vllm/vllm-openai:nightly",
            "container_name": "vllm-test",
            "host_port": 8000,
            "genesis_pin": "test-pin",
            "argv": _runtime_argv(cfg),
        }

    def test_systemd_unit_quotes_json(self):
        from sndr.product_api.legacy.deployment import _systemd_unit
        cfg = _make_cfg(
            spec_decode=_SPEC,
            vllm_extra_args=[
                "--override-generation-config",
                json.dumps(_OGC, separators=(",", ":"), sort_keys=True),
            ],
        )
        unit = _systemd_unit(cfg, self._params(cfg))
        exec_line = next(
            l for l in unit.splitlines() if l.startswith("ExecStart=")
        )[len("ExecStart="):]
        toks = shlex.split(exec_line)
        oi = toks.index("--override-generation-config")
        assert json.loads(toks[oi + 1]) == _OGC
        si = toks.index("--speculative-config")
        assert json.loads(toks[si + 1]) == {
            "method": "mtp", "num_speculative_tokens": 5,
        }
        assert not any(
            re.fullmatch(r"(temperature|top_k|top_p):[\d.]+", t) for t in toks
        )

    def test_bare_metal_script_quotes_json(self):
        from sndr.product_api.legacy.deployment import _bare_metal_script
        cfg = _make_cfg(
            spec_decode=_SPEC,
            vllm_extra_args=[
                "--override-generation-config",
                json.dumps(_OGC, separators=(",", ":"), sort_keys=True),
            ],
        )
        script = _bare_metal_script(cfg, self._params(cfg))
        exec_line = next(
            l for l in script.splitlines() if l.startswith("exec ")
        )[len("exec "):]
        toks = shlex.split(exec_line)
        oi = toks.index("--override-generation-config")
        assert json.loads(toks[oi + 1]) == _OGC
        si = toks.index("--speculative-config")
        assert json.loads(toks[si + 1]) == {
            "method": "mtp", "num_speculative_tokens": 5,
        }


def test_argv_to_shell_not_used_by_raw_consumers():
    """Guard: the k8s manifest / compose `command:` lists consume RAW argv
    and must NOT gain shell quotes. build_runtime_command().argv stays raw
    (unquoted) — only the shell renderers quote."""
    from sndr.model_configs.runtime_command import build_runtime_command
    cfg = _make_cfg(
        spec_decode=_SPEC,
        vllm_extra_args=[
            "--override-generation-config",
            json.dumps(_OGC, separators=(",", ":"), sort_keys=True),
        ],
    )
    argv = build_runtime_command(cfg).argv
    # Raw JSON token — no surrounding single-quotes added at the argv layer.
    assert json.dumps(_OGC, separators=(",", ":"), sort_keys=True) in argv
    assert "'{\"temperature\":0.6,\"top_k\":20,\"top_p\":0.95}'" not in argv
