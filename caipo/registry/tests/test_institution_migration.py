"""The second registry migration, applied, reversed, and applied again
(ADR-0018 point 46; ADR-0019 points 7 to 10 and the supplementary test of Increment 3).

It creates Institution and InstitutionName; both triggers exist once it is
applied; it depends on the first registry migration and on no accounts
migration; it reverses. Each test that reverses it always returns the schema
to the latest migration, whatever happens in between.
"""

from collections.abc import Iterator

import pytest
from django.db import IntegrityError, connection, migrations, transaction
from django.db.migrations.executor import MigrationExecutor

from caipo.accounts.models import AuditEvent
from caipo.accounts.selectors import AuthenticationContext
from caipo.registry import services
from caipo.registry.models import Country, Institution, InstitutionName, Language
from caipo.registry.services import NewName

pytestmark = [pytest.mark.services, pytest.mark.django_db(transaction=True)]

FIRST = ("registry", "0001_initial")
MIGRATION = ("registry", "0002_institutions")

FIRST_TABLES = {"registry_country", "registry_language"}
TABLES = {"registry_institution", "registry_institutionname"}
FUNCTIONS = {"registry_institution_refuse_change", "registry_institutionname_refuse_change"}
TRIGGERS = {
    ("registry_institution", "registry_institution_protect", "O"),
    ("registry_institutionname", "registry_institutionname_protect", "O"),
}
CONSTRAINTS = {
    "registry_institution_public_id_unique",
    "registry_institution_kind_known",
    "registry_institution_dates_in_order",
    "registry_institution_not_own_parent",
    "registry_institution_not_own_successor",
    "registry_institution_successor_needs_valid_to",
    "registry_institutionname_public_id_unique",
    "registry_institutionname_kind_known",
    "registry_institutionname_dates_in_order",
}


def _migrate(target: tuple[str, str]) -> None:
    MigrationExecutor(connection).migrate([target])


def _restore() -> None:
    """Return the schema to the latest migration of every app, whichever that is by then."""
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def _tables() -> set[str]:
    return {name for name in connection.introspection.table_names() if name.startswith("registry")}


def _functions() -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT proname FROM pg_proc"
            " WHERE pronamespace = current_schema()::regnamespace AND proname LIKE %s",
            ["registry\\_institution%"],
        )
        return {str(name) for (name,) in cursor.fetchall()}


def _triggers() -> set[tuple[str, str, str]]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgrelid::regclass::text, tgname, tgenabled FROM pg_trigger"
            " WHERE NOT tgisinternal AND tgrelid::regclass::text = ANY(%s)",
            [sorted(TABLES)],
        )
        return {(str(table), str(name), str(enabled)) for table, name, enabled in cursor.fetchall()}


def _every_trigger() -> set[tuple[str, str, str]]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgrelid::regclass::text, tgname, tgenabled FROM pg_trigger"
            " WHERE NOT tgisinternal"
        )
        return {(str(table), str(name), str(enabled)) for table, name, enabled in cursor.fetchall()}


