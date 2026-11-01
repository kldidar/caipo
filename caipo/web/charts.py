"""Server-rendered line charts for indicator series (ADR-0020 point 15).

Geometry only: this module turns series into coordinates, and the template
draws them as SVG. A year without a value breaks the line, so a gap is seen
as a gap and never bridged. One y-axis per chart, with rounded ticks; the
scale is not forced to start at zero, which the axis labels make visible.
Each series keeps the colour of its country across every chart, because
series always come in the same order.
"""

import math
from dataclasses import dataclass
from decimal import Decimal

from caipo.indicators.selectors import IndicatorView, Point

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
    first, last = view.years[0], view.years[-1]

    def x(year: int) -> float:
        return LEFT if first == last else LEFT + (year - first) / (last - first) * (right - LEFT)

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
    year_step = max(1, math.ceil(len(view.years) / 8))
    x_ticks = tuple(Tick(round(x(year), 1), str(year)) for year in view.years[::year_step])
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
