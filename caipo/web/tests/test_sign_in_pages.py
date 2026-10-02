"""The sign-in and sign-out pages, exercised over HTTP."""

import logging
import re
from typing import Any

import pytest
from django.conf import LazySettings
from django.contrib.sessions.models import Session
from django.http import HttpRequest, HttpResponse
from django.test import Client
from django.urls import include, path

from caipo.accounts import selectors
from caipo.accounts.models import AuthenticationEvent, RoleEvent, User
from caipo.accounts.selectors import Permission, Role
from caipo.accounts.tests.fixtures import UserFactory
from caipo.web.access import requires

pytestmark = [pytest.mark.services, pytest.mark.django_db]

# Visibly synthetic fixture values.
EMAIL = "test.reader@caipo.test"
PASSWORD = "TEST-passphrase-for-fixtures-only"
WRONG = "TEST-wrong-passphrase"
UNKNOWN = "test.nobody@caipo.test"

LOGIN = "/login/"
LOGOUT = "/logout/"
REFUSED = "The email address or password is not correct."
THROTTLED = "Too many sign-in attempts."


@requires(Permission.WORKSPACE_READ)
def workspace_view(request: HttpRequest) -> HttpResponse:
    return HttpResponse("TEST workspace")


# The real routes, plus one view that needs a permission.
urlpatterns = [
    path("", include("caipo.web.urls")),
    path("workspace/", workspace_view),
]


@pytest.fixture
def user() -> User:
    return User.objects.create_user(EMAIL, PASSWORD)


def _sign_in(client: Client, email: str = EMAIL, password: str = PASSWORD, **extra: str) -> Any:
    return client.post(LOGIN, {"email": email, "password": password, **extra})


def _signed_in_as(client: Client) -> str | None:
    user_id: str | None = client.session.get("_auth_user_id")
    return user_id


def _events() -> list[tuple[str, int | None]]:
    return list(AuthenticationEvent.objects.order_by("id").values_list("event_type", "user_id"))


def _without_what_varies(response: Any) -> str:
    """Return the page with the per-request token and the echoed email address removed."""
    body = response.content.decode()
    body = re.sub(r'name="csrfmiddlewaretoken" value="[^"]+"', "", body)
    return re.sub(r'(<input type="email"[^>]*?) value="[^"]*"', r"\1", body)


# --- The page -------------------------------------------------------------------


def test_an_anonymous_visitor_gets_the_sign_in_page(client: Client) -> None:
    response = client.get(LOGIN)
    body = response.content.decode()

    assert response.status_code == 200
    assert 'name="email"' in body
    assert 'type="password"' in body
    assert 'name="csrfmiddlewaretoken"' in body
    assert 'method="post"' in body
    assert "no-store" in response["Cache-Control"]
    assert _events() == []


def test_the_page_is_not_cached_and_cannot_be_framed(client: Client) -> None:
    response = client.get(LOGIN)

    assert "no-store" in response["Cache-Control"]
    assert response["X-Frame-Options"] == "DENY"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Referrer-Policy"] == "same-origin"


# --- Signing in -----------------------------------------------------------------


def test_valid_credentials_sign_in_and_redirect(client: Client, user: User) -> None:
    response = _sign_in(client)

    assert response.status_code == 302
    assert response["Location"] == LOGIN
    assert _signed_in_as(client) == str(user.pk)
    assert _events() == [("login_success", user.pk)]
    assert User.objects.get(pk=user.pk).last_login is not None


def test_after_signing_in_the_page_says_who_is_signed_in(client: Client, user: User) -> None:
    _sign_in(client)

    body = client.get(LOGIN).content.decode()

    assert EMAIL in body
    assert f'action="{LOGOUT}"' in body
    assert 'type="password"' not in body


def test_the_email_never_appears_in_a_url(client: Client, user: User) -> None:
    response = _sign_in(client)

    assert EMAIL not in response["Location"]
    assert "@" not in response["Location"]


