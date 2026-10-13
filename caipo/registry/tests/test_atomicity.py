"""A registry change and its audit event are committed together or not at all
(ADR-0018 points 39 and 42, testing requirement 2).

These tests commit their data, because a test transaction around a service
would hide whether the service's own transaction was rolled back, and the
database is emptied after each of them.
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from django.db import DataError, IntegrityError, transaction

from caipo.accounts.models import AuditEvent, AuditEventChange
from caipo.accounts.selectors import AuthenticationContext
from caipo.accounts.services import AuditRecordError
from caipo.registry import services
from caipo.registry.models import Country, Language
from caipo.registry.services import DuplicateCodeError
from caipo.registry.tests.helpers import changes, events, stored

pytestmark = [pytest.mark.services, pytest.mark.django_db(transaction=True)]

type Operation = Callable[[AuthenticationContext, uuid.UUID, uuid.UUID], object]


def _country(actor: AuthenticationContext) -> uuid.UUID:
    return services.create_country(actor=actor, alpha2="XA", alpha3="XAA", name_en="TEST Country A")


def _language(actor: AuthenticationContext) -> uuid.UUID:
    return services.create_language(
        actor=actor, code="qaa", script_code="Qaaa", name_en="TEST Language A"
    )


# Every operation, given an existing country and language to act on. The
# creations make a second record of their kind.
OPERATIONS: dict[str, Operation] = {
    "create_country": lambda actor, country, language: services.create_country(
        actor=actor, alpha2="XB", alpha3="XBB", name_en="TEST Country B"
    ),
    "rename_country": lambda actor, country, language: services.rename_country(
        actor=actor, public_id=country, name_en="TEST Renamed"
    ),
    "deactivate_country": lambda actor, country, language: services.deactivate_country(
        actor=actor, public_id=country
    ),
    "create_language": lambda actor, country, language: services.create_language(
        actor=actor, code="qab", script_code="Qaab", name_en="TEST Language B"
    ),
    "rename_language": lambda actor, country, language: services.rename_language(
        actor=actor, public_id=language, name_en="TEST Renamed"
    ),
    "deactivate_language": lambda actor, country, language: services.deactivate_language(
        actor=actor, public_id=language
    ),
}
EXPECTED_ACTION = {
    "create_country": "created",
    "rename_country": "updated",
    "deactivate_country": "deactivated",
    "create_language": "created",
    "rename_language": "updated",
    "deactivate_language": "deactivated",
}


def _reactivations(
    actor: AuthenticationContext, country: uuid.UUID, language: uuid.UUID
) -> dict[str, Operation]:
    """Deactivate both records, and return the two operations that undo it."""
    services.deactivate_country(actor=actor, public_id=country)
    services.deactivate_language(actor=actor, public_id=language)
    return {
        "reactivate_country": lambda actor, country, language: services.reactivate_country(
            actor=actor, public_id=country
        ),
        "reactivate_language": lambda actor, country, language: services.reactivate_language(
            actor=actor, public_id=language
        ),
    }


# --- Success: both are present ------------------------------------------------


@pytest.mark.parametrize("operation", OPERATIONS)
def test_after_a_change_both_the_change_and_its_event_are_committed(
    administrator: AuthenticationContext, operation: str
) -> None:
    country, language = _country(administrator), _language(administrator)
    before = stored()

    OPERATIONS[operation](administrator, country, language)

    after = stored()
    assert (after["countries"], after["languages"]) != (before["countries"], before["languages"])
    assert [action for action, _, _, _ in events()[2:]] == [EXPECTED_ACTION[operation]]
    assert not transaction.get_connection().in_atomic_block


@pytest.mark.parametrize("operation", ["reactivate_country", "reactivate_language"])
def test_after_a_reactivation_both_the_change_and_its_event_are_committed(
    administrator: AuthenticationContext, operation: str
) -> None:
    country, language = _country(administrator), _language(administrator)
    reactivate = _reactivations(administrator, country, language)[operation]

    reactivate(administrator, country, language)

    assert [action for action, _, _, _ in events()[4:]] == ["reactivated"]
    model: Any = Country if operation == "reactivate_country" else Language
    assert model.objects.get().is_active


# --- The audit write fails: the change is absent ------------------------------


def _refuse_the_event(**_: object) -> None:
    raise AuditRecordError("TEST the audit event was refused")


@pytest.mark.parametrize("operation", OPERATIONS)
def test_when_the_audit_writer_refuses_the_change_is_not_made(
    administrator: AuthenticationContext, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    country, language = _country(administrator), _language(administrator)
    before = stored()
    monkeypatch.setattr("caipo.accounts.services.record_audit_event", _refuse_the_event)

    with pytest.raises(AuditRecordError, match="TEST the audit event was refused"):
        OPERATIONS[operation](administrator, country, language)

    assert stored() == before


@pytest.mark.parametrize("operation", ["reactivate_country", "reactivate_language"])
def test_when_the_audit_writer_refuses_a_reactivation_is_not_made(
    administrator: AuthenticationContext, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    country, language = _country(administrator), _language(administrator)
    reactivate = _reactivations(administrator, country, language)[operation]
    before = stored()
    monkeypatch.setattr("caipo.accounts.services.record_audit_event", _refuse_the_event)

    with pytest.raises(AuditRecordError):
        reactivate(administrator, country, language)

    assert stored() == before


@pytest.mark.parametrize("operation", OPERATIONS)
def test_when_the_database_refuses_the_audit_event_the_change_is_not_made(
    administrator: AuthenticationContext, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """The real writer, failing in the database: a correlation ID too long for its column."""
    country, language = _country(administrator), _language(administrator)
    before = stored()
    monkeypatch.setattr("caipo.accounts.services.get_correlation_id", lambda: "T" * 33)

    with pytest.raises(DataError):
        OPERATIONS[operation](administrator, country, language)

    assert stored() == before


@pytest.mark.parametrize("operation", ["rename_country", "rename_language"])
def test_when_the_database_refuses_the_change_record_neither_the_event_nor_the_change_is_kept(
    administrator: AuthenticationContext, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """The event is written and its change record is refused: the event goes with the rest."""
    country, language = _country(administrator), _language(administrator)
    before = stored()

    def refuse(*args: object, **kwargs: object) -> None:
        raise IntegrityError("TEST the change record was refused")

    monkeypatch.setattr(AuditEventChange.objects, "bulk_create", refuse)

    with pytest.raises(IntegrityError, match="TEST the change record was refused"):
        OPERATIONS[operation](administrator, country, language)

    assert stored() == before
    assert AuditEvent.objects.count() == 2


# --- The change fails on a constraint: no event is present ---------------------


def test_a_country_the_database_refuses_on_a_check_leaves_no_event_and_is_not_called_a_duplicate(
    administrator: AuthenticationContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the service's own check out of the way, the database's check refuses the row.

    The error is the database's, as it is: only a violated uniqueness of a
    code is reported as a code in use.
    """
    monkeypatch.setattr(services, "_require_form", lambda *args: None)

    with pytest.raises(IntegrityError, match="registry_country_alpha2_form") as raised:
        services.create_country(
            actor=administrator, alpha2="xa", alpha3="XAA", name_en="TEST Country"
        )

    assert not isinstance(raised.value, DuplicateCodeError)
    assert stored() == {"countries": [], "languages": [], "events": [], "changes": []}


