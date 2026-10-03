"""TOTP codes and the encryption of their secrets, with no database and no HTTP."""

from datetime import UTC, datetime, timedelta

import pytest
from django.conf import LazySettings
from django.core.exceptions import ImproperlyConfigured

from caipo.accounts import totp
from caipo.accounts.tests.fixtures import TEST_TOTP_SECRET, code_at

# The shared secret of the RFC 6238 test vectors, and the last six digits of
# the SHA-1 code the RFC gives for each time.
RFC_SECRET = b"12345678901234567890"
RFC_VECTORS = [
    (59, "287082"),
    (1111111109, "081804"),
    (1111111111, "050471"),
    (1234567890, "005924"),
    (2000000000, "279037"),
    (20000000000, "353130"),
]

NOW = datetime(2026, 10, 2, 12, 0, 15, tzinfo=UTC)
STEP = timedelta(seconds=totp.PERIOD_SECONDS)


def _at(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, tz=UTC)


# --- Codes ----------------------------------------------------------------------


@pytest.mark.parametrize(("seconds", "code"), RFC_VECTORS)
def test_the_rfc_6238_test_vectors_are_accepted(seconds: int, code: str) -> None:
    assert totp.matching_step(RFC_SECRET, code, at=_at(seconds)) == seconds // 30


@pytest.mark.parametrize(("seconds", "code"), RFC_VECTORS)
def test_the_test_helper_agrees_with_the_rfc(seconds: int, code: str) -> None:
    assert code_at(_at(seconds), secret=RFC_SECRET) == code


def test_the_parameters_are_what_authenticator_applications_implement() -> None:
    assert (totp.DIGITS, totp.PERIOD_SECONDS, totp.SECRET_BYTES) == (6, 30, 20)


def test_the_current_code_is_accepted_for_its_own_step() -> None:
    assert totp.matching_step(TEST_TOTP_SECRET, code_at(NOW), at=NOW) == int(NOW.timestamp()) // 30


@pytest.mark.parametrize("steps_off", [-1, 1])
def test_a_code_one_step_away_is_accepted_and_reported_as_its_own_step(steps_off: int) -> None:
    then = NOW + steps_off * STEP

    assert totp.matching_step(TEST_TOTP_SECRET, code_at(then), at=NOW) == (
        int(then.timestamp()) // 30
    )


@pytest.mark.parametrize("steps_off", [-10, -3, -2, 2, 3, 10])
def test_a_code_further_away_is_refused(steps_off: int) -> None:
    then = NOW + steps_off * STEP

    assert totp.matching_step(TEST_TOTP_SECRET, code_at(then), at=NOW) is None


def test_the_window_follows_the_setting(settings: LazySettings) -> None:
    settings.TOTP_DRIFT_STEPS = 0

    assert totp.matching_step(TEST_TOTP_SECRET, code_at(NOW), at=NOW) is not None
    assert totp.matching_step(TEST_TOTP_SECRET, code_at(NOW - STEP), at=NOW) is None
    assert totp.matching_step(TEST_TOTP_SECRET, code_at(NOW + STEP), at=NOW) is None


def test_a_code_for_another_secret_is_refused() -> None:
    other = b"TEST-other-secret-00"

    assert totp.matching_step(other, code_at(NOW), at=NOW) is None


@pytest.mark.parametrize(
    "shape",
    ["", " ", "12345", "1234567", "12345a", "abcdef", "12 345", " 123456", "123456 ", "١٢٣٤٥٦"],
    ids=["empty", "space", "short", "long", "letter", "letters", "inner-space", "leading-space",
         "trailing-space", "non-ascii-digits"],
)  # fmt: skip
def test_anything_that_is_not_six_ascii_digits_matches_nothing(shape: str) -> None:
    assert totp.matching_step(TEST_TOTP_SECRET, shape, at=NOW) is None


def test_a_code_padded_to_the_right_shape_is_not_the_code() -> None:
    code = code_at(NOW)

    assert totp.matching_step(TEST_TOTP_SECRET, code + "0", at=NOW) is None
    assert totp.matching_step(TEST_TOTP_SECRET, code[:5], at=NOW) is None


# --- Secrets --------------------------------------------------------------------


def test_a_generated_secret_is_160_random_bits() -> None:
    secrets = {totp.generate_secret() for _ in range(50)}

    assert len(secrets) == 50
    assert {len(secret) for secret in secrets} == {20}


def test_an_encrypted_secret_decrypts_for_the_same_account() -> None:
    ciphertext, key_id = totp.encrypt_secret(TEST_TOTP_SECRET, user_id=7)

    assert totp.decrypt_secret(ciphertext, key_id, user_id=7) == TEST_TOTP_SECRET


