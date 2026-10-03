"""Creating and activating accounts over HTTP (ADR-0015).

An Administrator signed in with a trusted second factor creates an account; its
owner receives a message, opens the link, and chooses a password. Messages go
to the in-memory backend, and the token is read from the message as the person
receiving it would read it.
"""

import logging
import re
from collections.abc import Callable
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

from caipo.accounts import selectors, services
from caipo.accounts.models import (
    AccountActivation,
    AccountEvent,
    AccountStatus,
    RoleEvent,
    User,
)
from caipo.accounts.selectors import Permission, Role
from caipo.accounts.tests.fixtures import (
    Clock,
    UserFactory,
    approving_administrator,
    enrolled_device,
    logged,
)
from caipo.web import accounts, activation, sessions
from caipo.web.access import PUBLIC, declared_access, requires
from caipo.web.tests.helpers import signed_in, verified

pytestmark = [pytest.mark.services, pytest.mark.django_db, pytest.mark.urls(__name__)]

type AccountFactory = Callable[..., User]

# Visibly synthetic fixture values.
EMAIL = "test.invited@caipo.test"
OTHER_EMAIL = "test.other.invited@caipo.test"
PASSWORD = "TEST-passphrase-chosen-by-the-owner"
OTHER_PASSWORD = "TEST-another-passphrase-entirely"
ORIGIN = "http://testserver"

LOGIN = "/login/"
LOGOUT = "/logout/"
ACTIVATE = "/activate/"
ACCOUNTS = "/administration/accounts/"
CREATE = "/administration/accounts/create/"
WORKSPACE = "/workspace/"
REVIEW = "/review/"
ADMINISTRATION = "/administration/"
OVERVIEW = "/account/second-factor/"

REFUSED = "That code was not accepted."


@requires(Permission.WORKSPACE_READ)
def workspace_view(request: HttpRequest) -> HttpResponse:
    return HttpResponse("TEST workspace")


@requires(Permission.RESEARCH_REVIEW)
def review_view(request: HttpRequest) -> HttpResponse:
    return HttpResponse("TEST review")


@requires(Permission.ROLES_MANAGE)
def administration_view(request: HttpRequest) -> HttpResponse:
    return HttpResponse("TEST administration")


# The real routes, plus one view for each kind of permission.
urlpatterns = [
    path("", include("caipo.web.urls")),
    path("workspace/", workspace_view),
    path("review/", review_view),
    path("administration/", administration_view),
]


def _send_url(user: User | int) -> str:
    return f"{ACCOUNTS}{user if isinstance(user, int) else user.pk}/send-verification/"


@pytest.fixture
def administrator(user_with_roles: UserFactory) -> Client:
    """Return a client signed in as an Administrator with a trusted second factor."""
    return verified(Client(), user_with_roles(Role.ADMINISTRATOR))


def _events() -> list[str]:
    return list(AccountEvent.objects.order_by("id").values_list("event_type", flat=True))


def _link(index: int = -1) -> str:
    """Read the link off a verification message, by default the last one sent."""
    (link,) = re.findall(r"https?://\S+", str(django_mail.outbox[index].body))
    return str(link)


def _token(index: int = -1) -> str:
    return _link(index).split("#", 1)[1]


def _create(administrator: Client, email: str = EMAIL, role: str = "reader", **extra: str) -> Any:
    return administrator.post(CREATE, {"email": email, "role": role, **extra})


def _invited(administrator: Client, email: str = EMAIL, role: str = "reader") -> tuple[User, str]:
    assert _create(administrator, email, role).status_code == 302
    return User.objects.get(email=email), _token()


def _activate(client: Client, token: str, password: str = PASSWORD, **extra: str) -> Any:
    return client.post(
        ACTIVATE, {"token": token, "password": password, "password_again": password, **extra}
    )


def _signed_in_as(client: Client) -> str | None:
    user_id: str | None = client.session.get("_auth_user_id")
    return user_id


# --- From creation to a signed-in account -------------------------------------------------


