# SPDX-License-Identifier: Apache-2.0
"""Production trust-anchor gate.

Гарантирует что Ed25519 public key в `vllm.sndr_core.license` —
реальный, а не placeholder (32 нулевых байта). Placeholder режим
отвергает все signed tokens как BAD_SIGNATURE, что делает
engine-tier license недоступным.

Включён в audit P1-1 closure (2026-05-12).
"""
from __future__ import annotations


def test_trust_anchor_is_not_placeholder():
    """Активный pubkey не должен быть 32-нулевой placeholder."""
    from vllm.sndr_core.license import _is_placeholder_anchor

    assert not _is_placeholder_anchor(), (
        "Trust anchor placeholder detected. Run "
        "`scripts/generate_trust_anchor.py` (offline) и обновить "
        "`_TRUST_ANCHOR_PUBKEY_B64URL` в `vllm/sndr_core/license.py`. "
        "См. docs/security/TRUST_ANCHOR_CEREMONY.md."
    )


def test_trust_anchor_pubkey_shape():
    """Pubkey должен быть 43-char base64url (32 raw bytes)."""
    import base64
    from vllm.sndr_core.license import _TRUST_ANCHOR_PUBKEY_B64URL

    assert isinstance(_TRUST_ANCHOR_PUBKEY_B64URL, str), \
        "anchor must be str"
    assert len(_TRUST_ANCHOR_PUBKEY_B64URL) == 43, (
        f"Ed25519 pubkey в base64url без padding = 43 chars, "
        f"got {len(_TRUST_ANCHOR_PUBKEY_B64URL)}"
    )
    pad = "=" * (-len(_TRUST_ANCHOR_PUBKEY_B64URL) % 4)
    raw = base64.urlsafe_b64decode(_TRUST_ANCHOR_PUBKEY_B64URL + pad)
    assert len(raw) == 32, f"raw key must be 32 bytes, got {len(raw)}"
