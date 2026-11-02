"""Write interface of the demonstrator's policies (ADR-0020).

Each operation requires `RESEARCH_CONTRIBUTE` first, then validates, writes,
and records its audit event, in one transaction. Records of the two data
classes are never mixed: a policy's documents, events, and provisions are of
its own class, and its country fits that class. Nothing is deleted, and a
policy event, once recorded, is never changed.
"""

import logging
import uuid
from datetime import date

from django.db import IntegrityError, transaction
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
from caipo.core.entry import DataClassError, InvalidEntryError, RecordNotFoundError, clean_text
from caipo.policies.models import (
    FORMAL_ROLES,
    LOCATOR_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    AIFocus,
    ContextualCategory,
    CorpusAssignment,
    DocumentRole,
    Policy,
    PolicyDocumentLink,
    PolicyEvent,
    PolicyEventType,
    PolicyProvision,
    PolicyType,
    ProvisionType,
)
from caipo.registry import selectors as registry_selectors
from caipo.sources import selectors as sources_selectors

logger = logging.getLogger(__name__)


class DuplicateLinkError(InvalidEntryError):
    """The document is already linked to the policy in that role."""


def _listed(value: str, values: list[str], field: str) -> str:
    if value not in values:
        raise InvalidEntryError(_("The %(field)s is not one of those listed.") % {"field": field})
    return value


def _assignment(corpus_assignment: str, ai_focus: str, contextual_category: str) -> None:
    _listed(corpus_assignment, CorpusAssignment.values, _("corpus assignment"))
    if corpus_assignment == CorpusAssignment.CORE:
        _listed(ai_focus, AIFocus.values, _("AI focus"))
        if contextual_category:
            raise InvalidEntryError(_("A core policy has no contextual category."))
    else:
        _listed(contextual_category, ContextualCategory.values, _("contextual category"))
        if ai_focus:
            raise InvalidEntryError(_("A contextual policy has no AI focus."))


def _record(
    actor: AuthenticationContext,
    target_type: AuditTargetType,
    public_id: uuid.UUID,
    action: AuditAction = AuditAction.CREATED,
    changes: tuple[AuditChange, ...] = (),
) -> None:
    accounts_services.record_audit_event(
        actor=actor,
        action=action,
        target_type=target_type,
        target_public_id=public_id,
        changes=changes,
    )


def _log(actor: AuthenticationContext, event: str, public_id: uuid.UUID) -> None:
    logger.info(
        "Demonstrator record changed",
        extra={"event": event, "public_id": str(public_id), "actor_id": actor.user.pk},
    )


def _locked_policy(public_id: uuid.UUID) -> Policy:
    policy = Policy.objects.select_for_update().filter(public_id=public_id).first()
    if policy is None:
        raise RecordNotFoundError(_("The policy does not exist."))
    return policy


def _document_of(policy: Policy, document: uuid.UUID) -> sources_selectors.DocumentReference:
    reference = sources_selectors.document_reference(document)
    if reference is None:
        raise RecordNotFoundError(_("The document does not exist."))
    if reference.data_class != policy.data_class:
        raise DataClassError(_("A policy and its documents are of the same data class."))
    return reference


def create_policy(
    *,
    actor: AuthenticationContext,
    data_class: str,
    country: uuid.UUID,
    policy_type: str,
    title: str,
    title_language: uuid.UUID,
    corpus_assignment: str,
    assignment_reason: str,
    ai_focus: str = "",
    contextual_category: str = "",
    title_en: str = "",
    lead_institution: uuid.UUID | None = None,
    summary: str = "",
) -> uuid.UUID:
    """Create a policy with its provisional corpus assignment, and return its public identifier.

    Preconditions: the actor holds `RESEARCH_CONTRIBUTE`; the data class and
    kind are listed values; the country exists, is active, and fits the data
    class; the language exists and is active; a lead institution, if given,
    exists; the title and the reason for the assignment are not empty; a core
    policy has an AI focus and no contextual category, and a contextual one
    the reverse.

    Side effects: one Policy and one `created` audit event in one
    transaction, and a log line after it commits. No status is stored: it is
    derived from the events recorded later.

    Raises PermissionDenied before anything else is examined;
    InvalidEntryError, RecordNotFoundError, or DataClassError if a value is
    not acceptable. Nothing is stored in any of those cases.
    """
    accounts_selectors.require_permission(actor, Permission.RESEARCH_CONTRIBUTE)
    _listed(data_class, DataClass.values, _("data class"))
    _listed(policy_type, PolicyType.values, _("kind of policy"))
    _assignment(corpus_assignment, ai_focus, contextual_category)
    reason = clean_text(assignment_reason, field=_("reason for the assignment"), max_length=5000)
    country_ref = registry_selectors.country_reference(country)
    if country_ref is None:
        raise RecordNotFoundError(_("The country does not exist."))
    if not country_ref.is_active:
        raise InvalidEntryError(_("The country is deactivated."))
    if not country_fits(data_class, country_ref.alpha2):
        raise DataClassError(
            _(
                "Demonstration records belong only to synthetic countries, "
                "and reference records never do."
            )
        )
    language = registry_selectors.language_reference(title_language)
    if language is None:
        raise RecordNotFoundError(_("The language does not exist."))
    if not language.is_active:
        raise InvalidEntryError(_("The language is deactivated."))
    lead = None
    if lead_institution is not None:
        lead = registry_selectors.institution_key(lead_institution)
        if lead is None:
            raise RecordNotFoundError(_("The institution does not exist."))
    with transaction.atomic():
        policy = Policy.objects.create(
            data_class=data_class,
            country_id=country_ref.pk,
            lead_institution_id=lead.pk if lead else None,
            policy_type=policy_type,
            title=clean_text(title, field=_("title"), max_length=TITLE_MAX_LENGTH),
            title_language_id=language.pk,
            title_en=clean_text(
                title_en, field=_("English title"), max_length=TITLE_MAX_LENGTH, required=False
            ),
            corpus_assignment=corpus_assignment,
            ai_focus=ai_focus,
            contextual_category=contextual_category,
            assignment_reason=reason,
            summary=clean_text(summary, field=_("summary"), max_length=5000, required=False),
        )
        _record(actor, AuditTargetType.POLICY, policy.public_id)
    _log(actor, "policies.policy_created", policy.public_id)
    return policy.public_id


