"""Server-rendered line charts for indicator series (ADR-0020 point 15).

Geometry only: this module turns series into coordinates, and the template
draws them as SVG. A year without a value breaks the line, so a gap is seen
as a gap and never bridged. One y-axis per chart, with rounded ticks; the
scale is not forced to start at zero, which the axis labels make visible.
Each series keeps the colour of its country across every chart, because
series always come in the same order.

Formal policy events get a panel of their own above a chart, on the same
scale of years (FR-42). Nothing drawn there reaches into the chart, and
nothing in the chart refers to an event.
"""

import math
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from caipo.indicators.selectors import IndicatorView, Point
from caipo.policies.selectors import TimelineEvent

WIDTH = 640
HEIGHT = 260
LEFT = 48
RIGHT = 88
TOP = 16
BOTTOM = 32


@dataclass(frozen=True)
class ChartPoint:
    x: float
    y: float
    label: str
    flagged: bool


@dataclass(frozen=True)
class ChartSeries:
    index: int
    country: str
    alpha2: str
    paths: tuple[str, ...]
    points: tuple[ChartPoint, ...]
    end: ChartPoint | None
    label_y: float
    held: int
    total: int


@dataclass(frozen=True)
class Tick:
    position: float
    label: str


@dataclass(frozen=True)
class LineChart:
    width: int
    height: int
    left: int
    right: float
    top: int
    bottom: float
    series: tuple[ChartSeries, ...]
    x_ticks: tuple[Tick, ...]
    y_ticks: tuple[Tick, ...]
    empty: bool


def format_value(value: Decimal) -> str:
    """Show a value with at most two decimals. The stored value is never changed."""
    text = f"{value.quantize(Decimal('0.01')):,}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _nice_step(span: float, count: int = 4) -> float:
    raw = span / count if span > 0 else 1.0
    magnitude: float = 10.0 ** math.floor(math.log10(raw))
    for factor in (1, 2, 2.5, 5, 10):
        if raw <= factor * magnitude:
            return factor * magnitude
    return 10 * magnitude


def _bounds(values: list[float]) -> tuple[float, float, float]:
    low, high = min(values), max(values)
    if low == high:
        low, high = low - 1, high + 1
    step = _nice_step(high - low)
    return math.floor(low / step) * step, math.ceil(high / step) * step, step


def _label(point: Point, country: str, unit: str) -> str:
    if point.value is None:
        return f"{country}, {point.year}: no value"
    flag = "" if not point.is_flagged else f" ({point.status_label.lower()})"
    return f"{country}, {point.year}: {format_value(point.value)} {unit}{flag}"


def _x_scale(years: Sequence[int], right: float) -> Callable[[int], float]:
    first, last = years[0], years[-1]

    def x(year: int) -> float:
        return LEFT if first == last else LEFT + (year - first) / (last - first) * (right - LEFT)

    return x


def _x_ticks(years: Sequence[int], x: Callable[[int], float]) -> tuple[Tick, ...]:
    year_step = max(1, math.ceil(len(years) / 8))
    return tuple(Tick(round(x(year), 1), str(year)) for year in years[::year_step])