def test_an_account_from_creation_to_its_first_sign_in(
    administrator: Client, client: Client
) -> None:
    # 1. The Administrator creates the account. No password is involved.
    response = _create(administrator)
    assert response["Location"] == f"{ACCOUNTS}?created=1"
    user = User.objects.get(email=EMAIL)
    assert user.status == AccountStatus.PENDING_VERIFICATION
    assert "was created" in administrator.get(response["Location"]).content.decode()

    # 2. Its owner cannot sign in yet, with any password.
    assert client.post(LOGIN, {"email": EMAIL, "password": PASSWORD}).status_code == 200
    assert _signed_in_as(client) is None

    # 3. The link in the message opens the activation page. Opening it sends
    #    no token: the token is after the "#".
    link = _link()
    assert link.startswith(f"{ORIGIN}{ACTIVATE}#")
    page = client.get(ACTIVATE)
    assert page.status_code == 200
    assert _token() not in page.content.decode()

    # 4. The owner chooses a password, and is sent to sign in. Nobody is signed in.
    activated = _activate(client, _token())
    assert activated["Location"] == f"{LOGIN}?activated=1"
    assert _signed_in_as(client) is None
    assert "Your account is active" in client.get(activated["Location"]).content.decode()
    assert User.objects.get(email=EMAIL).status == AccountStatus.ACTIVE

    # 5. The password chosen signs in, with what the role gives.
    assert client.post(LOGIN, {"email": EMAIL, "password": PASSWORD})["Location"] == LOGIN
    assert _signed_in_as(client) == str(user.pk)
    assert client.get(WORKSPACE).status_code == 200
    assert client.get(ADMINISTRATION).status_code == 403
    assert client.get(ACCOUNTS).status_code == 403
    assert _events() == ["account_created", "verification_sent", "verification_succeeded"]


@pytest.mark.parametrize(
    ("role", "page"), [("reviewer", REVIEW), ("administrator", ADMINISTRATION)]
)
def test_a_privileged_account_created_this_way_still_needs_its_second_factor(
    administrator: Client, client: Client, role: str, page: str
) -> None:
    _, token = _invited(administrator, role=role)
    _activate(client, token)
    client.post(LOGIN, {"email": EMAIL, "password": PASSWORD})

    # Signed in on the password it chose: its own second factor and nothing else.
    assert client.get(page).status_code == 403
    assert client.get(ACCOUNTS).status_code == 403
    assert _create(client, OTHER_EMAIL, "administrator").status_code == 403
    assert client.get(OVERVIEW).status_code == 200
    # And asking for that second factor makes a request an Administrator must approve.
    asked = client.post("/account/second-factor/enrol/", {"password": PASSWORD})
    assert "must be approved by an Administrator" in asked.content.decode()
    assert client.get(page).status_code == 403
    assert not User.objects.filter(email=OTHER_EMAIL).exists()


# --- Who reaches the Administrator's pages ---------------------------------------------------


def _visitor(kind: str, user_with_roles: UserFactory) -> Client:
    client = Client()
    if kind == "anonymous":
        return client
    if kind == "administrator-on-a-password":
        user = user_with_roles(Role.ADMINISTRATOR)
        enrolled_device(user)
        return signed_in(client, user)
    if kind == "administrator-with-an-unapproved-device":
        user = user_with_roles(Role.ADMINISTRATOR)
        device = enrolled_device(user, trusted=False)
        signed_in(client, user)
        session = client.session
        session[sessions.VERIFIED_DEVICE_KEY] = device.pk
        session.save()
        return client
    if kind == "administrator-not-enrolled":
        return signed_in(client, user_with_roles(Role.ADMINISTRATOR))
    role = {"reviewer": Role.REVIEWER, "researcher": Role.RESEARCHER, "reader": Role.READER}[kind]
    return verified(client, user_with_roles(role))


VISITORS = [
    "anonymous",
    "administrator-on-a-password",
    "administrator-with-an-unapproved-device",
    "administrator-not-enrolled",
    "reviewer",
    "researcher",
    "reader",
]


