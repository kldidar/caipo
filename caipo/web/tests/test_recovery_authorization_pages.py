"""Authorising and rejecting a recovery request over HTTP (ADR-0017).

An Administrator who is signed in with a trusted second factor decides on
another account's request. The sessions here are real ones: what a recovery
does to them is read from the next request each of them makes.
"""

import re
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.core import mail as django_mail
from django.test import Client

from caipo.accounts import services
from caipo.accounts.models import (
    AuthenticationEvent,
    MfaChallenge,
    MfaRecoveryRequest,
    RoleEvent,
    RoleEventType,
    TotpDevice,
    TotpDeviceState,
    User,
)
from caipo.accounts.selectors import Permission, Role
from caipo.accounts.tests.fixtures import (
    Clock,
    UserFactory,
    code_at,
    enrolled_device,
    supporting_account,
)
from caipo.web import recovery_requests
from caipo.web.access import declared_access
from caipo.web.tests.helpers import signed_in, verified

pytestmark = [pytest.mark.services, pytest.mark.django_db]

type AccountFactory = Callable[..., User]

# Visibly synthetic fixture values.
PASSWORD = "TEST-passphrase-for-fixtures-only"
NEW_PASSWORD = "TEST-passphrase-chosen-afterwards"
SOURCE = "203.0.113.10"

LOGIN = "/login/"
VERIFY = "/login/verify/"
RECOVER = "/login/verify/recover/"
# A page that needs a permission every role holds.
OWN_PAGE = "/account/second-factor/"
ENROL = "/account/second-factor/enrol/"
REQUESTS = "/administration/recovery-requests/"
ENROLMENT_REQUESTS = "/administration/second-factor-requests/"

CONFIRMED = {"confirmed": "on"}
UNAVAILABLE = "That request is not available. Nothing was changed."
UNCONFIRMED = "Nothing was authorised."
MINUTE = timedelta(minutes=1)


def _authorize_url(number: int) -> str:
    return f"{REQUESTS}{number}/authorize/"


def _reject_url(number: int) -> str:
    return f"{REQUESTS}{number}/reject/"


@pytest.fixture
def account(user_with_roles: UserFactory) -> AccountFactory:
    """Return a factory for synthetic users with a known password and an active second factor."""

    def make(*roles: Role) -> User:
        user = user_with_roles(*roles)
        user.set_password(PASSWORD)
        user.save()
        enrolled_device(user)
        return user

    return make


@pytest.fixture
def administrator(account: AccountFactory) -> User:
    """Return the Administrator who decides."""
    return account(Role.ADMINISTRATOR)


@pytest.fixture
def decider(administrator: User) -> Client:
    """Return a client signed in as that Administrator with a trusted second factor."""
    return verified(Client(), administrator)


@pytest.fixture
def another(account: AccountFactory) -> User:
    """Return a further Administrator, who is able to act."""
    return account(Role.ADMINISTRATOR)


def _signed_in_with_code(user: User) -> Client:
    """Sign in as the pages do it: the password, then a code from the device."""
    client = Client()
    response = client.post(LOGIN, {"email": user.email, "password": PASSWORD})
    assert response["Location"] == VERIFY
    response = client.post(VERIFY, {"code": code_at()})
    assert response.status_code == 302, response.content
    return client


def _pending(user: User, password: str = PASSWORD) -> Client:
    client = Client()
    response = client.post(LOGIN, {"email": user.email, "password": password})
    assert response["Location"] == VERIFY
    return client


def _asked(user: User, password: str = PASSWORD) -> int:
    """Ask for recovery as the account's owner does, and read the number off the page."""
    response = _pending(user, password).post(RECOVER)
    (number,) = re.findall(r"request number is <strong>(\d+)</strong>", response.content.decode())
    return int(number)


def _recognised(client: Client) -> bool:
    status = client.get(OWN_PAGE).status_code
    assert status in (200, 403)
    return bool(status == 200)


def _reset_password(user: User) -> None:
    services.request_password_reset(
        email=user.email,
        source=SOURCE,
        reset_url=lambda token: f"https://caipo.test/password-reset/confirm/#{token}",
    )
    token = re.findall(r"#(\S+)", str(django_mail.outbox[-1].body))[-1]
    services.reset_password(token=token, password=NEW_PASSWORD, source=SOURCE)