def reassign_policy(
    *,
    actor: AuthenticationContext,
    policy: uuid.UUID,
    corpus_assignment: str,
    assignment_reason: str,
    ai_focus: str = "",
    contextual_category: str = "",
) -> None:
    """Change a policy's provisional corpus assignment, with a new reason.

    Preconditions: as for the assignment in `create_policy`; the policy
    exists; the assignment differs from the present one in at least one of
    its three parts. A policy that has AI-related provisions cannot be moved
    to the contextual registry, where nothing is coded.

    Side effects: the policy's assignment and reason are replaced, and an
    `updated` audit event records each part that changed, in one
    transaction; a log line after it commits.

    Raises PermissionDenied before anything else is examined;
    RecordNotFoundError if the policy does not exist; InvalidEntryError if a
    value is not acceptable or nothing would change. Nothing is stored in
    any of those cases.
    """
    accounts_selectors.require_permission(actor, Permission.RESEARCH_CONTRIBUTE)
    _assignment(corpus_assignment, ai_focus, contextual_category)
    reason = clean_text(assignment_reason, field=_("reason for the assignment"), max_length=5000)
    with transaction.atomic():
        record = _locked_policy(policy)
        changes = tuple(
            AuditChange(field, old or None, new or None)
            for field, old, new in (
                (AuditField.CORPUS_ASSIGNMENT, record.corpus_assignment, corpus_assignment),
                (AuditField.AI_FOCUS, record.ai_focus, ai_focus),
                (AuditField.CONTEXTUAL_CATEGORY, record.contextual_category, contextual_category),
            )
            if old != new
        )
        if not changes:
            raise InvalidEntryError(_("The assignment is the present one."))
        if corpus_assignment == CorpusAssignment.CONTEXTUAL and record.provisions.exists():
            raise InvalidEntryError(
                _("A policy with AI-related provisions stays in the core corpus.")
            )
        record.corpus_assignment = corpus_assignment
        record.ai_focus = ai_focus
        record.contextual_category = contextual_category
        record.assignment_reason = reason
        record.save(
            update_fields=[
                "corpus_assignment",
                "ai_focus",
                "contextual_category",
                "assignment_reason",
            ]
        )
        _record(actor, AuditTargetType.POLICY, record.public_id, AuditAction.UPDATED, changes)
    _log(actor, "policies.policy_reassigned", record.public_id)


def link_document(
    *, actor: AuthenticationContext, policy: uuid.UUID, document: uuid.UUID, role: str
) -> uuid.UUID:
    """Link a document to a policy in a role, and return the link's public identifier.

    Preconditions: the actor holds `RESEARCH_CONTRIBUTE`; the policy and the
    document exist and are of the same data class; the role is listed; the
    document is not already linked to the policy in that role.

    Side effects: one PolicyDocumentLink and one `created` audit event in one
    transaction, and a log line after it commits.

    Raises PermissionDenied before anything else is examined;
    RecordNotFoundError, DataClassError, InvalidEntryError, or
    DuplicateLinkError (a kind of InvalidEntryError). Nothing is stored in
    any of those cases.
    """
    accounts_selectors.require_permission(actor, Permission.RESEARCH_CONTRIBUTE)
    _listed(role, DocumentRole.values, _("role"))
    try:
        with transaction.atomic():
            record = _locked_policy(policy)
            reference = _document_of(record, document)
            if PolicyDocumentLink.objects.filter(
                policy=record, document_id=reference.pk, role=role
            ).exists():
                raise DuplicateLinkError(_("The document is already linked in this role."))
            link = PolicyDocumentLink.objects.create(
                policy=record, document_id=reference.pk, role=role
            )
            _record(actor, AuditTargetType.POLICY_DOCUMENT_LINK, link.public_id)
    except IntegrityError as error:
        if "policies_link_unique" in str(error):
            raise DuplicateLinkError(_("The document is already linked in this role.")) from error
        raise
    _log(actor, "policies.document_linked", link.public_id)
    return link.public_id