def _trigger_events() -> dict[str, tuple[str, str, bool, bool, bool, bool]]:
    """Return, for each trigger of the two tables, its function, timing, and statements."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgname, tgfoid::regproc::text,"
            " CASE WHEN tgtype & 2 = 2 THEN 'BEFORE' ELSE 'AFTER' END,"
            " tgtype & 1 = 1, tgtype & 4 = 4, tgtype & 8 = 8, tgtype & 16 = 16"
            " FROM pg_trigger WHERE NOT tgisinternal AND tgrelid::regclass::text = ANY(%s)",
            [sorted(TABLES)],
        )
        return {
            str(name): (str(function), str(timing), each_row, on_insert, on_delete, on_update)
            for name, function, timing, each_row, on_insert, on_delete, on_update in (
                cursor.fetchall()
            )
        }


def _constraints() -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT conname FROM pg_constraint"
            " WHERE conrelid::regclass::text = ANY(%s) AND contype IN ('c', 'u')",
            [sorted(TABLES)],
        )
        return {str(name) for (name,) in cursor.fetchall()}


@pytest.fixture
def reversed_migration() -> Iterator[None]:
    """Take the schema back to just after the first registry migration, and always forward."""
    try:
        _migrate(FIRST)
        yield
    finally:
        _restore()


def test_it_depends_on_the_first_registry_migration_and_on_nothing_else() -> None:
    """In particular on no migration of accounts (ADR-0018 point 1, ADR-0019 point 9)."""
    loader = MigrationExecutor(connection).loader
    migration = loader.get_migration(*MIGRATION)

    assert migration.dependencies == [FIRST]
    assert migration.run_before == []
    assert loader.graph.leaf_nodes("registry") == [MIGRATION]
    assert set(loader.graph.forwards_plan(MIGRATION)) == {FIRST, MIGRATION}


def test_no_accounts_migration_depends_on_it() -> None:
    loader = MigrationExecutor(connection).loader

    for leaf in loader.graph.leaf_nodes("accounts"):
        assert not [node for node in loader.graph.forwards_plan(leaf) if node[0] == "registry"]


def test_it_creates_institution_and_institution_name_and_no_other_model() -> None:
    migration = MigrationExecutor(connection).loader.get_migration(*MIGRATION)
    created = [
        operation.name
        for operation in migration.operations
        if isinstance(operation, migrations.CreateModel)
    ]

    assert created == ["Institution", "InstitutionName"]
    assert not [
        operation
        for operation in migration.operations
        if type(operation).__name__
        in {"RunPython", "AddField", "AlterField", "RemoveField", "DeleteModel", "AddConstraint"}
    ]


def test_it_writes_no_row() -> None:
    assert not Institution.objects.exists()
    assert not InstitutionName.objects.exists()


def test_applied_it_has_made_the_two_tables_their_constraints_and_their_triggers() -> None:
    assert _tables() == FIRST_TABLES | TABLES
    assert _functions() == FUNCTIONS
    assert _triggers() == TRIGGERS
    assert _constraints() == CONSTRAINTS


def test_each_trigger_fires_before_every_update_and_delete_of_a_row_and_on_no_insert() -> None:
    assert _trigger_events() == {
        "registry_institution_protect": (
            "registry_institution_refuse_change",
            "BEFORE",
            True,
            False,
            True,
            True,
        ),
        "registry_institutionname_protect": (
            "registry_institutionname_refuse_change",
            "BEFORE",
            True,
            False,
            True,
            True,
        ),
    }


def test_each_table_is_created_with_its_constraints_and_then_its_trigger() -> None:
    """So that neither table exists at any point without its protection."""
    migration = MigrationExecutor(connection).loader.get_migration(*MIGRATION)
    kinds = [type(operation).__name__ for operation in migration.operations]

    assert kinds == ["CreateModel", "RunSQL", "CreateModel", "RunSQL"]
    assert migration.atomic
    institution_sql, name_sql = (
        str(operation.sql)
        for operation in migration.operations
        if isinstance(operation, migrations.RunSQL)
    )
    assert "ON registry_institution\n" in institution_sql
    assert "registry_institutionname" not in institution_sql
    assert "ON registry_institutionname\n" in name_sql
    for operation in migration.operations:
        if isinstance(operation, migrations.CreateModel):
            assert operation.options["constraints"], operation.name


def test_reversed_nothing_of_it_is_left_and_the_first_migration_and_audit_are_untouched(
    reversed_migration: None,
) -> None:
    applied = MigrationExecutor(connection).loader.applied_migrations

    assert MIGRATION not in applied and FIRST in applied
    assert _tables() == FIRST_TABLES
    assert _functions() == set()
    assert _triggers() == set()
    assert {
        ("registry_country", "registry_country_protect", "O"),
        ("registry_language", "registry_language_protect", "O"),
        ("accounts_auditevent", "accounts_auditevent_append_only", "O"),
        ("accounts_auditeventchange", "accounts_auditeventchange_append_only", "O"),
    } <= _every_trigger()


def test_it_can_be_applied_again_after_being_reversed(reversed_migration: None) -> None:
    _migrate(MIGRATION)

    assert _tables() == FIRST_TABLES | TABLES
    assert _functions() == FUNCTIONS
    assert _triggers() == TRIGGERS
    assert _constraints() == CONSTRAINTS


def test_the_tables_are_protected_as_soon_as_it_is_applied(reversed_migration: None) -> None:
    _migrate(MIGRATION)
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO registry_language (public_id, code, script_code, name_en, is_active)"
            " VALUES ('00000000-0000-4000-8000-000000000001', 'qaa', 'Qaaa', 'TEST', true)"
            " RETURNING id"
        )
        (language,) = cursor.fetchone()
        cursor.execute(
            "INSERT INTO registry_institution (public_id, kind)"
            " VALUES ('00000000-0000-4000-8000-000000000002', 'ministry') RETURNING id"
        )
        (institution,) = cursor.fetchone()
        cursor.execute(
            "INSERT INTO registry_institutionname (public_id, institution_id, text, language_id,"
            " kind, entered_in_error) VALUES ('00000000-0000-4000-8000-000000000003', %s,"
            " 'TEST Name', %s, 'official', true)",
            [institution, language],
        )

    for statement, refusal in (
        ("DELETE FROM registry_institutionname", "never deleted"),
        ("UPDATE registry_institutionname SET text = 'TEST Other'", "identity is immutable"),
        ("UPDATE registry_institutionname SET entered_in_error = false", "never cleared"),
        ("DELETE FROM registry_institution", "never deleted"),
        (
            "UPDATE registry_institution SET public_id = '00000000-0000-4000-8000-000000000004'",
            "identity is immutable",
        ),
    ):
        with pytest.raises(IntegrityError, match=refusal), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(statement)

    assert InstitutionName.objects.get().text == "TEST Name"
    assert Institution.objects.count() == 1


def test_reversing_it_destroys_the_records_and_leaves_countries_languages_and_the_events(
    administrator: AuthenticationContext,
) -> None:
    """Nothing stops the reversal when rows exist. This is the cost that is stated.

    The tables come back empty when it is applied again. Countries and
    languages stay, and the audit events, which are in another app, then
    name institutions and names that no longer exist.
    """
    country = services.create_country(
        actor=administrator, alpha2="XA", alpha3="XAA", name_en="TEST Country"
    )
    language = services.create_language(
        actor=administrator, code="qaa", script_code="Qaaa", name_en="TEST Language"
    )
    institution = services.create_institution(
        actor=administrator,
        kind="ministry",
        country=country,
        first_name=NewName(text="TEST Institution", language=language, kind="official"),
    )
    events_before = list(
        AuditEvent.objects.order_by("id").values_list("action", "target_type", "target_public_id")
    )
    try:
        _migrate(FIRST)
        assert _tables() == FIRST_TABLES
    finally:
        _restore()

    assert not Institution.objects.exists()
    assert not InstitutionName.objects.exists()
    assert list(Country.objects.values_list("public_id", flat=True)) == [country]
    assert list(Language.objects.values_list("public_id", flat=True)) == [language]
    assert (
        list(
            AuditEvent.objects.order_by("id").values_list(
                "action", "target_type", "target_public_id"
            )
        )
        == events_before
    )
    assert ("created", "registry.institution", institution) in events_before
