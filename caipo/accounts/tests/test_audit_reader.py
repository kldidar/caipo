"""Reading the general audit record (ADR-0018, "a later increment, with its own permission")."""

import uuid

import pytest
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext

from caipo.accounts import selectors
from caipo.accounts.authorization import ROLE_PERMISSIONS
from caipo.accounts.selectors import (
    AuditAction,
    AuditField,
    AuditTargetType,
    AuthenticationContext,
    Permission,
    Role,
)
from caipo.accounts.services import AuditChange, record_audit_event
from caipo.accounts.tests.fixtures import UserFactory, signed_in, verified
from caipo.core.correlation import correlation_scope

pytestmark = [pytest.mark.services, pytest.mark.django_db]

# Visibly synthetic identifiers of records that do not exist.
FIRST = uuid.UUID("00000000-0000-4000-8000-000000000001")
SECOND = uuid.UUID("00000000-0000-4000-8000-000000000002")
RENAMED = AuditChange(AuditField.NAME_EN, "TEST a", "TEST b")


def _write(
    actor: AuthenticationContext,
    action: AuditAction,
    target_type: AuditTargetType,
    target: uuid.UUID,
    *changes: AuditChange,
) -> None:
    with transaction.atomic():
        record_audit_event(
            actor=actor,
            action=action,
            target_type=target_type,
            target_public_id=target,
            changes=changes,
        )


@pytest.fixture
def administrator(user_with_roles: UserFactory) -> AuthenticationContext:
    return verified(user_with_roles(Role.ADMINISTRATOR))


@pytest.fixture
def writer(user_with_roles: UserFactory) -> AuthenticationContext:
    return signed_in(user_with_roles(Role.RESEARCHER))


def test_every_change_is_read_latest_first_with_its_fields_and_author(
    administrator: AuthenticationContext, writer: AuthenticationContext
) -> None:
    with correlation_scope() as correlation_id:
        _write(writer, AuditAction.CREATED, AuditTargetType.COUNTRY, FIRST)
    _write(
        writer,
        AuditAction.UPDATED,
        AuditTargetType.INSTITUTION,
        SECOND,
        AuditChange(AuditField.NAME_EN, "TEST old", "TEST new"),
        AuditChange(AuditField.VALID_TO, None, "TEST 2020"),
    )

    page = selectors.audit_record(administrator)

    latest, earliest = page.entries
    assert (latest.action_label, latest.target_label, latest.target_public_id) == (
        "Updated",
        "Institution",
        SECOND,
    )
    assert latest.actor_email == writer.user.email
    assert [(c.field_label, c.old_value, c.new_value) for c in latest.changes] == [
        ("English name", "TEST old", "TEST new"),
        ("Valid to", "", "TEST 2020"),
    ]
    assert (earliest.action_label, earliest.target_label, earliest.changes) == (
        "Created",
        "Country",
        (),
    )
    assert earliest.correlation_id == correlation_id
    assert (page.number, page.has_previous, page.has_next, page.target_type) == (
        1,
        False,
        False,
        None,
    )


def test_the_record_is_narrowed_to_one_kind(
    administrator: AuthenticationContext, writer: AuthenticationContext
) -> None:
    _write(writer, AuditAction.CREATED, AuditTargetType.COUNTRY, FIRST)
    _write(writer, AuditAction.CREATED, AuditTargetType.POLICY, SECOND)

    page = selectors.audit_record(administrator, target_type=AuditTargetType.POLICY)

    assert [entry.target_public_id for entry in page.entries] == [SECOND]
    assert page.target_type == AuditTargetType.POLICY


@pytest.mark.parametrize("kind", ["", "unknown", "registry.country' OR 1=1", "COUNTRY"])
def test_a_kind_that_is_not_a_record_type_narrows_nothing(
    administrator: AuthenticationContext, writer: AuthenticationContext, kind: str
) -> None:
    _write(writer, AuditAction.CREATED, AuditTargetType.COUNTRY, FIRST)
    _write(writer, AuditAction.CREATED, AuditTargetType.POLICY, SECOND)

    page = selectors.audit_record(administrator, target_type=kind)

    assert len(page.entries) == 2
    assert page.target_type is None


def test_the_record_is_read_page_by_page(
    administrator: AuthenticationContext,
    writer: AuthenticationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(selectors, "AUDIT_RECORD_PAGE_SIZE", 2)
    targets = [uuid.UUID(int=n) for n in range(1, 6)]
    for target in targets:
        _write(writer, AuditAction.CREATED, AuditTargetType.LANGUAGE, target)

    first = selectors.audit_record(administrator)
    last = selectors.audit_record(administrator, page=3)

    assert [e.target_public_id for e in first.entries] == [targets[4], targets[3]]
    assert (first.has_previous, first.has_next) == (False, True)
    assert [e.target_public_id for e in last.entries] == [targets[0]]
    assert (last.has_previous, last.has_next) == (True, False)
    assert selectors.audit_record(administrator, page=99).number == 3
    assert selectors.audit_record(administrator, page=-4).number == 1


def test_reading_takes_as_many_queries_for_many_changes_as_for_few(
    administrator: AuthenticationContext, writer: AuthenticationContext
) -> None:
    def queries() -> int:
        with CaptureQueriesContext(connection) as captured:
            selectors.audit_record(administrator)
        return len(captured)

    _write(writer, AuditAction.UPDATED, AuditTargetType.COUNTRY, FIRST, RENAMED)
    few = queries()
    for n in range(10, 20):
        _write(writer, AuditAction.UPDATED, AuditTargetType.COUNTRY, uuid.UUID(int=n), RENAMED)

    assert queries() == few


@pytest.mark.parametrize("caller", ["reader", "researcher", "reviewer", "unverified administrator"])
def test_only_a_verified_administrator_reads_the_record(
    user_with_roles: UserFactory, caller: str
) -> None:
    if caller == "unverified administrator":
        context = signed_in(user_with_roles(Role.ADMINISTRATOR))
    else:
        context = verified(user_with_roles(Role(caller)))

    with pytest.raises(PermissionDenied):
        selectors.audit_record(context)


def test_the_permission_belongs_to_the_administrator_alone() -> None:
    holders = {role for role, held in ROLE_PERMISSIONS.items() if Permission.AUDIT_READ in held}

    assert holders == {Role.ADMINISTRATOR}
