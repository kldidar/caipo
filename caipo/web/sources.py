"""The source pages of the demonstrator (ADR-0020): sources, their documents, and registering both.

These views handle the request and nothing else. What may be registered,
and by whom, is decided by `caipo.sources`, whose services check the
permission again.
"""

import uuid

from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_safe

from caipo.accounts import selectors as accounts_selectors
from caipo.accounts.selectors import Permission
from caipo.core.data_class import DataClass
from caipo.core.entry import RecordNotFoundError
from caipo.sources import selectors, services
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
from caipo.web.workspace_forms import DocumentForm, SourceForm


@requires(Permission.WORKSPACE_READ)
@never_cache
@require_safe
def browse(request: HttpRequest) -> HttpResponse:
    """List the sources, optionally of one data class (`?class=`)."""
    actor = actor_of(request)
    chosen = request.GET.get("class", "")
    data_class = chosen if chosen in DataClass.values else None
    return render(
        request,
        "web/sources.html",
        {
            "sources": selectors.sources(actor, data_class=data_class),
            "data_class": data_class or "",
            "data_classes": DataClass.choices,
            "may_contribute": accounts_selectors.can(actor, Permission.RESEARCH_CONTRIBUTE),
        },
    )


@requires(Permission.WORKSPACE_READ)
@never_cache
@require_safe
def detail(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Show a source, its terms and coverage, and the documents registered from it."""
    actor = actor_of(request)
    found = selectors.source_detail(actor, public_id)
    if found is None:
        raise Http404
    return render(
        request,
        "web/source.html",
        {
            "detail": found,
            "may_contribute": accounts_selectors.can(actor, Permission.RESEARCH_CONTRIBUTE),
        },
    )


@requires(Permission.RESEARCH_CONTRIBUTE)
@never_cache
@csrf_protect
@require_http_methods(["GET", "HEAD", "POST"])
def create(request: HttpRequest) -> HttpResponse:
    """Show the form for a new source, and register it on POST."""
    actor = actor_of(request)
    form = SourceForm(request.POST if request.method == "POST" else None)
    form.offer("country", country_options(), blank=True)
    error = None
    if request.method == "POST":
        if form.is_valid():
            data = form.cleaned_data
            try:
                public_id = services.create_source(
                    actor=actor,
                    data_class=data["data_class"],
                    name=data["name"],
                    publisher=data["publisher"],
                    url=data["url"],
                    source_tier=data["source_tier"],
                    permitted_use=data["permitted_use"],
                    accessed_on=data["accessed_on"],
                    country=parse_uuid(data["country"]),
                    licence=data["licence"],
                    licence_verified=data["licence_verified"],
                    coverage=data["coverage"],
                    limitations=data["limitations"],
                )
            except REFUSED as refusal:
                error = str(refusal)
            else:
                return HttpResponseRedirect(reverse("source", args=[public_id]))
        else:
            error = str(FORM_ERROR)
    status = 400 if error else 200
    return render(request, "web/source_new.html", {"form": form, "error": error}, status=status)


@requires(Permission.RESEARCH_CONTRIBUTE)
@never_cache
@csrf_protect
@require_http_methods(["GET", "HEAD", "POST"])
def create_document(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Show the form for a new document of a source, and register it on POST."""
    actor = actor_of(request)
    found = selectors.source_detail(actor, public_id)
    if found is None:
        raise Http404
    form = DocumentForm(request.POST if request.method == "POST" else None)
    form.offer("country", country_options())
    form.offer("title_language", language_options())
    form.offer("issuing_institution", institution_options(), blank=True)
    error = None
    if request.method == "POST":
        if form.is_valid():
            data = form.cleaned_data
            country = parse_uuid(data["country"])
            language = parse_uuid(data["title_language"])
            try:
                if country is None or language is None:
                    raise RecordNotFoundError("Choose a country and a language.")
                services.create_document(
                    actor=actor,
                    source=public_id,
                    country=country,
                    document_type=data["document_type"],
                    title=data["title"],
                    title_language=language,
                    title_en=data["title_en"],
                    title_en_official=data["title_en_official"],
                    official_identifier=data["official_identifier"],
                    date_of_issue=data["date_of_issue"],
                    official_url=data["official_url"],
                    accessed_on=data["accessed_on"],
                    issuing_institution=parse_uuid(data["issuing_institution"]),
                    notes=data["notes"],
                )
            except REFUSED as refusal:
                error = str(refusal)
            else:
                return HttpResponseRedirect(reverse("source", args=[public_id]))
        else:
            error = str(FORM_ERROR)
    status = 400 if error else 200
    return render(
        request,
        "web/document_new.html",
        {"form": form, "error": error, "source": found.source},
        status=status,
    )
