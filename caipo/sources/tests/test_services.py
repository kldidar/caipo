"""The services of the demonstrator's sources and documents (ADR-0020)."""

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection, transaction

from caipo.accounts.selectors import AuthenticationContext, Role
from caipo.core.data_class import is_synthetic_country
from caipo.core.entry import DataClassError, InvalidEntryError, RecordNotFoundError
from caipo.registry.tests.helpers import ActingAs
from caipo.sources import selectors, services
from caipo.sources.models import Document, Source
from caipo.sources.tests.helpers import (
    UNKNOWN,
    World,
    audit_events,
    make_document,
    make_source,
    source_values,
)

pytestmark = pytest.mark.django_db


# --- The synthetic-country rule -----------------------------------------------------------------


@pytest.mark.parametrize("code", ["AA", "ZZ", "QM", "QZ", "XA", "XZ"])
def test_user_assigned_codes_are_synthetic(code: str) -> None:
    assert is_synthetic_country(code)


@pytest.mark.parametrize("code", ["TM", "UZ", "KZ", "OA", "QL", "XX0", "xa"])
def test_other_codes_are_not_synthetic(code: str) -> None:
    assert not is_synthetic_country(code)


# --- Sources -------------------------------------------------------------------------------------


@pytest.mark.parametrize("data_class", ["demonstration", "reference"])
def test_a_researcher_registers_a_source_with_its_audit_event(
    researcher: AuthenticationContext, world: World, data_class: str
) -> None:
    public_id = make_source(researcher, world, data_class)

    source = Source.objects.get(public_id=public_id)
    assert source.data_class == data_class
    assert source.url == "https://source.example/"
    assert audit_events("sources.source") == [("created", public_id)]


def test_a_reader_may_not_register_a_source(reader: AuthenticationContext, world: World) -> None:
    with pytest.raises(PermissionDenied):
        make_source(reader, world)
    assert not Source.objects.exists()


def test_an_administrator_may_not_register_a_source(acting_as: ActingAs, world: World) -> None:
    with pytest.raises(PermissionDenied):
        make_source(acting_as(Role.ADMINISTRATOR, second_factor=True), world)


@pytest.mark.parametrize(
    ("data_class", "country_attribute"),
    [("demonstration", "reference_country"), ("reference", "demo_country")],
)
def test_data_classes_are_never_given_the_wrong_kind_of_country(
    researcher: AuthenticationContext, world: World, data_class: str, country_attribute: str
) -> None:
    values = source_values(world, data_class, country=getattr(world, country_attribute))

    with pytest.raises(DataClassError):
        services.create_source(actor=researcher, **values)
    assert not Source.objects.exists()
    assert audit_events("sources.source") == []


@pytest.mark.parametrize(
    "changes",
    [
        {"url": "javascript:alert(1)"},
        {"url": "ftp://files.example/"},
        {"url": ""},
        {"name": "   "},
        {"publisher": ""},
        {"source_tier": "H"},
        {"permitted_use": "anything"},
        {"data_class": "real"},
        {"licence_verified": True, "licence": ""},
        {"name": "TEST ‮ reversed"},
    ],
)
def test_an_unacceptable_source_is_refused(
    researcher: AuthenticationContext, world: World, changes: dict[str, object]
) -> None:
    with pytest.raises(InvalidEntryError):
        services.create_source(actor=researcher, **source_values(world, **changes))
    assert not Source.objects.exists()


def test_an_unknown_country_is_refused(researcher: AuthenticationContext, world: World) -> None:
    with pytest.raises(RecordNotFoundError):
        services.create_source(actor=researcher, **source_values(world, country=UNKNOWN))


def test_a_source_need_not_have_a_country(researcher: AuthenticationContext, world: World) -> None:
    public_id = services.create_source(
        actor=researcher, **source_values(world, "reference", country=None)
    )

    assert Source.objects.get(public_id=public_id).country is None


# --- Documents -----------------------------------------------------------------------------------


