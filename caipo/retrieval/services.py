"""Write interface of retrieval: rebuilding the index (ADR-0025 point 5; DATA_MODEL.md §3.8).

The index is derived data. Rebuilding it deletes every chunk and makes them
again from the Segments held and the help corpus, under the configuration
in `chunking.toml`. It changes no Segment and no record of any other app.
"""

import logging
from dataclasses import dataclass

from django.contrib.postgres.search import SearchVector
from django.db import transaction

from caipo.retrieval import config
from caipo.retrieval.corpus import help_pages, search_text
from caipo.retrieval.models import ChunkKind, RetrievalChunk
from caipo.sources import selectors as sources_selectors

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IndexSummary:
    version: str
    document_chunks: int
    help_chunks: int


def rebuild_index() -> IndexSummary:
    """Delete every retrieval chunk and build them again; return what was built.

    An operational task for the development command and the demonstration
    seed, not an action of an account: it reads only Segments, which hold
    only synthetic demonstration text, and the help corpus in the
    repository, and writes only derived data. It takes no actor.

    Side effects: in one transaction, every RetrievalChunk is deleted, one is
    made for each Segment and for each section of help, and their search
    vectors are computed; a log line follows.

    Raises ValueError if the configuration or a help page is not in the
    expected form (HelpCorpusError is one). Nothing is changed in that case.
    """
    configuration = config.load()
    pages = help_pages()
    transformations = configuration.transformations
    chunks = [
        RetrievalChunk(
            chunking_version=configuration.version,
            kind=ChunkKind.DOCUMENT,
            segment=segment.public_id,
            document=segment.document,
            start_offset=0,
            end_offset=len(segment.text),
            heading=segment.locator,
            source_text=segment.text,
            search_text=search_text(f"{segment.locator}\n{segment.text}", transformations),
        )
        for segment in sources_selectors.demonstration_segments()
    ]
    document_chunks = len(chunks)
    for page in pages:
        for section in page.sections:
            chunks.append(
                RetrievalChunk(
                    chunking_version=configuration.version,
                    kind=ChunkKind.HELP,
                    start_offset=0,
                    end_offset=len(section.text),
                    help_page=page.page,
                    help_section=section.anchor,
                    heading=f"{page.title}: {section.heading}",
                    source_text=section.text,
                    search_text=search_text(
                        f"{page.title}\n{section.heading}\n{section.text}", transformations
                    ),
                )
            )
    with transaction.atomic():
        RetrievalChunk.objects.all().delete()
        RetrievalChunk.objects.bulk_create(chunks)
        RetrievalChunk.objects.update(
            search_vector=SearchVector("search_text", config=configuration.text_search_config)
        )
    summary = IndexSummary(configuration.version, document_chunks, len(chunks) - document_chunks)
    logger.info(
        "Retrieval index rebuilt",
        extra={
            "event": "retrieval.index_rebuilt",
            "chunking_version": summary.version,
            "document_chunks": summary.document_chunks,
            "help_chunks": summary.help_chunks,
        },
    )
    return summary
