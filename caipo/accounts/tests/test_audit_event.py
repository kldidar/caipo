"""AuditEvent and AuditEventChange: small, closed, and append-only in the database (ADR-0018)."""

import uuid
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

import pytest
from django.db import DataError, IntegrityError, connection, models, transaction
from django.db.models import ProtectedError

from caipo.accounts.models import (
    AUDIT_ACTION_TARGET_TYPES,
    AUDIT_VALUE_MAX_LENGTH,
    AuditAction,
    AuditEvent,
    AuditEventChange,
    AuditField,
    AuditTargetType,
    User,
)
from caipo.core.append_only import AppendOnlyError

pytestmark = [pytest.mark.services, pytest.mark.django_db]

EVENT_IS_APPEND_ONLY = "accounts_auditevent is append-only"
CHANGE_IS_APPEND_ONLY = "accounts_auditeventchange is append-only"
# Visibly synthetic: the identifiers of records that do not exist.
TARGET = uuid.UUID("00000000-0000-4000-8000-000000000001")
OTHER_TARGET = uuid.UUID("00000000-0000-4000-8000-000000000002")

ACTIONS = ["created", "updated", "deactivated", "reactivated", "marked_entered_in_error"]
TARGET_TYPES = [
    "registry.country",
    "registry.language",
    "registry.institution",
    "registry.institution_name",
]
FIELDS = ["name_en", "kind", "country", "parent", "successor", "valid_from", "valid_to"]
# Written out here, not read from the application: ADR-0018 point 31.
ALLOWED_PAIRS = (
    {(action, target_type) for action in ("created", "updated") for target_type in TARGET_TYPES}
    | {
        (action, target_type)
        for action in ("deactivated", "reactivated")
        for target_type in ("registry.country", "registry.language")
    }
    | {("marked_entered_in_error", "registry.institution_name")}
)
EVERY_PAIR = [(action, target_type) for action in ACTIONS for target_type in TARGET_TYPES]

INSERT_EVENT = (
    "INSERT INTO accounts_auditevent"
    " (action, target_type, target_public_id, actor_id, correlation_id, created_at)"
    " VALUES (%s, %s, %s, %s, '', now())"
)
INSERT_CHANGE = (
    "INSERT INTO accounts_auditeventchange (event_id, field, old_value, new_value)"
    " VALUES (%s, %s, %s, %s)"
)


@pytest.fixture
def user() -> User:
    return User.objects.create_user("test.actor@caipo.test")


@pytest.fixture
def event(user: User) -> AuditEvent:
    return AuditEvent.objects.create(
        action=AuditAction.UPDATED,
        target_type=AuditTargetType.COUNTRY,
        target_public_id=TARGET,
        actor=user,
    )


@pytest.fixture
def change(event: AuditEvent) -> AuditEventChange:
    return AuditEventChange.objects.create(
        event=event, field=AuditField.NAME_EN, old_value="TEST old name", new_value="TEST new name"
    )


def _insert(statement: str, parameters: Sequence[Any]) -> None:
    """Write a row without the application, in a transaction of its own."""
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(statement, parameters)


def _column(table: str, column: str) -> tuple[str, int | None, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT data_type, character_maximum_length, is_nullable"
            " FROM information_schema.columns"
            " WHERE table_schema = current_schema() AND table_name = %s AND column_name = %s",
            [table, column],
        )
        data_type, length, nullable = cursor.fetchone()
    return str(data_type), length, str(nullable)


# --- What the tables hold -----------------------------------------------------


def test_the_event_table_holds_exactly_these_columns() -> None:
    columns = {field.column for field in AuditEvent._meta.concrete_fields}

    assert columns == {
        "id",
        "action",
        "target_type",
        "target_public_id",
        "actor_id",
        "correlation_id",
        "created_at",
    }


