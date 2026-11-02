"""The services and selectors of the demonstrator's research records (ADR-0020)."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection, transaction

from caipo.accounts.selectors import AuthenticationContext
from caipo.core.entry import InvalidEntryError, RecordNotFoundError
from caipo.indicators import services as indicator_services
from caipo.indicators.services import ObservationRow
from caipo.research import selectors, services
from caipo.research.models import AnalysisRun, SearchRun
from caipo.sources.tests.helpers import World, audit_events, make_source

pytestmark = pytest.mark.django_db


@pytest.fixture
def indicators(researcher: AuthenticationContext, world: World) -> dict[str, uuid.UUID]:
    demo = make_source(researcher, world)
    reference = make_source(researcher, world, "reference")
    ids = {
        "demo": indicator_services.create_indicator(
            actor=researcher,
            source=demo,
            code="TEST-D",
            name="TEST demo",
            unit="%",
            layer="A",
            layer_reason="TEST",
        ),
        "reference": indicator_services.create_indicator(
            actor=researcher,
            source=reference,
            code="TEST-R",
            name="TEST reference",
            unit="%",
            layer="A",
            layer_reason="TEST",
        ),
        "demo_source": demo,
    }
    indicator_services.import_release(
        actor=researcher,
        source=demo,
        label="TEST",
        retrieved_on=date(2026, 1, 1),
        file_name="t",
        sha256="a" * 64,
        rows=[
            ObservationRow("TEST-D", "XA", 2020, Decimal("10"), "reported"),
            ObservationRow("TEST-D", "XA", 2022, Decimal("15"), "reported"),
        ],
    )
    indicator_services.import_release(
        actor=researcher,
        source=reference,
        label="TEST",
        retrieved_on=date(2026, 1, 1),
        file_name="t",
        sha256="b" * 64,
        rows=[ObservationRow("TEST-R", "OA", 2020, Decimal("1"), "reported")],
    )
    return ids


def _run(
    actor: AuthenticationContext,
    ids: list[uuid.UUID],
    data_class: str = "demonstration",
    **changes: Any,
) -> uuid.UUID:
    values: dict[str, Any] = {
        "title": "TEST run",
        "data_class": data_class,
        "indicators": ids,
        "start_year": 2020,
        "end_year": 2022,
    }
    values.update(changes)
    return services.run_analysis(actor=actor, **values)


def test_a_run_records_inputs_result_fingerprints_and_its_audit_event(
    researcher: AuthenticationContext, indicators: dict[str, uuid.UUID]
) -> None:
    public_id = _run(researcher, [indicators["demo"]])

    run = AnalysisRun.objects.get(public_id=public_id)
    assert run.method == "descriptive_change" and run.method_version == 1
    assert [item["year"] for item in run.inputs] == [2020, 2022]
    (row,) = run.result
    assert (row["start_value"], row["end_value"], row["years_missing"]) == ("10", "15", 1)
    assert len(run.input_fingerprint) == 64 and len(run.result_fingerprint) == 64
    assert audit_events("research.analysis_run") == [("created", public_id)]


def test_a_run_never_mixes_the_data_classes(
    researcher: AuthenticationContext, indicators: dict[str, uuid.UUID]
) -> None:
    public_id = _run(researcher, [indicators["demo"], indicators["reference"]])

    run = AnalysisRun.objects.get(public_id=public_id)
    assert {item["indicator"] for item in run.inputs} == {"TEST-D"}
    with pytest.raises(RecordNotFoundError):
        _run(researcher, [indicators["reference"]], "demonstration")


@pytest.mark.parametrize(
    "changes",
    [
        {"title": ""},
        {"start_year": 2022, "end_year": 2020},
        {"indicators": []},
        {"data_class": "real"},
    ],
)
def test_an_unacceptable_run_is_refused(
    researcher: AuthenticationContext, indicators: dict[str, uuid.UUID], changes: dict[str, Any]
) -> None:
    with pytest.raises(InvalidEntryError):
        _run(researcher, [indicators["demo"]], **changes)
    assert not AnalysisRun.objects.exists()


def test_a_reader_may_not_run_an_analysis(
    reader: AuthenticationContext, indicators: dict[str, uuid.UUID]
) -> None:
    with pytest.raises(PermissionDenied):
        _run(reader, [indicators["demo"]])


def test_a_run_reproduces_exactly_until_a_later_release_arrives(
    researcher: AuthenticationContext,
    reader: AuthenticationContext,
    indicators: dict[str, uuid.UUID],
) -> None:
    public_id = _run(researcher, [indicators["demo"]])
    entry = selectors.analysis(reader, public_id)
    assert entry is not None

    same = selectors.reproduce(reader, entry)
    indicator_services.import_release(
        actor=researcher,
        source=indicators["demo_source"],
        label="TEST 2",
        retrieved_on=date(2026, 2, 1),
        file_name="t2",
        sha256="c" * 64,
        rows=[ObservationRow("TEST-D", "XA", 2022, Decimal("16"), "provisional")],
    )
    changed = selectors.reproduce(reader, entry)

    assert same.same_inputs and same.same_result
    assert not changed.same_inputs and not changed.same_result
    assert (
        AnalysisRun.objects.get(public_id=public_id).result_fingerprint == entry.result_fingerprint
    )


def _search(actor: AuthenticationContext, **changes: Any) -> uuid.UUID:
    values: dict[str, Any] = {
        "data_class": "demonstration",
        "title": "TEST search",
        "layer": "core",
        "countries": "XA",
        "searched_on": date(2026, 1, 1),
        "queries": "TEST query",
        "source_universe": "TEST portal",
        "inclusion_criteria": "TEST rule",
        "sources_examined": "TEST item",
        "method": "TEST method",
        "outcome": "no_qualifying_source_found",
        "summary": "TEST summary",
    }
    values.update(changes)
    return services.record_search(actor=actor, **values)


def test_a_search_is_recorded_with_its_bounded_outcome(
    researcher: AuthenticationContext, world: World
) -> None:
    public_id = _search(researcher)

    assert SearchRun.objects.get(public_id=public_id).outcome == "no_qualifying_source_found"
    assert audit_events("research.search_run") == [("created", public_id)]


@pytest.mark.parametrize(
    "changes",
    [
        {"outcome": "nothing exists"},
        {"layer": "everything"},
        {"sources_examined": ""},
        {"method": " "},
        {"summary": ""},
    ],
)
def test_an_incomplete_search_is_refused(
    researcher: AuthenticationContext, world: World, changes: dict[str, Any]
) -> None:
    with pytest.raises(InvalidEntryError):
        _search(researcher, **changes)
    assert not SearchRun.objects.exists()


def test_a_reader_may_not_record_a_search(reader: AuthenticationContext, world: World) -> None:
    with pytest.raises(PermissionDenied):
        _search(reader)


def test_runs_and_searches_are_never_changed_or_deleted(
    researcher: AuthenticationContext, indicators: dict[str, uuid.UUID]
) -> None:
    _run(researcher, [indicators["demo"]])
    _search(researcher)

    for statement in (
        "UPDATE research_analysisrun SET title = 'x'",
        "DELETE FROM research_analysisrun",
        "UPDATE research_searchrun SET outcome = 'qualifying_sources_found'",
        "DELETE FROM research_searchrun",
    ):
        with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(statement)
