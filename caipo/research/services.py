"""Write interface of the demonstrator's research records (ADR-0020).

Each operation requires `RESEARCH_CONTRIBUTE` first, then validates, writes,
and records its audit event, in one transaction. Records are append-only:
a run or a search, once recorded, is never changed.
"""

import logging
import uuid
from datetime import date

from django.db import transaction

from caipo.accounts import selectors as accounts_selectors
from caipo.accounts import services as accounts_services
from caipo.accounts.selectors import AuditAction, AuditTargetType, AuthenticationContext, Permission
from caipo.core.data_class import DataClass
from caipo.core.entry import InvalidEntryError, clean_text
from caipo.research.analysis import METHOD, METHOD_VERSION, compute, fingerprint, serialise
from caipo.research.inputs import gather
from caipo.research.models import AnalysisRun, SearchLayer, SearchOutcome, SearchRun

logger = logging.getLogger(__name__)


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


def run_analysis(
    *,
    actor: AuthenticationContext,
    title: str,
    data_class: str,
    indicators: list[uuid.UUID],
    start_year: int,
    end_year: int,
) -> uuid.UUID:
    """Run the descriptive-change method and record the run, and return its public identifier.

    Preconditions: the actor holds `RESEARCH_CONTRIBUTE`; the title is not
    empty; the data class is listed; 1 to 12 indicators are named; the first
    year is before the last; at least one value of the indicators, of that
    data class, lies in the range. Indicators of the other data class are
    left out, so a run never mixes the two.

    Side effects: one AnalysisRun, with its parameters, every input value and
    its release, the result, and the SHA-256 of the inputs and of the result,
    and one `created` audit event, in one transaction; a log line after it
    commits.

    Raises PermissionDenied before anything else is examined;
    InvalidEntryError or RecordNotFoundError. Nothing is stored in either case.
    """
    accounts_selectors.require_permission(actor, Permission.RESEARCH_CONTRIBUTE)
    clean_title = clean_text(title, field="title", max_length=300)
    inputs = gather(
        actor,
        data_class=data_class,
        indicators=indicators,
        start_year=start_year,
        end_year=end_year,
    )
    stored_inputs = serialise(inputs)
    result = compute(inputs, start_year=start_year, end_year=end_year)
    parameters = {
        "indicator_ids": sorted(str(public_id) for public_id in set(indicators)),
        "indicators": sorted({row["indicator"] for row in stored_inputs}),
        "start_year": start_year,
        "end_year": end_year,
        "data_class": data_class,
    }
    with transaction.atomic():
        run = AnalysisRun.objects.create(
            data_class=data_class,
            title=clean_title,
            method=METHOD,
            method_version=METHOD_VERSION,
            parameters=parameters,
            inputs=stored_inputs,
            result=result,
            input_fingerprint=fingerprint(stored_inputs),
            result_fingerprint=fingerprint(result),
            created_by=actor.user,
        )
        _record(actor, AuditTargetType.ANALYSIS_RUN, run.public_id)
    logger.info(
        "Analysis run recorded",
        extra={
            "event": "research.analysis_run",
            "public_id": str(run.public_id),
            "actor_id": actor.user.pk,
        },
    )
    return run.public_id


def record_search(
    *,
    actor: AuthenticationContext,
    data_class: str,
    title: str,
    layer: str,
    countries: str,
    searched_on: date,
    queries: str,
    source_universe: str,
    inclusion_criteria: str,
    sources_examined: str,
    method: str,
    outcome: str,
    summary: str,
    exclusion_criteria: str = "",
) -> uuid.UUID:
    """Record a search for sources, and return its public identifier.

    Preconditions: the actor holds `RESEARCH_CONTRIBUTE`; the data class,
    layer, and outcome are listed; the title, countries, queries, sources in
    scope, inclusion criteria, sources examined, method, and summary are not
    empty. The outcome is bounded by what was examined, and the record is
    the evidence of that bound.

    Side effects: one SearchRun and one `created` audit event in one
    transaction; a log line after it commits.

    Raises PermissionDenied before anything else is examined; InvalidEntryError.
    """
    accounts_selectors.require_permission(actor, Permission.RESEARCH_CONTRIBUTE)
    for value, values, field in (
        (data_class, DataClass.values, "data class"),
        (layer, SearchLayer.values, "layer"),
        (outcome, SearchOutcome.values, "outcome"),
    ):
        if value not in values:
            raise InvalidEntryError(f"The {field} is not one of those listed.")

    def long(text: str, field: str, required: bool = True) -> str:
        return clean_text(text, field=field, max_length=10000, required=required)

    with transaction.atomic():
        search = SearchRun.objects.create(
            data_class=data_class,
            title=clean_text(title, field="title", max_length=300),
            layer=layer,
            countries=clean_text(countries, field="countries", max_length=200),
            searched_on=searched_on,
            queries=long(queries, "queries"),
            source_universe=long(source_universe, "sources in scope"),
            inclusion_criteria=long(inclusion_criteria, "inclusion criteria"),
            exclusion_criteria=long(exclusion_criteria, "exclusion criteria", required=False),
            sources_examined=long(sources_examined, "sources examined"),
            method=long(method, "method"),
            outcome=outcome,
            summary=long(summary, "summary"),
            created_by=actor.user,
        )
        _record(actor, AuditTargetType.SEARCH_RUN, search.public_id)
    logger.info(
        "Search run recorded",
        extra={
            "event": "research.search_run",
            "public_id": str(search.public_id),
            "actor_id": actor.user.pk,
        },
    )
    return search.public_id
