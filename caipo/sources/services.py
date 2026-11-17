"""Write interface of the demonstrator's sources and documents (ADR-0020).

Each operation requires `RESEARCH_CONTRIBUTE` first, then validates, writes,
and records its audit event, in one transaction. A record is named by its
public identifier, and nothing takes a request. Nothing is deleted.
"""

import hashlib
import logging
import unicodedata
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from django.db import transaction
from django.utils.translation import gettext as _

from caipo.accounts import selectors as accounts_selectors
from caipo.accounts import services as accounts_services
from caipo.accounts.selectors import (
    AuditAction,
    AuditField,
    AuditTargetType,
    AuthenticationContext,
    Permission,
)
from caipo.accounts.services import AuditChange
from caipo.core.data_class import DataClass, country_fits
from caipo.core.entry import (
    DataClassError,
    InvalidEntryError,
    RecordNotFoundError,
    clean_address,
    clean_text,
    has_direction_control,
)
from caipo.registry import selectors as registry_selectors
from caipo.sources.models import (
    LOCATOR_MAX_LENGTH,
    NAME_MAX_LENGTH,
    SEGMENT_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    URL_MAX_LENGTH,
    Document,
    DocumentType,
    Passage,
    PermittedUse,
    Segment,
    Source,
    SourceTier,
)

logger = logging.getLogger(__name__)


def _choice(
    value: str, choices: type[DataClass | SourceTier | PermittedUse | DocumentType], field: str
) -> str:
    if value not in choices.values:
        raise InvalidEntryError(_("The %(field)s is not one of those listed.") % {"field": field})
    return value


def _country(public_id: uuid.UUID, data_class: str) -> registry_selectors.CountryReference:
    country = registry_selectors.country_reference(public_id)
    if country is None:
        raise RecordNotFoundError(_("The country does not exist."))
    if not country.is_active:
        raise InvalidEntryError(_("The country is deactivated."))
    if not country_fits(data_class, country.alpha2):
        raise DataClassError(
            _(
                "Demonstration records belong only to synthetic countries, "
                "and reference records never do."
            )
        )
    return country


def _record(
    actor: AuthenticationContext, target_type: AuditTargetType, public_id: uuid.UUID
) -> None:
    accounts_services.record_audit_event(
        actor=actor,
        action=AuditAction.CREATED,
        target_type=target_type,
        target_public_id=public_id,
        changes=(),
    )


def _log(actor: AuthenticationContext, event: str, public_id: uuid.UUID) -> None:
    logger.info(
        "Demonstrator record created",
        extra={"event": event, "public_id": str(public_id), "actor_id": actor.user.pk},
    )


def create_source(
    *,
    actor: AuthenticationContext,
    data_class: str,
    name: str,
    publisher: str,
    url: str,
    source_tier: str,
    permitted_use: str,
    accessed_on: date,
    country: uuid.UUID | None = None,
    licence: str = "",
    licence_verified: bool = False,
    coverage: str = "",
    limitations: str = "",
) -> uuid.UUID:
    """Register a source and return its public identifier.

    Preconditions: the actor holds `RESEARCH_CONTRIBUTE`; the data class,
    tier, and permitted use are listed values; the name and publisher are
    not empty; the address is http or https (it is recorded, never fetched);
    a country, if given, exists, is active, and fits the data class
    (`caipo.core.data_class.country_fits`); a licence called verified is
    written down.

    Side effects: one Source and one `created` audit event in one
    transaction, and a log line after it commits.

    Raises PermissionDenied before anything else is examined;
    InvalidEntryError, RecordNotFoundError, or DataClassError if a value is
    not acceptable. Nothing is stored in any of those cases.
    """
    accounts_selectors.require_permission(actor, Permission.RESEARCH_CONTRIBUTE)
    _choice(data_class, DataClass, _("data class"))
    _choice(source_tier, SourceTier, _("source tier"))
    _choice(permitted_use, PermittedUse, _("permitted use"))
    clean_licence = clean_text(licence, field=_("licence"), max_length=500, required=False)
    if licence_verified and not clean_licence:
        raise InvalidEntryError(_("A licence called verified is written down."))
    with transaction.atomic():
        source = Source.objects.create(
            data_class=data_class,
            name=clean_text(name, field=_("name"), max_length=NAME_MAX_LENGTH),
            publisher=clean_text(publisher, field=_("publisher"), max_length=NAME_MAX_LENGTH),
            url=clean_address(url, field=_("address"), max_length=URL_MAX_LENGTH),
            source_tier=source_tier,
            country_id=_country(country, data_class).pk if country is not None else None,
            licence=clean_licence,
            licence_verified=licence_verified,
            permitted_use=permitted_use,
            accessed_on=accessed_on,
            coverage=clean_text(coverage, field=_("coverage"), max_length=5000, required=False),
            limitations=clean_text(
                limitations, field=_("limitations"), max_length=5000, required=False
            ),
        )
        _record(actor, AuditTargetType.SOURCE, source.public_id)
    _log(actor, "sources.source_created", source.public_id)
    return source.public_id