def test_the_change_table_holds_exactly_these_columns() -> None:
    columns = {field.column for field in AuditEventChange._meta.concrete_fields}

    assert columns == {"id", "event_id", "field", "old_value", "new_value"}


def test_the_database_holds_the_same_columns_as_the_models() -> None:
    with connection.cursor() as cursor:
        described = {
            table: {
                column.name
                for column in connection.introspection.get_table_description(cursor, table)
            }
            for table in ("accounts_auditevent", "accounts_auditeventchange")
        }

    assert described == {
        "accounts_auditevent": {field.column for field in AuditEvent._meta.concrete_fields},
        "accounts_auditeventchange": {
            field.column for field in AuditEventChange._meta.concrete_fields
        },
    }


def test_the_identifier_is_an_integer_and_the_target_is_a_uuid() -> None:
    assert _column("accounts_auditevent", "id") == ("bigint", None, "NO")
    assert _column("accounts_auditevent", "target_public_id") == ("uuid", None, "NO")
    assert _column("accounts_auditeventchange", "id") == ("bigint", None, "NO")


def test_a_value_is_bounded_text_of_two_hundred_characters() -> None:
    assert AUDIT_VALUE_MAX_LENGTH == 200
    assert _column("accounts_auditeventchange", "old_value") == ("character varying", 200, "NO")
    assert _column("accounts_auditeventchange", "new_value") == ("character varying", 200, "NO")


def test_an_event_records_action_target_actor_and_time(event: AuditEvent, user: User) -> None:
    stored = AuditEvent.objects.get(pk=event.pk)

    assert stored.action == "updated"
    assert stored.target_type == "registry.country"
    assert stored.target_public_id == TARGET
    assert stored.actor == user
    assert stored.correlation_id == ""
    assert stored.created_at.utcoffset() == timedelta(0)


def test_later_events_have_higher_identifiers(event: AuditEvent, user: User) -> None:
    later = AuditEvent.objects.create(
        action=AuditAction.CREATED,
        target_type=AuditTargetType.LANGUAGE,
        target_public_id=OTHER_TARGET,
        actor=user,
    )

    assert later.pk > event.pk


# --- The actor ----------------------------------------------------------------


def test_the_database_rejects_an_event_without_an_actor() -> None:
    with pytest.raises(IntegrityError, match="actor_id"):
        _insert(INSERT_EVENT, ["created", "registry.country", TARGET, None])


def test_the_database_rejects_an_actor_that_is_no_account(user: User) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(INSERT_EVENT, ["created", "registry.country", TARGET, user.pk + 1000])
            # The reference is checked at the end of the statement or of the
            # transaction, whichever the database was told.
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_an_account_named_as_an_actor_cannot_be_deleted(event: AuditEvent) -> None:
    with pytest.raises(ProtectedError):
        event.actor.delete()

    assert AuditEvent.objects.filter(pk=event.pk).exists()


def test_an_event_that_has_changes_cannot_be_removed_through_the_relation(
    change: AuditEventChange,
) -> None:
    unguarded: models.QuerySet[AuditEvent] = models.QuerySet(model=AuditEvent)

    with pytest.raises(ProtectedError):
        unguarded.filter(pk=change.event.pk).delete()


# --- The closed lists ---------------------------------------------------------


def test_the_actions_are_exactly_these() -> None:
    assert AuditAction.values == ACTIONS


def test_the_target_types_are_exactly_these() -> None:
    assert AuditTargetType.values == TARGET_TYPES


def test_the_fields_are_exactly_these() -> None:
    assert AuditField.values == FIELDS


@pytest.mark.parametrize(
    ("limit", "values"),
    [
        (AuditEvent._meta.get_field("action").max_length, ACTIONS),
        (AuditEvent._meta.get_field("target_type").max_length, TARGET_TYPES),
        (AuditEventChange._meta.get_field("field").max_length, FIELDS),
    ],
    ids=["action", "target type", "field"],
)
def test_every_value_of_the_lists_fits_its_column(limit: int | None, values: list[str]) -> None:
    assert limit is not None
    assert max(len(value) for value in values) <= limit


