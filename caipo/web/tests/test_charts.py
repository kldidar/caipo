"""The geometry of the server-rendered line charts."""

import uuid
from decimal import Decimal

from caipo.indicators.selectors import IndicatorView, Point, Series
from caipo.web.charts import format_value, line_chart


def _view(*series: Series) -> IndicatorView:
    years = tuple(point.year for point in series[0].points)
    return IndicatorView(
        uuid.uuid4(),
        "demonstration",
        "TEST",
        "TEST indicator",
        "%",
        "A",
        "TEST",
        "TEST",
        uuid.uuid4(),
        years,
        series,
    )


def _series(alpha2: str, values: list[str | None]) -> Series:
    return Series(
        alpha2,
        f"TEST {alpha2}",
        tuple(
            Point(
                2020 + i,
                Decimal(v) if v is not None else None,
                "reported" if v is not None else "missing",
                "",
            )
            for i, v in enumerate(values)
        ),
    )


def test_a_gap_breaks_the_line() -> None:
    chart = line_chart(_view(_series("XA", ["1", "2", None, "4", "5"])))

    (series,) = chart.series
    assert len(series.paths) == 2
    assert len(series.points) == 4
    assert (series.held, series.total) == (4, 5)


def test_a_country_without_values_draws_nothing_but_is_listed() -> None:
    chart = line_chart(_view(_series("XA", ["1", "2"]), _series("XB", [None, None])))

    assert [s.index for s in chart.series] == [1, 2]
    assert chart.series[1].paths == ()
    assert chart.series[1].held == 0


def test_with_no_value_at_all_the_chart_is_empty() -> None:
    assert line_chart(_view(_series("XA", [None, None]))).empty


def test_end_labels_never_overlap() -> None:
    chart = line_chart(_view(_series("XA", ["1", "10"]), _series("XB", ["1", "10.01"])))

    first, second = (s.label_y for s in chart.series)
    assert abs(first - second) >= 14


def test_values_are_shown_rounded_and_never_changed() -> None:
    value = Decimal("22.2215537100341")

    assert format_value(value) == "22.22"
    assert format_value(Decimal("100")) == "100"
    assert format_value(Decimal("1234.5")) == "1,234.5"
    assert value == Decimal("22.2215537100341")
