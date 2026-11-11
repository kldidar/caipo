"""Where a registry name or an institution's dates were read (ADR-0023)."""

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from caipo.accounts.models import AuditEvent
from caipo.accounts.selectors import AuthenticationContext, Role
from caipo.core.append_only import AppendOnlyError
from caipo.registry import selectors, services
from caipo.registry.models import Institution, InstitutionName, RegistryCitation
from caipo.registry.services import (
    Citation,
    CitationExistsError,
    DirectionControlError,
    InvalidEntryError,
    NewName,
    RecordNotFoundError,
)
from caipo.registry.tests.helpers import TEST_SOURCE, ActingAs, names_of, reference_records

pytestmark = [pytest.mark.services, pytest.mark.django_db]

D1, D2 = date(2001, 2, 3), date(2002, 3, 4)
BAD_SOURCES: list[Any] = [
    None,
    "https://source.example/",
    replace(TEST_SOURCE, url="javascript:alert(1)"),
    replace(TEST_SOURCE, url="ftp://source.example/file"),
    replace(TEST_SOURCE, url="https://source.example/a page"),
    replace(TEST_SOURCE, url="https://" + "a" * 2049),
    replace(TEST_SOURCE, url=""),
    replace(TEST_SOURCE, title="   "),
    replace(TEST_SOURCE, title="T" * 501),
    replace(TEST_SOURCE, title="TEST \x00 title"),
    replace(TEST_SOURCE, accessed_on=datetime(2026, 1, 2, tzinfo=UTC)),
    Citation(TEST_SOURCE.url, TEST_SOURCE.title, "2026-01-02"),  # type: ignore[arg-type]  # a wrong type is what is tested
]
UNCHANGED: dict[str, Any] = {"kind": "ministry", "country": None, "parent": None, "successor": None}


class Records:
    def __init__(self, actor: AuthenticationContext) -> None:
        countries, languages = reference_records(actor)
        self.country, self.language = countries[0], languages[0]


@pytest.fixture
def records(administrator: AuthenticationContext) -> Records:
    return Records(administrator)


@pytest.fixture
def researcher(acting_as: ActingAs) -> AuthenticationContext:
    return acting_as(Role.RESEARCHER)


def _name(records: Records, source: Any = TEST_SOURCE, text: str = "TEST Ministry") -> NewName:
    return NewName(text=text, language=records.language, kind="official", source=source)


def _create(actor: AuthenticationContext, records: Records, **values: Any) -> uuid.UUID:
    return services.create_institution(
        actor=actor, kind="ministry", first_name=_name(records), **values
    )


def _create_with(actor: AuthenticationContext, records: Records, source: Citation) -> uuid.UUID:
    return services.create_institution(
        actor=actor, kind="ministry", first_name=_name(records, source)
    )


def _counts() -> tuple[int, int, int, int]:
    return (
        RegistryCitation.objects.count(),
        Institution.objects.count(),
        InstitutionName.objects.count(),
        AuditEvent.objects.count(),
    )


# --- Names -----------------------------------------------------------------------


def test_a_new_name_is_stored_with_its_source_as_entered(
    researcher: AuthenticationContext, records: Records
) -> None:
    source = Citation("  https://source.example/page?a=1  ", "  TEST Page title  ", D1)

    public_id = _create_with(researcher, records, source)

    (name,) = InstitutionName.objects.filter(institution__public_id=public_id)
    assert name.citation is not None
    assert (name.citation.url, name.citation.title, name.citation.accessed_on) == (
        "https://source.example/page?a=1",
        "TEST Page title",
        D1,
    )
    (entry,) = selectors.institutions(researcher)
    assert entry.names[0].source == selectors.CitationEntry(
        "https://source.example/page?a=1", "TEST Page title", D1
    )


@pytest.mark.parametrize("source", BAD_SOURCES)
def test_a_name_without_a_valid_source_is_refused_and_nothing_is_stored(
    researcher: AuthenticationContext, records: Records, source: Any
) -> None:
    owner = _create(researcher, records)
    before = _counts()

    with pytest.raises(InvalidEntryError):
        services.add_institution_name(
            actor=researcher, institution=owner, name=_name(records, source, "TEST Other")
        )

    assert _counts() == before