def test_the_application_states_the_pairs_of_the_decision() -> None:
    stated = {
        (action.value, target_type.value)
        for action, target_types in AUDIT_ACTION_TARGET_TYPES.items()
        for target_type in target_types
    }

    assert stated == ALLOWED_PAIRS
    assert set(AUDIT_ACTION_TARGET_TYPES) == set(AuditAction)


@pytest.mark.parametrize(("action", "target_type"), EVERY_PAIR)
def test_the_database_accepts_exactly_the_pairs_of_the_decision(
    user: User, action: str, target_type: str
) -> None:
    if (action, target_type) in ALLOWED_PAIRS:
        _insert(INSERT_EVENT, [action, target_type, TARGET, user.pk])
        assert AuditEvent.objects.filter(action=action, target_type=target_type).count() == 1
    else:
        with pytest.raises(IntegrityError, match="accounts_auditevent_action_fits_target_type"):
            _insert(INSERT_EVENT, [action, target_type, TARGET, user.pk])
        assert not AuditEvent.objects.exists()


@pytest.mark.parametrize("action", ["deleted", "CREATED", "created ", "", "read"])
def test_the_database_rejects_an_unknown_action(user: User, action: str) -> None:
    with pytest.raises(IntegrityError, match="accounts_auditevent_action"):
        _insert(INSERT_EVENT, [action, "registry.country", TARGET, user.pk])

    assert not AuditEvent.objects.exists()


@pytest.mark.parametrize(
    "target_type", ["country", "registry.source", "accounts.user", "Registry.Country", ""]
)
def test_the_database_rejects_an_unknown_target_type(user: User, target_type: str) -> None:
    with pytest.raises(IntegrityError, match="accounts_auditevent_"):
        _insert(INSERT_EVENT, ["created", target_type, TARGET, user.pk])

    assert not AuditEvent.objects.exists()


@pytest.mark.parametrize("field", ["text", "code", "name", "NAME_EN", "reason", ""])
def test_the_database_rejects_an_unknown_field(event: AuditEvent, field: str) -> None:
    with pytest.raises(IntegrityError, match="accounts_auditeventchange_field_known"):
        _insert(INSERT_CHANGE, [event.pk, field, "TEST a", "TEST b"])

    assert not AuditEventChange.objects.exists()


@pytest.mark.parametrize("field", FIELDS)
def test_the_database_accepts_each_listed_field(event: AuditEvent, field: str) -> None:
    _insert(INSERT_CHANGE, [event.pk, field, "", "TEST value"])

    assert AuditEventChange.objects.get().field == field


def test_the_database_rejects_a_target_that_is_not_a_uuid(user: User) -> None:
    with pytest.raises(DataError):
        _insert(INSERT_EVENT, ["created", "registry.country", "TEST-not-a-uuid", user.pk])
    with pytest.raises(IntegrityError, match="target_public_id"):
        _insert(INSERT_EVENT, ["created", "registry.country", None, user.pk])

    assert not AuditEvent.objects.exists()


# --- The values of a change ---------------------------------------------------


@pytest.mark.parametrize(("old", "new"), [("TEST same", "TEST same"), ("", "")])
def test_the_database_rejects_a_change_whose_values_are_equal(
    event: AuditEvent, old: str, new: str
) -> None:
    with pytest.raises(IntegrityError, match="accounts_auditeventchange_values_differ"):
        _insert(INSERT_CHANGE, [event.pk, "name_en", old, new])

    assert not AuditEventChange.objects.exists()


def test_the_database_rejects_a_field_twice_in_one_event(change: AuditEventChange) -> None:
    with pytest.raises(IntegrityError, match="accounts_auditeventchange_field_once_per_event"):
        _insert(INSERT_CHANGE, [change.event.pk, change.field, "TEST b", "TEST c"])

    assert AuditEventChange.objects.count() == 1


