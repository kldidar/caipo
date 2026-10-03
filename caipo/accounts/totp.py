"""TOTP codes and the protection of their secrets (ADR-0014).

Internal to the accounts app: services call it, nothing else does. It holds no
policy. Whether a code is asked for, how many may be tried, and what an
accepted code allows are decided in `services` and `authorization`.

Both the code algorithm (RFC 6238) and the cipher come from the `cryptography`
package. Nothing cryptographic is implemented here.
"""

import base64
import hmac
import secrets
from datetime import datetime

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.twofactor import InvalidToken
from cryptography.hazmat.primitives.twofactor.totp import TOTP
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

# What authenticator applications implement: six digits, thirty seconds,
# HMAC-SHA1. Changing any of them would silently invalidate every enrolled
# device, so they are constants and not settings.
DIGITS = 6
PERIOD_SECONDS = 30
# RFC 4226 recommends a secret as long as the hash output: 160 bits.
SECRET_BYTES = 20

KEY_BYTES = 32
_NONCE_BYTES = 12
_TAG_BYTES = 16


class SecretUnavailableError(Exception):
    """A stored secret cannot be decrypted with the configured key.

    Raised for a secret encrypted under another key, a ciphertext that was
    altered, and a ciphertext moved from another account. Carries no detail.
    """


def generate_secret() -> bytes:
    """Return a new random secret. It is never derived from anything a client sent."""
    return secrets.token_bytes(SECRET_BYTES)


def _encryption_key() -> bytes:
    key = getattr(settings, "TOTP_ENCRYPTION_KEY", None)
    if not isinstance(key, bytes) or len(key) != KEY_BYTES:
        raise ImproperlyConfigured("TOTP_ENCRYPTION_KEY is not configured.")
    return key


def _key_id(key: bytes) -> str:
    """Return a name for a key that says nothing about it."""
    return hmac.new(key, b"caipo.accounts.totp.key-id", "sha256").hexdigest()[:16]


def _associated_data(user_id: int) -> bytes:
    # Authenticated with the ciphertext, so a ciphertext copied to another
    # account's row does not decrypt there.
    return f"caipo.accounts.totp:{user_id}".encode()


def encrypt_secret(secret: bytes, *, user_id: int) -> tuple[bytes, str]:
    """Return the secret encrypted for one account, and the identifier of the key used.

    AES-256-GCM under TOTP_ENCRYPTION_KEY, with a fresh random nonce stored in
    front of the ciphertext. Raises ImproperlyConfigured if no key is
    configured.
    """
    key = _encryption_key()
    nonce = secrets.token_bytes(_NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, secret, _associated_data(user_id))
    return nonce + ciphertext, _key_id(key)


def decrypt_secret(ciphertext: bytes, key_id: str, *, user_id: int) -> bytes:
    """Return the secret that was encrypted for this account.

    Raises SecretUnavailableError if it was encrypted under a different key,
    was altered, or belongs to another account, and ImproperlyConfigured if no
    key is configured.
    """
    key = _encryption_key()
    if not hmac.compare_digest(key_id.encode(), _key_id(key).encode()):
        raise SecretUnavailableError
    if len(ciphertext) < _NONCE_BYTES + _TAG_BYTES:
        raise SecretUnavailableError
    try:
        return AESGCM(key).decrypt(
            ciphertext[:_NONCE_BYTES], ciphertext[_NONCE_BYTES:], _associated_data(user_id)
        )
    except InvalidTag:
        raise SecretUnavailableError from None


def _totp(secret: bytes) -> TOTP:
    # The noqa below: SHA-1 is what RFC 6238 authenticator applications
    # implement. It is used here only inside HMAC, which the collision attacks
    # on SHA-1 do not affect.
    return TOTP(secret, DIGITS, hashes.SHA1(), PERIOD_SECONDS)  # noqa: S303


def matching_step(secret: bytes, code: str, *, at: datetime) -> int | None:
    """Return the time step for which the code is right, or None if it is not right.

    The step containing `at` is tried, and TOTP_DRIFT_STEPS steps on either
    side of it, to allow for a clock that is slightly off. Every step in the
    window is always tried, whichever matches. Anything that is not exactly
    DIGITS ASCII digits matches nothing.
    """
    if len(code) != DIGITS or not code.isascii() or not code.isdigit():
        return None
    totp = _totp(secret)
    current = int(at.timestamp()) // PERIOD_SECONDS
    matched = None
    for step in range(current - settings.TOTP_DRIFT_STEPS, current + settings.TOTP_DRIFT_STEPS + 1):
        try:
            totp.verify(code.encode(), step * PERIOD_SECONDS)
        except InvalidToken:
            continue
        matched = step
    return matched


def manual_entry_key(secret: bytes) -> str:
    """Return the secret in the Base32 form that authenticator applications accept."""
    return base64.b32encode(secret).decode()


def provisioning_uri(secret: bytes, *, account: str) -> str:
    """Return the otpauth URI that enrols the secret in an authenticator application.

    It carries the secret, the issuer, and the account's email address, and
    nothing else: no password and nothing of the session. It must be shown
    only to the account it was made for and must never be stored or logged.
    """
    return _totp(secret).get_provisioning_uri(account, settings.TOTP_ISSUER)