def test_a_source_read_on_a_day_to_come_is_refused(
    researcher: AuthenticationContext, records: Records
) -> None:
    tomorrow = timezone.localdate() + timedelta(days=1)

    with pytest.raises(InvalidEntryError, match="still to come"):
        _create_with(researcher, records, replace(TEST_SOURCE, accessed_on=tomorrow))


def test_a_source_title_with_a_direction_control_is_refused(
    researcher: AuthenticationContext, records: Records
) -> None:
    with pytest.raises(DirectionControlError):
        _create_with(researcher, records, replace(TEST_SOURCE, title="TEST ‮ title"))


# --- An institution's dates ----------------------------------------------------------


def test_dates_are_entered_with_their_source(
    researcher: AuthenticationContext, records: Records
) -> None:
    before = _counts()
    with pytest.raises(InvalidEntryError, match="source"):
        _create(researcher, records, valid_from=D1)
    assert _counts() == before

    public_id = _create(researcher, records, valid_from=D1, dates_source=TEST_SOURCE)

    institution = Institution.objects.get(public_id=public_id)
    assert institution.dates_citation is not None
    assert institution.dates_citation.title == TEST_SOURCE.title


def test_an_undated_institution_records_no_source_of_dates(
    researcher: AuthenticationContext, records: Records
) -> None:
    public_id = _create(researcher, records, dates_source=TEST_SOURCE)

    assert Institution.objects.get(public_id=public_id).dates_citation is None
    # Only the name's.
    assert RegistryCitation.objects.count() == 1


def test_a_change_of_a_date_needs_a_source_and_records_the_new_one(
    researcher: AuthenticationContext, records: Records
) -> None:
    public_id = _create(researcher, records, valid_from=D1, dates_source=TEST_SOURCE)
    first = Institution.objects.get(public_id=public_id).dates_citation
    before = _counts()

    with pytest.raises(InvalidEntryError, match="source"):
        services.change_institution(
            actor=researcher, public_id=public_id, valid_from=D1, valid_to=D2, **UNCHANGED
        )
    assert _counts() == before

    services.change_institution(
        actor=researcher,
        public_id=public_id,
        valid_from=D1,
        valid_to=D2,
        dates_source=replace(TEST_SOURCE, title="TEST Later page"),
        **UNCHANGED,
    )

    second = Institution.objects.get(public_id=public_id).dates_citation
    assert first is not None and second is not None
    assert second.title == "TEST Later page"
    # The first citation stays: a source is never changed in place.
    assert RegistryCitation.objects.filter(pk=first.pk).exists()
    changes = set(AuditEvent.objects.latest("id").changes.values_list("field", "old_value"))
    assert ("dates_citation", str(first.public_id)) in changes


def test_a_change_of_no_date_keeps_the_source_of_the_dates(
    researcher: AuthenticationContext, records: Records
) -> None:
    public_id = _create(researcher, records, valid_from=D1, dates_source=TEST_SOURCE)
    first = Institution.objects.get(public_id=public_id).dates_citation

    services.change_institution(
        actor=researcher,
        public_id=public_id,
        kind="regulator",
        country=None,
        parent=None,
        successor=None,
        valid_from=D1,
        valid_to=None,
        dates_source=replace(TEST_SOURCE, title="TEST Unused"),
    )

    assert Institution.objects.get(public_id=public_id).dates_citation == first
    assert not RegistryCitation.objects.filter(title="TEST Unused").exists()


def test_clearing_both_dates_clears_their_source(
    researcher: AuthenticationContext, records: Records
) -> None:
    public_id = _create(researcher, records, valid_from=D1, dates_source=TEST_SOURCE)
    first = Institution.objects.get(public_id=public_id).dates_citation
    assert first is not None

    services.change_institution(
        actor=researcher, public_id=public_id, valid_from=None, valid_to=None, **UNCHANGED
    )

    assert Institution.objects.get(public_id=public_id).dates_citation is None
    changes = set(
        AuditEvent.objects.latest("id").changes.values_list("field", "old_value", "new_value")
    )
    assert ("dates_citation", str(first.public_id), "") in changes


# --- A source for a name entered before ADR-0023 --------------------------------------


