"""Resetting a forgotten password over HTTP (ADR-0016).

Somebody who is not signed in asks for a message, opens the link, and chooses a
new password. Messages go to the in-memory backend, and the token is read from
the message as the person receiving it would read it.
"""

import logging
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from django.conf import LazySettings
from django.contrib.sessions.models import Session
from django.contrib.staticfiles import finders
from django.core import mail as django_mail
from django.http import HttpRequest, HttpResponse
from django.test import Client
from django.urls import include, path
from django.utils import timezone

from caipo.accounts import services
from caipo.accounts.models import (
    AccountStatus,
    AuthenticationEvent,
    MfaChallenge,
    PasswordReset,
    User,
)
from caipo.accounts.selectors import Permission, Role
from caipo.accounts.tests.fixtures import (
    Clock,
    UserFactory,
    approving_administrator,
    code_at,
    enrolled_device,
    logged,
)
from caipo.web import password_reset, sessions
from caipo.web.access import PUBLIC, declared_access, requires
from caipo.web.tests.helpers import signed_in

pytestmark = [pytest.mark.services, pytest.mark.django_db, pytest.mark.urls(__name__)]

# Visibly synthetic fixture values.
EMAIL = "test.forgetful@caipo.test"
OTHER_EMAIL = "test.other.forgetful@caipo.test"
UNKNOWN = "test.nobody@caipo.test"
OLD_PASSWORD = "TEST-passphrase-that-was-forgotten"
PASSWORD = "TEST-passphrase-chosen-afterwards"
OTHER_PASSWORD = "TEST-another-passphrase-entirely"
ORIGIN = "http://testserver"

LOGIN = "/login/"
VERIFY = "/login/verify/"
ACTIVATE = "/activate/"
REQUEST = "/password-reset/"
CONFIRM = "/password-reset/confirm/"
WORKSPACE = "/workspace/"

SENT = "a message with a link has been sent"
REFUSED = "That code was not accepted."


@requires(Permission.WORKSPACE_READ)
def workspace_view(request: HttpRequest) -> HttpResponse:
    return HttpResponse("TEST workspace")


# The real routes, plus one view that needs a signed-in Reader.
urlpatterns = [
    path("", include("caipo.web.urls")),
    path("workspace/", workspace_view),
]


@pytest.fixture
def user(user_with_roles: UserFactory) -> User:
    """Return an active Reader with the password that was forgotten."""
    reader = user_with_roles(Role.READER)
    reader.email = EMAIL
    reader.set_password(OLD_PASSWORD)
    reader.save()
    return reader


def _account(email: str, status: AccountStatus) -> User:
    """Return a synthetic account written directly in the given state."""
    now = timezone.now()
    verified = None if status == AccountStatus.PENDING_VERIFICATION else now
    account = User(email=email, status=status, email_verified_at=verified, activated_at=verified)
    account.set_password(OLD_PASSWORD)
    account.save()
    return account


def _ask(client: Client, email: str = EMAIL, **extra: str) -> Any:
    return client.post(REQUEST, {"email": email, **extra})


def _link(index: int = -1) -> str:
    """Read the link off a reset message, by default the last one sent."""
    (link,) = re.findall(r"https?://\S+", str(django_mail.outbox[index].body))
    return str(link)


def _token(index: int = -1) -> str:
    return _link(index).split("#", 1)[1]


def _asked(client: Client, email: str = EMAIL) -> str:
    """Ask for a reset and return the token that was sent."""
    sent = len(django_mail.outbox)
    assert _ask(client, email).status_code == 200
    assert len(django_mail.outbox) == sent + 1
    return _token()


def _set(client: Client, token: str, password: str = PASSWORD, **extra: str) -> Any:
    return client.post(
        CONFIRM, {"token": token, "password": password, "password_again": password, **extra}
    )


def _signed_in_as(client: Client) -> str | None:
    user_id: str | None = client.session.get("_auth_user_id")
    return user_id


def _events() -> list[str]:
    return list(AuthenticationEvent.objects.order_by("id").values_list("event_type", flat=True))


def _visible_text(body: str) -> str:
    """Return what a person sees of a page: its text, without tags and their attributes."""
    return re.sub(r"<[^>]*>", " ", body)


