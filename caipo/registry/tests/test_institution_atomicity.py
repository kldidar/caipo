"""A change to an institution or a name and its audit events are committed together or
not at all (ADR-0018 points 20, 39, and 42; testing requirement 2; ADR-0019 Increment 3).

An institution and its first name are one creation: if anything of it
fails, neither is stored and neither event is.

These tests commit their data, because a test transaction around a service
would hide whether the service's own transaction was rolled back, and the
database is emptied after each of them.
"""

import uuid
from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from django.db import DataError, IntegrityError, transaction

from caipo.accounts import services as accounts_services
from caipo.accounts.models import AuditEvent, AuditEventChange
from caipo.accounts.selectors import AuditTargetType, AuthenticationContext
from caipo.accounts.services import AuditRecordError
from caipo.registry import services
from caipo.registry.models import Institution, InstitutionName
from caipo.registry.services import NewName
from caipo.registry.tests.helpers import (
    events,
    institution,
    names_of,
    stored_with_institutions,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db(transaction=True)]

D1, D2 = date(2001, 2, 3), date(2002, 3, 4)


class Records:
    """A language, and an institution with two names, for the operations to act on."""

    def __init__(self, actor: AuthenticationContext) -> None:
        self.language = services.create_language(
            actor=actor, code="qaa", script_code="Qaaa", name_en="TEST Language A"
        )
        self.institution = institution(actor, self.language)
        services.add_institution_name(
            actor=actor,
            institution=self.institution,
            name=NewName(text="TEST Second name", language=self.language, kind="official"),
        )
        self.name, self.other_name = names_of(self.institution)


@pytest.fixture
def records(administrator: AuthenticationContext) -> Records:
    return Records(administrator)


type Operation = Callable[[AuthenticationContext, Records], object]


def _change(actor: AuthenticationContext, records: Records, **values: Any) -> None:
    services.change_institution(
        actor=actor,
        public_id=records.institution,
        **{
            "kind": "regulator",
            "country": None,
            "parent": None,
            "successor": None,
            "valid_from": None,
            "valid_to": None,
            **values,
        },
    )


OPERATIONS: dict[str, Operation] = {
    "create_institution": lambda actor, records: institution(
        actor, records.language, "TEST New institution"
    ),
    "change_institution": lambda actor, records: _change(actor, records, valid_from=D1),
    "add_institution_name": lambda actor, records: services.add_institution_name(
        actor=actor,
        institution=records.institution,
        name=NewName(text="TEST Third name", language=records.language, kind="official"),
    ),
    "change_institution_name_dates": lambda actor, records: services.change_institution_name_dates(
        actor=actor, public_id=records.name, valid_from=D1, valid_to=D2
    ),
    "mark_institution_name_entered_in_error": lambda actor, records: (
        services.mark_institution_name_entered_in_error(actor=actor, public_id=records.name)
    ),
}
EXPECTED_ACTIONS = {
    "create_institution": ["created", "created"],
    "change_institution": ["updated"],
    "add_institution_name": ["created"],
    "change_institution_name_dates": ["updated"],
    "mark_institution_name_entered_in_error": ["marked_entered_in_error"],
}


# --- Success: both are present ------------------------------------------------


@pytest.mark.parametrize("operation", OPERATIONS)
def test_after_a_change_both_the_change_and_its_events_are_committed(
    administrator: AuthenticationContext, records: Records, operation: str
) -> None:
    before = stored_with_institutions()
    recorded = len(events())

    OPERATIONS[operation](administrator, records)

    assert stored_with_institutions() != before
    assert [action for action, _, _, _ in events()[recorded:]] == EXPECTED_ACTIONS[operation]


# --- The audit write fails: the change is absent -------------------------------


def _refuse_the_event(**_: object) -> None:
    raise AuditRecordError("TEST the audit event was refused")