def test_the_ciphertext_does_not_contain_the_secret_and_differs_every_time() -> None:
    first, _ = totp.encrypt_secret(TEST_TOTP_SECRET, user_id=7)
    second, _ = totp.encrypt_secret(TEST_TOTP_SECRET, user_id=7)

    assert TEST_TOTP_SECRET not in first
    assert first != second
    # A nonce, the secret's length, and the authentication tag.
    assert len(first) == 12 + len(TEST_TOTP_SECRET) + 16


def test_a_ciphertext_moved_to_another_account_does_not_decrypt() -> None:
    ciphertext, key_id = totp.encrypt_secret(TEST_TOTP_SECRET, user_id=7)

    with pytest.raises(totp.SecretUnavailableError):
        totp.decrypt_secret(ciphertext, key_id, user_id=8)


@pytest.mark.parametrize("position", [0, 11, 12, 20, 31, 32, 47])
def test_an_altered_ciphertext_does_not_decrypt(position: int) -> None:
    ciphertext, key_id = totp.encrypt_secret(TEST_TOTP_SECRET, user_id=7)
    altered = bytearray(ciphertext)
    altered[position] ^= 1

    with pytest.raises(totp.SecretUnavailableError):
        totp.decrypt_secret(bytes(altered), key_id, user_id=7)


@pytest.mark.parametrize("ciphertext", [b"", b"TEST", b"0" * 12, b"0" * 28])
def test_something_that_is_not_a_ciphertext_does_not_decrypt(ciphertext: bytes) -> None:
    _, key_id = totp.encrypt_secret(TEST_TOTP_SECRET, user_id=7)

    with pytest.raises(totp.SecretUnavailableError):
        totp.decrypt_secret(ciphertext, key_id, user_id=7)


def test_a_secret_encrypted_under_another_key_does_not_decrypt(settings: LazySettings) -> None:
    ciphertext, key_id = totp.encrypt_secret(TEST_TOTP_SECRET, user_id=7)
    settings.TOTP_ENCRYPTION_KEY = bytes(range(32))

    with pytest.raises(totp.SecretUnavailableError):
        totp.decrypt_secret(ciphertext, key_id, user_id=7)
    # Not even when the stored identifier is replaced with the new key's.
    _, new_key_id = totp.encrypt_secret(TEST_TOTP_SECRET, user_id=7)
    assert new_key_id != key_id
    with pytest.raises(totp.SecretUnavailableError):
        totp.decrypt_secret(ciphertext, new_key_id, user_id=7)


@pytest.mark.parametrize("key_id", ["", "0" * 16, "ключ-TEST", "0" * 64])
def test_an_unknown_key_identifier_does_not_decrypt(key_id: str) -> None:
    ciphertext, _ = totp.encrypt_secret(TEST_TOTP_SECRET, user_id=7)

    with pytest.raises(totp.SecretUnavailableError):
        totp.decrypt_secret(ciphertext, key_id, user_id=7)


def test_the_key_identifier_names_the_key_without_revealing_it(settings: LazySettings) -> None:
    _, key_id = totp.encrypt_secret(TEST_TOTP_SECRET, user_id=7)
    _, again = totp.encrypt_secret(TEST_TOTP_SECRET, user_id=8)

    assert key_id == again
    assert len(key_id) == 16
    assert key_id not in settings.TOTP_ENCRYPTION_KEY.hex()


@pytest.mark.parametrize("key", [None, b"", b"TEST-too-short", "0" * 32, bytes(33)])
def test_without_a_usable_key_nothing_is_encrypted_or_decrypted(
    settings: LazySettings, key: object
) -> None:
    ciphertext, key_id = totp.encrypt_secret(TEST_TOTP_SECRET, user_id=7)
    settings.TOTP_ENCRYPTION_KEY = key

    with pytest.raises(ImproperlyConfigured, match="TOTP_ENCRYPTION_KEY"):
        totp.encrypt_secret(TEST_TOTP_SECRET, user_id=7)
    with pytest.raises(ImproperlyConfigured, match="TOTP_ENCRYPTION_KEY"):
        totp.decrypt_secret(ciphertext, key_id, user_id=7)


def test_a_missing_key_setting_fails_closed(settings: LazySettings) -> None:
    del settings.TOTP_ENCRYPTION_KEY

    with pytest.raises(ImproperlyConfigured, match="TOTP_ENCRYPTION_KEY"):
        totp.encrypt_secret(TEST_TOTP_SECRET, user_id=7)


# --- Provisioning ---------------------------------------------------------------


def test_the_manual_entry_key_is_the_secret_in_base32() -> None:
    assert totp.manual_entry_key(RFC_SECRET) == "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


def test_the_provisioning_uri_names_the_issuer_and_the_account_and_nothing_else() -> None:
    uri = totp.provisioning_uri(RFC_SECRET, account="test.user@caipo.test")

    assert uri == (
        "otpauth://totp/CAIPO:test.user%40caipo.test"
        "?digits=6&secret=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ&algorithm=SHA1&issuer=CAIPO&period=30"
    )