def _answer(response: Any) -> tuple[int, str, str]:
    """Return what tells responses apart: status, redirect, and the page without its CSRF token."""
    body = re.sub(r'name="csrfmiddlewaretoken" value="[^"]+"', "", response.content.decode())
    return response.status_code, response.get("Location", ""), body


# --- From a forgotten password to a signed-in account -----------------------------------------


def test_a_password_from_forgotten_to_the_next_sign_in(client: Client, user: User) -> None:
    assert client.post(LOGIN, {"email": EMAIL, "password": PASSWORD}).status_code == 200

    asked = _ask(client)
    assert asked.status_code == 200
    assert SENT in asked.content.decode()
    link = _link()
    address, token = link.split("#", 1)
    assert address == f"{ORIGIN}{CONFIRM}"

    # What a browser requests when the link is opened: the part before the "#".
    page = client.get(address.removeprefix(ORIGIN))
    assert page.status_code == 200
    reset = _set(client, token)

    assert reset.status_code == 302
    assert reset["Location"] == f"{LOGIN}?reset=1"
    assert _signed_in_as(client) is None
    after = client.get(reset["Location"])
    assert "Your password has been changed" in after.content.decode()
    assert client.post(LOGIN, {"email": EMAIL, "password": OLD_PASSWORD}).status_code == 200
    assert _signed_in_as(client) is None
    assert client.post(LOGIN, {"email": EMAIL, "password": PASSWORD})["Location"] == LOGIN
    assert _signed_in_as(client) == str(user.pk)
    assert _events() == [
        "login_failure",
        "password_reset_requested",
        "password_reset_succeeded",
        "login_failure",
        "login_success",
    ]


def test_the_sign_in_page_links_to_the_reset_page(client: Client) -> None:
    assert f'href="{REQUEST}"' in client.get(LOGIN).content.decode()


# --- The two pages ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", [REQUEST, CONFIRM])
def test_the_pages_are_public_and_never_cached(client: Client, url: str) -> None:
    response = client.get(url)

    assert response.status_code == 200
    assert "no-store" in response["Cache-Control"]
    assert "private" in response["Cache-Control"]
    assert _signed_in_as(client) is None
    assert AuthenticationEvent.objects.count() == 0


def test_the_pages_declare_public_access() -> None:
    assert declared_access(password_reset.request_reset) == PUBLIC
    assert declared_access(password_reset.confirm_reset) == PUBLIC


def test_the_request_page_asks_for_an_email_address_and_nothing_else(client: Client) -> None:
    body = client.get(REQUEST).content.decode()

    assert 'type="email"' in body
    assert 'type="password"' not in body
    assert "<script" not in body
    assert f'action="{REQUEST}"' in body and 'method="post"' in body


def test_the_confirmation_page_shows_a_form_and_loads_the_script_that_reads_the_link(
    client: Client,
) -> None:
    body = client.get(CONFIRM).content.decode()

    assert 'id="id_token"' in body
    assert body.count('type="password"') == 2
    assert f'action="{CONFIRM}"' in body and 'method="post"' in body
    # The script activation uses, and no inline script: only the one static file.
    assert 'src="/static/web/activate.js"' in body
    assert body.count("<script") == 1


def test_the_script_fills_the_field_this_page_has_and_sends_the_code_nowhere(
    client: Client,
) -> None:
    found = finders.find("web/activate.js")
    assert found is not None
    script = Path(str(found)).read_text()

    # The field the script looks for is the one the page renders.
    (field,) = re.findall(r'getElementById\("([^"]+)"\)', script)
    assert f'id="{field}"' in client.get(CONFIRM).content.decode()
    assert "window.location.hash" in script
    assert "replaceState" in script
    assert "window.location.pathname" in script
    for sender in ("fetch", "XMLHttpRequest", "sendBeacon", "http", "cookie", "localStorage"):
        assert sender not in script


@pytest.mark.parametrize("url", [REQUEST, CONFIRM])
@pytest.mark.parametrize("method", ["head", "put", "patch", "delete"])
def test_the_pages_accept_get_and_post_only(
    client: Client, user: User, url: str, method: str
) -> None:
    response = getattr(client, method)(f"{url}?email={EMAIL}")

    assert response.status_code == 405
    assert _events() == []
    assert django_mail.outbox == []


