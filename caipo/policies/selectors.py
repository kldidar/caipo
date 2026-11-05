"""Read interface of the demonstrator's policies (ADR-0020).

Every function requires `WORKSPACE_READ`.
"""

import uuid
from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date

from django.db.models import Count

from caipo.accounts import selectors as accounts_selectors
from caipo.accounts.selectors import AuthenticationContext, Permission
from caipo.policies.models import (
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
from caipo.policies.status import FormalStatus, derive_status
from caipo.registry import selectors as registry_selectors
from caipo.sources import selectors as sources_selectors

__all__ = [
    "AIFocus",
    "ContextualCategory",
    "CorpusAssignment",
    "CountryCoverage",
    "DocumentRole",
    "EventEntry",
    "FormalStatus",
    "LinkedDocument",
    "PolicyDetail",
    "PolicyEntry",
    "PolicyEventType",
    "PolicyType",
    "ProvisionEntry",
    "ProvisionType",
    "TimelineEvent",
    "coverage",
    "formal_events",
    "policies",
    "policy_choices",
    "policy_detail",
]


@dataclass(frozen=True)
class PolicyEntry:
    public_id: uuid.UUID
    data_class: str
    country_alpha2: str
    country_name: str
    policy_type: str
    title: str
    title_en: str
    corpus_assignment: str
    ai_focus: str
    contextual_category: str
    assignment_reason: str
    summary: str
    lead_institution: uuid.UUID | None
    status: FormalStatus
    document_count: int
    provision_count: int

    @property
    def display_title(self) -> str:
        return self.title_en or self.title

    @property
    def type_label(self) -> str:
        return str(PolicyType(self.policy_type).label)

    @property
    def corpus_label(self) -> str:
        return str(CorpusAssignment(self.corpus_assignment).label)

    @property
    def is_core(self) -> bool:
        return self.corpus_assignment == CorpusAssignment.CORE

    @property
    def focus_label(self) -> str:
        if self.ai_focus:
            return str(AIFocus(self.ai_focus).label)
        return str(ContextualCategory(self.contextual_category).label)

    @property
    def status_label(self) -> str:
        return str(self.status.label)


@dataclass(frozen=True)
class LinkedDocument:
    role: str
    document: sources_selectors.DocumentEntry

    @property
    def role_label(self) -> str:
        return str(DocumentRole(self.role).label)


@dataclass(frozen=True)
class EventEntry:
    public_id: uuid.UUID
    event_type: str
    effective_date: date
    locator: str
    document_title: str
    document_public_id: uuid.UUID

    @property
    def label(self) -> str:
        return str(PolicyEventType(self.event_type).label)


@dataclass(frozen=True)
class ProvisionEntry:
    public_id: uuid.UUID
    data_class: str
    provision_type: str
    locator: str
    label: str
    quoted_text: str
    document_title: str

    @property
    def type_label(self) -> str:
        return str(ProvisionType(self.provision_type).label)


@dataclass(frozen=True)
class PolicyDetail:
    policy: PolicyEntry
    lead_institution_label: str | None
    documents: tuple[LinkedDocument, ...]
    events: tuple[EventEntry, ...]
    provisions: tuple[ProvisionEntry, ...]


_FIELDS = (
    "pk",
    "public_id",
    "data_class",
    "country__alpha2",
    "country__name_en",
    "policy_type",
    "title",
    "title_en",
    "corpus_assignment",
    "ai_focus",
    "contextual_category",
    "assignment_reason",
    "summary",
    "lead_institution__public_id",
)


def _entries(**filters: object) -> list[PolicyEntry]:
    rows = list(
        Policy.objects.filter(**filters)
        .annotate(
            document_count=Count("document_links__document", distinct=True),
            provision_count=Count("provisions", distinct=True),
        )
        .order_by("country__name_en", "title_en", "title", "id")
        .values_list(*_FIELDS, "document_count", "provision_count")
    )
    events: dict[int, list[tuple[str, date]]] = defaultdict(list)
    for policy_id, event_type, effective_date in PolicyEvent.objects.filter(
        policy_id__in=[row[0] for row in rows]
    ).values_list("policy_id", "event_type", "effective_date"):
        events[policy_id].append((event_type, effective_date))
    entries = []
    for (
        pk,
        public_id,
        data_class,
        alpha2,
        country_name,
        policy_type,
        title,
        title_en,
        corpus_assignment,
        ai_focus,
        contextual_category,
        reason,
        summary,
        lead,
        document_count,
        provision_count,
    ) in rows:
        entries.append(
            PolicyEntry(
                public_id=public_id,
                data_class=data_class,
                country_alpha2=alpha2,
                country_name=country_name,
                policy_type=policy_type,
                title=title,
                title_en=title_en,
                corpus_assignment=corpus_assignment,
                ai_focus=ai_focus,
                contextual_category=contextual_category,
                assignment_reason=reason,
                summary=summary,
                lead_institution=lead,
                status=derive_status(events[pk]),
                document_count=document_count,
                provision_count=provision_count,
            )
        )
    return entries


def policies(
    context: AuthenticationContext | None,
    *,
    corpus_assignment: str,
    country: str | None = None,
    data_class: str | None = None,
    policy_type: str | None = None,
) -> list[PolicyEntry]:
    """Return the policies of one corpus assignment, optionally narrowed, with derived statuses.

    `country` is an alpha-2 code. Reads only. Raises PermissionDenied if the
    context may not read the workspace.
    """
    accounts_selectors.require_permission(context, Permission.WORKSPACE_READ)
    filters: dict[str, object] = {"corpus_assignment": corpus_assignment}
    if country:
        filters["country__alpha2"] = country
    if data_class:
        filters["data_class"] = data_class
    if policy_type:
        filters["policy_type"] = policy_type
    return _entries(**filters)


def policy_detail(
    context: AuthenticationContext | None, public_id: uuid.UUID
) -> PolicyDetail | None:
    """Return a policy with its documents, events, and provisions, or None if there is none.

    Reads only. Raises PermissionDenied if the context may not read the workspace.
    """
    accounts_selectors.require_permission(context, Permission.WORKSPACE_READ)
    found = _entries(public_id=public_id)
    if not found:
        return None
    entry = found[0]
    policy = Policy.objects.only("pk", "lead_institution_id").get(public_id=public_id)
    links = list(
        PolicyDocumentLink.objects.filter(policy=policy)
        .order_by("id")
        .values_list("role", "document_id")
    )
    events = list(
        PolicyEvent.objects.filter(policy=policy)
        .order_by("effective_date", "id")
        .values_list("public_id", "event_type", "effective_date", "locator", "document_id")
    )
    provisions = list(
        PolicyProvision.objects.filter(policy=policy)
        .order_by("id")
        .values_list(
            "public_id",
            "data_class",
            "provision_type",
            "locator",
            "label",
            "quoted_text",
            "document_id",
        )
    )
    keys = {key for _, key in links} | {row[4] for row in events} | {row[6] for row in provisions}
    documents = sources_selectors.documents_by_key(sorted(keys))
    lead_label = None
    if entry.lead_institution is not None:
        lead_label = dict(registry_selectors.institution_choices()).get(entry.lead_institution)
    return PolicyDetail(
        policy=entry,
        lead_institution_label=lead_label,
        documents=tuple(LinkedDocument(role, documents[key]) for role, key in links),
        events=tuple(
            EventEntry(
                public_id,
                event_type,
                effective_date,
                locator,
                documents[key].display_title,
                documents[key].public_id,
            )
            for public_id, event_type, effective_date, locator, key in events
        ),
        provisions=tuple(
            ProvisionEntry(
                public_id,
                data_class,
                provision_type,
                locator,
                label,
                quoted,
                documents[key].display_title,
            )
            for public_id, data_class, provision_type, locator, label, quoted, key in provisions
        ),
    )


@dataclass(frozen=True)
class TimelineEvent:
    """A formal lifecycle event of a policy in the core AI policy corpus, for a time axis."""

    country_alpha2: str
    country_name: str
    effective_date: date
    event_type: str
    policy_public_id: uuid.UUID
    policy_title: str

    @property
    def label(self) -> str:
        return str(PolicyEventType(self.event_type).label)


def formal_events(
    context: AuthenticationContext | None, *, data_class: str, countries: Collection[str]
) -> list[TimelineEvent]:
    """Return the formal events of core-corpus policies of these countries, oldest first.

    `countries` are alpha-2 codes, and only policies of `data_class` count, so
    that synthetic and reference records are never shown together. Policies
    of the contextual registry are left out: they are never counted as AI
    policy. A policy's English title is used where one is recorded, and its
    title as written otherwise. Reads only. Raises PermissionDenied if the
    context may not read the workspace.
    """
    accounts_selectors.require_permission(context, Permission.WORKSPACE_READ)
    rows = (
        PolicyEvent.objects.filter(
            policy__data_class=data_class,
            policy__corpus_assignment=CorpusAssignment.CORE,
            policy__country__alpha2__in=list(countries),
        )
        .order_by("effective_date", "policy__country__alpha2", "id")
        .values_list(
            "policy__country__alpha2",
            "policy__country__name_en",
            "effective_date",
            "event_type",
            "policy__public_id",
            "policy__title_en",
            "policy__title",
        )
    )
    return [
        TimelineEvent(alpha2, name, effective, event_type, public_id, title_en or title)
        for alpha2, name, effective, event_type, public_id, title_en, title in rows
    ]


def policy_choices(
    context: AuthenticationContext | None, *, corpus_assignment: str | None = None
) -> list[tuple[uuid.UUID, str, str]]:
    """Return policies as (public identifier, label, data class) for a form.

    Reads only. Raises PermissionDenied if the context may not read the workspace.
    """
    accounts_selectors.require_permission(context, Permission.WORKSPACE_READ)
    rows = Policy.objects.all()
    if corpus_assignment:
        rows = rows.filter(corpus_assignment=corpus_assignment)
    return [
        (public_id, title_en or title, data_class)
        for public_id, title, title_en, data_class in rows.order_by("title").values_list(
            "public_id", "title", "title_en", "data_class"
        )
    ]


@dataclass(frozen=True)
class CountryCoverage:
    alpha2: str
    name: str
    data_class: str
    core: int
    contextual: int
    provisions: int
    events: int


def coverage(context: AuthenticationContext | None) -> list[CountryCoverage]:
    """Return, per country, how many core and contextual policies, provisions, and events exist.

    Only countries with at least one policy appear; a country with none is
    not shown as having zero, because nothing was searched for it here.
    Reads only. Raises PermissionDenied if the context may not read the workspace.
    """
    accounts_selectors.require_permission(context, Permission.WORKSPACE_READ)
    names: dict[str, tuple[str, str]] = {}
    counted: dict[tuple[str, str], int] = {}
    for alpha2, name, data_class, assignment, number in (
        Policy.objects.values_list(
            "country__alpha2", "country__name_en", "data_class", "corpus_assignment"
        )
        .annotate(n=Count("id"))
        .order_by("country__name_en")
    ):
        names.setdefault(alpha2, (name, data_class))
        counted[(alpha2, assignment)] = number
    provisions = dict(
        PolicyProvision.objects.values_list("policy__country__alpha2").annotate(n=Count("id"))
    )
    events = dict(
        PolicyEvent.objects.values_list("policy__country__alpha2").annotate(n=Count("id"))
    )
    return [
        CountryCoverage(
            alpha2=alpha2,
            name=name,
            data_class=data_class,
            core=counted.get((alpha2, CorpusAssignment.CORE), 0),
            contextual=counted.get((alpha2, CorpusAssignment.CONTEXTUAL), 0),
            provisions=provisions.get(alpha2, 0),
            events=events.get(alpha2, 0),
        )
        for alpha2, (name, data_class) in names.items()
    ]
