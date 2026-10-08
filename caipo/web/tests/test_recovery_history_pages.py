"""The pages that show the history of recoveries, and the notice on the signed-in page
(ADR-0017 point 78).

Two read-only pages: an account's own history, reached on its password alone,
and every account's, for an Administrator verified with a trusted second
factor. The sessions here are real ones.
"""

import re
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.conf import LazySettings
from django.core import mail as django_mail
from django.db import connection
from django.test import Client
from django.utils import timezone

from caipo.accounts import selectors, services
from caipo.accounts.models import (
    AccountEvent,
    AccountStatus,
    AuthenticationEvent,
    AuthenticationEventType,
    BreakGlassAction,
    MfaRecoveryRequest,
    RoleEvent,
    TotpDevice,
    User,
)
from caipo.accounts.selectors import Permission, Role
from caipo.accounts.services import BreakGlassOutcome
from caipo.accounts.tests.fixtures import UserFactory, enrolled_device
from caipo.web import recovery_history
from caipo.web.access import declared_access
from caipo.web.tests.helpers import signed_in, verified

pytestmark = [pytest.mark.services, pytest.mark.django_db]

type AccountFactory = Callable[..., User]

# Visibly synthetic fixture values.
PASSWORD = "TEST-passphrase-for-fixtures-only"
IDENTIFIER_KEY = "TEST-identifier-key-never-shown"
SOURCE_KEY = "TEST-source-key-never-shown"
CORRELATION_ID = "TESTcorrelationidnevershown"

LOGIN = "/login/"
VERIFY = "/login/verify/"
RECOVER = "/login/verify/recover/"
OWN = "/account/second-factor/history/"
EVERY = "/administration/recoveries/"
REQUESTS = "/administration/recovery-requests/"
ENROL = "/account/second-factor/enrol/"

CONFIRMED = {"confirmed": "on"}
AT_SERVER = "Performed at the server's terminal. No account of this site acted"
NOTICE = "was revoked through recovery at"

REQUESTED = AuthenticationEventType.MFA_RECOVERY_REQUESTED
REJECTED = AuthenticationEventType.MFA_RECOVERY_REJECTED
AUTHORIZED = AuthenticationEventType.MFA_RECOVERY_AUTHORIZED
COMPLETED = AuthenticationEventType.MFA_RECOVERY_COMPLETED
BREAK_GLASS = AuthenticationEventType.MFA_RECOVERY_BREAK_GLASS
APPROVED = AuthenticationEventType.MFA_ENROLLMENT_APPROVED


@pytest.fixture
def account(user_with_roles: UserFactory) -> AccountFactory:
    """Return a factory for synthetic users with a known password and an active second factor."""

    def make(*roles: Role, device: bool = True) -> User:
        user = user_with_roles(*roles)
        user.set_password(PASSWORD)
        user.save()
        if device:
            enrolled_device(user)
        return user

    return make


@pytest.fixture
def owner(account: AccountFactory) -> User:
    """Return the account whose history is read. It has no second factor."""
    return account(Role.REVIEWER, device=False)


@pytest.fixture
def administrator(account: AccountFactory) -> User:
    return account(Role.ADMINISTRATOR)


def _event(
    event_type: str, user: User | None, *, actor: User | None = None, action: str = ""
) -> AuthenticationEvent:
    """Write one event straight into the table, with every column that is never shown filled."""
    return AuthenticationEvent.objects.create(
        event_type=event_type,
        user=user,
        actor=actor,
        identifier_key=IDENTIFIER_KEY,
        source_key="" if event_type == BREAK_GLASS else SOURCE_KEY,
        correlation_id=CORRELATION_ID,
        break_glass_action=action,
    )


def _every_step(user: User, actor: User) -> list[AuthenticationEvent]:
    """Record one of each step that is shown, as a recovery and its sequel would."""
    return [
        _event(REQUESTED, user),
        _event(REJECTED, user, actor=actor),
        _event(AUTHORIZED, user, actor=actor),
        _event(APPROVED, user, actor=actor),
        _event(COMPLETED, user),
        _event(BREAK_GLASS, user, action=BreakGlassAction.REVOKE_DEVICE),
        _event(BREAK_GLASS, user, action=BreakGlassAction.APPROVE_ENROLLMENT),
    ]


