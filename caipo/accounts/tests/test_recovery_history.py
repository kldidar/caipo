"""The history of recoveries of a lost second factor, as it is read (ADR-0017 point 78).

Three selectors: what an account is shown of its own recoveries, what an
Administrator is shown of every account's, and when an account's second
factor was last revoked by one. Most tests write events straight into the
table, so that each kind of event can be put in front of the selectors by
itself; the last tests make the events with the services.
"""

import dataclasses
import inspect
from collections.abc import Callable
from datetime import datetime, timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from caipo.accounts import selectors, services
from caipo.accounts.models import (
    DECISION_EVENT_TYPES,
    AccountStatus,
    AuthenticationEvent,
    AuthenticationEventType,
    BreakGlassAction,
    TotpDevice,
    User,
)
from caipo.accounts.selectors import (
    AuthenticationContext,
    RecoveryHistoryEntry,
    RecoveryHistoryPage,
    Role,
)
from caipo.accounts.services import BreakGlassOutcome, MfaOutcome
from caipo.accounts.tests.fixtures import (
    UserFactory,
    enrolled_device,
    signed_in,
    verified,
)
from caipo.accounts.tests.test_recovery_authorization import (
    AUTHORIZED,
    PASSWORD,
    REJECTED,
    _approve,
    _asked,
    _authorize,
    _confirm,
    _enrolment_request,
    _reject,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db]

type AccountFactory = Callable[..., User]

# Visibly synthetic values for the columns that are never shown.
IDENTIFIER_KEY = "TEST-identifier-key-never-shown"
SOURCE_KEY = "TEST-source-key-never-shown"
CORRELATION_ID = "TESTcorrelationidnevershown"

REQUESTED = AuthenticationEventType.MFA_RECOVERY_REQUESTED
REJECTED_EVENT = AuthenticationEventType.MFA_RECOVERY_REJECTED
AUTHORIZED_EVENT = AuthenticationEventType.MFA_RECOVERY_AUTHORIZED
COMPLETED = AuthenticationEventType.MFA_RECOVERY_COMPLETED
BREAK_GLASS = AuthenticationEventType.MFA_RECOVERY_BREAK_GLASS
APPROVED = AuthenticationEventType.MFA_ENROLLMENT_APPROVED
FAILED = AuthenticationEventType.MFA_RECOVERY_FAILED
REVOKE = BreakGlassAction.REVOKE_DEVICE
APPROVE = BreakGlassAction.APPROVE_ENROLLMENT

LABEL_REQUESTED = "Recovery requested"
LABEL_REJECTED = "Recovery request rejected by an Administrator"
LABEL_AUTHORIZED = "Recovery authorised by an Administrator: the second factor was revoked"
LABEL_APPROVED = "Enrolment of the new second factor approved by an Administrator"
LABEL_COMPLETED = "Recovery completed: the new second factor accepted its first code"
LABEL_REVOKED_AT_SERVER = "Second factor revoked by the emergency procedure"
LABEL_APPROVED_AT_SERVER = "Enrolment of the new second factor approved by the emergency procedure"

# The steps that are shown whenever they were recorded, with what is read for each.
ALWAYS_SHOWN = [
    (REQUESTED, "", LABEL_REQUESTED),
    (REJECTED_EVENT, "", LABEL_REJECTED),
    (AUTHORIZED_EVENT, "", LABEL_AUTHORIZED),
    (COMPLETED, "", LABEL_COMPLETED),
    (BREAK_GLASS, REVOKE, LABEL_REVOKED_AT_SERVER),
    (BREAK_GLASS, APPROVE, LABEL_APPROVED_AT_SERVER),
]
NEVER_SHOWN = sorted(
    set(AuthenticationEventType) - {event_type for event_type, _, _ in ALWAYS_SHOWN} - {APPROVED}
)
HOUR = timedelta(hours=1)


@pytest.fixture
def account(user_with_roles: UserFactory) -> AccountFactory:
    """Return a factory for synthetic users with a known password and an active second factor."""

    def make(*roles: Role, trusted: bool = True) -> User:
        user = user_with_roles(*roles)
        user.set_password(PASSWORD)
        user.save()
        enrolled_device(user, trusted=trusted)
        return user

    return make


