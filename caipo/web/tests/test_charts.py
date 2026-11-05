"""The geometry of the server-rendered line charts."""

import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from caipo.indicators.selectors import IndicatorView, Point, Series
from caipo.policies.selectors import TimelineEvent
from caipo.web.charts import event_axis, format_value, line_chart

INCLUDES = Path(__file__).resolve().parents[1] / "templates" / "web" / "includes"


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


def test_chart_points_are_not_tab_stops() -> None:
    """A chart is one image to assistive technology; its values are in the table beside it."""
    for name in ("line_chart.html", "event_axis.html"):
        template = (INCLUDES / name).read_text()

        assert "tabindex" not in template, name
        assert 'role="img"' in template, name


# --- Formal policy events on the same years (FR-42) ------------------------------------------


def _event(alpha2: str, on: date, event_type: str = "adopted") -> TimelineEvent:
    return TimelineEvent(
        alpha2, f"TEST {alpha2}", on, event_type, uuid.uuid4(), f"TEST Policy of {alpha2}"
    )


def test_an_event_sits_at_the_x_of_its_year_in_the_chart() -> None:
    view = _view(_series("XA", ["1", "2", "3", "4"]))

    axis = event_axis(view, [_event("XA", date(2022, 7, 1))])

    (mark,) = axis.rows[0].marks
    point_2022 = line_chart(view).series[0].points[2]
    assert mark.x == point_2022.x
    assert (axis.left, axis.right, axis.width) == (48, line_chart(view).right, 640)
    assert [tick.position for tick in axis.x_ticks] == [
        tick.position for tick in line_chart(view).x_ticks
    ]


def test_events_of_one_country_in_one_year_are_one_mark_that_names_each() -> None:
    view = _view(_series("XA", ["1", "2", "3"]))

    axis = event_axis(
        view,
        [_event("XA", date(2021, 3, 1)), _event("XA", date(2021, 6, 1), "entered_into_force")],
    )

    (mark,) = axis.rows[0].marks
    assert mark.count == 2
    assert "Adopted, 2021-03-01" in mark.label
    assert "Entered into force, 2021-06-01" in mark.label
    assert mark.label.startswith("TEST XA, 2021: ")
    assert axis.charted == 2


def test_an_event_outside_the_years_charted_is_counted_and_not_drawn() -> None:
    view = _view(_series("XA", ["1", "2", "3"]))

    axis = event_axis(view, [_event("XA", date(2019, 12, 31)), _event("XA", date(2023, 1, 1))])

    assert axis.rows[0].marks == ()
    assert (axis.charted, axis.outside) == (0, 2)


def test_every_country_of_the_chart_has_a_row_in_its_order_and_colour() -> None:
    view = _view(_series("XA", ["1", "2"]), _series("XB", ["3", "4"]))

    axis = event_axis(view, [_event("XB", date(2020, 1, 1))])

    assert [(row.index, row.alpha2) for row in axis.rows] == [(1, "XA"), (2, "XB")]
    assert [s.index for s in line_chart(view).series] == [1, 2]
    assert axis.rows[0].marks == ()
    assert len(axis.rows[1].marks) == 1
    assert axis.rows[0].y < axis.rows[1].y < axis.height


def test_the_event_panel_draws_no_line_or_shape_that_could_join_an_event_to_a_value() -> None:
    """FR-42 (a): marks and row guides only; no path, no polyline, no area."""
    template = (INCLUDES / "event_axis.html").read_text()

    for element in ("<path", "<polyline", "<polygon", "<circle", "<area"):
        assert element not in template, element
