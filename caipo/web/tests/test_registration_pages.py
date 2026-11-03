"""Registering an account on the site over HTTP (ADR-0021).

Somebody who is not signed in gives an email address, opens the link in the
message, chooses a password, signs in, and can read the workspace and do
nothing else. Messages go to the in-memory backend, and the token is read from
the message as the person receiving it would read it.
"""

import re
from typing import Any

import pytest
from django.conf import LazySettings
from django.core import mail as django_mail
from django.test import Client
from django.utils import timezone

from caipo.accounts.models import AccountEvent, AccountStatus, RoleEvent, User
from caipo.accounts.selectors import Role
from caipo.web import registration
from caipo.web.access import PUBLIC, declared_access

pytestmark = [pytest.mark.services, pytest.mark.django_db]

# Visibly synthetic fixture values.
EMAIL = "test.registrant@caipo.test"
PASSWORD = "TEST-passphrase-chosen-at-activation"
ORIGIN = "http://testserver"

HOME = "/"
LOGIN = "/login/"
REGISTER = "/register/"
ACTIVATE = "/activate/"
RESET = "/password-reset/"
POLICIES = "/policies/"
NEW_POLICY = "/policies/new/"

SENT = "If that address can be registered, a message with a link has been sent to it."
OUTBOX = "data/outbox/"


def _register(client: Client, email: str = EMAIL, **extra: str) -> Any:
    return client.post(REGISTER, {"email": email, **extra})


def _link(index: int = -1) -> str:
    (link,) = re.findall(r"https?://\S+", str(django_mail.outbox[index].body))
    return str(link)


def _answer(response: Any) -> tuple[int, str, str]:
    """Return what tells responses apart: status, redirect, and the page without its CSRF token."""
    body = re.sub(r'name="csrfmiddlewaretoken" value="[^"]+"', "", response.content.decode())
    return response.status_code, response.get("Location", ""), body


def _account(email: str, status: AccountStatus) -> User:
    now = timezone.now()
    verified = None if status == AccountStatus.PENDING_VERIFICATION else now
    user = User(email=email, status=status, email_verified_at=verified, activated_at=verified)
    user.set_password("TEST-passphrase-of-an-existing-account")
    user.save()
    return user


# --- From registration to a signed-in Reader --------------------------------------------


def test_from_registration_to_a_reader_who_can_read_and_cannot_add(client: Client) -> None:
    page = client.get(REGISTER)
    assert page.status_code == 200

    registered = _register(client)
    assert registered.status_code == 200
    assert SENT in registered.content.decode()
    address, token = _link().split("#", 1)
    assert address == f"{ORIGIN}{ACTIVATE}"
    assert client.get(address.removeprefix(ORIGIN)).status_code == 200
    activated = client.post(
        ACTIVATE, {"token": token, "password": PASSWORD, "password_again": PASSWORD}
    )
    assert activated.status_code == 302
    assert activated["Location"] == f"{LOGIN}?activated=1"

    signed_in = client.post(LOGIN, {"email": EMAIL, "password": PASSWORD})

    assert signed_in.status_code == 302
    assert client.get(HOME).status_code == 200
    assert client.get(POLICIES).status_code == 200
    assert client.get(NEW_POLICY).status_code == 403
    user = User.objects.get(email=EMAIL)
    assert user.status == AccountStatus.ACTIVE
    (grant,) = RoleEvent.objects.filter(user=user)
    assert (grant.role, grant.actor_id) == (Role.READER, None)


# --- The page ------------------------------------------------------------------------------


def test_the_page_is_public_and_never_cached(client: Client) -> None:
    response = client.get(REGISTER)

    assert response.status_code == 200
    assert "no-store" in response["Cache-Control"]
    assert "private" in response["Cache-Control"]
    assert client.session.get("_auth_user_id") is None
    assert not AccountEvent.objects.exists()


def test_the_page_declares_public_access() -> None:
    assert declared_access(registration.register) == PUBLIC


def test_the_page_asks_for_an_email_address_and_nothing_else(client: Client) -> None:
    body = client.get(REGISTER).content.decode()

    (form,) = re.findall(r"<form.*?</form>", body, flags=re.DOTALL)
    names = set(re.findall(r'name="([^"]+)"', form)) - {"csrfmiddlewaretoken"}
    assert names == {"email"}
    assert 'type="password"' not in body


def test_the_page_says_what_an_account_can_do_and_what_is_kept(client: Client) -> None:
    body = client.get(REGISTER).content.decode()

    assert "It cannot add or change records." in body
    assert "CAIPO keeps your email address" in body
    assert f'href="{LOGIN}"' in body


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_the_page_accepts_get_and_post_only(client: Client, method: str) -> None:
    assert getattr(client, method)(REGISTER).status_code == 405


def test_registering_without_a_csrf_token_is_refused() -> None:
    client = Client(enforce_csrf_checks=True)

    response = _register(client)

    assert response.status_code == 403
    assert not User.objects.exists()
    assert django_mail.outbox == []


