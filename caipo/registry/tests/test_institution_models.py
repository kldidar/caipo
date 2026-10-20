"""Institution and InstitutionName in the database: their columns and references, the
checks on their kinds and dates and on succession, and the triggers that keep what is
set once (ADR-0018 points 8 to 10, 16, 19, 21, 22, 46, and 50; testing requirements 5
and 6; ADR-0019 Increment 3).

Every row here is sent to the database as SQL, past the models and the
services, so that what is tested is what PostgreSQL itself refuses.
"""

import uuid
from collections.abc import Sequence
from typing import Any

import pytest
from django.db import DataError, IntegrityError, connection, models, transaction

from caipo.registry.models import (
    Country,
    Institution,
    InstitutionKind,
    InstitutionName,
    InstitutionNameKind,
    Language,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db]

# Visibly synthetic: identifiers of no record, and codes from the ranges the
# standards reserve for private use.
PUBLIC_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
OTHER_PUBLIC_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")
THIRD_PUBLIC_ID = uuid.UUID("00000000-0000-4000-8000-000000000003")

INSERT_INSTITUTION = (
    "INSERT INTO registry_institution (public_id, kind, country_id, parent_id, valid_from,"
    " valid_to, successor_id) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id"
)
INSERT_NAME = (
    "INSERT INTO registry_institutionname (public_id, institution_id, text, language_id, kind,"
    " valid_from, valid_to, entered_in_error) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
    " RETURNING id"
)


def _execute(statement: str, parameters: Sequence[Any] = ()) -> int | None:
    """Send a statement without the application, in a transaction of its own.

    Returns the first column of the first row it returns, if it returns one.
    """
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(statement, parameters)
        row = cursor.fetchone() if cursor.description else None
        return None if row is None else int(row[0])


def _country() -> int:
    key = _execute(
        "INSERT INTO registry_country (public_id, alpha2, alpha3, name_en, is_active)"
        " VALUES (%s, 'XA', 'XAA', 'TEST Country', true) RETURNING id",
        [uuid.uuid4()],
    )
    assert key is not None
    return key


def _language() -> int:
    key = _execute(
        "INSERT INTO registry_language (public_id, code, script_code, name_en, is_active)"
        " VALUES (%s, 'qaa', 'Qaaa', 'TEST Language', true) RETURNING id",
        [uuid.uuid4()],
    )
    assert key is not None
    return key


def _institution(
    public_id: uuid.UUID = PUBLIC_ID,
    kind: str = "ministry",
    *,
    country: int | None = None,
    parent: int | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
    successor: int | None = None,
) -> int:
    key = _execute(
        INSERT_INSTITUTION, [public_id, kind, country, parent, valid_from, valid_to, successor]
    )
    assert key is not None
    return key


def _name(
    institution: int,
    language: int,
    public_id: uuid.UUID = PUBLIC_ID,
    *,
    text: str = "TEST Name",
    kind: str = "official",
    valid_from: str | None = None,
    valid_to: str | None = None,
    entered_in_error: bool = False,
) -> int:
    key = _execute(
        INSERT_NAME,
        [public_id, institution, text, language, kind, valid_from, valid_to, entered_in_error],
    )
    assert key is not None
    return key


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


def test_the_institution_table_holds_exactly_these_columns() -> None:
    """No active flag: an institution's validity period says whether it exists (point 8)."""
    assert _columns("registry_institution") == {
        "id": ("bigint", None, "NO"),
        "public_id": ("uuid", None, "NO"),
        "kind": ("character varying", 32, "NO"),
        "country_id": ("bigint", None, "YES"),
        "parent_id": ("bigint", None, "YES"),
        "valid_from": ("date", None, "YES"),
        "valid_to": ("date", None, "YES"),
        "successor_id": ("bigint", None, "YES"),
    }


def test_the_institution_name_table_holds_exactly_these_columns() -> None:
    assert _columns("registry_institutionname") == {
        "id": ("bigint", None, "NO"),
        "public_id": ("uuid", None, "NO"),
        "institution_id": ("bigint", None, "NO"),
        "text": ("character varying", 500, "NO"),
        "language_id": ("bigint", None, "NO"),
        "kind": ("character varying", 32, "NO"),
        "valid_from": ("date", None, "YES"),
        "valid_to": ("date", None, "YES"),
        "entered_in_error": ("boolean", None, "NO"),
    }