def create_document(
    *,
    actor: AuthenticationContext,
    source: uuid.UUID,
    country: uuid.UUID,
    document_type: str,
    title: str,
    title_language: uuid.UUID,
    title_en: str = "",
    title_en_official: bool = False,
    official_identifier: str = "",
    date_of_issue: date | None = None,
    official_url: str = "",
    accessed_on: date | None = None,
    issuing_institution: uuid.UUID | None = None,
    notes: str = "",
) -> uuid.UUID:
    """Register a document from a source by its metadata, and return its public identifier.

    Preconditions: the actor holds `RESEARCH_CONTRIBUTE`; the source exists,
    and the document takes its data class; the country exists, is active,
    and fits that data class; the language exists and is active; an issuing
    institution, if given, exists; the form is a listed value; the title is
    not empty; an English title called official is given; an official
    address, if given, is http or https. No text of the document is taken:
    the demonstrator registers metadata only (ADR-0020 point 7).

    Side effects: one Document and one `created` audit event in one
    transaction, and a log line after it commits.

    Raises PermissionDenied before anything else is examined;
    InvalidEntryError, RecordNotFoundError, or DataClassError if a value is
    not acceptable. Nothing is stored in any of those cases.
    """
    accounts_selectors.require_permission(actor, Permission.RESEARCH_CONTRIBUTE)
    _choice(document_type, DocumentType, _("form"))
    with transaction.atomic():
        parent = Source.objects.filter(public_id=source).values_list("pk", "data_class").first()
        if parent is None:
            raise RecordNotFoundError(_("The source does not exist."))
        source_pk, data_class = parent
        language = registry_selectors.language_reference(title_language)
        if language is None:
            raise RecordNotFoundError(_("The language does not exist."))
        if not language.is_active:
            raise InvalidEntryError(_("The language is deactivated."))
        issuer = None
        if issuing_institution is not None:
            issuer = registry_selectors.institution_key(issuing_institution)
            if issuer is None:
                raise RecordNotFoundError(_("The institution does not exist."))
        english = clean_text(
            title_en, field=_("English title"), max_length=TITLE_MAX_LENGTH, required=False
        )
        if title_en_official and not english:
            raise InvalidEntryError(_("An English title called official is given."))
        document = Document.objects.create(
            source_id=source_pk,
            data_class=data_class,
            country_id=_country(country, data_class).pk,
            issuing_institution_id=issuer.pk if issuer else None,
            document_type=document_type,
            title=clean_text(title, field=_("title"), max_length=TITLE_MAX_LENGTH),
            title_language_id=language.pk,
            title_en=english,
            title_en_official=title_en_official,
            official_identifier=clean_text(
                official_identifier, field=_("official identifier"), max_length=200, required=False
            ),
            date_of_issue=date_of_issue,
            official_url=clean_address(
                official_url, field=_("official address"), max_length=URL_MAX_LENGTH, required=False
            ),
            accessed_on=accessed_on,
            notes=clean_text(notes, field=_("notes"), max_length=5000, required=False),
        )
        _record(actor, AuditTargetType.DOCUMENT, document.public_id)
    _log(actor, "sources.document_created", document.public_id)
    return document.public_id


# A demonstration text has at least one part and is bounded in its number of parts.
TEXT_MAX_PARTS = 200


@dataclass(frozen=True)
class TextPart:
    """One part of a document's text: where it is in the document, and what it says."""

    locator: str
    text: str