def test_asking_without_a_csrf_token_is_refused(user: User) -> None:
    client = Client(enforce_csrf_checks=True)

    assert _ask(client).status_code == 403
    assert _events() == []
    assert django_mail.outbox == []

    client.get(REQUEST)
    csrf = client.cookies["csrftoken"].value
    assert _ask(client, csrfmiddlewaretoken=csrf).status_code == 200
    assert len(django_mail.outbox) == 1


def test_setting_the_password_without_a_csrf_token_is_refused(user: User) -> None:
    token = _asked(Client())
    client = Client(enforce_csrf_checks=True)

    assert _set(client, token).status_code == 403
    assert User.objects.get(pk=user.pk).check_password(OLD_PASSWORD) is True
    assert PasswordReset.objects.exists()

    client.get(CONFIRM)
    csrf = client.cookies["csrftoken"].value
    assert _set(client, token, csrfmiddlewaretoken=csrf).status_code == 302


# --- Asking: one answer ------------------------------------------------------------------------


def test_every_request_gets_the_same_answer(
    client: Client, user: User, user_with_roles: UserFactory, settings: LazySettings
) -> None:
    _account("test.pending@caipo.test", AccountStatus.PENDING_VERIFICATION)
    _account("test.disabled@caipo.test", AccountStatus.DISABLED)
    unverified = user_with_roles(Role.ADMINISTRATOR)
    assert unverified.email_verified_at is None
    for _ in range(settings.PASSWORD_RESET_REQUEST_EMAIL_LIMIT):
        _ask(Client(), "test.throttled@caipo.test")
    events = AuthenticationEvent.objects.count()

    answers = {
        name: _answer(_ask(Client(), email))
        for name, email in {
            "active": EMAIL,
            "unknown": UNKNOWN,
            "pending": "test.pending@caipo.test",
            "disabled": "test.disabled@caipo.test",
            "unverified": unverified.email,
            "throttled": "test.throttled@caipo.test",
            "differently typed": "  Test.Forgetful@CAIPO.test ",
        }.items()
    }

    assert len(set(answers.values())) == 1, {name: answer[0] for name, answer in answers.items()}
    status, location, body = answers["unknown"]
    assert (status, location) == (200, "")
    assert SENT in body
    # Nothing that was submitted, and nothing about any account, is in the page.
    assert "caipo.test" not in body.lower()
    assert "forgetful" not in body.lower()
    # Only the three eligible requests sent anything, and the throttled one stored nothing.
    assert [message.to for message in django_mail.outbox] == [[EMAIL], [unverified.email], [EMAIL]]
    assert AuthenticationEvent.objects.count() == events + 6


def test_a_request_throttled_by_its_source_gets_the_same_answer_and_sends_nothing(
    client: Client, user: User, settings: LazySettings
) -> None:
    settings.PASSWORD_RESET_REQUEST_SOURCE_LIMIT = 3
    answers = [_answer(_ask(client, f"test.nobody{number}@caipo.test")) for number in range(3)]

    throttled = _answer(_ask(client))

    assert throttled == answers[0] == answers[2]
    assert throttled[0] == 200
    assert django_mail.outbox == []
    assert not PasswordReset.objects.exists()
    assert _events() == ["password_reset_requested"] * 3


def test_a_message_that_cannot_be_sent_gets_the_same_answer(
    client: Client, user: User, settings: LazySettings
) -> None:
    settings.EMAIL_BACKEND = "caipo.core.mail.RefusingEmailBackend"

    assert _answer(_ask(client)) == _answer(_ask(Client(), UNKNOWN))


@pytest.mark.parametrize(
    "typed",
    ["", "   ", "not-an-address", "TEST-passphrase-typed-in-the-wrong-field", "a@" + "b" * 260],
    ids=["empty", "blank", "no-at-sign", "a-password", "too-long"],
)
def test_a_malformed_address_is_refused_by_the_form_and_not_put_back(
    client: Client, user: User, typed: str
) -> None:
    response = _ask(client, typed)

    body = response.content.decode()
    assert response.status_code == 200
    assert "Enter a valid email address." in body
    assert SENT not in body
    if typed.strip():
        assert typed not in body
    assert 'value="' not in re.sub(r'name="csrfmiddlewaretoken" value="[^"]+"', "", body)
    assert _events() == []
    assert django_mail.outbox == []


