"""The synthetic text of a demonstration document, as Segments (ADR-0025 point 4)."""

import hashlib
import unicodedata
import uuid
from collections.abc import Sequence

import pytest
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.db.utils import IntegrityError

from caipo.accounts.models import AuditEvent
from caipo.accounts.selectors import AuthenticationContext
from caipo.core.entry import DataClassError, InvalidEntryError, RecordNotFoundError
from caipo.sources import selectors, services
from caipo.sources.models import SEGMENT_MAX_LENGTH, Document, Segment
from caipo.sources.services import TEXT_MAX_PARTS, TextPart
from caipo.sources.tests.helpers import UNKNOWN, World, make_document, make_source

pytestmark = [pytest.mark.services, pytest.mark.django_db]

PARTS = [
    TextPart("Art. 1", "TEST The strategy is approved."),
    TextPart("Art. 2", "TEST A council is established.\n\nIt meets  twice a year."),
]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _document(researcher: AuthenticationContext, world: World, data_class: str) -> uuid.UUID:
    source = make_source(researcher, world, data_class)
    return make_document(researcher, world, source, data_class)


@pytest.fixture
def demo_document(researcher: AuthenticationContext, world: World) -> uuid.UUID:
    return _document(researcher, world, "demonstration")


def _stored(document: uuid.UUID) -> list[tuple[int, str, str, str]]:
    return list(
        Segment.objects.filter(document__public_id=document)
        .order_by("position")
        .values_list("position", "locator", "text", "text_sha256")
    )


def test_a_researcher_attaches_a_text_in_order_with_its_audit_event(
    researcher: AuthenticationContext, demo_document: uuid.UUID
) -> None:
    fingerprint = services.attach_demonstration_text(
        actor=researcher, document=demo_document, parts=PARTS
    )

    assert _stored(demo_document) == [
        (1, "Art. 1", PARTS[0].text, _sha256(PARTS[0].text)),
        (2, "Art. 2", PARTS[1].text, _sha256(PARTS[1].text)),
    ]
    assert fingerprint == _sha256(f"{_sha256(PARTS[0].text)}\n{_sha256(PARTS[1].text)}")
    event = AuditEvent.objects.latest("id")
    assert (event.action, event.target_type, event.target_public_id) == (
        "updated",
        "sources.document",
        demo_document,
    )
    change = event.changes.get()
    assert (change.field, change.old_value, change.new_value) == ("text", "", fingerprint)


def test_a_text_is_held_in_nfc_and_otherwise_as_given(
    researcher: AuthenticationContext, demo_document: uuid.UUID
) -> None:
    decomposed = "  TEST Café policy,\tkept  as written.\n"

    services.attach_demonstration_text(
        actor=researcher, document=demo_document, parts=[TextPart("", decomposed)]
    )

    ((_, _, text, digest),) = _stored(demo_document)
    assert text == unicodedata.normalize("NFC", decomposed)
    assert text != decomposed and text.startswith("  ") and "\t" in text
    assert digest == _sha256(text)


def test_the_text_is_read_back_in_order(
    researcher: AuthenticationContext, demo_document: uuid.UUID
) -> None:
    services.attach_demonstration_text(actor=researcher, document=demo_document, parts=PARTS)

    entries = selectors.document_text(demo_document)

    assert [(e.position, e.locator, e.text) for e in entries] == [
        (1, "Art. 1", PARTS[0].text),
        (2, "Art. 2", PARTS[1].text),
    ]
    assert {e.document for e in entries} == {demo_document}
    assert selectors.document_text(UNKNOWN) == ()


def test_a_reference_document_never_holds_a_text(
    researcher: AuthenticationContext, world: World
) -> None:
    reference = _document(researcher, world, "reference")
    events = AuditEvent.objects.count()

    with pytest.raises(DataClassError):
        services.attach_demonstration_text(actor=researcher, document=reference, parts=PARTS)

    assert _stored(reference) == []
    assert AuditEvent.objects.count() == events


