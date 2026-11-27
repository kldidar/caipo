"""Read interface of retrieval: lexical search over the index (ADR-0025 point 5).

Two retrievers, PostgreSQL full-text search and trigram word similarity,
over the derived search text of the chunks of one kind. Their rankings are
combined by reciprocal rank fusion, which needs no calibration of scores.
The question is untrusted text: it is bounded in length, transformed as the
chunks were, and reaches the database only as a bound parameter.

For the services of higher apps, which have checked their own permission
first.
"""

import operator
import re
import uuid
from dataclasses import dataclass
from functools import reduce

from django.contrib.postgres.search import SearchQuery, SearchRank, TrigramWordSimilarity
from django.db.models import QuerySet

from caipo.retrieval import config
from caipo.retrieval.corpus import HelpPage, help_pages, search_text
from caipo.retrieval.models import ChunkKind, RetrievalChunk

__all__ = [
    "ChunkKind",
    "QueryTooLongError",
    "SearchHit",
    "chunking_version",
    "help_corpus",
    "max_query_length",
    "search",
]


class QueryTooLongError(ValueError):
    """The question is longer than the configuration allows."""


@dataclass(frozen=True)
class SearchHit:
    """One retrieved chunk, with its place in each ranking and its fused score."""

    chunk_id: int
    kind: str
    segment: uuid.UUID | None
    document: uuid.UUID | None
    start_offset: int
    end_offset: int
    help_page: str
    help_section: str
    heading: str
    text: str
    lexical_rank: int | None
    trigram_rank: int | None
    score: float
    chunking_version: str


def search(
    question: str, *, kind: ChunkKind, limit: int, any_word: bool = False
) -> tuple[SearchHit, ...]:
    """Return up to `limit` chunks of one kind for a question, best first.

    The full-text retriever finds a chunk that holds every word of the
    question; with `any_word`, one that holds any of them, ranked by how well
    it matches, for a question translated into the texts' language whose
    words may not be the texts' own. An empty question, after the
    search-side transformations, finds nothing.
    Raises QueryTooLongError if the transformed question is longer than the
    configured maximum, and ValueError if `limit` is not positive.
    """
    if limit < 1:
        raise ValueError("The limit is at least 1.")
    configuration = config.load()
    query_text = search_text(question, configuration.transformations)
    if len(query_text) > configuration.max_query_length:
        raise QueryTooLongError(
            f"A question is at most {configuration.max_query_length} characters."
        )
    if not query_text:
        return ()
    chunks = RetrievalChunk.objects.filter(kind=kind, chunking_version=configuration.version)
    candidates = configuration.candidates_per_retriever
    lexical = _lexical(chunks, query_text, any_word=any_word, limit=candidates)
    trigram = list(
        chunks.annotate(similarity=TrigramWordSimilarity(query_text, "search_text"))
        .filter(similarity__gte=configuration.trigram_threshold)
        .order_by("-similarity", "id")
        .values_list("id", flat=True)[:candidates]
    )
    lexical_rank = {chunk_id: rank for rank, chunk_id in enumerate(lexical, start=1)}
    trigram_rank = {chunk_id: rank for rank, chunk_id in enumerate(trigram, start=1)}
    k = configuration.rrf_k
    scores = {
        chunk_id: sum(
            1 / (k + ranks[chunk_id]) for ranks in (lexical_rank, trigram_rank) if chunk_id in ranks
        )
        for chunk_id in lexical_rank.keys() | trigram_rank.keys()
    }
    best = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[:limit]
    found = RetrievalChunk.objects.in_bulk(best)
    return tuple(
        SearchHit(
            chunk_id=chunk_id,
            kind=found[chunk_id].kind,
            segment=found[chunk_id].segment,
            document=found[chunk_id].document,
            start_offset=found[chunk_id].start_offset,
            end_offset=found[chunk_id].end_offset,
            help_page=found[chunk_id].help_page,
            help_section=found[chunk_id].help_section,
            heading=found[chunk_id].heading,
            text=found[chunk_id].source_text,
            lexical_rank=lexical_rank.get(chunk_id),
            trigram_rank=trigram_rank.get(chunk_id),
            score=scores[chunk_id],
            chunking_version=found[chunk_id].chunking_version,
        )
        for chunk_id in best
    )


def _lexical(
    chunks: QuerySet[RetrievalChunk], query_text: str, *, any_word: bool, limit: int
) -> list[int]:
    language = config.load().text_search_config
    if any_word:
        # Each word is its own query, so no word of the question is read as an
        # operator; a word that is only a stop word matches nothing.
        words = [
            SearchQuery(word, search_type="plain", config=language)
            for word in re.findall(r"\w+", query_text)
        ]
        if not words:
            return []
        query = reduce(operator.or_, words)
    else:
        query = SearchQuery(query_text, search_type="websearch", config=language)
    return list(
        chunks.filter(search_vector=query)
        .annotate(rank=SearchRank("search_vector", query))
        .order_by("-rank", "id")
        .values_list("id", flat=True)[:limit]
    )


def help_corpus() -> tuple[HelpPage, ...]:
    """Every help page, as the repository holds it, for the pages that show help."""
    return help_pages()


def chunking_version() -> str:
    """The version of the chunking configuration that search uses now."""
    return config.load().version


def max_query_length() -> int:
    """The longest question search takes, after the search-side transformations."""
    return config.load().max_query_length
