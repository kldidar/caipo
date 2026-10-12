"""Country and Language in the database: their columns, the forms and uniqueness of
their codes, and the triggers that keep their identity (ADR-0018 points 6, 7, 16, 17,
46, and 50; ADR-0019 points 29 to 32).

Every row here is sent to the database as SQL, past the models and the
services, so that what is tested is what PostgreSQL itself refuses.
"""

import uuid
from collections.abc import Sequence
from typing import Any

import pytest
from django.db import IntegrityError, connection, transaction

from caipo.registry.models import (
    COUNTRY_ALPHA2_PATTERN,
    COUNTRY_ALPHA3_PATTERN,
    LANGUAGE_CODE_PATTERN,
    LANGUAGE_SCRIPT_CODE_PATTERN,
    Country,
    Language,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db]

# Visibly synthetic: codes from the ranges the standards reserve for private
# use, and identifiers of no record.
PUBLIC_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
OTHER_PUBLIC_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")

INSERT_COUNTRY = (
    "INSERT INTO registry_country (public_id, alpha2, alpha3, name_en, is_active)"
    " VALUES (%s, %s, %s, 'TEST Country', true)"
)
INSERT_LANGUAGE = (
    "INSERT INTO registry_language (public_id, code, script_code, name_en, is_active)"
    " VALUES (%s, %s, %s, 'TEST Language', true)"
)

# What is not two, or three, capital ASCII letters. The look-alikes are single
# characters that a person or a careless comparison takes for an ASCII letter.
NOT_CAPITAL_LETTERS = [
    "x{rest}",  # lower case
    "Х{rest}",  # CYRILLIC CAPITAL LETTER HA, which looks like X
    "Χ{rest}",  # GREEK CAPITAL LETTER CHI, which looks like X
    "Ｘ{rest}",  # FULLWIDTH LATIN CAPITAL LETTER X
    "İ{rest}",  # LATIN CAPITAL LETTER I WITH DOT ABOVE
    "Å{rest}",  # LATIN CAPITAL LETTER A WITH RING ABOVE
    "1{rest}",
    " {rest}",
    "-{rest}",
    "\n{rest}",
    "\t{rest}",
]
NOT_LOWER_CASE_LETTERS = [
    "Q{rest}",  # upper case
    "ԛ{rest}",  # CYRILLIC SMALL LETTER QA, which looks like q
    "ｑ{rest}",  # FULLWIDTH LATIN SMALL LETTER Q
    "ı{rest}",  # LATIN SMALL LETTER DOTLESS I
    "å{rest}",  # LATIN SMALL LETTER A WITH RING ABOVE
    "ß{rest}",  # LATIN SMALL LETTER SHARP S
    "1{rest}",
    " {rest}",
    "-{rest}",
    "\n{rest}",
]


def _execute(statement: str, parameters: Sequence[Any] = ()) -> None:
    """Send a statement to the database without the application, in a transaction of its own."""
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(statement, parameters)


def _country(alpha2: str = "XA", alpha3: str = "XAA", public_id: uuid.UUID = PUBLIC_ID) -> None:
    _execute(INSERT_COUNTRY, [public_id, alpha2, alpha3])


def _language(
    code: str = "qaa", script_code: str = "Qaaa", public_id: uuid.UUID = PUBLIC_ID
) -> None:
    _execute(INSERT_LANGUAGE, [public_id, code, script_code])


def _columns(table: str) -> dict[str, tuple[str, int | None, str]]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name, data_type, character_maximum_length, is_nullable"
            " FROM information_schema.columns"
            " WHERE table_schema = current_schema() AND table_name = %s",
            [table],
        )
        return {
            str(name): (str(data_type), length, str(nullable))
            for name, data_type, length, nullable in cursor.fetchall()
        }


# --- What the tables hold -----------------------------------------------------


def test_the_country_table_holds_exactly_these_columns() -> None:
    assert _columns("registry_country") == {
        "id": ("bigint", None, "NO"),
        "public_id": ("uuid", None, "NO"),
        "alpha2": ("character varying", None, "NO"),
        "alpha3": ("character varying", None, "NO"),
        "name_en": ("character varying", 200, "NO"),
        "is_active": ("boolean", None, "NO"),
    }


def test_the_language_table_holds_exactly_these_columns() -> None:
    assert _columns("registry_language") == {
        "id": ("bigint", None, "NO"),
        "public_id": ("uuid", None, "NO"),
        "code": ("character varying", None, "NO"),
        "script_code": ("character varying", None, "NO"),
        "name_en": ("character varying", 200, "NO"),
        "is_active": ("boolean", None, "NO"),
    }