def test_a_language_the_database_refuses_on_a_check_leaves_no_event_and_is_not_called_a_duplicate(
    administrator: AuthenticationContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(services, "_require_form", lambda *args: None)

    with pytest.raises(IntegrityError, match="registry_language_script_code_form"):
        services.create_language(
            actor=administrator, code="qaa", script_code="QAAA", name_en="TEST Language"
        )

    assert stored() == {"countries": [], "languages": [], "events": [], "changes": []}


@pytest.mark.parametrize(
    ("create", "model", "constraint"),
    [
        (_country, Country, "registry_country_public_id_unique"),
        (_language, Language, "registry_language_public_id_unique"),
    ],
)
def test_a_public_identifier_that_collides_fails_the_creation_and_is_not_called_a_duplicate_code(
    administrator: AuthenticationContext,
    monkeypatch: pytest.MonkeyPatch,
    create: Callable[[AuthenticationContext], uuid.UUID],
    model: Any,
    constraint: str,
) -> None:
    """ADR-0018 point 50: the insert fails and the transaction with it. Nothing retries."""
    taken = create(administrator)
    before = stored()
    monkeypatch.setattr(model._meta.get_field("public_id"), "get_default", lambda: taken)
    other: dict[str, Operation] = {
        "country": OPERATIONS["create_country"],
        "language": OPERATIONS["create_language"],
    }

    with pytest.raises(IntegrityError, match=constraint) as raised:
        other[model._meta.model_name](administrator, taken, taken)

    assert not isinstance(raised.value, DuplicateCodeError)
    assert stored() == before


@pytest.mark.parametrize(
    ("operation", "model"), [("rename_country", Country), ("rename_language", Language)]
)
def test_a_rename_the_database_refuses_leaves_the_name_and_no_event(
    administrator: AuthenticationContext,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    model: Any,
) -> None:
    """With the service's own limit out of the way, the width of the column refuses the name."""
    country, language = _country(administrator), _language(administrator)
    before = stored()
    monkeypatch.setattr(services, "NAME_MAX_LENGTH", 300)
    rename = services.rename_country if operation == "rename_country" else services.rename_language
    public_id = country if operation == "rename_country" else language

    with pytest.raises(DataError):
        rename(actor=administrator, public_id=public_id, name_en="T" * 250)

    assert stored() == before
    assert changes() == []


# --- Inside a caller's transaction ---------------------------------------------


def test_a_change_made_inside_a_transaction_that_fails_leaves_nothing(
    administrator: AuthenticationContext,
) -> None:
    class CallerFailed(Exception):
        pass

    with pytest.raises(CallerFailed), transaction.atomic():
        public_id = _country(administrator)
        services.rename_country(actor=administrator, public_id=public_id, name_en="TEST Renamed")
        raise CallerFailed

    assert stored() == {"countries": [], "languages": [], "events": [], "changes": []}


def test_a_refused_change_inside_a_transaction_leaves_the_transaction_usable(
    administrator: AuthenticationContext,
) -> None:
    """A duplicate is refused at the service's own savepoint, not at the caller's transaction."""
    with transaction.atomic():
        _country(administrator)
        with pytest.raises(DuplicateCodeError):
            _country(administrator)
        _language(administrator)

    assert Country.objects.count() == 1 and Language.objects.count() == 1
    assert [action for action, _, _, _ in events()] == ["created", "created"]