def test_asking_takes_the_address_from_the_form_and_never_from_the_url(
    client: Client, user: User
) -> None:
    assert client.get(f"{REQUEST}?email={EMAIL}").status_code == 200
    posted = client.post(f"{REQUEST}?email={EMAIL}", {})

    assert posted.status_code == 200
    assert EMAIL not in posted.content.decode()
    assert _events() == []
    assert django_mail.outbox == []


def test_asking_while_signed_in_changes_nothing_about_the_session(
    client: Client, user: User, user_with_roles: UserFactory
) -> None:
    other = user_with_roles(Role.READER)
    signed_in(client, other)

    assert _answer(_ask(client)) == _answer(_ask(Client(), UNKNOWN))

    assert _signed_in_as(client) == str(other.pk)
    assert PasswordReset.objects.get().user == user


# --- The public address in the link -------------------------------------------------------------


def test_the_link_uses_the_configured_address_and_nothing_from_the_request(
    client: Client, user: User, settings: LazySettings
) -> None:
    settings.PUBLIC_BASE_URL = "https://caipo.example.test"
    settings.ALLOWED_HOSTS = ["testserver", "evil.test"]

    response = client.post(
        f"{REQUEST}?next=https://evil.test&origin=https://evil.test",
        {
            "email": EMAIL,
            "origin": "https://evil.test",
            "public_url": "https://evil.test",
            "reset_url": "https://evil.test/password-reset/confirm/",
            "next": "https://evil.test",
        },
        HTTP_HOST="evil.test",
        HTTP_X_FORWARDED_HOST="evil.test",
        HTTP_X_FORWARDED_PROTO="http",
        HTTP_ORIGIN="https://evil.test",
        HTTP_REFERER="https://evil.test/",
        HTTP_FORWARDED="host=evil.test;proto=http",
    )

    assert response.status_code == 200
    assert _link() == f"https://caipo.example.test{CONFIRM}#{_token()}"
    assert "evil.test" not in str(django_mail.outbox[0].body)
    assert "evil.test" not in str(django_mail.outbox[0].message())


def test_a_host_that_is_not_allowed_is_refused_before_anything_is_sent(
    client: Client, user: User
) -> None:
    response = client.post(REQUEST, {"email": EMAIL}, HTTP_HOST="evil.test")

    assert response.status_code == 400
    assert django_mail.outbox == []
    assert not PasswordReset.objects.exists()


def test_the_link_is_built_from_the_setting_alone() -> None:
    assert password_reset.reset_url("TEST-token") == f"{ORIGIN}{CONFIRM}#TEST-token"
    source = Path(password_reset.__file__).read_text()
    assert "build_absolute_uri" not in source
    assert "get_host" not in source
    # Nothing is read from a query string, on either page.
    assert "request.GET" not in source


# --- Setting the password ----------------------------------------------------------------------


def test_a_token_in_a_url_is_not_accepted_and_not_put_into_the_page(
    client: Client, user: User
) -> None:
    token = _asked(client)
    query = f"?token={token}&password={PASSWORD}&password_again={PASSWORD}"

    response = client.get(f"{CONFIRM}{query}")

    assert response.status_code == 200
    assert token not in response.content.decode()
    assert 'type="hidden" name="token"' not in response.content.decode()
    assert User.objects.get(pk=user.pk).check_password(OLD_PASSWORD) is True
    # Nor does a POST read it from the address.
    posted = client.post(f"{CONFIRM}{query}", {"password": PASSWORD, "password_again": PASSWORD})
    assert posted.status_code == 200
    assert token not in posted.content.decode()
    assert User.objects.get(pk=user.pk).check_password(OLD_PASSWORD) is True
    assert _events() == ["password_reset_requested"]
    # The token was not spent by being ignored.
    assert _set(client, token).status_code == 302