@pytest.mark.parametrize("operation", OPERATIONS)
def test_when_the_audit_writer_refuses_the_change_is_not_made(
    administrator: AuthenticationContext,
    records: Records,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    before = stored_with_institutions()
    monkeypatch.setattr("caipo.accounts.services.record_audit_event", _refuse_the_event)

    with pytest.raises(AuditRecordError, match="TEST the audit event was refused"):
        OPERATIONS[operation](administrator, records)

    assert stored_with_institutions() == before


def test_when_the_event_of_the_first_name_is_refused_the_institution_is_not_created_either(
    administrator: AuthenticationContext, records: Records, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The institution's own event was written, and goes with everything else."""
    write = accounts_services.record_audit_event
    before = stored_with_institutions()

    def refuse_the_name(**arguments: Any) -> None:
        if arguments["target_type"] == AuditTargetType.INSTITUTION_NAME:
            raise AuditRecordError("TEST the event of the name was refused")
        write(**arguments)

    monkeypatch.setattr("caipo.accounts.services.record_audit_event", refuse_the_name)

    with pytest.raises(AuditRecordError, match="TEST the event of the name was refused"):
        OPERATIONS["create_institution"](administrator, records)

    assert stored_with_institutions() == before
    assert Institution.objects.count() == 1


@pytest.mark.parametrize("operation", OPERATIONS)
def test_when_the_database_refuses_the_audit_event_the_change_is_not_made(
    administrator: AuthenticationContext,
    records: Records,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """The real writer, failing in the database: a correlation ID too long for its column."""
    before = stored_with_institutions()
    monkeypatch.setattr("caipo.accounts.services.get_correlation_id", lambda: "T" * 33)

    with pytest.raises(DataError):
        OPERATIONS[operation](administrator, records)

    assert stored_with_institutions() == before


@pytest.mark.parametrize("operation", ["change_institution", "change_institution_name_dates"])
def test_when_the_database_refuses_a_change_record_neither_the_event_nor_the_change_is_kept(
    administrator: AuthenticationContext,
    records: Records,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    before = stored_with_institutions()
    events_before = AuditEvent.objects.count()

    def refuse(*args: object, **kwargs: object) -> None:
        raise IntegrityError("TEST the change record was refused")

    monkeypatch.setattr(AuditEventChange.objects, "bulk_create", refuse)

    with pytest.raises(IntegrityError, match="TEST the change record was refused"):
        OPERATIONS[operation](administrator, records)

    assert stored_with_institutions() == before
    assert AuditEvent.objects.count() == events_before


# --- The change fails on a constraint: no event is present ---------------------


def test_an_institution_the_database_refuses_on_its_dates_leaves_no_event_and_no_name(
    administrator: AuthenticationContext, records: Records, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the service's own check out of the way, the database's check refuses the row."""
    before = stored_with_institutions()
    monkeypatch.setattr(services, "_valid_period", lambda valid_from, valid_to: (D2, D1))

    with pytest.raises(IntegrityError, match="registry_institution_dates_in_order"):
        OPERATIONS["create_institution"](administrator, records)

    assert stored_with_institutions() == before


def test_a_first_name_the_database_refuses_leaves_no_institution_and_no_event(
    administrator: AuthenticationContext, records: Records, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the service's own limit out of the way, the width of the column refuses the text."""
    before = stored_with_institutions()
    monkeypatch.setattr(services, "INSTITUTION_NAME_MAX_LENGTH", 600)

    with pytest.raises(DataError):
        institution(administrator, records.language, "T" * 550)

    assert stored_with_institutions() == before


@pytest.mark.parametrize(
    ("bypassed", "values", "constraint"),
    [
        (
            "_require_succession",
            {"successor": "other", "valid_to": None},
            "registry_institution_successor_needs_valid_to",
        ),
        ("_require_no_cycle", {"parent": "itself"}, "registry_institution_not_own_parent"),
        (
            "_require_no_cycle",
            {"successor": "itself", "valid_to": D1},
            "registry_institution_not_own_successor",
        ),
    ],
)
def test_a_change_the_database_refuses_on_a_check_leaves_the_institution_and_no_event(
    administrator: AuthenticationContext,
    records: Records,
    monkeypatch: pytest.MonkeyPatch,
    bypassed: str,
    values: dict[str, Any],
    constraint: str,
) -> None:
    other = institution(administrator, records.language, "TEST Other")
    named = {"other": other, "itself": records.institution}
    before = stored_with_institutions()
    monkeypatch.setattr(services, bypassed, lambda *args: None)

    with pytest.raises(IntegrityError, match=constraint):
        _change(
            administrator,
            records,
            **{key: named.get(value, value) for key, value in values.items()},
        )

    assert stored_with_institutions() == before


@pytest.mark.parametrize(
    ("model", "create", "constraint"),
    [
        (Institution, "institution", "registry_institution_public_id_unique"),
        (InstitutionName, "name", "registry_institutionname_public_id_unique"),
    ],
)
def test_a_public_identifier_that_collides_fails_the_creation(
    administrator: AuthenticationContext,
    records: Records,
    monkeypatch: pytest.MonkeyPatch,
    model: Any,
    create: str,
    constraint: str,
) -> None:
    """ADR-0018 point 50: the insert fails and the transaction with it. Nothing retries."""
    taken = records.institution if model is Institution else records.name
    before = stored_with_institutions()
    monkeypatch.setattr(model._meta.get_field("public_id"), "get_default", lambda: taken)

    with pytest.raises(IntegrityError, match=constraint):
        if create == "institution":
            OPERATIONS["create_institution"](administrator, records)
        else:
            OPERATIONS["add_institution_name"](administrator, records)

    assert stored_with_institutions() == before


# --- Inside a caller's transaction ---------------------------------------------


def test_a_change_made_inside_a_transaction_that_fails_leaves_nothing(
    administrator: AuthenticationContext, records: Records
) -> None:
    class CallerFailed(Exception):
        pass

    before = stored_with_institutions()

    with pytest.raises(CallerFailed), transaction.atomic():
        for operation in OPERATIONS.values():
            operation(administrator, records)
        raise CallerFailed

    assert stored_with_institutions() == before


def test_a_refused_change_inside_a_transaction_leaves_the_transaction_usable(
    administrator: AuthenticationContext, records: Records
) -> None:
    """A refusal is raised before anything is written, at the service's own savepoint."""
    with transaction.atomic():
        with pytest.raises(services.CycleError):
            _change(administrator, records, parent=records.institution)
        OPERATIONS["change_institution"](administrator, records)

    assert Institution.objects.get(public_id=records.institution).kind == "regulator"


def test_every_operation_written_once_with_its_event_leaves_a_consistent_record(
    administrator: AuthenticationContext, records: Records
) -> None:
    """After all five, every name has an event that created it, and so does every institution."""
    for operation in OPERATIONS.values():
        operation(administrator, records)

    created = {target for action, _, target, _ in events() if action == "created"}
    assert set(Institution.objects.values_list("public_id", flat=True)) <= created
    assert set(InstitutionName.objects.values_list("public_id", flat=True)) <= created
    assert all(isinstance(target, uuid.UUID) for target in created)
