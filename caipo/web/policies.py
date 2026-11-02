"""The policy pages of the demonstrator (ADR-0020).

The core AI policy corpus and the contextual policy registry are listed on
separate tabs and never mixed in one list (RESEARCH_PROTOCOL.md §3.1.5). A
policy page shows its provisional assignment with the reason, its formal
status as derived from its events, its AI-related provisions, and every
document with the provenance of its source.

These views handle the request and nothing else. Each change is a POST that
names the policy in its path; `caipo.policies` checks the permission again.
"""

import uuid
from collections.abc import Callable
from typing import Any

from django.forms import Form
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from caipo.accounts import selectors as accounts_selectors
from caipo.accounts.selectors import AuthenticationContext, Permission
from caipo.core.data_class import DataClass
from caipo.core.entry import InvalidEntryError
from caipo.policies import selectors, services
from caipo.policies.selectors import CorpusAssignment, PolicyDetail, PolicyType
from caipo.sources import selectors as sources_selectors
from caipo.web.access import requires
from caipo.web.workspace import (
    FORM_ERROR,
    REFUSED,
    actor_of,
    country_options,
    institution_options,
    language_options,
    parse_uuid,
)
from caipo.web.workspace_forms import EventForm, LinkForm, PolicyForm, ProvisionForm, ReassignForm


def _chosen(value: str, allowed: list[str]) -> str | None:
    return value if value in allowed else None


@requires(Permission.WORKSPACE_READ)
@never_cache
@require_safe
def browse(request: HttpRequest) -> HttpResponse:
    """List the policies of one corpus, chosen by tab, with optional filters.

    `?corpus=core` (the default) or `?corpus=contextual`; `?country=` an
    alpha-2 code; `?class=` a data class; `?type=` a kind of policy. An
    unknown value is ignored rather than refused.
    """
    actor = actor_of(request)
    corpus = _chosen(request.GET.get("corpus", ""), CorpusAssignment.values) or str(
        CorpusAssignment.CORE
    )
    data_class = _chosen(request.GET.get("class", ""), DataClass.values)
    policy_type = _chosen(request.GET.get("type", ""), PolicyType.values)
    coverage = selectors.coverage(actor)
    countries = [(row.alpha2, row.name) for row in coverage]
    country = _chosen(request.GET.get("country", ""), [code for code, _name in countries])
    entries = selectors.policies(
        actor,
        corpus_assignment=corpus,
        country=country,
        data_class=data_class,
        policy_type=policy_type,
    )
    return render(
        request,
        "web/policies.html",
        {
            "corpus": corpus,
            "entries": entries,
            "coverage": coverage,
            "countries": countries,
            "country": country or "",
            "data_class": data_class or "",
            "policy_type": policy_type or "",
            "data_classes": DataClass.choices,
            "policy_types": PolicyType.choices,
            "filtered": bool(country or data_class or policy_type),
            "has_demonstration": any(
                entry.data_class == DataClass.DEMONSTRATION for entry in entries
            ),
            "may_contribute": accounts_selectors.can(actor, Permission.RESEARCH_CONTRIBUTE),
        },
    )


def _linked(detail: PolicyDetail) -> list[tuple[str, str]]:
    return [
        (str(item.document.public_id), f"{item.document.display_title} ({item.role_label})")
        for item in detail.documents
    ]


def _offer(actor: AuthenticationContext, detail: PolicyDetail, form: Form) -> Form:
    """Give a policy form the documents it may name: of the policy's class, or already linked."""
    if isinstance(form, LinkForm):
        form.offer(
            "document",
            [
                (str(key), label)
                for key, label in sources_selectors.document_choices(
                    actor, data_class=detail.policy.data_class
                )
            ],
        )
    elif isinstance(form, EventForm | ProvisionForm):
        form.offer("document", _linked(detail))
    return form


def _detail_forms(
    actor: AuthenticationContext, detail: PolicyDetail, bound: dict[str, Form]
) -> dict[str, Form]:
    policy = detail.policy
    forms: dict[str, Form] = {
        "link_form": LinkForm(),
        "event_form": EventForm(),
        "provision_form": ProvisionForm(),
        "reassign_form": ReassignForm(
            initial={
                "corpus_assignment": policy.corpus_assignment,
                "ai_focus": policy.ai_focus,
                "contextual_category": policy.contextual_category,
            }
        ),
    }
    forms.update(bound)
    return {name: _offer(actor, detail, form) for name, form in forms.items()}


def _detail_page(
    request: HttpRequest,
    actor: AuthenticationContext,
    public_id: uuid.UUID,
    *,
    error: str | None = None,
    status: int = 200,
    **bound: Form,
) -> HttpResponse:
    detail = selectors.policy_detail(actor, public_id)
    if detail is None:
        raise Http404
    may_contribute = accounts_selectors.can(actor, Permission.RESEARCH_CONTRIBUTE)
    context: dict[str, Any] = {
        "detail": detail,
        "policy": detail.policy,
        "error": error,
        "saved": "saved" in request.GET,
        "may_contribute": may_contribute,
    }
    if may_contribute:
        context.update(_detail_forms(actor, detail, bound))
    return render(request, "web/policy.html", context, status=status)


