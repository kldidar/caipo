"""Retrieval chunks: derived, rebuildable units of search (DATA_MODEL.md §3.8; ADR-0025).

Not provenance. A chunk is deleted and rebuilt whenever its configuration
changes, and its loss loses nothing: it is made again from the Segments and
the help corpus. A chunk refers to its Segment and document by their public
identifiers, read through the selectors of `sources`, and holds the exact
text of the span it covers, so that a hit can be shown and quoted without
reading another app's tables.
"""

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.utils.translation import gettext_lazy as _

HEADING_MAX_LENGTH = 300


class ChunkKind(models.TextChoices):
    DOCUMENT = "document", _("Demonstration document")
    HELP = "help", _("Help page")


class RetrievalChunk(models.Model):
    """One unit of search: one Segment of a demonstration document, or one section of help."""

    chunking_version = models.CharField(_("chunking configuration version"), max_length=64)
    kind = models.CharField(_("kind"), max_length=16, choices=ChunkKind)
    segment = models.UUIDField(_("segment"), null=True, blank=True)
    document = models.UUIDField(_("document"), null=True, blank=True)
    start_offset = models.PositiveIntegerField(_("start offset"))
    end_offset = models.PositiveIntegerField(_("end offset"))
    help_page = models.CharField(_("help page"), max_length=64, blank=True)
    help_section = models.CharField(_("help section"), max_length=HEADING_MAX_LENGTH, blank=True)
    heading = models.CharField(_("heading"), max_length=HEADING_MAX_LENGTH, blank=True)
    source_text = models.TextField(_("text of the span"))
    search_text = models.TextField(_("search text"))
    search_vector = SearchVectorField(_("search vector"), null=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("retrieval chunk")
        verbose_name_plural = _("retrieval chunks")
        # Trigram similarity is computed for each chunk: the corpora are small,
        # and a trigram index would serve only PostgreSQL's fixed-threshold
        # operators, not the configured threshold.
        indexes = [GinIndex(fields=["search_vector"], name="retrieval_chunk_vector_gin")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(kind__in=ChunkKind.values), name="retrieval_chunk_kind_known"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    kind=ChunkKind.DOCUMENT,
                    segment__isnull=False,
                    document__isnull=False,
                    help_page="",
                    help_section="",
                )
                | models.Q(
                    kind=ChunkKind.HELP,
                    segment__isnull=True,
                    document__isnull=True,
                )
                & ~models.Q(help_page="")
                & ~models.Q(help_section=""),
                name="retrieval_chunk_kind_fits_its_reference",
            ),
            models.CheckConstraint(
                condition=models.Q(start_offset__lt=models.F("end_offset")),
                name="retrieval_chunk_span_not_empty",
            ),
            models.CheckConstraint(
                condition=~models.Q(source_text="") & ~models.Q(search_text=""),
                name="retrieval_chunk_text_present",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.heading}"
