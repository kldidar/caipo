"""Account changes made at the same time, on separate database connections.

These tests commit their data, because other connections must see it, and the
database is emptied after each of them.
"""

import threading
import time
from collections.abc import Callable

import pytest
from django.core.exceptions import PermissionDenied
from django.db import connection, connections, transaction

from caipo.accounts import selectors, services
from caipo.accounts.models import RoleEvent, RoleEventType, User
from caipo.accounts.selectors import Role
from caipo.accounts.tests.fixtures import UserFactory

pytestmark = [
    pytest.mark.services,
    pytest.mark.django_db(transaction=True),
    pytest.mark.usefixtures("mfa_enrolled"),
]

REASON = "TEST concurrent change"
WAIT_SECONDS = 20


def _in_thread(operation: Callable[[], object], outcome: list[object]) -> threading.Thread:
    """Start an operation on its own connection, recording its result or its exception."""

    def run() -> None:
        try:
            outcome.append(operation())
        except Exception as error:  # recorded and asserted on by the test, not hidden
            outcome.append(error)
        finally:
            connections.close_all()

    thread = threading.Thread(target=run)
    thread.start()
    return thread


def _at_the_same_time(*operations: Callable[[], object]) -> list[object]:
    """Run the operations together and return each one's result or exception, in order."""
    barrier = threading.Barrier(len(operations))
    outcomes: list[list[object]] = [[] for _ in operations]

    def released(operation: Callable[[], object]) -> Callable[[], object]:
        def run() -> object:
            barrier.wait(timeout=WAIT_SECONDS)
            return operation()

        return run

    threads = [
        _in_thread(released(operation), outcome)
        for operation, outcome in zip(operations, outcomes, strict=True)
    ]
    for thread in threads:
        thread.join(timeout=WAIT_SECONDS)
        assert not thread.is_alive(), "an operation did not finish"
    return [outcome[0] for outcome in outcomes]


def _connections_waiting_for_the_lock() -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_locks"
            " WHERE NOT granted AND relation = 'accounts_roleevent'::regclass"
        )
        (waiting,) = cursor.fetchone()
    return int(waiting)


def _wait_until_one_connection_waits_for_the_lock() -> None:
    deadline = time.monotonic() + WAIT_SECONDS
    while _connections_waiting_for_the_lock() == 0:
        assert time.monotonic() < deadline, "no operation ever waited for the lock"
        time.sleep(0.02)


class _ChangeInProgress:
    """Another account change that has taken the lock and not yet committed."""

    def __init__(self, change: Callable[[], object] = lambda: None) -> None:
        self._change = change
        self._holding = threading.Event()
        self._finish = threading.Event()
        self._outcome: list[object] = []

    def __enter__(self) -> _ChangeInProgress:
        def hold() -> None:
            with transaction.atomic():
                services._serialize_account_changes()
                self._change()
                self._holding.set()
                self._finish.wait(timeout=WAIT_SECONDS)

        self._thread = _in_thread(hold, self._outcome)
        assert self._holding.wait(timeout=WAIT_SECONDS), self._outcome
        return self

    def commit(self) -> None:
        self._finish.set()
        self._thread.join(timeout=WAIT_SECONDS)
        assert self._outcome == [None], self._outcome

    def __exit__(self, *exc_info: object) -> None:
        self._finish.set()
        self._thread.join(timeout=WAIT_SECONDS)


def _kinds(outcomes: list[object]) -> set[str]:
    return {type(outcome).__name__ for outcome in outcomes}


def _administrators() -> set[int]:
    return {
        user.pk
        for user in User.objects.filter(is_active=True)
        if Role.ADMINISTRATOR in selectors.roles_of(user)
    }


@pytest.mark.parametrize("operation", ["grant", "revoke", "deactivate"])
def test_a_change_waits_for_one_already_in_progress(
    user_with_roles: UserFactory, operation: str
) -> None:
    administrator = user_with_roles(Role.ADMINISTRATOR)
    user = user_with_roles(Role.READER)
    operations: dict[str, Callable[[], object]] = {
        "grant": lambda: services.grant_role(
            actor=administrator, user=user, role=Role.RESEARCHER, reason=REASON
        ),
        "revoke": lambda: services.revoke_role(
            actor=administrator, user=user, role=Role.READER, reason=REASON
        ),
        "deactivate": lambda: services.deactivate_user(actor=administrator, user=user),
    }
    outcome: list[object] = []

    with _ChangeInProgress() as other:
        thread = _in_thread(operations[operation], outcome)
        _wait_until_one_connection_waits_for_the_lock()
        assert outcome == [], "the operation must not finish while another is in progress"
        other.commit()
        thread.join(timeout=WAIT_SECONDS)

    assert len(outcome) == 1
    assert not isinstance(outcome[0], Exception), outcome


