# SPDX-License-Identifier: Apache-2.0
"""GROUP-CONFIG (2026-07-06) — the root `.env.example` scaffold contract.

`.env.example` is the copy-and-edit-only-what-you-want scaffold (GAP 1). It
must be a literal KEY=VALUE file (docker-compose semantics, NOT `source`d),
document the Section-B remote triplet, carry Section-A defaults that MATCH the
code's real defaults, be English-only, and carry no real secrets.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO_ROOT / ".env.example"

# KEY=VALUE, tolerating a leading comment marker (the scaffold ships every
# knob commented so a zero-edit copy still boots on auto-defaults).
_KV_RE = re.compile(r"^#?\s*(?P<key>[A-Z][A-Z0-9_]*)=(?P<val>.*)$")


def _parse_kv(text: str) -> dict[str, str]:
    """Parse the scaffold line-by-line as KEY=VALUE (never `source`)."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        m = _KV_RE.match(line)
        if not m:
            continue
        out[m.group("key")] = m.group("val").strip()
    return out


def test_env_example_exists_at_repo_root():
    assert ENV_EXAMPLE.is_file(), ".env.example must live at the repo root"


def test_parses_as_key_value_not_source():
    """Every documented knob is a plain KEY=VALUE line — no `$(...)`, no
    `${OTHER}` interpolation, no `export ` prefix (it is read literally,
    not sourced)."""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    kv = _parse_kv(text)
    assert kv, "no KEY=VALUE lines parsed from .env.example"
    for line in text.splitlines():
        stripped = line.lstrip("#").strip()
        assert not stripped.startswith("export "), (
            f"scaffold is read literally, not sourced: {line!r}"
        )
    # No command substitution / shell interpolation in actual VALUES (prose
    # comments may mention `$(...)` when explaining that it is unsupported).
    for key, val in kv.items():
        assert "$(" not in val, f"no command substitution in value of {key}: {val!r}"
        assert "${" not in val, f"no interpolation in value of {key}: {val!r}"


def test_section_b_remote_triplet_present():
    """The remote-client triplet (the only genuinely manual surface) must be
    documented."""
    kv = _parse_kv(ENV_EXAMPLE.read_text(encoding="utf-8"))
    for key in ("SNDR_OPENAI_BASE_URL", "SNDR_ENGINE_API_KEY",
                "GENESIS_MEMORY_DSN"):
        assert key in kv, f"Section-B triplet key missing: {key}"


def test_section_a_defaults_match_code():
    """Section-A documented defaults must match the code's real defaults."""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    kv = _parse_kv(text)
    # SNDR_ENGINE_API_KEY default must match schema.py ModelConfig.api_key.
    import dataclasses

    from sndr.model_configs.schema import ModelConfig
    schema_default = {
        f.name: f.default for f in dataclasses.fields(ModelConfig)
    }["api_key"]
    assert schema_default == "genesis-local"
    assert kv.get("SNDR_ENGINE_API_KEY") == schema_default
    # GUI daemon port.
    assert kv.get("SNDR_GUI_PORT") == "8765"
    # Engine self-launch port 8000 must appear (documented default).
    assert "8000" in text, "engine self-launch port 8000 must be documented"
    # Default engine overlay.
    assert kv.get("SNDR_ENGINE") == "vllm"


def test_comments_are_english_only_ascii():
    """Language rule: the scaffold's comments/strings are English only."""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for i, line in enumerate(text.splitlines(), 1):
        # Box-drawing chars used for section rules are allowed; flag any
        # non-ASCII LETTER (would signal a non-English word slipped in).
        for ch in line:
            if ch.isalpha() and ord(ch) > 127:
                raise AssertionError(
                    f".env.example L{i}: non-English/non-ASCII letter "
                    f"{ch!r} in {line!r}"
                )


def test_no_real_secrets_committed():
    """No AWS keys, no private-key blocks, no long opaque tokens. The dev
    defaults genesis-local / genesis_mem_dev are established non-secrets."""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert not re.search(r"\bAKIA[A-Z0-9]{16}\b", text), "AWS key leaked"
    assert "PRIVATE KEY" not in text, "private-key block leaked"
    # A crude opaque-token sniff: a 40+ char run of base64-ish chars that is
    # not one of the whitelisted placeholders.
    for tok in re.findall(r"[A-Za-z0-9+/_-]{40,}", text):
        assert tok in ("YOUR_RIG_HOST",), f"suspicious long token: {tok!r}"


def test_gitignore_tracks_the_template():
    """`.env` is ignored but `.env.example` is explicitly tracked (negation)."""
    gi = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "!.env.example" in gi, (
        ".gitignore must negate .env.example so the scaffold is tracked"
    )