@pytest.mark.parametrize("kind", VISITORS)
def test_only_a_verified_administrator_reaches_the_account_pages(
    administrator: Client, user_with_roles: UserFactory, kind: str
) -> None:
    pending, _ = _invited(administrator, OTHER_EMAIL)
    visitor = _visitor(kind, user_with_roles)
    users, sent, events = User.objects.count(), len(django_mail.outbox), _events()

    listing = visitor.get(ACCOUNTS)
    creation = _create(visitor)
    resend = visitor.post(_send_url(pending))

    assert (listing.status_code, creation.status_code, resend.status_code) == (403, 403, 403)
    assert OTHER_EMAIL not in listing.content.decode()
    assert User.objects.count() == users
    assert not User.objects.filter(email=EMAIL).exists()
    assert len(django_mail.outbox) == sent
    assert _events() == events


def test_the_account_pages_declare_the_permission_to_create_accounts() -> None:
    """The HTTP boundary names the same permission the services require."""
    for view in (accounts.overview, accounts.create, accounts.send_verification):
        assert declared_access(view) == Permission.ACCOUNTS_CREATE
    assert declared_access(activation.activate) == PUBLIC


def test_a_role_or_a_second_factor_named_by_the_browser_creates_nothing(
    user_with_roles: UserFactory,
) -> None:
    reader = verified(Client(), user_with_roles(Role.READER))
    claims = {"actor_role": "administrator", "mfa_verified": "true", "is_administrator": "1"}

    responses = [
        _create(reader, **claims),
        reader.post(
            f"{CREATE}?role=administrator&mfa_verified=true", {"email": EMAIL, "role": "reader"}
        ),
        reader.post(
            CREATE,
            {"email": EMAIL, "role": "reader"},
            HTTP_X_ROLE="administrator",
            HTTP_X_MFA_VERIFIED="true",
            HTTP_X_FORWARDED_USER="administrator",
        ),
    ]
    reader.cookies["role"] = "administrator"
    reader.cookies["mfa_verified"] = "true"
    responses.append(_create(reader))

    assert [response.status_code for response in responses] == [403] * 4
    assert not User.objects.filter(email=EMAIL).exists()
    assert django_mail.outbox == []


def test_the_sign_in_page_links_to_the_accounts_only_for_a_verified_administrator(
    administrator: Client, user_with_roles: UserFactory
) -> None:
    assert ACCOUNTS in administrator.get(LOGIN).content.decode()

    for kind in VISITORS:
        assert ACCOUNTS not in _visitor(kind, user_with_roles).get(LOGIN).content.decode(), kind


# --- How an account is created ---------------------------------------------------------------


@pytest.mark.parametrize("url", [CREATE, f"{ACCOUNTS}1/send-verification/"])
@pytest.mark.parametrize("method", ["get", "head", "put", "patch", "delete"])
def test_changes_are_made_by_post_only(administrator: Client, url: str, method: str) -> None:
    response = getattr(administrator, method)(f"{url}?email={EMAIL}&role=reader")

    assert response.status_code == 405
    assert not User.objects.filter(email=EMAIL).exists()
    assert django_mail.outbox == []


def test_the_page_itself_is_fetched_by_get_only(administrator: Client) -> None:
    assert administrator.post(ACCOUNTS, {"email": EMAIL, "role": "reader"}).status_code == 405
    assert not User.objects.filter(email=EMAIL).exists()


def test_a_change_without_a_csrf_token_is_refused(user_with_roles: UserFactory) -> None:
    administrator = verified(Client(enforce_csrf_checks=True), user_with_roles(Role.ADMINISTRATOR))

    assert _create(administrator).status_code == 403
    assert not User.objects.filter(email=EMAIL).exists()

    administrator.get(ACCOUNTS)
    token = administrator.cookies["csrftoken"].value
    assert _create(administrator, csrfmiddlewaretoken=token).status_code == 302
    pending = User.objects.get(email=EMAIL)
    assert administrator.post(_send_url(pending)).status_code == 403
    assert len(django_mail.outbox) == 1
    assert administrator.post(_send_url(pending), {"csrfmiddlewaretoken": token}).status_code == 302
    assert len(django_mail.outbox) == 2