def _segment_text(value: str) -> str:
    # Held in NFC and otherwise as given (DATA_MODEL.md §5): no whitespace is
    # removed or collapsed. Only its form is checked.
    text = unicodedata.normalize("NFC", value)
    if not text.strip():
        raise InvalidEntryError(_("Each part of the text says something."))
    if len(text) > SEGMENT_MAX_LENGTH:
        raise InvalidEntryError(
            _("Each part of the text is at most %(limit)d characters.")
            % {"limit": SEGMENT_MAX_LENGTH}
        )
    if has_direction_control(text):
        raise InvalidEntryError(_("The text holds a direction control character."))
    return text


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def attach_demonstration_text(
    *, actor: AuthenticationContext, document: uuid.UUID, parts: Sequence[TextPart]
) -> str:
    """Give a demonstration document its synthetic text, once, and return its fingerprint.

    Preconditions: the actor holds `RESEARCH_CONTRIBUTE`; the document exists
    and is demonstration data; it has no text yet; there are 1 to
    TEXT_MAX_PARTS parts, each with a locator of at most LOCATOR_MAX_LENGTH
    characters and a text that is not blank, of at most SEGMENT_MAX_LENGTH
    characters, and free of direction controls. A text is held in NFC and is
    otherwise stored as given (ADR-0025 point 4).

    The fingerprint is the SHA-256 of the segments' own SHA-256 values, in
    order, one per line. It names the whole text in the audit record, which
    never holds the text itself.

    Side effects: one Segment per part, in the order given, and one `updated`
    audit event on the document whose change is the fingerprint, in one
    transaction, and a log line after it commits.

    Raises PermissionDenied before anything else is examined;
    RecordNotFoundError if the document does not exist; DataClassError if it
    is reference data; InvalidEntryError if it already has a text or a part is
    not acceptable. Nothing is stored in any of those cases.
    """
    accounts_selectors.require_permission(actor, Permission.RESEARCH_CONTRIBUTE)
    if not 1 <= len(parts) <= TEXT_MAX_PARTS:
        raise InvalidEntryError(
            _("A text has from 1 to %(limit)d parts.") % {"limit": TEXT_MAX_PARTS}
        )
    cleaned = [
        (
            clean_text(
                part.locator,
                field=_("locator"),
                max_length=LOCATOR_MAX_LENGTH,
                required=False,
            ),
            _segment_text(part.text),
        )
        for part in parts
    ]
    with transaction.atomic():
        found = (
            Document.objects.select_for_update()
            .filter(public_id=document)
            .values_list("pk", "data_class")
            .first()
        )
        if found is None:
            raise RecordNotFoundError(_("The document does not exist."))
        document_pk, data_class = found
        if data_class != DataClass.DEMONSTRATION:
            raise DataClassError(
                _(
                    "Only a demonstration document holds a text:"
                    " a reference document's rights are not decided."
                )
            )
        if Segment.objects.filter(document_id=document_pk).exists():
            raise InvalidEntryError(
                _("The document has its text already, and it is never replaced.")
            )
        hashes = []
        for position, (locator, text) in enumerate(cleaned, start=1):
            digest = _sha256(text)
            Segment.objects.create(
                document_id=document_pk,
                position=position,
                locator=locator,
                text=text,
                text_sha256=digest,
            )
            hashes.append(digest)
        fingerprint = _sha256("\n".join(hashes))
        accounts_services.record_audit_event(
            actor=actor,
            action=AuditAction.UPDATED,
            target_type=AuditTargetType.DOCUMENT,
            target_public_id=document,
            changes=[AuditChange(AuditField.TEXT, None, fingerprint)],
        )
    logger.info(
        "Demonstration text attached",
        extra={
            "event": "sources.document_text_attached",
            "public_id": str(document),
            "actor_id": actor.user.pk,
            "segments": len(cleaned),
        },
    )
    return fingerprint


def passage_for_span(*, segment: uuid.UUID, start_offset: int, end_offset: int) -> uuid.UUID:
    """Return the Passage of an exact span of a Segment, recording it the first time.

    Preconditions: the Segment exists, and 0 <= start_offset < end_offset <=
    the length of its text in code points. Called by the assistant's
    pipeline for a span an answer cites, after the pipeline checked that the
    asker may ask (ADR-0025): a Passage is made by the server, never by a
    model, and says only where evidence is. It takes no actor.

    Side effects: at most one Passage, holding the Segment's own text of the
    span; an existing Passage of the same span is returned instead.

    Raises RecordNotFoundError if the Segment does not exist, and
    InvalidEntryError if the span is not within its text. Nothing is
    recorded in those cases.
    """
    with transaction.atomic():
        found = Segment.objects.filter(public_id=segment).values_list("pk", "text").first()
        if found is None:
            raise RecordNotFoundError(_("The segment does not exist."))
        segment_pk, text = found
        if not 0 <= start_offset < end_offset <= len(text):
            raise InvalidEntryError(_("The span is not within the segment's text."))
        passage, _created = Passage.objects.get_or_create(
            segment_id=segment_pk,
            start_offset=start_offset,
            end_offset=end_offset,
            defaults={"quote": text[start_offset:end_offset]},
        )
    return passage.public_id
