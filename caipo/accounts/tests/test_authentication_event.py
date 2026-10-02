"""AuthenticationEvent is small, append-only, and holds no credential."""

import pytest
from django.db import IntegrityError, connection, models, transaction

from caipo.accounts.models import (
    AppendOnlyError,
    AuthenticationEvent,
    AuthenticationEventType,
    User,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db]

APPEND_ONLY = "accounts_authenticationevent is append-only"
KEY = "0" * 64


@pytest.fixture
def user() -> User:
    return User.objects.create_user("test.reader@caipo.test")


@pytest.fixture
def event(user: User) -> AuthenticationEvent:
    return AuthenticationEvent.objects.create(
        event_type=AuthenticationEventType.LOGIN_SUCCESS,
        user=user,
        identifier_key=KEY,
        source_key=KEY,
    )


def test_the_table_holds_exactly_these_columns() -> None:
    columns = {field.column for field in AuthenticationEvent._meta.concrete_fields}

    assert columns == {
        "id",
        "event_type",
        "user_id",
        "identifier_key",
        "source_key",
        "correlation_id",
        "created_at",
    }


def test_the_event_types_are_exactly_these() -> None:
    assert AuthenticationEventType.values == ["login_success", "login_failure", "logout"]


def test_the_trigger_is_installed_and_enabled() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgname, tgenabled, pg_get_triggerdef(oid) FROM pg_trigger"
            " WHERE tgrelid = 'accounts_authenticationevent'::regclass AND NOT tgisinternal"
        )
        ((name, enabled, definition),) = cursor.fetchall()

    assert name == "accounts_authenticationevent_append_only"
    assert enabled == "O"
    assert "BEFORE DELETE OR UPDATE" in definition
    assert "FOR EACH ROW" in definition


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE accounts_authenticationevent SET event_type = 'logout' WHERE id = %s",
        "UPDATE accounts_authenticationevent SET user_id = NULL WHERE id = %s",
        "UPDATE accounts_authenticationevent SET created_at = now() WHERE id = %s",
        "DELETE FROM accounts_authenticationevent WHERE id = %s",
    ],
)
def test_the_database_refuses_update_and_delete_sent_as_sql(
    event: AuthenticationEvent, statement: str
) -> None:
    with pytest.raises(IntegrityError, match=APPEND_ONLY), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(statement, [event.pk])

    stored = AuthenticationEvent.objects.get(pk=event.pk)
    assert (stored.event_type, stored.user, stored.created_at) == (
        "login_success",
        event.user,
        event.created_at,
    )


def test_the_database_refuses_changes_through_a_queryset_without_the_guards(
    event: AuthenticationEvent,
) -> None:
    unguarded: models.QuerySet[AuthenticationEvent] = models.QuerySet(model=AuthenticationEvent)

    with pytest.raises(IntegrityError, match=APPEND_ONLY), transaction.atomic():
        unguarded.filter(pk=event.pk).update(event_type="logout")
    with pytest.raises(IntegrityError, match=APPEND_ONLY), transaction.atomic():
        unguarded.filter(pk=event.pk).delete()

    assert AuthenticationEvent.objects.filter(pk=event.pk).exists()


def test_the_application_refuses_changes_before_the_database_is_asked(
    event: AuthenticationEvent,
) -> None:
    event.event_type = AuthenticationEventType.LOGOUT

    with pytest.raises(AppendOnlyError):
        event.save()
    with pytest.raises(AppendOnlyError):
        event.delete()
    with pytest.raises(AppendOnlyError):
        AuthenticationEvent.objects.all().update(event_type="logout")
    with pytest.raises(AppendOnlyError):
        AuthenticationEvent.objects.all().delete()

    assert AuthenticationEvent.objects.get(pk=event.pk).event_type == "login_success"


@pytest.mark.parametrize("event_type", ["login_success", "logout"])
def test_the_database_rejects_a_success_or_sign_out_without_a_user(event_type: str) -> None:
    with (
        pytest.raises(
            IntegrityError, match="accounts_authenticationevent_user_known_unless_failure"
        ),
        transaction.atomic(),
    ):
        AuthenticationEvent.objects.create(
            event_type=event_type, user=None, identifier_key=KEY, source_key=KEY
        )


def test_the_database_accepts_a_failure_without_a_user() -> None:
    AuthenticationEvent.objects.create(
        event_type=AuthenticationEventType.LOGIN_FAILURE,
        user=None,
        identifier_key=KEY,
        source_key=KEY,
    )

    assert AuthenticationEvent.objects.get().user is None


def test_the_database_rejects_an_unknown_event_type(user: User) -> None:
    with (
        pytest.raises(IntegrityError, match="accounts_authenticationevent_event_type_known"),
        transaction.atomic(),
    ):
        AuthenticationEvent.objects.create(
            event_type="password_reset", user=user, identifier_key=KEY, source_key=KEY
        )
