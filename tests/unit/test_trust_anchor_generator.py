# SPDX-License-Identifier: Apache-2.0
"""Tests for trust anchor generator script + placeholder detection.

Wave 4.4 — replaces placeholder zero-key in license.py with real
production keypair.
"""
from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_trust_anchor.py"


@pytest.fixture
def generator_module():
    spec = importlib.util.spec_from_file_location(
        "generate_trust_anchor", SCRIPT_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cryptography_available():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )
        return True
    except ImportError:
        pytest.skip("cryptography not installed")


# ─── Generator output shape ──────────────────────────────────────────────


class TestGenerator:
    def test_generates_valid_keypair(self, cryptography_available, generator_module):
        pub_b64, priv_b64 = generator_module.generate_keypair()
        # Both should be base64url, no padding, 43 chars (32 bytes raw)
        assert len(pub_b64) == 43
        assert len(priv_b64) == 43
        # Decodable
        pub_bytes = base64.urlsafe_b64decode(pub_b64 + "==")
        priv_bytes = base64.urlsafe_b64decode(priv_b64 + "==")
        assert len(pub_bytes) == 32
        assert len(priv_bytes) == 32
        # Non-zero
        assert pub_bytes != b"\x00" * 32
        assert priv_bytes != b"\x00" * 32

    def test_keypair_is_unique_each_call(self, cryptography_available, generator_module):
        p1, _ = generator_module.generate_keypair()
        p2, _ = generator_module.generate_keypair()
        assert p1 != p2

    def test_save_private_key_chmod_0o600(self, cryptography_available, generator_module, tmp_path):
        priv = "x" * 43
        path = tmp_path / "subdir" / "priv.key"
        generator_module.save_private_key(path, priv)
        assert path.is_file()
        mode = path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_save_refuses_overwrite(self, cryptography_available, generator_module, tmp_path):
        path = tmp_path / "priv.key"
        path.write_text("existing", encoding="utf-8")
        with pytest.raises(SystemExit):
            generator_module.save_private_key(path, "newkey")


# ─── License.py runtime warning ──────────────────────────────────────────


class TestPlaceholderDetection:
    def test_is_placeholder_returns_true_for_zeros(self, monkeypatch):
        """Когда `_TRUST_ANCHOR_PUBKEY_B64URL` ставится в 32-нулевой
        placeholder, детектор должен срабатывать. Тест не проверяет
        live-состояние модуля (там сейчас активирован реальный ключ
        2026-05-12 ceremony) — только семантику самой функции.
        """
        from vllm.sndr_core import license as L
        zero_b64 = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        monkeypatch.setattr(L, "_TRUST_ANCHOR_PUBKEY_B64URL", zero_b64)
        assert L._is_placeholder_anchor() is True

    def test_warning_logged_at_module_load(self, caplog, monkeypatch):
        """Warning должен срабатывать когда anchor — placeholder.
        Здесь тоже мокаем константу, потому что в production-tree
        реальный ключ активирован."""
        from vllm.sndr_core import license as L
        assert hasattr(L, "_maybe_log_placeholder_warning")
        zero_b64 = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        monkeypatch.setattr(L, "_TRUST_ANCHOR_PUBKEY_B64URL", zero_b64)
        L._TRUST_ANCHOR_PLACEHOLDER_DETECTED = False
        with caplog.at_level("WARNING", logger="genesis.license"):
            L._maybe_log_placeholder_warning()
        assert any(
            "PLACEHOLDER zero-key" in r.message
            for r in caplog.records
        )

    def test_warning_idempotent(self, caplog, monkeypatch):
        """Повторный вызов `_maybe_log_placeholder_warning` не должен
        генерить новые warnings (идемпотентность). Мокаем anchor в
        placeholder режим иначе функция вообще ничего не пишет."""
        from vllm.sndr_core import license as L
        zero_b64 = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        monkeypatch.setattr(L, "_TRUST_ANCHOR_PUBKEY_B64URL", zero_b64)
        L._TRUST_ANCHOR_PLACEHOLDER_DETECTED = False
        with caplog.at_level("WARNING", logger="genesis.license"):
            L._maybe_log_placeholder_warning()
            n_first = len([r for r in caplog.records if "PLACEHOLDER" in r.message])
        with caplog.at_level("WARNING", logger="genesis.license"):
            L._maybe_log_placeholder_warning()
            n_second = len([r for r in caplog.records if "PLACEHOLDER" in r.message])
        # n_second includes n_first, increment should be 0
        assert n_second == n_first


