"""The research workspace pages and exports (ADR-0020)."""

import csv
import io
import json
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.test import Client

from caipo.accounts.selectors import Role
from caipo.accounts.tests.fixtures import UserFactory
from caipo.indicators import services as indicator_services
from caipo.indicators.services import ObservationRow
from caipo.registry.tests.helpers import ActingAs
from caipo.research import services
from caipo.research.models import AnalysisRun, SearchRun
from caipo.sources.tests.helpers import make_source, make_world
from caipo.web.exports import safe_cell
from caipo.web.tests.helpers import signed_in, verified

pytestmark = pytest.mark.django_db


def _text(response: Any) -> str:
    return str(response.content.decode())


@pytest.fixture
def records(acting_as: ActingAs) -> dict[str, Any]:
    world = make_world()
    actor = acting_as(Role.RESEARCHER)
    source = make_source(actor, world)
    indicator = indicator_services.create_indicator(
        actor=actor,
        source=source,
        code="TEST-1",
        name='=HYPERLINK("x") TEST',
        unit="%",
        layer="C",
        layer_reason="TEST",
    )
    indicator_services.import_release(
        actor=actor,
        source=source,
        label="TEST release",
        retrieved_on=date(2026, 1, 1),
        file_name="t",
        sha256="d" * 64,
        rows=[
            ObservationRow("TEST-1", "XA", 2020, Decimal("1"), "reported"),
            ObservationRow("TEST-1", "XA", 2021, Decimal("3"), "estimated"),
        ],
    )
    run = services.run_analysis(
        actor=actor,
        title="TEST run",
        data_class="demonstration",
        indicators=[indicator],
        start_year=2020,
        end_year=2021,
    )
    return {"indicator": indicator, "run": run}


@pytest.fixture
def reader(user_with_roles: UserFactory) -> Client:
    return signed_in(Client(), user_with_roles(Role.READER))


@pytest.fixture
def researcher(user_with_roles: UserFactory) -> Client:
    return signed_in(Client(), user_with_roles(Role.RESEARCHER))


@pytest.mark.parametrize("url", ["/analysis/", "/searches/", "/policies/export.csv"])
def test_the_pages_need_workspace_access(
    client: Client, user_with_roles: UserFactory, url: str
) -> None:
    assert client.get(url).status_code in (302, 403)
    assert verified(Client(), user_with_roles(Role.ADMINISTRATOR)).get(url).status_code == 403


def test_a_reader_reads_runs_but_cannot_run_one(reader: Client, records: dict[str, Any]) -> None:
    page = _text(reader.get("/analysis/"))

    assert "TEST run" in page
    assert "Run and record" not in page
    response = reader.post("/analysis/", {"title": "x", "data_class": "demonstration"})
    assert response.status_code == 403
    assert AnalysisRun.objects.count() == 1


def test_a_researcher_runs_an_analysis_through_the_form(
    researcher: Client, records: dict[str, Any]
) -> None:
    response = researcher.post(
        "/analysis/",
        {
            "title": "TEST form run",
            "data_class": "demonstration",
            "indicators": [str(records["indicator"])],
            "start_year": "2020",
            "end_year": "2021",
        },
    )

    run = AnalysisRun.objects.get(title="TEST form run")
    assert response["Location"] == f"/analysis/{run.public_id}/"


def test_the_run_page_states_the_notice_and_checks_reproducibility(
    reader: Client, records: dict[str, Any]
) -> None:
    page = _text(reader.get(f"/analysis/{records['run']}/"))
    checked = _text(reader.get(f"/analysis/{records['run']}/?check=1"))

    assert "Not a causal analysis." in page
    assert "Demonstration data is shown." in page
    assert "Check reproducibility" in page
    assert "Reproduced exactly." in checked
    assert reader.get(f"/analysis/{uuid.UUID(int=1)}/").status_code == 404


def test_the_csv_export_carries_provenance_and_cannot_run_formulas(
    reader: Client, records: dict[str, Any]
) -> None:
    response = reader.get(f"/analysis/{records['run']}/export.csv")

    assert response["Content-Disposition"].startswith("attachment;")
    assert response["Content-Type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(_text(response))))
    notes = [row[0] for row in rows if row and row[0].startswith("#")]
    assert any("Data class: demonstration (synthetic" in note for note in notes)
    assert any("It does not show that any policy caused any change" in note for note in notes)
    assert any("d" * 64 in note for note in notes)
    header = rows[len(notes)]
    data = rows[len(notes) + 1]
    assert header[0] == "data_class" and data[0] == "demonstration"
    assert data[header.index("indicator_name")].startswith("'=")


def test_the_json_export_holds_inputs_result_and_fingerprints(
    reader: Client, records: dict[str, Any]
) -> None:
    document = json.loads(_text(reader.get(f"/analysis/{records['run']}/export.json")))

    assert document["data_class"] == "demonstration"
    assert len(document["input_fingerprint"]) == 64
    assert [item["year"] for item in document["inputs"]] == [2020, 2021]
    assert "non_causation_notice" in document


@pytest.mark.parametrize("value", ["=1+1", "+1", "-1", "@SUM(A1)", "\tx"])
def test_a_cell_that_looks_like_a_formula_is_neutralised(value: str) -> None:
    assert safe_cell(value) == "'" + value


def test_a_researcher_records_a_search_and_its_negative_finding_is_bounded(
    researcher: Client, records: dict[str, Any]
) -> None:
    response = researcher.post(
        "/searches/",
        {
            "data_class": "demonstration",
            "title": "TEST search",
            "layer": "core",
            "countries": "XA",
            "searched_on": "2026-01-02",
            "queries": "TEST",
            "source_universe": "TEST",
            "inclusion_criteria": "TEST",
            "sources_examined": "TEST",
            "method": "TEST",
            "outcome": "no_qualifying_source_found",
            "summary": "TEST",
        },
    )

    search = SearchRun.objects.get()
    assert response["Location"] == f"/searches/{search.public_id}/"
    page = _text(researcher.get(response["Location"]))
    assert "A bounded negative finding." in page
    assert "not evidence that no such source exists" in page


def test_the_policy_register_exports_both_corpora_apart(
    reader: Client, records: dict[str, Any]
) -> None:
    response = reader.get("/policies/export.csv")

    text = _text(response)
    assert response["Content-Disposition"] == 'attachment; filename="caipo-policy-register.csv"'
    assert "contextual material is never counted as AI policy" in text
    assert "data_class,corpus,assignment" in text
