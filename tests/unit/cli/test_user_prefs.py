# SPDX-License-Identifier: Apache-2.0
"""UX GROUP-CLI — per-user default/preference store (``sndr/cli/user_prefs.py``).

The store mirrors club-3090's DEFAULT-2 ``.env`` pin cache, adapted to OUR
stack: a per-user ``$SNDR_HOME/defaults.toml`` (never tracked in the repo) that
remembers the operator's chosen default preset and last-used remote. Two
disciplines are asserted here:

  * DEFAULT-2 slug validation — ``set_default_preset`` refuses a preset that is
    not in ``registry_v2.list_presets()`` (so a typo can never be persisted);
  * DEFAULT-4 precedence — a value in the SHELL ENV (``SNDR_DEFAULT_PRESET``)
    WINS over the file, and the resolver surfaces which source won.
"""
from __future__ import annotations

import pytest

pytest.importorskip("pydantic")

from sndr.cli import user_prefs  # noqa: E402
from sndr.model_configs.registry_v2 import list_presets  # noqa: E402


@pytest.fixture
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SNDR_HOME", str(tmp_path))
    monkeypatch.delenv("SNDR_DEFAULT_PRESET", raising=False)
    return tmp_path


def _a_real_preset() -> str:
    return list_presets()[0]


def test_prefs_path_honors_sndr_home(home_dir):
    assert user_prefs._prefs_path() == home_dir / "defaults.toml"


def test_default_preset_roundtrip(home_dir):
    assert user_prefs.get_default_preset() is None
    p = _a_real_preset()
    user_prefs.set_default_preset(p)
    assert user_prefs.get_default_preset() == p
    user_prefs.clear_default_preset()
    assert user_prefs.get_default_preset() is None


def test_set_rejects_unknown_preset(home_dir):
    with pytest.raises(ValueError, match="known preset"):
        user_prefs.set_default_preset("definitely-not-a-real-preset")


def test_shell_env_wins_over_file(home_dir, monkeypatch):
    presets = list_presets()
    file_preset, env_preset = presets[0], presets[1]
    user_prefs.set_default_preset(file_preset)
    monkeypatch.setenv("SNDR_DEFAULT_PRESET", env_preset)
    # env wins
    assert user_prefs.get_default_preset() == env_preset
    # and the resolver names the source
    value, source = user_prefs.resolve_default_preset()
    assert value == env_preset
    assert "env" in source.lower()


def test_last_remote_roundtrip(home_dir):
    assert user_prefs.get_last_remote() is None
    user_prefs.set_last_remote(
        "http://192.168.1.10:8102/v1",
        key="genesis-local",
        dsn="postgresql://u:p@127.0.0.1:55432/genesis_memory",
    )
    r = user_prefs.get_last_remote()
    assert r is not None
    assert r["url"] == "http://192.168.1.10:8102/v1"
    assert r["key"] == "genesis-local"
    assert "genesis_memory" in r["dsn"]
