"""The messages and the history of a recovery alongside other operations, on separate
database connections (ADR-0017 points 78 to 81).

These tests commit their data, because other connections must see it, and the
database is emptied after each of them.

What they show: a message is sent only after its change is committed and
while none of the locks of a recovery is held, so a mail service that does
not answer holds nothing back; operations made together tell each person
once; who is told is who was an Administrator when the change was committed;
and a history is read without waiting for a recovery that is under way.
"""

import threading
from collections.abc import Callable
from functools import partial

import pytest
from django.core import mail as django_mail
from django.db import connection, connections, transaction
from django.utils import timezone

from caipo.accounts import selectors, services
from caipo.accounts.models import AuthenticationEvent, User
from caipo.accounts.selectors import AuthenticationContext, Role
from caipo.accounts.services import (
    BreakGlassOutcome,
    BreakGlassResult,
    RecoveryRequestOutcome,
    SignInOutcome,
)
from caipo.accounts.tests.fixtures import UserFactory, signed_in, verified
from caipo.accounts.tests.test_recovery_authorization_concurrency import (
    AUTHORIZED,
    PASSWORD,
    SOURCE,
    UNAVAILABLE,
    _account,
    _ask,
    _asked,
    _authorize,
    _challenge,
)
from caipo.accounts.tests.test_recovery_request_concurrency import (
    SETTLE_SECONDS,
    WAIT_SECONDS,
    _at_the_same_time,
    _behind,
    _Held,
)
from caipo.core import mail

pytestmark = [pytest.mark.services, pytest.mark.django_db(transaction=True)]

REQUEST_MADE = "A second-factor recovery request was made."
FINALIZED = "A second-factor recovery was finalized."
EMERGENCY = "An emergency second-factor recovery action was performed."

DONE = BreakGlassResult(BreakGlassOutcome.DONE)
NOT_DONE = BreakGlassResult(BreakGlassOutcome.UNAVAILABLE)
ROUNDS = 4

# Where a finalisation has made every change but its record, under every lock.
FINALIZING = "_finalize_recovery"


def _told(user_with_roles: UserFactory, role: Role, *, device: bool = True) -> User:
    """Return an account with a verified email address, which is therefore told."""
    if device:
        user = _account(user_with_roles, role)
    else:
        user = user_with_roles(role)
        user.set_password(PASSWORD)
        user.save()
    User.objects.filter(pk=user.pk).update(email_verified_at=timezone.now())
    user.refresh_from_db()
    return user


def _revoke(user: User, number: int) -> BreakGlassResult:
    return services.break_glass_revoke_device(email=user.email, request_number=number)


def _sent() -> list[tuple[str, str]]:
    return sorted((message.to[0], str(message.body)) for message in django_mail.outbox)


def _elsewhere[T](operation: Callable[[], T]) -> T:
    """Run the operation on another connection, as another request would, and return its result.

    Fails if it does not finish in the time an operation that waits for
    nothing needs.
    """
    results: list[T] = []
    errors: list[Exception] = []

    def run() -> None:
        try:
            results.append(operation())
        except Exception as error:  # recorded and raised by the test, not hidden
            errors.append(error)
        finally:
            connections.close_all()

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(timeout=SETTLE_SECONDS * 4)
    assert not thread.is_alive(), "the operation waited for something"
    if errors:
        raise errors[0]
    return results[0]


def _locks_are_free(user: User) -> bool:
    """Take every lock a recovery of the account holds, without waiting, and give them back.

    Raises if any of them is held by another connection.
    """
    identifier_key = services._key("identifier", user.email)
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("LOCK TABLE accounts_roleevent IN SHARE ROW EXCLUSIVE MODE NOWAIT")
        cursor.execute(
            "SELECT pg_try_advisory_xact_lock(%s, %s)",
            [services._IDENTIFIER_LOCK, int(identifier_key[:8], 16) >> 1],
        )
        (sign_in_lock,) = cursor.fetchone()
        cursor.execute(
            "SELECT pg_try_advisory_xact_lock(%s, %s)",
            [services._SECOND_FACTOR_LOCK, user.pk % 2**31],
        )
        (second_factor_lock,) = cursor.fetchone()
        cursor.execute("SELECT id FROM accounts_user WHERE id = %s FOR UPDATE NOWAIT", [user.pk])
    return bool(sign_in_lock and second_factor_lock)


