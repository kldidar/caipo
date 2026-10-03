"""Two-step verification over HTTP: enrolling, signing in with a code, and disabling.

Nothing stands in for TOTP here. Secrets are read from the enrolment page as a
person would read them, and codes are computed from them as an authenticator
application would.
"""

import base64
import logging
import re
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.conf import LazySettings
from django.contrib.sessions.models import Session
from django.http import HttpRequest, HttpResponse
from django.test import Client
from django.urls import include, path
from django.utils import timezone

from caipo.accounts import selectors, services
from caipo.accounts.models import (
    AuthenticationEvent,
    MfaChallenge,
    TotpDevice,
    TotpDeviceState,
    User,
)
from caipo.accounts.selectors import MfaState, Permission, Role
from caipo.accounts.tests.fixtures import (
    TEST_TOTP_SECRET,
    Clock,
    UserFactory,
    approving_administrator,
    code_at,
    enrolled_device,
    logged,
)
from caipo.web import sessions
from caipo.web.access import requires
from caipo.web.tests.helpers import signed_in, verified

pytestmark = [pytest.mark.services, pytest.mark.django_db, pytest.mark.urls(__name__)]

type AccountFactory = Callable[..., User]

# Visibly synthetic fixture values.
PASSWORD = "TEST-passphrase-for-fixtures-only"
WRONG = "TEST-wrong-passphrase"

LOGIN = "/login/"
VERIFY = "/login/verify/"
LOGOUT = "/logout/"
OVERVIEW = "/account/second-factor/"
ENROL = "/account/second-factor/enrol/"
CONFIRM = "/account/second-factor/confirm/"
DISABLE = "/account/second-factor/disable/"

ADMINISTRATION = "/administration/"
REVIEW = "/review/"
WORKSPACE = "/workspace/"

CODE_REFUSED = "The code was not accepted."
REFUSED = "That was not accepted."
STEP = timedelta(seconds=30)


@requires(Permission.ROLES_MANAGE)
def administration_view(request: HttpRequest) -> HttpResponse:
    return HttpResponse("TEST administration")


@requires(Permission.RESEARCH_REVIEW)
def review_view(request: HttpRequest) -> HttpResponse:
    return HttpResponse("TEST review")


@requires(Permission.WORKSPACE_READ)
def workspace_view(request: HttpRequest) -> HttpResponse:
    return HttpResponse("TEST workspace")


# The real routes, plus one view for each kind of permission.
urlpatterns = [
    path("", include("caipo.web.urls")),
    path("administration/", administration_view),
    path("review/", review_view),
    path("workspace/", workspace_view),
]


@pytest.fixture
def account(user_with_roles: UserFactory) -> AccountFactory:
    """Return a factory for synthetic users with the given roles and a known password."""

    def make(*roles: Role) -> User:
        user = user_with_roles(*roles)
        user.set_password(PASSWORD)
        user.save()
        return user

    return make


def _password_step(client: Client, user: User, password: str = PASSWORD, **extra: str) -> Any:
    return client.post(LOGIN, {"email": user.email, "password": password, **extra})


def _signed_in_as(client: Client) -> str | None:
    user_id: str | None = client.session.get("_auth_user_id")
    return user_id


def _events() -> list[str]:
    return list(AuthenticationEvent.objects.order_by("id").values_list("event_type", flat=True))


def _shown_secret(response: Any) -> bytes:
    """Read the key off the enrolment page, as the person enrolling would."""
    (key,) = re.findall(r"<code>([A-Z2-7]{32})</code>", response.content.decode())
    return base64.b32decode(key)


def _wrong_code(secret: bytes = TEST_TOTP_SECRET) -> str:
    """Return a code that is certainly not right for the secret at the moment."""
    now = timezone.now()
    right = {code_at(now + offset * STEP, secret=secret) for offset in range(-10, 11)}
    return next(code for code in ("000000", "111111", "222222", "333333") if code not in right)


def _approve_what_awaits_approval() -> None:
    """Have an Administrator approve every enrolment request that awaits one."""
    if not TotpDevice.objects.filter(state=TotpDeviceState.PENDING_APPROVAL).exists():
        return
    approver = approving_administrator()
    for request in selectors.enrollment_requests_awaiting_approval(approver):
        result = services.approve_mfa_enrollment(
            actor=approver, request_number=request.number, source="203.0.113.99"
        )
        assert result.outcome == services.MfaOutcome.ACCEPTED


def _start(client: Client, **extra: str) -> Any:
    """Start an enrolment through the page and, where one is needed, have it approved.

    What these tests are about begins where the first code is awaited. The
    approval pages, and everything an unapproved enrolment must not do, are
    tested in test_second_factor_request_pages.py.
    """
    response = client.post(ENROL, {"password": PASSWORD, **extra})
    _approve_what_awaits_approval()
    return response


def _enrol(client: Client) -> bytes:
    """Enrol the signed-in account through the pages and return its secret."""
    secret = _shown_secret(_start(client))
    response = client.post(CONFIRM, {"code": code_at(secret=secret)})
    assert response.status_code == 302
    return secret


# --- Who reaches the pages ------------------------------------------------------


@pytest.mark.parametrize("url", [OVERVIEW, ENROL, CONFIRM, DISABLE])
@pytest.mark.parametrize("method", ["get", "post"])
def test_an_anonymous_visitor_cannot_reach_the_second_factor_pages(
    client: Client, url: str, method: str
) -> None:
    response = getattr(client, method)(url, {"password": PASSWORD, "code": "123456"})

    assert response.status_code == 403
    assert not TotpDevice.objects.exists()
    assert _events() == []


