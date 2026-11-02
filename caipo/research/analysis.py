"""The descriptive-change method, as a pure function of its inputs (ADR-0020 point 14).

Given the values of some indicators for some countries between two years,
it reports, for each indicator and country: the value in the first year,
the value in the last year, the absolute change, the relative change, how
many years in the range hold a value, how many do not, and how many held
values the provider flags as estimated, provisional, or projected.

It never fills a gap. If the first or the last value is missing, the change
is not computed and the reason is given. It states no correlation, cause,
or interpretation. Its version is recorded with every run; any change to
what it computes is a new version.
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

METHOD = "descriptive_change"
METHOD_VERSION = 1
_PLACES = Decimal("0.000001")


@dataclass(frozen=True)
class InputValue:
    """One value the run used, with where it came from."""

    indicator: str
    indicator_name: str
    unit: str
    layer: str
    country: str
    year: int
    value: str | None
    status: str
    release_sha256: str
    release_label: str
    source: str


def _change(first: Decimal | None, last: Decimal | None) -> dict[str, str | None]:
    if first is None or last is None:
        return {
            "absolute_change": None,
            "relative_change_percent": None,
            "not_computed_because": (
                "the value of the first year is missing"
                if first is None
                else "the value of the last year is missing"
            ),
        }
    relative = None if first == 0 else str(((last - first) / abs(first) * 100).quantize(_PLACES))
    return {
        "absolute_change": str((last - first).quantize(_PLACES)),
        "relative_change_percent": relative,
        "not_computed_because": None if relative is not None else "the first value is zero",
    }


def compute(
    inputs: Sequence[InputValue], *, start_year: int, end_year: int
) -> list[dict[str, Any]]:
    """Return one result row for each indicator and country among the inputs, in a fixed order."""
    keys = sorted({(item.layer, item.indicator, item.country) for item in inputs})
    rows = []
    for layer, indicator, country in keys:
        values = {
            item.year: item
            for item in inputs
            if item.indicator == indicator and item.country == country
        }
        first = values.get(start_year)
        last = values.get(end_year)
        first_value = Decimal(first.value) if first and first.value is not None else None
        last_value = Decimal(last.value) if last and last.value is not None else None
        in_range = [values.get(year) for year in range(start_year, end_year + 1)]
        held = [item for item in in_range if item is not None and item.value is not None]
        sample = next(iter(values.values()))
        rows.append(
            {
                "layer": layer,
                "indicator": indicator,
                "indicator_name": sample.indicator_name,
                "unit": sample.unit,
                "country": country,
                "start_year": start_year,
                "end_year": end_year,
                "start_value": str(first_value) if first_value is not None else None,
                "end_value": str(last_value) if last_value is not None else None,
                **_change(first_value, last_value),
                "years_held": len(held),
                "years_missing": (end_year - start_year + 1) - len(held),
                "values_flagged": sum(
                    1 for item in held if item.status not in ("reported", "missing")
                ),
            }
        )
    return rows


def fingerprint(document: object) -> str:
    """Return the SHA-256 of a document in one canonical JSON form."""
    text = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def serialise(inputs: Sequence[InputValue]) -> list[dict[str, Any]]:
    """Return the inputs as plain values, in a fixed order, for storage and fingerprinting."""
    return sorted(
        (asdict(item) for item in inputs),
        key=lambda item: (item["layer"], item["indicator"], item["country"], item["year"]),
    )