def _revoke(user: User, role: Role) -> None:
    RoleEvent.objects.create(
        user=user,
        role=role,
        event_type=RoleEventType.REVOKED,
        actor=supporting_account("test.seed@caipo.test"),
        reason="TEST fixture",
    )


def _decisions() -> list[tuple[str, int | None, int | None]]:
    return list(
        AuthenticationEvent.objects.filter(
            event_type__in=["mfa_recovery_authorized", "mfa_recovery_rejected"]
        )
        .order_by("id")
        .values_list("event_type", "user_id", "actor_id")
    )


def _answer(response: Any) -> tuple[int, str, list[str], list[tuple[str, str]]]:
    """Return everything an Administrator can observe in a response.

    Two things are left out because they differ between any two responses,
    by design: the CSRF token in the page, which is masked anew each time,
    and the time in the Expires header.
    """
    body = re.sub(
        r'name="csrfmiddlewaretoken" value="[^"]+"',
        'name="csrfmiddlewaretoken" value=""',
        response.content.decode(),
    )
    headers = sorted(
        (name, value)
        for name, value in response.headers.items()
        if name not in ("Content-Length", "Expires")
    )
    return response.status_code, body, sorted(response.cookies.keys()), headers


# --- Who reaches the pages --------------------------------------------------------------


def test_the_three_views_declare_the_permission_to_authorise_recoveries() -> None:
    for view in (recovery_requests.overview, recovery_requests.authorize, recovery_requests.reject):
        assert declared_access(view) == Permission.MFA_RECOVERY_AUTHORIZE


def test_an_administrator_with_a_trusted_second_factor_sees_the_requests(
    account: AccountFactory, administrator: User, decider: Client
) -> None:
    user = account(Role.REVIEWER)
    number = _asked(user)

    response = decider.get(REQUESTS)

    assert response.status_code == 200
    page = response.content.decode()
    assert f"Request {number}" in page
    assert user.email in page
    assert f'action="{_authorize_url(number)}"' in page
    assert f'action="{_reject_url(number)}"' in page
    assert "no-store" in response["Cache-Control"]


def test_the_page_shows_no_request_of_whoever_is_looking(
    administrator: User, decider: Client
) -> None:
    number = _asked(administrator)

    page = decider.get(REQUESTS).content.decode()

    assert f"Request {number}" not in page
    assert "No request awaits a decision." in page


@pytest.mark.parametrize("who", ["anonymous", "password_only", "reviewer", "reader"])
def test_nobody_else_reaches_the_pages_or_decides(
    who: str, account: AccountFactory, administrator: User, another: User
) -> None:
    user = account(Role.REVIEWER)
    number = _asked(user)
    client = Client()
    if who == "password_only":
        signed_in(client, administrator)
    elif who == "reviewer":
        verified(client, account(Role.REVIEWER))
    elif who == "reader":
        verified(client, account(Role.READER))

    assert client.get(REQUESTS).status_code == 403
    assert client.post(_authorize_url(number), CONFIRMED).status_code == 403
    assert client.post(_reject_url(number)).status_code == 403

    assert MfaRecoveryRequest.objects.filter(pk=number).exists()
    assert TotpDevice.objects.filter(user=user, state=TotpDeviceState.ACTIVE).exists()
    assert _decisions() == []


@pytest.mark.parametrize("method", ["get", "put", "delete", "patch"])
def test_a_decision_is_only_made_by_post(
    method: str, account: AccountFactory, decider: Client, another: User
) -> None:
    number = _asked(account(Role.REVIEWER))

    for url in (_authorize_url(number), _reject_url(number)):
        assert getattr(decider, method)(url).status_code == 405

    assert MfaRecoveryRequest.objects.filter(pk=number).exists()
    assert _decisions() == []


def test_a_decision_needs_a_csrf_token(
    account: AccountFactory, administrator: User, another: User
) -> None:
    number = _asked(account(Role.REVIEWER))
    client = verified(Client(enforce_csrf_checks=True), administrator)

    assert client.post(_authorize_url(number), CONFIRMED).status_code == 403
    assert client.post(_reject_url(number)).status_code == 403

    assert MfaRecoveryRequest.objects.filter(pk=number).exists()
    assert _decisions() == []