# ─── update_license_py() ─────────────────────────────────────────────────


class TestUpdateLicenseScript:
    def test_update_license_replaces_pubkey(self, cryptography_available, generator_module, tmp_path, monkeypatch):
        # Mock LICENSE_PY to point at a tmp file
        mock_license = tmp_path / "license.py"
        mock_license.write_text(
            'something\n'
            '_TRUST_ANCHOR_PUBKEY_B64URL = (\n'
            '    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  # placeholder\n'
            ')\n'
            'more code\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(generator_module, "LICENSE_PY", mock_license)
        new_pub = "B" * 43
        ok = generator_module.update_license_py(new_pub)
        assert ok is True
        contents = mock_license.read_text()
        assert new_pub in contents
        # Old placeholder gone
        assert '"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"' not in contents

    def test_update_license_handles_missing_file(self, generator_module, tmp_path, monkeypatch, capsys):
        nonexistent = tmp_path / "no.py"
        monkeypatch.setattr(generator_module, "LICENSE_PY", nonexistent)
        ok = generator_module.update_license_py("B" * 43)
        assert ok is False


# ─── End-to-end via main() ──────────────────────────────────────────────


class TestMainCli:
    """Etap 0.2 (audit 2026-05-12): private key никогда не уходит в
    stdout без явного opt-in. Default — `main([])` отказывается
    генерить ключ если не указано куда положить приватную половину."""

    def test_no_destination_refuses(self, generator_module, capsys):
        """`main([])` без --out и без --print-private → rc=3, error в stderr.

        Не зависит от cryptography — guard срабатывает ДО generate_keypair().
        """
        rc = generator_module.main([])
        assert rc == 3
        err = capsys.readouterr().err
        assert "nowhere to go" in err
        assert "--out" in err and "--print-private" in err

    def test_out_only_emits_public_in_stdout(self, cryptography_available, generator_module, capsys, tmp_path):
        """`--out` без `--print-private` → public в stdout, private ТОЛЬКО в файле."""
        path = tmp_path / "priv.key"
        rc = generator_module.main(["--out", str(path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "PUBLIC  KEY" in out
        # Etap 0.2: private key НЕ должен оказаться в stdout
        assert "PRIVATE KEY" not in out
        # Но должен быть в файле
        assert path.is_file()
        assert (path.stat().st_mode & 0o777) == 0o600
        # Содержимое файла — base64url 43 chars (плюс newline)
        priv_in_file = path.read_text().strip()
        assert len(priv_in_file) == 43
        # И этот string не должен встретиться в stdout
        assert priv_in_file not in out

    def test_print_private_emits_both(self, cryptography_available, generator_module, capsys):
        """`--print-private` явный opt-in → public + private оба в stdout."""
        rc = generator_module.main(["--print-private"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "PUBLIC  KEY" in out
        assert "PRIVATE KEY" in out

    def test_out_plus_print_private_combination(self, cryptography_available, generator_module, capsys, tmp_path):
        """`--out PATH --print-private` — обе ветки активны (file + stdout)."""
        path = tmp_path / "priv.key"
        rc = generator_module.main(["--out", str(path), "--print-private"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "PRIVATE KEY" in out
        assert path.is_file()

    def test_quiet_with_out_keeps_security_default(self, cryptography_available, generator_module, capsys, tmp_path):
        """`--quiet` не меняет exposure правил — только убирает баннеры."""
        path = tmp_path / "priv.key"
        rc = generator_module.main(["--out", str(path), "--quiet"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "NEXT STEPS" not in out
        assert "PUBLIC" in out
        # Private всё равно не утекает в stdout
        assert "PRIVATE KEY" not in out
        priv_in_file = path.read_text().strip()
        assert priv_in_file not in out