def test_a_reset_goes_to_the_sign_in_page_and_nowhere_a_request_names(
    client: Client, user: User
) -> None:
    token = _asked(client)

    response = client.post(
        f"{CONFIRM}?next=https://evil.test/&redirect=https://evil.test/",
        {
            "token": token,
            "password": PASSWORD,
            "password_again": PASSWORD,
            "next": "https://evil.test/",
            "redirect_to": "//evil.test/",
        },
        HTTP_REFERER="https://evil.test/",
    )

    assert response["Location"] == f"{LOGIN}?reset=1"
    assert _signed_in_as(client) is None


def test_a_reset_creates_no_session_and_signs_nobody_in(client: Client, user: User) -> None:
    token = _asked(client)
    sessions_before = Session.objects.count()

    assert _set(client, token).status_code == 302

    assert Session.objects.count() == sessions_before == 0
    assert "sessionid" not in client.cookies
    assert client.get(WORKSPACE).status_code == 403
    assert "login_success" not in _events()


def test_a_reset_with_a_second_factor_still_asks_for_the_code(client: Client, user: User) -> None:
    enrolled_device(user)
    assert _set(client, _asked(client)).status_code == 302

    response = client.post(LOGIN, {"email": EMAIL, "password": PASSWORD})

    assert response["Location"] == VERIFY
    assert _signed_in_as(client) is None
    assert client.get(WORKSPACE).status_code == 403
    assert client.post(VERIFY, {"code": code_at()})["Location"] == LOGIN
    assert _signed_in_as(client) == str(user.pk)


def test_resetting_while_signed_in_as_somebody_else_changes_only_the_account_of_the_token(
    client: Client, user: User, user_with_roles: UserFactory
) -> None:
    other = user_with_roles(Role.READER)
    signed_in(client, other)
    token = _asked(Client())

    assert _set(client, token).status_code == 302

    assert User.objects.get(pk=user.pk).check_password(PASSWORD) is True
    assert _signed_in_as(client) == str(other.pk)
    assert User.objects.get(pk=other.pk).check_password(PASSWORD) is False
    assert client.get(WORKSPACE).status_code == 200


def test_every_refused_token_gets_the_same_answer(
    client: Client, user: User, clock: Clock, settings: LazySettings
) -> None:
    settings.PASSWORD_RESET_REQUEST_SOURCE_LIMIT = 100
    used = _asked(client)
    _set(Client(), used)
    replaced = _asked(client)
    _asked(client)
    disabled = _account("test.disabled@caipo.test", AccountStatus.ACTIVE)
    of_disabled = _asked(client, disabled.email)
    User.objects.filter(pk=disabled.pk).update(status=AccountStatus.DISABLED)
    lapsing = _account("test.lapsed@caipo.test", AccountStatus.ACTIVE)
    lapsed = _asked(client, lapsing.email)
    PasswordReset.objects.filter(user=lapsing).update(
        created_at=timezone.now() - timedelta(hours=1), expires_at=timezone.now()
    )
    invited = services.create_user(
        actor=approving_administrator(),
        email="test.invited@caipo.test",
        role=Role.READER,
        source="203.0.113.10",
        activation_url=lambda token: f"{ORIGIN}{ACTIVATE}#{token}",
    )
    activation = _token()
    settings.PASSWORD_RESET_THROTTLE_FAILURES = 100

    answers = {
        name: _answer(_set(Client(), token))
        for name, token in {
            "unknown": "A" * 43,
            "malformed": "x",
            "used": used,
            "replaced": replaced,
            "disabled": of_disabled,
            "lapsed": lapsed,
            "activation": activation,
        }.items()
    }

    assert len(set(answers.values())) == 1, {name: answer[0] for name, answer in answers.items()}
    status, location, body = answers["unknown"]
    assert (status, location) == (200, "")
    assert REFUSED in body
    # Nothing that was submitted, and nothing about any account, is in the page.
    for value in ("A" * 43, used, replaced, of_disabled, lapsed, activation, "caipo.test"):
        assert value not in body
    assert 'value="' not in body
    assert body.count('type="password"') == 2
    assert User.objects.get(pk=invited.user.pk).status == AccountStatus.PENDING_VERIFICATION


