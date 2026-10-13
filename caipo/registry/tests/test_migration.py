"""The first registry migration, applied, reversed, and applied again
(ADR-0018 point 46; ADR-0019 points 7 to 10 and the supplementary test of Increment 2).

Each test that reverses it always returns the schema to the latest
migration, whatever happens in between.
"""

from collections.abc import Iterator

import pytest
from django.db import IntegrityError, connection, migrations, transaction
from django.db.migrations.executor import MigrationExecutor

from caipo.accounts.models import AuditEvent
from caipo.accounts.selectors import AuthenticationContext
from caipo.registry import services
from caipo.registry.models import Country, Language

pytestmark = [pytest.mark.services, pytest.mark.django_db(transaction=True)]

MIGRATION = ("registry", "0001_initial")
BEFORE = ("registry", None)

TABLES = {"registry_country", "registry_language"}
FUNCTIONS = {"registry_country_refuse_change", "registry_language_refuse_change"}
TRIGGERS = {
    ("registry_country", "registry_country_protect", "O"),
    ("registry_language", "registry_language_protect", "O"),
}
CONSTRAINTS = {
    "registry_country_public_id_unique",
    "registry_country_alpha2_unique",
    "registry_country_alpha3_unique",
    "registry_country_alpha2_form",
    "registry_country_alpha3_form",
    "registry_language_public_id_unique",
    "registry_language_codes_unique",
    "registry_language_code_form",
    "registry_language_script_code_form",
}


def _migrate(target: tuple[str, str | None]) -> None:
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
            ["registry\\_%"],
        )
        return {str(name) for (name,) in cursor.fetchall()}