@pytest.mark.parametrize(
    ("model", "references"),
    [
        (Institution, {"country": Country, "parent": Institution, "successor": Institution}),
        (InstitutionName, {"institution": Institution, "language": Language}),
    ],
)
def test_each_reference_is_to_a_registry_record_and_protects_what_it_refers_to(
    model: type[models.Model], references: dict[str, type[models.Model]]
) -> None:
    """None refers to a user (ADR-0018 point 3), and every one is PROTECT (point 16)."""
    concrete = [field for field in model._meta.get_fields() if field.is_relation and field.concrete]

    assert {field.name: field.related_model for field in concrete} == references
    for field in concrete:
        assert isinstance(field, models.ForeignKey)
        assert field.remote_field.on_delete is models.PROTECT


def test_a_public_identifier_is_a_random_version_4_uuid() -> None:
    identifiers = {Institution().public_id for _ in range(20)} | {InstitutionName().public_id}

    assert len(identifiers) == 21
    assert {identifier.version for identifier in identifiers} == {4}


def test_a_name_starts_unmarked() -> None:
    assert InstitutionName().entered_in_error is False
    assert InstitutionName._meta.get_field("entered_in_error").default is False


# --- The kinds (ADR-0018 points 9 and 10) -------------------------------------


@pytest.mark.parametrize("kind", InstitutionKind.values)
def test_the_database_accepts_each_kind_of_institution(kind: str) -> None:
    _institution(kind=kind)

    assert Institution.objects.get().kind == kind


def test_the_kinds_of_institution_are_the_eight_of_the_data_model() -> None:
    assert InstitutionKind.values == [
        "ministry",
        "legislature",
        "regulator",
        "statistical_agency",
        "international_organisation",
        "university",
        "media_outlet",
        "company",
    ]


@pytest.mark.parametrize(
    "kind", ["other", "", "Ministry", "MINISTRY", "ministry ", "agency", "official"]
)
def test_the_database_rejects_any_other_kind_of_institution(kind: str) -> None:
    with pytest.raises(IntegrityError, match="registry_institution_kind_known"):
        _institution(kind=kind)

    assert not Institution.objects.exists()


@pytest.mark.parametrize("kind", InstitutionNameKind.values)
def test_the_database_accepts_each_kind_of_name(kind: str) -> None:
    _name(_institution(), _language(), kind=kind)

    assert InstitutionName.objects.get().kind == kind


def test_the_kinds_of_name_are_the_four_of_adr_0018() -> None:
    assert InstitutionNameKind.values == [
        "official",
        "transliteration",
        "english_rendering",
        "abbreviation",
    ]


@pytest.mark.parametrize(
    "kind", ["other", "", "Official", "official ", "english rendering", "ministry"]
)
def test_the_database_rejects_any_other_kind_of_name(kind: str) -> None:
    institution, language = _institution(), _language()

    with pytest.raises(IntegrityError, match="registry_institutionname_kind_known"):
        _name(institution, language, kind=kind)

    assert not InstitutionName.objects.exists()


# --- The order of the dates (ADR-0018 point 21) -------------------------------

DATES_IN_ORDER = [
    (None, None),
    ("2001-02-03", None),
    (None, "2001-02-03"),
    ("2001-02-03", "2001-02-04"),
    ("1900-01-01", "2100-12-31"),
]
DATES_OUT_OF_ORDER = [("2001-02-03", "2001-02-03"), ("2001-02-04", "2001-02-03")]


@pytest.mark.parametrize(("valid_from", "valid_to"), DATES_IN_ORDER)
def test_the_database_accepts_an_institution_whose_known_dates_are_in_order(
    valid_from: str | None, valid_to: str | None
) -> None:
    _institution(valid_from=valid_from, valid_to=valid_to)

    assert Institution.objects.count() == 1


@pytest.mark.parametrize(("valid_from", "valid_to"), DATES_OUT_OF_ORDER)
def test_the_database_rejects_an_institution_that_ends_before_or_when_it_begins(
    valid_from: str, valid_to: str
) -> None:
    """Half-open: an institution that begins and ends on the same day covers no day."""
    with pytest.raises(IntegrityError, match="registry_institution_dates_in_order"):
        _institution(valid_from=valid_from, valid_to=valid_to)
    key = _institution(valid_from="2001-02-01")
    with pytest.raises(IntegrityError, match="registry_institution_dates_in_order"):
        _execute(
            "UPDATE registry_institution SET valid_from = %s, valid_to = %s WHERE id = %s",
            [valid_from, valid_to, key],
        )

    assert Institution.objects.values_list("valid_from", "valid_to").get()[1] is None