@pytest.mark.parametrize(
    ("email", "password"),
    [(EMAIL, WRONG), (UNKNOWN, PASSWORD), ("test.inactive@caipo.test", PASSWORD)],
    ids=["wrong-password", "unknown-email", "inactive-account"],
)
def test_bad_credentials_are_refused(client: Client, user: User, email: str, password: str) -> None:
    User.objects.create_user("test.inactive@caipo.test", PASSWORD)
    User.objects.filter(email="test.inactive@caipo.test").update(is_active=False)

    response = _sign_in(client, email, password)

    assert response.status_code == 200
    assert REFUSED in response.content.decode()
    assert _signed_in_as(client) is None
    assert [event_type for event_type, _ in _events()] == ["login_failure"]


def test_every_refusal_is_the_same_response(client: Client, user: User) -> None:
    User.objects.create_user("test.inactive@caipo.test", PASSWORD)
    User.objects.filter(email="test.inactive@caipo.test").update(is_active=False)

    responses = [
        _sign_in(Client(), EMAIL, WRONG),
        _sign_in(Client(), UNKNOWN, PASSWORD),
        _sign_in(Client(), UNKNOWN, WRONG),
        _sign_in(Client(), "test.inactive@caipo.test", PASSWORD),
    ]

    assert {response.status_code for response in responses} == {200}
    assert len({_without_what_varies(response) for response in responses}) == 1
    assert len({tuple(sorted(response.headers)) for response in responses}) == 1
    assert all(not response.cookies.get("sessionid") for response in responses)


def test_the_password_is_never_sent_back(client: Client, user: User) -> None:
    response = _sign_in(client, EMAIL, WRONG)

    assert WRONG not in response.content.decode()
    assert 'type="password"' in response.content.decode()


def test_missing_fields_are_reported_without_an_attempt_being_made(client: Client) -> None:
    response = client.post(LOGIN, {"email": "", "password": ""})

    assert response.status_code == 200
    assert "This field is required." in response.content.decode()
    assert _events() == []


def test_an_overlong_password_is_refused_before_it_is_hashed(client: Client, user: User) -> None:
    response = _sign_in(client, EMAIL, "x" * 5000)

    assert response.status_code == 200
    assert _signed_in_as(client) is None
    assert _events() == []


# --- The session ----------------------------------------------------------------


def test_signing_in_replaces_the_session_key(client: Client, user: User) -> None:
    # A session that existed before signing in, as an attacker would plant.
    session = client.session
    session["planted"] = "TEST value"
    session.save()
    before = session.session_key
    assert before

    _sign_in(client)

    after = client.session.session_key
    assert after != before
    assert not Session.objects.filter(session_key=before).exists()
    assert _signed_in_as(client) == str(user.pk)


def test_a_refused_attempt_does_not_create_a_session(client: Client, user: User) -> None:
    _sign_in(client, EMAIL, WRONG)

    assert Session.objects.count() == 0


def test_the_session_cookie_is_secure_http_only_and_ends_with_the_browser(
    client: Client, user: User
) -> None:
    cookie = _sign_in(client).cookies["sessionid"]

    assert cookie["secure"] is True
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Lax"
    assert cookie["path"] == "/"
    assert cookie["domain"] == ""
    # No lifetime in the cookie: the browser drops it when it closes.
    assert cookie["max-age"] == ""
    assert cookie["expires"] == ""


def test_the_session_expires_on_the_server_after_the_configured_time(
    client: Client, user: User, settings: LazySettings
) -> None:
    _sign_in(client)

    assert settings.SESSION_COOKIE_AGE == 12 * 60 * 60
    assert client.session.get_expiry_age() == pytest.approx(12 * 60 * 60, abs=5)


def test_the_session_holds_an_identifier_not_a_credential(client: Client, user: User) -> None:
    _sign_in(client)

    stored = repr(dict(client.session.items()))
    assert PASSWORD not in stored
    assert EMAIL not in stored
    assert set(client.session.keys()) == {"_auth_user_id", "_auth_user_backend", "_auth_user_hash"}


def test_the_csrf_cookie_is_secure(client: Client) -> None:
    cookie = client.get(LOGIN).cookies["csrftoken"]

    assert cookie["secure"] is True
    assert cookie["samesite"] == "Lax"