def _triggers() -> set[tuple[str, str, str]]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgrelid::regclass::text, tgname, tgenabled FROM pg_trigger"
            " WHERE NOT tgisinternal AND tgrelid::regclass::text LIKE %s",
            ["registry\\_%"],
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
    """Return, for each registry trigger, its function, timing, and the statements it fires on."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgname, tgfoid::regproc::text,"
            " CASE WHEN tgtype & 2 = 2 THEN 'BEFORE' ELSE 'AFTER' END,"
            " tgtype & 1 = 1, tgtype & 4 = 4, tgtype & 8 = 8, tgtype & 16 = 16"
            " FROM pg_trigger WHERE NOT tgisinternal AND tgrelid::regclass::text LIKE %s",
            ["registry\\_%"],
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
    """Take the schema back to before the registry existed, and always forward again."""
    try:
        _migrate(BEFORE)
        yield
    finally:
        _restore()


def test_it_is_the_only_registry_migration_and_depends_on_no_other() -> None:
    """In particular on no migration of accounts (ADR-0018 point 1, ADR-0019 point 9)."""
    loader = MigrationExecutor(connection).loader
    migration = loader.get_migration(*MIGRATION)

    assert loader.graph.leaf_nodes("registry") == [MIGRATION]
    assert loader.graph.root_nodes("registry") == [MIGRATION]
    assert migration.dependencies == []
    assert migration.run_before == []
    assert not [
        ancestor for ancestor in loader.graph.forwards_plan(MIGRATION) if ancestor != MIGRATION
    ]


def test_no_accounts_migration_depends_on_it() -> None:
    loader = MigrationExecutor(connection).loader

    for leaf in loader.graph.leaf_nodes("accounts"):
        assert not [node for node in loader.graph.forwards_plan(leaf) if node[0] == "registry"]


def test_it_creates_country_and_language_and_no_other_model() -> None:
    migration = MigrationExecutor(connection).loader.get_migration(*MIGRATION)
    created = [
        operation.name
        for operation in migration.operations
        if isinstance(operation, migrations.CreateModel)
    ]

    assert created == ["Country", "Language"]
    assert not [
        operation
        for operation in migration.operations
        if type(operation).__name__ in {"RunPython", "AddField", "AlterField", "DeleteModel"}
    ]


def test_it_writes_no_row() -> None:
    assert not Country.objects.exists()
    assert not Language.objects.exists()


def test_applied_it_has_made_the_two_tables_their_constraints_and_their_triggers() -> None:
    assert _tables() == TABLES
    assert _functions() == FUNCTIONS
    assert _triggers() == TRIGGERS
    assert _constraints() == CONSTRAINTS


def test_each_trigger_fires_before_every_update_and_delete_of_a_row_and_on_no_insert() -> None:
    assert _trigger_events() == {
        "registry_country_protect": (
            "registry_country_refuse_change",
            "BEFORE",
            True,
            False,
            True,
            True,
        ),
        "registry_language_protect": (
            "registry_language_refuse_change",
            "BEFORE",
            True,
            False,
            True,
            True,
        ),
    }


def test_each_trigger_is_created_in_the_migration_right_after_its_table() -> None:
    """So that neither table exists at any point without its protection."""
    migration = MigrationExecutor(connection).loader.get_migration(*MIGRATION)
    kinds = [type(operation).__name__ for operation in migration.operations]

    assert kinds == ["CreateModel", "RunSQL", "CreateModel", "RunSQL"]
    assert migration.atomic
    country_sql, language_sql = (
        str(operation.sql)
        for operation in migration.operations
        if isinstance(operation, migrations.RunSQL)
    )
    assert "ON registry_country" in country_sql and "registry_language" not in country_sql
    assert "ON registry_language" in language_sql and "registry_country" not in language_sql


def test_reversed_nothing_of_it_is_left_and_the_audit_tables_are_untouched(
    reversed_migration: None,
) -> None:
    assert MIGRATION not in MigrationExecutor(connection).loader.applied_migrations
    assert _tables() == set()
    assert _functions() == set()
    assert _triggers() == set()
    assert {
        ("accounts_auditevent", "accounts_auditevent_append_only", "O"),
        ("accounts_auditeventchange", "accounts_auditeventchange_append_only", "O"),
    } <= _every_trigger()


def test_it_can_be_applied_again_after_being_reversed(reversed_migration: None) -> None:
    _migrate(MIGRATION)

    assert _tables() == TABLES
    assert _functions() == FUNCTIONS
    assert _triggers() == TRIGGERS
    assert _constraints() == CONSTRAINTS


def test_the_tables_are_protected_as_soon_as_it_is_applied(reversed_migration: None) -> None:
    _migrate(MIGRATION)
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO registry_country (public_id, alpha2, alpha3, name_en, is_active)"
            " VALUES ('00000000-0000-4000-8000-000000000001', 'XA', 'XAA', 'TEST Country', true)"
        )
        cursor.execute(
            "INSERT INTO registry_language (public_id, code, script_code, name_en, is_active)"
            " VALUES ('00000000-0000-4000-8000-000000000002', 'qaa', 'Qaaa', 'TEST Language', true)"
        )

    for statement, refusal in (
        ("DELETE FROM registry_country", "never deleted"),
        ("UPDATE registry_country SET alpha2 = 'XB'", "identity is immutable"),
        ("DELETE FROM registry_language", "never deleted"),
        ("UPDATE registry_language SET code = 'qab'", "identity is immutable"),
    ):
        with pytest.raises(IntegrityError, match=refusal), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(statement)

    assert Country.objects.get().alpha2 == "XA"
    assert Language.objects.get().code == "qaa"


def test_reversing_it_destroys_the_records_and_leaves_the_audit_events_that_name_them(
    administrator: AuthenticationContext,
) -> None:
    """Nothing stops the reversal when rows exist. This is the cost that is stated.

    The tables come back empty when it is applied again, and the audit
    events, which are in another app, then name records that no longer exist.
    """
    country = services.create_country(
        actor=administrator, alpha2="XA", alpha3="XAA", name_en="TEST Country"
    )
    language = services.create_language(
        actor=administrator, code="qaa", script_code="Qaaa", name_en="TEST Language"
    )
    try:
        _migrate(BEFORE)
        assert _tables() == set()
    finally:
        _restore()

    assert not Country.objects.exists()
    assert not Language.objects.exists()
    assert list(AuditEvent.objects.order_by("id").values_list("action", "target_public_id")) == [
        ("created", country),
        ("created", language),
    ]
