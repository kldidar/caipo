"""Read interface of the demonstrator's sources and documents (ADR-0020).

Pages read through the functions that take an authentication context; they
require `WORKSPACE_READ`. The functions that take none serve the services of
higher apps, which have checked their own permission first.
"""

import uuid
from dataclasses import dataclass
from datetime import date

from django.db.models import Count

from caipo.accounts import selectors as accounts_selectors
from caipo.accounts.selectors import AuthenticationContext, Permission
from caipo.sources.models import (
    Document,
    DocumentType,
    PermittedUse,
    Segment,
    Source,
    SourceTier,
)

__all__ = [
    "DocumentEntry",
    "DocumentReference",
    "SegmentEntry",
    "SegmentSource",
    "SourceReference",
    "source_reference",
    "DocumentType",
    "PermittedUse",
    "SourceDetail",
    "SourceEntry",
    "SourceTier",
    "counts",
    "document_choices",
    "document_reference",
    "demonstration_segments",
    "segment_source",
    "document_text",
    "documents_by_key",
    "source_choices",
    "source_detail",
    "sources",
]


@dataclass(frozen=True)
class SourceEntry:
    public_id: uuid.UUID
    data_class: str
    name: str
    publisher: str
    url: str
    source_tier: str
    country_alpha2: str | None
    country_name: str | None
    licence: str
    licence_verified: bool
    permitted_use: str
    accessed_on: date
    coverage: str
    limitations: str
    document_count: int

    @property
    def tier_label(self) -> str:
        return str(SourceTier(self.source_tier).label)

    @property
    def permitted_use_label(self) -> str:
        return str(PermittedUse(self.permitted_use).label)


@dataclass(frozen=True)
class DocumentEntry:
    """A document with the provenance of its source, as a page shows it."""

    public_id: uuid.UUID
    data_class: str
    document_type: str
    title: str
    title_language: str
    title_en: str
    title_en_official: bool
    official_identifier: str
    date_of_issue: date | None
    official_url: str
    accessed_on: date | None
    notes: str
    country_alpha2: str
    country_name: str
    issuing_institution: uuid.UUID | None
    source_public_id: uuid.UUID
    source_name: str
    source_publisher: str
    source_tier: str
    source_permitted_use: str
    source_licence: str
    source_licence_verified: bool

    @property
    def type_label(self) -> str:
        return str(DocumentType(self.document_type).label)

    @property
    def display_title(self) -> str:
        return self.title_en or self.title


@dataclass(frozen=True)
class SourceDetail:
    source: SourceEntry
    documents: tuple[DocumentEntry, ...]


@dataclass(frozen=True)
class DocumentReference:
    pk: int
    public_id: uuid.UUID
    data_class: str
    country_pk: int


_SOURCE_FIELDS = (
    "public_id",
    "data_class",
    "name",
    "publisher",
    "url",
    "source_tier",
    "country__alpha2",
    "country__name_en",
    "licence",
    "licence_verified",
    "permitted_use",
    "accessed_on",
    "coverage",
    "limitations",
)
_DOCUMENT_FIELDS = (
    "public_id",
    "data_class",
    "document_type",
    "title",
    "title_language__code",
    "title_en",
    "title_en_official",
    "official_identifier",
    "date_of_issue",
    "official_url",
    "accessed_on",
    "notes",
    "country__alpha2",
    "country__name_en",
    "issuing_institution__public_id",
    "source__public_id",
    "source__name",
    "source__publisher",
    "source__source_tier",
    "source__permitted_use",
    "source__licence",
    "source__licence_verified",
)


def sources(
    context: AuthenticationContext | None, *, data_class: str | None = None
) -> list[SourceEntry]:
    """Return every source, or those of one data class, by name, with its number of documents.

    Reads only. Raises PermissionDenied if the context may not read the workspace.
    """
    accounts_selectors.require_permission(context, Permission.WORKSPACE_READ)
    rows = Source.objects.annotate(document_count=Count("documents"))
    if data_class:
        rows = rows.filter(data_class=data_class)
    return [
        SourceEntry(*row)
        for row in rows.order_by("name", "id").values_list(*_SOURCE_FIELDS, "document_count")
    ]


def _documents(**filters: object) -> tuple[DocumentEntry, ...]:
    return tuple(
        DocumentEntry(*row)
        for row in Document.objects.filter(**filters)
        .order_by("date_of_issue", "id")
        .values_list(*_DOCUMENT_FIELDS)
    )


def source_detail(
    context: AuthenticationContext | None, public_id: uuid.UUID
) -> SourceDetail | None:
    """Return a source with its documents, or None if there is none with this identifier.

    Reads only. Raises PermissionDenied if the context may not read the workspace.
    """
    accounts_selectors.require_permission(context, Permission.WORKSPACE_READ)
    row = (
        Source.objects.filter(public_id=public_id)
        .annotate(document_count=Count("documents"))
        .values_list(*_SOURCE_FIELDS, "document_count")
        .first()
    )
    if row is None:
        return None
    return SourceDetail(SourceEntry(*row), _documents(source__public_id=public_id))


def documents_by_key(keys: list[int]) -> dict[int, DocumentEntry]:
    """Return the documents with these keys, with their sources' provenance. For higher apps."""
    rows = Document.objects.filter(pk__in=keys).values_list("pk", *_DOCUMENT_FIELDS)
    return {row[0]: DocumentEntry(*row[1:]) for row in rows}