# --- CSRF -----------------------------------------------------------------------


def _token(client: Client) -> str:
    return client.get(LOGIN).cookies["csrftoken"].value


def test_sign_in_without_a_csrf_token_is_refused(user: User) -> None:
    client = Client(enforce_csrf_checks=True)
    client.get(LOGIN)

    response = _sign_in(client)

    assert response.status_code == 403
    assert _signed_in_as(client) is None
    assert _events() == []


def test_sign_in_with_a_csrf_token_works(user: User) -> None:
    client = Client(enforce_csrf_checks=True)

    response = _sign_in(client, csrfmiddlewaretoken=_token(client))

    assert response.status_code == 302
    assert _signed_in_as(client) == str(user.pk)


def test_sign_in_with_a_forged_csrf_token_is_refused(user: User) -> None:
    client = Client(enforce_csrf_checks=True)
    client.get(LOGIN)

    response = _sign_in(client, csrfmiddlewaretoken="A" * 64)

    assert response.status_code == 403
    assert _signed_in_as(client) is None


def test_sign_out_without_a_csrf_token_is_refused(user: User) -> None:
    client = Client(enforce_csrf_checks=True)
    _sign_in(client, csrfmiddlewaretoken=_token(client))

    response = client.post(LOGOUT)

    assert response.status_code == 403
    assert _signed_in_as(client) == str(user.pk)
    assert _events() == [("login_success", user.pk)]


def test_sign_out_with_a_csrf_token_works(user: User) -> None:
    client = Client(enforce_csrf_checks=True)
    _sign_in(client, csrfmiddlewaretoken=_token(client))

    response = client.post(LOGOUT, {"csrfmiddlewaretoken": _token(client)})

    assert response.status_code == 302
    assert _signed_in_as(client) is None


@pytest.mark.parametrize("method", ["get", "head", "put", "patch", "delete"])
def test_credentials_are_only_accepted_by_post(client: Client, user: User, method: str) -> None:
    getattr(client, method)(f"{LOGIN}?email={EMAIL}&password={PASSWORD}")

    assert _signed_in_as(client) is None
    assert _events() == []


# --- Where signing in leads -----------------------------------------------------


@pytest.mark.parametrize(
    "destination",
    [
        "https://evil.test/",
        "http://evil.test/",
        "//evil.test/",
        "///evil.test/",
        "/\\evil.test/",
        "\\\\evil.test/",
        "https:evil.test",
        "javascript:alert(1)",
        "data:text/html,TEST",
        "http://testserver.evil.test/",
        "http://testserver@evil.test/",
        " https://evil.test/",
        "\thttps://evil.test/",
    ],
)
def test_an_outside_destination_is_ignored(client: Client, user: User, destination: str) -> None:
    for response in (
        _sign_in(client, next=destination),
        client.post(f"{LOGIN}?next={destination}", {"email": EMAIL, "password": PASSWORD}),
    ):
        assert response.status_code == 302
        assert response["Location"] == LOGIN


@pytest.mark.parametrize("destination", ["/workspace/", "/health/live/", "/workspace/?page=2"])
def test_a_destination_on_this_site_is_followed(
    client: Client, user: User, destination: str
) -> None:
    response = _sign_in(client, next=destination)

    assert response.status_code == 302
    assert response["Location"] == destination


def test_the_page_carries_a_local_destination_and_drops_an_outside_one(client: Client) -> None:
    local = client.get(f"{LOGIN}?next=/workspace/").content.decode()
    outside = client.get(f"{LOGIN}?next=https://evil.test/").content.decode()

    assert '<input type="hidden" name="next" value="/workspace/">' in local
    assert "evil.test" not in outside
    assert 'name="next"' not in outside


def test_a_destination_is_escaped_in_the_page(client: Client) -> None:
    body = client.get(f'{LOGIN}?next=/workspace/"><script>alert(1)</script>').content.decode()

    assert "<script>" not in body


# --- Signing out ----------------------------------------------------------------


