"""Authorization decisions about real accounts, made without any HTTP request."""

import logging
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test.utils import CaptureQueriesContext

from caipo.accounts import selectors
from caipo.accounts.models import RoleEvent, RoleEventType, User
from caipo.accounts.selectors import Assurance, AuthenticationContext, Permission, Role
from caipo.accounts.tests.fixtures import (
    UserFactory,
    enrolled_device,
    signed_in,
    supporting_account,
    verified,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db]

READ = Permission.WORKSPACE_READ
CONTRIBUTE = Permission.RESEARCH_CONTRIBUTE
REVIEW = Permission.RESEARCH_REVIEW
MANAGE_ROLES = Permission.ROLES_MANAGE
DEACTIVATE = Permission.ACCOUNTS_DEACTIVATE
OWN_MFA = Permission.MFA_MANAGE_OWN


def _record(user: User, role: Role, event_type: RoleEventType) -> None:
    seeder = supporting_account("test.seed@caipo.test")
    RoleEvent.objects.create(
        user=user, role=role, event_type=event_type, actor=seeder, reason="TEST fixture"
    )


def test_a_new_user_has_no_roles_and_no_permissions(user_with_roles: UserFactory) -> None:
    user = user_with_roles()

    assert selectors.roles_of(user) == frozenset()
    assert selectors.permissions_of(signed_in(user)) == frozenset()
    assert not any(selectors.can(signed_in(user), permission) for permission in Permission)


@pytest.mark.parametrize("visitor", [AnonymousUser(), None])
def test_an_anonymous_visitor_holds_no_permission(visitor: AnonymousUser | None) -> None:
    actor = selectors.authentication_context(visitor, verified_device_id=1)

    assert actor is None
    assert selectors.permissions_of(actor) == frozenset()
    assert not any(selectors.can(actor, permission) for permission in Permission)
    # The ignore below: a visitor passed without a context is the case under test.
    assert selectors.permissions_of(visitor) == frozenset()  # type: ignore[arg-type]


@pytest.mark.parametrize("roles", [(Role.READER,), (Role.ADMINISTRATOR, Role.REVIEWER)])
def test_an_account_passed_without_a_context_holds_no_permission(
    user_with_roles: UserFactory, roles: tuple[Role, ...]
) -> None:
    user = user_with_roles(*roles)
    enrolled_device(user)

    # The ignores below: an account that is not in a context is the case under test.
    assert selectors.permissions_of(user) == frozenset()  # type: ignore[arg-type]
    assert not any(
        selectors.can(user, permission)  # type: ignore[arg-type]
        for permission in Permission
    )
    with pytest.raises(PermissionDenied):
        selectors.require_permission(user, READ)  # type: ignore[arg-type]


def test_a_user_can_hold_several_roles(user_with_roles: UserFactory) -> None:
    user = user_with_roles(Role.READER, Role.RESEARCHER)

    assert selectors.roles_of(user) == {Role.READER, Role.RESEARCHER}


def test_roles_belong_to_one_user_only(user_with_roles: UserFactory) -> None:
    user_with_roles(Role.RESEARCHER)
    other = user_with_roles()

    assert selectors.roles_of(other) == frozenset()


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (Role.READER, {READ, OWN_MFA}),
        (Role.RESEARCHER, {READ, CONTRIBUTE, OWN_MFA}),
        # On a password alone these two roles allow enrolling a second factor
        # and nothing else.
        (Role.REVIEWER, {OWN_MFA}),
        (Role.ADMINISTRATOR, {OWN_MFA}),
    ],
)
def test_what_each_role_can_do_on_a_password_alone(
    user_with_roles: UserFactory, role: Role, expected: set[Permission]
) -> None:
    user = user_with_roles(role)

    actor = signed_in(user)

    assert selectors.permissions_of(actor) == expected
    assert {permission for permission in Permission if selectors.can(actor, permission)} == expected


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (Role.READER, {READ, OWN_MFA}),
        (Role.RESEARCHER, {READ, CONTRIBUTE, OWN_MFA}),
        (Role.REVIEWER, {READ, CONTRIBUTE, REVIEW, OWN_MFA}),
        (
            Role.ADMINISTRATOR,
            {
                MANAGE_ROLES,
                Permission.ACCOUNTS_CREATE,
                DEACTIVATE,
                Permission.ACCOUNTS_ENABLE,
                OWN_MFA,
                Permission.MFA_ENROLLMENT_APPROVE,
            },
        ),
    ],
)
def test_what_each_role_can_do_with_a_verified_second_factor(
    user_with_roles: UserFactory, role: Role, expected: set[Permission]
) -> None:
    assert selectors.permissions_of(verified(user_with_roles(role))) == expected


