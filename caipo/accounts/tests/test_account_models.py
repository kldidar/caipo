"""The lifecycle invariants of an account and its records, enforced by PostgreSQL (ADR-0015)."""

from typing import Any

import pytest
from django.db import IntegrityError, connection, models, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from caipo.accounts.models import (
    ADMINISTRATIVE_ACCOUNT_EVENT_TYPES,
    AccountActivation,
    AccountEvent,
    AccountEventType,
    AccountStatus,
    User,
)
from caipo.core.append_only import AppendOnlyError

pytestmark = [pytest.mark.services, pytest.mark.django_db]

APPEND_ONLY = "accounts_accountevent is append-only"
KEY = "0" * 64
EMAIL = "test.account@caipo.test"

PENDING = AccountStatus.PENDING_VERIFICATION
ACTIVE = AccountStatus.ACTIVE
DISABLED = AccountStatus.DISABLED


@pytest.fixture
def user() -> User:
    return User.objects.create_user(EMAIL)


@pytest.fixture
def actor() -> User:
    return User.objects.create_user("test.actor@caipo.test")


# --- The account -----------------------------------------------------------------------


def test_the_states_are_exactly_these_three() -> None:
    assert AccountStatus.values == ["pending_verification", "active", "disabled"]
    limit = User._meta.get_field("status").max_length
    assert limit is not None
    assert max(len(value) for value in AccountStatus.values) <= limit


def test_an_account_is_stored_awaiting_verification_unless_something_says_otherwise() -> None:
    account = User(email=EMAIL)
    account.set_unusable_password()
    account.save()

    stored = User.objects.get()
    assert stored.status == PENDING
    assert stored.is_active is False
    assert (stored.email_verified_at, stored.activated_at) == (None, None)


def test_the_manager_creates_an_active_account_that_says_nothing_of_its_address(user: User) -> None:
    assert user.status == ACTIVE
    assert user.is_active is True
    assert user.activated_at is not None
    assert user.email_verified_at is None


@pytest.mark.parametrize(
    ("status", "active"), [(PENDING, False), (ACTIVE, True), (DISABLED, False), ("", False)]
)
def test_only_an_active_account_is_active_for_django(status: str, active: bool) -> None:
    assert User(email=EMAIL, status=status).is_active is active


def test_whether_an_account_is_active_cannot_be_set_apart_from_its_status() -> None:
    assert "is_active" not in {field.name for field in User._meta.get_fields()}
    with pytest.raises(AttributeError):
        User(email=EMAIL).is_active = True  # type: ignore[misc]  # assigning is the point of the test


@pytest.mark.parametrize("status", ["enabled", "verified", "inactive", "", "ACTIVE", "deleted"])
def test_the_database_rejects_an_unknown_status(user: User, status: str) -> None:
    with pytest.raises(IntegrityError, match="accounts_user_status_"), transaction.atomic():
        User.objects.filter(pk=user.pk).update(status=status)

    assert User.objects.get().status == ACTIVE


@pytest.mark.parametrize(
    "values",
    [
        {"activated_at": timezone.now()},
        {"email_verified_at": timezone.now()},
        {"activated_at": timezone.now(), "email_verified_at": timezone.now()},
    ],
    ids=["activated", "verified", "both"],
)
def test_the_database_rejects_an_account_awaiting_verification_that_was_verified_or_active(
    user: User, values: dict[str, Any]
) -> None:
    with (
        pytest.raises(IntegrityError, match="accounts_user_status_matches_history"),
        transaction.atomic(),
    ):
        User.objects.filter(pk=user.pk).update(
            **({"activated_at": None, "email_verified_at": None} | values), status=PENDING
        )

    assert User.objects.get().status == ACTIVE


def test_the_database_rejects_an_active_account_that_never_became_active(user: User) -> None:
    with (
        pytest.raises(IntegrityError, match="accounts_user_status_matches_history"),
        transaction.atomic(),
    ):
        User.objects.filter(pk=user.pk).update(activated_at=None)

    # So an account that awaits verification cannot be made active by the status alone.
    User.objects.filter(pk=user.pk).update(status=PENDING, activated_at=None)
    with (
        pytest.raises(IntegrityError, match="accounts_user_status_matches_history"),
        transaction.atomic(),
    ):
        User.objects.filter(pk=user.pk).update(status=ACTIVE)

    assert User.objects.get().status == PENDING


