"""Approval of two-step verification over HTTP (ADR-0014).

A Reviewer or Administrator account asks for two-step verification and an
Administrator who is signed in with a trusted second factor decides. Nothing
stands in for TOTP: secrets are read from the pages, and codes are computed
from them as an authenticator application would.
"""

import base64
import logging
import re
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.contrib.sessions.models import Session
from django.http import HttpRequest, HttpResponse
from django.test import Client
from django.urls import include, path

from caipo.accounts import selectors
from caipo.accounts.models import AuthenticationEvent, TotpDevice, TotpDeviceState, User
from caipo.accounts.selectors import MfaState, Permission, Role
from caipo.accounts.tests.fixtures import (
    Clock,
    UserFactory,
    code_at,
    enrolled_device,
    logged,
)
from caipo.web import second_factor, second_factor_requests, sessions
from caipo.web.access import declared_access, requires
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
REPLACE = "/account/second-factor/replace/"
REQUESTS = "/administration/second-factor-requests/"
ADMINISTRATION = "/administration/"
REVIEW = "/review/"

STEP = timedelta(seconds=30)
CONFIRMED = {"confirmed": "on"}


@requires(Permission.ROLES_MANAGE)
def administration_view(request: HttpRequest) -> HttpResponse:
    return HttpResponse("TEST administration")


@requires(Permission.RESEARCH_REVIEW)
def review_view(request: HttpRequest) -> HttpResponse:
    return HttpResponse("TEST review")


# The real routes, plus one view for each privileged permission. The real
# routes come first, so that the requests page is the real one.
urlpatterns = [
    path("", include("caipo.web.urls")),
    path("administration/", administration_view),
    path("review/", review_view),
]


def _approve_url(number: int) -> str:
    return f"{REQUESTS}{number}/approve/"


def _reject_url(number: int) -> str:
    return f"{REQUESTS}{number}/reject/"


@pytest.fixture
def account(user_with_roles: UserFactory) -> AccountFactory:
    """Return a factory for synthetic users with the given roles and a known password."""

    def make(*roles: Role) -> User:
        user = user_with_roles(*roles)
        user.set_password(PASSWORD)
        user.save()
        return user

    return make


@pytest.fixture
def approver(account: AccountFactory) -> Client:
    """Return a client signed in as an Administrator with a trusted second factor."""
    return verified(Client(), account(Role.ADMINISTRATOR))


def _events() -> list[str]:
    return list(AuthenticationEvent.objects.order_by("id").values_list("event_type", flat=True))


def _shown_secret(response: Any) -> bytes:
    """Read the key off the page, as the person enrolling would."""
    (key,) = re.findall(r"<code>([A-Z2-7]{32})</code>", response.content.decode())
    return base64.b32decode(key)


def _shown_number(response: Any) -> int:
    """Read the request number off the page, as the person enrolling would."""
    (number,) = re.findall(r"request number is <strong>(\d+)</strong>", response.content.decode())
    return int(number)


def _request(client: Client) -> tuple[bytes, int]:
    """Ask for two-step verification through the page; return the secret and the number."""
    response = client.post(ENROL, {"password": PASSWORD})
    assert response.status_code == 200
    return _shown_secret(response), _shown_number(response)


def _device(user: User) -> TotpDevice:
    return TotpDevice.objects.get(user=user)


# --- The compromised password, over HTTP ------------------------------------------