def test_a_reviewer_who_is_also_a_researcher_works_as_a_researcher_on_a_password(
    user_with_roles: UserFactory,
) -> None:
    user = user_with_roles(Role.RESEARCHER, Role.REVIEWER)

    assert selectors.roles_of(user) == {Role.RESEARCHER, Role.REVIEWER}
    assert selectors.permissions_of(signed_in(user)) == {READ, CONTRIBUTE, OWN_MFA}


def test_the_latest_event_for_a_role_decides(user_with_roles: UserFactory) -> None:
    user = user_with_roles(Role.READER)

    _record(user, Role.READER, RoleEventType.REVOKED)
    assert selectors.roles_of(user) == frozenset()
    assert not selectors.can(signed_in(user), READ)

    _record(user, Role.READER, RoleEventType.GRANTED)
    assert selectors.roles_of(user) == {Role.READER}
    assert selectors.can(signed_in(user), READ)


def test_revoking_one_role_leaves_the_others(user_with_roles: UserFactory) -> None:
    user = user_with_roles(Role.READER, Role.RESEARCHER)

    _record(user, Role.RESEARCHER, RoleEventType.REVOKED)

    assert selectors.roles_of(user) == {Role.READER}
    assert selectors.permissions_of(signed_in(user)) == {READ, OWN_MFA}


def test_a_deactivated_account_keeps_its_record_but_holds_no_permission(
    user_with_roles: UserFactory,
) -> None:
    user = user_with_roles(Role.ADMINISTRATOR, Role.RESEARCHER, is_active=False)

    assert selectors.roles_of(user) == {Role.ADMINISTRATOR, Role.RESEARCHER}
    assert selectors.permissions_of(signed_in(user)) == frozenset()
    assert selectors.permissions_of(verified(user)) == frozenset()


def test_deactivation_takes_effect_for_an_object_loaded_earlier(
    user_with_roles: UserFactory,
) -> None:
    user = user_with_roles(Role.READER)
    assert selectors.can(signed_in(user), READ)

    User.objects.filter(pk=user.pk).update(status="disabled")

    assert user.is_active is True, "the object in memory is stale on purpose"
    assert not selectors.can(signed_in(user), READ)


def test_a_role_claimed_on_the_object_is_not_believed(user_with_roles: UserFactory) -> None:
    user = user_with_roles()
    for attribute in ("role", "roles", "is_staff", "is_superuser", "is_administrator"):
        setattr(user, attribute, Role.ADMINISTRATOR if "role" in attribute else True)

    assert selectors.permissions_of(verified(user)) == frozenset()


def test_an_object_that_only_looks_like_a_user_holds_no_permission(
    user_with_roles: UserFactory,
) -> None:
    administrator = user_with_roles(Role.ADMINISTRATOR)
    impostor = SimpleNamespace(
        pk=administrator.pk, id=administrator.pk, is_active=True, is_authenticated=True
    )

    device = enrolled_device(administrator)

    # The ignores below: passing something that is not a User is the case under test.
    assert selectors.permissions_of(impostor) == frozenset()  # type: ignore[arg-type]
    claimed = AuthenticationContext(impostor, Assurance.MFA_VERIFIED, device.pk)  # type: ignore[arg-type]
    assert selectors.permissions_of(claimed) == frozenset()


def test_an_unsaved_user_holds_nothing() -> None:
    user = User(email="test.unsaved@caipo.test")

    assert selectors.roles_of(user) == frozenset()
    assert selectors.permissions_of(signed_in(user)) == frozenset()


def test_a_decision_costs_one_query(user_with_roles: UserFactory) -> None:
    user = user_with_roles(Role.READER, Role.RESEARCHER)

    with CaptureQueriesContext(connection) as queries:
        assert selectors.can(signed_in(user), CONTRIBUTE)

    assert len(queries) == 1


def test_require_permission_passes_silently_when_the_permission_is_held(
    user_with_roles: UserFactory,
) -> None:
    selectors.require_permission(signed_in(user_with_roles(Role.READER)), READ)


def test_require_permission_stops_and_logs_when_it_is_not_held(
    user_with_roles: UserFactory, caplog: pytest.LogCaptureFixture
) -> None:
    user = user_with_roles(Role.READER)

    with (
        caplog.at_level(logging.WARNING, logger="caipo.accounts.selectors"),
        pytest.raises(PermissionDenied),
    ):
        selectors.require_permission(signed_in(user), CONTRIBUTE)

    (record,) = caplog.records
    assert record.__dict__["event"] == "authorization.denied"
    assert record.__dict__["permission"] == "research.contribute"
    assert record.__dict__["user_id"] == user.pk
    assert user.email not in record.getMessage()


@pytest.mark.parametrize("visitor", [AnonymousUser(), None])
def test_require_permission_stops_an_anonymous_visitor(visitor: AnonymousUser | None) -> None:
    with pytest.raises(PermissionDenied):
        selectors.require_permission(selectors.authentication_context(visitor), READ)
