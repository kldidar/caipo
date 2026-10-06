"""What binds a session to its account, with and without a session epoch (ADR-0017 point 46).

Only the authorisation of a recovery raises an account's epoch, and that is
tested with it. These tests fix what the value means: at 0, exactly what
Django computes, so that no session established before the field existed is
ended by it.
"""

import pytest
from django.conf import LazySettings
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import IntegrityError, transaction
from django.utils.crypto import salted_hmac

from caipo.accounts.models import User

EMAIL = "test.account@caipo.test"
PASSWORD = "TEST-passphrase-for-fixtures-only"
# Visibly synthetic: what stands in the password column in the tests that need
# no real hash.
STORED = "TEST$not-a-real-password-hash"
RETIRED_KEYS = ["TEST-retired-secret-key-one", "TEST-retired-secret-key-two"]
# The salt of Django's own value, written out here on purpose: these tests
# must fail if the value at epoch 0 ever stops being Django's.
DJANGO_SALT = "django.contrib.auth.models.AbstractBaseUser.get_session_auth_hash"


def _account(epoch: int, stored: str = STORED) -> User:
    return User(email=EMAIL, password=stored, session_epoch=epoch)


def _django_value(stored: str, secret: str | None = None) -> str:
    return salted_hmac(DJANGO_SALT, stored, secret=secret, algorithm="sha256").hexdigest()


def test_an_account_is_made_at_epoch_zero() -> None:
    assert User(email=EMAIL).session_epoch == 0
    assert User._meta.get_field("session_epoch").default == 0


def test_at_epoch_zero_the_value_is_exactly_djangos() -> None:
    account = _account(0)

    assert account.get_session_auth_hash() == _django_value(STORED)
    assert account.get_session_auth_hash() == AbstractBaseUser.get_session_auth_hash(account)


def test_at_epoch_zero_the_values_under_retired_keys_are_exactly_djangos(
    settings: LazySettings,
) -> None:
    settings.SECRET_KEY_FALLBACKS = RETIRED_KEYS
    account = _account(0)

    values = list(account.get_session_auth_fallback_hash())

    assert values == [_django_value(STORED, key) for key in RETIRED_KEYS]
    assert values == list(AbstractBaseUser.get_session_auth_fallback_hash(account))


def test_with_no_retired_key_there_is_no_other_value(settings: LazySettings) -> None:
    settings.SECRET_KEY_FALLBACKS = []

    for epoch in (0, 1):
        assert list(_account(epoch).get_session_auth_fallback_hash()) == []


@pytest.mark.parametrize("epoch", [1, 2, 10, 2147483647])
def test_above_zero_the_value_is_never_djangos(epoch: int, settings: LazySettings) -> None:
    settings.SECRET_KEY_FALLBACKS = RETIRED_KEYS
    account = _account(epoch)
    djangos = {_django_value(STORED), *(_django_value(STORED, key) for key in RETIRED_KEYS)}

    assert account.get_session_auth_hash() not in djangos
    assert djangos.isdisjoint(account.get_session_auth_fallback_hash())


def test_every_epoch_has_a_value_of_its_own(settings: LazySettings) -> None:
    settings.SECRET_KEY_FALLBACKS = RETIRED_KEYS
    epochs = range(0, 6)

    current = [_account(epoch).get_session_auth_hash() for epoch in epochs]
    retired = [tuple(_account(epoch).get_session_auth_fallback_hash()) for epoch in epochs]

    assert len(set(current)) == len(epochs)
    assert len(set(retired)) == len(epochs)
    assert all(len(values) == len(RETIRED_KEYS) for values in retired)
    assert set(current).isdisjoint(value for values in retired for value in values)


@pytest.mark.parametrize("epoch", [0, 1, 2])
def test_the_value_is_the_same_each_time_it_is_asked_for(epoch: int) -> None:
    assert _account(epoch).get_session_auth_hash() == _account(epoch).get_session_auth_hash()
    assert len(_account(epoch).get_session_auth_hash()) == 64


@pytest.mark.parametrize("epoch", [0, 1, 2])
def test_the_password_is_part_of_the_value_at_every_epoch(epoch: int) -> None:
    before = _account(epoch, STORED).get_session_auth_hash()
    after = _account(epoch, STORED + "-changed").get_session_auth_hash()

    assert before != after


@pytest.mark.parametrize("epoch", [0, 1, 2])
def test_the_secret_key_is_part_of_the_value_at_every_epoch(
    epoch: int, settings: LazySettings
) -> None:
    before = _account(epoch).get_session_auth_hash()
    settings.SECRET_KEY = "TEST-another-secret-key-for-the-session-epoch-tests"

    assert _account(epoch).get_session_auth_hash() != before


def test_the_value_under_a_retired_key_is_what_that_key_gave_when_it_was_current(
    settings: LazySettings,
) -> None:
    account = _account(3)
    settings.SECRET_KEY = RETIRED_KEYS[0]
    when_current = account.get_session_auth_hash()

    settings.SECRET_KEY = "TEST-another-secret-key-for-the-session-epoch-tests"
    settings.SECRET_KEY_FALLBACKS = [RETIRED_KEYS[0]]

    assert list(account.get_session_auth_fallback_hash()) == [when_current]
    assert account.get_session_auth_hash() != when_current


def test_the_epoch_and_the_password_cannot_be_read_two_ways() -> None:
    # 1 and "1:x" against 11 and ":x": the same characters, split differently.
    assert (
        _account(1, "1:TEST").get_session_auth_hash()
        != _account(11, ":TEST").get_session_auth_hash()
    )


@pytest.mark.services
@pytest.mark.django_db
def test_an_account_is_stored_at_epoch_zero_and_keeps_the_epoch_it_is_given() -> None:
    user = User.objects.create_user(EMAIL, PASSWORD)

    stored = User.objects.get(pk=user.pk)
    assert stored.session_epoch == 0
    assert stored.get_session_auth_hash() == _django_value(stored.password)

    User.objects.filter(pk=user.pk).update(session_epoch=1)
    raised = User.objects.get(pk=user.pk)
    assert raised.session_epoch == 1
    assert raised.password == stored.password
    assert raised.get_session_auth_hash() != stored.get_session_auth_hash()


@pytest.mark.services
@pytest.mark.django_db
def test_the_database_rejects_an_epoch_below_zero() -> None:
    user = User.objects.create_user(EMAIL, PASSWORD)

    with pytest.raises(IntegrityError, match="session_epoch"), transaction.atomic():
        User.objects.filter(pk=user.pk).update(session_epoch=-1)

    assert User.objects.get(pk=user.pk).session_epoch == 0
