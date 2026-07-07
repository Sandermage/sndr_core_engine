# SPDX-License-Identifier: Apache-2.0
"""GROUP-CONFIG (2026-07-06) — host.yaml first-run auto-init (BREAK #2).

A brand-new operator with no `host.yaml` must never watch the launch renderer
emit a literal `${models_dir}`. `ensure_host_yaml()` auto-detects + persists on
first miss, is idempotent on a present file, and preserves the env-wins ladder
(DOWNLOAD-3): a `GENESIS_*` / `SNDR_*` override is baked into the written map.
"""
from __future__ import annotations

from sndr.model_configs.host import HostConfig, load_host_config
from sndr.model_configs.host_autoinit import ensure_host_yaml
from sndr.model_configs.types.docker import resolve_symbolic_mounts


def _clear_host_env(monkeypatch):
    for var in ("SNDR_MODELS_DIR", "GENESIS_MODELS_DIR", "SNDR_HF_CACHE",
                "HF_HOME", "HUGGINGFACE_HUB_CACHE", "SNDR_HOME",
                "GENESIS_HOME"):
        monkeypatch.delenv(var, raising=False)


def test_writes_detected_paths_on_first_miss(tmp_path, monkeypatch):
    """Absent host.yaml -> detected paths get written; the renderer then
    resolves ${models_dir} instead of leaving the literal token."""
    _clear_host_env(monkeypatch)
    models = tmp_path / "srv_models"
    models.mkdir()
    # Env override is the deterministic way to make detect_paths find a dir
    # inside the tmp sandbox (also exercises the env-wins ladder at write).
    monkeypatch.setenv("SNDR_MODELS_DIR", str(models))

    host_yaml = tmp_path / ".sndr" / "host.yaml"
    assert not host_yaml.exists()

    written = ensure_host_yaml(path=host_yaml)
    assert written == host_yaml
    assert host_yaml.is_file(), "host.yaml must be created on first miss"

    hc = load_host_config(host_yaml)
    assert hc.get("models_dir") == str(models)

    # Renderer no longer emits a literal ${models_dir}.
    resolved = resolve_symbolic_mounts(
        ["${models_dir}:/models:ro"], hc.paths, strict=False,
    )
    assert resolved == [f"{models}:/models:ro"]
    assert "${models_dir}" not in resolved[0]


def test_present_host_yaml_is_noop(tmp_path, monkeypatch):
    """A present host.yaml is never touched (idempotent)."""
    _clear_host_env(monkeypatch)
    host_yaml = tmp_path / ".sndr" / "host.yaml"
    host_yaml.parent.mkdir(parents=True)
    original = "paths:\n  models_dir: /operator/custom/models\n"
    host_yaml.write_text(original)

    result = ensure_host_yaml(path=host_yaml)
    assert result is None, "must no-op when host.yaml already exists"
    assert host_yaml.read_text() == original, "existing file must be untouched"


def test_idempotent_second_call(tmp_path, monkeypatch):
    """Re-running after a write is a no-op (resumable / re-run safe)."""
    _clear_host_env(monkeypatch)
    models = tmp_path / "models"
    models.mkdir()
    monkeypatch.setenv("SNDR_MODELS_DIR", str(models))
    host_yaml = tmp_path / ".sndr" / "host.yaml"

    first = ensure_host_yaml(path=host_yaml)
    assert first == host_yaml
    snapshot = host_yaml.read_text()

    second = ensure_host_yaml(path=host_yaml)
    assert second is None
    assert host_yaml.read_text() == snapshot


def test_env_override_wins_into_written_file(tmp_path, monkeypatch):
    """DOWNLOAD-3 ladder: a GENESIS_* env override pre-empts the probe list
    and is what lands in the written host.yaml (env wins at write time)."""
    _clear_host_env(monkeypatch)
    env_models = tmp_path / "env_models"
    env_models.mkdir()
    monkeypatch.setenv("GENESIS_MODELS_DIR", str(env_models))

    host_yaml = tmp_path / ".sndr" / "host.yaml"
    ensure_host_yaml(path=host_yaml)

    hc = load_host_config(host_yaml)
    assert hc.get("models_dir") == str(env_models), (
        "env override must win over default probe candidates in the written map"
    )


def test_nothing_detectable_writes_nothing(tmp_path, monkeypatch):
    """On a host where detect_paths finds nothing, no stub file is written
    (read-only / CI callers must not be polluted)."""
    _clear_host_env(monkeypatch)
    host_yaml = tmp_path / ".sndr" / "host.yaml"

    import sndr.model_configs.host_autoinit as mod
    monkeypatch.setattr(mod._host, "detect_paths", dict)

    result = ensure_host_yaml(path=host_yaml)
    assert result is None
    assert not host_yaml.exists()


def test_persist_false_detects_without_writing(tmp_path, monkeypatch):
    """persist=False probes but never writes."""
    _clear_host_env(monkeypatch)
    models = tmp_path / "models"
    models.mkdir()
    monkeypatch.setenv("SNDR_MODELS_DIR", str(models))
    host_yaml = tmp_path / ".sndr" / "host.yaml"

    result = ensure_host_yaml(persist=False, path=host_yaml)
    assert result == host_yaml, "would-write target is reported"
    assert not host_yaml.exists(), "persist=False must not write"


def test_load_host_config_autoinit_opt_out(tmp_path, monkeypatch):
    """SNDR_HOST_AUTOINIT=0 keeps the legacy 'empty on absent' contract for
    the default-path load (opt-out escape hatch)."""
    _clear_host_env(monkeypatch)
    monkeypatch.setenv("SNDR_HOME", str(tmp_path / ".sndr"))
    monkeypatch.setenv("SNDR_HOST_AUTOINIT", "0")
    models = tmp_path / "models"
    models.mkdir()
    monkeypatch.setenv("SNDR_MODELS_DIR", str(models))

    hc = load_host_config()  # default path resolution, no host.yaml present
    assert isinstance(hc, HostConfig)
    assert not (tmp_path / ".sndr" / "host.yaml").exists(), (
        "opt-out must not auto-write"
    )