@pytest.mark.parametrize(
    ("role", "page"), [(Role.ADMINISTRATOR, ADMINISTRATION), (Role.REVIEWER, REVIEW)]
)
def test_a_compromised_password_opens_no_privileged_page(
    client: Client, account: AccountFactory, clock: Clock, role: Role, page: str
) -> None:
    victim = account(role)

    # The attacker signs in with the password they know.
    assert client.post(LOGIN, {"email": victim.email, "password": PASSWORD})["Location"] == LOGIN
    assert client.get(page).status_code == 403

    # They get a key of their own, and are told it needs approval.
    response = client.post(ENROL, {"password": PASSWORD})
    secret, number = _shown_secret(response), _shown_number(response)
    assert selectors.mfa_state_of(victim) == MfaState.PENDING_APPROVAL

    # The code for that key is not accepted, and nothing opens.
    for _ in range(2):
        refused = client.post(CONFIRM, {"code": code_at(secret=secret)})
        assert refused.status_code == 409
        assert client.get(page).status_code == 403
        clock(STEP)

    # They cannot see or decide the request themselves.
    assert client.get(REQUESTS).status_code == 403
    assert client.post(_approve_url(number), CONFIRMED).status_code == 403
    assert client.post(_reject_url(number)).status_code == 403

    # Nor by writing into the request what the session does not hold.
    claims = {"role": "administrator", "mfa_verified": "true", "approved": "true", **CONFIRMED}
    assert client.post(f"{_approve_url(number)}?mfa_verified=true", claims).status_code == 403
    assert (
        client.post(
            _approve_url(number),
            claims,
            HTTP_X_MFA_VERIFIED="true",
            HTTP_X_ROLE="administrator",
            HTTP_X_FORWARDED_USER="administrator",
        ).status_code
        == 403
    )
    client.cookies["mfa_verified"] = "true"
    client.cookies["role"] = "administrator"
    assert client.post(_approve_url(number), CONFIRMED).status_code == 403
    assert client.get(page).status_code == 403

    device = _device(victim)
    assert device.state == TotpDeviceState.PENDING_APPROVAL
    assert device.approved_at is None
    assert _events() == ["login_success", "mfa_enrollment_started"]


def test_noting_the_pending_request_in_the_session_proves_nothing(
    client: Client, account: AccountFactory
) -> None:
    user = account(Role.ADMINISTRATOR)
    signed_in(client, user)
    _, number = _request(client)
    session = client.session
    session[sessions.VERIFIED_DEVICE_KEY] = number
    session.save()

    assert client.get(ADMINISTRATION).status_code == 403
    assert client.get(REQUESTS).status_code == 403
    assert client.post(_approve_url(number), CONFIRMED).status_code == 403
    assert _device(user).state == TotpDeviceState.PENDING_APPROVAL


# --- What the person asking sees --------------------------------------------------


@pytest.mark.parametrize("role", [Role.REVIEWER, Role.ADMINISTRATOR])
def test_a_privileged_account_is_shown_its_key_once_and_a_request_number(
    client: Client, account: AccountFactory, role: Role
) -> None:
    user = account(role)
    signed_in(client, user)

    response = client.post(ENROL, {"password": PASSWORD})

    body = response.content.decode()
    assert _shown_number(response) == _device(user).pk
    assert "must be approved by an Administrator" in body
    # No form for a code is offered while the request awaits approval.
    assert CONFIRM not in body
    key = base64.b32encode(_shown_secret(response)).decode()
    again = client.get(OVERVIEW).content.decode()
    assert key not in again
    assert "otpauth" not in again
    assert f"<strong>{_device(user).pk}</strong>" in again
    assert "no-store" in response["Cache-Control"]


@pytest.mark.parametrize("role", [Role.READER, Role.RESEARCHER])
def test_an_account_without_a_privileged_role_is_asked_for_its_code_at_once(
    client: Client, account: AccountFactory, role: Role
) -> None:
    signed_in(client, account(role))

    response = client.post(ENROL, {"password": PASSWORD})

    body = response.content.decode()
    assert "request number" not in body
    assert CONFIRM in body
    assert (
        client.post(CONFIRM, {"code": code_at(secret=_shown_secret(response))}).status_code == 302
    )


def test_after_the_approval_the_code_turns_it_on_and_opens_the_privileged_pages(
    client: Client, account: AccountFactory, approver: Client
) -> None:
    user = account(Role.ADMINISTRATOR)
    signed_in(client, user)
    secret, number = _request(client)

    assert approver.post(_approve_url(number), CONFIRMED)["Location"] == REQUESTS

    # Approved, and still nothing until the code is given.
    assert client.get(ADMINISTRATION).status_code == 403
    assert CONFIRM in client.get(OVERVIEW).content.decode()
    key_before = client.session.session_key
    assert client.post(CONFIRM, {"code": code_at(secret=secret)})["Location"] == OVERVIEW
    assert client.session.session_key != key_before
    assert client.get(ADMINISTRATION).status_code == 200
    assert client.get(REQUESTS).status_code == 200
    assert _events() == [
        "mfa_enrollment_started",
        "mfa_enrollment_approved",
        "mfa_enrollment_succeeded",
    ]