def _entries(response: Any) -> list[str]:
    """Return the text of each step a page lists, in the order of the page."""
    assert response.status_code == 200
    items = re.findall(r"<li>(.*?)</li>", response.content.decode(), flags=re.DOTALL)
    return [" ".join(item.split()) for item in items]


def _distinctive_identifiers() -> None:
    """Make the next event and the next request get identifiers that occur nowhere by chance."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence('accounts_authenticationevent', 'id'), 918273640)"
        )
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence('accounts_mfarecoveryrequest', 'id'), 827364510)"
        )


def _password_sign_in(user: User) -> Client:
    """Sign in as the pages do it, for an account with no second factor."""
    client = Client()
    response = client.post(LOGIN, {"email": user.email, "password": PASSWORD})
    assert response.status_code == 302 and response["Location"] == LOGIN, response.content
    return client


def _asked(user: User) -> int:
    """Ask for recovery as the account's owner does, and read the number off the page."""
    client = Client()
    assert client.post(LOGIN, {"email": user.email, "password": PASSWORD})["Location"] == VERIFY
    response = client.post(RECOVER)
    (number,) = re.findall(r"request number is <strong>(\d+)</strong>", response.content.decode())
    return int(number)


def _counts() -> tuple[int, ...]:
    return (
        AuthenticationEvent.objects.count(),
        AccountEvent.objects.count(),
        RoleEvent.objects.count(),
        MfaRecoveryRequest.objects.count(),
        TotpDevice.objects.count(),
        User.objects.count(),
    )


# --- Who reaches the account's own page -------------------------------------------------


def test_the_two_views_declare_their_permissions() -> None:
    assert declared_access(recovery_history.own) == Permission.MFA_MANAGE_OWN
    assert declared_access(recovery_history.every_account) == Permission.MFA_RECOVERY_AUTHORIZE


def test_an_anonymous_visitor_is_refused_both_pages(owner: User) -> None:
    _event(REQUESTED, owner)

    for url in (OWN, EVERY):
        response = Client().get(url)
        assert response.status_code == 403
        assert owner.email not in response.content.decode()


@pytest.mark.parametrize("role", list(Role))
def test_every_role_reaches_its_own_history_on_its_password_alone(
    role: Role, account: AccountFactory
) -> None:
    user = account(role, device=False)
    _event(REQUESTED, user)

    response = signed_in(Client(), user).get(OWN)

    assert _entries(response) == [f"{_time(user)}: Recovery requested."]
    assert "no-store" in response["Cache-Control"]


def _time(user: User) -> str:
    """Return the one event of the user as the page writes it: its time, twice."""
    moment = AuthenticationEvent.objects.get(user=user).created_at.isoformat()
    return f'<time datetime="{moment}">{moment}</time>'


def test_an_account_verified_with_its_second_factor_reaches_its_own_history(
    account: AccountFactory,
) -> None:
    user = account(Role.REVIEWER)
    _event(REQUESTED, user)

    assert len(_entries(verified(Client(), user).get(OWN))) == 1


def test_an_account_with_no_role_is_refused(account: AccountFactory) -> None:
    user = account(device=False)

    assert signed_in(Client(), user).get(OWN).status_code == 403


def test_a_disabled_account_is_refused_on_its_next_request(owner: User) -> None:
    client = signed_in(Client(), owner)
    assert client.get(OWN).status_code == 200

    User.objects.filter(pk=owner.pk).update(status=AccountStatus.DISABLED)

    assert client.get(OWN).status_code == 403
    assert client.get(EVERY).status_code == 403