def test_the_sign_in_page_and_the_public_home_page_link_to_it(client: Client) -> None:
    assert f'href="{REGISTER}"' in client.get(LOGIN).content.decode()
    assert f'href="{REGISTER}"' in client.get(HOME).content.decode()
    assert "There is no public registration" not in client.get(LOGIN).content.decode()


# --- What a registration tells ------------------------------------------------------------


def test_every_registration_gets_the_same_answer(settings: LazySettings) -> None:
    _account("test.active@caipo.test", AccountStatus.ACTIVE)
    _account("test.disabled@caipo.test", AccountStatus.DISABLED)
    _account("test.pending@caipo.test", AccountStatus.PENDING_VERIFICATION)
    settings.ACCOUNT_REGISTRATION_SOURCE_LIMIT = 5

    answers = {
        name: _answer(_register(Client(), email))
        for name, email in {
            "new": EMAIL,
            "active": "test.active@caipo.test",
            "disabled": "test.disabled@caipo.test",
            "pending": "test.pending@caipo.test",
            "differently typed": "  Test.Active@CAIPO.test ",
            "throttled": "test.throttled@caipo.test",
        }.items()
    }

    assert len(set(answers.values())) == 1, {name: answer[0] for name, answer in answers.items()}
    status, location, body = answers["new"]
    assert (status, location) == (200, "")
    assert SENT in body
    # Nothing that was submitted, and nothing about any account, is in the page.
    assert "caipo.test" not in body.lower()
    assert "registrant" not in body.lower()
    # Only the new and the pending accounts were sent anything; the throttled one stored nothing.
    assert [message.to for message in django_mail.outbox] == [
        [EMAIL],
        ["test.pending@caipo.test"],
    ]
    assert not User.objects.filter(email="test.throttled@caipo.test").exists()


def test_a_message_that_cannot_be_sent_gets_the_same_answer(settings: LazySettings) -> None:
    _account("test.active@caipo.test", AccountStatus.ACTIVE)
    settings.EMAIL_BACKEND = "caipo.core.mail.RefusingEmailBackend"

    assert _answer(_register(Client())) == _answer(_register(Client(), "test.active@caipo.test"))
    assert User.objects.filter(email=EMAIL).exists()


@pytest.mark.parametrize(
    "typed",
    ["", "   ", "not-an-address", "TEST-passphrase-typed-in-the-wrong-field", "a@" + "b" * 260],
    ids=["empty", "blank", "no-at-sign", "a-password", "too-long"],
)
def test_a_malformed_address_is_refused_and_not_put_back(client: Client, typed: str) -> None:
    response = _register(client, typed)

    body = response.content.decode()
    assert response.status_code == 200
    assert "Enter a valid email address." in body
    assert SENT not in body
    if typed.strip():
        assert typed not in body
    assert 'value="' not in re.sub(r'name="csrfmiddlewaretoken" value="[^"]+"', "", body)
    assert not User.objects.exists()
    assert django_mail.outbox == []


def test_a_role_sent_with_the_form_is_ignored(client: Client) -> None:
    _register(client, role=Role.ADMINISTRATOR)

    user = User.objects.get(email=EMAIL)
    assert list(RoleEvent.objects.filter(user=user).values_list("role", flat=True)) == [Role.READER]


def test_registering_takes_the_address_from_the_form_and_never_from_the_url(
    client: Client,
) -> None:
    response = client.post(f"{REGISTER}?email={EMAIL}", {"email": "test.form@caipo.test"})

    assert response.status_code == 200
    assert not User.objects.filter(email=EMAIL).exists()
    assert User.objects.filter(email="test.form@caipo.test").exists()


def test_a_forwarded_header_cannot_move_a_registration_to_another_source(
    settings: LazySettings,
) -> None:
    settings.ACCOUNT_REGISTRATION_SOURCE_LIMIT = 1
    _register(Client(), "test.first@caipo.test")

    _register(Client(HTTP_X_FORWARDED_FOR="198.51.100.200"))

    assert not User.objects.filter(email=EMAIL).exists()


# --- Where development messages go ----------------------------------------------------------


@pytest.mark.parametrize(("url", "debug"), [(REGISTER, True), (RESET, True), (REGISTER, False)])
def test_development_says_messages_are_written_to_the_outbox(
    client: Client, settings: LazySettings, url: str, debug: bool
) -> None:
    settings.DEBUG = debug

    body = client.post(url, {"email": EMAIL}).content.decode()

    assert (OUTBOX in body) is debug


def test_the_outbox_is_not_mentioned_before_anything_is_asked(
    client: Client, settings: LazySettings
) -> None:
    settings.DEBUG = True

    assert OUTBOX not in client.get(REGISTER).content.decode()
    assert OUTBOX not in client.get(RESET).content.decode()