def test_a_document_takes_the_data_class_of_its_source(
    researcher: AuthenticationContext, world: World
) -> None:
    source = make_source(researcher, world, "reference")

    public_id = make_document(researcher, world, source, "reference")

    document = Document.objects.get(public_id=public_id)
    assert document.data_class == "reference"
    assert audit_events("sources.document") == [("created", public_id)]


def test_a_document_of_a_demonstration_source_cannot_belong_to_a_real_country(
    researcher: AuthenticationContext, world: World
) -> None:
    source = make_source(researcher, world)

    with pytest.raises(DataClassError):
        make_document(researcher, world, source, country=world.reference_country)
    assert not Document.objects.exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"title": ""},
        {"document_type": "poem"},
        {"official_url": "data:text/html,x"},
        {"title_en_official": True, "title_en": ""},
    ],
)
def test_an_unacceptable_document_is_refused(
    researcher: AuthenticationContext, world: World, changes: dict[str, object]
) -> None:
    source = make_source(researcher, world)

    with pytest.raises(InvalidEntryError):
        make_document(researcher, world, source, **changes)
    assert not Document.objects.exists()


@pytest.mark.parametrize("missing", ["source", "title_language", "issuing_institution"])
def test_a_document_naming_an_unknown_record_is_refused(
    researcher: AuthenticationContext, world: World, missing: str
) -> None:
    source = make_source(researcher, world)

    with pytest.raises(RecordNotFoundError):
        make_document(researcher, world, source, **{missing: UNKNOWN})


def test_a_reader_may_not_register_a_document(
    researcher: AuthenticationContext, reader: AuthenticationContext, world: World
) -> None:
    source = make_source(researcher, world)

    with pytest.raises(PermissionDenied):
        make_document(reader, world, source)


def test_the_text_is_normalised_and_never_otherwise_changed(
    researcher: AuthenticationContext, world: World
) -> None:
    source = make_source(researcher, world)

    public_id = make_document(researcher, world, source, title="  TEST Café Décret  ")

    assert Document.objects.get(public_id=public_id).title == "TEST Café Décret"


# --- Reading -------------------------------------------------------------------------------------


def test_a_reader_reads_sources_and_their_documents(
    researcher: AuthenticationContext, reader: AuthenticationContext, world: World
) -> None:
    source = make_source(researcher, world)
    make_document(researcher, world, source)

    listed = selectors.sources(reader)
    detail = selectors.source_detail(reader, source)

    assert [entry.document_count for entry in listed] == [1]
    assert detail is not None and len(detail.documents) == 1
    assert detail.documents[0].source_name == "TEST Source"
    assert selectors.source_detail(reader, UNKNOWN) is None


def test_an_account_without_workspace_access_reads_nothing(acting_as: ActingAs) -> None:
    administrator = acting_as(Role.ADMINISTRATOR, second_factor=True)

    with pytest.raises(PermissionDenied):
        selectors.sources(administrator)


# --- The database keeps the rules ----------------------------------------------------------------


def test_nothing_is_deleted(researcher: AuthenticationContext, world: World) -> None:
    source = make_source(researcher, world)
    make_document(researcher, world, source)

    for table in ("sources_document", "sources_source"):
        with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed table names


@pytest.mark.parametrize(
    "changes",
    [
        {"data_class": "real"},
        {"source_tier": "Z"},
        {"url": "javascript:x"},
        {"licence_verified": True, "licence": ""},
    ],
)
def test_the_database_refuses_a_source_the_service_would_refuse(
    world: World, changes: dict[str, object]
) -> None:
    values: dict[str, object] = {
        "data_class": "demonstration",
        "name": "TEST",
        "publisher": "TEST",
        "url": "https://x.example/",
        "source_tier": "A",
        "permitted_use": "store",
        "accessed_on": "2026-01-01",
    }
    values.update(changes)
    with pytest.raises(IntegrityError), transaction.atomic():
        Source.objects.create(**values)