@pytest.mark.parametrize("sent", [{}, {"confirmed": ""}, {"confirmed": "1"}, {"confirmed": "true"}])
def test_nothing_is_authorised_without_the_ticked_confirmation(
    sent: dict[str, str], account: AccountFactory, decider: Client, another: User
) -> None:
    user = account(Role.REVIEWER)
    number = _asked(user)

    response = decider.post(_authorize_url(number), sent)

    assert response.status_code == 400
    assert UNCONFIRMED in response.content.decode()
    assert MfaRecoveryRequest.objects.filter(pk=number).exists()
    assert TotpDevice.objects.filter(user=user).exists()
    assert _decisions() == []


# --- An authorisation -------------------------------------------------------------------


def test_authorising_revokes_the_device_and_goes_back_to_the_list(
    account: AccountFactory, administrator: User, decider: Client, another: User
) -> None:
    user = account(Role.REVIEWER)
    number = _asked(user)

    response = decider.post(_authorize_url(number), CONFIRMED)

    assert response.status_code == 302
    assert response["Location"] == REQUESTS
    assert not TotpDevice.objects.filter(user=user).exists()
    assert _decisions() == [("mfa_recovery_authorized", user.pk, administrator.pk)]
    assert f"Request {number}" not in decider.get(REQUESTS).content.decode()


def test_nothing_the_browser_sends_names_the_actor_or_the_account(
    account: AccountFactory, administrator: User, decider: Client, another: User
) -> None:
    user, bystander = account(Role.REVIEWER), account(Role.REVIEWER)
    number = _asked(user)
    bystander_number = _asked(bystander)

    decider.post(
        _authorize_url(number) + f"?number={bystander_number}&user={bystander.pk}",
        {
            **CONFIRMED,
            "number": str(bystander_number),
            "user": str(bystander.pk),
            "actor": str(another.pk),
            "reason": "TEST free text that is stored nowhere",
        },
    )

    # The number in the path and the account of the session, and nothing else.
    assert _decisions() == [("mfa_recovery_authorized", user.pk, administrator.pk)]
    assert TotpDevice.objects.filter(user=bystander).exists()
    assert MfaRecoveryRequest.objects.get().pk == bystander_number
    assert "TEST free text" not in repr(list(AuthenticationEvent.objects.values()))


def test_an_administrator_cannot_authorise_or_reject_their_own_request(
    administrator: User, decider: Client, another: User, account: AccountFactory
) -> None:
    account(Role.ADMINISTRATOR)
    number = _asked(administrator)

    assert decider.post(_authorize_url(number), CONFIRMED).status_code == 403
    assert decider.post(_reject_url(number)).status_code == 403

    assert MfaRecoveryRequest.objects.filter(pk=number).exists()
    assert TotpDevice.objects.filter(user=administrator).exists()
    assert _decisions() == []
    assert _recognised(decider) is True


# --- What a recovery does to sessions (point 46) ----------------------------------------


def test_every_session_of_the_account_fails_on_its_next_request(
    account: AccountFactory, decider: Client, another: User
) -> None:
    user = account(Role.REVIEWER)
    with_code = _signed_in_with_code(user)
    elsewhere = verified(Client(), user)
    on_a_password = signed_in(Client(), user)
    sessions = (with_code, elsewhere, on_a_password)
    assert all(_recognised(client) for client in sessions)
    number = _asked(user)

    assert decider.post(_authorize_url(number), CONFIRMED).status_code == 302

    assert [_recognised(client) for client in sessions] == [False, False, False]
    # And again: a session that was ended does not come back.
    assert [_recognised(client) for client in sessions] == [False, False, False]