def document_reference(public_id: uuid.UUID) -> DocumentReference | None:
    """Return the key, data class, and country key of a document, or None. For higher apps."""
    row = (
        Document.objects.filter(public_id=public_id)
        .values_list("pk", "public_id", "data_class", "country_id")
        .first()
    )
    return DocumentReference(*row) if row else None


def document_choices(
    context: AuthenticationContext | None, *, data_class: str | None = None
) -> list[tuple[uuid.UUID, str]]:
    """Return documents as (public identifier, label) for a form, ordered by title.

    Reads only. Raises PermissionDenied if the context may not read the workspace.
    """
    accounts_selectors.require_permission(context, Permission.WORKSPACE_READ)
    rows = Document.objects.all()
    if data_class:
        rows = rows.filter(data_class=data_class)
    return [
        (public_id, f"{title_en or title} [{alpha2}]")
        for public_id, title, title_en, alpha2 in rows.order_by("title").values_list(
            "public_id", "title", "title_en", "country__alpha2"
        )
    ]


def source_choices(context: AuthenticationContext | None) -> list[tuple[uuid.UUID, str, str]]:
    """Return sources as (public identifier, name, data class) for a form.

    Reads only. Raises PermissionDenied if the context may not read the workspace.
    """
    accounts_selectors.require_permission(context, Permission.WORKSPACE_READ)
    return list(Source.objects.order_by("name").values_list("public_id", "name", "data_class"))


def counts(context: AuthenticationContext | None) -> dict[str, int]:
    """Return how many sources and documents there are of each data class.

    Reads only. Raises PermissionDenied if the context may not read the workspace.
    """
    accounts_selectors.require_permission(context, Permission.WORKSPACE_READ)
    result = {
        "sources_reference": 0,
        "sources_demonstration": 0,
        "documents_reference": 0,
        "documents_demonstration": 0,
    }
    for data_class, number in Source.objects.values_list("data_class").annotate(n=Count("id")):
        result[f"sources_{data_class}"] = number
    for data_class, number in Document.objects.values_list("data_class").annotate(n=Count("id")):
        result[f"documents_{data_class}"] = number
    return result


@dataclass(frozen=True)
class SourceReference:
    pk: int
    public_id: uuid.UUID
    data_class: str
    name: str


def source_reference(public_id: uuid.UUID) -> SourceReference | None:
    """Return the key, data class, and name of a source, or None. For higher apps."""
    row = (
        Source.objects.filter(public_id=public_id)
        .values_list("pk", "public_id", "data_class", "name")
        .first()
    )
    return SourceReference(*row) if row else None


@dataclass(frozen=True)
class SegmentEntry:
    """One part of a demonstration document's synthetic text, as held."""

    public_id: uuid.UUID
    document: uuid.UUID
    position: int
    locator: str
    text: str
    text_sha256: str


def demonstration_segments() -> tuple[SegmentEntry, ...]:
    """Every Segment held, by document and position: the texts retrieval may index (ADR-0025).

    Only demonstration documents hold Segments, by the trigger of migration
    0002. For the services of higher apps, which have checked their own
    permission first.
    """
    return tuple(
        SegmentEntry(
            public_id=public_id,
            document=document,
            position=position,
            locator=locator,
            text=text,
            text_sha256=text_sha256,
        )
        for public_id, document, position, locator, text, text_sha256 in Segment.objects.order_by(
            "document_id", "position"
        ).values_list(
            "public_id", "document__public_id", "position", "locator", "text", "text_sha256"
        )
    )


def document_text(document: uuid.UUID) -> tuple[SegmentEntry, ...]:
    """Return a document's text in order; empty if it has none (ADR-0025 point 4).

    Only a demonstration document has a text. For the services of higher
    apps, which have checked their own permission first.
    """
    return tuple(
        SegmentEntry(
            public_id=segment.public_id,
            document=document,
            position=segment.position,
            locator=segment.locator,
            text=segment.text,
            text_sha256=segment.text_sha256,
        )
        for segment in Segment.objects.filter(document__public_id=document).order_by("position")
    )


@dataclass(frozen=True)
class SegmentSource:
    """A Segment as held, with what the server shows as its source (ADR-0025 point 2)."""

    segment: SegmentEntry
    document_title: str
    document_data_class: str
    document_issued: date | None
    source: uuid.UUID


def segment_source(segment: uuid.UUID) -> SegmentSource | None:
    """Return a Segment, its document's title and date, and its source, or None if there is none.

    For the services of higher apps, which have checked their own permission
    first: the assistant checks what it retrieved against the Segment held.
    """
    row = (
        Segment.objects.filter(public_id=segment)
        .values_list(
            "public_id",
            "document__public_id",
            "position",
            "locator",
            "text",
            "text_sha256",
            "document__title",
            "document__data_class",
            "document__date_of_issue",
            "document__source__public_id",
        )
        .first()
    )
    if row is None:
        return None
    public_id, document, position, locator, text, digest, title, data_class, issued, source = row
    return SegmentSource(
        SegmentEntry(public_id, document, position, locator, text, digest),
        title,
        data_class,
        issued,
        source,
    )
