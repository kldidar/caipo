"""The retrieval index and lexical search over it (ADR-0025 point 5)."""

import uuid
from io import StringIO

import pytest
from django.core.management import call_command

from caipo.accounts.selectors import AuthenticationContext
from caipo.retrieval import config, selectors, services
from caipo.retrieval.corpus import help_pages
from caipo.retrieval.models import ChunkKind, RetrievalChunk
from caipo.sources import selectors as sources_selectors
from caipo.sources import services as sources_services
from caipo.sources.services import TextPart
from caipo.sources.tests.helpers import World, make_document, make_source

pytestmark = [pytest.mark.services, pytest.mark.django_db]

PARTS = [
    TextPart("Art. 2", "TEST A national council for artificial intelligence is established."),
    TextPart("Art. 7", "TEST A competitive grant programme supports start-ups."),
]


@pytest.fixture
def document(researcher: AuthenticationContext, world: World) -> uuid.UUID:
    source = make_source(researcher, world)
    public_id = make_document(researcher, world, source)
    sources_services.attach_demonstration_text(actor=researcher, document=public_id, parts=PARTS)
    return public_id


def _help_sections() -> int:
    return sum(len(page.sections) for page in help_pages())


def test_the_index_holds_one_chunk_per_segment_and_per_help_section(document: uuid.UUID) -> None:
    summary = services.rebuild_index()

    assert (summary.document_chunks, summary.help_chunks) == (2, _help_sections())
    chunks = RetrievalChunk.objects.filter(kind=ChunkKind.DOCUMENT).order_by("id")
    segments = sources_selectors.document_text(document)
    assert [(c.segment, c.document, c.heading, c.source_text) for c in chunks] == [
        (s.public_id, document, s.locator, s.text) for s in segments
    ]
    assert all(c.start_offset == 0 and c.end_offset == len(c.source_text) for c in chunks)
    assert not RetrievalChunk.objects.filter(search_vector=None).exists()


def test_rebuilding_replaces_the_index_and_never_touches_a_segment(document: uuid.UUID) -> None:
    services.rebuild_index()
    before = sources_selectors.document_text(document)

    services.rebuild_index()

    assert RetrievalChunk.objects.count() == 2 + _help_sections()
    assert sources_selectors.document_text(document) == before


def test_a_question_finds_the_segment_that_answers_it(document: uuid.UUID) -> None:
    services.rebuild_index()

    hits = selectors.search("grant programme for start-ups", kind=ChunkKind.DOCUMENT, limit=5)

    assert hits[0].heading == "Art. 7"
    assert hits[0].document == document
    assert hits[0].text == PARTS[1].text
    assert hits[0].lexical_rank == 1


def test_a_question_holding_a_word_no_text_holds_is_found_only_by_any_word(
    document: uuid.UUID,
) -> None:
    services.rebuild_index()
    question = "competitive grant programme for veterans"

    every = selectors.search(question, kind=ChunkKind.DOCUMENT, limit=5)
    anyone = selectors.search(question, kind=ChunkKind.DOCUMENT, limit=5, any_word=True)

    assert all(hit.lexical_rank is None for hit in every)
    assert anyone[0].heading == "Art. 7"
    assert anyone[0].lexical_rank == 1


def test_with_any_word_the_text_holding_more_of_the_words_ranks_first(
    document: uuid.UUID,
) -> None:
    services.rebuild_index()

    hits = selectors.search(
        "council grant programme start-ups", kind=ChunkKind.DOCUMENT, limit=5, any_word=True
    )

    by_rank = {hit.lexical_rank: hit.heading for hit in hits if hit.lexical_rank is not None}
    assert by_rank == {1: "Art. 7", 2: "Art. 2"}


def test_with_any_word_a_question_of_stop_words_or_signs_finds_nothing_by_words(
    document: uuid.UUID,
) -> None:
    services.rebuild_index()

    for question in ("the and of", "!!! ((( ::: &&& |||"):
        hits = selectors.search(question, kind=ChunkKind.DOCUMENT, limit=5, any_word=True)
        assert all(hit.lexical_rank is None for hit in hits)


def test_a_misspelt_question_is_found_by_trigram_similarity(document: uuid.UUID) -> None:
    services.rebuild_index()

    hits = selectors.search("compettive grnt programe", kind=ChunkKind.DOCUMENT, limit=5)

    assert hits and hits[0].heading == "Art. 7"
    assert hits[0].lexical_rank is None and hits[0].trigram_rank == 1


def test_a_help_question_finds_help_and_never_a_document(document: uuid.UUID) -> None:
    services.rebuild_index()

    hits = selectors.search("export an analysis as CSV", kind=ChunkKind.HELP, limit=3)

    assert hits and {hit.kind for hit in hits} == {"help"}
    assert ("analysis", "exports") in {(hit.help_page, hit.help_section) for hit in hits}
    assert all(hit.document is None and hit.segment is None for hit in hits)


def test_chunks_of_another_configuration_version_are_not_searched(document: uuid.UUID) -> None:
    services.rebuild_index()
    RetrievalChunk.objects.update(chunking_version="TEST-old")

    assert selectors.search("grant programme", kind=ChunkKind.DOCUMENT, limit=5) == ()


def test_an_empty_question_finds_nothing(document: uuid.UUID) -> None:
    services.rebuild_index()

    assert selectors.search(" \t\n ", kind=ChunkKind.DOCUMENT, limit=5) == ()


def test_a_question_is_bounded_in_length() -> None:
    limit = config.load().max_query_length

    with pytest.raises(selectors.QueryTooLongError):
        selectors.search("a" * (limit + 1), kind=ChunkKind.HELP, limit=5)
    assert selectors.max_query_length() == limit


def test_a_limit_below_one_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        selectors.search("grant", kind=ChunkKind.HELP, limit=0)


@pytest.mark.parametrize(
    "question",
    ["'; DROP TABLE retrieval_retrievalchunk; --", 'grant" OR "1"="1', "!!! ((( ::: &&& |||"],
)
def test_a_hostile_question_is_only_ever_a_search(document: uuid.UUID, question: str) -> None:
    services.rebuild_index()

    selectors.search(question, kind=ChunkKind.DOCUMENT, limit=5)
    selectors.search(question, kind=ChunkKind.DOCUMENT, limit=5, any_word=True)

    assert RetrievalChunk.objects.count() == 2 + _help_sections()


def test_the_command_rebuilds_and_reports(document: uuid.UUID) -> None:
    out = StringIO()

    call_command("rebuild_retrieval_index", stdout=out)

    assert f"2 document chunks, {_help_sections()} help chunks" in out.getvalue()
