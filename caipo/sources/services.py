"""Write interface of the demonstrator's sources and documents (ADR-0020).

Each operation requires `RESEARCH_CONTRIBUTE` first, then validates, writes,
and records its audit event, in one transaction. A record is named by its
public identifier, and nothing takes a request. Nothing is deleted.
"""

import logging
import uuid
from datetime import date

from django.db import transaction
from django.utils.translation import gettext as _

from caipo.accounts import selectors as accounts_selectors
from caipo.accounts import services as accounts_services
from caipo.accounts.selectors import AuditAction, AuditTargetType, AuthenticationContext, Permission
from caipo.core.data_class import DataClass, country_fits
from caipo.core.entry import (
    DataClassError,
    InvalidEntryError,
    RecordNotFoundError,
    clean_address,
    clean_text,
)
from caipo.registry import selectors as registry_selectors
from caipo.sources.models import (
    NAME_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    URL_MAX_LENGTH,
    Document,
    DocumentType,
    PermittedUse,
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