def test_signing_out_ends_the_session(client: Client, user: User) -> None:
    _sign_in(client)
    key = client.session.session_key

    response = client.post(LOGOUT)

    assert response.status_code == 302
    assert response["Location"] == LOGIN
    assert _signed_in_as(client) is None
    assert not Session.objects.filter(session_key=key).exists()
    assert _events() == [("login_success", user.pk), ("logout", user.pk)]


def test_the_old_session_cookie_is_worthless_after_signing_out(client: Client, user: User) -> None:
    _sign_in(client)
    stolen = client.cookies["sessionid"].value
    client.post(LOGOUT)

    thief = Client()
    thief.cookies["sessionid"] = stolen

    assert EMAIL not in thief.get(LOGIN).content.decode()
    assert _signed_in_as(thief) is None


def test_signing_out_tells_the_browser_to_drop_the_cookie(client: Client, user: User) -> None:
    _sign_in(client)

    cookie = client.post(LOGOUT).cookies["sessionid"]

    assert cookie.value == ""
    assert cookie["max-age"] == 0


@pytest.mark.parametrize("method", ["get", "head", "put", "patch", "delete", "options"])
def test_signing_out_is_post_only(client: Client, user: User, method: str) -> None:
    _sign_in(client)

    response = getattr(client, method)(LOGOUT)

    assert response.status_code == 405
    assert _signed_in_as(client) == str(user.pk)
    assert _events() == [("login_success", user.pk)]


def test_signing_out_when_not_signed_in_is_harmless(client: Client) -> None:
    response = client.post(LOGOUT)

    assert response.status_code == 302
    assert response["Location"] == LOGIN
    assert _events() == []


@pytest.mark.parametrize("destination", ["https://evil.test/", "//evil.test/", "/workspace/"])
def test_signing_out_takes_no_destination(client: Client, user: User, destination: str) -> None:
    _sign_in(client)

    response = client.post(f"{LOGOUT}?next={destination}", {"next": destination})

    assert response["Location"] == LOGIN


def test_signing_out_changes_nothing_but_the_session_and_the_record(
    client: Client, user: User, user_with_roles: UserFactory
) -> None:
    other = user_with_roles(Role.READER)
    _sign_in(client)
    users_before = list(User.objects.order_by("id").values("id", "is_active", "password", "email"))

    client.post(LOGOUT)

    assert list(User.objects.order_by("id").values("id", "is_active", "password", "email")) == (
        users_before
    )
    assert AuthenticationEvent.objects.filter(user=other).count() == 0


# --- Access after signing in ----------------------------------------------------


@pytest.mark.urls(__name__)
def test_an_anonymous_visitor_cannot_reach_the_workspace(client: Client) -> None:
    assert client.get("/workspace/").status_code == 403
    assert client.get(LOGIN).status_code == 200


@pytest.mark.urls(__name__)
def test_signing_in_gives_what_the_roles_give_and_no_more(
    client: Client, user_with_roles: UserFactory
) -> None:
    reader = user_with_roles(Role.READER)
    reader.set_password(PASSWORD)
    reader.save()
    without_role = User.objects.create_user("test.norole@caipo.test", PASSWORD)

    _sign_in(client, reader.email)
    assert client.get("/workspace/").status_code == 200
    client.post(LOGOUT)
    assert client.get("/workspace/").status_code == 403

    _sign_in(client, without_role.email)
    assert _signed_in_as(client) == str(without_role.pk)
    assert client.get("/workspace/").status_code == 403


def test_a_deactivated_account_loses_its_session(client: Client, user: User) -> None:
    _sign_in(client)

    User.objects.filter(pk=user.pk).update(is_active=False)

    assert EMAIL not in client.get(LOGIN).content.decode()


def test_changing_the_password_ends_other_sessions(client: Client, user: User) -> None:
    _sign_in(client)

    user.set_password("TEST-a-new-passphrase-entirely")
    user.save()

    assert EMAIL not in client.get(LOGIN).content.decode()