def test_an_approval_raises_no_session(
    client: Client, account: AccountFactory, approver: Client
) -> None:
    """The approval lets a code be accepted. It verifies nothing for anybody."""
    user = account(Role.REVIEWER)
    signed_in(client, user)
    _, number = _request(client)
    other = signed_in(Client(), user)

    approver.post(_approve_url(number), CONFIRMED)

    for session_of_the_account in (client, other):
        assert session_of_the_account.get(REVIEW).status_code == 403
        assert sessions.VERIFIED_DEVICE_KEY not in session_of_the_account.session


# --- Who reaches the pages -------------------------------------------------------


def _visitor(kind: str, account: AccountFactory) -> Client:
    client = Client()
    if kind == "anonymous":
        return client
    if kind == "administrator-on-a-password":
        user = account(Role.ADMINISTRATOR)
        enrolled_device(user)
        return signed_in(client, user)
    if kind == "administrator-with-an-unapproved-device":
        user = account(Role.ADMINISTRATOR)
        device = enrolled_device(user, trusted=False)
        signed_in(client, user)
        session = client.session
        session[sessions.VERIFIED_DEVICE_KEY] = device.pk
        session.save()
        return client
    if kind == "administrator-not-enrolled":
        return signed_in(client, account(Role.ADMINISTRATOR))
    role = {"reviewer": Role.REVIEWER, "researcher": Role.RESEARCHER, "reader": Role.READER}[kind]
    return verified(client, account(role))


VISITORS = [
    "anonymous",
    "administrator-on-a-password",
    "administrator-with-an-unapproved-device",
    "administrator-not-enrolled",
    "reviewer",
    "researcher",
    "reader",
]


def test_the_request_pages_declare_the_permission_to_approve() -> None:
    """The HTTP boundary names the same permission the services require."""
    for view in (
        second_factor_requests.overview,
        second_factor_requests.approve,
        second_factor_requests.reject,
    ):
        assert declared_access(view) == Permission.MFA_ENROLLMENT_APPROVE
    assert declared_access(second_factor.replace) == Permission.MFA_MANAGE_OWN


@pytest.mark.parametrize("kind", VISITORS)
def test_only_a_verified_administrator_reaches_the_requests(
    account: AccountFactory, kind: str
) -> None:
    requester = account(Role.REVIEWER)
    _, number = _request(signed_in(Client(), requester))
    visitor = _visitor(kind, account)
    before = TotpDevice.objects.values().get(pk=number)

    listing = visitor.get(REQUESTS)
    approval = visitor.post(_approve_url(number), CONFIRMED)
    rejection = visitor.post(_reject_url(number))

    assert (listing.status_code, approval.status_code, rejection.status_code) == (403, 403, 403)
    assert requester.email not in listing.content.decode()
    assert TotpDevice.objects.values().get(pk=number) == before
    assert "mfa_enrollment_approved" not in _events()
    assert "mfa_enrollment_rejected" not in _events()


def test_a_verified_administrator_sees_the_requests_of_others_and_no_key(
    account: AccountFactory, approver: Client
) -> None:
    requester = account(Role.REVIEWER)
    secret, number = _request(signed_in(Client(), requester))
    reader = account(Role.READER)
    signed_in(Client(), reader).post(ENROL, {"password": PASSWORD})

    response = approver.get(REQUESTS)

    body = response.content.decode()
    assert response.status_code == 200
    assert "no-store" in response["Cache-Control"]
    assert f"Request {number}" in body
    assert requester.email in body
    # What needs no approval is not listed.
    assert reader.email not in body
    assert base64.b32encode(secret).decode() not in body
    assert "otpauth" not in body


def test_the_sign_in_page_links_to_the_requests_only_for_a_verified_administrator(
    account: AccountFactory, approver: Client
) -> None:
    assert REQUESTS in approver.get(LOGIN).content.decode()

    for kind in VISITORS:
        assert REQUESTS not in _visitor(kind, account).get(LOGIN).content.decode(), kind


# --- How a decision is made ---------------------------------------------------------


