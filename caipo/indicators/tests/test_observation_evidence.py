"""The structured query of reference observations for the assistant (AI_ARCHITECTURE.md §4.2)."""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from caipo.accounts.selectors import AuthenticationContext
from caipo.indicators import selectors, services
from caipo.indicators.models import Indicator
from caipo.indicators.services import ObservationRow
from caipo.registry.models import Country
from caipo.sources.tests.helpers import World, make_source

pytestmark = [pytest.mark.services, pytest.mark.django_db]


def _release(
    actor: AuthenticationContext, source: uuid.UUID, sha: str, rows: list[ObservationRow]
) -> None:
    services.import_release(
        actor=actor,
        source=source,
        label=f"TEST release {sha[0]}",
        retrieved_on=date(2026, 1, 2),
        file_name="TEST.csv",
        sha256=sha * 64,
        rows=rows,
    )


@pytest.fixture
def reference(researcher: AuthenticationContext, world: World) -> uuid.UUID:
    Country.objects.create(alpha2="OB", alpha3="OBB", name_en="TEST Reference Country B")
    source = make_source(researcher, world, "reference")
    for code, name in (
        ("TEST-NET", "TEST Internet users"),
        ("TEST-GDP", "TEST Gross domestic product"),
    ):
        services.create_indicator(
            actor=researcher,
            source=source,
            code=code,
            name=name,
            unit="TEST unit",
            layer="B",
            layer_reason="TEST reason",
        )
    _release(
        researcher,
        source,
        "a",
        [
            ObservationRow("TEST-NET", "OA", year, Decimal(year - 1990), "reported")
            for year in range(2010, 2025)
        ]
        + [ObservationRow("TEST-NET", "OB", 2024, None, "missing")]
        + [ObservationRow("TEST-GDP", "OA", 2024, Decimal("5"), "reported")],
    )
    _release(
        researcher,
        source,
        "b",
        [ObservationRow("TEST-NET", "OA", 2024, Decimal("99.5"), "estimated")],
    )
    return source


def _evidence(
    query: str,
    *,
    countries: list[str] | None = None,
    years: tuple[int, int] | None = None,
    indicators: int = 2,
    limit: int = 50,
) -> tuple[selectors.ObservationEvidence, ...]:
    return selectors.observation_evidence(
        query,
        countries=countries or [],
        years=years,
        indicators=indicators,
        recent_years=3,
        limit=limit,
    )


@pytest.mark.usefixtures("reference")
def test_any_word_of_the_question_chooses_an_indicator() -> None:
    question = "How many people were internet users in TEST Reference Country A in 2019?"

    # Every synthetic name holds "TEST", as the question does; the indicator
    # that matches more of its words ranks first.
    found = _evidence(question, indicators=1)
    assert {item.code for item in found} == {"TEST-NET"}
    assert {item.indicator_public_id for item in found} == {
        Indicator.objects.get(code="TEST-NET").public_id
    }


@pytest.mark.usefixtures("reference")
@pytest.mark.parametrize("query", ["zzqx wvvp", "", "2019 2020", "!!! ((( ::: &&& |||", "_ __"])
def test_a_question_that_names_no_indicator_finds_nothing(query: str) -> None:
    assert _evidence(query) == ()


@pytest.mark.usefixtures("reference")
def test_the_most_recent_years_of_every_country_are_taken_when_none_is_named() -> None:
    found = _evidence("internet users")

    assert sorted({item.year for item in found}) == [2022, 2023, 2024]
    gap = next(item for item in found if item.alpha2 == "OB")
    assert (gap.year, gap.value, gap.status) == (2024, None, "missing")


@pytest.mark.usefixtures("reference")
def test_named_countries_and_years_narrow_the_rows() -> None:
    found = _evidence("internet users", countries=["test reference country"], years=(2012, 2013))

    assert [(item.alpha2, item.year, item.value) for item in found] == [
        ("OA", 2012, Decimal("22.000000000000000000")),
        ("OA", 2013, Decimal("23.000000000000000000")),
    ]


@pytest.mark.usefixtures("reference")
def test_the_value_of_the_latest_release_is_taken() -> None:
    (latest,) = _evidence(
        "internet users", countries=["TEST Reference Country"], years=(2024, 2024)
    )

    assert (latest.value, latest.status, latest.release) == (
        Decimal("99.500000000000000000"),
        "estimated",
        "TEST release b",
    )


@pytest.mark.usefixtures("reference")
def test_the_numbers_of_indicators_and_rows_are_bounded() -> None:
    assert {
        item.code for item in _evidence("internet users gross domestic product", indicators=1)
    } in (
        {"TEST-NET"},
        {"TEST-GDP"},
    )
    assert len(_evidence("internet users", limit=2)) == 2


def test_demonstration_indicators_are_never_taken(
    researcher: AuthenticationContext, world: World
) -> None:
    source = make_source(researcher, world)
    services.create_indicator(
        actor=researcher,
        source=source,
        code="TEST-DEMO",
        name="TEST Internet users",
        unit="TEST unit",
        layer="B",
        layer_reason="TEST reason",
    )
    _release(
        researcher, source, "c", [ObservationRow("TEST-DEMO", "XA", 2024, Decimal("1"), "reported")]
    )

    assert _evidence("internet users") == ()
    assert selectors.reference_countries() == []
