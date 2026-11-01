"""The economic transformation pages (ADR-0020)."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.test import Client

from caipo.accounts.selectors import Role
from caipo.accounts.tests.fixtures import UserFactory
from caipo.indicators import services
from caipo.indicators.services import ObservationRow
from caipo.registry.tests.helpers import ActingAs
from caipo.sources.tests.helpers import World, make_source, make_world
from caipo.web.tests.helpers import signed_in, verified

pytestmark = pytest.mark.django_db


def _text(response: Any) -> str:
    return str(response.content.decode())


@pytest.fixture
def records(acting_as: ActingAs) -> dict[str, Any]:
    world: World = make_world()
    actor = acting_as(Role.RESEARCHER)
    demo = make_source(actor, world)
    reference = make_source(actor, world, "reference")
    demo_indicator = services.create_indicator(
        actor=actor,
        source=demo,
        code="TEST-C",
        name="TEST AI start-ups",
        unit="per million",
        layer="C",
        layer_reason="TEST reason",
    )
    services.create_indicator(
        actor=actor,
        source=reference,
        code="TEST-A",
        name="TEST Agriculture share",
        unit="% of GDP",
        layer="A",
        layer_reason="TEST reason",
    )
    services.import_release(
        actor=actor,
        source=demo,
        label="TEST",
        retrieved_on=date(2026, 1, 1),
        file_name="t",
        sha256="a" * 64,
        rows=[
            ObservationRow("TEST-C", "XA", 2020, Decimal("1.5"), "reported"),
            ObservationRow("TEST-C", "XA", 2021, None, "missing"),
            ObservationRow("TEST-C", "XA", 2022, Decimal("2.25"), "estimated"),
        ],
    )
    services.import_release(
        actor=actor,
        source=reference,
        label="TEST",
        retrieved_on=date(2026, 1, 1),
        file_name="t",
        sha256="b" * 64,
        rows=[ObservationRow("TEST-A", "OA", 2020, Decimal("12.3456"), "reported")],
    )
    return {"demo_indicator": demo_indicator}


@pytest.fixture
def reader(user_with_roles: UserFactory) -> Client:
    return signed_in(Client(), user_with_roles(Role.READER))


def test_the_page_needs_workspace_access(client: Client, user_with_roles: UserFactory) -> None:
    assert client.get("/indicators/").status_code in (302, 403)
    assert (
        verified(Client(), user_with_roles(Role.ADMINISTRATOR)).get("/indicators/").status_code
        == 403
    )


def test_reference_and_demonstration_countries_never_share_a_page(
    reader: Client, records: dict[str, Any]
) -> None:
    reference = _text(reader.get("/indicators/?layer=A"))
    demo = _text(reader.get("/indicators/?class=demonstration&layer=C"))

    assert "TEST Agriculture share" in reference and "TEST Synthetic Country" not in reference
    assert "TEST AI start-ups" in demo and "TEST Reference Country" not in demo
    assert "Demonstration data is shown." in demo
    assert "Demonstration data is shown." not in reference


def test_the_page_says_it_is_not_a_causal_analysis(reader: Client, records: dict[str, Any]) -> None:
    page = _text(reader.get("/indicators/"))

    assert "Not a causal analysis." in page
    assert "never combined into an index" in page


def test_a_layer_without_an_indicator_is_reported_not_dropped(
    reader: Client, records: dict[str, Any]
) -> None:
    page = _text(reader.get("/indicators/?class=reference&layer=C"))

    assert "No indicator recorded" in page
    assert "No indicator is recorded for C. AI-specific outcomes" in page
    assert "not that no reliable, comparable measure exists" in page


def test_gaps_and_flags_are_visible_and_values_rounded_only_for_display(
    reader: Client, records: dict[str, Any]
) -> None:
    page = _text(reader.get("/indicators/?class=demonstration&layer=C"))

    assert "2 of 3 years" in page
    assert "no value" in page
    assert 'class="is-flagged"' in page
    assert "2.25" in page
    assert "TEST AI start-ups (per million)" in page


def test_the_indicator_page_shows_provenance_and_the_release_hash(
    reader: Client, records: dict[str, Any]
) -> None:
    page = _text(reader.get(f"/indicators/{records['demo_indicator']}/"))

    assert "a" * 64 in page
    assert "TEST reason" in page
    assert "Provisional" in page
    assert reader.get("/indicators/00000000-0000-4000-8000-00000000ffff/").status_code == 404


def test_unknown_parameters_fall_back_rather_than_fail(
    reader: Client, records: dict[str, Any]
) -> None:
    response = reader.get("/indicators/?class=<x>&layer=Z")

    assert response.status_code == 200
    assert "TEST Agriculture share" in _text(response)
