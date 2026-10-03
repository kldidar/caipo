"""AuthenticationEvent is small, append-only, and holds no credential."""

import pytest
from django.db import IntegrityError, connection, models, transaction

from caipo.accounts.models import (
    DECISION_EVENT_TYPES,
    USERLESS_EVENT_TYPES,
    AppendOnlyError,
    AuthenticationEvent,
    AuthenticationEventType,
    User,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db]

APPEND_ONLY = "accounts_authenticationevent is append-only"
KEY = "0" * 64
# What was submitted may belong to no account: an email address at sign-in or
# in a reset request, and a reset token (ADR-0013, ADR-0016).
MAY_NAME_NOBODY = ["login_failure", "password_reset_requested", "password_reset_failed"]


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
        "actor_id",
        "identifier_key",
        "source_key",
        "correlation_id",
        "created_at",
    }


def test_the_event_types_are_exactly_these() -> None:
    assert AuthenticationEventType.values == [
        "login_success",
        "login_failure",
        "logout",
        "password_confirmation_failed",
        "mfa_challenge_issued",
        "mfa_enrollment_started",
        "mfa_enrollment_succeeded",
        "mfa_verification_failed",
        "mfa_verification_succeeded",
        "mfa_disabled",
        "mfa_enrollment_approved",
        "mfa_enrollment_rejected",
        "mfa_device_replaced",
        "password_reset_requested",
        "password_reset_succeeded",
        "password_reset_failed",
    ]


def test_every_event_type_fits_its_column() -> None:
    limit = AuthenticationEvent._meta.get_field("event_type").max_length

    assert limit is not None
    assert max(len(value) for value in AuthenticationEventType.values) <= limit


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


def test_the_events_that_may_name_nobody_are_exactly_these() -> None:
    assert list(USERLESS_EVENT_TYPES) == MAY_NAME_NOBODY


@pytest.mark.parametrize(
    "event_type",
    [value for value in AuthenticationEventType.values if value not in MAY_NAME_NOBODY],
)
def test_the_database_rejects_any_other_event_without_a_user(
    event_type: str,
) -> None:
    # A decision names its actor, so that only the missing user is at fault.
    actor = (
        User.objects.create_user("test.actor@caipo.test")
        if event_type in DECISION_EVENT_TYPES
        else None
    )
    with (
        pytest.raises(
            IntegrityError, match="accounts_authenticationevent_user_known_unless_failure"
        ),
        transaction.atomic(),
    ):
        AuthenticationEvent.objects.create(
            event_type=event_type, user=None, actor=actor, identifier_key=KEY, source_key=KEY
        )


@pytest.mark.parametrize("event_type", MAY_NAME_NOBODY)
def test_the_database_accepts_a_failure_or_a_reset_request_without_a_user(event_type: str) -> None:
    AuthenticationEvent.objects.create(
        event_type=event_type, user=None, identifier_key=KEY, source_key=KEY
    )

    assert AuthenticationEvent.objects.get().user is None


@pytest.mark.parametrize(
    "event_type",
    ["password_reset_requested", "password_reset_succeeded", "password_reset_failed"],
)
def test_a_password_reset_event_can_name_its_account_and_never_an_actor(
    user: User, event_type: str
) -> None:
    stored = AuthenticationEvent.objects.create(
        event_type=event_type, user=user, identifier_key=KEY, source_key=KEY
    )

    assert (stored.user, stored.actor) == (user, None)
    assert event_type not in DECISION_EVENT_TYPES


def test_the_database_rejects_an_unknown_event_type(user: User) -> None:
    with (
        pytest.raises(IntegrityError, match="accounts_authenticationevent_event_type_known"),
        transaction.atomic(),
    ):
        AuthenticationEvent.objects.create(
            event_type="password_reset", user=user, identifier_key=KEY, source_key=KEY
        )


# --- Who decided on an enrolment request ---------------------------------------


@pytest.mark.parametrize("event_type", DECISION_EVENT_TYPES)
def test_a_decision_names_the_administrator_who_made_it(user: User, event_type: str) -> None:
    actor = User.objects.create_user("test.actor@caipo.test")

    stored = AuthenticationEvent.objects.create(
        event_type=event_type, user=user, actor=actor, identifier_key=KEY, source_key=KEY
    )

    assert (stored.user, stored.actor) == (user, actor)


@pytest.mark.parametrize("event_type", DECISION_EVENT_TYPES)
def test_the_database_rejects_a_decision_without_an_actor(user: User, event_type: str) -> None:
    with (
        pytest.raises(IntegrityError, match="accounts_authenticationevent_actor_iff_decision"),
        transaction.atomic(),
    ):
        AuthenticationEvent.objects.create(
            event_type=event_type, user=user, identifier_key=KEY, source_key=KEY
        )


@pytest.mark.parametrize("event_type", DECISION_EVENT_TYPES)
def test_the_database_rejects_a_decision_on_ones_own_enrolment(user: User, event_type: str) -> None:
    with (
        pytest.raises(IntegrityError, match="accounts_authenticationevent_actor_is_not_user"),
        transaction.atomic(),
    ):
        AuthenticationEvent.objects.create(
            event_type=event_type, user=user, actor=user, identifier_key=KEY, source_key=KEY
        )


@pytest.mark.parametrize(
    "event_type",
    [value for value in AuthenticationEventType.values if value not in DECISION_EVENT_TYPES],
)
def test_the_database_rejects_an_actor_on_any_other_event(user: User, event_type: str) -> None:
    actor = User.objects.create_user("test.actor@caipo.test")

    with (
        pytest.raises(IntegrityError, match="accounts_authenticationevent_actor_iff_decision"),
        transaction.atomic(),
    ):
        AuthenticationEvent.objects.create(
            event_type=event_type, user=user, actor=actor, identifier_key=KEY, source_key=KEY
        )


def test_an_account_named_as_an_actor_cannot_be_deleted(user: User) -> None:
    actor = User.objects.create_user("test.actor@caipo.test")
    AuthenticationEvent.objects.create(
        event_type=AuthenticationEventType.MFA_ENROLLMENT_APPROVED,
        user=user,
        actor=actor,
        identifier_key=KEY,
        source_key=KEY,
    )

    with pytest.raises(models.ProtectedError):
        actor.delete()
