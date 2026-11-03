"""Migration 0013, which allows registration on the site, applied, reversed, and applied
again (ADR-0021).

Each test takes the schema back to migration 0012 where it needs to, and always
returns it to the latest migration, whatever happens in between.
"""

from collections.abc import Iterator

import pytest
from django.db import IntegrityError, connection
from django.db.migrations.executor import MigrationExecutor

from caipo.accounts.models import RoleEvent, RoleEventType, User
from caipo.accounts.selectors import Role

pytestmark = [pytest.mark.services, pytest.mark.django_db(transaction=True)]

BEFORE = ("accounts", "0012_audit_research_targets")
AFTER = ("accounts", "0013_self_registration")

# Visibly synthetic.
EMAIL = "test.registrant@caipo.test"

CHECKS_AFTER = {
    "accounts_accountevent_event_type_known",
    "accounts_roleevent_no_actor_only_bootstrap_or_registration",
}
INDEXES_AFTER = {"accounts_roleevent_single_bootstrap", "accounts_roleevent_single_registration"}


def _migrate(target: tuple[str, str]) -> None:
    MigrationExecutor(connection).migrate([target])


def _migrate_to_latest() -> None:
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def _checks() -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT conname FROM pg_constraint WHERE contype = 'c'"
            " AND conrelid::regclass::text IN ('accounts_roleevent', 'accounts_accountevent')"
        )
        return {str(name) for (name,) in cursor.fetchall()}


def _partial_indexes() -> dict[str, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'accounts_roleevent'"
        )
        return {str(name): str(definition) for name, definition in cursor.fetchall()}


@pytest.fixture
def earlier() -> Iterator[None]:
    """Take the schema back to migration 0012, and always return it to the latest."""
    try:
        _migrate(BEFORE)
        yield
    finally:
        _migrate_to_latest()


def test_applied_it_holds_the_checks_and_the_two_partial_unique_indexes() -> None:
    checks, indexes = _checks(), _partial_indexes()

    assert checks >= CHECKS_AFTER
    assert "accounts_roleevent_no_actor_only_for_bootstrap" not in checks
    assert INDEXES_AFTER <= set(indexes)
    assert "'administrator'" in indexes["accounts_roleevent_single_bootstrap"]
    assert "(user_id)" in indexes["accounts_roleevent_single_registration"]


@pytest.mark.usefixtures("earlier")
def test_reversed_before_anybody_registered_it_restores_the_earlier_checks() -> None:
    checks = _checks()

    assert "accounts_roleevent_no_actor_only_for_bootstrap" in checks
    assert "accounts_roleevent_no_actor_only_bootstrap_or_registration" not in checks
    assert "accounts_roleevent_single_registration" not in _partial_indexes()

    _migrate(AFTER)

    assert _checks() >= CHECKS_AFTER


def test_reversing_it_fails_once_an_account_has_registered() -> None:
    user = User.objects.create_user(EMAIL)
    RoleEvent.objects.create(
        user=user,
        role=Role.READER,
        event_type=RoleEventType.GRANTED,
        actor=None,
        reason="TEST registration",
    )

    try:
        with pytest.raises(IntegrityError, match="accounts_roleevent_no_actor_only_for_bootstrap"):
            _migrate(BEFORE)
    finally:
        _migrate_to_latest()

    assert AFTER in MigrationExecutor(connection).loader.applied_migrations