@pytest.mark.parametrize(
    "role",
    ["", "superuser", "ADMINISTRATOR", "Administrator", "staff", "reader,administrator", "owner"],
)
def test_a_role_outside_the_four_roles_creates_nothing(administrator: Client, role: str) -> None:
    response = _create(administrator, role=role)

    assert response.status_code == 400
    assert not User.objects.filter(email=EMAIL).exists()
    assert django_mail.outbox == []
    assert _events() == []


def test_a_form_with_several_roles_or_other_fields_gives_exactly_what_was_chosen(
    administrator: Client,
) -> None:
    """What a manipulated form can add is ignored: one role, awaiting verification, no password."""
    response = administrator.post(
        CREATE,
        {
            "email": EMAIL,
            # Django reads the last of several values.
            "role": ["administrator", "reader"],
            "roles": "administrator",
            "status": "active",
            "is_active": "true",
            "activated_at": "2026-01-01T00:00:00Z",
            "email_verified_at": "2026-01-01T00:00:00Z",
            "password": PASSWORD,
            "is_staff": "true",
            "is_superuser": "true",
            "actor": "1",
        },
    )

    assert response.status_code == 302
    user = User.objects.get(email=EMAIL)
    assert selectors.roles_of(user) == {Role.READER}
    assert RoleEvent.objects.filter(user=user).count() == 1
    assert user.status == AccountStatus.PENDING_VERIFICATION
    assert (user.activated_at, user.email_verified_at) == (None, None)
    assert user.check_password(PASSWORD) is False
    assert not hasattr(user, "is_staff") and not hasattr(user, "is_superuser")


def test_the_grant_names_the_administrator_of_the_session_and_nothing_from_the_form(
    user_with_roles: UserFactory,
) -> None:
    acting = user_with_roles(Role.ADMINISTRATOR)
    other = user_with_roles(Role.ADMINISTRATOR)
    client = verified(Client(), acting)

    _create(client, actor=str(other.pk), user=str(other.pk))

    user = User.objects.get(email=EMAIL)
    assert RoleEvent.objects.get(user=user).actor == acting
    assert {event.actor for event in AccountEvent.objects.all()} == {acting}


def test_the_form_asks_for_no_password_and_offers_exactly_the_four_roles(
    administrator: Client,
) -> None:
    body = administrator.get(ACCOUNTS).content.decode()

    assert 'type="password"' not in body
    assert re.findall(r'<option value="([^"]*)"', body) == [
        "reader",
        "researcher",
        "reviewer",
        "administrator",
    ]
    assert "no-store" in administrator.get(ACCOUNTS)["Cache-Control"]


@pytest.mark.parametrize("email", ["", "not-an-email", "test@"])
def test_an_invalid_email_address_creates_nothing(administrator: Client, email: str) -> None:
    response = _create(administrator, email=email)

    assert response.status_code == 400
    assert User.objects.filter(status=AccountStatus.PENDING_VERIFICATION).count() == 0
    assert django_mail.outbox == []


def test_an_email_address_that_has_an_account_creates_nothing(administrator: Client) -> None:
    _invited(administrator)

    response = _create(administrator, EMAIL.upper(), "administrator")

    assert response.status_code == 400
    assert "already exists" in response.content.decode()
    assert selectors.roles_of(User.objects.get(email=EMAIL)) == {Role.READER}
    assert len(django_mail.outbox) == 1


def test_a_message_that_cannot_be_sent_is_reported_and_can_be_sent_again(
    administrator: Client, client: Client, settings: LazySettings
) -> None:
    settings.EMAIL_BACKEND = "caipo.core.mail.RefusingEmailBackend"

    response = _create(administrator)

    assert response.status_code == 502
    assert "could not be sent" in response.content.decode()
    pending = User.objects.get(email=EMAIL)
    assert EMAIL in response.content.decode()
    assert "no message that still works is outstanding" not in response.content.decode()

    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    again = administrator.post(_send_url(pending))
    assert again["Location"] == f"{ACCOUNTS}?sent=1"
    assert _activate(client, _token()).status_code == 302