def test_a_text_is_attached_once_and_never_replaced(
    researcher: AuthenticationContext, demo_document: uuid.UUID
) -> None:
    services.attach_demonstration_text(actor=researcher, document=demo_document, parts=PARTS)
    before = _stored(demo_document)
    events = AuditEvent.objects.count()

    with pytest.raises(InvalidEntryError, match="never replaced"):
        services.attach_demonstration_text(
            actor=researcher, document=demo_document, parts=[TextPart("", "TEST other")]
        )

    assert _stored(demo_document) == before
    assert AuditEvent.objects.count() == events


@pytest.mark.parametrize(
    "parts",
    [
        [],
        [TextPart("", "TEST")] * (TEXT_MAX_PARTS + 1),
        [TextPart("Art. 1", "   \n ")],
        [TextPart("Art. 1", "T" * (SEGMENT_MAX_LENGTH + 1))],
        [TextPart("Art. 1", "TEST ‮turned")],
        [TextPart("A" * 201, "TEST")],
        [TextPart("Art. 1", "TEST fine"), TextPart("Art. 2", "")],
    ],
    ids=["none", "too-many", "blank", "too-long", "direction-control", "long-locator", "one-empty"],
)
def test_an_unacceptable_text_is_refused_and_nothing_is_stored(
    researcher: AuthenticationContext, demo_document: uuid.UUID, parts: list[TextPart]
) -> None:
    events = AuditEvent.objects.count()

    with pytest.raises(InvalidEntryError):
        services.attach_demonstration_text(actor=researcher, document=demo_document, parts=parts)

    assert _stored(demo_document) == []
    assert AuditEvent.objects.count() == events


def test_an_unknown_document_is_refused(researcher: AuthenticationContext, world: World) -> None:
    with pytest.raises(RecordNotFoundError):
        services.attach_demonstration_text(actor=researcher, document=UNKNOWN, parts=PARTS)


def test_a_reader_may_not_attach_a_text_and_is_refused_first(
    reader: AuthenticationContext, researcher: AuthenticationContext, demo_document: uuid.UUID
) -> None:
    with pytest.raises(PermissionDenied):
        services.attach_demonstration_text(actor=reader, document=demo_document, parts=PARTS)
    with pytest.raises(PermissionDenied):
        services.attach_demonstration_text(actor=reader, document=UNKNOWN, parts=[])

    assert _stored(demo_document) == []


def _raw(sql: str, params: Sequence[str | int | uuid.UUID]) -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(sql, params)


def _insert(document: uuid.UUID, text: str, digest: str, position: int = 9) -> None:
    _raw(
        "INSERT INTO sources_segment"
        " (public_id, document_id, position, locator, text, text_sha256, created_at)"
        " VALUES (%s, %s, %s, '', %s, %s, now())",
        [uuid.uuid4(), Document.objects.get(public_id=document).pk, position, text, digest],
    )


def test_the_database_refuses_any_change_or_deletion_of_a_segment(
    researcher: AuthenticationContext, demo_document: uuid.UUID
) -> None:
    services.attach_demonstration_text(actor=researcher, document=demo_document, parts=PARTS)
    before = _stored(demo_document)

    with pytest.raises(IntegrityError, match="append-only: UPDATE refused"):
        _raw("UPDATE sources_segment SET text = %s", ["TEST changed"])
    with pytest.raises(IntegrityError, match="append-only: DELETE refused"):
        _raw("DELETE FROM sources_segment", [])

    assert _stored(demo_document) == before


def test_the_database_refuses_a_segment_on_a_reference_document(
    researcher: AuthenticationContext, world: World
) -> None:
    reference = _document(researcher, world, "reference")

    with pytest.raises(IntegrityError, match="only the text of a demonstration document"):
        _insert(reference, "TEST", _sha256("TEST"))


def test_the_database_refuses_a_text_not_in_nfc(demo_document: uuid.UUID) -> None:
    decomposed = "TEST Café"

    with pytest.raises(IntegrityError, match="held in NFC"):
        _insert(demo_document, decomposed, _sha256(decomposed))


def test_the_database_refuses_a_hash_that_does_not_match_the_text(
    demo_document: uuid.UUID,
) -> None:
    with pytest.raises(IntegrityError, match="does not match its text"):
        _insert(demo_document, "TEST", _sha256("TEST other"))
    _insert(demo_document, "TEST", _sha256("TEST"))

    assert len(_stored(demo_document)) == 1