def test_a_reset_token_does_not_activate_an_account(client: Client, user: User) -> None:
    token = _asked(client)

    response = client.post(
        ACTIVATE, {"token": token, "password": PASSWORD, "password_again": PASSWORD}
    )

    assert response.status_code == 200
    assert REFUSED in response.content.decode()
    assert User.objects.get(pk=user.pk).check_password(OLD_PASSWORD) is True
    assert _set(client, token).status_code == 302


def test_a_refused_token_tells_nothing_about_the_password_sent_with_it(client: Client) -> None:
    weak = _answer(_set(client, "A" * 43, "Tx9!q"))
    strong = _answer(_set(client, "A" * 43, PASSWORD))

    assert weak == strong
    assert "too short" not in weak[2]


def test_two_passwords_that_differ_reset_nothing_and_put_nothing_back(
    client: Client, user: User
) -> None:
    token = _asked(client)

    response = client.post(
        CONFIRM, {"token": token, "password": PASSWORD, "password_again": OTHER_PASSWORD}
    )

    body = response.content.decode()
    assert response.status_code == 200
    assert "not the same" in body
    assert PASSWORD not in body and OTHER_PASSWORD not in body
    # The form did not ask the service, so the page cannot know the token is good.
    assert token not in body
    assert User.objects.get(pk=user.pk).check_password(OLD_PASSWORD) is True
    assert _events() == ["password_reset_requested"]
    assert _set(client, token).status_code == 302


@pytest.mark.parametrize(
    "fields",
    [
        {"token": "", "password": PASSWORD, "password_again": PASSWORD},
        {"token": "TEST-passphrase-typed-in-the-wrong-field" * 4, "password": PASSWORD},
        {"token": "TEST-passphrase-typed-in-the-wrong-field"},
        {},
    ],
    ids=["no-token", "token-too-long", "no-password", "nothing"],
)
def test_an_incomplete_form_resets_nothing_and_puts_nothing_back(
    client: Client, user: User, fields: dict[str, str]
) -> None:
    _asked(client)

    response = client.post(CONFIRM, fields)

    body = response.content.decode()
    assert response.status_code == 200
    assert body.count('role="alert"') == 1
    assert "TEST-passphrase" not in body
    assert 'value="' not in re.sub(r'name="csrfmiddlewaretoken" value="[^"]+"', "", body)
    assert _events() == ["password_reset_requested"]
    assert User.objects.get(pk=user.pk).check_password(OLD_PASSWORD) is True


@pytest.mark.parametrize(
    "password",
    ["Tx9!q", "12345678901234", "qwertyuiop", "test.forgetful"],
    ids=["too-short", "all-digits", "common", "like-the-email"],
)
def test_a_password_that_fails_validation_resets_nothing_and_keeps_the_token(
    client: Client, user: User, password: str
) -> None:
    token = _asked(client)

    response = _set(client, token, password)

    body = response.content.decode()
    assert response.status_code == 200
    assert body.count('role="alert"') >= 1
    assert f'value="{password}"' not in body
    assert User.objects.get(pk=user.pk).check_password(OLD_PASSWORD) is True
    assert PasswordReset.objects.filter(user=user).exists()
    # The token the service found good is kept once, in a hidden field, and
    # nowhere a person looking at the page could read it.
    assert body.count(token) == 1
    (hidden,) = re.findall(r'<input type="hidden" name="token"[^>]*>', body)
    assert f'value="{token}"' in hidden and 'id="id_token"' in hidden
    assert token not in _visible_text(body)
    assert 'type="text"' not in body
    assert "Reset code" not in body
    assert "?" not in re.findall(r'<form[^>]*action="([^"]*)"', body)[0]
    # What the browser sends next is the hidden value in the body of a POST,
    # and a better password completes the reset.
    (kept,) = re.findall(r'name="token" value="([^"]+)"', body)
    assert _set(client, kept).status_code == 302
    assert User.objects.get(pk=user.pk).check_password(PASSWORD) is True


