"""The descriptive-change method, as a pure function."""

from caipo.research.analysis import InputValue, compute, fingerprint, serialise


def _value(
    year: int, value: str | None, status: str = "reported", country: str = "XA"
) -> InputValue:
    return InputValue(
        indicator="TEST-1",
        indicator_name="TEST",
        unit="%",
        layer="A",
        country=country,
        year=year,
        value=value,
        status=status if value is not None else "missing",
        release_sha256="a" * 64,
        release_label="TEST",
        source="TEST",
    )


def test_change_between_the_first_and_last_year() -> None:
    (row,) = compute(
        [_value(2020, "10"), _value(2021, "11"), _value(2022, "15")], start_year=2020, end_year=2022
    )

    assert (row["start_value"], row["end_value"]) == ("10", "15")
    assert row["absolute_change"] == "5.000000"
    assert row["relative_change_percent"] == "50.000000"
    assert (row["years_held"], row["years_missing"]) == (3, 0)


def test_a_missing_end_is_never_filled_in() -> None:
    (row,) = compute(
        [_value(2020, "10"), _value(2021, "12"), _value(2022, None)], start_year=2020, end_year=2022
    )

    assert row["end_value"] is None
    assert row["absolute_change"] is None
    assert row["not_computed_because"] == "the value of the last year is missing"
    assert (row["years_held"], row["years_missing"]) == (2, 1)


def test_a_year_with_no_record_counts_as_missing() -> None:
    (row,) = compute([_value(2020, "1"), _value(2024, "2")], start_year=2020, end_year=2024)

    assert (row["years_held"], row["years_missing"]) == (2, 3)


def test_a_zero_start_gives_no_relative_change() -> None:
    (row,) = compute([_value(2020, "0"), _value(2021, "4")], start_year=2020, end_year=2021)

    assert row["absolute_change"] == "4.000000"
    assert row["relative_change_percent"] is None
    assert row["not_computed_because"] == "the first value is zero"


def test_flagged_values_are_counted() -> None:
    (row,) = compute(
        [_value(2020, "1", "estimated"), _value(2021, "2")], start_year=2020, end_year=2021
    )

    assert row["values_flagged"] == 1


def test_each_country_is_a_row_of_its_own_in_a_fixed_order() -> None:
    rows = compute(
        [_value(2020, "1", country="XB"), _value(2020, "2", country="XA")],
        start_year=2020,
        end_year=2021,
    )

    assert [row["country"] for row in rows] == ["XA", "XB"]


def test_the_fingerprint_depends_on_content_and_not_on_order() -> None:
    first = serialise([_value(2020, "1"), _value(2021, "2")])
    second = serialise([_value(2021, "2"), _value(2020, "1")])
    changed = serialise([_value(2020, "1"), _value(2021, "2.0")])

    assert fingerprint(first) == fingerprint(second)
    assert fingerprint(first) != fingerprint(changed)
    assert len(fingerprint(first)) == 64
