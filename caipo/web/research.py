"""The research workspace of the demonstrator (ADR-0020): analysis runs, search runs, exports.

These views handle the request and nothing else. Running an analysis and
recording a search are decided by `caipo.research`, which checks the
permission again. Checking a run's reproducibility writes nothing.
"""

import uuid
from decimal import Decimal
from typing import Any

from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_safe

from caipo.accounts import selectors as accounts_selectors
from caipo.accounts.selectors import Permission
from caipo.core.data_class import DataClass
from caipo.indicators import selectors as indicators_selectors
from caipo.policies import selectors as policies_selectors
from caipo.policies.selectors import CorpusAssignment
from caipo.research import selectors, services
from caipo.research.selectors import AnalysisEntry
from caipo.web.access import requires
from caipo.web.exports import NON_CAUSATION, csv_response, json_response
from caipo.web.workspace import FORM_ERROR, REFUSED, actor_of
from caipo.web.workspace_forms import AnalysisForm, SearchForm

_RESULT_COLUMNS = (
    "layer",
    "indicator",
    "indicator_name",
    "unit",
    "country",
    "start_year",
    "end_year",
    "start_value",
    "end_value",
    "absolute_change",
    "relative_change_percent",
    "not_computed_because",
    "years_held",
    "years_missing",
    "values_flagged",
)
# The columns whose values the stored result holds as exact decimal text.
_NUMERIC_COLUMNS = frozenset(
    {"start_value", "end_value", "absolute_change", "relative_change_percent"}
)


def _indicator_options(actor: Any, data_class: str) -> list[tuple[str, str]]:
    return [
        (str(public_id), f"{layer} · {name}")
        for public_id, name, layer in indicators_selectors.indicator_choices(
            actor, data_class=data_class
        )
    ]


@requires(Permission.WORKSPACE_READ)
@never_cache
@csrf_protect
@require_http_methods(["GET", "HEAD", "POST"])
def analyses(request: HttpRequest) -> HttpResponse:
    """List the analysis runs; a Researcher runs a new one on POST."""
    actor = actor_of(request)
    may_contribute = accounts_selectors.can(actor, Permission.RESEARCH_CONTRIBUTE)
    chosen = request.POST.get("data_class") or request.GET.get("class", "")
    data_class = chosen if chosen in DataClass.values else str(DataClass.REFERENCE)
    form = AnalysisForm(
        request.POST if request.method == "POST" else None, initial={"data_class": data_class}
    )
    form.offer("indicators", _indicator_options(actor, data_class))
    error = None
    if request.method == "POST":
        if not may_contribute:
            return HttpResponse(status=403)
        if form.is_valid():
            data = form.cleaned_data
            try:
                public_id = services.run_analysis(
                    actor=actor,
                    title=data["title"],
                    data_class=data["data_class"],
                    indicators=[uuid.UUID(value) for value in data["indicators"]],
                    start_year=data["start_year"],
                    end_year=data["end_year"],
                )
            except REFUSED as refusal:
                error = str(refusal)
            else:
                return HttpResponseRedirect(reverse("analysis", args=[public_id]))
        else:
            error = str(FORM_ERROR)
    return render(
        request,
        "web/analyses.html",
        {
            "runs": selectors.analyses(actor),
            "form": form if may_contribute else None,
            "data_class": data_class,
            "error": error,
        },
        status=400 if error else 200,
    )


def _run(request: HttpRequest, public_id: uuid.UUID) -> tuple[Any, AnalysisEntry]:
    actor = actor_of(request)
    entry = selectors.analysis(actor, public_id)
    if entry is None:
        raise Http404
    return actor, entry