@pytest.mark.parametrize("activated", [True, False])
@pytest.mark.parametrize("verified", [True, False])
def test_a_disabled_account_keeps_whatever_history_it_had(
    user: User, activated: bool, verified: bool
) -> None:
    now = timezone.now()

    User.objects.filter(pk=user.pk).update(
        status=DISABLED,
        activated_at=now if activated else None,
        email_verified_at=now if verified else None,
    )

    stored = User.objects.get()
    assert stored.status == DISABLED
    assert (stored.activated_at is not None, stored.email_verified_at is not None) == (
        activated,
        verified,
    )


# --- The activation token ---------------------------------------------------------------


def _activation(user: User, key: str = KEY) -> AccountActivation:
    return AccountActivation.objects.create(user=user, token_key=key, created_at=timezone.now())


def test_an_account_has_at_most_one_activation(user: User) -> None:
    _activation(user)

    with pytest.raises(IntegrityError, match="user_id"), transaction.atomic():
        _activation(user, "1" * 64)

    assert AccountActivation.objects.count() == 1


def test_two_accounts_cannot_share_a_token(user: User, actor: User) -> None:
    _activation(user)

    with pytest.raises(IntegrityError, match="token_key"), transaction.atomic():
        _activation(actor)


def test_an_account_with_an_activation_cannot_be_deleted(user: User) -> None:
    _activation(user)

    with pytest.raises(ProtectedError):
        user.delete()


def test_the_activation_table_holds_exactly_these_columns() -> None:
    # A keyed hash and a time. No token, no address, no password.
    assert {field.column for field in AccountActivation._meta.concrete_fields} == {
        "id",
        "user_id",
        "token_key",
        "created_at",
    }
    assert AccountActivation._meta.get_field("token_key").max_length == 64


# --- Account events -----------------------------------------------------------------------


def _event(user: User | None, event_type: str, actor: User | None = None) -> AccountEvent:
    return AccountEvent.objects.create(
        event_type=event_type, user=user, actor=actor, source_key=KEY
    )


@pytest.fixture
def event(user: User, actor: User) -> AccountEvent:
    return _event(user, AccountEventType.ACCOUNT_CREATED, actor)


def test_the_event_types_are_exactly_these() -> None:
    assert AccountEventType.values == [
        "account_created",
        "verification_sent",
        "verification_succeeded",
        "verification_failed",
        "account_disabled",
        "account_enabled",
    ]
    limit = AccountEvent._meta.get_field("event_type").max_length
    assert limit is not None
    assert max(len(value) for value in AccountEventType.values) <= limit


def test_the_event_table_holds_exactly_these_columns() -> None:
    assert {field.column for field in AccountEvent._meta.concrete_fields} == {
        "id",
        "event_type",
        "user_id",
        "actor_id",
        "source_key",
        "correlation_id",
        "created_at",
    }


def test_the_database_rejects_an_unknown_event_type(user: User) -> None:
    with (
        pytest.raises(IntegrityError, match="accounts_accountevent_event_type_known"),
        transaction.atomic(),
    ):
        _event(user, "password_reset")


@pytest.mark.parametrize(
    "event_type",
    [value for value in AccountEventType.values if value != "verification_failed"],
)
def test_the_database_rejects_anything_but_a_refused_verification_without_a_user(
    actor: User, event_type: str
) -> None:
    named = actor if event_type in ADMINISTRATIVE_ACCOUNT_EVENT_TYPES else None

    with (
        pytest.raises(IntegrityError, match="accounts_accountevent_user_known_unless_failure"),
        transaction.atomic(),
    ):
        _event(None, event_type, named)


def test_the_database_accepts_a_refused_verification_with_or_without_a_user(user: User) -> None:
    _event(None, AccountEventType.VERIFICATION_FAILED)
    _event(user, AccountEventType.VERIFICATION_FAILED)

    assert AccountEvent.objects.count() == 2