@pytest.mark.parametrize("decision", ["approve", "reject"])
@pytest.mark.parametrize("method", ["get", "head", "put", "patch", "delete"])
def test_a_decision_is_made_by_post_only(
    account: AccountFactory, approver: Client, decision: str, method: str
) -> None:
    requester = account(Role.REVIEWER)
    _, number = _request(signed_in(Client(), requester))
    url = _approve_url(number) if decision == "approve" else _reject_url(number)

    response = getattr(approver, method)(f"{url}?confirmed=on")

    assert response.status_code == 405
    assert _device(requester).state == TotpDeviceState.PENDING_APPROVAL


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_a_decision_without_a_csrf_token_is_refused(account: AccountFactory, decision: str) -> None:
    requester = account(Role.REVIEWER)
    _, number = _request(signed_in(Client(), requester))
    approver = verified(Client(enforce_csrf_checks=True), account(Role.ADMINISTRATOR))
    url = _approve_url(number) if decision == "approve" else _reject_url(number)

    assert approver.post(url, CONFIRMED).status_code == 403
    assert _device(requester).state == TotpDeviceState.PENDING_APPROVAL

    approver.get(REQUESTS)
    token = approver.cookies["csrftoken"].value
    accepted = approver.post(url, {**CONFIRMED, "csrfmiddlewaretoken": token})
    assert accepted.status_code == 302


@pytest.mark.parametrize(
    "data",
    [{}, {"confirmed": ""}, {"confirmed": "false"}, {"confirmed": "0"}, {"approve": "on"}],
    ids=["nothing", "empty", "false", "zero", "another-field"],
)
def test_an_approval_without_the_explicit_confirmation_approves_nothing(
    account: AccountFactory, approver: Client, data: dict[str, str]
) -> None:
    requester = account(Role.ADMINISTRATOR)
    _, number = _request(signed_in(Client(), requester))

    response = approver.post(_approve_url(number), data)

    assert response.status_code == 400
    assert "Nothing was approved" in response.content.decode()
    device = _device(requester)
    assert (device.state, device.approved_at) == (TotpDeviceState.PENDING_APPROVAL, None)
    assert _events() == ["mfa_enrollment_started"]


def test_an_approval_records_the_administrator_from_the_session_and_nothing_from_the_form(
    account: AccountFactory,
) -> None:
    requester = account(Role.REVIEWER)
    _, number = _request(signed_in(Client(), requester))
    administrator = account(Role.ADMINISTRATOR)
    approver = verified(Client(), administrator)
    claims = {"actor": str(requester.pk), "approved_by": str(requester.pk), "user": "1"}

    approver.post(_approve_url(number), {**CONFIRMED, **claims})

    assert _device(requester).approved_by == administrator
    event = AuthenticationEvent.objects.get(event_type="mfa_enrollment_approved")
    assert (event.user, event.actor) == (requester, administrator)


def test_a_rejection_discards_the_request(
    client: Client, account: AccountFactory, approver: Client
) -> None:
    requester = account(Role.REVIEWER)
    signed_in(client, requester)
    secret, number = _request(client)

    assert approver.post(_reject_url(number))["Location"] == REQUESTS

    assert not TotpDevice.objects.filter(user=requester).exists()
    assert client.post(CONFIRM, {"code": code_at(secret=secret)}).status_code == 409
    assert "Two-step verification is off" in client.get(OVERVIEW).content.decode()
    assert _events()[-1] == "mfa_enrollment_rejected"


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_a_request_that_was_replaced_or_does_not_exist_cannot_be_decided(
    client: Client, account: AccountFactory, approver: Client, decision: str
) -> None:
    requester = account(Role.ADMINISTRATOR)
    signed_in(client, requester)
    _, old = _request(client)
    _, new = _request(client)
    url = _approve_url if decision == "approve" else _reject_url

    for number in (old, new + 1000):
        response = approver.post(url(number), CONFIRMED)
        assert response.status_code == 409
        assert "no longer awaits a decision" in response.content.decode()

    device = _device(requester)
    assert (device.pk, device.state) == (new, TotpDeviceState.PENDING_APPROVAL)


def test_an_administrator_cannot_decide_on_their_own_request_from_another_session(
    account: AccountFactory,
) -> None:
    """A second session of the same account cannot be the trusted Administrator."""
    administrator = account(Role.ADMINISTRATOR)
    first = signed_in(Client(), administrator)
    _, number = _request(first)
    second = signed_in(Client(), administrator)
    session = second.session
    session[sessions.VERIFIED_DEVICE_KEY] = number
    session.save()

    for visitor in (first, second):
        assert visitor.post(_approve_url(number), CONFIRMED).status_code == 403
        assert visitor.post(_reject_url(number)).status_code == 403

    assert _device(administrator).state == TotpDeviceState.PENDING_APPROVAL