def line_chart(view: IndicatorView) -> LineChart:
    """Return the geometry of a line chart of every country's series of one indicator."""
    right = WIDTH - RIGHT
    bottom = HEIGHT - BOTTOM
    held = [
        float(point.value)
        for series in view.series
        for point in series.points
        if point.value is not None
    ]
    if not held or not view.years:
        return LineChart(WIDTH, HEIGHT, LEFT, right, TOP, bottom, (), (), (), True)
    low, high, step = _bounds(held)
    x = _x_scale(view.years, right)

    def y(value: float) -> float:
        return bottom - (value - low) / (high - low) * (bottom - TOP)

    chart_series = []
    for index, series in enumerate(view.series, start=1):
        paths: list[str] = []
        current: list[str] = []
        points = []
        for point in series.points:
            if point.value is None:
                if current:
                    paths.append(" ".join(current))
                current = []
                continue
            px, py = round(x(point.year), 1), round(y(float(point.value)), 1)
            current.append(f"{'M' if not current else 'L'}{px},{py}")
            points.append(
                ChartPoint(px, py, _label(point, series.country, view.unit), point.is_flagged)
            )
        if current:
            paths.append(" ".join(current))
        chart_series.append(
            ChartSeries(
                index=index,
                country=series.country,
                alpha2=series.alpha2,
                paths=tuple(paths),
                points=tuple(points),
                end=points[-1] if points else None,
                label_y=points[-1].y if points else 0.0,
                held=series.held,
                total=len(series.points),
            )
        )
    chart_series = _spread_labels(chart_series)
    x_ticks = _x_ticks(view.years, x)
    count = round((high - low) / step)
    y_ticks = tuple(
        Tick(round(y(low + i * step), 1), format_value(Decimal(str(round(low + i * step, 6)))))
        for i in range(count + 1)
    )
    return LineChart(
        WIDTH, HEIGHT, LEFT, right, TOP, bottom, tuple(chart_series), x_ticks, y_ticks, False
    )


def _spread_labels(series: list[ChartSeries], gap: float = 14.0) -> list[ChartSeries]:
    """Move the end labels apart, keeping their order, so that no two overlap."""
    placed: list[ChartSeries] = []
    for item in sorted(series, key=lambda entry: entry.label_y):
        label_y = item.label_y
        if placed and item.end is not None and label_y - placed[-1].label_y < gap:
            label_y = placed[-1].label_y + gap
        placed.append(
            ChartSeries(
                item.index,
                item.country,
                item.alpha2,
                item.paths,
                item.points,
                item.end,
                label_y,
                item.held,
                item.total,
            )
        )
    return sorted(placed, key=lambda entry: entry.index)


EVENT_ROW = 30
EVENT_TOP = 18
EVENT_AXIS = 26


@dataclass(frozen=True)
class EventMark:
    """One country's formal events in one year, drawn as one mark."""

    x: float
    count: int
    label: str


@dataclass(frozen=True)
class EventRow:
    index: int
    alpha2: str
    y: float
    marks: tuple[EventMark, ...]


@dataclass(frozen=True)
class EventAxis:
    """The geometry of the panel of formal events above a chart of the same years.

    `outside` counts the events of these countries that fall outside the
    years charted: they are listed in the table and not drawn.
    """

    width: int
    height: int
    left: int
    right: float
    rows: tuple[EventRow, ...]
    x_ticks: tuple[Tick, ...]
    charted: int
    outside: int


def event_axis(view: IndicatorView, events: Sequence[TimelineEvent]) -> EventAxis:
    """Return the formal events of each country of `view`, by year, on the chart's scale.

    Values are annual, so an event is placed at its year, as a value is, and
    its exact date is in its label and in the table. One row per country, in
    the order and colour of the chart's series.
    """
    right = WIDTH - RIGHT
    height = EVENT_TOP + EVENT_ROW * len(view.series) + EVENT_AXIS
    years = set(view.years)
    by_row: dict[tuple[str, int], list[TimelineEvent]] = defaultdict(list)
    outside = 0
    for event in events:
        if event.effective_date.year in years:
            by_row[(event.country_alpha2, event.effective_date.year)].append(event)
        else:
            outside += 1
    if not view.years:
        return EventAxis(WIDTH, height, LEFT, right, (), (), 0, outside)
    x = _x_scale(view.years, right)
    rows = []
    for index, series in enumerate(view.series, start=1):
        marks = tuple(
            EventMark(
                round(x(year), 1),
                len(held),
                f"{series.country}, {year}: "
                + "; ".join(
                    f"{event.label}, {event.effective_date.isoformat()}, {event.policy_title}"
                    for event in held
                ),
            )
            for year in view.years
            if (held := by_row.get((series.alpha2, year)))
        )
        rows.append(EventRow(index, series.alpha2, EVENT_TOP + EVENT_ROW * (index - 0.5), marks))
    charted = sum(mark.count for row in rows for mark in row.marks)
    return EventAxis(
        WIDTH, height, LEFT, right, tuple(rows), _x_ticks(view.years, x), charted, outside
    )
