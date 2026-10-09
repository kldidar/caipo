"""Migration 0009, which creates the audit record, applied, reversed, and applied again (ADR-0018).

Each test takes the schema back to migration 0008, and always returns it to
the latest migration, whatever happens in between.
"""

from collections.abc import Iterator

import pytest
from django.apps.registry import Apps
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from caipo.accounts.models import AuditEvent, RoleEvent, User

pytestmark = [pytest.mark.services, pytest.mark.django_db(transaction=True)]

BEFORE = ("accounts", "0008_account_recovery_foundation")
AFTER = ("accounts", "0009_audit_event")

TABLES = {"accounts_auditevent", "accounts_auditeventchange"}
FUNCTIONS = {"accounts_auditevent_refuse_change", "accounts_auditeventchange_refuse_change"}
TRIGGERS = {
    ("accounts_auditevent", "accounts_auditevent_append_only", "O"),
    ("accounts_auditeventchange", "accounts_auditeventchange_append_only", "O"),
}
CONSTRAINTS = {
    "accounts_auditevent_action_known",
    "accounts_auditevent_target_type_known",
    "accounts_auditevent_action_fits_target_type",
    "accounts_auditeventchange_field_known",
    "accounts_auditeventchange_values_differ",
    "accounts_auditeventchange_field_once_per_event",
}
EARLIER_TRIGGERS = {
    ("accounts_roleevent", "accounts_roleevent_append_only", "O"),
    ("accounts_authenticationevent", "accounts_authenticationevent_append_only", "O"),
    ("accounts_accountevent", "accounts_accountevent_append_only", "O"),
}
# Visibly synthetic.
EMAIL = "test.account@caipo.test"
STORED = "TEST$not-a-real-password-hash"
TARGET = "00000000-0000-4000-8000-000000000001"


def _migrate(target: tuple[str, str]) -> Apps:
    executor = MigrationExecutor(connection)
    executor.migrate([target])
    return MigrationExecutor(connection).loader.project_state([target]).apps


def _applied() -> set[tuple[str, str]]:
    return set(MigrationExecutor(connection).loader.applied_migrations)


def _tables() -> set[str]:
    return set(connection.introspection.table_names())


def _functions() -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT proname FROM pg_proc"
            " WHERE pronamespace = current_schema()::regnamespace AND proname LIKE %s",
            ["accounts\\_audit%"],
        )
        return {str(name) for (name,) in cursor.fetchall()}


def _triggers() -> set[tuple[str, str, str]]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgrelid::regclass::text, tgname, tgenabled FROM pg_trigger"
            " WHERE NOT tgisinternal"
        )
        return {(str(table), str(name), str(enabled)) for table, name, enabled in cursor.fetchall()}


def _constraints() -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT conname FROM pg_constraint"
            " WHERE conrelid::regclass::text = ANY(%s) AND contype IN ('c', 'u')",
            [sorted(TABLES)],
        )
        return {str(name) for (name,) in cursor.fetchall()}


@pytest.fixture
def earlier() -> Iterator[Apps]:
    """Yield the models of migration 0008, on a schema taken back to it."""
    try:
        yield _migrate(BEFORE)
    finally:
        _migrate(AFTER)


def test_it_is_the_latest_migration_and_follows_the_one_before_it() -> None:
    loader = MigrationExecutor(connection).loader

    assert loader.graph.leaf_nodes("accounts") == [AFTER]
    assert loader.get_migration(*AFTER).dependencies == [BEFORE]


def test_applied_it_has_made_the_tables_their_constraints_and_their_triggers() -> None:
    assert AFTER in _applied()
    assert TABLES <= _tables()
    assert _functions() == FUNCTIONS
    assert TRIGGERS <= _triggers()
    assert _constraints() == CONSTRAINTS


def test_the_earlier_schema_has_none_of_what_it_adds(earlier: Apps) -> None:
    assert AFTER not in _applied()
    assert TABLES.isdisjoint(_tables())
    assert _functions() == set()
    assert TRIGGERS.isdisjoint(_triggers())


def test_reversing_it_leaves_the_three_earlier_event_tables_protected(earlier: Apps) -> None:
    assert _triggers() == EARLIER_TRIGGERS


def test_it_can_be_applied_again_after_being_reversed(earlier: Apps) -> None:
    _migrate(AFTER)

    assert TABLES <= _tables()
    assert _functions() == FUNCTIONS
    assert _triggers() == EARLIER_TRIGGERS | TRIGGERS
    assert _constraints() == CONSTRAINTS


def test_applying_it_changes_no_account_and_no_earlier_event(earlier: Apps) -> None:
    users = earlier.get_model("accounts", "User").objects
    account = users.create(
        email=EMAIL, password=STORED, status="active", activated_at=timezone.now()
    )
    earlier.get_model("accounts", "RoleEvent").objects.create(
        user=account, role="administrator", event_type="granted", reason="TEST bootstrap"
    )
    account_before = users.filter(pk=account.pk).values().get()
    events_before = list(RoleEvent.objects.values())

    _migrate(AFTER)

    assert User.objects.filter(pk=account.pk).values().get() == account_before
    assert list(RoleEvent.objects.values()) == events_before
    assert not AuditEvent.objects.exists()


def test_the_tables_are_protected_as_soon_as_it_is_applied(earlier: Apps) -> None:
    account = earlier.get_model("accounts", "User").objects.create(
        email=EMAIL, password=STORED, status="active", activated_at=timezone.now()
    )
    _migrate(AFTER)
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO accounts_auditevent"
            " (action, target_type, target_public_id, actor_id, correlation_id, created_at)"
            " VALUES ('created', 'registry.country', %s, %s, '', now())",
            [TARGET, account.pk],
        )

    for statement in (
        "UPDATE accounts_auditevent SET action = 'updated'",
        "DELETE FROM accounts_auditevent",
    ):
        with pytest.raises(IntegrityError, match="append-only"), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(statement)

    assert AuditEvent.objects.get().action == "created"


def test_reversing_it_destroys_the_audit_events_it_holds(earlier: Apps) -> None:
    """Nothing stops the reversal when rows exist. This is the cost that is stated."""
    account = earlier.get_model("accounts", "User").objects.create(
        email=EMAIL, password=STORED, status="active", activated_at=timezone.now()
    )
    _migrate(AFTER)
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO accounts_auditevent"
            " (action, target_type, target_public_id, actor_id, correlation_id, created_at)"
            " VALUES ('created', 'registry.country', %s, %s, '', now())",
            [TARGET, account.pk],
        )

    _migrate(BEFORE)
    assert TABLES.isdisjoint(_tables())
    _migrate(AFTER)

    assert not AuditEvent.objects.exists()
    assert User.objects.filter(pk=account.pk).exists()