def _unsourced_name(actor: AuthenticationContext, records: Records) -> uuid.UUID:
    """A name as one entered before migration 0003 is: a row without a source.

    Written past the services, as such a name was: they now refuse a name
    without a source.
    """
    owner = Institution.objects.get(public_id=_create(actor, records))
    name = InstitutionName.objects.create(
        institution=owner,
        text="TEST Older name",
        language=InstitutionName.objects.get(institution=owner).language,
        kind="abbreviation",
    )
    return name.public_id


def test_a_source_is_added_once_to_a_name_that_has_none_and_is_audited(
    researcher: AuthenticationContext, records: Records
) -> None:
    name = _unsourced_name(researcher, records)

    services.add_institution_name_source(actor=researcher, public_id=name, source=TEST_SOURCE)

    citation = InstitutionName.objects.get(public_id=name).citation
    assert citation is not None
    event = AuditEvent.objects.latest("id")
    assert (event.action, event.target_type, event.target_public_id) == (
        "updated",
        "registry.institution_name",
        name,
    )
    assert list(event.changes.values_list("field", "old_value", "new_value")) == [
        ("citation", "", str(citation.public_id))
    ]
    with pytest.raises(CitationExistsError):
        services.add_institution_name_source(actor=researcher, public_id=name, source=TEST_SOURCE)


def test_a_name_with_a_source_is_not_given_another(
    researcher: AuthenticationContext, records: Records
) -> None:
    (name,) = names_of(_create(researcher, records))
    before = _counts()

    with pytest.raises(CitationExistsError):
        services.add_institution_name_source(actor=researcher, public_id=name, source=TEST_SOURCE)

    assert _counts() == before


def test_a_name_marked_as_entered_in_error_is_not_given_a_source(
    researcher: AuthenticationContext, records: Records
) -> None:
    name = _unsourced_name(researcher, records)
    services.mark_institution_name_entered_in_error(actor=researcher, public_id=name)

    with pytest.raises(InvalidEntryError, match="entered in error"):
        services.add_institution_name_source(actor=researcher, public_id=name, source=TEST_SOURCE)


def test_adding_a_source_needs_the_permission_before_the_name_is_looked_up(
    acting_as: ActingAs, researcher: AuthenticationContext, records: Records
) -> None:
    name = _unsourced_name(researcher, records)
    reader = acting_as(Role.READER)

    for public_id in (name, uuid.UUID(int=7)):
        with pytest.raises(PermissionDenied):
            services.add_institution_name_source(
                actor=reader, public_id=public_id, source=TEST_SOURCE
            )
    with pytest.raises(RecordNotFoundError):
        services.add_institution_name_source(
            actor=researcher, public_id=uuid.UUID(int=7), source=TEST_SOURCE
        )
    assert InstitutionName.objects.get(public_id=name).citation is None


# --- The database ---------------------------------------------------------------------


def test_a_citation_is_never_changed_or_deleted(
    researcher: AuthenticationContext, records: Records
) -> None:
    _create(researcher, records)
    citation = RegistryCitation.objects.get()

    with pytest.raises(AppendOnlyError):
        citation.save()
    with pytest.raises(AppendOnlyError):
        RegistryCitation.objects.all().delete()
    for statement in (
        "UPDATE registry_registrycitation SET title = 'TEST Other'",
        "DELETE FROM registry_registrycitation",
    ):
        with pytest.raises(IntegrityError, match="append-only"), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(statement)

    assert RegistryCitation.objects.get().title == TEST_SOURCE.title


@pytest.mark.parametrize("to_null", [False, True])
def test_a_names_source_once_set_is_never_changed(
    researcher: AuthenticationContext, records: Records, to_null: bool
) -> None:
    owner = _create(researcher, records)
    services.add_institution_name(
        actor=researcher, institution=owner, name=_name(records, text="TEST Other")
    )
    first, second = InstitutionName.objects.order_by("id")
    value = None if to_null else second.citation_id

    with pytest.raises(IntegrityError, match="set once"), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE registry_institutionname SET citation_id = %s WHERE id = %s",
                [value, first.pk],
            )


@pytest.mark.parametrize(
    ("url", "title"),
    [("javascript:alert(1)", "TEST"), ("https://source.example/", "")],
)
def test_the_database_refuses_a_citation_of_the_wrong_form(url: str, title: str) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        RegistryCitation.objects.create(url=url, title=title, accessed_on=D1)