@pytest.mark.parametrize("model", [Country, Language])
def test_no_registry_record_refers_to_another_table(model: type[Country] | type[Language]) -> None:
    """In particular, none refers to a user (ADR-0018 point 3)."""
    assert [field.name for field in model._meta.get_fields() if field.is_relation] == []


def test_a_public_identifier_is_a_random_version_4_uuid() -> None:
    identifiers = {Country().public_id for _ in range(20)} | {Language().public_id}

    assert len(identifiers) == 21
    assert {identifier.version for identifier in identifiers} == {4}


# --- The form of the Country codes (ADR-0018 point 6) -------------------------


@pytest.mark.parametrize(("alpha2", "alpha3"), [("XA", "XAA"), ("AA", "ZZZ"), ("QM", "QMA")])
def test_the_database_accepts_country_codes_of_the_right_form(alpha2: str, alpha3: str) -> None:
    _country(alpha2, alpha3)

    assert Country.objects.values_list("alpha2", "alpha3").get() == (alpha2, alpha3)


@pytest.mark.parametrize(
    "alpha2",
    [template.format(rest="A") for template in NOT_CAPITAL_LETTERS]
    + ["A\n", "X", "", "XAA", "XA\n", "XA ", " XA", "XAXA"],
)
def test_the_database_rejects_an_alpha2_code_that_is_not_two_capital_letters(alpha2: str) -> None:
    with pytest.raises(IntegrityError, match="registry_country_alpha2_form"):
        _country(alpha2=alpha2)

    assert not Country.objects.exists()


@pytest.mark.parametrize(
    "alpha3",
    [template.format(rest="AA") for template in NOT_CAPITAL_LETTERS]
    + ["XA\n", "XA", "X", "", "XAAA", "XAA\n", "XAA ", " XAA"],
)
def test_the_database_rejects_an_alpha3_code_that_is_not_three_capital_letters(
    alpha3: str,
) -> None:
    with pytest.raises(IntegrityError, match="registry_country_alpha3_form"):
        _country(alpha3=alpha3)

    assert not Country.objects.exists()


@pytest.mark.parametrize("column", ["alpha2", "alpha3", "public_id", "name_en", "is_active"])
def test_the_database_rejects_a_country_with_a_missing_value(column: str) -> None:
    values: dict[str, object] = {
        "public_id": PUBLIC_ID,
        "alpha2": "XA",
        "alpha3": "XAA",
        "name_en": "TEST Country",
        "is_active": True,
    }
    values[column] = None

    with pytest.raises(IntegrityError, match=column):
        _execute(
            "INSERT INTO registry_country (public_id, alpha2, alpha3, name_en, is_active)"
            " VALUES (%(public_id)s, %(alpha2)s, %(alpha3)s, %(name_en)s, %(is_active)s)",
            values,  # type: ignore[arg-type]  # a mapping is what named placeholders take
        )


# --- The uniqueness of the Country codes (ADR-0018 point 6) -------------------


def test_the_database_rejects_a_second_country_with_the_same_alpha2_code() -> None:
    _country("XA", "XAA")

    with pytest.raises(IntegrityError, match="registry_country_alpha2_unique"):
        _country("XA", "XBB", OTHER_PUBLIC_ID)

    assert Country.objects.count() == 1


def test_the_database_rejects_a_second_country_with_the_same_alpha3_code() -> None:
    _country("XA", "XAA")

    with pytest.raises(IntegrityError, match="registry_country_alpha3_unique"):
        _country("XB", "XAA", OTHER_PUBLIC_ID)

    assert Country.objects.count() == 1


def test_the_database_rejects_a_second_country_with_the_same_public_identifier() -> None:
    _country("XA", "XAA")

    with pytest.raises(IntegrityError, match="registry_country_public_id_unique"):
        _country("XB", "XBB", PUBLIC_ID)

    assert Country.objects.count() == 1


def test_countries_that_share_nothing_are_both_stored() -> None:
    _country("XA", "XAA")
    _country("XB", "XBB", OTHER_PUBLIC_ID)

    assert Country.objects.count() == 2


# --- The form of the Language codes (ADR-0019 points 29 to 31) ----------------


@pytest.mark.parametrize(
    ("code", "script_code"), [("qaa", "Qaaa"), ("qtz", "Qabx"), ("abc", "Zyyy")]
)
def test_the_database_accepts_language_codes_of_the_right_form(code: str, script_code: str) -> None:
    _language(code, script_code)

    assert Language.objects.values_list("code", "script_code").get() == (code, script_code)