# --- Replacing an active device ----------------------------------------------------


def _replace(client: Client, password: str = PASSWORD, code: str | None = None) -> Any:
    return client.post(
        REPLACE,
        {
            "replace-password": password,
            "replace-code": code if code is not None else code_at(),
        },
    )


@pytest.mark.parametrize("method", ["get", "head", "put", "patch", "delete"])
def test_replacing_is_done_by_post_only(
    client: Client, account: AccountFactory, method: str
) -> None:
    user = account(Role.ADMINISTRATOR)
    verified(client, user)

    assert getattr(client, method)(REPLACE).status_code == 405
    assert selectors.mfa_state_of(user) == MfaState.ACTIVE


def test_replacing_without_a_csrf_token_is_refused(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    client = verified(Client(enforce_csrf_checks=True), user)

    assert _replace(client).status_code == 403
    assert selectors.mfa_state_of(user) == MfaState.ACTIVE


@pytest.mark.parametrize(
    "data",
    [
        {"replace-password": PASSWORD},
        {"replace-password": PASSWORD, "replace-code": ""},
        {"replace-password": PASSWORD, "replace-code": "000000"},
        {"replace-password": WRONG, "replace-code": "right"},
        {"replace-code": "right"},
        # The fields of the form that turns it off are not this form's.
        {"password": PASSWORD, "code": "right"},
    ],
    ids=["no-code", "empty-code", "wrong-code", "wrong-password", "no-password", "other-form"],
)
def test_a_device_is_not_replaced_without_the_password_and_a_current_code(
    client: Client, account: AccountFactory, data: dict[str, str]
) -> None:
    user = account(Role.ADMINISTRATOR)
    verified(client, user)
    before = _device(user).pk
    data = {name: code_at() if value == "right" else value for name, value in data.items()}

    response = client.post(REPLACE, data)

    assert response.status_code == 200
    assert b"<code>" not in response.content
    assert _device(user).pk == before
    assert selectors.mfa_state_of(user) == MfaState.ACTIVE
    assert client.get(ADMINISTRATION).status_code == 200
    assert "mfa_device_replaced" not in _events()


def test_a_password_only_session_of_an_enrolled_account_cannot_replace_the_device(
    client: Client, account: AccountFactory
) -> None:
    """A session from before the enrolment, or a stolen one, with the password and no device."""
    user = account(Role.ADMINISTRATOR)
    enrolled_device(user)
    signed_in(client, user)
    before = _device(user).pk

    assert client.post(ENROL, {"password": PASSWORD}).status_code == 409
    assert b"<code>" not in _replace(client, code="000000").content
    assert client.post(REPLACE, {"replace-password": PASSWORD}).status_code == 200

    assert _device(user).pk == before
    assert selectors.mfa_state_of(user) == MfaState.ACTIVE


def test_replacing_with_both_proofs_shows_a_new_key_and_gives_up_the_privileges(
    client: Client, account: AccountFactory, approver: Client, clock: Clock
) -> None:
    user = account(Role.ADMINISTRATOR)
    verified(client, user)
    old = _device(user).pk
    assert client.get(ADMINISTRATION).status_code == 200
    key_before = client.session.session_key

    response = _replace(client)

    assert response.status_code == 200
    secret, number = _shown_secret(response), _shown_number(response)
    assert number != old
    assert not TotpDevice.objects.filter(pk=old).exists()
    assert selectors.mfa_state_of(user) == MfaState.PENDING_APPROVAL
    # The session that held the privilege holds it no longer, under a new key.
    assert client.session.session_key != key_before
    assert not Session.objects.filter(session_key=key_before).exists()
    assert sessions.VERIFIED_DEVICE_KEY not in client.session
    assert client.get(ADMINISTRATION).status_code == 403
    assert _events() == ["mfa_device_replaced", "mfa_enrollment_started"]

    # The new device goes the whole way again: approval, then its code.
    clock(STEP)
    assert client.post(CONFIRM, {"code": code_at(secret=secret)}).status_code == 409
    approver.post(_approve_url(number), CONFIRMED)
    assert client.post(CONFIRM, {"code": code_at(secret=secret)}).status_code == 302
    assert client.get(ADMINISTRATION).status_code == 200


# --- Signing out ----------------------------------------------------------------------


def test_signing_out_leaves_nothing_of_a_request_in_the_browser_and_no_way_back_to_the_key(
    client: Client, account: AccountFactory, approver: Client
) -> None:
    """The request is the account's and waits for a person; the key was shown once."""
    user = account(Role.REVIEWER)
    client.post(LOGIN, {"email": user.email, "password": PASSWORD})
    secret, number = _request(client)
    key = base64.b32encode(secret).decode()
    session_key = client.session.session_key
    stored = Session.objects.get(session_key=session_key).get_decoded()
    assert key not in repr(stored) and str(number) not in repr(stored.keys())

    assert client.post(LOGOUT)["Location"] == LOGIN

    # The session is gone, with everything it held.
    assert not Session.objects.filter(session_key=session_key).exists()
    assert client.get(OVERVIEW).status_code == 403
    assert client.post(CONFIRM, {"code": code_at(secret=secret)}).status_code == 403
    # The request still waits, and still grants nothing to anybody.
    assert _device(user).state == TotpDeviceState.PENDING_APPROVAL
    assert selectors.permissions_of(selectors.authentication_context(user)) == {
        Permission.MFA_MANAGE_OWN
    }

    # Whoever signs in next sees the number and never the key.
    client.post(LOGIN, {"email": user.email, "password": PASSWORD})
    body = client.get(OVERVIEW).content.decode()
    assert f"<strong>{number}</strong>" in body
    assert key not in body and "otpauth" not in body
    assert client.get(REVIEW).status_code == 403

    # After the approval, only the holder of the key can finish.
    approver.post(_approve_url(number), CONFIRMED)
    assert client.post(CONFIRM, {"code": "000000"}).status_code == 200
    assert client.get(REVIEW).status_code == 403
    assert client.post(CONFIRM, {"code": code_at(secret=secret)}).status_code == 302
    assert client.get(REVIEW).status_code == 200


def test_signing_out_ends_what_an_approved_enrolment_gave_the_session(
    client: Client, account: AccountFactory, approver: Client, clock: Clock
) -> None:
    user = account(Role.ADMINISTRATOR)
    signed_in(client, user)
    secret, number = _request(client)
    approver.post(_approve_url(number), CONFIRMED)
    client.post(CONFIRM, {"code": code_at(secret=secret)})
    assert client.get(ADMINISTRATION).status_code == 200

    client.post(LOGOUT)

    assert client.get(ADMINISTRATION).status_code == 403
    clock(STEP)
    # From now on the password alone signs nobody in.
    assert client.post(LOGIN, {"email": user.email, "password": PASSWORD})["Location"] == VERIFY
    assert client.get(ADMINISTRATION).status_code == 403
    assert client.post(VERIFY, {"code": code_at(secret=secret)})["Location"] == LOGIN
    assert client.get(ADMINISTRATION).status_code == 200


# --- What is logged ---------------------------------------------------------------------


def test_no_key_code_or_password_reaches_the_logs_or_a_url_of_the_approval_pages(
    client: Client, account: AccountFactory, approver: Client, caplog: pytest.LogCaptureFixture
) -> None:
    user = account(Role.ADMINISTRATOR)
    signed_in(client, user)

    with caplog.at_level(logging.DEBUG):
        shown = client.post(ENROL, {"password": PASSWORD})
        secret, number = _shown_secret(shown), _shown_number(shown)
        code = code_at(secret=secret)
        refused = client.post(CONFIRM, {"code": code})
        listing = approver.get(REQUESTS)
        approval = approver.post(_approve_url(number), CONFIRMED)
        confirmed = client.post(CONFIRM, {"code": code})

    assert confirmed.status_code == 302
    written = logged(caplog.records)
    key = base64.b32encode(secret).decode()
    for value in (key, secret.hex(), PASSWORD, "otpauth", user.email):
        assert value not in written, value
    assert f" {code} " not in f" {written} "
    for response in (refused, listing, approval, confirmed):
        assert key not in str(response.headers)
        assert key not in response.content.decode()
