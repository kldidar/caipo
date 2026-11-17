"""Passages: exact spans of a Segment, created by the server (ADR-0025 point 4)."""

import uuid

import pytest
from django.db import connection, transaction
from django.db.utils import IntegrityError

from caipo.accounts.selectors import AuthenticationContext
from caipo.core.entry import InvalidEntryError, RecordNotFoundError
from caipo.sources import selectors, services
from caipo.sources.models import Passage, Segment
from caipo.sources.services import TextPart
from caipo.sources.tests.helpers import World, make_document, make_source

pytestmark = [pytest.mark.services, pytest.mark.django_db]

TEXT = "TEST A council is established.\n\nIt meets twice a year: Café."


@pytest.fixture
def segment(researcher: AuthenticationContext, world: World) -> uuid.UUID:
    document = make_document(researcher, world, make_source(researcher, world))
    services.attach_demonstration_text(
        actor=researcher, document=document, parts=[TextPart("Art. 1", TEXT)]
    )
    (entry,) = selectors.document_text(document)
    return entry.public_id


def test_a_passage_holds_the_segments_own_text_of_its_span(segment: uuid.UUID) -> None:
    public_id = services.passage_for_span(segment=segment, start_offset=5, end_offset=len(TEXT))

    passage = Passage.objects.get(public_id=public_id)
    assert passage.quote == TEXT[5:]
    assert (passage.start_offset, passage.end_offset) == (5, len(TEXT))


def test_the_same_span_gives_the_same_passage(segment: uuid.UUID) -> None:
    first = services.passage_for_span(segment=segment, start_offset=0, end_offset=4)

    assert services.passage_for_span(segment=segment, start_offset=0, end_offset=4) == first
    assert Passage.objects.count() == 1


@pytest.mark.parametrize(("start", "end"), [(-1, 4), (4, 4), (5, 4), (0, len(TEXT) + 1)])
def test_a_span_outside_the_text_is_refused(segment: uuid.UUID, start: int, end: int) -> None:
    with pytest.raises(InvalidEntryError):
        services.passage_for_span(segment=segment, start_offset=start, end_offset=end)

    assert not Passage.objects.exists()


def test_an_unknown_segment_is_refused() -> None:
    with pytest.raises(RecordNotFoundError):
        services.passage_for_span(segment=uuid.uuid4(), start_offset=0, end_offset=1)


def _raw(sql: str, params: list[str | int | uuid.UUID]) -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(sql, params)


def _insert(segment: uuid.UUID, start: int, end: int, quote: str) -> None:
    _raw(
        "INSERT INTO sources_passage"
        " (public_id, segment_id, start_offset, end_offset, quote, created_at)"
        " VALUES (%s, %s, %s, %s, %s, now())",
        [uuid.uuid4(), Segment.objects.get(public_id=segment).pk, start, end, quote],
    )


def test_the_database_refuses_a_quote_that_is_not_the_span(segment: uuid.UUID) -> None:
    with pytest.raises(IntegrityError, match="not its segment span"):
        _insert(segment, 0, 4, "FAKE")
    with pytest.raises(IntegrityError, match="not its segment span"):
        _insert(segment, 0, len(TEXT) + 5, TEXT)
    _insert(segment, len(TEXT) - 5, len(TEXT), TEXT[-5:])

    assert Passage.objects.get().quote == "Café."


def test_the_database_refuses_any_change_or_deletion_of_a_passage(segment: uuid.UUID) -> None:
    services.passage_for_span(segment=segment, start_offset=0, end_offset=4)

    with pytest.raises(IntegrityError, match="append-only: UPDATE refused"):
        _raw("UPDATE sources_passage SET quote = %s", ["TEST"])
    with pytest.raises(IntegrityError, match="append-only: DELETE refused"):
        _raw("DELETE FROM sources_passage", [])

    assert Passage.objects.get().quote == TEXT[:4]