@pytest.fixture
def owner(user_with_roles: UserFactory) -> User:
    """Return the account whose history is read."""
    return user_with_roles(Role.REVIEWER)


@pytest.fixture
def decider(user_with_roles: UserFactory) -> User:
    """Return an account that is named as the actor of a decision."""
    return user_with_roles(Role.ADMINISTRATOR)


@pytest.fixture
def overseer(user_with_roles: UserFactory) -> AuthenticationContext:
    """Return the verified context of an Administrator who reads every account's history."""
    return verified(user_with_roles(Role.ADMINISTRATOR))


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


def _any_event(event_type: str, user: User, decider: User, action: str = "") -> AuthenticationEvent:
    """Write an event of any type about the user, naming the decider where the type needs one."""
    actor = decider if event_type in DECISION_EVENT_TYPES else None
    if event_type == BREAK_GLASS and not action:
        action = REVOKE
    return _event(event_type, user, actor=actor, action=action)


def _own(user: User, page: int = 1) -> RecoveryHistoryPage:
    return selectors.recovery_history_of(signed_in(user), page=page)


def _labels(history: RecoveryHistoryPage) -> list[str]:
    return [entry.label for entry in history.entries]


def _disable(user: User) -> None:
    User.objects.filter(pk=user.pk).update(status=AccountStatus.DISABLED)


# --- What is shown ----------------------------------------------------------------------


@pytest.mark.parametrize(("event_type", "action", "label"), ALWAYS_SHOWN)
def test_each_step_of_a_recovery_is_shown_to_the_account_and_to_an_administrator(
    event_type: str,
    action: str,
    label: str,
    owner: User,
    decider: User,
    overseer: AuthenticationContext,
) -> None:
    event = _any_event(event_type, owner, decider, action)

    for history in (_own(owner), selectors.recoveries_on_record(overseer)):
        (entry,) = history.entries
        assert entry.label == label
        assert entry.occurred_at == event.created_at
        assert entry.account_email == owner.email


@pytest.mark.parametrize("event_type", NEVER_SHOWN)
def test_no_other_event_of_the_account_is_shown_to_anybody(
    event_type: str, owner: User, decider: User, overseer: AuthenticationContext
) -> None:
    # Inside an open recovery, where an approval would be shown: nothing else
    # is, whatever it is. That includes a refused submission, the start and
    # the success of an enrolment, every step of a password reset, and every
    # sign-in.
    _event(AUTHORIZED_EVENT, owner, actor=decider)
    _any_event(event_type, owner, decider)

    assert _labels(_own(owner)) == [LABEL_AUTHORIZED]
    assert _labels(selectors.recoveries_on_record(overseer)) == [LABEL_AUTHORIZED]


def test_the_events_that_are_never_shown_are_the_ones_the_decision_names() -> None:
    assert {
        FAILED,
        AuthenticationEventType.MFA_ENROLLMENT_STARTED,
        AuthenticationEventType.MFA_ENROLLMENT_SUCCEEDED,
        AuthenticationEventType.MFA_ENROLLMENT_REJECTED,
        AuthenticationEventType.PASSWORD_RESET_REQUESTED,
        AuthenticationEventType.PASSWORD_RESET_SUCCEEDED,
        AuthenticationEventType.PASSWORD_RESET_FAILED,
        AuthenticationEventType.LOGIN_SUCCESS,
        AuthenticationEventType.LOGIN_FAILURE,
        AuthenticationEventType.LOGOUT,
        AuthenticationEventType.MFA_CHALLENGE_ISSUED,
    } <= set(NEVER_SHOWN)
    assert len(NEVER_SHOWN) == len(AuthenticationEventType) - 6


@pytest.mark.parametrize(
    "event_type",
    [
        FAILED,
        AuthenticationEventType.LOGIN_FAILURE,
        AuthenticationEventType.PASSWORD_RESET_REQUESTED,
        AuthenticationEventType.PASSWORD_RESET_FAILED,
    ],
)
def test_an_event_that_names_nobody_is_shown_to_nobody(
    event_type: str, owner: User, overseer: AuthenticationContext
) -> None:
    _event(event_type, None)

    assert _own(owner).entries == ()
    assert selectors.recoveries_on_record(overseer).entries == ()