@pytest.mark.parametrize("event_type", ADMINISTRATIVE_ACCOUNT_EVENT_TYPES)
def test_what_an_administrator_does_names_the_administrator(
    user: User, actor: User, event_type: str
) -> None:
    assert _event(user, event_type, actor).actor == actor

    with (
        pytest.raises(IntegrityError, match="accounts_accountevent_actor_iff_administrative"),
        transaction.atomic(),
    ):
        _event(user, event_type)


@pytest.mark.parametrize("event_type", ["verification_succeeded", "verification_failed"])
def test_the_database_rejects_an_actor_on_what_the_owner_does(
    user: User, actor: User, event_type: str
) -> None:
    with (
        pytest.raises(IntegrityError, match="accounts_accountevent_actor_iff_administrative"),
        transaction.atomic(),
    ):
        _event(user, event_type, actor)


@pytest.mark.parametrize("event_type", ["account_created", "verification_sent", "account_enabled"])
def test_nobody_creates_invites_or_enables_their_own_account(user: User, event_type: str) -> None:
    with (
        pytest.raises(
            IntegrityError, match="accounts_accountevent_actor_is_not_user_unless_disabling"
        ),
        transaction.atomic(),
    ):
        _event(user, event_type, user)


def test_disabling_ones_own_account_can_be_recorded(user: User) -> None:
    stored = _event(user, AccountEventType.ACCOUNT_DISABLED, user)

    assert stored.actor == stored.user == user


def test_an_account_named_in_an_event_cannot_be_deleted(event: AccountEvent) -> None:
    assert event.user is not None and event.actor is not None
    for account in (event.user, event.actor):
        with pytest.raises(ProtectedError):
            account.delete()


def test_the_trigger_is_installed_and_enabled() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgname, tgenabled, pg_get_triggerdef(oid) FROM pg_trigger"
            " WHERE tgrelid = 'accounts_accountevent'::regclass AND NOT tgisinternal"
        )
        ((name, enabled, definition),) = cursor.fetchall()

    assert name == "accounts_accountevent_append_only"
    assert enabled == "O"
    assert "BEFORE DELETE OR UPDATE" in definition
    assert "FOR EACH ROW" in definition


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE accounts_accountevent SET event_type = 'account_enabled' WHERE id = %s",
        "UPDATE accounts_accountevent SET user_id = NULL WHERE id = %s",
        "UPDATE accounts_accountevent SET actor_id = user_id WHERE id = %s",
        "UPDATE accounts_accountevent SET created_at = now() WHERE id = %s",
        "DELETE FROM accounts_accountevent WHERE id = %s",
    ],
)
def test_the_database_refuses_update_and_delete_sent_as_sql(
    event: AccountEvent, statement: str
) -> None:
    with pytest.raises(IntegrityError, match=APPEND_ONLY), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(statement, [event.pk])

    stored = AccountEvent.objects.get(pk=event.pk)
    assert (stored.event_type, stored.user, stored.actor, stored.created_at) == (
        "account_created",
        event.user,
        event.actor,
        event.created_at,
    )


def test_the_database_refuses_changes_through_a_queryset_without_the_guards(
    event: AccountEvent,
) -> None:
    unguarded: models.QuerySet[AccountEvent] = models.QuerySet(model=AccountEvent)

    with pytest.raises(IntegrityError, match=APPEND_ONLY), transaction.atomic():
        unguarded.filter(pk=event.pk).update(event_type="account_enabled")
    with pytest.raises(IntegrityError, match=APPEND_ONLY), transaction.atomic():
        unguarded.filter(pk=event.pk).delete()

    assert AccountEvent.objects.filter(pk=event.pk).exists()


def test_the_application_refuses_changes_before_the_database_is_asked(event: AccountEvent) -> None:
    event.event_type = AccountEventType.ACCOUNT_ENABLED

    with pytest.raises(AppendOnlyError):
        event.save()
    with pytest.raises(AppendOnlyError):
        event.delete()
    with pytest.raises(AppendOnlyError):
        AccountEvent.objects.all().update(event_type="account_enabled")
    with pytest.raises(AppendOnlyError):
        AccountEvent.objects.all().delete()

    assert AccountEvent.objects.get(pk=event.pk).event_type == "account_created"
