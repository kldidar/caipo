"""The demonstration journeys, end to end through the pages, on the seeded environment.

Each journey signs in through the sign-in form with an account that
`seed_demo` created, and follows the links a person would follow. These are
the paths of the professor-facing demonstration (docs/DEMO.md).
"""

import csv
import io
import json
import re
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from django.test import Client, override_settings

from caipo.policies.models import Policy

pytestmark = pytest.mark.django_db

PASSWORD = "TEST-journey-password-2026"


def _text(response: Any) -> str:
    return str(response.content.decode())


@pytest.fixture
def seeded() -> None:
    with override_settings(DEBUG=True):
        call_command("seed_demo", "--password", PASSWORD, stdout=StringIO())


def _sign_in(email: str) -> Client:
    client = Client()
    response = client.post("/login/", {"email": email, "password": PASSWORD})
    assert response.status_code == 302, _text(response)
    return client


def _links(page: str, prefix: str) -> list[str]:
    return re.findall(rf'href="({re.escape(prefix)}[0-9a-f-]{{36}}/)"', page)


def test_a_reader_follows_the_evidence_from_policy_to_export(seeded: None) -> None:
    reader = _sign_in("demo.reader@caipo.test")

    overview = _text(reader.get("/"))
    assert "Core AI policies" in overview and "Economic transformation, study countries" in overview

    core = _text(reader.get("/policies/?class=reference"))
    assert "Strategy for the Development of Artificial Intelligence Technologies until 2030" in core
    (strategy,) = _links(core, "/policies/")
    page = _text(reader.get(strategy))
    assert "In force" in page
    assert "RP-358" in page and "https://lex.uz/ru/docs/7159258" in page
    assert "Provisional" in page and "not an eligibility decision" in page

    contextual = _text(reader.get("/policies/?corpus=contextual&class=reference"))
    assert "State Program for the Development of the Digital Economy" in contextual
    assert "No formal event recorded" in contextual

    layer_c = _text(reader.get("/indicators/?layer=C"))
    assert "No indicator recorded" in layer_c
    layer_b = _text(reader.get("/indicators/?layer=B"))
    assert "Individuals using the Internet" in layer_b
    assert "of 15 years" in layer_b

    runs = _text(reader.get("/analysis/"))
    run = next(
        link
        for link in _links(runs, "/analysis/")
        if "Structural change" in _text(reader.get(link))
    )
    checked = _text(reader.get(run + "?check=1"))
    assert "Reproduced exactly." in checked
    exported = _text(reader.get(run + "export.csv"))
    rows = list(csv.reader(io.StringIO(exported)))
    assert any("World Development Indicators" in row[0] for row in rows if row)
    assert any(row and row[0] == "reference" for row in rows)

    searches = _text(reader.get("/searches/"))
    assert "No qualifying source found" in searches


def test_a_researcher_records_a_policy_and_runs_an_analysis(seeded: None) -> None:
    researcher = _sign_in("demo.researcher@caipo.test")

    form = _text(researcher.get("/policies/new/"))
    country = re.search(r'<option value="([0-9a-f-]{36})">DEMO Northland \(XA\)</option>', form)
    language = re.search(r'<option value="([0-9a-f-]{36})">English \(eng-Latn\)</option>', form)
    assert country and language
    created = researcher.post(
        "/policies/new/",
        {
            "data_class": "demonstration",
            "country": country.group(1),
            "policy_type": "programme",
            "title": "DEMO Programme for AI Skills",
            "title_language": language.group(1),
            "corpus_assignment": "core",
            "ai_focus": "ai_focused",
            "assignment_reason": "DEMO journey: the programme's subject is AI skills.",
        },
    )
    assert created.status_code == 302
    page = _text(researcher.get(created["Location"]))
    assert "DEMO Programme for AI Skills" in page and "No formal event recorded." in page
    assert Policy.objects.filter(
        title="DEMO Programme for AI Skills", data_class="demonstration"
    ).exists()

    analysis_form = _text(researcher.get("/analysis/?class=demonstration"))
    indicators = re.findall(r'name="indicators" value="([0-9a-f-]{36})"', analysis_form)
    assert indicators
    ran = researcher.post(
        "/analysis/",
        {
            "title": "DEMO journey run",
            "data_class": "demonstration",
            "indicators": indicators,
            "start_year": "2019",
            "end_year": "2025",
        },
    )
    assert ran.status_code == 302
    document = json.loads(_text(researcher.get(ran["Location"] + "export.json")))
    assert document["data_class"] == "demonstration"
    assert {row["country"] for row in document["result"]} <= {"XA", "XB"}


def test_reference_and_demonstration_data_never_appear_as_one(seeded: None) -> None:
    reader = _sign_in("demo.reader@caipo.test")

    reference = _text(reader.get("/indicators/?class=reference&layer=A"))
    demonstration = _text(reader.get("/indicators/?class=demonstration&layer=A"))

    assert "Turkmenistan" in reference and "DEMO Northland" not in reference
    assert "DEMO Northland" in demonstration and "Turkmenistan" not in demonstration
    assert "Demonstration data is shown." in demonstration
    assert "Demonstration data is shown." not in reference