def test_an_account_is_shown_no_event_of_another_account(
    owner: User, decider: User, user_with_roles: UserFactory, overseer: AuthenticationContext
) -> None:
    other = user_with_roles(Role.REVIEWER)
    for event_type, action, _label in ALWAYS_SHOWN:
        _any_event(event_type, other, decider, action)
    _event(APPROVED, other, actor=decider)
    _event(REQUESTED, owner)

    assert _labels(_own(owner)) == [LABEL_REQUESTED]
    assert {entry.account_email for entry in _own(other).entries} == {other.email}
    # The Administrator's page holds both accounts' events.
    emails = [entry.account_email for entry in selectors.recoveries_on_record(overseer).entries]
    assert emails.count(owner.email) == 1
    assert emails.count(other.email) == 7


def test_an_administrator_named_as_the_actor_is_not_shown_the_event_as_its_own(
    owner: User, decider: User
) -> None:
    _event(AUTHORIZED_EVENT, owner, actor=decider)

    assert _own(decider).entries == ()


def test_the_history_of_an_account_takes_no_account_from_its_caller() -> None:
    for selector in (selectors.recovery_history_of, selectors.last_recovery_of):
        parameters = set(inspect.signature(selector).parameters)
        assert parameters <= {"context", "page"}, selector.__name__
    assert set(inspect.signature(selectors.recoveries_on_record).parameters) == {"context", "page"}


# --- The approval of an enrolment is a step only inside a recovery ----------------------


def test_an_approval_that_follows_no_recovery_is_not_shown(
    owner: User, decider: User, overseer: AuthenticationContext
) -> None:
    _event(APPROVED, owner, actor=decider)

    assert _own(owner).entries == ()
    assert selectors.recoveries_on_record(overseer).entries == ()


@pytest.mark.parametrize("opener", ["authorisation", "revocation at the server"])
def test_an_approval_inside_an_open_recovery_is_shown(
    opener: str, owner: User, decider: User, overseer: AuthenticationContext
) -> None:
    if opener == "authorisation":
        _event(AUTHORIZED_EVENT, owner, actor=decider)
    else:
        _event(BREAK_GLASS, owner, action=REVOKE)
    _event(APPROVED, owner, actor=decider)

    assert _labels(_own(owner))[0] == LABEL_APPROVED
    assert _labels(selectors.recoveries_on_record(overseer))[0] == LABEL_APPROVED


def test_an_approval_after_the_recovery_was_completed_is_not_shown(
    owner: User, decider: User
) -> None:
    _event(AUTHORIZED_EVENT, owner, actor=decider)
    _event(APPROVED, owner, actor=decider)
    _event(COMPLETED, owner)
    # A later replacement of the device, which no recovery opened.
    _event(APPROVED, owner, actor=decider)

    assert _labels(_own(owner)) == [LABEL_COMPLETED, LABEL_APPROVED, LABEL_AUTHORIZED]


def test_an_approval_is_inside_only_the_recovery_of_its_own_account(
    owner: User, decider: User, user_with_roles: UserFactory
) -> None:
    other = user_with_roles(Role.REVIEWER)
    _event(AUTHORIZED_EVENT, other, actor=decider)
    _event(APPROVED, owner, actor=decider)

    assert _own(owner).entries == ()


def test_an_approval_at_the_server_opens_no_recovery_for_a_later_approval(
    owner: User, decider: User
) -> None:
    # The command's approval is not an opening: an Administrator's approval
    # recorded after it, with no recovery open, is still outside one.
    _event(BREAK_GLASS, owner, action=APPROVE)
    _event(APPROVED, owner, actor=decider)

    assert _labels(_own(owner)) == [LABEL_APPROVED_AT_SERVER]


