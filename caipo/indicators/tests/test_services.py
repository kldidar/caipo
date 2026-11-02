"""The services and selectors of the demonstrator's indicators (ADR-0020)."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection, transaction

from caipo.accounts.selectors import AuthenticationContext
from caipo.core.append_only import AppendOnlyError
from caipo.core.entry import DataClassError, InvalidEntryError, RecordNotFoundError
from caipo.indicators import selectors, services
from caipo.indicators.models import DatasetRelease, Indicator, Observation
from caipo.indicators.services import DuplicateReleaseError, ObservationRow
from caipo.registry.models import Country
from caipo.sources.tests.helpers import World, audit_events, make_source

pytestmark = pytest.mark.django_db

HASH_1 = "1" * 64
HASH_2 = "2" * 64


def _indicator(
    actor: AuthenticationContext, source: uuid.UUID, code: str = "TEST-1", layer: str = "B"
) -> uuid.UUID:
    return services.create_indicator(
        actor=actor,
        source=source,
        code=code,
        name=f"TEST indicator {code}",
        unit="%",
        layer=layer,
        layer_reason="TEST reason",
    )


def _import(
    actor: AuthenticationContext,
    source: uuid.UUID,
    rows: list[ObservationRow],
    sha256: str = HASH_1,
) -> uuid.UUID:
    return services.import_release(
        actor=actor,
        source=source,
        label="TEST release",
        retrieved_on=date(2026, 1, 2),
        file_name="TEST.json",
        sha256=sha256,
        rows=rows,
    )


def _row(
    year: int,
    value: str | None,
    status: str = "reported",
    code: str = "TEST-1",
    country: str = "XA",
) -> ObservationRow:
    return ObservationRow(
        code, country, year, Decimal(value) if value is not None else None, status
    )


@pytest.fixture
def source(researcher: AuthenticationContext, world: World) -> uuid.UUID:
    return make_source(researcher, world)


# --- Indicators ----------------------------------------------------------------------------------


def test_an_indicator_takes_its_providers_data_class_and_is_audited(
    researcher: AuthenticationContext, world: World
) -> None:
    reference = make_source(researcher, world, "reference")

    public_id = _indicator(researcher, reference)

    assert Indicator.objects.get(public_id=public_id).data_class == "reference"
    assert audit_events("indicators.indicator") == [("created", public_id)]


@pytest.mark.parametrize(
    "changes", [{"layer": "D"}, {"unit": ""}, {"layer_reason": " "}, {"code": ""}]
)
def test_an_incomplete_indicator_is_refused(
    researcher: AuthenticationContext, source: uuid.UUID, changes: dict[str, Any]
) -> None:
    values: dict[str, Any] = {
        "source": source,
        "code": "TEST-1",
        "name": "TEST",
        "unit": "%",
        "layer": "A",
        "layer_reason": "TEST",
    }
    values.update(changes)

    with pytest.raises(InvalidEntryError):
        services.create_indicator(actor=researcher, **values)


def test_a_code_is_used_once_per_provider(
    researcher: AuthenticationContext, source: uuid.UUID
) -> None:
    _indicator(researcher, source)

    with pytest.raises(InvalidEntryError):
        _indicator(researcher, source)


def test_a_reader_may_not_create_an_indicator(
    reader: AuthenticationContext, source: uuid.UUID
) -> None:
    with pytest.raises(PermissionDenied):
        _indicator(reader, source)


# --- Releases ------------------------------------------------------------------------------------


def test_a_release_is_imported_whole_with_values_exactly_as_given(
    researcher: AuthenticationContext, source: uuid.UUID
) -> None:
    _indicator(researcher, source)

    public_id = _import(
        researcher,
        source,
        [_row(2020, "22.2215537100341"), _row(2021, None, "missing"), _row(2022, "3", "estimated")],
    )

    stored = dict(Observation.objects.values_list("year", "value"))
    assert stored[2020] == Decimal("22.2215537100341")
    assert stored[2021] is None
    assert audit_events("indicators.dataset_release") == [("created", public_id)]
    assert DatasetRelease.objects.get().data_class == "demonstration"


@pytest.mark.parametrize(
    "row",
    [
        ObservationRow("TEST-1", "XA", 2020, None, "reported"),
        ObservationRow("TEST-1", "XA", 2020, Decimal("1"), "missing"),
        ObservationRow("TEST-1", "XA", 2020, Decimal("NaN"), "reported"),
        ObservationRow("TEST-1", "XA", 2020, Decimal("1e19"), "reported"),
        ObservationRow("TEST-1", "XA", 2020, Decimal("0.1234567890123456789"), "reported"),
        ObservationRow("TEST-1", "XA", 1800, Decimal("1"), "reported"),
        ObservationRow("TEST-1", "XA", 2020, Decimal("1"), "guessed"),
    ],
)
def test_a_release_with_one_bad_row_stores_nothing(
    researcher: AuthenticationContext, source: uuid.UUID, row: ObservationRow
) -> None:
    _indicator(researcher, source)

    with pytest.raises(InvalidEntryError):
        _import(researcher, source, [_row(2019, "1"), row])
    assert not DatasetRelease.objects.exists()
    assert not Observation.objects.exists()


def test_a_value_is_never_given_to_a_country_of_the_other_data_class(
    researcher: AuthenticationContext, source: uuid.UUID
) -> None:
    _indicator(researcher, source)

    with pytest.raises(DataClassError):
        _import(researcher, source, [_row(2020, "1", country="OA")])


@pytest.mark.parametrize(
    "row", [_row(2020, "1", code="TEST-unknown"), _row(2020, "1", country="XZ")]
)
def test_unknown_indicators_and_countries_are_refused(
    researcher: AuthenticationContext, source: uuid.UUID, row: ObservationRow
) -> None:
    _indicator(researcher, source)

    with pytest.raises(RecordNotFoundError):
        _import(researcher, source, [row])


def test_a_row_occurs_once_and_a_file_is_imported_once(
    researcher: AuthenticationContext, source: uuid.UUID
) -> None:
    _indicator(researcher, source)

    with pytest.raises(InvalidEntryError):
        _import(researcher, source, [_row(2020, "1"), _row(2020, "2")])
    _import(researcher, source, [_row(2020, "1")])
    with pytest.raises(DuplicateReleaseError):
        _import(researcher, source, [_row(2020, "1")])


def test_releases_and_observations_are_never_changed_or_deleted(
    researcher: AuthenticationContext, source: uuid.UUID
) -> None:
    _indicator(researcher, source)
    _import(researcher, source, [_row(2020, "1")])

    with pytest.raises(AppendOnlyError):
        Observation.objects.update(value=Decimal("2"))
    for statement in (
        "UPDATE indicators_observation SET value = 2",
        "DELETE FROM indicators_observation",
        "DELETE FROM indicators_datasetrelease",
        "DELETE FROM indicators_indicator",
    ):
        with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(statement)


def test_the_database_refuses_a_missing_value_that_holds_something(
    researcher: AuthenticationContext, source: uuid.UUID
) -> None:
    indicator = Indicator.objects.get(public_id=_indicator(researcher, source))
    release = DatasetRelease.objects.get(public_id=_import(researcher, source, []))

    with pytest.raises(IntegrityError), transaction.atomic():
        Observation.objects.create(
            indicator=indicator,
            country=Country.objects.get(alpha2="XA"),
            release=release,
            year=2020,
            value=Decimal("1"),
            status="missing",
        )


# --- Reading -------------------------------------------------------------------------------------


def test_gaps_stay_gaps_and_the_latest_release_wins(
    researcher: AuthenticationContext, reader: AuthenticationContext, source: uuid.UUID
) -> None:
    _indicator(researcher, source)
    _import(researcher, source, [_row(2020, "1"), _row(2022, "3")], HASH_1)
    _import(researcher, source, [_row(2022, "3.5", "provisional")], HASH_2)

    (view,) = selectors.layer_view(reader, layer="B", data_class="demonstration")

    (series,) = view.series
    assert view.years == (2020, 2021, 2022)
    assert [(p.year, p.value, p.status) for p in series.points] == [
        (2020, Decimal("1"), "reported"),
        (2021, None, "missing"),
        (2022, Decimal("3.5"), "provisional"),
    ]
    assert series.held == 2


def test_every_layer_is_reported_even_without_an_indicator(
    researcher: AuthenticationContext, reader: AuthenticationContext, source: uuid.UUID
) -> None:
    _indicator(researcher, source, layer="A")
    _import(researcher, source, [_row(2020, "1")])

    coverage = selectors.coverage(reader, data_class="demonstration")

    assert [(row.layer, row.indicators) for row in coverage] == [("A", 1), ("B", 0), ("C", 0)]
    assert coverage[0].countries[0].with_values == 1
    assert selectors.coverage(reader, data_class="reference")[2].countries == ()


def test_reference_and_demonstration_values_are_read_apart(
    researcher: AuthenticationContext,
    reader: AuthenticationContext,
    world: World,
    source: uuid.UUID,
) -> None:
    reference = make_source(researcher, world, "reference")
    _indicator(researcher, source)
    _indicator(researcher, reference, code="TEST-R")
    _import(researcher, source, [_row(2020, "1")])
    _import(researcher, reference, [_row(2020, "5", code="TEST-R", country="OA")], HASH_2)

    demo = selectors.layer_view(reader, layer="B", data_class="demonstration")
    real = selectors.layer_view(reader, layer="B", data_class="reference")

    assert [s.alpha2 for v in demo for s in v.series] == ["XA"]
    assert [s.alpha2 for v in real for s in v.series] == ["OA"]
