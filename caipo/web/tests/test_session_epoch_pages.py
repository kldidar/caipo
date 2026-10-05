"""Sessions and the session epoch, over HTTP (ADR-0017 point 46).

Nothing raises an account's epoch yet, so these tests raise it in the
database. They show what the value does to a session, and above all that an
account at epoch 0 keeps the sessions it had before the epoch existed.
"""

from typing import Any

import pytest
from django.conf import LazySettings
from django.contrib.sessions.models import Session
from django.test import Client
from django.utils.crypto import salted_hmac

from caipo.accounts.models import RoleEvent, RoleEventType, User
from caipo.accounts.selectors import Role
from caipo.accounts.tests.fixtures import supporting_account

pytestmark = [pytest.mark.services, pytest.mark.django_db]

EMAIL = "test.reader@caipo.test"
OTHER_EMAIL = "test.other.reader@caipo.test"
PASSWORD = "TEST-passphrase-for-fixtures-only"
NEW_PASSWORD = "TEST-another-passphrase-for-fixtures"

LOGIN = "/login/"
# A page that needs a permission every role holds.
OWN_PAGE = "/account/second-factor/"
HASH_KEY = "_auth_user_hash"
# The salt of Django's own value, written out here on purpose.
DJANGO_SALT = "django.contrib.auth.models.AbstractBaseUser.get_session_auth_hash"


def _reader(email: str = EMAIL) -> User:
    user = User.objects.create_user(email, PASSWORD)
    RoleEvent.objects.create(
        user=user,
        role=Role.READER,
        event_type=RoleEventType.GRANTED,
        actor=supporting_account("test.seed@caipo.test"),
        reason="TEST fixture",
    )
    return user


def _signed_in(user: User) -> Client:
    client = Client()
    response = client.post(LOGIN, {"email": user.email, "password": PASSWORD})
    assert response.status_code == 302
    return client


def _django_value(user: User, secret: str | None = None) -> str:
    stored = User.objects.get(pk=user.pk).password
    return salted_hmac(DJANGO_SALT, stored, secret=secret, algorithm="sha256").hexdigest()


def _raise_epoch(user: User, to: int = 1) -> None:
    User.objects.filter(pk=user.pk).update(session_epoch=to)


def _recognised(client: Client) -> bool:
    status = client.get(OWN_PAGE).status_code
    assert status in (200, 403)
    return bool(status == 200)


def test_a_sign_in_at_epoch_zero_stores_exactly_what_django_stores() -> None:
    user = _reader()

    client = _signed_in(user)

    assert client.session[HASH_KEY] == _django_value(user)
    assert _recognised(client)


def test_a_session_from_before_the_epoch_existed_is_still_recognised() -> None:
    user = _reader()
    client = Client()
    client.force_login(user)
    # Exactly what a session held before this field was added: Django's keys
    # and Django's value, written here and not by the code under test.
    session = client.session
    session[HASH_KEY] = _django_value(user)
    session.save()
    key = session.session_key

    assert _recognised(client)
    assert _recognised(client)
    # Recognised as it was: the same session, and nothing rewritten in it.
    assert client.session.session_key == key
    assert client.session[HASH_KEY] == _django_value(user)
    assert client.session["_auth_user_id"] == str(user.pk)


def test_raising_the_epoch_ends_the_accounts_sessions_on_their_next_request() -> None:
    user = _reader()
    first, second = _signed_in(user), _signed_in(user)
    keys = {first.session.session_key, second.session.session_key}
    assert _recognised(first)
    assert _recognised(second)

    _raise_epoch(user)

    assert not _recognised(first)
    assert not _recognised(second)
    assert "_auth_user_id" not in first.session
    assert "_auth_user_id" not in second.session
    # Not merely unrecognised: gone from the server.
    assert not Session.objects.filter(session_key__in=keys).exists()


def test_raising_the_epoch_changes_nothing_else_about_the_account() -> None:
    user = _reader()
    before: dict[str, Any] = dict(User.objects.filter(pk=user.pk).values().get())

    _raise_epoch(user)

    after: dict[str, Any] = dict(User.objects.filter(pk=user.pk).values().get())
    assert {name for name in before if before[name] != after[name]} == {"session_epoch"}


def test_raising_one_accounts_epoch_leaves_every_other_session_alone() -> None:
    user, other = _reader(), _reader(OTHER_EMAIL)
    client, others = _signed_in(user), _signed_in(other)
    key = others.session.session_key

    _raise_epoch(user)

    assert not _recognised(client)
    assert _recognised(others)
    assert others.session.session_key == key
    assert others.session[HASH_KEY] == _django_value(other)


def test_a_sign_in_after_the_epoch_was_raised_is_recognised_under_the_new_epoch() -> None:
    user = _reader()
    old = _signed_in(user)
    _raise_epoch(user)

    new = _signed_in(user)

    assert _recognised(new)
    assert _recognised(new)
    assert new.session[HASH_KEY] != _django_value(user)
    assert not _recognised(old)


def test_a_session_of_one_epoch_is_not_recognised_at_a_later_one() -> None:
    user = _reader()
    _raise_epoch(user, to=1)
    client = _signed_in(user)
    assert _recognised(client)

    _raise_epoch(user, to=2)

    assert not _recognised(client)


def test_the_old_value_cannot_be_put_back_into_a_session_after_the_epoch_was_raised() -> None:
    user = _reader()
    _raise_epoch(user)
    client = Client()
    client.force_login(User.objects.get(pk=user.pk))
    session = client.session
    session[HASH_KEY] = _django_value(user)
    session.save()

    assert not _recognised(client)


@pytest.mark.parametrize("epoch", [0, 1])
def test_changing_the_password_still_ends_the_sessions_at_any_epoch(epoch: int) -> None:
    user = _reader()
    _raise_epoch(user, to=epoch)
    client = _signed_in(user)
    assert _recognised(client)

    stored = User.objects.get(pk=user.pk)
    stored.set_password(NEW_PASSWORD)
    stored.save(update_fields=["password"])

    assert not _recognised(client)
    assert User.objects.get(pk=user.pk).session_epoch == epoch


@pytest.mark.parametrize("epoch", [0, 1])
def test_a_session_made_under_a_retired_secret_key_is_kept_at_its_own_epoch(
    epoch: int, settings: LazySettings
) -> None:
    user = _reader()
    _raise_epoch(user, to=epoch)
    retired = settings.SECRET_KEY
    client = _signed_in(user)
    under_retired_key = client.session[HASH_KEY]

    settings.SECRET_KEY = "TEST-another-secret-key-for-the-session-epoch-tests"
    settings.SECRET_KEY_FALLBACKS = [retired]

    assert _recognised(client)
    # Django moves the session to the current key, as it always has.
    assert client.session[HASH_KEY] == User.objects.get(pk=user.pk).get_session_auth_hash()
    assert client.session[HASH_KEY] != under_retired_key


def test_a_retired_secret_key_does_not_revive_a_session_of_an_earlier_epoch(
    settings: LazySettings,
) -> None:
    user = _reader()
    retired = settings.SECRET_KEY
    client = _signed_in(user)

    _raise_epoch(user)
    settings.SECRET_KEY = "TEST-another-secret-key-for-the-session-epoch-tests"
    settings.SECRET_KEY_FALLBACKS = [retired]

    assert not _recognised(client)