def test_a_session_from_before_the_revocation_is_refused_and_a_new_one_reads_the_history(
    account: AccountFactory, administrator: User
) -> None:
    user = account(Role.REVIEWER)
    account(Role.ADMINISTRATOR)
    before = verified(Client(), user)
    assert before.get(OWN).status_code == 200
    number = _asked(user)

    decider = verified(Client(), administrator)
    assert decider.post(f"{REQUESTS}{number}/authorize/", CONFIRMED).status_code == 302

    # The sessions of the account ended with the device.
    assert before.get(OWN).status_code == 403
    # Signed in again on the password alone, with no second factor to give.
    assert not TotpDevice.objects.filter(user=user).exists()
    entries = _entries(_password_sign_in(user).get(OWN))
    assert len(entries) == 2
    assert "Recovery authorised by an Administrator: the second factor was revoked." in entries[0]
    assert f"Decided by {administrator.email}." in entries[0]
    assert "Recovery requested." in entries[1]


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_the_pages_are_only_read(method: str, owner: User, administrator: User) -> None:
    _event(REQUESTED, owner)
    before = _counts()

    assert getattr(signed_in(Client(), owner), method)(OWN).status_code == 405
    assert getattr(verified(Client(), administrator), method)(EVERY).status_code == 405

    assert _counts() == before


def test_reading_the_pages_changes_nothing(owner: User, administrator: User) -> None:
    _every_step(owner, administrator)
    before = _counts()

    assert signed_in(Client(), owner).get(OWN).status_code == 200
    assert signed_in(Client(), owner).get(LOGIN).status_code == 200
    assert verified(Client(), administrator).get(EVERY).status_code == 200

    assert _counts() == before


def test_the_pages_offer_nothing_to_do(owner: User, administrator: User) -> None:
    _every_step(owner, administrator)

    for client, url in (
        (signed_in(Client(), owner), OWN),
        (verified(Client(), administrator), EVERY),
    ):
        page = client.get(url).content.decode()
        for forbidden in ("<form", "<button", "<input", "csrfmiddlewaretoken", "method="):
            assert forbidden not in page, forbidden


# --- An account reaches no history but its own ------------------------------------------


def test_an_account_is_shown_nothing_of_another_account(
    owner: User, account: AccountFactory, administrator: User
) -> None:
    other = account(Role.REVIEWER, device=False)
    _every_step(other, administrator)
    _event(REQUESTED, owner)

    page = signed_in(Client(), owner).get(OWN)

    assert len(_entries(page)) == 1
    assert other.email not in page.content.decode()
    assert administrator.email not in page.content.decode()


@pytest.mark.parametrize(
    "parameter", ["user", "user_id", "account", "id", "email", "owner", "pk", "of"]
)
def test_nothing_in_the_request_names_another_account(
    parameter: str, owner: User, account: AccountFactory, administrator: User
) -> None:
    other = account(Role.REVIEWER, device=False)
    _every_step(other, administrator)
    client = signed_in(Client(), owner)

    for value in (str(other.pk), other.email):
        page = client.get(OWN, {parameter: value}, headers={"X-User": value})
        assert _entries(page) == ["Nothing is on record."]
        assert other.email not in page.content.decode().replace(f"={other.email}", "")


def test_no_path_names_an_account(owner: User, account: AccountFactory) -> None:
    other = account(Role.REVIEWER, device=False)
    client = signed_in(Client(), owner)

    for path in (f"{OWN}{other.pk}/", f"/account/{other.pk}/second-factor/history/"):
        assert client.get(path).status_code == 404


def test_an_administrator_named_as_the_actor_does_not_see_the_event_on_its_own_page(
    owner: User, administrator: User
) -> None:
    _event(AUTHORIZED, owner, actor=administrator)

    page = signed_in(Client(), administrator).get(OWN)

    assert _entries(page) == ["Nothing is on record."]


# --- Who reaches the page of every account ----------------------------------------------


def test_an_administrator_with_a_trusted_second_factor_sees_every_accounts_recoveries(
    owner: User, account: AccountFactory, administrator: User
) -> None:
    other = account(Role.ADMINISTRATOR)
    _event(REQUESTED, owner)
    _event(REQUESTED, other)
    _event(REQUESTED, administrator)

    response = verified(Client(), administrator).get(EVERY)

    entries = _entries(response)
    assert [re.findall(r"Account (\S+)\.", entry) for entry in entries] == [
        [administrator.email],
        [other.email],
        [owner.email],
    ]
    assert "no-store" in response["Cache-Control"]