def test_whether_an_approval_is_inside_a_recovery_is_read_from_the_order_of_the_events(
    owner: User, decider: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The host that recorded the completion is an hour ahead: by its time the
    # completion is after the second approval, by its identifier before the
    # second opening. The identifiers decide.
    recorded_at = timezone.now()
    monkeypatch.setattr(timezone, "now", lambda: recorded_at)
    _event(AUTHORIZED_EVENT, owner, actor=decider)
    monkeypatch.setattr(timezone, "now", lambda: recorded_at + HOUR)
    _event(COMPLETED, owner)
    monkeypatch.setattr(timezone, "now", lambda: recorded_at)
    _event(AUTHORIZED_EVENT, owner, actor=decider)
    _event(APPROVED, owner, actor=decider)

    assert _labels(_own(owner))[0] == LABEL_APPROVED


def test_the_history_and_the_open_recovery_are_one_derivation() -> None:
    # One statement of what opens a recovery, used by both: the history keeps
    # no second representation of where a recovery begins.
    for function in (selectors.open_recovery_of, selectors._recovery_history):
        assert "_RECOVERY_OPENER" in inspect.getsource(function), function.__name__
    assert "_RECOVERY_OPENER" in inspect.getsource(selectors.last_recovery_of)
    source = inspect.getsource(selectors)
    assert source.count("BreakGlassAction.REVOKE_DEVICE") == 2  # the opener, and a label


# --- Who is named -----------------------------------------------------------------------


@pytest.mark.parametrize("event_type", [REJECTED_EVENT, AUTHORIZED_EVENT])
def test_a_decision_names_the_administrator_who_made_it(
    event_type: str, owner: User, decider: User, overseer: AuthenticationContext
) -> None:
    _event(event_type, owner, actor=decider)

    for history in (_own(owner), selectors.recoveries_on_record(overseer)):
        (entry,) = history.entries
        assert entry.actor_email == decider.email
        assert entry.performed_at_server is False


def test_an_approval_names_the_administrator_who_gave_it(owner: User, decider: User) -> None:
    _event(BREAK_GLASS, owner, action=REVOKE)
    _event(APPROVED, owner, actor=decider)

    assert _own(owner).entries[0].actor_email == decider.email


@pytest.mark.parametrize("event_type", [REQUESTED, COMPLETED])
def test_what_the_account_itself_did_names_no_actor(event_type: str, owner: User) -> None:
    _event(event_type, owner)

    (entry,) = _own(owner).entries
    assert entry.actor_email is None
    assert entry.performed_at_server is False


@pytest.mark.parametrize("action", [REVOKE, APPROVE])
def test_a_step_performed_at_the_server_names_nobody_and_says_so(
    action: str, owner: User, overseer: AuthenticationContext
) -> None:
    _event(BREAK_GLASS, owner, action=action)

    for history in (_own(owner), selectors.recoveries_on_record(overseer)):
        (entry,) = history.entries
        assert entry.actor_email is None
        assert entry.performed_at_server is True


# --- What is never shown ----------------------------------------------------------------


def test_an_entry_holds_five_things_and_nothing_else() -> None:
    assert [field.name for field in dataclasses.fields(RecoveryHistoryEntry)] == [
        "occurred_at",
        "label",
        "account_email",
        "actor_email",
        "performed_at_server",
    ]
    assert [field.name for field in dataclasses.fields(RecoveryHistoryPage)] == [
        "entries",
        "number",
        "has_previous",
        "has_next",
    ]


def test_nothing_internal_to_an_event_leaves_the_selectors(
    owner: User, decider: User, overseer: AuthenticationContext
) -> None:
    with connection.cursor() as cursor:
        # So that an identifier cannot occur in a page by chance.
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence('accounts_authenticationevent', 'id'), 918273640)"
        )
    events = [
        _any_event(event_type, owner, decider, action) for event_type, action, _ in ALWAYS_SHOWN
    ]
    events.append(_event(APPROVED, owner, actor=decider))
    assert all(event.pk > 918273640 for event in events)

    for history in (_own(owner), selectors.recoveries_on_record(overseer)):
        assert len(history.entries) == 7
        text = repr(history)
        for forbidden in (
            IDENTIFIER_KEY,
            SOURCE_KEY,
            CORRELATION_ID,
            *(str(event.pk) for event in events),
            *AuthenticationEventType.values,
            *BreakGlassAction.values,
            str(owner.pk) + ",",
            owner.password,
        ):
            assert forbidden not in text, forbidden


def test_only_the_columns_that_are_shown_are_read_from_the_events(owner: User) -> None:
    _event(REQUESTED, owner)

    with CaptureQueriesContext(connection) as queries:
        _own(owner)

    (rows,) = [
        query["sql"]
        for query in queries
        if "accounts_authenticationevent" in query["sql"] and "COUNT(" not in query["sql"]
    ]
    selected = rows.split(" FROM ")[0]
    for column in ("identifier_key", "source_key", "correlation_id", '"password"'):
        assert column not in selected, column
    assert '"accounts_authenticationevent"."id"' not in selected


