"""Read interface of the demonstrator's research records (ADR-0020).

Every function requires `WORKSPACE_READ`.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from caipo.accounts import selectors as accounts_selectors
from caipo.accounts.selectors import AuthenticationContext, Permission
from caipo.research.analysis import compute, fingerprint, serialise
from caipo.research.inputs import gather
from caipo.research.models import AnalysisMethod, AnalysisRun, SearchLayer, SearchOutcome, SearchRun

__all__ = [
    "AnalysisEntry",
    "Reproduction",
    "SearchEntry",
    "SearchLayer",
    "SearchOutcome",
    "analysis",
    "analyses",
    "reproduce",
    "search",
    "searches",
]


@dataclass(frozen=True)
class AnalysisEntry:
    public_id: uuid.UUID
    data_class: str
    title: str
    method: str
    method_version: int
    parameters: dict[str, Any]
    inputs: list[dict[str, Any]]
    result: list[dict[str, Any]]
    input_fingerprint: str
    result_fingerprint: str
    created_by: str
    created_at: datetime

    @property
    def method_label(self) -> str:
        return str(AnalysisMethod(self.method).label)

    @property
    def releases(self) -> list[tuple[str, str, str]]:
        """Every release the inputs came from, as (source, label, SHA-256)."""
        return sorted({(i["source"], i["release_label"], i["release_sha256"]) for i in self.inputs})


@dataclass(frozen=True)
class Reproduction:
    same_inputs: bool
    same_result: bool
    input_fingerprint: str
    result_fingerprint: str


@dataclass(frozen=True)
class SearchEntry:
    public_id: uuid.UUID
    data_class: str
    title: str
    layer: str
    countries: str
    searched_on: date
    queries: str
    source_universe: str
    inclusion_criteria: str
    exclusion_criteria: str
    sources_examined: str
    method: str
    outcome: str
    summary: str
    created_by: str
    created_at: datetime

    @property
    def layer_label(self) -> str:
        return str(SearchLayer(self.layer).label)

    @property
    def outcome_label(self) -> str:
        return str(SearchOutcome(self.outcome).label)


_ANALYSIS_FIELDS = (
    "public_id",
    "data_class",
    "title",
    "method",
    "method_version",
    "parameters",
    "inputs",
    "result",
    "input_fingerprint",
    "result_fingerprint",
    "created_by__email",
    "created_at",
)
_SEARCH_FIELDS = (
    "public_id",
    "data_class",
    "title",
    "layer",
    "countries",
    "searched_on",
    "queries",
    "source_universe",
    "inclusion_criteria",
    "exclusion_criteria",
    "sources_examined",
    "method",
    "outcome",
    "summary",
    "created_by__email",
    "created_at",
)


def analyses(context: AuthenticationContext | None) -> list[AnalysisEntry]:
    """Return every analysis run, the latest first. Reads only; requires `WORKSPACE_READ`."""
    accounts_selectors.require_permission(context, Permission.WORKSPACE_READ)
    return [
        AnalysisEntry(*row)
        for row in AnalysisRun.objects.order_by("-created_at", "-id").values_list(*_ANALYSIS_FIELDS)
    ]


def analysis(context: AuthenticationContext | None, public_id: uuid.UUID) -> AnalysisEntry | None:
    """Return one analysis run, or None. Reads only; requires `WORKSPACE_READ`."""
    accounts_selectors.require_permission(context, Permission.WORKSPACE_READ)
    row = AnalysisRun.objects.filter(public_id=public_id).values_list(*_ANALYSIS_FIELDS).first()
    return AnalysisEntry(*row) if row else None


def reproduce(context: AuthenticationContext | None, entry: AnalysisEntry) -> Reproduction:
    """Run a recorded analysis again on the values held now, and compare the fingerprints.

    Nothing is written. The same inputs give the same result unless the
    method has changed; different inputs mean a later release has been
    imported since the run. Reads only. Raises PermissionDenied if the
    context may not read the workspace.
    """
    accounts_selectors.require_permission(context, Permission.WORKSPACE_READ)
    parameters = entry.parameters
    inputs = gather(
        context,
        data_class=parameters["data_class"],
        indicators=[uuid.UUID(value) for value in parameters["indicator_ids"]],
        start_year=parameters["start_year"],
        end_year=parameters["end_year"],
    )
    stored = serialise(inputs)
    result = compute(inputs, start_year=parameters["start_year"], end_year=parameters["end_year"])
    return Reproduction(
        same_inputs=fingerprint(stored) == entry.input_fingerprint,
        same_result=fingerprint(result) == entry.result_fingerprint,
        input_fingerprint=fingerprint(stored),
        result_fingerprint=fingerprint(result),
    )


def searches(context: AuthenticationContext | None) -> list[SearchEntry]:
    """Return every search run, the latest first. Reads only; requires `WORKSPACE_READ`."""
    accounts_selectors.require_permission(context, Permission.WORKSPACE_READ)
    return [
        SearchEntry(*row)
        for row in SearchRun.objects.order_by("-searched_on", "-id").values_list(*_SEARCH_FIELDS)
    ]


def search(context: AuthenticationContext | None, public_id: uuid.UUID) -> SearchEntry | None:
    """Return one search run, or None. Reads only; requires `WORKSPACE_READ`."""
    accounts_selectors.require_permission(context, Permission.WORKSPACE_READ)
    row = SearchRun.objects.filter(public_id=public_id).values_list(*_SEARCH_FIELDS).first()
    return SearchEntry(*row) if row else None