@pytest.mark.parametrize(
    "who",
    [
        "administrator on a password alone",
        "administrator with an untrusted second factor",
        "disabled administrator",
        "reviewer",
        "researcher",
        "reader",
        "the owner",
        "no role",
    ],
)
def test_nobody_else_reaches_the_page_of_every_account(
    who: str, owner: User, account: AccountFactory, administrator: User
) -> None:
    _event(REQUESTED, owner)
    client = Client()
    if who == "administrator on a password alone":
        signed_in(client, administrator)
    elif who == "administrator with an untrusted second factor":
        TotpDevice.objects.filter(user=administrator).update(approved_at=None, approved_by=None)
        verified(client, administrator)
    elif who == "disabled administrator":
        verified(client, administrator)
        User.objects.filter(pk=administrator.pk).update(status=AccountStatus.DISABLED)
    elif who == "the owner":
        verified(client, owner)
    elif who == "no role":
        verified(client, account())
    else:
        verified(client, account(Role(who)))

    response = client.get(EVERY)

    assert response.status_code == 403
    assert owner.email not in response.content.decode()
    assert "Recovery requested" not in response.content.decode()


# --- What a page shows of each step -----------------------------------------------------


def test_each_step_is_shown_with_its_time_its_label_and_whoever_decided(
    owner: User, administrator: User
) -> None:
    events = _every_step(owner, administrator)
    times = [
        f'<time datetime="{event.created_at.isoformat()}">{event.created_at.isoformat()}</time>'
        for event in events
    ]
    decided = f" Decided by {administrator.email}."
    at_server = (
        " Performed at the server's terminal. No account of this site acted, and this"
        " site does not record who did."
    )

    def expected(account: str) -> list[str]:
        return [
            f"{times[6]}: Enrolment of the new second factor approved by the emergency"
            f" procedure.{account}{at_server}",
            f"{times[5]}: Second factor revoked by the emergency procedure.{account}{at_server}",
            f"{times[4]}: Recovery completed: the new second factor accepted its first"
            f" code.{account}",
            f"{times[3]}: Enrolment of the new second factor approved by an"
            f" Administrator.{account}{decided}",
            f"{times[2]}: Recovery authorised by an Administrator: the second factor was"
            f" revoked.{account}{decided}",
            f"{times[1]}: Recovery request rejected by an Administrator.{account}{decided}",
            f"{times[0]}: Recovery requested.{account}",
        ]

    assert _entries(signed_in(Client(), owner).get(OWN)) == expected("")
    assert _entries(verified(Client(), administrator).get(EVERY)) == expected(
        f" Account {owner.email}."
    )


def test_a_time_is_shown_in_utc_as_it_was_recorded(owner: User) -> None:
    event = _event(REQUESTED, owner)

    page = signed_in(Client(), owner).get(OWN).content.decode()

    assert event.created_at.utcoffset() is not None
    assert event.created_at.isoformat().endswith("+00:00")
    assert page.count(event.created_at.isoformat()) == 2


def test_a_step_performed_at_the_server_names_no_actor_and_says_that_none_acted(
    owner: User, administrator: User
) -> None:
    _event(AUTHORIZED, owner, actor=administrator)
    _event(BREAK_GLASS, owner, action=BreakGlassAction.REVOKE_DEVICE)
    _event(BREAK_GLASS, owner, action=BreakGlassAction.APPROVE_ENROLLMENT)

    for client, url in (
        (signed_in(Client(), owner), OWN),
        (verified(Client(), administrator), EVERY),
    ):
        at_server_one, at_server_two, decided = _entries(client.get(url))
        for entry in (at_server_one, at_server_two):
            assert AT_SERVER in entry
            assert "Decided by" not in entry
            assert administrator.email not in entry
        assert AT_SERVER not in decided
        assert f"Decided by {administrator.email}." in decided


def test_what_the_account_did_itself_names_no_actor(owner: User, administrator: User) -> None:
    _event(REQUESTED, owner)
    _event(COMPLETED, owner)

    for client, url in (
        (signed_in(Client(), owner), OWN),
        (verified(Client(), administrator), EVERY),
    ):
        for entry in _entries(client.get(url)):
            assert "Decided by" not in entry
            assert AT_SERVER not in entry