def test_a_kept_token_reaches_no_log_no_event_and_no_header(
    client: Client, user: User, caplog: pytest.LogCaptureFixture
) -> None:
    token = _asked(client)

    with caplog.at_level(logging.DEBUG):
        response = _set(client, token, "Tx9!q")

    assert response.status_code == 200
    assert "no-store" in response["Cache-Control"]
    key = services._key("password_reset", token)
    stored = repr(list(AuthenticationEvent.objects.values()))
    for value in (token, key):
        assert value not in logged(caplog.records)
        assert value not in stored
        assert value not in str(response.headers)
    assert _events() == ["password_reset_requested"]


def test_only_a_token_the_service_found_good_is_kept(client: Client, user: User) -> None:
    _asked(client)

    refused = _set(client, "A" * 43, "Tx9!q").content.decode()
    fresh = client.get(CONFIRM).content.decode()

    # Otherwise the code field is the visible, empty one that the script fills.
    for body in (refused, fresh):
        assert 'type="hidden" name="token"' not in body
        assert '<input type="text" name="token"' in body
        assert 'id="id_token"' in body
        assert "A" * 43 not in body


def test_too_many_refused_tokens_answer_429_whatever_is_sent_next(
    client: Client, user: User, clock: Clock, settings: LazySettings
) -> None:
    settings.PASSWORD_RESET_THROTTLE_FAILURES = 3
    token = _asked(client)
    for _ in range(3):
        assert _set(client, "A" * 43).status_code == 200

    wrong, right = _set(client, "B" * 43), _set(client, token)

    assert _answer(wrong) == _answer(right)
    assert right.status_code == 429
    assert "Too many attempts" in right.content.decode()
    assert token not in right.content.decode()
    assert User.objects.get(pk=user.pk).check_password(OLD_PASSWORD) is True
    assert _events().count("password_reset_failed") == 3
    # Asking is a separate limit, and answers as it always does.
    assert _answer(_ask(client, UNKNOWN))[0] == 200
    # The token was not spent: once the refusals have aged out it still works.
    clock(settings.PASSWORD_RESET_THROTTLE_WINDOW + timedelta(seconds=1))
    assert _set(client, token).status_code == 302


def test_a_forwarded_header_cannot_move_a_submission_to_another_source(
    client: Client, user: User, settings: LazySettings
) -> None:
    settings.PASSWORD_RESET_THROTTLE_FAILURES = 2

    statuses = [
        client.post(
            CONFIRM,
            {"token": "A" * 43, "password": PASSWORD, "password_again": PASSWORD},
            HTTP_X_FORWARDED_FOR=f"198.51.100.{number}",
        ).status_code
        for number in range(4)
    ]

    assert statuses == [200, 200, 429, 429]


def test_a_forwarded_header_cannot_move_a_request_to_another_source(
    client: Client, user: User, settings: LazySettings
) -> None:
    settings.PASSWORD_RESET_REQUEST_SOURCE_LIMIT = 2

    for number in range(4):
        response = client.post(
            REQUEST,
            {"email": f"test.nobody{number}@caipo.test"},
            HTTP_X_FORWARDED_FOR=f"198.51.100.{number}",
        )
        assert response.status_code == 200

    assert _events() == ["password_reset_requested"] * 2
    assert len(set(AuthenticationEvent.objects.values_list("source_key", flat=True))) == 1


# --- What was obtained with the old password ----------------------------------------------------


def test_a_session_established_before_the_reset_is_anonymous_on_its_next_request(
    client: Client, user: User
) -> None:
    assert client.post(LOGIN, {"email": EMAIL, "password": OLD_PASSWORD})["Location"] == LOGIN
    assert client.get(WORKSPACE).status_code == 200
    session_key = client.session.session_key
    elsewhere = Client()

    assert _set(elsewhere, _asked(elsewhere)).status_code == 302

    # The same cookie, the next request: nobody is signed in.
    assert client.cookies["sessionid"].value == session_key
    assert client.get(WORKSPACE).status_code == 403
    page = client.get(LOGIN)
    assert page.context["user"].is_authenticated is False
    assert EMAIL not in page.content.decode()
    assert _signed_in_as(client) is None
    # The browser that reset the password was not signed in by it either.
    assert elsewhere.get(WORKSPACE).status_code == 403