def test_the_password_is_unchanged_and_a_new_sign_in_works(
    account: AccountFactory, decider: Client, another: User
) -> None:
    user = account(Role.REVIEWER)
    before = User.objects.get(pk=user.pk).password
    decider.post(_authorize_url(_asked(user)), CONFIRMED)

    assert User.objects.get(pk=user.pk).password == before
    client = Client()
    response = client.post(LOGIN, {"email": user.email, "password": PASSWORD})

    # Signed in at once: the account has no second factor to be asked for.
    assert response.status_code == 302
    assert response["Location"] != VERIFY
    assert _recognised(client) is True
    # On a password alone, which opens the account's own second factor and
    # nothing that the role would.
    assert client.get(REQUESTS).status_code == 403
    assert _recognised(client) is True


def test_a_session_made_after_the_recovery_survives_and_one_made_before_does_not(
    account: AccountFactory, decider: Client, another: User
) -> None:
    user = account(Role.REVIEWER)
    earlier = _signed_in_with_code(user)
    decider.post(_authorize_url(_asked(user)), CONFIRMED)

    later = Client()
    later.post(LOGIN, {"email": user.email, "password": PASSWORD})

    assert _recognised(later) is True
    assert _recognised(earlier) is False
    assert User.objects.get(pk=user.pk).session_epoch == 1


def test_no_other_account_loses_a_session(
    account: AccountFactory, decider: Client, another: User
) -> None:
    user, bystander = account(Role.REVIEWER), account(Role.REVIEWER)
    of_bystander = _signed_in_with_code(bystander)
    of_another = verified(Client(), another)
    number = _asked(user)

    decider.post(_authorize_url(number), CONFIRMED)

    assert _recognised(of_bystander) is True
    assert of_another.get(REQUESTS).status_code == 200
    # The Administrator who authorised is still signed in, and still verified.
    assert decider.get(REQUESTS).status_code == 200
    assert User.objects.exclude(pk=user.pk).filter(session_epoch__gt=0).count() == 0


def test_a_sign_in_that_awaited_its_code_cannot_be_completed_afterwards(
    account: AccountFactory, decider: Client, another: User
) -> None:
    user = account(Role.REVIEWER)
    number = _asked(user)
    pending = _pending(user)
    assert MfaChallenge.objects.filter(user=user).exists()

    decider.post(_authorize_url(number), CONFIRMED)

    response = pending.post(VERIFY, {"code": code_at()})
    assert response.status_code != 302
    assert _recognised(pending) is False
    assert not AuthenticationEvent.objects.filter(user=user, event_type="login_success").exists()