def test_what_is_not_a_step_of_a_recovery_is_on_neither_page(
    owner: User, administrator: User
) -> None:
    _event(AUTHORIZED, owner, actor=administrator)
    for event_type in (
        AuthenticationEventType.MFA_RECOVERY_FAILED,
        AuthenticationEventType.MFA_ENROLLMENT_STARTED,
        AuthenticationEventType.MFA_ENROLLMENT_SUCCEEDED,
        AuthenticationEventType.PASSWORD_RESET_REQUESTED,
        AuthenticationEventType.PASSWORD_RESET_SUCCEEDED,
        AuthenticationEventType.PASSWORD_RESET_FAILED,
        AuthenticationEventType.LOGIN_SUCCESS,
        AuthenticationEventType.LOGIN_FAILURE,
        AuthenticationEventType.LOGOUT,
        AuthenticationEventType.MFA_DISABLED,
    ):
        _event(event_type, owner)
    for event_type in (
        AuthenticationEventType.MFA_RECOVERY_FAILED,
        AuthenticationEventType.LOGIN_FAILURE,
        AuthenticationEventType.PASSWORD_RESET_REQUESTED,
        AuthenticationEventType.PASSWORD_RESET_FAILED,
    ):
        _event(event_type, None)

    assert len(_entries(signed_in(Client(), owner).get(OWN))) == 1
    assert len(_entries(verified(Client(), administrator).get(EVERY))) == 1


def test_nothing_internal_and_no_raw_name_is_in_either_page(
    owner: User, administrator: User
) -> None:
    _distinctive_identifiers()
    events = _every_step(owner, administrator)
    assert all(event.pk > 918273640 for event in events)

    for client, url in (
        (signed_in(Client(), owner), OWN),
        (verified(Client(), administrator), EVERY),
    ):
        page = client.get(url).content.decode()
        assert len(_entries(client.get(url))) == 7
        for forbidden in (
            IDENTIFIER_KEY,
            SOURCE_KEY,
            CORRELATION_ID,
            *(str(event.pk) for event in events),
            "9182736",
            *AuthenticationEventType.values,
            *BreakGlassAction.values,
            "mfa_",
            "break_glass",
            "break-glass",
            client.session.session_key or "no session",
            owner.password,
            PASSWORD,
        ):
            assert forbidden not in page, forbidden


def test_no_request_number_secret_or_reason_of_a_real_recovery_is_in_either_page(
    account: AccountFactory, administrator: User, caplog: pytest.LogCaptureFixture
) -> None:
    _distinctive_identifiers()
    user = account(Role.ADMINISTRATOR)
    decider = verified(Client(), administrator)
    # A decision that is not made: its reason is in the log and nowhere else.
    lapsing = _asked(user)
    assert decider.post(f"{REQUESTS}{lapsing}/authorize/", CONFIRMED).status_code == 409
    assert "no_other_administrator" in " ".join(
        str(record.__dict__.get("reason")) for record in caplog.records
    )
    another = account(Role.ADMINISTRATOR)
    number = _asked(user)
    assert number > 827364510
    assert decider.post(f"{REQUESTS}{number}/authorize/", CONFIRMED).status_code == 302
    owner_client = _password_sign_in(user)
    enrolment = owner_client.post(ENROL, {"password": PASSWORD}).content.decode()
    (key,) = re.findall(r"Key:\s*<code>([A-Z2-7]+)</code>", enrolment)
    device = TotpDevice.objects.get(user=user)
    assert (
        verified(Client(), another)
        .post(f"/administration/second-factor-requests/{device.pk}/approve/", CONFIRMED)
        .status_code
        == 302
    )

    for client, url in ((owner_client, OWN), (decider, EVERY)):
        page = client.get(url).content.decode()
        assert "Enrolment of the new second factor approved by an Administrator" in page
        for forbidden in (
            str(number),
            str(lapsing),
            "8273645",
            "9182736",
            key,
            "otpauth",
            "no_other_administrator",
            "cooling",
            "lapsed",
            "unavailable",
        ):
            assert forbidden not in page, forbidden