@requires(Permission.WORKSPACE_READ)
@never_cache
@require_safe
def detail(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Show a policy with its provenance, derived status, events, and provisions."""
    return _detail_page(request, actor_of(request), public_id)


@requires(Permission.RESEARCH_CONTRIBUTE)
@never_cache
@csrf_protect
@require_http_methods(["GET", "HEAD", "POST"])
def create(request: HttpRequest) -> HttpResponse:
    """Show the form for a new policy, and create it on POST."""
    actor = actor_of(request)
    form = PolicyForm(request.POST if request.method == "POST" else None)
    form.offer("country", country_options())
    form.offer("title_language", language_options())
    form.offer("lead_institution", institution_options(), blank=True)
    error = None
    if request.method == "POST":
        if form.is_valid():
            data = form.cleaned_data
            country = parse_uuid(data["country"])
            language = parse_uuid(data["title_language"])
            try:
                if country is None or language is None:
                    raise InvalidEntryError(_("Choose a country and a language."))
                public_id = services.create_policy(
                    actor=actor,
                    data_class=data["data_class"],
                    country=country,
                    policy_type=data["policy_type"],
                    title=data["title"],
                    title_language=language,
                    corpus_assignment=data["corpus_assignment"],
                    assignment_reason=data["assignment_reason"],
                    ai_focus=data["ai_focus"],
                    contextual_category=data["contextual_category"],
                    title_en=data["title_en"],
                    lead_institution=parse_uuid(data["lead_institution"]),
                    summary=data["summary"],
                )
            except REFUSED as refusal:
                error = str(refusal)
            else:
                return HttpResponseRedirect(reverse("policy", args=[public_id]))
        else:
            error = str(FORM_ERROR)
    return render(
        request,
        "web/policy_new.html",
        {"form": form, "error": error},
        status=400 if error else 200,
    )


def _require(actor: AuthenticationContext, public_id: uuid.UUID) -> PolicyDetail:
    detail = selectors.policy_detail(actor, public_id)
    if detail is None:
        raise Http404
    return detail


def _change(
    request: HttpRequest,
    public_id: uuid.UUID,
    form_class: type[Form],
    form_name: str,
    apply: Callable[[AuthenticationContext, dict[str, Any]], object],
) -> HttpResponse:
    """Validate a POSTed form of the policy page, apply it, and answer with the page."""
    actor = actor_of(request)
    form = _offer(actor, _require(actor, public_id), form_class(request.POST))
    error = str(FORM_ERROR)
    if form.is_valid():
        try:
            apply(actor, form.cleaned_data)
        except REFUSED as refusal:
            error = str(refusal)
        else:
            return HttpResponseRedirect(reverse("policy", args=[public_id]) + "?saved=1")
    return _detail_page(request, actor, public_id, error=error, status=400, **{form_name: form})


def _document(data: dict[str, Any]) -> uuid.UUID:
    document = parse_uuid(data["document"])
    if document is None:
        raise InvalidEntryError(_("Choose a document."))
    return document


@requires(Permission.RESEARCH_CONTRIBUTE)
@never_cache
@csrf_protect
@require_POST
def link_document(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Link a document to the policy in a role."""
    return _change(
        request,
        public_id,
        LinkForm,
        "link_form",
        lambda actor, data: services.link_document(
            actor=actor, policy=public_id, document=_document(data), role=data["role"]
        ),
    )


@requires(Permission.RESEARCH_CONTRIBUTE)
@never_cache
@csrf_protect
@require_POST
def record_event(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Record a formal lifecycle event of the policy."""
    return _change(
        request,
        public_id,
        EventForm,
        "event_form",
        lambda actor, data: services.record_event(
            actor=actor,
            policy=public_id,
            event_type=data["event_type"],
            effective_date=data["effective_date"],
            document=_document(data),
            locator=data["locator"],
        ),
    )


@requires(Permission.RESEARCH_CONTRIBUTE)
@never_cache
@csrf_protect
@require_POST
def add_provision(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Record an AI-related provision of the policy."""
    return _change(
        request,
        public_id,
        ProvisionForm,
        "provision_form",
        lambda actor, data: services.add_provision(
            actor=actor,
            policy=public_id,
            provision_type=data["provision_type"],
            document=_document(data),
            locator=data["locator"],
            label=data["label"],
            quoted_text=data["quoted_text"],
        ),
    )


@requires(Permission.RESEARCH_CONTRIBUTE)
@never_cache
@csrf_protect
@require_POST
def reassign(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Change the policy's provisional corpus assignment."""
    return _change(
        request,
        public_id,
        ReassignForm,
        "reassign_form",
        lambda actor, data: services.reassign_policy(
            actor=actor,
            policy=public_id,
            corpus_assignment=data["corpus_assignment"],
            assignment_reason=data["assignment_reason"],
            ai_focus=data["ai_focus"],
            contextual_category=data["contextual_category"],
        ),
    )