def record_event(
    *,
    actor: AuthenticationContext,
    policy: uuid.UUID,
    event_type: str,
    effective_date: date,
    document: uuid.UUID,
    locator: str = "",
) -> uuid.UUID:
    """Record a formal lifecycle event of a policy, and return its public identifier.

    Preconditions: the actor holds `RESEARCH_CONTRIBUTE`; the event is one of
    the five formal events (adopted, amended, entered into force, expired,
    repealed: implementation is never one); the policy exists; the document
    establishing it is linked to the policy as its enacting text, an
    amendment, or an implementing act; the locator is at most 200
    characters. Only one adoption and one entry into force are recorded.

    Side effects: one PolicyEvent, which is append-only, and one `created`
    audit event in one transaction; a log line after it commits. The
    policy's derived status may change; nothing stored on the policy does.

    Raises PermissionDenied before anything else is examined;
    RecordNotFoundError, DataClassError, or InvalidEntryError. Nothing is
    stored in any of those cases.
    """
    accounts_selectors.require_permission(actor, Permission.RESEARCH_CONTRIBUTE)
    _listed(event_type, PolicyEventType.values, _("event"))
    clean_locator = clean_text(
        locator, field=_("locator"), max_length=LOCATOR_MAX_LENGTH, required=False
    )
    with transaction.atomic():
        record = _locked_policy(policy)
        reference = _document_of(record, document)
        if not PolicyDocumentLink.objects.filter(
            policy=record, document_id=reference.pk, role__in=FORMAL_ROLES
        ).exists():
            raise InvalidEntryError(
                _(
                    "A formal event is established by a document linked as the enacting text, "
                    "an amendment, or an implementing act."
                )
            )
        once = (PolicyEventType.ADOPTED, PolicyEventType.ENTERED_INTO_FORCE)
        if event_type in once and record.events.filter(event_type=event_type).exists():
            raise InvalidEntryError(_("This event is already recorded for the policy."))
        event = PolicyEvent.objects.create(
            policy=record,
            event_type=event_type,
            effective_date=effective_date,
            document_id=reference.pk,
            locator=clean_locator,
        )
        _record(actor, AuditTargetType.POLICY_EVENT, event.public_id)
    _log(actor, "policies.event_recorded", event.public_id)
    return event.public_id


def add_provision(
    *,
    actor: AuthenticationContext,
    policy: uuid.UUID,
    provision_type: str,
    document: uuid.UUID,
    locator: str,
    label: str,
    quoted_text: str = "",
) -> uuid.UUID:
    """Record an AI-related provision of a core policy, and return its public identifier.

    Preconditions: the actor holds `RESEARCH_CONTRIBUTE`; the kind is
    listed; the policy exists and is in the core corpus (contextual material
    is not coded); the document is linked to the policy; the locator and the
    label are not empty; quoted text is given only for demonstration data,
    because the text of a reference document is not held (ADR-0020 point 7).

    Side effects: one PolicyProvision of the policy's data class and one
    `created` audit event in one transaction; a log line after it commits.

    Raises PermissionDenied before anything else is examined;
    RecordNotFoundError, DataClassError, or InvalidEntryError. Nothing is
    stored in any of those cases.
    """
    accounts_selectors.require_permission(actor, Permission.RESEARCH_CONTRIBUTE)
    _listed(provision_type, ProvisionType.values, _("kind of provision"))
    with transaction.atomic():
        record = _locked_policy(policy)
        if record.corpus_assignment != CorpusAssignment.CORE:
            raise InvalidEntryError(_("Only a policy in the core corpus has coded provisions."))
        reference = _document_of(record, document)
        if not PolicyDocumentLink.objects.filter(policy=record, document_id=reference.pk).exists():
            raise InvalidEntryError(_("A provision is located in a document of the policy."))
        text = clean_text(quoted_text, field=_("quoted text"), max_length=5000, required=False)
        if text and record.data_class != DataClass.DEMONSTRATION:
            raise DataClassError(_("The text of a reference document is not held."))
        provision = PolicyProvision.objects.create(
            policy=record,
            data_class=record.data_class,
            provision_type=provision_type,
            document_id=reference.pk,
            locator=clean_text(locator, field=_("locator"), max_length=LOCATOR_MAX_LENGTH),
            label=clean_text(label, field=_("description"), max_length=300),
            quoted_text=text,
        )
        _record(actor, AuditTargetType.POLICY_PROVISION, provision.public_id)
    _log(actor, "policies.provision_added", provision.public_id)
    return provision.public_id
