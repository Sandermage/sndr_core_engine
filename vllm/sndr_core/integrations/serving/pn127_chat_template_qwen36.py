# SPDX-License-Identifier: Apache-2.0
"""PN127 — Qwen 3.5/3.6 enhanced chat-template auto-install.

Закрывает operator-pain: до этого патча правильный chat template
для Qwen 3.5/3.6 hybrid_gdn_moe (с interleaved-thinking + XML
tool_call, M2.5-style) надо было:
  1. Знать что дефолтный template ломается на multi-turn tool-call
     (club-3090#53, club-3090#72 — 30-120s SSE silence)
  2. Найти где взять enhanced version (фрагментирован между
     froggeric, Sandermage v7.62, club-3090 repos)
  3. Положить .jinja файл рядом с checkpoint
  4. Указать `--chat-template /path/to/file.jinja` в launch args

PN127 убирает шаги 2-3: enhanced template запекается в Genesis
package как asset, на apply() копируется в writable location
которая известна оператору. Operator больше не ищет файл — он
живёт по канонической dataimage path сразу после `pip install`.

Использование оператором
========================

Запуск:
  vllm serve <model> \
    ...
    --chat-template /tmp/genesis/chat_templates/qwen3.6_enhanced.jinja

или через env var GENESIS_AUTO_CHAT_TEMPLATE_PATH (читается launch
скриптом, добавляется в `--chat-template` arg):
  GENESIS_AUTO_CHAT_TEMPLATE_PATH=/tmp/genesis/chat_templates/qwen3.6_enhanced.jinja

Что внутри template
===================
  - Multimodal (image + video token rendering)
  - XML tool_call + tool_response wrapping (qwen3_coder parser
    compatible)
  - M2.5-style interleaved thinking:
    * historical assistant reasoning перед последним user query
      hidden (no cache pollution)
    * assistant turns после последнего user query сохраняют <think>
    * generation всегда стартует в <think>
  - 7 фиксов которые отсутствуют в дефолтном Qwen template:
    1. empty `<think></think>` spam
    2. `</thinking>` hallucination (wrong close tag)
    3. unclosed think before tool call
    4. no-user-query startup crash
    5. developer role passthrough (для IDE-агентов)
    6. multi-turn tool-call SSE deadlock (club-3090#72)
    7. think→tool_call boundary truncation

Источник
========
  - Base: Sandermage Genesis v7.62 chat_template_enhanced.jinja
  - Cross-validated: froggeric Qwen-Fixed-Chat-Templates
  - Live verify: club-3090 turbo dual config, 30/30 tool regression PASS

Safety
======
  - Опт-ин: GENESIS_ENABLE_PN127_AUTO_CHAT_TEMPLATE=1
  - Идемпотентен: SHA256 проверка — переписывает только если изменился
  - Никогда не raise — failed write только log.warning, operator
    падает на explicit --chat-template путь
  - Target: /tmp/genesis/chat_templates/qwen3.6_enhanced.jinja
    (или GENESIS_CHAT_TEMPLATE_DIR override)
  - Source: vllm.sndr_core.assets.chat_templates.qwen3.6_enhanced.jinja

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
Genesis-original 2026-05-15 — закрывает club-3090#53 / club-3090#72
class разладок template-on-disk dependency.
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

log = logging.getLogger("genesis.wiring.pn127_chat_template_qwen36")

GENESIS_PN127_MARKER = "Genesis PN127 Qwen3.5/3.6 chat-template auto-install v1"
_ENV_ENABLE = "GENESIS_ENABLE_PN127_AUTO_CHAT_TEMPLATE"
_ENV_DISABLE = "GENESIS_DISABLE_PN127_AUTO_CHAT_TEMPLATE"
_ENV_DIR_OVERRIDE = "GENESIS_CHAT_TEMPLATE_DIR"

_DEFAULT_INSTALL_DIR = "/tmp/genesis/chat_templates"
_TEMPLATE_FILENAME = "qwen3.6_enhanced.jinja"


def _env_enabled() -> bool:
    """Default OFF до bench-валидации."""
    if os.environ.get(_ENV_DISABLE, "").strip().lower() in ("1", "true", "yes", "on"):
        return False
    val = os.environ.get(_ENV_ENABLE, "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _resolve_install_dir() -> Path:
    """Куда писать template. Operator override через env."""
    custom = os.environ.get(_ENV_DIR_OVERRIDE, "").strip()
    if custom:
        return Path(custom)
    return Path(_DEFAULT_INSTALL_DIR)


def _read_packaged_template() -> str | None:
    """Прочитать template, запеченный в Genesis package."""
    try:
        from importlib.resources import files
        asset = files("vllm.sndr_core.assets.chat_templates") / _TEMPLATE_FILENAME
        return asset.read_text(encoding="utf-8")
    except (ModuleNotFoundError, FileNotFoundError, OSError) as e:
        log.warning(
            "[PN127] packaged template asset not readable: %s. Genesis "
            "install may be missing assets/chat_templates/. Skip.", e,
        )
        return None


def _sha256_short(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


_APPLIED = False
_INSTALLED_PATH: Path | None = None


def apply() -> tuple[str, str]:
    """Запекает template в writable location. Идемпотентен."""
    global _APPLIED, _INSTALLED_PATH

    if not _env_enabled():
        return "skipped", (
            f"PN127 disabled (set {_ENV_ENABLE}=1 чтобы Genesis "
            f"auto-install Qwen3.5/3.6 enhanced chat-template; путь "
            f"будет logged ниже и доступен через --chat-template)"
        )

    if _APPLIED and _INSTALLED_PATH is not None and _INSTALLED_PATH.is_file():
        return "applied", (
            f"PN127 already installed at {_INSTALLED_PATH} (идемпотентный skip)"
        )

    template = _read_packaged_template()
    if template is None:
        return "skipped", "PN127 packaged template asset missing — see warning above"

    install_dir = _resolve_install_dir()
    target = install_dir / _TEMPLATE_FILENAME

    try:
        install_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return "skipped", f"PN127 cannot create install dir {install_dir}: {e}"

    # Проверка нужна ли запись (SHA-сравнение)
    expected_sha = _sha256_short(template)
    if target.is_file():
        try:
            current_sha = _sha256_short(target.read_text(encoding="utf-8"))
            if current_sha == expected_sha:
                _APPLIED = True
                _INSTALLED_PATH = target
                return "applied", (
                    f"PN127 template already at {target} "
                    f"(sha256:{expected_sha[:8]}, идемпотентный)"
                )
        except OSError:
            pass  # перепишем
        log.info(
            "[PN127] existing template at %s differs (sha changed) — overwriting",
            target,
        )

    try:
        target.write_text(template, encoding="utf-8")
    except OSError as e:
        return "skipped", f"PN127 cannot write to {target}: {e}"

    _APPLIED = True
    _INSTALLED_PATH = target

    log.info(
        "[PN127] installed Qwen3.5/3.6 enhanced chat-template at %s "
        "(sha256:%s). Operator: используйте --chat-template %s в "
        "launch args для применения.",
        target, expected_sha[:8], target,
    )
    return "applied", (
        f"PN127 installed: enhanced chat-template скопирован в {target} "
        f"(sha256:{expected_sha[:8]}). Operator больше не ищет файл — "
        f"запускайте vllm с --chat-template {target}. Resolves "
        f"club-3090#53 (multi-turn tool-call) + club-3090#72 (SSE "
        f"silence на narrative <tool_call>)."
    )


def is_applied() -> bool:
    return _APPLIED


def installed_path() -> Path | None:
    """Путь к установленному template (или None если PN127 не applied)."""
    return _INSTALLED_PATH


def revert() -> bool:
    """Удалить установленный template. Идемпотентен."""
    global _APPLIED, _INSTALLED_PATH
    if not _APPLIED or _INSTALLED_PATH is None:
        return False
    try:
        if _INSTALLED_PATH.is_file():
            _INSTALLED_PATH.unlink()
    except OSError as e:
        log.warning("[PN127] revert: cannot remove %s: %s", _INSTALLED_PATH, e)
        return False
    _APPLIED = False
    _INSTALLED_PATH = None
    return True