# --- Sending the message again ------------------------------------------------------------------


def test_sending_again_replaces_the_link(administrator: Client, client: Client) -> None:
    pending, first = _invited(administrator)

    response = administrator.post(_send_url(pending))

    assert response["Location"] == f"{ACCOUNTS}?sent=1"
    second = _token()
    assert second != first
    assert REFUSED in _activate(client, first).content.decode()
    assert _activate(client, second).status_code == 302


def test_the_list_shows_who_awaits_verification_and_never_a_link(
    administrator: Client, client: Client
) -> None:
    _, token = _invited(administrator)
    _, other_token = _invited(administrator, OTHER_EMAIL)
    _activate(client, other_token)

    body = administrator.get(ACCOUNTS).content.decode()

    assert EMAIL in body
    assert OTHER_EMAIL not in body
    assert token not in body
    assert "#" + token not in body
    assert AccountActivation.objects.get().token_key not in body


@pytest.mark.parametrize("state", ["active", "disabled", "unknown"])
def test_a_message_is_sent_again_only_to_an_account_that_awaits_verification(
    administrator: Client, client: Client, state: str
) -> None:
    user, token = _invited(administrator)
    _activate(client, token)
    if state == "disabled":
        services.disable_user(actor=approving_administrator(), user=user)
    sent = len(django_mail.outbox)

    response = administrator.post(_send_url(user if state != "unknown" else 2**31))

    assert response.status_code == 409
    assert len(django_mail.outbox) == sent
    assert not AccountActivation.objects.exists()


# --- The public address in the link --------------------------------------------------------------


def test_the_link_uses_the_configured_address_and_nothing_from_the_request(
    administrator: Client, settings: LazySettings
) -> None:
    settings.PUBLIC_BASE_URL = "https://caipo.example.test"
    settings.ALLOWED_HOSTS = ["testserver", "evil.test"]

    response = administrator.post(
        f"{CREATE}?next=https://evil.test&origin=https://evil.test",
        {
            "email": EMAIL,
            "role": "reader",
            "origin": "https://evil.test",
            "public_url": "https://evil.test",
            "activation_url": "https://evil.test/activate/",
            "next": "https://evil.test",
        },
        HTTP_HOST="evil.test",
        HTTP_X_FORWARDED_HOST="evil.test",
        HTTP_X_FORWARDED_PROTO="http",
        HTTP_ORIGIN="https://evil.test",
        HTTP_REFERER="https://evil.test/",
        HTTP_FORWARDED="host=evil.test;proto=http",
    )

    assert response.status_code == 302
    assert response["Location"] == f"{ACCOUNTS}?created=1"
    link = _link()
    assert link == f"https://caipo.example.test{ACTIVATE}#{_token()}"
    assert "evil.test" not in str(django_mail.outbox[0].body)
    assert "evil.test" not in str(django_mail.outbox[0].message())


def test_a_host_that_is_not_allowed_is_refused_before_anything_is_created(
    administrator: Client,
) -> None:
    response = administrator.post(CREATE, {"email": EMAIL, "role": "reader"}, HTTP_HOST="evil.test")

    assert response.status_code == 400
    assert not User.objects.filter(email=EMAIL).exists()
    assert django_mail.outbox == []


def test_the_link_is_built_from_the_setting_alone() -> None:
    assert activation.activation_url("TEST-token") == f"{ORIGIN}{ACTIVATE}#TEST-token"
    source = Path(activation.__file__).read_text()
    assert "build_absolute_uri" not in source
    assert "get_host" not in source
    assert "build_absolute_uri" not in Path(accounts.__file__).read_text()


# --- The activation page ------------------------------------------------------------------------