@requires(Permission.WORKSPACE_READ)
@never_cache
@require_safe
def analysis(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Show a run: parameters, result, inputs and their releases, fingerprints.

    `?check=1` runs it again on the values held now and compares fingerprints.
    """
    actor, entry = _run(request, public_id)
    reproduction = selectors.reproduce(actor, entry) if request.GET.get("check") else None
    return render(
        request,
        "web/analysis.html",
        {
            "analysis": entry,
            "reproduction": reproduction,
            "non_causation": NON_CAUSATION,
            "methodology": METHODOLOGY,
        },
    )


METHODOLOGY = (
    "Descriptive change between two years: for each indicator and country, the first and last "
    "values of the range, their absolute and relative change, and how many years hold a value. "
    "Missing values are left missing; a change is not computed where the first or last value is "
    "missing. The value of the latest release is used."
)


def _notes(entry: AnalysisEntry) -> list[str]:
    return [
        f"CAIPO analysis run {entry.public_id}: {entry.title}",
        f"Data class: {entry.data_class}"
        + (
            " (synthetic; not evidence about any real country)"
            if entry.data_class == DataClass.DEMONSTRATION
            else ""
        ),
        f"Method: {entry.method} version {entry.method_version};"
        f" run at {entry.created_at.isoformat()}",
        f"Input fingerprint (SHA-256): {entry.input_fingerprint}",
        f"Result fingerprint (SHA-256): {entry.result_fingerprint}",
        "Releases: "
        + "; ".join(f"{source}, {label}, SHA-256 {sha}" for source, label, sha in entry.releases),
        METHODOLOGY,
        NON_CAUSATION,
    ]


@requires(Permission.WORKSPACE_READ)
@never_cache
@require_safe
def analysis_csv(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Export a run's result as CSV, with its provenance and methodology note.

    The stored result holds its values as exact decimal text; they are
    written as numbers, so that a fall keeps its sign and is not quoted.
    """
    _, entry = _run(request, public_id)

    def cell(row: dict[str, Any], column: str) -> object:
        value = row.get(column)
        return Decimal(value) if column in _NUMERIC_COLUMNS and value is not None else value

    return csv_response(
        f"caipo-analysis-{entry.public_id}.csv",
        _notes(entry),
        ("data_class", *_RESULT_COLUMNS),
        (
            (entry.data_class, *(cell(row, column) for column in _RESULT_COLUMNS))
            for row in entry.result
        ),
    )


@requires(Permission.WORKSPACE_READ)
@never_cache
@require_safe
def analysis_json(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Export a run whole as JSON: parameters, inputs with releases, result, fingerprints."""
    _, entry = _run(request, public_id)
    return json_response(
        f"caipo-analysis-{entry.public_id}.json",
        {
            "analysis_run": str(entry.public_id),
            "title": entry.title,
            "data_class": entry.data_class,
            "method": entry.method,
            "method_version": entry.method_version,
            "run_at": entry.created_at.isoformat(),
            "parameters": entry.parameters,
            "input_fingerprint": entry.input_fingerprint,
            "result_fingerprint": entry.result_fingerprint,
            "methodology": METHODOLOGY,
            "non_causation_notice": NON_CAUSATION,
            "inputs": entry.inputs,
            "result": entry.result,
        },
    )


@requires(Permission.WORKSPACE_READ)
@never_cache
@csrf_protect
@require_http_methods(["GET", "HEAD", "POST"])
def searches(request: HttpRequest) -> HttpResponse:
    """List the search runs; a Researcher records a new one on POST."""
    actor = actor_of(request)
    may_contribute = accounts_selectors.can(actor, Permission.RESEARCH_CONTRIBUTE)
    form = SearchForm(request.POST if request.method == "POST" else None)
    error = None
    if request.method == "POST":
        if not may_contribute:
            return HttpResponse(status=403)
        if form.is_valid():
            try:
                public_id = services.record_search(actor=actor, **form.cleaned_data)
            except REFUSED as refusal:
                error = str(refusal)
            else:
                return HttpResponseRedirect(reverse("search", args=[public_id]))
        else:
            error = str(FORM_ERROR)
    return render(
        request,
        "web/searches.html",
        {
            "runs": selectors.searches(actor),
            "form": form if may_contribute else None,
            "error": error,
        },
        status=400 if error else 200,
    )


@requires(Permission.WORKSPACE_READ)
@never_cache
@require_safe
def search(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Show a search run in full."""
    entry = selectors.search(actor_of(request), public_id)
    if entry is None:
        raise Http404
    return render(request, "web/search.html", {"search": entry})


@requires(Permission.WORKSPACE_READ)
@never_cache
@require_safe
def policies_csv(request: HttpRequest) -> HttpResponse:
    """Export the policy register as CSV: both corpora, kept apart by a column, with provenance."""
    actor = actor_of(request)
    rows = []
    for corpus in (CorpusAssignment.CORE, CorpusAssignment.CONTEXTUAL):
        for entry in policies_selectors.policies(actor, corpus_assignment=corpus):
            detail = policies_selectors.policy_detail(actor, entry.public_id)
            documents = detail.documents if detail else ()
            rows.append(
                (
                    entry.data_class,
                    entry.corpus_label,
                    "provisional",
                    entry.country_alpha2,
                    entry.display_title,
                    entry.title,
                    entry.type_label,
                    entry.focus_label,
                    entry.status_label,
                    entry.assignment_reason,
                    " | ".join(
                        f"{item.role_label}: {item.document.display_title}"
                        f" [{item.document.official_identifier or 'no identifier'}]"
                        f" {item.document.official_url or ''}"
                        f" (source: {item.document.source_name}, tier {item.document.source_tier})"
                        for item in documents
                    ),
                    entry.provision_count,
                )
            )
    return csv_response(
        "caipo-policy-register.csv",
        [
            "CAIPO policy register. Core and contextual material are kept apart by the"
            " corpus column; contextual material is never counted as AI policy.",
            "Every assignment is provisional, not an eligibility decision under the"
            " research protocol.",
            "Rows of data class 'demonstration' are synthetic and are not evidence about"
            " any real country.",
            "Formal status is derived from formal events; 'No formal event recorded' means"
            " none is recorded here.",
        ],
        (
            "data_class",
            "corpus",
            "assignment",
            "country",
            "title",
            "title_as_written",
            "kind",
            "ai_focus_or_category",
            "formal_status",
            "reason",
            "documents",
            "ai_related_provisions",
        ),
        rows,
    )
