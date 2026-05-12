# Trust Anchor Ceremony (Ed25519 keypair для license tokens)

Дата активации: 2026-05-12
Алгоритм: Ed25519 (32-byte ключи, RFC 8032)

## Назначение

`vllm.sndr_core.license` верифицирует подписанные license-токены для
engine-tier патчей. Trust anchor — публичный Ed25519 ключ, встроенный
в `_TRUST_ANCHOR_PUBKEY_B64URL` константу. Это единственный root of
trust для проверки токенов; смена pubkey = полная rotation всех
выпущенных токенов.

## Текущий статус

| Поле | Значение |
|---|---|
| Public key (base64url) | `iSk29MUb9HldKokPRyOG7bAjwYaQdgqYsS17yfskE8s` |
| Активирован | 2026-05-12 (audit P1-1 closure) |
| Предыдущий статус | Placeholder zero-key (32 нулевых байта) |
| Private key хранится | Offline, у Sandermage (USB+paper backup) |
| Скрипт генерации | `scripts/generate_trust_anchor.py` |

До 2026-05-12 проект использовал placeholder zero-key — подписанные
токены отвергались как `BAD_SIGNATURE`. Legacy unsigned-key mode
сохраняется за `SNDR_ALLOW_LEGACY_LICENSE_KEYS=1` флагом.

## Что делает оператор при rotation

1. **Только** на offline machine (no network):

   ```bash
   python3 scripts/generate_trust_anchor.py --out /secure/keys/trust_anchor_v2
   ```

   Скрипт печатает на stdout новые pub/priv keys. Сохраняет private в
   файл с правами 0600.

2. Public key из stdout (43-char base64url) скопировать в
   `vllm/sndr_core/license.py::_TRUST_ANCHOR_PUBKEY_B64URL`.

3. Private key:
   - Записать на YubiKey OR USB-носитель OR бумажный backup.
   - **Никогда** не коммитить в git, не загружать в cloud.
   - `.gitignore` уже игнорирует `~/.sndr/keys/`.

4. Перевыпустить все active customer tokens на новый ключ (вне scope
   этого репо — отдельная signing-tool инфраструктура).

5. Release новый wheel с обновлённой константой. Старые токены
   перестают валидироваться при upgrade — это intentional rotation.

## Когда rotate

- **Подозрение компромисса** private key.
- **Major version release** (например v12.0.0).
- **Annual policy review** (минимум 1 раз/год).

## Технические детали

### Алгоритм: Ed25519

- Curve25519-based EdDSA. Совместим с RFC 8032.
- 32-byte priv + 32-byte pub. Подписи 64 байт.
- Реализация — `cryptography.hazmat.primitives.asymmetric.ed25519`.

### Формат на диске

- Public key: 43-char base64url без padding (32 raw bytes).
- Private key: тот же формат, права 0600, постоянное хранилище offline.

### Verification path

```python
from vllm.sndr_core.license import (
    is_placeholder_anchor,
    verify_token,
    LicenseStatus,
)

# Sanity-check anchor не placeholder
assert not is_placeholder_anchor(), "trust anchor is placeholder — run ceremony"

# Verify token (по умолчанию использует встроенный trust anchor)
result = verify_token(token_str)
if result.status == LicenseStatus.LICENSED:
    customer = result.payload["customer_id"]
    print(f"OK, licensed to {customer}, expires_at={result.payload['expires_at']}")
elif result.status == LicenseStatus.EXPIRED:
    print(f"token expired: {result.detail}")
elif result.status == LicenseStatus.BAD_PAYLOAD:
    print(f"token contract violated: {result.detail}")
else:
    print(f"token rejected ({result.status.value}): {result.detail}")
```

**Etap 0.5 (2026-05-12):** `verify_token` и `is_placeholder_anchor`
теперь часть public API (`__all__`). Раньше документация ссылалась на
эти имена, но реально существовали только приватные `_verify_signed_token`
и `_is_placeholder_anchor`. Также `verify_token` теперь проверяет
строгий payload contract (`customer_id`/`issued_at`/`expires_at`/
`engine_major` обязательны) — раньше missing `expires_at` давал
бессрочный token.

## Связанные файлы

- `vllm/sndr_core/license.py` — public API: `verify_token`, `is_placeholder_anchor`, `LicenseStatus`, `TokenVerification`, `check_engine_tier_eligible`
- `scripts/generate_trust_anchor.py` — keygen + ceremony walkthrough (Etap 0.2: private key только в файл или с явным `--print-private`)
- `tests/unit/test_license.py` — verification tests + payload contract
- `tests/unit/test_trust_anchor_generator.py` — keygen smoke

## CI gate

```bash
python3 -c "from vllm.sndr_core.license import is_placeholder_anchor; assert not is_placeholder_anchor(), 'placeholder anchor — run ceremony'"
python3 -m pytest -q tests/unit/test_license.py
```