@pytest.mark.parametrize(("valid_from", "valid_to"), DATES_IN_ORDER)
def test_the_database_accepts_a_name_whose_known_dates_are_in_order(
    valid_from: str | None, valid_to: str | None
) -> None:
    _name(_institution(), _language(), valid_from=valid_from, valid_to=valid_to)

    assert InstitutionName.objects.count() == 1


@pytest.mark.parametrize(("valid_from", "valid_to"), DATES_OUT_OF_ORDER)
def test_the_database_rejects_a_name_that_ends_before_or_when_it_begins(
    valid_from: str, valid_to: str
) -> None:
    institution, language = _institution(), _language()

    with pytest.raises(IntegrityError, match="registry_institutionname_dates_in_order"):
        _name(institution, language, valid_from=valid_from, valid_to=valid_to)
    key = _name(institution, language)
    with pytest.raises(IntegrityError, match="registry_institutionname_dates_in_order"):
        _execute(
            "UPDATE registry_institutionname SET valid_from = %s, valid_to = %s WHERE id = %s",
            [valid_from, valid_to, key],
        )

    assert InstitutionName.objects.values_list("valid_from", "valid_to").get() == (None, None)


# --- Parent and successor (ADR-0018 point 22) ---------------------------------


def test_the_database_rejects_an_institution_that_is_its_own_parent() -> None:
    with pytest.raises(IntegrityError, match="registry_institution_not_own_parent"):
        _execute(
            "INSERT INTO registry_institution (id, public_id, kind, parent_id)"
            " VALUES (900001, %s, 'ministry', 900001)",
            [PUBLIC_ID],
        )
    key = _institution()
    with pytest.raises(IntegrityError, match="registry_institution_not_own_parent"):
        _execute("UPDATE registry_institution SET parent_id = id WHERE id = %s", [key])

    assert Institution.objects.values_list("parent_id", flat=True).get() is None


def test_the_database_rejects_an_institution_that_is_its_own_successor() -> None:
    with pytest.raises(IntegrityError, match="registry_institution_not_own_successor"):
        _execute(
            "INSERT INTO registry_institution (id, public_id, kind, valid_to, successor_id)"
            " VALUES (900001, %s, 'ministry', '2001-02-03', 900001)",
            [PUBLIC_ID],
        )
    key = _institution(valid_to="2001-02-03")
    with pytest.raises(IntegrityError, match="registry_institution_not_own_successor"):
        _execute("UPDATE registry_institution SET successor_id = id WHERE id = %s", [key])

    assert Institution.objects.values_list("successor_id", flat=True).get() is None


def test_the_database_accepts_another_institution_as_parent_and_as_successor() -> None:
    other = _institution(OTHER_PUBLIC_ID)

    _institution(parent=other, valid_to="2001-02-03", successor=other)

    assert Institution.objects.filter(parent_id=other, successor_id=other).count() == 1


def test_the_database_rejects_a_successor_of_an_institution_with_no_valid_to_date() -> None:
    """An institution that names a successor has ended."""
    successor = _institution(OTHER_PUBLIC_ID)

    with pytest.raises(IntegrityError, match="registry_institution_successor_needs_valid_to"):
        _institution(successor=successor)
    with pytest.raises(IntegrityError, match="registry_institution_successor_needs_valid_to"):
        _institution(valid_from="2001-02-03", successor=successor)

    assert Institution.objects.count() == 1


def test_the_database_rejects_clearing_the_valid_to_date_of_an_institution_with_a_successor() -> (
    None
):
    successor = _institution(OTHER_PUBLIC_ID)
    key = _institution(valid_to="2001-02-03", successor=successor)

    with pytest.raises(IntegrityError, match="registry_institution_successor_needs_valid_to"):
        _execute("UPDATE registry_institution SET valid_to = NULL WHERE id = %s", [key])

    _execute(
        "UPDATE registry_institution SET valid_to = NULL, successor_id = NULL WHERE id = %s", [key]
    )
    assert Institution.objects.get(pk=key).successor_id is None