def test_the_same_field_can_change_in_another_event(change: AuditEventChange, user: User) -> None:
    other = AuditEvent.objects.create(
        action=AuditAction.UPDATED,
        target_type=AuditTargetType.COUNTRY,
        target_public_id=TARGET,
        actor=user,
    )

    _insert(INSERT_CHANGE, [other.pk, change.field, "TEST new name", "TEST newer name"])

    assert AuditEventChange.objects.count() == 2


def test_the_database_stores_a_value_of_the_greatest_length_whole(event: AuditEvent) -> None:
    longest = "T" * 200

    _insert(INSERT_CHANGE, [event.pk, "name_en", "", longest])

    assert AuditEventChange.objects.get().new_value == longest


@pytest.mark.parametrize("column", ["old", "new"])
def test_the_database_rejects_a_longer_value_and_shortens_nothing(
    event: AuditEvent, column: str
) -> None:
    too_long = "T" * 201
    old, new = (too_long, "") if column == "old" else ("", too_long)

    with pytest.raises(DataError, match="too long"):
        _insert(INSERT_CHANGE, [event.pk, "name_en", old, new])

    assert not AuditEventChange.objects.exists()


@pytest.mark.parametrize("column", ["event_id", "field", "old_value", "new_value"])
def test_nothing_in_a_change_can_be_null(event: AuditEvent, column: str) -> None:
    values: dict[str, Any] = {
        "event_id": event.pk,
        "field": "name_en",
        "old_value": "TEST a",
        "new_value": "TEST b",
    }
    values[column] = None

    with pytest.raises(IntegrityError, match=column):
        _insert(INSERT_CHANGE, list(values.values()))


def test_the_database_rejects_a_change_of_no_event(event: AuditEvent) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(INSERT_CHANGE, [event.pk + 1000, "name_en", "TEST a", "TEST b"])
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


# --- Append-only: the application guards ---------------------------------------


def test_the_application_refuses_changes_to_an_event_before_the_database_is_asked(
    event: AuditEvent,
) -> None:
    event.action = AuditAction.CREATED

    with pytest.raises(AppendOnlyError):
        event.save()
    with pytest.raises(AppendOnlyError):
        event.delete()
    with pytest.raises(AppendOnlyError):
        AuditEvent.objects.all().update(action="created")
    with pytest.raises(AppendOnlyError):
        AuditEvent.objects.bulk_update([event], ["action"])
    with pytest.raises(AppendOnlyError):
        AuditEvent.objects.all().delete()

    assert AuditEvent.objects.get(pk=event.pk).action == "updated"


def test_the_application_refuses_changes_to_a_change_before_the_database_is_asked(
    change: AuditEventChange,
) -> None:
    change.new_value = "TEST rewritten"

    with pytest.raises(AppendOnlyError):
        change.save()
    with pytest.raises(AppendOnlyError):
        change.delete()
    with pytest.raises(AppendOnlyError):
        AuditEventChange.objects.all().update(new_value="TEST rewritten")
    with pytest.raises(AppendOnlyError):
        AuditEventChange.objects.bulk_update([change], ["new_value"])
    with pytest.raises(AppendOnlyError):
        AuditEventChange.objects.all().delete()
    with pytest.raises(AppendOnlyError):
        change.event.changes.all().delete()

    assert AuditEventChange.objects.get(pk=change.pk).new_value == "TEST new name"


# --- Append-only: the database, reached past every application guard -----------