def test_the_page_is_public_shows_a_form_and_loads_the_script_that_reads_the_link(
    client: Client,
) -> None:
    response = client.get(ACTIVATE)

    body = response.content.decode()
    assert response.status_code == 200
    assert "no-store" in response["Cache-Control"]
    assert 'id="id_token"' in body
    assert body.count('type="password"') == 2
    assert 'src="/static/web/activate.js"' in body
    # No inline script: only the one static file.
    assert body.count("<script") == 1


def test_the_script_moves_the_code_out_of_the_address_and_sends_it_nowhere() -> None:
    found = finders.find("web/activate.js")
    assert found is not None
    script = Path(str(found)).read_text()

    assert "window.location.hash" in script
    assert "replaceState" in script
    for sender in ("fetch", "XMLHttpRequest", "sendBeacon", "http", "cookie", "localStorage"):
        assert sender not in script


@pytest.mark.parametrize("method", ["head", "put", "patch", "delete"])
def test_the_page_accepts_get_and_post_only(
    administrator: Client, client: Client, method: str
) -> None:
    user, token = _invited(administrator)

    response = getattr(client, method)(f"{ACTIVATE}?token={token}&password={PASSWORD}")

    assert response.status_code == 405
    assert User.objects.get(pk=user.pk).status == AccountStatus.PENDING_VERIFICATION


def test_a_token_in_a_url_is_not_accepted_and_not_put_into_the_page(
    administrator: Client, client: Client
) -> None:
    user, token = _invited(administrator)
    query = f"?token={token}&password={PASSWORD}&password_again={PASSWORD}"

    response = client.get(f"{ACTIVATE}{query}")

    assert response.status_code == 200
    assert token not in response.content.decode()
    stored = User.objects.get(pk=user.pk)
    assert stored.status == AccountStatus.PENDING_VERIFICATION
    assert stored.check_password(PASSWORD) is False
    assert _events() == ["account_created", "verification_sent"]
    # Nor does a POST read it from the address.
    posted = client.post(f"{ACTIVATE}{query}", {"password": PASSWORD, "password_again": PASSWORD})
    assert posted.status_code == 200
    assert User.objects.get(pk=user.pk).status == AccountStatus.PENDING_VERIFICATION


def test_activation_without_a_csrf_token_is_refused(administrator: Client) -> None:
    user, token = _invited(administrator)
    client = Client(enforce_csrf_checks=True)

    assert _activate(client, token).status_code == 403
    assert User.objects.get(pk=user.pk).status == AccountStatus.PENDING_VERIFICATION

    client.get(ACTIVATE)
    csrf = client.cookies["csrftoken"].value
    assert _activate(client, token, csrfmiddlewaretoken=csrf).status_code == 302


def test_activation_goes_to_the_sign_in_page_and_nowhere_a_request_names(
    administrator: Client, client: Client
) -> None:
    _, token = _invited(administrator)

    response = client.post(
        f"{ACTIVATE}?next=https://evil.test/&redirect=https://evil.test/",
        {
            "token": token,
            "password": PASSWORD,
            "password_again": PASSWORD,
            "next": "https://evil.test/",
            "redirect_to": "//evil.test/",
        },
        HTTP_REFERER="https://evil.test/",
    )

    assert response["Location"] == f"{LOGIN}?activated=1"
    assert _signed_in_as(client) is None


def test_activating_while_signed_in_as_somebody_else_changes_only_the_new_account(
    administrator: Client, client: Client, user_with_roles: UserFactory
) -> None:
    other = user_with_roles(Role.READER)
    signed_in(client, other)
    user, token = _invited(administrator)

    assert _activate(client, token).status_code == 302

    assert User.objects.get(pk=user.pk).status == AccountStatus.ACTIVE
    assert _signed_in_as(client) == str(other.pk)
    assert User.objects.get(pk=other.pk).check_password(PASSWORD) is False


def _answer(response: Any) -> tuple[int, str]:
    """Return what tells responses apart: the status and the page, without its CSRF token."""
    body = re.sub(r'name="csrfmiddlewaretoken" value="[^"]+"', "", response.content.decode())
    return response.status_code, body