def test_a_session_of_the_browser_that_resets_does_not_survive_either(
    client: Client, user: User
) -> None:
    client.post(LOGIN, {"email": EMAIL, "password": OLD_PASSWORD})
    assert client.get(WORKSPACE).status_code == 200

    assert _set(client, _asked(client)).status_code == 302

    assert client.get(WORKSPACE).status_code == 403
    assert _signed_in_as(client) is None


def test_a_session_verified_with_a_second_factor_does_not_survive_either(
    client: Client, user: User
) -> None:
    enrolled_device(user)
    client.post(LOGIN, {"email": EMAIL, "password": OLD_PASSWORD})
    assert client.post(VERIFY, {"code": code_at()})["Location"] == LOGIN
    assert client.get(WORKSPACE).status_code == 200
    assert client.session.get(sessions.VERIFIED_DEVICE_KEY) is not None

    assert _set(Client(), _asked(Client())).status_code == 302

    assert client.get(WORKSPACE).status_code == 403
    assert _signed_in_as(client) is None
    assert client.session.get(sessions.VERIFIED_DEVICE_KEY) is None


def test_a_sign_in_that_awaits_its_code_cannot_be_completed_after_the_reset(
    client: Client, user: User
) -> None:
    enrolled_device(user)
    assert client.post(LOGIN, {"email": EMAIL, "password": OLD_PASSWORD})["Location"] == VERIFY
    assert MfaChallenge.objects.filter(user=user).exists()

    assert _set(Client(), _asked(Client())).status_code == 302

    response = client.post(VERIFY, {"code": code_at()})
    assert response.status_code == 200
    assert _signed_in_as(client) is None
    assert client.get(WORKSPACE).status_code == 403
    assert not MfaChallenge.objects.exists()
    assert "login_success" not in _events()


# --- What is logged and what a browser is told ----------------------------------------------------


def test_no_token_password_or_address_reaches_the_logs_a_url_or_a_header(
    client: Client, user: User, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        unknown = _ask(client, UNKNOWN)
        asked = _ask(client)
        first = _token()
        refused = _set(client, first[:-1] + "x", OTHER_PASSWORD)
        asked_again = _ask(client)
        second = _token()
        stale = _set(client, first)
        weak = _set(client, second, "Tx9!q")
        reset = _set(client, second)
        used = _set(client, second)

    assert reset.status_code == 302
    written = logged(caplog.records)
    hashes = [services._key("password_reset", token) for token in (first, second)]
    for value in (first, second, *hashes, PASSWORD, OTHER_PASSWORD, "Tx9!q", EMAIL, UNKNOWN):
        assert value not in written, value
    assert CONFIRM + "#" not in written
    responses = (unknown, asked, refused, asked_again, stale, weak, reset, used)
    for response in responses:
        assert first not in str(response.headers)
        assert second not in str(response.headers)
        assert PASSWORD not in str(response.headers) + response.content.decode()
        assert EMAIL not in str(response.headers) + response.content.decode()
        assert first not in response.content.decode()
    # The good token is shown once, to its holder, with the refusal of a weak password.
    for response in responses:
        assert (second in response.content.decode()) is (response is weak)
    stored = repr(list(AuthenticationEvent.objects.values()))
    for value in (first, second, *hashes, PASSWORD, EMAIL, UNKNOWN, ORIGIN, "127.0.0.1"):
        assert value not in stored, value
    for session in Session.objects.all():
        assert first not in repr(session.get_decoded())
        assert second not in repr(session.get_decoded())


def test_events_made_by_the_pages_carry_the_correlation_id_of_their_request(
    client: Client, user: User
) -> None:
    _ask(client, UNKNOWN)
    token = _asked(client)
    _set(client, "A" * 43)
    _set(client, token)

    events = list(AuthenticationEvent.objects.order_by("id"))

    assert [(event.event_type, event.user) for event in events] == [
        ("password_reset_requested", None),
        ("password_reset_requested", user),
        ("password_reset_failed", None),
        ("password_reset_succeeded", user),
    ]
    ids = [event.correlation_id for event in events]
    assert all(len(correlation_id) == 32 for correlation_id in ids)
    assert len(set(ids)) == 4
    assert all(len(event.source_key) == 64 for event in events)
    assert all(event.actor is None for event in events)