def test_an_account_without_a_role_cannot_reach_them(
    client: Client, account: AccountFactory
) -> None:
    signed_in(client, account())

    assert client.get(OVERVIEW).status_code == 403
    assert _start(client).status_code == 403
    assert not TotpDevice.objects.exists()


@pytest.mark.parametrize("role", list(Role))
def test_every_role_reaches_its_own_second_factor_page_on_a_password(
    client: Client, account: AccountFactory, role: Role
) -> None:
    signed_in(client, account(role))

    response = client.get(OVERVIEW)

    assert response.status_code == 200
    assert "Two-step verification is off" in response.content.decode()
    assert "no-store" in response["Cache-Control"]


@pytest.mark.parametrize("url", [ENROL, CONFIRM, DISABLE])
@pytest.mark.parametrize("method", ["get", "head", "put", "patch", "delete"])
def test_changes_are_made_by_post_only(
    client: Client, account: AccountFactory, url: str, method: str
) -> None:
    user = account(Role.ADMINISTRATOR)
    signed_in(client, user)

    response = getattr(client, method)(f"{url}?password={PASSWORD}&code=123456")

    assert response.status_code == 405
    assert selectors.mfa_state_of(user) == MfaState.NOT_ENROLLED
    assert _events() == []


@pytest.mark.parametrize("url", [ENROL, CONFIRM, DISABLE])
def test_changes_need_a_csrf_token(account: AccountFactory, url: str) -> None:
    user = account(Role.ADMINISTRATOR)
    client = signed_in(Client(enforce_csrf_checks=True), user)

    response = client.post(url, {"password": PASSWORD, "code": "123456"})

    assert response.status_code == 403
    assert selectors.mfa_state_of(user) == MfaState.NOT_ENROLLED
    assert _events() == []