def test_an_authorisation_that_fails_part_way_ends_no_session(
    account: AccountFactory,
    decider: Client,
    another: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = account(Role.REVIEWER)
    session = _signed_in_with_code(user)
    number = _asked(user)
    pending = _pending(user)

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("TEST fault after every other step of the finalisation")

    with monkeypatch.context() as patched:
        patched.setattr(services, "_record", fail)
        with pytest.raises(RuntimeError, match="TEST fault"):
            decider.post(_authorize_url(number), CONFIRMED)

    # Everything is as it was before the attempt.
    assert _recognised(session) is True
    assert User.objects.get(pk=user.pk).session_epoch == 0
    assert TotpDevice.objects.filter(user=user, state=TotpDeviceState.ACTIVE).exists()
    assert MfaRecoveryRequest.objects.filter(pk=number).exists()
    assert MfaChallenge.objects.filter(user=user).exists()
    assert _decisions() == []
    assert pending.get(VERIFY).status_code == 200
    # And the same request can still be authorised.
    assert decider.post(_authorize_url(number), CONFIRMED).status_code == 302
    assert _recognised(session) is False


# --- A rejection ------------------------------------------------------------------------


def test_rejecting_removes_the_request_and_leaves_the_account_as_it_was(
    account: AccountFactory, administrator: User, decider: Client
) -> None:
    user = account(Role.REVIEWER)
    session = _signed_in_with_code(user)
    number = _asked(user)
    before = User.objects.filter(pk=user.pk).values().get()

    response = decider.post(_reject_url(number))

    assert response.status_code == 302
    assert response["Location"] == REQUESTS
    assert not MfaRecoveryRequest.objects.exists()
    assert _decisions() == [("mfa_recovery_rejected", user.pk, administrator.pk)]
    assert User.objects.filter(pk=user.pk).values().get() == before
    assert TotpDevice.objects.filter(user=user, state=TotpDeviceState.ACTIVE).exists()
    assert _recognised(session) is True
    # The account may ask again, and gets another number.
    assert _asked(user) != number


# --- One answer for every decision that is not made -------------------------------------


def test_every_reason_gets_the_same_answer_and_none_is_shown(
    account: AccountFactory, administrator: User, decider: Client, clock: Clock
) -> None:
    answers = []

    # No other Administrator exists yet.
    alone = account(Role.REVIEWER)
    number = _asked(alone)
    answers.append(decider.post(_authorize_url(number), CONFIRMED))
    account(Role.ADMINISTRATOR)

    answers.append(decider.post(_authorize_url(number + 1000), CONFIRMED))

    ineligible = account(Role.REVIEWER)
    number = _asked(ineligible)
    _revoke(ineligible, Role.REVIEWER)
    answers.append(decider.post(_authorize_url(number), CONFIRMED))

    reset_after = account(Role.REVIEWER)
    number = _asked(reset_after)
    clock(MINUTE)
    _reset_password(reset_after)
    answers.append(decider.post(_authorize_url(number), CONFIRMED))

    reset_before = account(Role.REVIEWER)
    _reset_password(reset_before)
    clock(MINUTE)
    number = _asked(reset_before, NEW_PASSWORD)
    answers.append(decider.post(_authorize_url(number), CONFIRMED))

    decided = account(Role.REVIEWER)
    number = _asked(decided)
    assert decider.post(_reject_url(number)).status_code == 302
    answers.append(decider.post(_authorize_url(number), CONFIRMED))
    answers.append(decider.post(_reject_url(number)))

    lapsed = account(Role.REVIEWER)
    number = _asked(lapsed)
    clock(timedelta(minutes=30))
    answers.append(decider.post(_authorize_url(number), CONFIRMED))
    answers.append(decider.post(_reject_url(number)))

    observed = [_answer(response) for response in answers]
    assert len(observed) == 9
    assert all(answer == observed[0] for answer in observed)
    status, page, _cookies, _headers = observed[0]
    assert status == 409
    assert UNAVAILABLE in page
    for word in ("lapsed", "expired", "reset", "wait", "hours", "eligible", "Administrator"):
        assert word not in page, word
    for user in (alone, ineligible, reset_after, reset_before, decided, lapsed):
        assert user.email not in page
    # Nothing was decided by any of them.
    assert _decisions() == [("mfa_recovery_rejected", decided.pk, administrator.pk)]
    assert not AuthenticationEvent.objects.filter(event_type="mfa_recovery_failed").exists()


def test_the_answer_holds_no_list_of_requests(
    account: AccountFactory, decider: Client, another: User
) -> None:
    waiting = account(Role.REVIEWER)
    waiting_number = _asked(waiting)

    response = decider.post(_authorize_url(waiting_number + 1000), CONFIRMED)

    page = response.content.decode()
    assert response.status_code == 409
    assert f"Request {waiting_number}" not in page
    assert waiting.email not in page
    assert "no-store" in response["Cache-Control"]


# --- The Administrator who authorised, and the enrolment that follows (point 37) --------


def test_the_authoriser_is_refused_the_approval_and_another_administrator_gives_it(
    account: AccountFactory, administrator: User, decider: Client, another: User
) -> None:
    user = account(Role.REVIEWER)
    decider.post(_authorize_url(_asked(user)), CONFIRMED)
    owner = Client()
    owner.post(LOGIN, {"email": user.email, "password": PASSWORD})
    response = owner.post(ENROL, {"password": PASSWORD})
    (number,) = re.findall(r"request number is <strong>(\d+)</strong>", response.content.decode())
    approve = f"{ENROLMENT_REQUESTS}{number}/approve/"

    refused = decider.post(approve, CONFIRMED)

    assert refused.status_code == 403
    device = TotpDevice.objects.get(user=user)
    assert device.state == TotpDeviceState.PENDING_APPROVAL
    assert device.approved_by is None

    given = verified(Client(), another).post(approve, CONFIRMED)

    assert given.status_code == 302
    device.refresh_from_db()
    assert device.state == TotpDeviceState.PENDING_VERIFICATION
    assert device.approved_by == another
