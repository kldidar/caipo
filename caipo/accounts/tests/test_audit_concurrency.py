"""Audit events written at the same time, on separate database connections (ADR-0018).

The writer takes no lock: which change to a record comes first is settled by
the service that makes the change, which locks the record. These tests commit
their data, because other connections must see it, and the database is
emptied after each of them.
"""

import threading
import uuid
from collections.abc import Callable

import pytest
from django.db import connections, transaction

from caipo.accounts.models import AuditEvent, AuditEventChange, User
from caipo.accounts.selectors import (
    AuditAction,
    AuditField,
    AuditTargetType,
    AuthenticationContext,
)
from caipo.accounts.services import AuditChange, record_audit_event
from caipo.accounts.tests.fixtures import signed_in

pytestmark = [pytest.mark.services, pytest.mark.django_db(transaction=True)]

WAIT_SECONDS = 20
WRITERS = 6
# Visibly synthetic: the identifier of a record that does not exist.
TARGET = uuid.UUID("00000000-0000-4000-8000-000000000001")


@pytest.fixture
def actor() -> AuthenticationContext:
    return signed_in(User.objects.create_user("test.actor@caipo.test"))


def _write(actor: AuthenticationContext, number: int) -> None:
    record_audit_event(
        actor=actor,
        action=AuditAction.UPDATED,
        target_type=AuditTargetType.COUNTRY,
        target_public_id=TARGET,
        changes=[AuditChange(AuditField.NAME_EN, "TEST name", f"TEST name {number}")],
    )


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


def test_writers_at_the_same_time_each_record_their_own_event(
    actor: AuthenticationContext,
) -> None:
    barrier = threading.Barrier(WRITERS)
    outcomes: list[list[object]] = [[] for _ in range(WRITERS)]

    def writer(number: int) -> Callable[[], None]:
        def run() -> None:
            with transaction.atomic():
                barrier.wait(timeout=WAIT_SECONDS)
                _write(actor, number)

        return run

    threads = [_in_thread(writer(number), outcomes[number]) for number in range(WRITERS)]
    for thread in threads:
        thread.join(timeout=WAIT_SECONDS)
        assert not thread.is_alive(), "a writer did not finish"

    assert outcomes == [[None]] * WRITERS
    assert AuditEvent.objects.count() == WRITERS
    assert len(set(AuditEvent.objects.values_list("id", flat=True))) == WRITERS
    by_event = dict(AuditEventChange.objects.values_list("event_id", "new_value"))
    assert sorted(by_event.values()) == [f"TEST name {number}" for number in range(WRITERS)]


def test_a_writer_does_not_wait_for_another_that_has_not_committed(
    actor: AuthenticationContext,
) -> None:
    written = threading.Event()
    finish = threading.Event()
    outcome: list[object] = []

    def hold() -> None:
        with transaction.atomic():
            _write(actor, 1)
            written.set()
            assert finish.wait(timeout=WAIT_SECONDS)

    thread = _in_thread(hold, outcome)
    try:
        assert written.wait(timeout=WAIT_SECONDS), outcome
        with transaction.atomic():
            _write(actor, 2)
        # The other transaction is still open, and this one has committed.
        assert list(AuditEventChange.objects.values_list("new_value", flat=True)) == ["TEST name 2"]
    finally:
        finish.set()
        thread.join(timeout=WAIT_SECONDS)

    assert outcome == [None]
    assert AuditEvent.objects.count() == 2


def test_a_writer_that_is_rolled_back_leaves_the_others_event(
    actor: AuthenticationContext,
) -> None:
    class ChangeFailed(Exception):
        pass

    written = threading.Event()
    finish = threading.Event()
    outcome: list[object] = []

    def fail() -> None:
        with transaction.atomic():
            _write(actor, 1)
            written.set()
            assert finish.wait(timeout=WAIT_SECONDS)
            raise ChangeFailed

    thread = _in_thread(fail, outcome)
    try:
        assert written.wait(timeout=WAIT_SECONDS), outcome
        with transaction.atomic():
            _write(actor, 2)
    finally:
        finish.set()
        thread.join(timeout=WAIT_SECONDS)

    assert len(outcome) == 1 and isinstance(outcome[0], ChangeFailed)
    assert list(AuditEventChange.objects.values_list("new_value", flat=True)) == ["TEST name 2"]
    assert AuditEvent.objects.count() == 1
