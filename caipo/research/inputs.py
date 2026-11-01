"""The values a descriptive-change run uses, read through the indicators' selectors."""

import uuid

from caipo.accounts.selectors import AuthenticationContext
from caipo.core.data_class import DataClass
from caipo.core.entry import InvalidEntryError, RecordNotFoundError
from caipo.indicators import selectors as indicators_selectors
from caipo.research.analysis import InputValue

# The most indicators one run may take, so that a run and its record stay readable.
MAX_INDICATORS = 12


def gather(
    actor: AuthenticationContext | None,
    *,
    data_class: str,
    indicators: list[uuid.UUID],
    start_year: int,
    end_year: int,
) -> list[InputValue]:
    """Return the inputs a descriptive-change run with these parameters would use now.

    Raises InvalidEntryError if the parameters are not acceptable, and
    RecordNotFoundError if no value of these indicators of this data class
    lies in the range.
    """
    if data_class not in DataClass.values:
        raise InvalidEntryError("The data class is not one of those listed.")
    if not 1900 <= start_year < end_year <= 2100:
        raise InvalidEntryError(
            "The first year is before the last, and both are between 1900 and 2100."
        )
    if not 1 <= len(set(indicators)) <= MAX_INDICATORS:
        raise InvalidEntryError(f"Choose between 1 and {MAX_INDICATORS} indicators.")
    rows = indicators_selectors.analysis_inputs(
        actor,
        indicators=sorted(set(indicators)),
        data_class=data_class,
        start_year=start_year,
        end_year=end_year,
    )
    if not rows:
        raise RecordNotFoundError("No value of these indicators lies in the range.")
    return [
        InputValue(
            indicator=row.indicator,
            indicator_name=row.indicator_name,
            unit=row.unit,
            layer=row.layer,
            country=row.country,
            year=row.year,
            # The canonical text of the value: the same number, without trailing zeros.
            value=format(row.value.normalize(), "f") if row.value is not None else None,
            status=row.status,
            release_sha256=row.release_sha256,
            release_label=row.release_label,
            source=row.source,
        )
        for row in rows
    ]