def test_every_refused_token_gets_the_same_answer(
    administrator: Client, clock: Clock, settings: LazySettings
) -> None:
    _, used = _invited(administrator, "test.used@caipo.test")
    _activate(Client(), used)
    disabled, of_disabled = _invited(administrator, "test.disabled@caipo.test")
    services.disable_user(actor=approving_administrator(), user=disabled)
    replaced_user, replaced = _invited(administrator, "test.replaced@caipo.test")
    administrator.post(_send_url(replaced_user))
    _, lapsed = _invited(administrator, "test.lapsed@caipo.test")
    clock(settings.ACCOUNT_ACTIVATION_LIFETIME)

    answers = {
        name: _answer(_activate(Client(), token))
        for name, token in {
            "unknown": "A" * 43,
            "malformed": "x",
            "used": used,
            "disabled": of_disabled,
            "replaced": replaced,
            "lapsed": lapsed,
        }.items()
    }

    assert len(set(answers.values())) == 1, {name: status for name, (status, _) in answers.items()}
    status, body = answers["unknown"]
    assert status == 200
    assert REFUSED in body
    # Nothing that was submitted, and nothing about any account, is in the page.
    for value in ("A" * 43, used, of_disabled, replaced, lapsed, "caipo.test", "disabled"):
        assert value not in body
    assert 'type="password"' in body


def test_a_refused_token_tells_nothing_about_the_password_sent_with_it(client: Client) -> None:
    weak = _answer(_activate(client, "A" * 43, "Tx9!q"))
    strong = _answer(_activate(client, "A" * 43, PASSWORD))

    assert weak == strong
    assert "too short" not in weak[1]


def test_two_passwords_that_differ_activate_nothing(administrator: Client, client: Client) -> None:
    user, token = _invited(administrator)

    response = client.post(
        ACTIVATE, {"token": token, "password": PASSWORD, "password_again": OTHER_PASSWORD}
    )

    body = response.content.decode()
    assert response.status_code == 200
    assert "not the same" in body
    assert PASSWORD not in body and OTHER_PASSWORD not in body
    stored = User.objects.get(pk=user.pk)
    assert stored.status == AccountStatus.PENDING_VERIFICATION
    assert stored.check_password(PASSWORD) is False
    assert _events() == ["account_created", "verification_sent"]


@pytest.mark.parametrize(
    "password",
    ["Tx9!q", "12345678901234", "qwertyuiop", "test.invited"],
    ids=["too-short", "all-digits", "common", "like-the-email"],
)
def test_a_password_that_fails_validation_activates_nothing_and_keeps_the_token(
    administrator: Client, client: Client, password: str
) -> None:
    user, token = _invited(administrator)

    response = _activate(client, token, password)

    body = response.content.decode()
    assert response.status_code == 200
    assert body.count('role="alert"') >= 1
    assert f'value="{password}"' not in body
    assert User.objects.get(pk=user.pk).status == AccountStatus.PENDING_VERIFICATION
    # The holder of the token keeps it in the form, and a better password completes it.
    assert f'value="{token}"' in body
    assert _activate(client, token).status_code == 302


def test_too_many_refused_attempts_answer_429_whatever_is_sent_next(
    administrator: Client, client: Client, settings: LazySettings
) -> None:
    settings.ACCOUNT_ACTIVATION_THROTTLE_FAILURES = 3
    user, token = _invited(administrator)
    for _ in range(3):
        assert _activate(client, "A" * 43).status_code == 200

    wrong, right = _activate(client, "B" * 43), _activate(client, token)

    assert _answer(wrong) == _answer(right)
    assert right.status_code == 429
    assert token not in right.content.decode()
    assert User.objects.get(pk=user.pk).status == AccountStatus.PENDING_VERIFICATION
    assert _events().count("verification_failed") == 3