def test_reading_a_history_writes_nothing(
    owner: User, decider: User, overseer: AuthenticationContext
) -> None:
    _event(AUTHORIZED_EVENT, owner, actor=decider)

    with CaptureQueriesContext(connection) as queries:
        _own(owner)
        selectors.recoveries_on_record(overseer)
        selectors.last_recovery_of(signed_in(owner))

    assert queries
    assert all(query["sql"].startswith("SELECT") for query in queries)
    assert AuthenticationEvent.objects.count() == 1


# --- Order and pages --------------------------------------------------------------------


def test_the_order_is_that_of_the_identifiers_when_the_times_disagree(
    owner: User, decider: User, overseer: AuthenticationContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded_at = timezone.now()
    monkeypatch.setattr(timezone, "now", lambda: recorded_at)
    first = _event(REQUESTED, owner)
    monkeypatch.setattr(timezone, "now", lambda: recorded_at - HOUR)
    second = _event(REJECTED_EVENT, owner, actor=decider)
    monkeypatch.setattr(timezone, "now", lambda: recorded_at - 2 * HOUR)
    third = _event(REQUESTED, owner)
    assert first.pk < second.pk < third.pk
    assert first.created_at > second.created_at > third.created_at

    for history in (_own(owner), selectors.recoveries_on_record(overseer)):
        # The latest recorded is first, and the times are shown as recorded.
        assert [entry.occurred_at for entry in history.entries] == [
            third.created_at,
            second.created_at,
            first.created_at,
        ]
        assert _labels(history) == [LABEL_REQUESTED, LABEL_REJECTED, LABEL_REQUESTED]


def _times(history: RecoveryHistoryPage) -> list[datetime]:
    return [entry.occurred_at for entry in history.entries]


def test_the_pages_hold_every_step_once_and_in_order(
    owner: User, overseer: AuthenticationContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(selectors, "RECOVERY_HISTORY_PAGE_SIZE", 3)
    recorded_at = timezone.now()
    expected = []
    for minute in range(7):
        monkeypatch.setattr(
            timezone, "now", lambda minute=minute: recorded_at + timedelta(minutes=minute)
        )
        expected.append(_event(REQUESTED, owner).created_at)
    expected.reverse()

    def own(page: int) -> RecoveryHistoryPage:
        return _own(owner, page)

    def every(page: int) -> RecoveryHistoryPage:
        return selectors.recoveries_on_record(overseer, page=page)

    for read in (own, every):
        pages = [read(number) for number in (1, 2, 3)]
        assert [len(page.entries) for page in pages] == [3, 3, 1]
        assert [time for page in pages for time in _times(page)] == expected
        assert [page.number for page in pages] == [1, 2, 3]
        assert [page.has_previous for page in pages] == [False, True, True]
        assert [page.has_next for page in pages] == [True, True, False]
        # Asked again, a page is the same page.
        assert read(2) == pages[1]


@pytest.mark.parametrize(("asked", "given"), [(0, 3), (-5, 3), (4, 3), (10**30, 3), (1, 1)])
def test_a_page_that_does_not_exist_is_the_nearest_one_that_does(
    asked: int, given: int, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(selectors, "RECOVERY_HISTORY_PAGE_SIZE", 3)
    for _ in range(7):
        _event(REQUESTED, owner)

    assert _own(owner, asked).number == given


def test_an_empty_history_is_one_empty_page(owner: User, overseer: AuthenticationContext) -> None:
    empty = RecoveryHistoryPage(entries=(), number=1, has_previous=False, has_next=False)

    assert _own(owner) == empty
    assert selectors.recoveries_on_record(overseer) == empty


def test_a_page_holds_fifty_steps() -> None:
    assert selectors.RECOVERY_HISTORY_PAGE_SIZE == 50


# --- Who may read -----------------------------------------------------------------------


@pytest.mark.parametrize("role", list(Role))
def test_every_role_reads_its_own_history_on_its_password_alone(
    role: Role, user_with_roles: UserFactory
) -> None:
    user = user_with_roles(role)
    _event(REQUESTED, user)

    assert _labels(_own(user)) == [LABEL_REQUESTED]
    assert selectors.last_recovery_of(signed_in(user)) is None


def test_an_account_whose_second_factor_was_revoked_reads_its_history(
    owner: User, decider: User
) -> None:
    opener = _event(AUTHORIZED_EVENT, owner, actor=decider)
    assert not TotpDevice.objects.filter(user=owner).exists()

    assert _labels(_own(owner)) == [LABEL_AUTHORIZED]
    assert selectors.last_recovery_of(signed_in(owner)) == opener.created_at


def test_an_account_verified_with_its_second_factor_reads_its_history(owner: User) -> None:
    _event(REQUESTED, owner)

    assert _labels(selectors.recovery_history_of(verified(owner))) == [LABEL_REQUESTED]


def test_an_account_with_no_role_reads_no_history(user_with_roles: UserFactory) -> None:
    user = user_with_roles()

    with pytest.raises(PermissionDenied):
        _own(user)
    with pytest.raises(PermissionDenied):
        selectors.last_recovery_of(signed_in(user))


def test_a_disabled_account_reads_no_history(owner: User) -> None:
    context = signed_in(owner)
    _disable(owner)

    with pytest.raises(PermissionDenied):
        selectors.recovery_history_of(context)
    with pytest.raises(PermissionDenied):
        selectors.last_recovery_of(context)


def test_an_administrator_verified_with_a_trusted_second_factor_reads_every_history(
    owner: User, overseer: AuthenticationContext
) -> None:
    _event(REQUESTED, owner)

    assert _labels(selectors.recoveries_on_record(overseer)) == [LABEL_REQUESTED]


def test_an_administrator_on_a_password_alone_reads_only_its_own_history(
    owner: User, user_with_roles: UserFactory
) -> None:
    administrator = user_with_roles(Role.ADMINISTRATOR)
    enrolled_device(administrator)
    _event(REQUESTED, owner)

    with pytest.raises(PermissionDenied):
        selectors.recoveries_on_record(signed_in(administrator))
    assert _own(administrator).entries == ()


def test_an_administrator_whose_second_factor_is_not_trusted_reads_only_its_own_history(
    owner: User, user_with_roles: UserFactory
) -> None:
    administrator = user_with_roles(Role.ADMINISTRATOR)
    device = enrolled_device(administrator, trusted=False)
    context = AuthenticationContext(administrator, selectors.Assurance.MFA_VERIFIED, device.pk)
    _event(REQUESTED, owner)

    with pytest.raises(PermissionDenied):
        selectors.recoveries_on_record(context)


@pytest.mark.parametrize("role", [Role.READER, Role.RESEARCHER, Role.REVIEWER])
def test_no_other_role_reads_every_history_even_with_a_second_factor(
    role: Role, owner: User, user_with_roles: UserFactory
) -> None:
    _event(REQUESTED, owner)

    with pytest.raises(PermissionDenied):
        selectors.recoveries_on_record(verified(user_with_roles(role)))


def test_a_disabled_administrator_reads_no_history(
    owner: User, overseer: AuthenticationContext
) -> None:
    _event(REQUESTED, owner)
    _disable(overseer.user)

    with pytest.raises(PermissionDenied):
        selectors.recoveries_on_record(overseer)


def test_an_administrator_sees_the_recoveries_of_its_own_account_too(
    overseer: AuthenticationContext,
) -> None:
    _event(REQUESTED, overseer.user)

    (entry,) = selectors.recoveries_on_record(overseer).entries
    assert entry.account_email == overseer.user.email


# --- When the second factor was last revoked --------------------------------------------


def test_an_account_that_was_never_recovered_has_no_last_recovery(
    owner: User, decider: User
) -> None:
    # Everything short of an opening: a request, a rejection, and an approval
    # at the server that no revocation preceded.
    _event(REQUESTED, owner)
    _event(REJECTED_EVENT, owner, actor=decider)
    _event(BREAK_GLASS, owner, action=APPROVE)
    _event(COMPLETED, owner)

    assert selectors.last_recovery_of(signed_in(owner)) is None


@pytest.mark.parametrize("opener", ["authorisation", "revocation at the server"])
def test_the_last_recovery_is_when_the_second_factor_was_revoked(
    opener: str, owner: User, decider: User
) -> None:
    if opener == "authorisation":
        event = _event(AUTHORIZED_EVENT, owner, actor=decider)
    else:
        event = _event(BREAK_GLASS, owner, action=REVOKE)

    assert selectors.last_recovery_of(signed_in(owner)) == event.created_at


def test_the_last_recovery_is_still_told_after_it_was_completed(owner: User, decider: User) -> None:
    # Nothing records that the account has seen it, so it does not go away.
    event = _event(AUTHORIZED_EVENT, owner, actor=decider)
    _event(COMPLETED, owner)

    assert selectors.last_recovery_of(signed_in(owner)) == event.created_at
    assert selectors.last_recovery_of(signed_in(owner)) == event.created_at


def test_the_last_recovery_is_the_one_recorded_last_even_if_its_time_is_earlier(
    owner: User, decider: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded_at = timezone.now()
    monkeypatch.setattr(timezone, "now", lambda: recorded_at)
    _event(AUTHORIZED_EVENT, owner, actor=decider)
    monkeypatch.setattr(timezone, "now", lambda: recorded_at - HOUR)
    later = _event(BREAK_GLASS, owner, action=REVOKE)

    assert selectors.last_recovery_of(signed_in(owner)) == later.created_at == recorded_at - HOUR


def test_the_recovery_of_another_account_is_not_an_accounts_last_recovery(
    owner: User, decider: User, user_with_roles: UserFactory
) -> None:
    _event(AUTHORIZED_EVENT, user_with_roles(Role.REVIEWER), actor=decider)

    assert selectors.last_recovery_of(signed_in(owner)) is None
    # Nor is one that the account decided on as an Administrator.
    assert selectors.last_recovery_of(signed_in(decider)) is None


# --- The histories of real recoveries, made by the services -----------------------------


def test_the_history_of_a_recovery_through_two_administrators(account: AccountFactory) -> None:
    user = account(Role.REVIEWER)
    first, second = account(Role.ADMINISTRATOR), account(Role.ADMINISTRATOR)
    assert _reject(_asked(user), verified(first)) == REJECTED
    assert _authorize(_asked(user), verified(first)) == AUTHORIZED
    secret, number = _enrolment_request(user)
    assert _approve(number, verified(second)).outcome == MfaOutcome.ACCEPTED
    assert _confirm(user, secret).outcome == MfaOutcome.ACCEPTED

    expected = [
        (LABEL_COMPLETED, None, False),
        (LABEL_APPROVED, second.email, False),
        (LABEL_AUTHORIZED, first.email, False),
        (LABEL_REQUESTED, None, False),
        (LABEL_REJECTED, first.email, False),
        (LABEL_REQUESTED, None, False),
    ]
    for history in (_own(user), selectors.recoveries_on_record(verified(first))):
        assert [
            (entry.label, entry.actor_email, entry.performed_at_server) for entry in history.entries
        ] == expected
        assert {entry.account_email for entry in history.entries} == {user.email}
    opened = AuthenticationEvent.objects.get(event_type=AUTHORIZED_EVENT)
    assert selectors.last_recovery_of(signed_in(user)) == opened.created_at


def test_the_history_of_the_only_administrator_recovered_at_the_server(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    revoked = services.break_glass_revoke_device(email=user.email, request_number=_asked(user))
    assert revoked.outcome == BreakGlassOutcome.DONE
    secret, number = _enrolment_request(user)
    approved = services.break_glass_approve_enrollment(email=user.email, request_number=number)
    assert approved.outcome == BreakGlassOutcome.DONE

    # On the password alone, before the new device has given its first code.
    assert [
        (entry.label, entry.actor_email, entry.performed_at_server) for entry in _own(user).entries
    ] == [
        (LABEL_APPROVED_AT_SERVER, None, True),
        (LABEL_REVOKED_AT_SERVER, None, True),
        (LABEL_REQUESTED, None, False),
    ]

    confirmed = _confirm(user, secret)
    assert confirmed.outcome == MfaOutcome.ACCEPTED
    assert confirmed.context is not None
    everything = selectors.recoveries_on_record(confirmed.context)
    assert _labels(everything) == [
        LABEL_COMPLETED,
        LABEL_APPROVED_AT_SERVER,
        LABEL_REVOKED_AT_SERVER,
        LABEL_REQUESTED,
    ]
    assert all(entry.actor_email is None for entry in everything.entries)