def test_a_change_with_a_csrf_token_is_accepted(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    client = signed_in(Client(enforce_csrf_checks=True), user)
    token = client.get(OVERVIEW).cookies["csrftoken"].value

    response = _start(client, csrfmiddlewaretoken=token)

    assert response.status_code == 200
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION


# --- Enrolling ------------------------------------------------------------------


def test_enrolling_needs_the_password_again(client: Client, account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    signed_in(client, user)

    response = client.post(ENROL, {"password": WRONG})

    assert response.status_code == 200
    assert REFUSED in response.content.decode()
    assert "<code>" not in response.content.decode()
    assert WRONG not in response.content.decode()
    assert selectors.mfa_state_of(user) == MfaState.NOT_ENROLLED
    assert _events() == ["password_confirmation_failed"]


def test_enrolling_without_a_password_starts_nothing(
    client: Client, account: AccountFactory
) -> None:
    user = account(Role.ADMINISTRATOR)
    signed_in(client, user)

    response = client.post(ENROL, {})

    assert response.status_code == 200
    assert selectors.mfa_state_of(user) == MfaState.NOT_ENROLLED
    assert _events() == []


def test_the_secret_is_shown_once_in_the_response_that_started_the_enrolment(
    client: Client, account: AccountFactory
) -> None:
    user = account(Role.ADMINISTRATOR)
    signed_in(client, user)

    response = _start(client)
    body = response.content.decode()
    key = base64.b32encode(_shown_secret(response)).decode()

    assert response.status_code == 200
    assert "no-store" in response["Cache-Control"]
    assert f"otpauth://totp/CAIPO:{user.email.replace('@', '%40')}?" in body
    assert f"secret={key}&amp;" in body
    assert PASSWORD not in body
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION
    # It cannot be fetched again, by any page.
    again = client.get(OVERVIEW).content.decode()
    assert key not in again
    assert "otpauth" not in again
    assert "has been started and is not on yet" in again
    assert key not in client.get(LOGIN).content.decode()


def test_the_secret_is_not_kept_in_the_session_or_in_a_cookie_or_in_a_url(
    client: Client, account: AccountFactory
) -> None:
    signed_in(client, account(Role.ADMINISTRATOR))

    response = _start(client)
    secret = _shown_secret(response)
    key = base64.b32encode(secret).decode()
    confirmed = client.post(CONFIRM, {"code": code_at(secret=secret)})

    for value in (key, secret.hex(), "otpauth"):
        assert value not in repr(dict(client.session.items()))
        assert value not in repr(list(Session.objects.values()))
        assert value not in str(client.cookies)
        assert value not in str(response.headers)
        assert value not in str(confirmed.headers)
    assert confirmed["Location"] == OVERVIEW


def test_a_secret_or_a_state_supplied_by_the_browser_is_ignored(
    client: Client, account: AccountFactory
) -> None:
    user = account(Role.ADMINISTRATOR)
    signed_in(client, user)
    supplied = base64.b32encode(TEST_TOTP_SECRET).decode()
    claims = {
        "secret": supplied,
        "key": supplied,
        "state": "active",
        "enabled": "true",
        "confirmed": "true",
        "mfa_verified": "true",
        "user": "1",
    }

    response = client.post(
        f"{ENROL}?secret={supplied}&state=active", {"password": PASSWORD, **claims}
    )
    # No claim spared the request its approval.
    assert selectors.mfa_state_of(user) == MfaState.PENDING_APPROVAL
    _approve_what_awaits_approval()

    assert _shown_secret(response) != TEST_TOTP_SECRET
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION
    # The code of the supplied secret confirms nothing, with whatever claims.
    confirmation = client.post(
        f"{CONFIRM}?state=active&enabled=true",
        {"code": code_at(secret=TEST_TOTP_SECRET), **claims},
        headers={"X-MFA-Verified": "true", "X-State": "active"},
    )
    assert confirmation.status_code == 200
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION
    assert client.get(ADMINISTRATION).status_code == 403


def test_a_pending_enrolment_opens_no_privileged_page(
    client: Client, account: AccountFactory
) -> None:
    signed_in(client, account(Role.ADMINISTRATOR, Role.REVIEWER))

    _start(client)

    assert client.get(ADMINISTRATION).status_code == 403
    assert client.get(REVIEW).status_code == 403
    assert client.get(WORKSPACE).status_code == 403


def test_a_wrong_code_does_not_turn_it_on(client: Client, account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    signed_in(client, user)
    secret = _shown_secret(_start(client))

    response = client.post(CONFIRM, {"code": _wrong_code(secret)})

    assert response.status_code == 200
    assert REFUSED in response.content.decode()
    assert base64.b32encode(secret).decode() not in response.content.decode()
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION
    assert client.get(ADMINISTRATION).status_code == 403


@pytest.mark.parametrize("code", ["", "12345", "1234567", "abcdef"])
def test_a_malformed_code_is_not_an_attempt(
    client: Client, account: AccountFactory, code: str
) -> None:
    user = account(Role.ADMINISTRATOR)
    signed_in(client, user)
    _start(client)

    response = client.post(CONFIRM, {"code": code})

    assert response.status_code == 200
    assert selectors.mfa_state_of(user) == MfaState.PENDING_VERIFICATION


def test_the_right_code_turns_it_on_and_raises_this_session(
    client: Client, account: AccountFactory
) -> None:
    user = account(Role.ADMINISTRATOR)
    signed_in(client, user)
    assert client.get(ADMINISTRATION).status_code == 403
    secret = _shown_secret(_start(client))
    key_before = client.session.session_key

    response = client.post(CONFIRM, {"code": code_at(secret=secret)})

    assert response.status_code == 302
    assert response["Location"] == OVERVIEW
    assert selectors.mfa_state_of(user) == MfaState.ACTIVE
    assert client.get(ADMINISTRATION).status_code == 200
    # The session that gained assurance has a new key, and the old one is gone.
    assert client.session.session_key != key_before
    assert not Session.objects.filter(session_key=key_before).exists()
    assert _signed_in_as(client) == str(user.pk)
    body = client.get(OVERVIEW).content.decode()
    assert "Two-step verification is on" in body
    assert base64.b32encode(secret).decode() not in body
    assert _events() == [
        "mfa_enrollment_started",
        "mfa_enrollment_approved",
        "mfa_enrollment_succeeded",
    ]


def test_the_csrf_token_is_replaced_when_the_session_gains_assurance(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    client = signed_in(Client(enforce_csrf_checks=True), user)
    before = client.get(OVERVIEW).cookies["csrftoken"].value
    secret = _shown_secret(_start(client, csrfmiddlewaretoken=before))

    response = client.post(CONFIRM, {"code": code_at(secret=secret), "csrfmiddlewaretoken": before})

    assert response.status_code == 302
    assert response.cookies["csrftoken"].value != before
    # The token from before the change no longer authorises a request.
    stale = Client(enforce_csrf_checks=True)
    stale.cookies["sessionid"] = client.cookies["sessionid"].value
    stale.cookies["csrftoken"] = client.cookies["csrftoken"].value
    assert stale.post(DISABLE, {"csrfmiddlewaretoken": before}).status_code == 403


def test_enrolling_raises_only_the_session_that_proved_the_code(
    client: Client, account: AccountFactory
) -> None:
    user = account(Role.ADMINISTRATOR)
    elsewhere = signed_in(Client(), user)
    signed_in(client, user)

    _enrol(client)

    assert client.get(ADMINISTRATION).status_code == 200
    assert elsewhere.get(ADMINISTRATION).status_code == 403


def test_an_expired_enrolment_cannot_be_confirmed(
    client: Client, account: AccountFactory, clock: Clock, settings: LazySettings
) -> None:
    # An enrolment that needs no approval; one that does waits longer.
    user = account(Role.READER)
    signed_in(client, user)
    secret = _shown_secret(_start(client))
    clock(settings.MFA_ENROLLMENT_LIFETIME)

    response = client.post(CONFIRM, {"code": code_at(secret=secret)})

    assert response.status_code == 409
    assert selectors.mfa_state_of(user) == MfaState.NOT_ENROLLED
    assert client.get(ADMINISTRATION).status_code == 403


def test_enrolling_again_while_it_is_on_is_refused(client: Client, account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    signed_in(client, user)
    _enrol(client)
    device = TotpDevice.objects.values().get(user=user)

    response = _start(client)

    assert response.status_code == 409
    assert "<code>" not in response.content.decode()
    assert TotpDevice.objects.values().get(user=user) == device


# --- Signing in -----------------------------------------------------------------


@pytest.mark.parametrize("role", [Role.READER, Role.RESEARCHER])
def test_reader_and_researcher_sign_in_with_a_password_alone(
    client: Client, account: AccountFactory, role: Role
) -> None:
    user = account(role)

    response = _password_step(client, user, next=WORKSPACE)

    assert response.status_code == 302
    assert response["Location"] == WORKSPACE
    assert _signed_in_as(client) == str(user.pk)
    assert client.get(WORKSPACE).status_code == 200
    assert client.get(ADMINISTRATION).status_code == 403
    assert client.get(REVIEW).status_code == 403
    assert _events() == ["login_success"]


@pytest.mark.parametrize(
    ("role", "privileged"), [(Role.REVIEWER, REVIEW), (Role.ADMINISTRATOR, ADMINISTRATION)]
)
def test_without_a_second_factor_the_password_opens_enrolment_and_nothing_privileged(
    client: Client, account: AccountFactory, role: Role, privileged: str
) -> None:
    user = account(role)

    response = _password_step(client, user)

    assert response.status_code == 302
    assert response["Location"] == LOGIN
    assert _signed_in_as(client) == str(user.pk)
    assert client.get(privileged).status_code == 403
    assert client.get(WORKSPACE).status_code == 403
    assert client.get(OVERVIEW).status_code == 200
    assert f'href="{OVERVIEW}"' in client.get(LOGIN).content.decode()


@pytest.mark.parametrize(
    ("role", "privileged"), [(Role.REVIEWER, REVIEW), (Role.ADMINISTRATOR, ADMINISTRATION)]
)
def test_with_a_second_factor_the_password_step_signs_nobody_in(
    client: Client, account: AccountFactory, role: Role, privileged: str
) -> None:
    user = account(role)
    enrolled_device(user)

    response = _password_step(client, user)

    assert response.status_code == 302
    assert response["Location"] == VERIFY
    assert _signed_in_as(client) is None
    assert set(client.session.keys()) == {sessions.PENDING_SIGN_IN_KEY}
    # To every other view the visitor is still anonymous.
    assert client.get(privileged).status_code == 403
    assert client.get(WORKSPACE).status_code == 403
    assert client.get(OVERVIEW).status_code == 403
    body = client.get(LOGIN).content.decode()
    assert user.email not in body
    assert 'type="password"' in body
    assert _events() == ["mfa_challenge_issued"]
    assert User.objects.get(pk=user.pk).last_login is None


def test_the_verification_page_asks_for_a_code_and_names_nobody(
    client: Client, account: AccountFactory
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    _password_step(client, user)

    response = client.get(VERIFY)
    body = response.content.decode()

    assert response.status_code == 200
    assert 'name="code"' in body
    assert 'autocomplete="one-time-code"' in body
    assert 'method="post"' in body
    assert 'name="csrfmiddlewaretoken"' in body
    assert "no-store" in response["Cache-Control"]
    assert user.email not in body
    assert response["X-Frame-Options"] == "DENY"


@pytest.mark.parametrize(
    ("role", "privileged"), [(Role.REVIEWER, REVIEW), (Role.ADMINISTRATOR, ADMINISTRATION)]
)
def test_the_right_code_completes_the_sign_in_with_the_higher_assurance(
    client: Client, account: AccountFactory, role: Role, privileged: str
) -> None:
    user = account(role)
    device = enrolled_device(user)
    _password_step(client, user, next=privileged)

    response = client.post(VERIFY, {"code": code_at()})

    assert response.status_code == 302
    assert response["Location"] == privileged
    assert _signed_in_as(client) == str(user.pk)
    assert client.session[sessions.VERIFIED_DEVICE_KEY] == device.pk
    assert sessions.PENDING_SIGN_IN_KEY not in client.session
    assert client.get(privileged).status_code == 200
    assert _events() == ["mfa_challenge_issued", "mfa_verification_succeeded", "login_success"]
    assert User.objects.get(pk=user.pk).last_login is not None


def test_a_reader_who_enrolled_is_asked_for_the_code_too(
    client: Client, account: AccountFactory
) -> None:
    user = account(Role.READER)
    enrolled_device(user)

    assert _password_step(client, user)["Location"] == VERIFY
    assert client.get(WORKSPACE).status_code == 403

    client.post(VERIFY, {"code": code_at()})
    assert client.get(WORKSPACE).status_code == 200


def test_a_wrong_code_signs_nobody_in(client: Client, account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    _password_step(client, user)

    response = client.post(VERIFY, {"code": _wrong_code()})

    assert response.status_code == 200
    assert CODE_REFUSED in response.content.decode()
    assert _signed_in_as(client) is None
    assert sessions.VERIFIED_DEVICE_KEY not in client.session
    assert client.get(ADMINISTRATION).status_code == 403
    assert _events() == ["mfa_challenge_issued", "mfa_verification_failed"]


def test_every_refusal_of_a_code_is_the_same_page(
    account: AccountFactory, clock: Clock, settings: LazySettings
) -> None:
    def page(response: Any) -> str:
        return re.sub(r'name="csrfmiddlewaretoken" value="[^"]+"', "", response.content.decode())

    wrong, used, lapsed, gone = (Client() for _ in range(4))
    users = [account(Role.ADMINISTRATOR) for _ in range(4)]
    for user in users:
        enrolled_device(user)
    for visitor, user in zip((wrong, used, lapsed, gone), users, strict=True):
        _password_step(visitor, user)
    # A code that was already used, a challenge that has lapsed, and a second
    # factor that no longer exists.
    code = code_at()
    TotpDevice.objects.filter(user=users[1]).update(last_used_step=10**10)
    MfaChallenge.objects.filter(user=users[2]).update(
        created_at=timezone.now() - settings.MFA_CHALLENGE_LIFETIME
    )
    TotpDevice.objects.filter(user=users[3]).delete()

    responses = [
        wrong.post(VERIFY, {"code": _wrong_code()}),
        used.post(VERIFY, {"code": code}),
        lapsed.post(VERIFY, {"code": code}),
        gone.post(VERIFY, {"code": code}),
    ]

    assert {response.status_code for response in responses} == {200}
    assert len({page(response) for response in responses}) == 1
    assert CODE_REFUSED in page(responses[0])
    assert all(_signed_in_as(visitor) is None for visitor in (wrong, used, lapsed, gone))


@pytest.mark.parametrize("method", ["get", "head", "put", "patch", "delete"])
def test_a_code_is_only_accepted_by_post(
    client: Client, account: AccountFactory, method: str
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    _password_step(client, user)

    getattr(client, method)(f"{VERIFY}?code={code_at()}")

    assert _signed_in_as(client) is None
    assert _events() == ["mfa_challenge_issued"]


def test_verification_needs_a_csrf_token(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    client = Client(enforce_csrf_checks=True)
    token = client.get(LOGIN).cookies["csrftoken"].value
    _password_step(client, user, csrfmiddlewaretoken=token)

    refused = client.post(VERIFY, {"code": code_at()})
    assert refused.status_code == 403
    assert _signed_in_as(client) is None
    assert _events() == ["mfa_challenge_issued"]

    token = client.get(VERIFY).cookies["csrftoken"].value
    accepted = client.post(VERIFY, {"code": code_at(), "csrfmiddlewaretoken": token})
    assert accepted.status_code == 302
    assert _signed_in_as(client) == str(user.pk)


@pytest.mark.parametrize("method", ["get", "post"])
def test_without_a_pending_sign_in_there_is_nothing_to_verify(client: Client, method: str) -> None:
    response = getattr(client, method)(VERIFY, {"code": "123456"})

    assert response.status_code == 302
    assert response["Location"] == LOGIN
    assert _events() == []


def test_someone_signed_in_by_password_cannot_verify_their_way_up(
    client: Client, account: AccountFactory
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    # A session from before the account enrolled: signed in, no code verified.
    signed_in(client, user)

    response = client.post(VERIFY, {"code": code_at()})

    assert response["Location"] == LOGIN
    assert client.get(ADMINISTRATION).status_code == 403
    assert _events() == []


# --- The session ----------------------------------------------------------------


def test_the_session_key_is_replaced_at_the_password_and_again_at_the_code(
    client: Client, account: AccountFactory
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    # A session that existed before signing in, as an attacker would plant.
    session = client.session
    session["planted"] = "TEST value"
    session.save()
    planted = session.session_key

    _password_step(client, user)
    pending = client.session.session_key
    assert pending != planted
    assert "planted" not in client.session
    assert not Session.objects.filter(session_key=planted).exists()

    client.post(VERIFY, {"code": code_at()})
    final = client.session.session_key
    assert final not in (planted, pending)
    assert not Session.objects.filter(session_key=pending).exists()
    assert _signed_in_as(client) == str(user.pk)


def test_a_planted_session_key_gains_nothing_from_the_sign_in(
    client: Client, account: AccountFactory
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    session = client.session
    session.save()
    planted = session.session_key
    assert planted

    _password_step(client, user)
    client.post(VERIFY, {"code": code_at()})

    attacker = Client()
    attacker.cookies["sessionid"] = planted
    assert attacker.get(ADMINISTRATION).status_code == 403
    assert attacker.get(VERIFY)["Location"] == LOGIN
    assert user.email not in attacker.get(LOGIN).content.decode()


def test_the_pending_session_cannot_be_replayed_after_it_was_used(
    client: Client, account: AccountFactory, clock: Clock
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    _password_step(client, user)
    pending_cookie = client.cookies["sessionid"].value
    challenge = client.session[sessions.PENDING_SIGN_IN_KEY]["challenge"]
    assert client.post(VERIFY, {"code": code_at()}).status_code == 302
    clock(STEP)

    # The cookie of the pending session leads nowhere any more.
    thief = Client()
    thief.cookies["sessionid"] = pending_cookie
    assert thief.post(VERIFY, {"code": code_at()})["Location"] == LOGIN
    assert _signed_in_as(thief) is None

    # And neither does the challenge, put back into a fresh session by hand.
    forged = Client()
    session = forged.session
    session[sessions.PENDING_SIGN_IN_KEY] = {"challenge": challenge, "destination": ""}
    session.save()
    response = forged.post(VERIFY, {"code": code_at()})
    assert response.status_code == 200
    assert CODE_REFUSED in response.content.decode()
    assert _signed_in_as(forged) is None
    assert _events().count("login_success") == 1


def test_the_session_holds_identifiers_and_no_secret_or_code(
    client: Client, account: AccountFactory
) -> None:
    user = account(Role.ADMINISTRATOR)
    device = enrolled_device(user)
    _password_step(client, user)
    code = code_at()

    pending = dict(client.session.items())
    client.post(VERIFY, {"code": code})
    final = dict(client.session.items())

    assert set(pending) == {sessions.PENDING_SIGN_IN_KEY}
    assert set(pending[sessions.PENDING_SIGN_IN_KEY]) == {"challenge", "destination"}
    assert set(final) == {
        "_auth_user_id",
        "_auth_user_backend",
        "_auth_user_hash",
        sessions.VERIFIED_DEVICE_KEY,
    }
    assert final[sessions.VERIFIED_DEVICE_KEY] == device.pk
    for stored in (repr(pending), repr(final)):
        assert code not in stored
        assert PASSWORD not in stored
        assert user.email not in stored
        assert TEST_TOTP_SECRET.hex() not in stored
        assert base64.b32encode(TEST_TOTP_SECRET).decode() not in stored


def test_a_challenge_cannot_be_moved_to_another_account(
    client: Client, account: AccountFactory, clock: Clock
) -> None:
    victim = account(Role.ADMINISTRATOR)
    attacker = account(Role.READER)
    enrolled_device(victim)
    # The attacker has a second factor of their own and knows the victim's password.
    attacker_client = signed_in(Client(), attacker)
    attacker_secret = _enrol(attacker_client)
    clock(STEP)
    _password_step(client, victim)

    response = client.post(
        VERIFY,
        {
            "code": code_at(secret=attacker_secret),
            "user": str(attacker.pk),
            "user_id": str(attacker.pk),
            "email": attacker.email,
        },
    )

    assert response.status_code == 200
    assert _signed_in_as(client) is None
    assert client.get(ADMINISTRATION).status_code == 403
    assert "login_success" not in _events()


def test_a_challenge_named_in_the_request_is_ignored(
    client: Client, account: AccountFactory
) -> None:
    # The visitor's own pending sign-in is for one account. They also hold the
    # challenge token and a valid code of another account.
    own = account(Role.READER)
    other = account(Role.ADMINISTRATOR)
    other_secret = b"TEST-other-secret-00"
    enrolled_device(own)
    enrolled_device(other, secret=other_secret)
    others_challenge = services.sign_in(email=other.email, password=PASSWORD, source="").challenge
    assert others_challenge
    _password_step(client, own)

    response = client.post(
        f"{VERIFY}?challenge={others_challenge}",
        {"code": code_at(secret=other_secret), "challenge": others_challenge},
        headers={"X-Challenge": others_challenge},
    )

    assert response.status_code == 200
    assert _signed_in_as(client) is None
    assert client.get(ADMINISTRATION).status_code == 403
    assert "login_success" not in _events()


def test_signing_in_as_another_account_abandons_the_pending_sign_in(
    client: Client, account: AccountFactory
) -> None:
    waiting = account(Role.ADMINISTRATOR)
    other = account(Role.READER)
    enrolled_device(waiting)
    _password_step(client, waiting)

    _password_step(client, other)

    assert _signed_in_as(client) == str(other.pk)
    assert sessions.PENDING_SIGN_IN_KEY not in client.session
    assert client.post(VERIFY, {"code": code_at()})["Location"] == LOGIN
    assert _signed_in_as(client) == str(other.pk)
    assert client.get(ADMINISTRATION).status_code == 403


def test_only_a_path_on_this_site_is_kept_while_the_code_is_awaited(
    client: Client, account: AccountFactory
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)

    _password_step(client, user, next="https://evil.test/")
    assert client.session[sessions.PENDING_SIGN_IN_KEY]["destination"] == ""

    _password_step(client, user, next=ADMINISTRATION)
    assert client.session[sessions.PENDING_SIGN_IN_KEY]["destination"] == ADMINISTRATION


def test_an_outside_destination_is_ignored_after_the_code(
    client: Client, account: AccountFactory
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    _password_step(client, user, next="https://evil.test/")

    response = client.post(VERIFY, {"code": code_at()})

    assert response["Location"] == LOGIN


def test_a_destination_given_with_the_code_is_ignored(
    client: Client, account: AccountFactory
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    _password_step(client, user, next=ADMINISTRATION)

    response = client.post(f"{VERIFY}?next=/workspace/", {"code": code_at(), "next": WORKSPACE})

    assert response["Location"] == ADMINISTRATION


# --- Tampering ------------------------------------------------------------------


def test_nothing_the_browser_sends_stands_in_for_the_code(
    client: Client, account: AccountFactory
) -> None:
    user = account(Role.ADMINISTRATOR, Role.REVIEWER)
    device = enrolled_device(user)
    signed_in(client, user)
    names = ["mfa", "mfa_verified", "assurance", "otp_verified", sessions.VERIFIED_DEVICE_KEY]
    values = ["true", "mfa_verified", str(device.pk)]

    for value in values:
        for name in names:
            client.cookies[name] = value
        query = "&".join(f"{name}={value}" for name in names)
        headers = {f"X-{name.replace('_', '-').replace('.', '-')}": value for name in names}
        for url in (ADMINISTRATION, REVIEW):
            response = client.post(f"{url}?{query}", dict.fromkeys(names, value), headers=headers)
            assert response.status_code == 403, (url, value)


def test_a_device_of_another_account_noted_in_the_session_proves_nothing(
    client: Client, account: AccountFactory
) -> None:
    user = account(Role.ADMINISTRATOR)
    other = account(Role.READER)
    others_device = enrolled_device(other)
    signed_in(client, user)

    for marker in (others_device.pk, 987654321, "1", True, [others_device.pk], {"device": 1}):
        session = client.session
        session[sessions.VERIFIED_DEVICE_KEY] = marker
        session.save()
        assert client.get(ADMINISTRATION).status_code == 403, marker


def test_a_pending_device_noted_in_the_session_proves_nothing(
    client: Client, account: AccountFactory
) -> None:
    user = account(Role.ADMINISTRATOR)
    signed_in(client, user)
    _start(client)
    session = client.session
    session[sessions.VERIFIED_DEVICE_KEY] = TotpDevice.objects.get(user=user).pk
    session.save()

    assert client.get(ADMINISTRATION).status_code == 403


def test_a_forged_pending_state_signs_nobody_in(client: Client, account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)

    for forged in (
        {"challenge": "TEST-invented-challenge", "destination": ""},
        {"challenge": str(user.pk), "destination": ""},
        {"user_id": user.pk},
        "TEST-not-a-mapping",
        user.pk,
    ):
        session = client.session
        session[sessions.PENDING_SIGN_IN_KEY] = forged
        session.save()
        client.post(VERIFY, {"code": code_at()})
        assert _signed_in_as(client) is None, forged
        assert client.get(ADMINISTRATION).status_code == 403, forged
    assert "login_success" not in _events()


def test_the_view_and_the_service_agree_at_each_assurance(
    client: Client, account: AccountFactory
) -> None:
    user = account(Role.ADMINISTRATOR, Role.REVIEWER)
    permissions = {ADMINISTRATION: Permission.ROLES_MANAGE, REVIEW: Permission.RESEARCH_REVIEW}

    for sign_in, expected in ((signed_in, 403), (verified, 200)):
        sign_in(client, user)
        actor = sessions_context(client, user)
        for url, permission in permissions.items():
            assert client.get(url).status_code == expected
            assert selectors.can(actor, permission) == (expected == 200)


# --- Throttling over HTTP -------------------------------------------------------


def test_too_many_wrong_codes_answer_429_and_the_right_code_no_longer_helps(
    client: Client, account: AccountFactory, settings: LazySettings
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    _password_step(client, user)

    for _ in range(settings.MFA_THROTTLE_FAILURES):
        assert client.post(VERIFY, {"code": _wrong_code()}).status_code == 200
    response = client.post(VERIFY, {"code": code_at()})

    assert response.status_code == 429
    assert "Too many codes were refused." in response.content.decode()
    assert _signed_in_as(client) is None
    assert client.get(ADMINISTRATION).status_code == 403
    assert _events().count("mfa_verification_failed") == settings.MFA_THROTTLE_FAILURES


def test_a_new_browser_and_a_new_password_step_do_not_reset_the_count(
    account: AccountFactory, settings: LazySettings
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)

    for number in range(settings.MFA_THROTTLE_FAILURES):
        visitor = Client(REMOTE_ADDR=f"203.0.113.{number}")
        _password_step(visitor, user)
        assert visitor.post(VERIFY, {"code": _wrong_code()}).status_code == 200

    last = Client(REMOTE_ADDR="203.0.113.200")
    _password_step(last, user)
    assert last.post(VERIFY, {"code": code_at()}).status_code == 429
    assert _signed_in_as(last) is None


# --- Signing out ----------------------------------------------------------------


def test_signing_out_abandons_a_pending_sign_in(client: Client, account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    _password_step(client, user)
    pending_cookie = client.cookies["sessionid"].value
    pending_key = client.session.session_key

    response = client.post(LOGOUT)

    assert response["Location"] == LOGIN
    assert not MfaChallenge.objects.exists()
    assert not Session.objects.filter(session_key=pending_key).exists()
    thief = Client()
    thief.cookies["sessionid"] = pending_cookie
    assert thief.post(VERIFY, {"code": code_at()})["Location"] == LOGIN
    assert _signed_in_as(thief) is None
    # Nobody was signed in, so nobody signed out.
    assert _events() == ["mfa_challenge_issued"]


def test_signing_out_ends_the_verified_session(client: Client, account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    _password_step(client, user)
    client.post(VERIFY, {"code": code_at()})
    assert client.get(ADMINISTRATION).status_code == 200
    stolen = client.cookies["sessionid"].value
    key = client.session.session_key

    client.post(LOGOUT)

    assert not Session.objects.filter(session_key=key).exists()
    assert client.get(ADMINISTRATION).status_code == 403
    thief = Client()
    thief.cookies["sessionid"] = stolen
    assert thief.get(ADMINISTRATION).status_code == 403
    assert _events()[-1] == "logout"


# --- Disabling ------------------------------------------------------------------


def test_turning_it_off_needs_the_password_and_a_current_code(
    client: Client, account: AccountFactory
) -> None:
    user = account(Role.ADMINISTRATOR)
    verified(client, user)

    for attempt in (
        {"password": WRONG, "code": code_at()},
        {"password": PASSWORD, "code": _wrong_code()},
        {"password": PASSWORD},
        {"code": code_at()},
        {},
    ):
        response = client.post(DISABLE, attempt)
        assert response.status_code == 200, attempt
        assert selectors.mfa_state_of(user) == MfaState.ACTIVE, attempt
        assert client.get(ADMINISTRATION).status_code == 200, attempt

    for claim in ("disable_mfa", "disable", "force", "confirmed"):
        client.post(f"{DISABLE}?{claim}=true", {claim: "true"}, headers={f"X-{claim}": "true"})
        assert selectors.mfa_state_of(user) == MfaState.ACTIVE, claim


def test_turning_it_off_takes_the_privileges_with_it(
    client: Client, account: AccountFactory
) -> None:
    user = account(Role.ADMINISTRATOR)
    verified(client, user)
    key_before = client.session.session_key

    response = client.post(DISABLE, {"password": PASSWORD, "code": code_at()})

    assert response.status_code == 302
    assert response["Location"] == OVERVIEW
    assert selectors.mfa_state_of(user) == MfaState.NOT_ENROLLED
    assert not TotpDevice.objects.exists()
    assert sessions.VERIFIED_DEVICE_KEY not in client.session
    assert client.session.session_key != key_before
    assert client.get(ADMINISTRATION).status_code == 403
    assert _signed_in_as(client) == str(user.pk)
    assert _events() == ["mfa_disabled"]


def test_turning_it_off_when_it_is_off_is_not_possible(
    client: Client, account: AccountFactory
) -> None:
    signed_in(client, account(Role.READER))

    response = client.post(DISABLE, {"password": PASSWORD, "code": "123456"})

    assert response.status_code == 409


# --- What is recorded and logged ------------------------------------------------


def test_no_secret_code_or_session_key_reaches_the_logs_or_a_url(
    client: Client, account: AccountFactory, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    user = account(Role.ADMINISTRATOR)
    locations: list[str] = []
    used: list[str] = [PASSWORD]

    with caplog.at_level(logging.DEBUG):
        locations.append(_password_step(client, user)["Location"])
        shown = _start(client)
        secret = _shown_secret(shown)
        used += [base64.b32encode(secret).decode(), secret.hex()]
        used.append(_wrong_code(secret))
        client.post(CONFIRM, {"code": used[-1]})
        used.append(code_at(secret=secret))
        locations.append(client.post(CONFIRM, {"code": used[-1]})["Location"])
        used.append(str(client.session.session_key))
        locations.append(client.post(LOGOUT)["Location"])
        clock(STEP)
        locations.append(_password_step(client, user)["Location"])
        used.append(client.session[sessions.PENDING_SIGN_IN_KEY]["challenge"])
        used.append(str(client.session.session_key))
        used.append(code_at(secret=secret))
        locations.append(client.post(VERIFY, {"code": used[-1]})["Location"])
        used.append(str(client.session.session_key))
        assert client.get(ADMINISTRATION).status_code == 200

    written = logged(caplog.records)
    stored = repr(list(AuthenticationEvent.objects.values()))
    assert locations == [LOGIN, OVERVIEW, LOGIN, VERIFY, LOGIN]
    for value in used:
        assert value not in written, value
        assert value not in stored, value
        assert all(value not in location for location in locations), value
    assert user.email not in written


def test_events_made_by_the_pages_carry_the_correlation_id_of_their_request(
    client: Client, account: AccountFactory
) -> None:
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    _password_step(client, user)
    client.post(VERIFY, {"code": code_at()})

    rows = list(
        AuthenticationEvent.objects.order_by("id").values_list("event_type", "correlation_id")
    )

    assert all(re.fullmatch(r"[0-9a-f]{32}", correlation_id) for _, correlation_id in rows)
    by_type = dict(rows)
    assert by_type["mfa_verification_succeeded"] == by_type["login_success"]
    assert by_type["mfa_challenge_issued"] != by_type["login_success"]


# --- The whole journey of the first Administrator -------------------------------


def test_the_first_administrator_from_bootstrap_to_privilege_and_back(
    client: Client, user_with_roles: UserFactory, clock: Clock
) -> None:
    email = "test.administrator@caipo.test"
    password = "TEST-correct-horse-battery-staple"
    enrollment = services.prepare_first_administrator(email=email, password=password)
    administrator = services.create_first_administrator(
        email=email,
        password=password,
        operator="TEST-operator",
        enrollment=enrollment,
        code=code_at(secret=enrollment.secret),
    )
    secret = enrollment.secret
    target = user_with_roles()
    clock(STEP)

    # 1. The password alone signs nobody in, and opens nothing at all: not
    #    the administration, and not the pages that manage the second factor.
    assert client.post(LOGIN, {"email": email, "password": password})["Location"] == VERIFY
    assert _signed_in_as(client) is None
    assert client.get(ADMINISTRATION).status_code == 403
    assert client.get(OVERVIEW).status_code == 403
    assert client.post(ENROL, {"password": password}).status_code == 403
    assert TotpDevice.objects.get().user == administrator

    # 2. A wrong code changes nothing.
    assert client.post(VERIFY, {"code": _wrong_code(secret)}).status_code == 200
    assert client.get(ADMINISTRATION).status_code == 403

    # 3. A code from the authenticator set up at the terminal completes the
    #    sign-in, with the privilege.
    assert client.post(VERIFY, {"code": code_at(secret=secret)})["Location"] == LOGIN
    assert client.get(ADMINISTRATION).status_code == 200
    actor = sessions_context(client, administrator)
    assert actor is not None
    services.grant_role(
        actor=actor,
        user=target,
        role=Role.READER,
        reason="TEST grant by the first Administrator",
    )
    assert selectors.roles_of(target) == {Role.READER}

    # 4. Signed in, the password alone still gives the account no other device.
    response = client.post(ENROL, {"password": password})
    assert response.status_code == 409
    assert b"<code>" not in response.content

    # 5. Signing out ends it.
    client.post(LOGOUT)
    assert client.get(ADMINISTRATION).status_code == 403
    assert _events() == [
        "mfa_enrollment_succeeded",
        "mfa_challenge_issued",
        "mfa_verification_failed",
        "mfa_verification_succeeded",
        "login_success",
        "logout",
    ]


def sessions_context(client: Client, user: User) -> selectors.AuthenticationContext | None:
    """Return the context the client's session gives the user, as the middleware builds it."""
    request = HttpRequest()
    request.user = user
    request.session = client.session
    return sessions.authentication_context(request)