def test_several_institutions_may_name_the_same_successor() -> None:
    """A merger (ADR-0018 point 22): a successor is one institution, named by any number."""
    successor = _institution(THIRD_PUBLIC_ID)

    _institution(PUBLIC_ID, valid_to="2001-02-03", successor=successor)
    _institution(OTHER_PUBLIC_ID, valid_to="2002-02-03", successor=successor)

    assert Institution.objects.filter(successor_id=successor).count() == 2


# --- Public identifiers and required values -----------------------------------


def test_the_database_rejects_a_second_institution_with_the_same_public_identifier() -> None:
    _institution()

    with pytest.raises(IntegrityError, match="registry_institution_public_id_unique"):
        _institution()

    assert Institution.objects.count() == 1


def test_the_database_rejects_a_second_name_with_the_same_public_identifier() -> None:
    institution, language = _institution(), _language()
    _name(institution, language)

    with pytest.raises(IntegrityError, match="registry_institutionname_public_id_unique"):
        _name(institution, language, text="TEST Other name")

    assert InstitutionName.objects.count() == 1


@pytest.mark.parametrize("column", ["public_id", "kind"])
def test_the_database_rejects_an_institution_with_a_missing_value(column: str) -> None:
    values = {"public_id": PUBLIC_ID, "kind": "ministry", column: None}

    with pytest.raises(IntegrityError, match="null value"):
        _execute(
            "INSERT INTO registry_institution (public_id, kind) VALUES (%s, %s)",
            [values["public_id"], values["kind"]],
        )

    assert not Institution.objects.exists()


@pytest.mark.parametrize(
    "column", ["public_id", "institution_id", "text", "language_id", "kind", "entered_in_error"]
)
def test_the_database_rejects_a_name_with_a_missing_value(column: str) -> None:
    values: dict[str, Any] = {
        "public_id": PUBLIC_ID,
        "institution_id": _institution(),
        "text": "TEST Name",
        "language_id": _language(),
        "kind": "official",
        "entered_in_error": False,
        column: None,
    }

    with pytest.raises(IntegrityError, match="null value"):
        _execute(
            "INSERT INTO registry_institutionname (public_id, institution_id, text, language_id,"
            " kind, entered_in_error) VALUES (%s, %s, %s, %s, %s, %s)",
            list(values.values()),
        )

    assert not InstitutionName.objects.exists()


def test_the_text_column_holds_the_longest_name_and_no_longer() -> None:
    institution, language = _institution(), _language()

    _name(institution, language, text="T" * 500)
    with pytest.raises(DataError):
        _name(institution, language, OTHER_PUBLIC_ID, text="T" * 501)

    assert InstitutionName.objects.get().text == "T" * 500


# --- Nothing is deleted, and what is set once does not change (points 16 to 19) ---


@pytest.mark.parametrize(
    ("table", "model"),
    [("registry_institution", Institution), ("registry_institutionname", InstitutionName)],
)
def test_the_database_refuses_to_delete_a_record(table: str, model: type[models.Model]) -> None:
    """An institution with no name, so that PROTECT on its names does not refuse it first."""
    if model is Institution:
        _institution()
    else:
        _name(_institution(), _language())

    with pytest.raises(IntegrityError, match=f"{table} is never deleted"):
        _execute(f"DELETE FROM {table}")  # noqa: S608  # one of two fixed table names written above
    with pytest.raises(IntegrityError, match=f"{table} is never deleted"), transaction.atomic():
        model._default_manager.all().delete()
    with pytest.raises(IntegrityError, match=f"{table} is never deleted"), transaction.atomic():
        model._default_manager.get().delete()

    assert model._default_manager.count() == 1


def test_the_database_refuses_to_change_the_public_identifier_of_an_institution() -> None:
    _institution()

    with pytest.raises(IntegrityError, match="registry_institution identity is immutable"):
        _execute("UPDATE registry_institution SET public_id = %s", [OTHER_PUBLIC_ID])
    with pytest.raises(IntegrityError, match="registry_institution identity is immutable"):
        _execute(
            "UPDATE registry_institution SET kind = 'regulator', public_id = %s",
            [OTHER_PUBLIC_ID],
        )

    assert Institution.objects.values_list("public_id", "kind").get() == (PUBLIC_ID, "ministry")


