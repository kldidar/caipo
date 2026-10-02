"""RoleEvent is append-only, in the application and in the database."""

from datetime import timedelta

import pytest
from django.db import IntegrityError, connection, models, transaction
from django.db.models import ProtectedError

from caipo.accounts.models import AppendOnlyError, RoleEvent, RoleEventType, User
from caipo.accounts.selectors import Role
from caipo.accounts.tests.fixtures import UserFactory

pytestmark = [pytest.mark.services, pytest.mark.django_db]

APPEND_ONLY = "accounts_roleevent is append-only"


@pytest.fixture
def event(user_with_roles: UserFactory) -> RoleEvent:
    return RoleEvent.objects.get(user=user_with_roles(Role.READER))


def _stored(event: RoleEvent) -> tuple[object, ...]:
    """Return the event as the database holds it now."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT user_id, role, event_type, actor_id, reason, created_at"
            " FROM accounts_roleevent WHERE id = %s",
            [event.pk],
        )
        row: tuple[object, ...] = cursor.fetchone()
    return row


def test_an_event_records_user_role_type_actor_reason_and_time(event: RoleEvent) -> None:
    assert event.user.email.startswith("test.user")
    assert event.role == Role.READER
    assert event.event_type == RoleEventType.GRANTED
    assert event.actor is not None
    assert event.actor.email == "test.seed@caipo.test"
    assert event.reason == "TEST fixture"
    assert event.created_at.utcoffset() == timedelta(0)


# --- Application guards ------------------------------------------------------


def test_an_event_cannot_be_saved_again(event: RoleEvent) -> None:
    before = _stored(event)
    event.role = Role.ADMINISTRATOR

    with pytest.raises(AppendOnlyError):
        event.save()

    assert _stored(event) == before


def test_an_event_cannot_be_deleted(event: RoleEvent) -> None:
    with pytest.raises(AppendOnlyError):
        event.delete()

    assert RoleEvent.objects.filter(pk=event.pk).exists()


def test_events_cannot_be_updated_in_bulk(event: RoleEvent) -> None:
    before = _stored(event)

    with pytest.raises(AppendOnlyError):
        RoleEvent.objects.filter(pk=event.pk).update(role=Role.ADMINISTRATOR)
    with pytest.raises(AppendOnlyError):
        RoleEvent.objects.bulk_update([event], ["role"])

    assert _stored(event) == before


def test_events_cannot_be_deleted_in_bulk(event: RoleEvent) -> None:
    with pytest.raises(AppendOnlyError):
        RoleEvent.objects.all().delete()

    assert RoleEvent.objects.filter(pk=event.pk).exists()


def test_a_user_with_role_events_cannot_be_deleted(event: RoleEvent) -> None:
    with pytest.raises(ProtectedError):
        event.user.delete()
    assert event.actor is not None
    with pytest.raises(ProtectedError):
        event.actor.delete()

    assert RoleEvent.objects.filter(pk=event.pk).exists()


# --- Database protection, reached past every application guard ----------------


def test_the_trigger_is_installed_and_enabled() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgname, tgenabled, pg_get_triggerdef(oid) FROM pg_trigger"
            " WHERE tgrelid = 'accounts_roleevent'::regclass AND NOT tgisinternal"
        )
        triggers = cursor.fetchall()

    ((name, enabled, definition),) = triggers
    assert name == "accounts_roleevent_append_only"
    assert enabled == "O", "the trigger must fire for ordinary sessions"
    assert "BEFORE DELETE OR UPDATE" in definition
    assert "FOR EACH ROW" in definition


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE accounts_roleevent SET role = 'administrator' WHERE id = %s",
        "UPDATE accounts_roleevent SET event_type = 'revoked' WHERE id = %s",
        "UPDATE accounts_roleevent SET actor_id = user_id WHERE id = %s",
        "UPDATE accounts_roleevent SET reason = 'TEST rewritten' WHERE id = %s",
        "UPDATE accounts_roleevent SET created_at = now() WHERE id = %s",
        # Even a change that changes nothing is a rewrite.
        "UPDATE accounts_roleevent SET role = role WHERE id = %s",
    ],
)
def test_the_database_refuses_update_sent_as_sql(event: RoleEvent, statement: str) -> None:
    before = _stored(event)

    with pytest.raises(IntegrityError, match=APPEND_ONLY), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(statement, [event.pk])

    assert _stored(event) == before


def test_the_database_refuses_delete_sent_as_sql(event: RoleEvent) -> None:
    with pytest.raises(IntegrityError, match=APPEND_ONLY), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM accounts_roleevent WHERE id = %s", [event.pk])
    with pytest.raises(IntegrityError, match=APPEND_ONLY), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM accounts_roleevent")

    assert RoleEvent.objects.filter(pk=event.pk).exists()


def test_the_database_refuses_update_through_a_queryset_without_the_guards(
    event: RoleEvent,
) -> None:
    before = _stored(event)
    unguarded: models.QuerySet[RoleEvent] = models.QuerySet(model=RoleEvent)

    with pytest.raises(IntegrityError, match=APPEND_ONLY), transaction.atomic():
        unguarded.filter(pk=event.pk).update(role=Role.ADMINISTRATOR)

    assert _stored(event) == before


def test_the_database_refuses_delete_through_a_queryset_without_the_guards(
    event: RoleEvent,
) -> None:
    unguarded: models.QuerySet[RoleEvent] = models.QuerySet(model=RoleEvent)

    with pytest.raises(IntegrityError, match=APPEND_ONLY), transaction.atomic():
        unguarded.filter(pk=event.pk).delete()

    assert RoleEvent.objects.filter(pk=event.pk).exists()


def test_the_database_refuses_an_update_that_bypasses_model_save(event: RoleEvent) -> None:
    before = _stored(event)
    event.reason = "TEST rewritten"

    with pytest.raises(IntegrityError, match=APPEND_ONLY), transaction.atomic():
        models.Model.save(event, force_update=True)

    assert _stored(event) == before


def test_the_database_still_accepts_new_events(event: RoleEvent) -> None:
    RoleEvent.objects.create(
        user=event.user,
        role=Role.READER,
        event_type=RoleEventType.REVOKED,
        actor=event.actor,
        reason="TEST fixture",
    )

    assert RoleEvent.objects.filter(user=event.user).count() == 2


# --- Database constraints on what an event may say ----------------------------


def _insert(user: User, actor: User, **overrides: str) -> None:
    values = {"role": Role.READER, "event_type": RoleEventType.GRANTED, "reason": "TEST fixture"}
    with transaction.atomic():
        RoleEvent.objects.create(user=user, actor=actor, **(values | overrides))


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"role": "superuser"}, "accounts_roleevent_role_known"),
        ({"role": "ADMINISTRATOR"}, "accounts_roleevent_role_known"),
        ({"role": ""}, "accounts_roleevent_role_known"),
        ({"event_type": "deleted"}, "accounts_roleevent_event_type_known"),
        ({"reason": ""}, "accounts_roleevent_reason_given"),
    ],
)
def test_the_database_rejects_an_invalid_event(
    user_with_roles: UserFactory, overrides: dict[str, str], constraint: str
) -> None:
    user, actor = user_with_roles(), user_with_roles()

    with pytest.raises(IntegrityError, match=constraint):
        _insert(user, actor, **overrides)

    assert not RoleEvent.objects.filter(user=user).exists()


def test_the_database_rejects_an_event_in_which_a_user_changes_their_own_roles(
    user_with_roles: UserFactory,
) -> None:
    user = user_with_roles()

    with pytest.raises(IntegrityError, match="accounts_roleevent_actor_is_not_user"):
        _insert(user, user)

    assert not RoleEvent.objects.filter(user=user).exists()


def _insert_without_actor(user: User, role: str, event_type: str) -> None:
    with transaction.atomic():
        RoleEvent.objects.create(
            user=user, role=role, event_type=event_type, actor=None, reason="TEST fixture"
        )


@pytest.mark.parametrize(
    ("role", "event_type"),
    [
        (Role.READER, RoleEventType.GRANTED),
        (Role.RESEARCHER, RoleEventType.GRANTED),
        (Role.REVIEWER, RoleEventType.GRANTED),
        (Role.ADMINISTRATOR, RoleEventType.REVOKED),
        (Role.READER, RoleEventType.REVOKED),
    ],
)
def test_the_database_rejects_an_event_without_an_actor_unless_it_is_the_bootstrap(
    user_with_roles: UserFactory, role: str, event_type: str
) -> None:
    user = user_with_roles()

    with pytest.raises(IntegrityError, match="accounts_roleevent_no_actor_only_for_bootstrap"):
        _insert_without_actor(user, role, event_type)

    assert not RoleEvent.objects.filter(user=user).exists()


def test_the_database_accepts_one_bootstrap_event_and_never_a_second(
    user_with_roles: UserFactory,
) -> None:
    first, second = user_with_roles(), user_with_roles()

    _insert_without_actor(first, Role.ADMINISTRATOR, RoleEventType.GRANTED)
    with pytest.raises(IntegrityError, match="accounts_roleevent_single_bootstrap"):
        _insert_without_actor(second, Role.ADMINISTRATOR, RoleEventType.GRANTED)
    with pytest.raises(IntegrityError, match="accounts_roleevent_single_bootstrap"):
        _insert_without_actor(first, Role.ADMINISTRATOR, RoleEventType.GRANTED)

    assert RoleEvent.objects.filter(actor__isnull=True).count() == 1