@pytest.mark.parametrize(
    "code",
    [template.format(rest="aa") for template in NOT_LOWER_CASE_LETTERS]
    + ["qa\n", "qA", "qaA", "qa", "q", "", "qaaa", "qaa\n", "qaa ", " qaa", "qaa-Qaaa"],
)
def test_the_database_rejects_a_language_code_that_is_not_three_lower_case_letters(
    code: str,
) -> None:
    """A two-letter code is among them, and so is a language and a script joined in one
    value: no other representation is accepted."""
    with pytest.raises(IntegrityError, match="registry_language_code_form"):
        _language(code=code)

    assert not Language.objects.exists()


@pytest.mark.parametrize(
    "script_code",
    [template.format(rest="aaa") for template in NOT_CAPITAL_LETTERS]
    + [f"Q{template.format(rest='aa')}" for template in NOT_LOWER_CASE_LETTERS]
    + ["Qaa\n", "QAAA", "QaaA", "qaaa", "Qaa", "Q", "", "Qaaaa", "Qaaa\n", "Qaaa ", " Qaaa"],
)
def test_the_database_rejects_a_script_code_that_is_not_a_capital_and_three_lower_case_letters(
    script_code: str,
) -> None:
    with pytest.raises(IntegrityError, match="registry_language_script_code_form"):
        _language(script_code=script_code)

    assert not Language.objects.exists()