def test_a_forwarded_header_cannot_move_an_attempt_to_another_source(
    administrator: Client, client: Client, settings: LazySettings
) -> None:
    settings.ACCOUNT_ACTIVATION_THROTTLE_FAILURES = 2
    _invited(administrator)

    statuses = [
        client.post(
            ACTIVATE,
            {"token": "A" * 43, "password": PASSWORD, "password_again": PASSWORD},
            HTTP_X_FORWARDED_FOR=f"198.51.100.{number}",
        ).status_code
        for number in range(4)
    ]

    assert statuses == [200, 200, 429, 429]


# --- Status takes effect at once ------------------------------------------------------------------


def test_disabling_ends_the_sessions_of_the_account_on_their_next_request(
    administrator: Client, client: Client
) -> None:
    user, token = _invited(administrator)
    _activate(client, token)
    client.post(LOGIN, {"email": EMAIL, "password": PASSWORD})
    assert client.get(WORKSPACE).status_code == 200

    services.disable_user(actor=approving_administrator(), user=user)

    assert client.get(WORKSPACE).status_code == 403
    assert client.post(LOGIN, {"email": EMAIL, "password": PASSWORD}).status_code == 200
    assert client.get(WORKSPACE).status_code == 403

    services.enable_user(actor=approving_administrator(), user=user)

    assert client.post(LOGIN, {"email": EMAIL, "password": PASSWORD})["Location"] == LOGIN
    assert client.get(WORKSPACE).status_code == 200


def test_a_sign_in_page_answers_alike_for_accounts_that_cannot_be_signed_in_to(
    administrator: Client,
) -> None:
    _invited(administrator)
    disabled, token = _invited(administrator, OTHER_EMAIL)
    _activate(Client(), token)
    services.disable_user(actor=approving_administrator(), user=disabled)

    answers = set()
    for email in (EMAIL, OTHER_EMAIL, "test.nobody@caipo.test"):
        status, body = _answer(Client().post(LOGIN, {"email": email, "password": PASSWORD}))
        # The form shows the address back to whoever typed it.
        answers.add((status, body.replace(email, "ADDRESS")))

    assert len(answers) == 1


# --- What is logged and what a browser is told ----------------------------------------------------


def test_no_token_password_or_address_reaches_the_logs_a_url_or_a_header(
    administrator: Client, client: Client, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        created = _create(administrator)
        pending = User.objects.get(email=EMAIL)
        first = _token()
        refused = _activate(client, first[:-1] + "x", OTHER_PASSWORD)
        resent = administrator.post(_send_url(pending))
        second = _token()
        weak = _activate(client, second, "Tx9!q")
        activated = _activate(client, second)
        listing = administrator.get(ACCOUNTS)

    assert activated.status_code == 302
    written = logged(caplog.records)
    for value in (first, second, PASSWORD, OTHER_PASSWORD, "Tx9!q", EMAIL, ORIGIN):
        assert value not in written, value
    for response in (created, refused, resent, weak, activated, listing):
        assert first not in str(response.headers)
        assert second not in str(response.headers)
        assert PASSWORD not in str(response.headers) + response.content.decode()
    for response in (created, refused, resent, activated, listing):
        assert first not in response.content.decode()
        assert second not in response.content.decode()
    # Neither the session of the person activating nor any other holds the token.
    for session in Session.objects.all():
        assert second not in repr(session.get_decoded())


def test_events_made_by_the_pages_carry_the_correlation_id_of_their_request(
    administrator: Client, client: Client
) -> None:
    _, token = _invited(administrator)
    _activate(client, "A" * 43)
    _activate(client, token)

    events = list(AccountEvent.objects.order_by("id"))

    assert [event.event_type for event in events] == [
        "account_created",
        "verification_sent",
        "verification_failed",
        "verification_succeeded",
    ]
    ids = [event.correlation_id for event in events]
    assert all(len(correlation_id) == 32 for correlation_id in ids)
    # One request created and sent; each activation attempt was its own request.
    assert ids[0] == ids[1]
    assert len({ids[1], ids[2], ids[3]}) == 3
    assert all(len(event.source_key) == 64 for event in events)
