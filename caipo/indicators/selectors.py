"""Read interface of the demonstrator's indicators (ADR-0020).

Every function requires `WORKSPACE_READ`.

Where a provider has published a value more than once, the value of the
latest release is the one read; earlier releases stay on record. Countries
are shown with every year in range, so a year without a value is visible as
a gap, never filled.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import Count

from caipo.accounts import selectors as accounts_selectors
from caipo.accounts.selectors import AuthenticationContext, Permission
from caipo.indicators.models import (
    DatasetRelease,
    Indicator,
    Layer,
    Observation,
    ObservationStatus,
)

__all__ = [
    "CountryCoverage",
    "IndicatorDetail",
    "IndicatorView",
    "Layer",
    "LayerCoverage",
    "ObservationStatus",
    "Point",
    "ReleaseEntry",
    "Series",
    "coverage",
    "indicator_detail",
    "layer_view",
]


@dataclass(frozen=True)
class Point:
    year: int
    value: Decimal | None
    status: str
    footnote: str

    @property
    def is_missing(self) -> bool:
        return self.value is None

    @property
    def is_flagged(self) -> bool:
        return self.status not in (ObservationStatus.REPORTED, ObservationStatus.MISSING)

    @property
    def status_label(self) -> str:
        return str(ObservationStatus(self.status).label)


@dataclass(frozen=True)
class Series:
    """One indicator for one country: a point for every year in range, held or not."""

    alpha2: str
    country: str
    points: tuple[Point, ...]

    @property
    def held(self) -> int:
        return sum(1 for point in self.points if not point.is_missing)

    @property
    def latest(self) -> Point | None:
        held = [point for point in self.points if not point.is_missing]
        return held[-1] if held else None


@dataclass(frozen=True)
class IndicatorView:
    public_id: uuid.UUID
    data_class: str
    code: str
    name: str
    unit: str
    layer: str
    layer_reason: str
    source_name: str
    source_public_id: uuid.UUID
    years: tuple[int, ...]
    series: tuple[Series, ...]

    @property
    def layer_label(self) -> str:
        return str(Layer(self.layer).label)


@dataclass(frozen=True)
class ReleaseEntry:
    label: str
    retrieved_on: date
    file_name: str
    sha256: str
    observations: int


@dataclass(frozen=True)
class IndicatorDetail:
    view: IndicatorView
    definition: str
    original_provider: str
    source_url: str
    source_licence: str
    source_licence_verified: bool
    releases: tuple[ReleaseEntry, ...]


@dataclass(frozen=True)
class CountryCoverage:
    alpha2: str
    country: str
    with_values: int
    latest_year: int | None


@dataclass(frozen=True)
class LayerCoverage:
    layer: str
    indicators: int
    countries: tuple[CountryCoverage, ...]

    @property
    def label(self) -> str:
        return str(Layer(self.layer).label)


def _countries(data_class: str) -> list[tuple[int, str, str]]:
    """The countries that any indicator of this data class has a value or a gap for."""
    return list(
        Observation.objects.filter(indicator__data_class=data_class)
        .values_list("country_id", "country__alpha2", "country__name_en")
        .distinct()
        .order_by("country__name_en")
    )


def _latest(
    indicator_ids: list[int],
) -> dict[tuple[int, int, int], tuple[Decimal | None, str, str]]:
    """(indicator, country, year) to (value, status, footnote) of the latest release."""
    latest: dict[tuple[int, int, int], tuple[Decimal | None, str, str]] = {}
    for indicator_id, country_id, year, value, status, footnote in (
        Observation.objects.filter(indicator_id__in=indicator_ids)
        .order_by("release_id")
        .values_list("indicator_id", "country_id", "year", "value", "status", "footnote")
    ):
        latest[(indicator_id, country_id, year)] = (value, status, footnote)
    return latest


def _views(data_class: str, **filters: object) -> list[IndicatorView]:
    rows = list(
        Indicator.objects.filter(data_class=data_class, **filters)
        .order_by("layer", "name", "id")
        .values_list(
            "pk",
            "public_id",
            "data_class",
            "code",
            "name",
            "unit",
            "layer",
            "layer_reason",
            "source__name",
            "source__public_id",
        )
    )
    latest = _latest([row[0] for row in rows])
    countries = _countries(data_class)
    years_of: dict[int, set[int]] = defaultdict(set)
    for indicator_id, _country, year in latest:
        years_of[indicator_id].add(year)
    views = []
    for pk, public_id, klass, code, name, unit, layer, reason, source_name, source_id in rows:
        years = tuple(range(min(years_of[pk]), max(years_of[pk]) + 1)) if years_of[pk] else ()
        series = tuple(
            Series(
                alpha2=alpha2,
                country=country_name,
                points=tuple(
                    Point(
                        year,
                        *latest.get((pk, country_id, year), (None, ObservationStatus.MISSING, "")),
                    )
                    for year in years
                ),
            )
            for country_id, alpha2, country_name in countries
        )
        views.append(
            IndicatorView(
                public_id,
                klass,
                code,
                name,
                unit,
                layer,
                reason,
                source_name,
                source_id,
                years,
                series,
            )
        )
    return views


def layer_view(
    context: AuthenticationContext | None, *, layer: str, data_class: str
) -> list[IndicatorView]:
    """Return every indicator of one layer and one data class, with a series for each country.

    Reads only. Raises PermissionDenied if the context may not read the workspace.
    """
    accounts_selectors.require_permission(context, Permission.WORKSPACE_READ)
    return _views(data_class, layer=layer)


def coverage(context: AuthenticationContext | None, *, data_class: str) -> list[LayerCoverage]:
    """Return, for each layer, how many indicators exist and how many have values for each country.

    Every layer is returned, including one with no indicator, so that a gap
    in the evidence is shown and not dropped. Reads only. Raises
    PermissionDenied if the context may not read the workspace.
    """
    accounts_selectors.require_permission(context, Permission.WORKSPACE_READ)
    views = _views(data_class)
    countries = [(alpha2, name) for _, alpha2, name in _countries(data_class)]
    result = []
    for layer in Layer.values:
        in_layer = [view for view in views if view.layer == layer]
        per_country = []
        for alpha2, name in countries:
            held = [
                series
                for view in in_layer
                for series in view.series
                if series.alpha2 == alpha2 and series.held
            ]
            latest_years = [series.latest.year for series in held if series.latest is not None]
            per_country.append(
                CountryCoverage(
                    alpha2, name, len(held), max(latest_years) if latest_years else None
                )
            )
        result.append(LayerCoverage(layer, len(in_layer), tuple(per_country)))
    return result


def indicator_detail(
    context: AuthenticationContext | None, public_id: uuid.UUID
) -> IndicatorDetail | None:
    """Return an indicator with its provenance, releases, and series, or None if there is none.

    Reads only. Raises PermissionDenied if the context may not read the workspace.
    """
    accounts_selectors.require_permission(context, Permission.WORKSPACE_READ)
    row = (
        Indicator.objects.filter(public_id=public_id)
        .values_list(
            "data_class",
            "definition",
            "original_provider",
            "source__url",
            "source__licence",
            "source__licence_verified",
        )
        .first()
    )
    if row is None:
        return None
    data_class, definition, original, url, licence, verified = row
    (view,) = _views(data_class, public_id=public_id)
    releases = tuple(
        ReleaseEntry(*release)
        for release in DatasetRelease.objects.filter(observations__indicator__public_id=public_id)
        .annotate(held=Count("observations"))
        .order_by("created_at")
        .values_list("label", "retrieved_on", "file_name", "sha256", "held")
    )
    return IndicatorDetail(view, definition, original, url, licence, verified, releases)