@pytest.mark.parametrize(
    ("table", "trigger"),
    [
        ("accounts_auditevent", "accounts_auditevent_append_only"),
        ("accounts_auditeventchange", "accounts_auditeventchange_append_only"),
    ],
)
def test_the_trigger_is_installed_and_enabled(table: str, trigger: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgname, tgenabled, pg_get_triggerdef(oid) FROM pg_trigger"
            " WHERE tgrelid = %s::regclass AND NOT tgisinternal",
            [table],
        )
        ((name, enabled, definition),) = cursor.fetchall()

    assert name == trigger
    assert enabled == "O"
    assert "BEFORE DELETE OR UPDATE" in definition
    assert "FOR EACH ROW" in definition


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE accounts_auditevent SET action = 'created' WHERE id = %s",
        "UPDATE accounts_auditevent SET target_type = 'registry.language' WHERE id = %s",
        "UPDATE accounts_auditevent SET target_public_id = gen_random_uuid() WHERE id = %s",
        "UPDATE accounts_auditevent SET actor_id = actor_id WHERE id = %s",
        "UPDATE accounts_auditevent SET correlation_id = 'TEST' WHERE id = %s",
        "UPDATE accounts_auditevent SET created_at = now() WHERE id = %s",
        "DELETE FROM accounts_auditevent WHERE id = %s",
    ],
)
def test_the_database_refuses_update_and_delete_of_an_event_sent_as_sql(
    event: AuditEvent, statement: str
) -> None:
    before = AuditEvent.objects.filter(pk=event.pk).values().get()

    with pytest.raises(IntegrityError, match=EVENT_IS_APPEND_ONLY), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(statement, [event.pk])

    assert AuditEvent.objects.filter(pk=event.pk).values().get() == before


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE accounts_auditeventchange SET field = 'kind' WHERE id = %s",
        "UPDATE accounts_auditeventchange SET old_value = 'TEST rewritten' WHERE id = %s",
        "UPDATE accounts_auditeventchange SET new_value = 'TEST rewritten' WHERE id = %s",
        "UPDATE accounts_auditeventchange SET event_id = event_id WHERE id = %s",
        "DELETE FROM accounts_auditeventchange WHERE id = %s",
    ],
)
def test_the_database_refuses_update_and_delete_of_a_change_sent_as_sql(
    change: AuditEventChange, statement: str
) -> None:
    before = AuditEventChange.objects.filter(pk=change.pk).values().get()

    with pytest.raises(IntegrityError, match=CHANGE_IS_APPEND_ONLY), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(statement, [change.pk])

    assert AuditEventChange.objects.filter(pk=change.pk).values().get() == before


def test_the_database_refuses_changes_through_querysets_without_the_guards(
    change: AuditEventChange,
) -> None:
    events: models.QuerySet[AuditEvent] = models.QuerySet(model=AuditEvent)
    changes: models.QuerySet[AuditEventChange] = models.QuerySet(model=AuditEventChange)

    with pytest.raises(IntegrityError, match=EVENT_IS_APPEND_ONLY), transaction.atomic():
        events.filter(pk=change.event.pk).update(action="created")
    with pytest.raises(IntegrityError, match=CHANGE_IS_APPEND_ONLY), transaction.atomic():
        changes.filter(pk=change.pk).update(new_value="TEST rewritten")
    with pytest.raises(IntegrityError, match=CHANGE_IS_APPEND_ONLY), transaction.atomic():
        changes.filter(pk=change.pk).delete()

    assert AuditEventChange.objects.get(pk=change.pk).new_value == "TEST new name"


def test_the_database_refuses_an_insert_that_would_overwrite_a_change(
    change: AuditEventChange,
) -> None:
    """Writing in bulk can be told to update the row it conflicts with."""
    rewritten = AuditEventChange(
        event=change.event, field=change.field, old_value="TEST a", new_value="TEST rewritten"
    )

    with pytest.raises(IntegrityError, match=CHANGE_IS_APPEND_ONLY), transaction.atomic():
        AuditEventChange.objects.bulk_create(
            [rewritten],
            update_conflicts=True,
            unique_fields=["event", "field"],
            update_fields=["new_value"],
        )

    assert AuditEventChange.objects.get().new_value == "TEST new name"
