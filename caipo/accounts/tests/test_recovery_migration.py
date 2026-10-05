"""Migration 0008 applied to a database that already holds accounts and events (ADR-0017).

Each test takes the schema back to migration 0007, and always returns it to
the latest migration, whatever happens in between.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from django.apps.registry import Apps
from django.db import IntegrityError, connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from django.utils.crypto import salted_hmac

from caipo.accounts.models import AuthenticationEvent, MfaRecoveryRequest, User

pytestmark = [pytest.mark.services, pytest.mark.django_db(transaction=True)]

BEFORE = ("accounts", "0007_password_reset")
AFTER = ("accounts", "0008_account_recovery_foundation")

EMAIL = "test.account@caipo.test"
# Visibly synthetic: what stands in the password column.
STORED = "TEST$not-a-real-password-hash"
KEY = "0" * 64
DJANGO_SALT = "django.contrib.auth.models.AbstractBaseUser.get_session_auth_hash"
REPLACED_CONSTRAINTS = {
    "accounts_authenticationevent_event_type_known",
    "accounts_authenticationevent_user_known_unless_failure",
    "accounts_authenticationevent_actor_iff_decision",
}
NEW_CONSTRAINTS = {
    "accounts_authenticationevent_action_iff_break_glass",
    "accounts_authenticationevent_break_glass_has_no_source",
}


def _migrate(target: tuple[str, str]) -> Apps:
    executor = MigrationExecutor(connection)
    executor.migrate([target])
    return MigrationExecutor(connection).loader.project_state([target]).apps


def _applied() -> set[tuple[str, str]]:
    return set(MigrationExecutor(connection).loader.applied_migrations)


def _columns(table: str) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = current_schema() AND table_name = %s",
            [table],
        )
        return {name for (name,) in cursor.fetchall()}


def _tables() -> set[str]:
    return set(connection.introspection.table_names())


def _checks(table: str) -> dict[str, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint"
            " WHERE conrelid = %s::regclass AND contype = 'c'",
            [table],
        )
        return dict(cursor.fetchall())


def _triggers(table: str) -> list[tuple[str, str]]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgname, tgenabled FROM pg_trigger"
            " WHERE tgrelid = %s::regclass AND NOT tgisinternal",
            [table],
        )
        return [(str(name), str(enabled)) for name, enabled in cursor.fetchall()]


def _event_rows() -> list[tuple[Any, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, event_type, user_id, actor_id, identifier_key, source_key,"
            " correlation_id, created_at FROM accounts_authenticationevent ORDER BY id"
        )
        return list(cursor.fetchall())


@pytest.fixture
def earlier() -> Iterator[Apps]:
    """Yield the models of migration 0007, on a schema taken back to it."""
    try:
        yield _migrate(BEFORE)
    finally:
        _migrate(AFTER)


def _earlier_account(earlier: Apps, email: str = EMAIL) -> Any:
    return earlier.get_model("accounts", "User").objects.create(
        email=email, password=STORED, status="active", activated_at=timezone.now()
    )


def _earlier_events(earlier: Apps, user: Any, actor: Any) -> None:
    events = earlier.get_model("accounts", "AuthenticationEvent").objects
    events.create(event_type="login_success", user=user, identifier_key=KEY, source_key=KEY)
    events.create(event_type="login_failure", user=None, identifier_key=KEY, source_key=KEY)
    events.create(
        event_type="mfa_enrollment_approved",
        user=user,
        actor=actor,
        identifier_key=KEY,
        source_key=KEY,
    )
    events.create(event_type="password_reset_failed", user=None, identifier_key="", source_key=KEY)


def test_the_earlier_schema_has_none_of_what_the_migration_adds(earlier: Apps) -> None:
    assert AFTER not in _applied()
    assert "accounts_mfarecoveryrequest" not in _tables()
    assert "session_epoch" not in _columns("accounts_user")
    assert "break_glass_action" not in _columns("accounts_authenticationevent")
    assert NEW_CONSTRAINTS.isdisjoint(_checks("accounts_authenticationevent"))


def test_applying_it_gives_every_existing_account_epoch_zero_and_changes_nothing_else(
    earlier: Apps,
) -> None:
    account = _earlier_account(earlier)
    before = earlier.get_model("accounts", "User").objects.filter(pk=account.pk).values().get()

    _migrate(AFTER)

    after: dict[str, Any] = dict(User.objects.filter(pk=account.pk).values().get())
    assert after.pop("session_epoch") == 0
    assert after == before


def test_a_session_established_before_it_is_recognised_after_it(earlier: Apps) -> None:
    account = _earlier_account(earlier)
    # What Django stored in the session of this account before the migration.
    held_by_the_session = salted_hmac(DJANGO_SALT, STORED, algorithm="sha256").hexdigest()

    _migrate(AFTER)

    assert User.objects.get(pk=account.pk).get_session_auth_hash() == held_by_the_session


def test_applying_it_touches_no_existing_event(earlier: Apps) -> None:
    user = _earlier_account(earlier)
    actor = _earlier_account(earlier, "test.actor@caipo.test")
    _earlier_events(earlier, user, actor)
    before = _event_rows()
    assert len(before) == 4

    _migrate(AFTER)

    assert _event_rows() == before
    assert set(AuthenticationEvent.objects.values_list("break_glass_action", flat=True)) == {""}


def test_applying_it_leaves_the_append_only_trigger_and_the_other_constraints_in_place(
    earlier: Apps,
) -> None:
    trigger_before = _triggers("accounts_authenticationevent")
    checks_before = _checks("accounts_authenticationevent")

    _migrate(AFTER)

    checks_after = _checks("accounts_authenticationevent")
    assert _triggers("accounts_authenticationevent") == trigger_before
    assert trigger_before == [("accounts_authenticationevent_append_only", "O")]
    assert set(checks_after) == set(checks_before) | NEW_CONSTRAINTS
    changed = {name for name in checks_before if checks_before[name] != checks_after[name]}
    assert changed == REPLACED_CONSTRAINTS


def test_it_is_reversible_and_can_be_applied_again(earlier: Apps) -> None:
    user = _earlier_account(earlier)
    actor = _earlier_account(earlier, "test.actor@caipo.test")
    _earlier_events(earlier, user, actor)
    events = _event_rows()
    checks = _checks("accounts_authenticationevent")
    _migrate(AFTER)
    MfaRecoveryRequest.objects.create(user_id=user.pk, created_at=timezone.now())

    _migrate(BEFORE)

    assert AFTER not in _applied()
    assert "accounts_mfarecoveryrequest" not in _tables()
    assert "session_epoch" not in _columns("accounts_user")
    assert "break_glass_action" not in _columns("accounts_authenticationevent")
    assert _checks("accounts_authenticationevent") == checks
    assert _event_rows() == events
    assert _triggers("accounts_authenticationevent") == [
        ("accounts_authenticationevent_append_only", "O")
    ]

    _migrate(AFTER)

    assert AFTER in _applied()
    assert _event_rows() == events
    assert not MfaRecoveryRequest.objects.exists()
    assert User.objects.get(pk=user.pk).session_epoch == 0


@pytest.mark.parametrize(
    ("event_type", "action", "decided"),
    [
        ("mfa_recovery_requested", "", False),
        ("mfa_recovery_failed", "", False),
        ("mfa_recovery_authorized", "", True),
        ("mfa_recovery_break_glass", "revoke_device", False),
    ],
)
def test_it_cannot_be_reversed_once_a_recovery_event_exists(
    event_type: str, action: str, decided: bool
) -> None:
    user = User.objects.create_user(EMAIL)
    actor = User.objects.create_user("test.actor@caipo.test") if decided else None
    User.objects.filter(pk=user.pk).update(session_epoch=1)
    AuthenticationEvent.objects.create(
        event_type=event_type,
        user=user,
        actor=actor,
        identifier_key=KEY,
        source_key="" if event_type == "mfa_recovery_break_glass" else KEY,
        break_glass_action=action,
    )
    request = MfaRecoveryRequest.objects.create(user=user, created_at=timezone.now())

    try:
        with pytest.raises(IntegrityError, match="accounts_authenticationevent"):
            _migrate(BEFORE)

        # Refused as a whole: the schema and everything in it are as they were.
        assert AFTER in _applied()
        assert "break_glass_action" in _columns("accounts_authenticationevent")
        assert set(_checks("accounts_authenticationevent")) >= NEW_CONSTRAINTS
        assert User.objects.get(pk=user.pk).session_epoch == 1
        assert MfaRecoveryRequest.objects.get().pk == request.pk
        stored = AuthenticationEvent.objects.get()
        assert (stored.event_type, stored.break_glass_action) == (event_type, action)
    finally:
        _migrate(AFTER)
