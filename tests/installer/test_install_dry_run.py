# SPDX-License-Identifier: Apache-2.0
"""S-05 (2026-05-08) — `sndr install` canonical wizard tests.

Replaces the Stage-11 8-step smoke tests after the install.sh →
install.py consolidation. The new wizard has 11 steps + uninstall:

  step_preflight, step_detect_hardware, step_detect_vllm,
  step_runtime_caveat, step_pick_workload, step_resolve_pin,
  step_clone_or_update, step_install_plugin, step_detect_host_paths,
  step_generate_launch, step_smoke_test

Live install ops (git clone, pip install, exec vllm serve) are skipped
under --dry-run. These tests exercise the wizard in dry-run only.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest


# Phase 10 (2026-06-01): V1 sunset — the B3 regression test asserts that
# auto-match returns a key containing "a5000", which is V1-naming-bound.
# V2 composed-triplet keys may still contain "a5000" via the hardware
# layer; the explicit V1-key assertion stays V1-specific.
_V1_DIR_INS = (Path(__file__).resolve().parents[2] / "vllm" / "sndr_core"
               / "model_configs" / "builtin")
_skip_if_no_v1_35b_ins = pytest.mark.skipif(
    not (_V1_DIR_INS / "a5000-2x-35b-prod.yaml").is_file(),
    reason="V1 fixture a5000-2x-35b-prod.yaml retired (Phase 10 sunset)",
)


def _make_opts(**kwargs) -> argparse.Namespace:
    """argparse.Namespace mimicking `sndr install` flags after S-05 rewrite."""
    defaults = dict(
        dry_run=True,
        non_interactive=True,
        workload="balanced",
        pin="stable",
        repo="https://github.com/Sandermage/genesis-vllm-patches.git",
        home=None,
        bare_metal=False,
        no_plugin=True,
        no_verify=True,
        system=False,
        uninstall=False,
        pro=False,
        license_key="",
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ─── Step-level coverage ──────────────────────────────────────────────────


def test_step_preflight_collects_python_and_disk():
    """Pre-flight reports OS/Python/git/disk info."""
    from sndr.cli.legacy.install import step_preflight
    res = step_preflight(_make_opts())
    assert "os" in res.data
    assert "python_version" in res.data
    assert "sndr_home" in res.data
    major, minor = res.data["python_version"].split(".")[:2]
    assert int(major) >= 3 and int(minor) >= 10


def test_step_detect_hardware_reports_gpu_count():
    """Hardware detection runs without crashing on CPU-only hosts."""
    from sndr.cli.legacy.install import step_detect_hardware
    res = step_detect_hardware(_make_opts())
    assert "n_gpus" in res.data
    assert res.data["n_gpus"] >= 0
    assert "gpu_class_hint" in res.data
    assert isinstance(res.data["gpu_class_hint"], str)


def test_step_detect_vllm_returns_installed_flag():
    """vllm detection sets `installed` boolean either way."""
    from sndr.cli.legacy.install import step_detect_vllm
    res = step_detect_vllm(_make_opts())
    assert "installed" in res.data
    assert isinstance(res.data["installed"], bool)


def test_step_runtime_caveat_returns_proxmox_flag():
    """Runtime caveat probe sets `proxmox_detected` boolean."""
    from sndr.cli.legacy.install import step_runtime_caveat
    res = step_runtime_caveat(_make_opts())
    assert "proxmox_detected" in res.data
    assert isinstance(res.data["proxmox_detected"], bool)


def test_step_pick_workload_explicit_flag_wins():
    """If `--workload tool_agent` is passed, it wins without prompting."""
    from sndr.cli.legacy.install import step_pick_workload
    res = step_pick_workload(_make_opts(workload="tool_agent"))
    assert res.data["workload"] == "tool_agent"


def test_step_pick_workload_invalid_value_fatal():
    """Invalid `--workload` aborts with SystemExit."""
    from sndr.cli.legacy.install import step_pick_workload
    with pytest.raises(SystemExit):
        step_pick_workload(_make_opts(workload="invalid_workload_xyz"))


def test_step_pick_workload_default_in_non_interactive():
    """Non-interactive without `--workload` defaults to balanced."""
    from sndr.cli.legacy.install import step_pick_workload
    res = step_pick_workload(_make_opts(workload=None))
    assert res.data["workload"] == "balanced"


def test_step_resolve_pin_dev_passes_through():
    """`--pin dev` resolves to literal `dev`."""
    from sndr.cli.legacy.install import step_resolve_pin
    res = step_resolve_pin(_make_opts(pin="dev"))
    assert res.data["pin"] == "dev"
    assert res.data["kind"] == "dev"


def test_step_resolve_pin_explicit_ref():
    """`--pin v7.69` returns the literal ref."""
    from sndr.cli.legacy.install import step_resolve_pin
    res = step_resolve_pin(_make_opts(pin="v7.69"))
    assert res.data["pin"] == "v7.69"
    assert res.data["kind"] == "explicit"


def test_step_resolve_pin_stable_handles_offline(monkeypatch):
    """`--pin stable` falls back to `main` when GitHub API is unreachable."""
    import sndr.cli.legacy.install as M
    monkeypatch.setattr(M, "_resolve_latest_tag", lambda: None)
    res = M.step_resolve_pin(_make_opts(pin="stable"))
    assert res.data["pin"] == "main"
    assert res.data["kind"] == "stable_fallback"


def test_step_clone_or_update_dry_run_returns_marker():
    """Dry-run clone returns `<dry-run>` head."""
    from sndr.cli.legacy.install import step_clone_or_update
    preflight = {"sndr_home": "/tmp/sndr-test-bogus"}
    pin = {"pin": "main"}
    res = step_clone_or_update(_make_opts(), preflight, pin)
    assert res.data["head"] == "<dry-run>"


def test_step_install_plugin_dry_run_skipped():
    """Dry-run plugin install reports skipped."""
    from sndr.cli.legacy.install import step_install_plugin
    res = step_install_plugin(_make_opts(), {"home": "/nonexistent"})
    assert res.data["installed"] is False
    assert res.data["reason"] in ("--no-plugin", "dry-run")


def test_step_smoke_test_skipped_with_no_verify():
    """`--no-verify` skips the smoke test."""
    from sndr.cli.legacy.install import step_smoke_test
    res = step_smoke_test(_make_opts(no_verify=True))
    assert res.data["ran"] is False


# ─── Top-level orchestrator ───────────────────────────────────────────────


def test_run_install_dry_run_full_flow():
    """End-to-end dry-run completes successfully on Mac dev (no GPU)."""
    from sndr.cli.legacy.install import run_install
    opts = _make_opts(workload="tool_agent")
    rc = run_install(opts)
    assert rc == 0


def test_run_install_uninstall_dispatches():
    """`--uninstall` flag dispatches to run_uninstall and returns 0."""
    from sndr.cli.legacy.install import run_install
    opts = _make_opts(uninstall=True)
    rc = run_install(opts)
    assert rc == 0


def test_argparser_registers_install_subcommand():
    """`add_argparser` wires the install subcommand correctly."""
    from sndr.cli.legacy.install import add_argparser
    p = argparse.ArgumentParser()
    sub = p.add_subparsers()
    add_argparser(sub)
    opts = p.parse_args(["install", "-y", "--workload", "balanced",
                         "--dry-run", "--no-plugin", "--no-verify"])
    assert opts.workload == "balanced"
    assert opts.dry_run is True


# ─── B3 fix (UNIFIED_CONFIG plan 2026-05-09): _match_preset uses gpu_match_keys

def test_gpu_keys_match_substring_either_direction():
    """Helper matches needle⊂key OR key⊂needle, lowercased."""
    from sndr.cli.legacy.install import _gpu_keys_match
    # Detected longer than config key (typical nvidia-smi output)
    assert _gpu_keys_match("nvidia rtx a5000", ["rtx a5000"])
    # Detected shorter than config key (rare)
    assert _gpu_keys_match("rtx pro 6000", ["rtx pro 6000 blackwell"])
    # Multiple keys — any match wins
    assert _gpu_keys_match("a100", ["rtx a5000", "a100", "h100"])


def test_gpu_keys_match_no_match():
    """Different GPU class returns False."""
    from sndr.cli.legacy.install import _gpu_keys_match
    assert not _gpu_keys_match("rtx 4090", ["rtx a5000", "a100"])
    assert not _gpu_keys_match("", ["rtx a5000"])
    assert not _gpu_keys_match("rtx a5000", [])
    assert not _gpu_keys_match("rtx a5000", [""])


@_skip_if_no_v1_35b_ins
def test_match_preset_finds_a5000_2x_35b_prod():
    """B3 regression: 'NVIDIA RTX A5000' + 2 GPUs must match
    a5000-2x-35b-prod (which has gpu_match_keys=['rtx a5000'])."""
    from sndr.cli.legacy.install import _match_preset
    cfg, key = _match_preset("NVIDIA RTX A5000", 2, "balanced")
    assert cfg is not None, "preset match must not be None — schema field is gpu_match_keys"
    assert key is not None
    # At least one of the 2× A5000 builtin configs should win on n_gpus=2 + balanced
    assert "a5000" in key.lower()


def test_match_preset_returns_none_for_unknown_gpu():
    """Unknown GPU returns (None, None) cleanly (no crash on any builtin config)."""
    from sndr.cli.legacy.install import _match_preset
    cfg, key = _match_preset("Some Unknown GPU XYZ", 2, "balanced")
    assert cfg is None
    assert key is None


# ─── B5: installer must render launch scripts with strict_mounts=True ──────
#
# The installer writes a REAL launcher to ~/.sndr/launch/. If it renders
# with strict_mounts=False (preview semantics) an unresolved ${models_dir}
# can land in an executable script. The live `sndr launch` path uses
# strict_mounts=True; the installer must match.


def test_step_generate_launch_renders_strict_mounts(monkeypatch, tmp_path):
    """step_generate_launch must call to_launch_script with
    strict_mounts=True so unresolved ${var} placeholders fail fast
    instead of being written into a real launcher script."""
    from sndr.cli.legacy import install as install_mod

    captured = {}

    class _FakeCfg:
        def to_launch_script(self, host_paths=None, *, strict_mounts=False):
            captured["strict_mounts"] = strict_mounts
            captured["host_paths"] = host_paths
            return "#!/bin/bash\necho ok\n"

    monkeypatch.setattr(
        install_mod, "_match_preset",
        lambda gpu, n, wl: (_FakeCfg(), "fake-preset"),
    )

    hw = {"gpu_class_hint": "rtx a5000", "n_gpus": 2}
    workload = {"workload": "balanced"}
    clone_info = {"home": str(tmp_path)}

    res = install_mod.step_generate_launch(
        _make_opts(), hw, workload, clone_info,
    )
    assert res.data.get("path") is not None
    assert captured.get("strict_mounts") is True, (
        "installer must render the real launcher with strict_mounts=True"
    )


def test_step_generate_launch_unresolved_placeholder_fails(monkeypatch, tmp_path):
    """If a placeholder survives (strict render raises or the script still
    carries ${var}), the installer must NOT silently write a broken
    launcher — it surfaces a non-success reason."""
    from sndr.cli.legacy import install as install_mod
    from sndr.model_configs.schema import SchemaError

    class _FakeCfg:
        def to_launch_script(self, host_paths=None, *, strict_mounts=False):
            if strict_mounts:
                raise SchemaError("unresolved ${models_dir}: fix host.yaml")
            return "docker run -v ${models_dir}:/models ...\n"

    monkeypatch.setattr(
        install_mod, "_match_preset",
        lambda gpu, n, wl: (_FakeCfg(), "fake-preset"),
    )

    hw = {"gpu_class_hint": "rtx a5000", "n_gpus": 2}
    workload = {"workload": "balanced"}
    clone_info = {"home": str(tmp_path)}

    res = install_mod.step_generate_launch(
        _make_opts(), hw, workload, clone_info,
    )
    # No real launcher written, reason surfaced.
    assert res.data.get("path") is None
    assert res.data.get("reason")


# ─── B6: empty gpu_class_hint must fall through to the picker ──────────────


def test_step_generate_launch_no_gpu_falls_through_to_picker(monkeypatch, tmp_path):
    """When GPU detection failed (empty gpu_class_hint) the installer must
    fall through to the interactive preset picker rather than returning a
    bare `no_gpu` skip. In non-interactive mode the picker cannot prompt,
    so it surfaces a picker-path reason (NOT `no_gpu`)."""
    from sndr.cli.legacy import install as install_mod

    picker_called = {"n": 0}

    def _fake_picker(opts):
        picker_called["n"] += 1
        return (None, None)  # non-interactive: no choice possible

    monkeypatch.setattr(
        install_mod, "_pick_preset_interactive", _fake_picker, raising=False,
    )

    hw = {"gpu_class_hint": "", "n_gpus": 0}
    workload = {"workload": "balanced"}
    clone_info = {"home": str(tmp_path)}

    res = install_mod.step_generate_launch(
        _make_opts(), hw, workload, clone_info,
    )
    assert picker_called["n"] == 1, (
        "empty gpu_class_hint must fall through to the interactive picker"
    )
    assert res.data.get("reason") != "no_gpu"


def test_step_generate_launch_picker_choice_is_rendered(monkeypatch, tmp_path):
    """When the picker returns a chosen (cfg, key), the installer renders
    and writes that preset's launcher (strict_mounts=True)."""
    from sndr.cli.legacy import install as install_mod

    captured = {}

    class _FakeCfg:
        def to_launch_script(self, host_paths=None, *, strict_mounts=False):
            captured["strict_mounts"] = strict_mounts
            return "#!/bin/bash\necho picked\n"

    monkeypatch.setattr(
        install_mod, "_pick_preset_interactive",
        lambda opts: (_FakeCfg(), "operator-picked"),
        raising=False,
    )

    hw = {"gpu_class_hint": "", "n_gpus": 0}
    workload = {"workload": "balanced"}
    clone_info = {"home": str(tmp_path)}

    res = install_mod.step_generate_launch(
        _make_opts(), hw, workload, clone_info,
    )
    assert res.data.get("path") is not None
    assert res.data.get("preset") == "operator-picked"
    assert captured.get("strict_mounts") is True


# ─── B7: token-based (robust) workload match ───────────────────────────────


def test_workload_score_token_based():
    """`tool_agent` must score on text that contains the tokens 'tool'
    and 'agent' even when they are not the contiguous substring
    'tool agent' (the old `replace('_', ' ') in text` was brittle)."""
    from sndr.cli.legacy.install import _workload_score
    # Tokens present but reordered / separated → old substring match missed.
    assert _workload_score("tool_agent", "best for agentic tool use") > 0
    assert _workload_score("tool_agent", "ide coding agent with tool calls") > 0
    # More token coverage scores higher than partial.
    full = _workload_score("long_context", "tuned for long context windows")
    partial = _workload_score("long_context", "long prompts only")
    assert full > partial
    # Unrelated text scores zero.
    assert _workload_score("tool_agent", "high throughput batch serving") == 0