@pytest.mark.parametrize("collation", ["C", "und-x-icu", "en-x-icu", "tr-x-icu"])
@pytest.mark.parametrize(
    ("pattern", "value"),
    [
        (COUNTRY_ALPHA2_PATTERN, "x\u0130"),
        (COUNTRY_ALPHA2_PATTERN, "\u00c5A"),
        (COUNTRY_ALPHA2_PATTERN, "xa"),
        (COUNTRY_ALPHA3_PATTERN, "xaa"),
        (LANGUAGE_CODE_PATTERN, "\u0131aa"),
        (LANGUAGE_CODE_PATTERN, "\u00e5aa"),
        (LANGUAGE_CODE_PATTERN, "QAA"),
        (LANGUAGE_SCRIPT_CODE_PATTERN, "qaaa"),
        (LANGUAGE_SCRIPT_CODE_PATTERN, "QAAA"),
    ],
)
def test_no_collation_makes_a_pattern_accept_a_letter_outside_ascii_or_of_the_other_case(
    collation: str, pattern: str, value: str
) -> None:
    """The patterns list their letters, so no collation widens them.

    A range would be read under the collation in force. The database of this
    project uses one collation; this asks the same patterns under others, so
    that the checks do not rest on which one a database was created with.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_collation WHERE collname = %s AND collencoding IN (-1, 6)",
            [collation],
        )
        if cursor.fetchone() is None:
            pytest.skip(f"This PostgreSQL has no collation {collation}.")
        cursor.execute(f'SELECT (%s COLLATE "{collation}") ~ %s', [value, pattern])  # noqa: S608  # the collation is one of four names written above, and a name cannot be a parameter
        (matches,) = cursor.fetchone()

    assert matches is False


@pytest.mark.parametrize(
    ("constraint", "pattern"),
    [
        ("registry_country_alpha2_form", COUNTRY_ALPHA2_PATTERN),
        ("registry_country_alpha3_form", COUNTRY_ALPHA3_PATTERN),
        ("registry_language_code_form", LANGUAGE_CODE_PATTERN),
        ("registry_language_script_code_form", LANGUAGE_SCRIPT_CODE_PATTERN),
    ],
)
def test_the_database_holds_each_check_with_the_pattern_the_model_states(
    constraint: str, pattern: str
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s", [constraint]
        )
        (definition,) = cursor.fetchone()

    assert f"'{pattern}'" in definition


# --- The uniqueness of the Language codes (ADR-0018 point 7) ------------------


def test_the_database_rejects_a_second_language_with_the_same_pair_of_codes() -> None:
    _language("qaa", "Qaaa")

    with pytest.raises(IntegrityError, match="registry_language_codes_unique"):
        _language("qaa", "Qaaa", OTHER_PUBLIC_ID)

    assert Language.objects.count() == 1


def test_the_same_language_in_another_script_is_another_record() -> None:
    _language("qaa", "Qaaa")
    _language("qaa", "Qaab", OTHER_PUBLIC_ID)

    assert Language.objects.count() == 2


def test_another_language_in_the_same_script_is_another_record() -> None:
    _language("qaa", "Qaaa")
    _language("qab", "Qaaa", OTHER_PUBLIC_ID)

    assert Language.objects.count() == 2


def test_the_database_rejects_a_second_language_with_the_same_public_identifier() -> None:
    _language("qaa", "Qaaa")

    with pytest.raises(IntegrityError, match="registry_language_public_id_unique"):
        _language("qab", "Qaab", PUBLIC_ID)

    assert Language.objects.count() == 1


# --- Identity does not change, and nothing is deleted (points 16 and 17) ------


@pytest.mark.parametrize(
    "assignment",
    ["alpha2 = 'XB'", "alpha3 = 'XBB'", "public_id = '00000000-0000-4000-8000-000000000002'"],
)
def test_the_database_refuses_to_change_the_identity_of_a_country(assignment: str) -> None:
    _country()
    before = Country.objects.values().get()

    with pytest.raises(IntegrityError, match="registry_country identity is immutable"):
        _execute(f"UPDATE registry_country SET {assignment}")  # noqa: S608  # one of three fixed assignments written above

    assert Country.objects.values().get() == before


@pytest.mark.parametrize(
    "assignment",
    ["code = 'qab'", "script_code = 'Qaab'", "public_id = '00000000-0000-4000-8000-000000000002'"],
)
def test_the_database_refuses_to_change_the_identity_of_a_language(assignment: str) -> None:
    _language()
    before = Language.objects.values().get()

    with pytest.raises(IntegrityError, match="registry_language identity is immutable"):
        _execute(f"UPDATE registry_language SET {assignment}")  # noqa: S608  # one of three fixed assignments written above

    assert Language.objects.values().get() == before


@pytest.mark.parametrize("table", ["registry_country", "registry_language"])
def test_the_database_refuses_an_identity_change_hidden_among_allowed_ones(table: str) -> None:
    _country()
    _language()

    with pytest.raises(IntegrityError, match=f"{table} identity is immutable"):
        _execute(
            f"UPDATE {table} SET name_en = 'TEST Other', is_active = false,"  # noqa: S608  # one of two fixed table names written above
            " public_id = '00000000-0000-4000-8000-000000000002'"
        )

    assert Country.objects.get().name_en == "TEST Country"
    assert Language.objects.get().name_en == "TEST Language"


@pytest.mark.parametrize("table", ["registry_country", "registry_language"])
def test_the_database_allows_the_name_and_the_active_flag_to_change(table: str) -> None:
    _country()
    _language()

    _execute(f"UPDATE {table} SET name_en = 'TEST Other', is_active = false")  # noqa: S608  # one of two fixed table names written above

    model: type[Country] | type[Language] = Country if table == "registry_country" else Language
    assert model.objects.values_list("name_en", "is_active").get() == ("TEST Other", False)


@pytest.mark.parametrize("table", ["registry_country", "registry_language"])
def test_the_database_allows_an_update_that_writes_the_same_identity_again(table: str) -> None:
    """What saving a whole record through the model sends: every column, unchanged ones too."""
    _country()
    _language()

    _execute(f"UPDATE {table} SET public_id = public_id, name_en = 'TEST Other'")  # noqa: S608  # one of two fixed table names written above


@pytest.mark.parametrize(
    ("table", "model"), [("registry_country", Country), ("registry_language", Language)]
)
def test_the_database_refuses_to_delete_a_record(
    table: str, model: type[Country] | type[Language]
) -> None:
    _country()
    _language()

    with pytest.raises(IntegrityError, match=f"{table} is never deleted"):
        _execute(f"DELETE FROM {table}")  # noqa: S608  # one of two fixed table names written above
    with pytest.raises(IntegrityError, match=f"{table} is never deleted"), transaction.atomic():
        model.objects.all().delete()
    with pytest.raises(IntegrityError, match=f"{table} is never deleted"), transaction.atomic():
        model.objects.get().delete()

    assert model.objects.count() == 1


@pytest.mark.parametrize("table", ["registry_country", "registry_language"])
def test_a_deactivated_record_is_protected_like_an_active_one(table: str) -> None:
    _country()
    _language()
    _execute(f"UPDATE {table} SET is_active = false")  # noqa: S608  # one of two fixed table names written above

    with pytest.raises(IntegrityError, match=f"{table} is never deleted"):
        _execute(f"DELETE FROM {table}")  # noqa: S608  # one of two fixed table names written above
    with pytest.raises(IntegrityError, match=f"{table} identity is immutable"):
        _execute(
            f"UPDATE {table} SET public_id = '00000000-0000-4000-8000-000000000002'"  # noqa: S608  # one of two fixed table names written above
        )