class _Deliveries:
    """Stands in front of the email boundary and looks at the database at each delivery.

    Every message is still handed to the real boundary afterwards.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch, user: User, event_type: str) -> None:
        self.seen: list[tuple[bool, bool, int]] = []
        deliver = mail.deliver

        def observed(*, to: str, subject: str, body: str) -> None:
            in_transaction = connection.in_atomic_block
            free = _elsewhere(lambda: _locks_are_free(user))
            committed = _elsewhere(
                lambda: AuthenticationEvent.objects.filter(
                    event_type=event_type, user_id=user.pk
                ).count()
            )
            self.seen.append((in_transaction, free, committed))
            deliver(to=to, subject=subject, body=body)

        monkeypatch.setattr(mail, "deliver", observed)


# --- A message is sent after the commit, holding no lock --------------------------------


def test_a_request_is_committed_and_holds_no_lock_when_its_message_is_sent(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _told(user_with_roles, Role.REVIEWER)
    challenge = _challenge(user)
    deliveries = _Deliveries(monkeypatch, user, "mfa_recovery_requested")

    assert _ask(challenge).outcome == RecoveryRequestOutcome.REQUESTED

    assert deliveries.seen == [(False, True, 1)]
    assert _sent() == [(user.email, REQUEST_MADE)]


def test_an_authorisation_is_committed_and_holds_no_lock_when_its_messages_are_sent(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _told(user_with_roles, Role.REVIEWER)
    actor = verified(_told(user_with_roles, Role.ADMINISTRATOR))
    other = _told(user_with_roles, Role.ADMINISTRATOR)
    number = _asked(user)
    django_mail.outbox.clear()
    deliveries = _Deliveries(monkeypatch, user, "mfa_recovery_authorized")

    assert _authorize(number, actor) == AUTHORIZED

    assert deliveries.seen == [(False, True, 1)] * 2
    assert _sent() == sorted([(user.email, FINALIZED), (other.email, FINALIZED)])


@pytest.mark.parametrize("action", ["revoke", "approve"])
def test_a_break_glass_action_is_committed_and_holds_no_lock_when_its_messages_are_sent(
    action: str, user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _told(user_with_roles, Role.ADMINISTRATOR)
    other = _told(user_with_roles, Role.ADMINISTRATOR, device=False)
    number = _asked(user)
    if action == "approve":
        assert _revoke(user, number) == DONE
        started = services.start_mfa_enrollment(
            actor=signed_in(user), password=PASSWORD, source=SOURCE
        )
        assert started.provisioning is not None
        enrolment = selectors.enrollment_request_number_of(user)
        assert enrolment is not None
        number = enrolment
    django_mail.outbox.clear()
    deliveries = _Deliveries(monkeypatch, user, "mfa_recovery_break_glass")

    if action == "revoke":
        assert _revoke(user, number) == DONE
        expected = [(user.email, FINALIZED), (other.email, EMERGENCY)]
    else:
        result = services.break_glass_approve_enrollment(email=user.email, request_number=number)
        assert result == DONE
        expected = [(other.email, EMERGENCY)]

    events = 1 if action == "revoke" else 2
    assert deliveries.seen == [(False, True, events)] * len(expected)
    assert _sent() == sorted(expected)


def test_a_mail_service_that_does_not_answer_holds_nothing_back(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _told(user_with_roles, Role.REVIEWER)
    actor = verified(_told(user_with_roles, Role.ADMINISTRATOR))
    other = verified(_told(user_with_roles, Role.ADMINISTRATOR))
    bystander = user_with_roles(Role.READER)
    number = _asked(user)
    reached, release = threading.Event(), threading.Event()
    outcome: list[object] = []

    def stalled(*, to: str, subject: str, body: str) -> None:
        reached.set()
        assert release.wait(timeout=WAIT_SECONDS), "never released"

    def authorise() -> None:
        try:
            outcome.append(_authorize(number, actor))
        finally:
            connections.close_all()

    monkeypatch.setattr(mail, "deliver", stalled)
    thread = threading.Thread(target=authorise)
    thread.start()
    try:
        assert reached.wait(timeout=WAIT_SECONDS), "no message was attempted"

        # The recovery is already finalised, for everybody.
        assert _elsewhere(lambda: selectors.has_open_recovery(user.pk)) is True
        # Whatever needs the locks of that recovery proceeds at once: a
        # change of role, which takes the lock on the role events; a sign-in
        # of the account, which takes the lock on its address; and a new
        # enrolment, which takes its second-factor lock.
        _elsewhere(
            lambda: services.grant_role(
                actor=other, user=bystander, role=Role.RESEARCHER, reason="TEST"
            )
        )
        signed = _elsewhere(
            lambda: services.sign_in(email=user.email, password=PASSWORD, source=SOURCE)
        )
        assert signed.outcome == SignInOutcome.SIGNED_IN
        started = _elsewhere(
            lambda: services.start_mfa_enrollment(
                actor=signed_in(user), password=PASSWORD, source=SOURCE
            )
        )
        assert started.provisioning is not None
        assert _elsewhere(lambda: _locks_are_free(user)) is True
    finally:
        release.set()
        thread.join(timeout=WAIT_SECONDS)
    assert not thread.is_alive()
    assert outcome == [AUTHORIZED]


# --- Operations made together tell each person once -------------------------------------


def test_two_authorisations_at_once_tell_the_owner_once(user_with_roles: UserFactory) -> None:
    first = verified(_told(user_with_roles, Role.ADMINISTRATOR))
    second = verified(_told(user_with_roles, Role.ADMINISTRATOR))
    for _ in range(ROUNDS):
        user = _told(user_with_roles, Role.REVIEWER)
        number = _asked(user)
        django_mail.outbox.clear()

        results = _at_the_same_time(
            partial(_authorize, number, first),
            partial(_authorize, number, second),
        )

        assert sorted(results, key=str) == sorted([AUTHORIZED, UNAVAILABLE], key=str)
        # Whoever authorised is not told, and the other Administrator is.
        other = second if results[0] == AUTHORIZED else first
        assert _sent() == sorted([(user.email, FINALIZED), (other.user.email, FINALIZED)])


def test_two_revocations_at_the_server_at_once_tell_each_person_once(
    user_with_roles: UserFactory,
) -> None:
    other = _told(user_with_roles, Role.ADMINISTRATOR, device=False)
    for _ in range(ROUNDS):
        # The accounts of the rounds before stay Administrators on record,
        # with no device any more: they are told too, and none is able to act.
        user = _told(user_with_roles, Role.ADMINISTRATOR)
        number = _asked(user)
        django_mail.outbox.clear()

        results = _at_the_same_time(
            partial(_revoke, user, number),
            partial(_revoke, user, number),
        )

        assert sorted(results, key=str) == sorted([DONE, NOT_DONE], key=str)
        sent = _sent()
        assert sent.count((user.email, FINALIZED)) == 1
        assert sent.count((other.email, EMERGENCY)) == 1
        assert len([body for _to, body in sent if body == FINALIZED]) == 1


def test_two_requests_at_once_tell_the_owner_once_for_each_that_was_made(
    user_with_roles: UserFactory,
) -> None:
    user = _told(user_with_roles, Role.REVIEWER)
    for _ in range(ROUNDS):
        challenge = _challenge(user)
        django_mail.outbox.clear()
        before = AuthenticationEvent.objects.filter(event_type="mfa_recovery_requested").count()

        results = _at_the_same_time(
            partial(_ask, challenge),
            partial(_ask, challenge),
        )

        # One challenge makes one request, however often it is submitted.
        made = AuthenticationEvent.objects.filter(event_type="mfa_recovery_requested").count()
        assert made == before + 1
        assert len(results) == 2
        assert _sent() == [(user.email, REQUEST_MADE)]


# --- Who is told is who was an Administrator when the change was committed --------------


def _administrators(user_with_roles: UserFactory) -> tuple[AuthenticationContext, User, User]:
    actor = verified(_told(user_with_roles, Role.ADMINISTRATOR))
    leaving = _told(user_with_roles, Role.ADMINISTRATOR)
    staying = _told(user_with_roles, Role.ADMINISTRATOR)
    return actor, leaving, staying


def test_an_administrator_who_lost_the_role_before_the_authorisation_is_not_told(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _told(user_with_roles, Role.REVIEWER)
    actor, leaving, staying = _administrators(user_with_roles)
    revoker = verified(staying)
    number = _asked(user)
    django_mail.outbox.clear()

    # Held with the lock on the role events and the revocation not yet
    # written: the authorisation waits, and then reads who is left.
    held = _Held(
        monkeypatch,
        "_require_another_administrator",
        lambda: services.revoke_role(
            actor=revoker, user=leaving, role=Role.ADMINISTRATOR, reason="TEST"
        ),
    )
    revoked, authorised = _behind(held, lambda: _authorize(number, actor))

    assert not isinstance(revoked, Exception), revoked
    assert authorised == AUTHORIZED
    assert _sent() == sorted([(user.email, FINALIZED), (staying.email, FINALIZED)])


def test_an_administrator_who_loses_the_role_after_the_authorisation_was_told(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _told(user_with_roles, Role.REVIEWER)
    actor, leaving, staying = _administrators(user_with_roles)
    revoker = verified(staying)
    number = _asked(user)
    django_mail.outbox.clear()

    held = _Held(monkeypatch, FINALIZING, lambda: _authorize(number, actor))
    authorised, revoked = _behind(
        held,
        lambda: services.revoke_role(
            actor=revoker, user=leaving, role=Role.ADMINISTRATOR, reason="TEST"
        ),
    )

    assert authorised == AUTHORIZED
    assert not isinstance(revoked, Exception), revoked
    assert _sent() == sorted(
        [(user.email, FINALIZED), (leaving.email, FINALIZED), (staying.email, FINALIZED)]
    )


def test_an_administrator_who_is_being_granted_the_role_is_told_only_if_the_grant_came_first(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _told(user_with_roles, Role.REVIEWER)
    actor, _leaving, staying = _administrators(user_with_roles)
    arriving = _told(user_with_roles, Role.READER)
    granter = verified(staying)
    number = _asked(user)
    django_mail.outbox.clear()

    held = _Held(monkeypatch, FINALIZING, lambda: _authorize(number, actor))
    authorised, granted = _behind(
        held,
        lambda: services.grant_role(
            actor=granter, user=arriving, role=Role.ADMINISTRATOR, reason="TEST"
        ),
    )

    assert authorised == AUTHORIZED
    assert not isinstance(granted, Exception), granted
    assert arriving.email not in [to for to, _body in _sent()]


# --- A history is read while a recovery is under way ------------------------------------


def _labels(history: selectors.RecoveryHistoryPage) -> list[str]:
    return [entry.label for entry in history.entries]


def test_a_history_is_read_without_waiting_for_an_authorisation_that_is_under_way(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _told(user_with_roles, Role.REVIEWER)
    actor = verified(_told(user_with_roles, Role.ADMINISTRATOR))
    other = verified(_told(user_with_roles, Role.ADMINISTRATOR))
    number = _asked(user)

    held = _Held(monkeypatch, FINALIZING, lambda: _authorize(number, actor))
    # The authorisation holds every lock of a recovery and has not committed.
    # Both pages are read at once, and show what is committed: the request.
    own = _elsewhere(lambda: selectors.recovery_history_of(signed_in(user)))
    every = _elsewhere(lambda: selectors.recoveries_on_record(other))
    last = _elsewhere(lambda: selectors.last_recovery_of(signed_in(user)))
    result = held.finish()

    assert result == AUTHORIZED
    assert _labels(own) == _labels(every) == ["Recovery requested"]
    assert last is None
    after = selectors.recovery_history_of(signed_in(user))
    assert _labels(after) == [
        "Recovery authorised by an Administrator: the second factor was revoked",
        "Recovery requested",
    ]
    assert after.entries[0].actor_email == actor.user.email
    assert selectors.last_recovery_of(signed_in(user)) == after.entries[0].occurred_at


def test_a_history_is_read_without_waiting_for_a_break_glass_action_that_is_under_way(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _told(user_with_roles, Role.ADMINISTRATOR)
    other = verified(_told(user_with_roles, Role.ADMINISTRATOR))
    number = _asked(user)

    held = _Held(monkeypatch, FINALIZING, lambda: _revoke(user, number))
    own = _elsewhere(lambda: selectors.recovery_history_of(signed_in(user)))
    every = _elsewhere(lambda: selectors.recoveries_on_record(other))
    result = held.finish()

    assert result == DONE
    assert _labels(own) == _labels(every) == ["Recovery requested"]
    after = selectors.recoveries_on_record(other)
    assert _labels(after) == [
        "Second factor revoked by the emergency procedure",
        "Recovery requested",
    ]
    assert after.entries[0].actor_email is None
    assert after.entries[0].performed_at_server is True


def test_histories_read_while_recoveries_are_finalised_are_always_whole(
    user_with_roles: UserFactory,
) -> None:
    first = verified(_told(user_with_roles, Role.ADMINISTRATOR))
    second = verified(_told(user_with_roles, Role.ADMINISTRATOR))
    for _ in range(ROUNDS):
        user = _told(user_with_roles, Role.REVIEWER)
        number = _asked(user)

        authorised, own, every = _at_the_same_time(
            partial(_authorize, number, first),
            partial(selectors.recovery_history_of, signed_in(user)),
            partial(selectors.recoveries_on_record, second),
        )

        assert authorised == AUTHORIZED
        assert isinstance(own, selectors.RecoveryHistoryPage)
        assert isinstance(every, selectors.RecoveryHistoryPage)
        # Before the commit or after it, and never something in between.
        assert _labels(own) in (
            ["Recovery requested"],
            [
                "Recovery authorised by an Administrator: the second factor was revoked",
                "Recovery requested",
            ],
        )
        for entry in own.entries:
            assert entry.account_email == user.email