def test_an_address_shown_is_escaped(account: AccountFactory, administrator: User) -> None:
    # An address is data: whatever it holds is shown as text.
    user = account(Role.REVIEWER, device=False)
    User.objects.filter(pk=user.pk).update(email="test<b>'x'@caipo.test")
    _event(REQUESTED, user)

    page = verified(Client(), administrator).get(EVERY).content.decode()

    assert "test&lt;b&gt;&#x27;x&#x27;@caipo.test" in page
    assert "<b>" not in page


# --- Order and pages --------------------------------------------------------------------


def test_the_order_of_a_page_is_that_of_the_identifiers_when_the_times_disagree(
    owner: User, administrator: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded_at = timezone.now()
    monkeypatch.setattr(timezone, "now", lambda: recorded_at)
    first = _event(REQUESTED, owner)
    monkeypatch.setattr(timezone, "now", lambda: recorded_at - timedelta(hours=1))
    second = _event(AUTHORIZED, owner, actor=administrator)
    assert first.pk < second.pk and first.created_at > second.created_at

    for client, url in (
        (signed_in(Client(), owner), OWN),
        (verified(Client(), administrator), EVERY),
    ):
        latest, earliest = _entries(client.get(url))
        assert second.created_at.isoformat() in latest and "authorised" in latest
        assert first.created_at.isoformat() in earliest and "requested" in earliest


def test_a_long_history_is_shown_in_pages_that_hold_every_step_once(
    owner: User, administrator: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(selectors, "RECOVERY_HISTORY_PAGE_SIZE", 2)
    _distinctive_identifiers()
    events = [_event(REQUESTED, owner) for _ in range(5)]
    times = [event.created_at.isoformat() for event in reversed(events)]

    for client, url in (
        (signed_in(Client(), owner), OWN),
        (verified(Client(), administrator), EVERY),
    ):
        pages = [client.get(url), client.get(url, {"page": 2}), client.get(url, {"page": 3})]
        shown = [re.findall(r'datetime="([^"]+)"', page.content.decode()) for page in pages]
        assert shown == [times[0:2], times[2:4], times[4:5]]
        links = [re.findall(r'<a href="(\?[^"]*)"', page.content.decode()) for page in pages]
        assert links == [["?page=2"], ["?page=1", "?page=3"], ["?page=2"]]
        # A page asked for again is the same page, and no link carries an identifier.
        assert client.get(url, {"page": 2}).content == pages[1].content
        for page in pages:
            assert "9182736" not in page.content.decode()


@pytest.mark.parametrize(
    ("asked", "shown"),
    [("abc", 1), ("", 1), ("0", 3), ("-1", 3), ("99", 3), ("2", 2), ("1e3", 1), ("2; DROP", 1)],
)
def test_a_page_number_that_is_not_one_shows_a_page_that_exists(
    asked: str, shown: int, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(selectors, "RECOVERY_HISTORY_PAGE_SIZE", 2)
    events = [_event(REQUESTED, owner) for _ in range(5)]
    times = [event.created_at.isoformat() for event in reversed(events)]

    response = signed_in(Client(), owner).get(OWN, {"page": asked})

    assert response.status_code == 200
    first = (shown - 1) * 2
    assert re.findall(r'datetime="([^"]+)"', response.content.decode()) == times[first : first + 2]


def test_no_parameter_filters_a_history(owner: User, administrator: User) -> None:
    _every_step(owner, administrator)
    client = signed_in(Client(), owner)
    whole = _entries(client.get(OWN))

    for parameters in (
        {"event_type": "mfa_recovery_requested"},
        {"type": "requested"},
        {"q": "requested"},
        {"since": "2099-01-01"},
        {"order": "asc"},
        {"sort": "created_at"},
        {"page_size": "1"},
        {"limit": "1"},
        {"format": "csv"},
    ):
        response = client.get(OWN, parameters)
        assert _entries(response) == whole
        assert response["Content-Type"].startswith("text/html")


# --- The notice on the signed-in page ---------------------------------------------------


def test_an_account_whose_second_factor_was_revoked_is_told_when_it_is_next_signed_in(
    account: AccountFactory, administrator: User
) -> None:
    user = account(Role.REVIEWER)
    account(Role.ADMINISTRATOR)
    number = _asked(user)
    decider = verified(Client(), administrator)
    assert decider.post(f"{REQUESTS}{number}/authorize/", CONFIRMED).status_code == 302
    revoked_at = AuthenticationEvent.objects.get(event_type=AUTHORIZED).created_at

    # On the password alone: the account has no second factor now.
    client = _password_sign_in(user)
    page = client.get(LOGIN).content.decode()

    assert f"{NOTICE} {revoked_at.isoformat()}." in page
    assert f'<a href="{OWN}">Recovery history</a>' in page
    assert client.get(OWN).status_code == 200


def test_the_notice_is_shown_to_no_other_account(
    owner: User, account: AccountFactory, administrator: User
) -> None:
    _event(AUTHORIZED, owner, actor=administrator)
    bystander = account(Role.REVIEWER, device=False)

    assert NOTICE in signed_in(Client(), owner).get(LOGIN).content.decode()
    for client in (
        signed_in(Client(), bystander),
        verified(Client(), administrator),
        Client(),
    ):
        assert NOTICE not in client.get(LOGIN).content.decode()


def test_an_account_that_was_never_recovered_is_shown_no_notice(
    owner: User, administrator: User
) -> None:
    _event(REQUESTED, owner)
    _event(REJECTED, owner, actor=administrator)

    assert NOTICE not in signed_in(Client(), owner).get(LOGIN).content.decode()


def test_the_notice_after_a_revocation_at_the_server_is_the_same(owner: User) -> None:
    event = _event(BREAK_GLASS, owner, action=BreakGlassAction.REVOKE_DEVICE)

    page = signed_in(Client(), owner).get(LOGIN).content.decode()

    assert f"{NOTICE} {event.created_at.isoformat()}." in page


def test_the_notice_is_kept_nowhere_and_is_shown_each_time(
    owner: User, administrator: User
) -> None:
    _event(AUTHORIZED, owner, actor=administrator)
    _event(COMPLETED, owner)
    client = signed_in(Client(), owner)
    before = _counts()
    session_before = dict(client.session)

    first = client.get(LOGIN).content.decode()
    client.get(OWN)
    second = client.get(LOGIN).content.decode()

    assert NOTICE in first and NOTICE in second
    assert _counts() == before
    # Nothing about having seen it is put in the session either.
    assert dict(client.session) == session_before
    assert NOTICE in signed_in(Client(), owner).get(LOGIN).content.decode()


def test_the_notice_holds_nothing_but_the_time(owner: User, administrator: User) -> None:
    _distinctive_identifiers()
    event = _event(AUTHORIZED, owner, actor=administrator)

    page = signed_in(Client(), owner).get(LOGIN).content.decode()

    for forbidden in (
        str(event.pk),
        administrator.email,
        IDENTIFIER_KEY,
        SOURCE_KEY,
        CORRELATION_ID,
        "mfa_recovery",
    ):
        assert forbidden not in page, forbidden


def test_an_account_with_no_role_is_shown_no_notice_and_the_page_still_works(
    account: AccountFactory, administrator: User
) -> None:
    user = account(device=False)
    _event(AUTHORIZED, user, actor=administrator)

    response = signed_in(Client(), user).get(LOGIN)

    assert response.status_code == 200
    assert NOTICE not in response.content.decode()


def test_the_signed_in_page_links_to_the_pages_each_account_may_reach(
    owner: User, administrator: User
) -> None:
    for client, own, every in (
        (signed_in(Client(), owner), True, False),
        (signed_in(Client(), administrator), True, False),
        (verified(Client(), administrator), True, True),
        (Client(), False, False),
    ):
        page = client.get(LOGIN).content.decode()
        assert (f'href="{EVERY}"' in page) is every
        assert ('href="/account/second-factor/"' in page) is own
    assert (
        f'href="{OWN}"'
        in signed_in(Client(), owner).get("/account/second-factor/").content.decode()
    )


# --- A message decides nothing a visitor can see ----------------------------------------


def _answer(response: Any, number: int | None = None) -> tuple[int, str, list[str]]:
    body = re.sub(
        r'name="csrfmiddlewaretoken" value="[^"]+"',
        'name="csrfmiddlewaretoken" value=""',
        response.content.decode(),
    )
    body = re.sub(r"<strong>\d+</strong>", "<strong>N</strong>", body)
    headers = sorted(
        f"{name}: {value}"
        for name, value in response.headers.items()
        if name not in ("Content-Length", "Expires")
    )
    return response.status_code, body, headers


def _recovery_answer(user: User) -> tuple[int, str, list[str]]:
    client = Client()
    assert client.post(LOGIN, {"email": user.email, "password": PASSWORD})["Location"] == VERIFY
    return _answer(client.post(RECOVER))


def test_the_answer_to_a_request_is_the_same_whether_or_not_a_message_was_sent(
    account: AccountFactory, settings: LazySettings
) -> None:
    user = account(Role.REVIEWER)
    assert user.email_verified_at is None

    never_verified = _recovery_answer(user)
    assert django_mail.outbox == []
    User.objects.filter(pk=user.pk).update(email_verified_at=timezone.now())
    told = _recovery_answer(user)
    assert len(django_mail.outbox) == 1
    settings.EMAIL_BACKEND = "caipo.core.mail.RefusingEmailBackend"
    not_reached = _recovery_answer(user)

    assert never_verified == told == not_reached
    assert never_verified[0] == 200
    assert "<strong>N</strong>" in never_verified[1]
    assert MfaRecoveryRequest.objects.filter(user=user).count() == 1
    assert AuthenticationEvent.objects.filter(event_type=REQUESTED).count() == 3


def test_a_refused_or_throttled_request_answers_as_before_and_sends_nothing(
    account: AccountFactory, settings: LazySettings
) -> None:
    settings.MFA_RECOVERY_REQUEST_ACCOUNT_LIMIT = 1
    reader = account(Role.READER)
    reviewer = account(Role.REVIEWER)
    User.objects.update(email_verified_at=timezone.now())

    refused = _recovery_answer(reader)
    _recovery_answer(reviewer)
    django_mail.outbox.clear()
    throttled = _recovery_answer(reviewer)

    assert refused[0] == 200 and "The request was not accepted." in refused[1]
    assert throttled[0] == 429 and "Too many recovery requests." in throttled[1]
    assert django_mail.outbox == []


def test_the_answer_to_an_authorisation_is_the_same_whether_or_not_messages_were_sent(
    account: AccountFactory, administrator: User, settings: LazySettings
) -> None:
    account(Role.ADMINISTRATOR)
    User.objects.update(email_verified_at=timezone.now())
    decider = verified(Client(), administrator)
    first, second = account(Role.REVIEWER), account(Role.REVIEWER)
    User.objects.filter(pk=first.pk).update(email_verified_at=timezone.now())

    told = _answer(decider.post(f"{REQUESTS}{_asked(first)}/authorize/", CONFIRMED))
    assert len(django_mail.outbox) == 3  # the request, and the two about the finalisation
    settings.EMAIL_BACKEND = "caipo.core.mail.RefusingEmailBackend"
    not_reached = _answer(decider.post(f"{REQUESTS}{_asked(second)}/authorize/", CONFIRMED))

    assert told == not_reached
    assert told[0] == 302
    assert AuthenticationEvent.objects.filter(event_type=AUTHORIZED).count() == 2
    # The page of every account shows both, sent or not.
    assert len(_entries(decider.get(EVERY))) == 4


# --- The command at the server is still no page -----------------------------------------


def test_a_recovery_made_at_the_server_is_read_on_the_pages_and_cannot_be_made_from_them(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    number = _asked(user)
    revoked = services.break_glass_revoke_device(email=user.email, request_number=number)
    assert revoked.outcome == BreakGlassOutcome.DONE
    client = _password_sign_in(user)
    events = AuthenticationEvent.objects.filter(event_type=BREAK_GLASS).count()

    entries = _entries(client.get(OWN))
    assert "Second factor revoked by the emergency procedure." in entries[0]
    assert AT_SERVER in entries[0]
    for url in (OWN, EVERY):
        assert client.post(url, {"number": number, "email": user.email}).status_code in (403, 405)
    assert AuthenticationEvent.objects.filter(event_type=BREAK_GLASS).count() == events