def test_the_database_allows_every_other_attribute_of_an_institution_to_change() -> None:
    """The kind, country, parent, dates, and successor are corrected in place (point 13)."""
    other = _institution(OTHER_PUBLIC_ID)
    key = _institution()
    country = _country()

    _execute(
        "UPDATE registry_institution SET kind = 'regulator', country_id = %s, parent_id = %s,"
        " valid_from = '2001-02-03', valid_to = '2002-02-03', successor_id = %s WHERE id = %s",
        [country, other, other, key],
    )
    _execute("UPDATE registry_institution SET public_id = public_id WHERE id = %s", [key])

    assert Institution.objects.values_list("kind", "country_id", "parent_id", "successor_id").get(
        pk=key
    ) == ("regulator", country, other, other)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("public_id", str(OTHER_PUBLIC_ID)),
        ("institution_id", "another institution"),
        ("text", "TEST Other name"),
        ("text", "TEST Name "),
        ("language_id", "another language"),
        ("kind", "abbreviation"),
    ],
)
def test_the_database_refuses_to_change_what_of_a_name_is_set_once(column: str, value: str) -> None:
    """A rename is a new name: the old one is never overwritten (ADR-0018 point 19)."""
    _name(_institution(), _language())
    others = {
        "another institution": _institution(OTHER_PUBLIC_ID),
        "another language": _execute(
            "INSERT INTO registry_language (public_id, code, script_code, name_en, is_active)"
            " VALUES (%s, 'qab', 'Qaab', 'TEST Language B', true) RETURNING id",
            [uuid.uuid4()],
        ),
    }
    before = InstitutionName.objects.values().get()

    with pytest.raises(IntegrityError, match="registry_institutionname identity is immutable"):
        _execute(
            f"UPDATE registry_institutionname SET {column} = %s",  # noqa: S608  # one of five fixed column names written above
            [others.get(value, value)],
        )

    assert InstitutionName.objects.values().get() == before


def test_the_database_refuses_a_change_of_a_name_hidden_among_allowed_ones() -> None:
    _name(_institution(), _language())

    with pytest.raises(IntegrityError, match="registry_institutionname identity is immutable"):
        _execute(
            "UPDATE registry_institutionname SET valid_from = '2001-02-03',"
            " entered_in_error = true, text = 'TEST Other name'"
        )

    assert InstitutionName.objects.values_list("text", "entered_in_error").get() == (
        "TEST Name",
        False,
    )


def test_the_database_allows_the_dates_of_a_name_to_change_and_its_mark_to_be_set() -> None:
    _name(_institution(), _language())

    _execute(
        "UPDATE registry_institutionname SET valid_from = '2001-02-03', valid_to = '2002-02-03'"
    )
    _execute("UPDATE registry_institutionname SET entered_in_error = true")
    # What saving a whole record through the model sends: every column again.
    _execute(
        "UPDATE registry_institutionname SET public_id = public_id, institution_id ="
        " institution_id, text = text, language_id = language_id, kind = kind,"
        " entered_in_error = entered_in_error"
    )

    assert InstitutionName.objects.values_list("entered_in_error", flat=True).get() is True


def test_the_database_refuses_to_clear_the_mark_of_a_name_entered_in_error() -> None:
    """The mark is set once and never cleared (ADR-0018 point 19)."""
    _name(_institution(), _language(), entered_in_error=True)

    with pytest.raises(IntegrityError, match="registry_institutionname mark is never cleared"):
        _execute("UPDATE registry_institutionname SET entered_in_error = false")
    with pytest.raises(IntegrityError, match="registry_institutionname mark is never cleared"):
        _execute(
            "UPDATE registry_institutionname SET valid_from = '2001-02-03',"
            " entered_in_error = false"
        )
    with (
        pytest.raises(IntegrityError, match="registry_institutionname mark is never cleared"),
        transaction.atomic(),
    ):
        InstitutionName.objects.update(entered_in_error=False)

    assert InstitutionName.objects.values_list("entered_in_error", "valid_from").get() == (
        True,
        None,
    )


def test_a_marked_name_is_protected_like_any_other() -> None:
    _name(_institution(), _language(), entered_in_error=True)

    with pytest.raises(IntegrityError, match="registry_institutionname is never deleted"):
        _execute("DELETE FROM registry_institutionname")
    with pytest.raises(IntegrityError, match="registry_institutionname identity is immutable"):
        _execute("UPDATE registry_institutionname SET text = 'TEST Other name'")