def test_signing_in_as_someone_else_discards_the_first_session(client: Client, user: User) -> None:
    other = User.objects.create_user("test.other@caipo.test", PASSWORD)
    _sign_in(client)
    first_key = client.session.session_key

    _sign_in(client, other.email)

    assert _signed_in_as(client) == str(other.pk)
    assert client.session.session_key != first_key
    assert not Session.objects.filter(session_key=first_key).exists()


def test_no_request_creates_an_administrator_or_a_role_event(client: Client, user: User) -> None:
    names = ["role", "roles", "administrator", "is_administrator", "bootstrap", "actor"]
    extra = dict.fromkeys(names, "administrator")
    headers = {f"X-{name}": "administrator" for name in names}
    for name in names:
        client.cookies[name] = "administrator"
    query = "&".join(f"{name}=administrator" for name in names)

    client.get(f"{LOGIN}?{query}", headers=headers)
    client.post(
        f"{LOGIN}?{query}", {"email": EMAIL, "password": PASSWORD, **extra}, headers=headers
    )
    client.post(f"{LOGOUT}?{query}", extra, headers=headers)

    assert RoleEvent.objects.count() == 0
    assert selectors.roles_of(user) == frozenset()
    assert selectors.an_administrator_was_ever_created() is False


# --- Throttling over HTTP -------------------------------------------------------


def test_too_many_failures_answer_429_whether_or_not_the_account_exists(
    user: User, settings: LazySettings
) -> None:
    limit = settings.LOGIN_THROTTLE_ACCOUNT_FAILURES
    pages = []
    for email, address in ((EMAIL, "203.0.113.10"), (UNKNOWN, "203.0.113.20")):
        client = Client(REMOTE_ADDR=address)
        for _ in range(limit):
            assert _sign_in(client, email, WRONG).status_code == 200
        response = _sign_in(client, email, PASSWORD)
        assert response.status_code == 429
        assert THROTTLED in response.content.decode()
        assert _signed_in_as(client) is None
        pages.append(_without_what_varies(response))

    assert pages[0] == pages[1]


def test_a_forwarded_header_cannot_move_an_attempt_to_another_source(
    user: User, settings: LazySettings
) -> None:
    client = Client(REMOTE_ADDR="203.0.113.10")
    limit = settings.LOGIN_THROTTLE_SOURCE_FAILURES

    for number in range(limit):
        client.post(
            LOGIN,
            {"email": f"test.guess{number}@caipo.test", "password": WRONG},
            headers={
                "X-Forwarded-For": f"198.51.100.{number}",
                "X-Real-IP": f"198.51.100.{number}",
            },
        )

    response = client.post(
        LOGIN,
        {"email": EMAIL, "password": PASSWORD},
        headers={"X-Forwarded-For": "198.51.100.250", "Forwarded": "for=198.51.100.250"},
    )
    assert response.status_code == 429


# --- What is recorded and logged ------------------------------------------------


def test_events_made_by_a_request_carry_its_correlation_id(client: Client, user: User) -> None:
    _sign_in(client, EMAIL, WRONG)
    _sign_in(client)
    client.post(LOGOUT)

    correlation_ids = list(
        AuthenticationEvent.objects.order_by("id").values_list("correlation_id", flat=True)
    )
    assert all(re.fullmatch(r"[0-9a-f]{32}", correlation_id) for correlation_id in correlation_ids)
    assert len(set(correlation_ids)) == 3, "one request, one correlation ID"


def test_no_credential_reaches_the_logs_or_the_event_table(
    client: Client, user: User, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        _sign_in(client, EMAIL, WRONG)
        _sign_in(client, UNKNOWN, WRONG)
        _sign_in(client)
        session_key = client.session.session_key
        client.post(LOGOUT)
        client.post(LOGIN, {"email": EMAIL, "password": WRONG}, REMOTE_ADDR="203.0.113.99")

    logged = " ".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
    stored = repr(list(AuthenticationEvent.objects.values()))
    assert session_key
    for secret in (PASSWORD, WRONG, EMAIL, UNKNOWN, session_key, user.password, "203.0.113.99"):
        assert secret not in logged
        assert secret not in stored