def test_the_permission_is_decided_after_waiting_not_before(
    user_with_roles: UserFactory,
) -> None:
    administrator = user_with_roles(Role.ADMINISTRATOR)
    target = user_with_roles()
    seeder = User.objects.get(email="test.seed@caipo.test")
    outcome: list[object] = []

    def revoke_the_administrator() -> None:
        RoleEvent.objects.create(
            user=administrator,
            role=Role.ADMINISTRATOR,
            event_type=RoleEventType.REVOKED,
            actor=seeder,
            reason=REASON,
        )

    with _ChangeInProgress(revoke_the_administrator) as other:
        # Still an Administrator as far as any other connection can see.
        assert selectors.can(administrator, selectors.Permission.ROLES_MANAGE)
        thread = _in_thread(
            lambda: services.grant_role(
                actor=administrator, user=target, role=Role.ADMINISTRATOR, reason=REASON
            ),
            outcome,
        )
        _wait_until_one_connection_waits_for_the_lock()
        other.commit()
        thread.join(timeout=WAIT_SECONDS)

    assert isinstance(outcome[0], PermissionDenied), outcome
    assert selectors.roles_of(target) == frozenset()


def test_two_administrators_revoking_each_other_leave_one(user_with_roles: UserFactory) -> None:
    first = user_with_roles(Role.ADMINISTRATOR)
    second = user_with_roles(Role.ADMINISTRATOR)

    outcomes = _at_the_same_time(
        lambda: services.revoke_role(
            actor=first, user=second, role=Role.ADMINISTRATOR, reason=REASON
        ),
        lambda: services.revoke_role(
            actor=second, user=first, role=Role.ADMINISTRATOR, reason=REASON
        ),
    )

    assert _kinds(outcomes) == {"RoleEvent", "PermissionDenied"}
    assert len(_administrators()) == 1


def test_two_administrators_deactivating_themselves_leave_one(
    user_with_roles: UserFactory,
) -> None:
    first = user_with_roles(Role.ADMINISTRATOR)
    second = user_with_roles(Role.ADMINISTRATOR)

    outcomes = _at_the_same_time(
        lambda: services.deactivate_user(actor=first, user=first),
        lambda: services.deactivate_user(actor=second, user=second),
    )

    assert _kinds(outcomes) == {"NoneType", "LastAdministratorError"}
    assert len(_administrators()) == 1


def test_two_administrators_deactivating_each_other_leave_one(
    user_with_roles: UserFactory,
) -> None:
    first = user_with_roles(Role.ADMINISTRATOR)
    second = user_with_roles(Role.ADMINISTRATOR)

    outcomes = _at_the_same_time(
        lambda: services.deactivate_user(actor=first, user=second),
        lambda: services.deactivate_user(actor=second, user=first),
    )

    assert _kinds(outcomes) == {"NoneType", "PermissionDenied"}
    assert len(_administrators()) == 1


def test_the_same_grant_made_twice_at_once_is_recorded_once(
    user_with_roles: UserFactory,
) -> None:
    first = user_with_roles(Role.ADMINISTRATOR)
    second = user_with_roles(Role.ADMINISTRATOR)
    user = user_with_roles()

    outcomes = _at_the_same_time(
        lambda: services.grant_role(actor=first, user=user, role=Role.REVIEWER, reason=REASON),
        lambda: services.grant_role(actor=second, user=user, role=Role.REVIEWER, reason=REASON),
    )

    assert _kinds(outcomes) == {"RoleEvent", "RoleChangeError"}
    assert RoleEvent.objects.filter(user=user).count() == 1
    assert selectors.roles_of(user) == {Role.REVIEWER}


def test_a_grant_and_a_revoke_of_the_same_role_at_once_leave_a_consistent_record(
    user_with_roles: UserFactory,
) -> None:
    first = user_with_roles(Role.ADMINISTRATOR)
    second = user_with_roles(Role.ADMINISTRATOR)
    user = user_with_roles(Role.READER)

    outcomes = _at_the_same_time(
        lambda: services.revoke_role(actor=first, user=user, role=Role.READER, reason=REASON),
        lambda: services.grant_role(actor=second, user=user, role=Role.READER, reason=REASON),
    )

    history = list(
        RoleEvent.objects.filter(user=user).order_by("id").values_list("event_type", flat=True)
    )
    # Whichever ran first, each event follows from the state the previous one left.
    assert history in (["granted", "revoked"], ["granted", "revoked", "granted"])
    assert isinstance(outcomes[0], RoleEvent)
    assert (Role.READER in selectors.roles_of(user)) == (history[-1] == "granted")
