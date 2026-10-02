"""Granting and revoking roles: who may, what is recorded, and what is refused."""

import logging
from collections.abc import Callable

import pytest
from django.core.exceptions import PermissionDenied
from django.db import transaction

from caipo.accounts import selectors, services
from caipo.accounts.models import RoleEvent, RoleEventType, User
from caipo.accounts.selectors import Permission, Role
from caipo.accounts.services import AccountChangeError, LastAdministratorError, RoleChangeError
from caipo.accounts.tests.fixtures import UserFactory

pytestmark = [pytest.mark.services, pytest.mark.django_db]

REASON = "TEST reason for the change"


def _events(user: User) -> list[tuple[str, str]]:
    return list(
        RoleEvent.objects.filter(user=user).order_by("id").values_list("role", "event_type")
    )


@pytest.fixture
def administrator(user_with_roles: UserFactory, mfa_enrolled: None) -> User:
    return user_with_roles(Role.ADMINISTRATOR)


def test_an_administrator_grants_a_role(administrator: User, user_with_roles: UserFactory) -> None:
    user = user_with_roles()

    event = services.grant_role(
        actor=administrator, user=user, role=Role.RESEARCHER, reason=f"  {REASON}  "
    )

    assert selectors.roles_of(user) == {Role.RESEARCHER}
    assert selectors.can(user, Permission.RESEARCH_CONTRIBUTE)
    assert (event.user, event.actor, event.role) == (user, administrator, Role.RESEARCHER)
    assert event.event_type == RoleEventType.GRANTED
    assert event.reason == REASON
    assert event.created_at is not None


def test_an_administrator_grants_several_roles_to_one_user(
    administrator: User, user_with_roles: UserFactory
) -> None:
    user = user_with_roles()

    services.grant_role(actor=administrator, user=user, role=Role.READER, reason=REASON)
    services.grant_role(actor=administrator, user=user, role=Role.REVIEWER, reason=REASON)

    assert selectors.roles_of(user) == {Role.READER, Role.REVIEWER}


def test_revoking_adds_an_event_and_keeps_the_grant_on_record(
    administrator: User, user_with_roles: UserFactory
) -> None:
    user = user_with_roles(Role.RESEARCHER)

    event = services.revoke_role(
        actor=administrator, user=user, role=Role.RESEARCHER, reason=REASON
    )

    assert selectors.roles_of(user) == frozenset()
    assert not selectors.can(user, Permission.RESEARCH_CONTRIBUTE)
    assert (event.actor, event.event_type) == (administrator, RoleEventType.REVOKED)
    assert _events(user) == [("researcher", "granted"), ("researcher", "revoked")]


def test_a_role_can_be_granted_again_after_revocation_with_full_history(
    administrator: User, user_with_roles: UserFactory
) -> None:
    user = user_with_roles(Role.READER)

    services.revoke_role(actor=administrator, user=user, role=Role.READER, reason=REASON)
    services.grant_role(actor=administrator, user=user, role=Role.READER, reason=REASON)

    assert selectors.roles_of(user) == {Role.READER}
    assert _events(user) == [("reader", "granted"), ("reader", "revoked"), ("reader", "granted")]


def test_a_change_is_logged_by_identifier_not_by_email(
    administrator: User, user_with_roles: UserFactory, caplog: pytest.LogCaptureFixture
) -> None:
    user = user_with_roles()

    with caplog.at_level(logging.INFO, logger="caipo.accounts.services"):
        event = services.grant_role(actor=administrator, user=user, role=Role.READER, reason=REASON)

    (record,) = caplog.records
    assert record.__dict__["event"] == "accounts.role_granted"
    assert record.__dict__["role"] == "reader"
    assert record.__dict__["user_id"] == user.pk
    assert record.__dict__["actor_id"] == administrator.pk
    assert record.__dict__["role_event_id"] == event.pk
    assert user.email not in str(record.__dict__)
    assert REASON not in str(record.__dict__)


@pytest.mark.usefixtures("mfa_enrolled")
@pytest.mark.parametrize("roles", [(), (Role.READER,), (Role.RESEARCHER,), (Role.REVIEWER,)])
@pytest.mark.parametrize("operation", [services.grant_role, services.revoke_role])
def test_only_an_administrator_may_change_roles(
    user_with_roles: UserFactory, roles: tuple[Role, ...], operation: Callable[..., RoleEvent]
) -> None:
    actor = user_with_roles(*roles)
    target = user_with_roles(Role.READER)

    with pytest.raises(PermissionDenied):
        operation(actor=actor, user=target, role=Role.RESEARCHER, reason=REASON)

    assert _events(target) == [("reader", "granted")]


def test_an_administrator_without_a_second_factor_cannot_change_roles(
    user_with_roles: UserFactory,
) -> None:
    # The real state of the system today: no account can enrol.
    actor = user_with_roles(Role.ADMINISTRATOR)
    target = user_with_roles()

    with pytest.raises(PermissionDenied):
        services.grant_role(actor=actor, user=target, role=Role.READER, reason=REASON)

    assert _events(target) == []


@pytest.mark.usefixtures("mfa_enrolled")
def test_a_deactivated_administrator_cannot_change_roles(user_with_roles: UserFactory) -> None:
    actor = user_with_roles(Role.ADMINISTRATOR, is_active=False)
    target = user_with_roles()

    with pytest.raises(PermissionDenied):
        services.grant_role(actor=actor, user=target, role=Role.READER, reason=REASON)

    assert _events(target) == []


@pytest.mark.usefixtures("mfa_enrolled")
@pytest.mark.parametrize("roles", [(), (Role.READER,), (Role.RESEARCHER,), (Role.REVIEWER,)])
def test_a_user_cannot_make_themselves_an_administrator(
    user_with_roles: UserFactory, roles: tuple[Role, ...]
) -> None:
    user = user_with_roles(*roles)

    with pytest.raises(PermissionDenied):
        services.grant_role(actor=user, user=user, role=Role.ADMINISTRATOR, reason=REASON)

    assert Role.ADMINISTRATOR not in selectors.roles_of(user)
    assert not selectors.can(user, Permission.ROLES_MANAGE)


@pytest.mark.usefixtures("mfa_enrolled")
def test_a_caller_without_the_permission_learns_nothing_from_the_error(
    user_with_roles: UserFactory,
) -> None:
    actor = user_with_roles(Role.READER)
    target = user_with_roles(Role.READER)

    # Each of these would be a different error for an Administrator.
    with pytest.raises(PermissionDenied):
        services.grant_role(actor=actor, user=target, role=Role.READER, reason=REASON)
    with pytest.raises(PermissionDenied):
        services.grant_role(actor=actor, user=target, role=Role.REVIEWER, reason="")
    with pytest.raises(PermissionDenied):
        # The ignore below: an invented role is the case under test.
        services.grant_role(actor=actor, user=target, role="superuser", reason=REASON)  # type: ignore[arg-type]


@pytest.mark.parametrize("role", ["superuser", "ADMINISTRATOR", "", "reader "])
def test_an_invented_role_is_rejected(
    administrator: User, user_with_roles: UserFactory, role: str
) -> None:
    user = user_with_roles()

    with pytest.raises(ValueError, match="is not a valid Role"):
        # The ignore below: an invented role is the case under test.
        services.grant_role(actor=administrator, user=user, role=role, reason=REASON)  # type: ignore[arg-type]

    assert _events(user) == []


@pytest.mark.parametrize("reason", ["", "   ", "\n\t"])
def test_a_reason_is_required(
    administrator: User, user_with_roles: UserFactory, reason: str
) -> None:
    user = user_with_roles()

    with pytest.raises(ValueError, match="reason"):
        services.grant_role(actor=administrator, user=user, role=Role.READER, reason=reason)

    assert _events(user) == []


def test_granting_a_role_already_held_is_refused_not_repeated(
    administrator: User, user_with_roles: UserFactory
) -> None:
    user = user_with_roles(Role.READER)

    with pytest.raises(RoleChangeError):
        services.grant_role(actor=administrator, user=user, role=Role.READER, reason=REASON)

    assert _events(user) == [("reader", "granted")]


def test_revoking_a_role_not_held_is_refused(
    administrator: User, user_with_roles: UserFactory
) -> None:
    user = user_with_roles(Role.READER)

    with pytest.raises(RoleChangeError):
        services.revoke_role(actor=administrator, user=user, role=Role.RESEARCHER, reason=REASON)

    assert _events(user) == [("reader", "granted")]


def test_a_deactivated_user_can_still_have_a_role_revoked(
    administrator: User, user_with_roles: UserFactory
) -> None:
    user = user_with_roles(Role.RESEARCHER, is_active=False)

    services.revoke_role(actor=administrator, user=user, role=Role.RESEARCHER, reason=REASON)

    assert selectors.roles_of(user) == frozenset()


# --- Separation of duties: nobody changes their own roles ---------------------


def _administrators() -> set[User]:
    return {user for user in User.objects.all() if Role.ADMINISTRATOR in selectors.roles_of(user)}


@pytest.mark.parametrize("role", list(Role))
def test_an_administrator_cannot_grant_themselves_a_role(
    administrator: User, user_with_roles: UserFactory, role: Role
) -> None:
    user_with_roles(Role.ADMINISTRATOR)  # so that the refusal is not about being the last one
    before = _events(administrator)

    with pytest.raises(PermissionDenied):
        services.grant_role(actor=administrator, user=administrator, role=role, reason=REASON)

    assert _events(administrator) == before
    assert selectors.roles_of(administrator) == {Role.ADMINISTRATOR}


def test_an_administrator_cannot_revoke_their_own_administrator_role(
    administrator: User, user_with_roles: UserFactory
) -> None:
    user_with_roles(Role.ADMINISTRATOR)
    before = _events(administrator)

    with pytest.raises(PermissionDenied):
        services.revoke_role(
            actor=administrator, user=administrator, role=Role.ADMINISTRATOR, reason=REASON
        )

    assert _events(administrator) == before
    assert selectors.can(administrator, Permission.ROLES_MANAGE)


def test_an_administrator_cannot_revoke_another_of_their_own_roles(
    user_with_roles: UserFactory, mfa_enrolled: None
) -> None:
    actor = user_with_roles(Role.ADMINISTRATOR, Role.REVIEWER)

    with pytest.raises(PermissionDenied):
        services.revoke_role(actor=actor, user=actor, role=Role.REVIEWER, reason=REASON)

    assert selectors.roles_of(actor) == {Role.ADMINISTRATOR, Role.REVIEWER}


def test_a_refused_change_to_own_roles_is_logged(
    administrator: User, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        caplog.at_level(logging.WARNING, logger="caipo.accounts.services"),
        pytest.raises(PermissionDenied),
    ):
        services.grant_role(
            actor=administrator, user=administrator, role=Role.REVIEWER, reason=REASON
        )

    (record,) = caplog.records
    assert record.__dict__["event"] == "accounts.own_role_change_refused"
    assert record.__dict__["user_id"] == administrator.pk


def test_two_administrators_can_change_each_other(
    administrator: User, user_with_roles: UserFactory
) -> None:
    other = user_with_roles(Role.ADMINISTRATOR)

    services.grant_role(actor=other, user=administrator, role=Role.REVIEWER, reason=REASON)
    services.revoke_role(actor=administrator, user=other, role=Role.ADMINISTRATOR, reason=REASON)

    assert selectors.roles_of(administrator) == {Role.ADMINISTRATOR, Role.REVIEWER}
    assert selectors.roles_of(other) == frozenset()


# --- There is always an Administrator -----------------------------------------


def test_the_only_administrator_cannot_remove_their_own_role(administrator: User) -> None:
    with pytest.raises(PermissionDenied):
        services.revoke_role(
            actor=administrator, user=administrator, role=Role.ADMINISTRATOR, reason=REASON
        )

    assert _administrators() == {administrator}


def test_revoking_administrator_from_another_leaves_the_actor_as_administrator(
    administrator: User, user_with_roles: UserFactory
) -> None:
    other = user_with_roles(Role.ADMINISTRATOR)

    services.revoke_role(actor=administrator, user=other, role=Role.ADMINISTRATOR, reason=REASON)

    assert _administrators() == {administrator}
    # The one who was removed can no longer remove the one who remains.
    with pytest.raises(PermissionDenied):
        services.revoke_role(
            actor=other, user=administrator, role=Role.ADMINISTRATOR, reason=REASON
        )
    assert _administrators() == {administrator}


def test_the_rule_itself_refuses_when_no_other_administrator_would_remain(
    administrator: User, user_with_roles: UserFactory
) -> None:
    # Reached directly: through the service an actor is always a second
    # Administrator, so the public operations cannot get here by themselves.
    with pytest.raises(LastAdministratorError):
        services._require_another_administrator(besides=administrator)

    other = user_with_roles(Role.ADMINISTRATOR)
    services._require_another_administrator(besides=administrator)

    User.objects.filter(pk=other.pk).update(is_active=False)
    with pytest.raises(LastAdministratorError):
        services._require_another_administrator(besides=administrator)


def test_an_administrator_whose_role_was_revoked_does_not_count_as_remaining(
    administrator: User, user_with_roles: UserFactory
) -> None:
    former = user_with_roles(Role.ADMINISTRATOR)
    services.revoke_role(actor=administrator, user=former, role=Role.ADMINISTRATOR, reason=REASON)

    with pytest.raises(LastAdministratorError):
        services._require_another_administrator(besides=administrator)


# --- Deactivating accounts ----------------------------------------------------


def test_an_administrator_deactivates_another_account(
    administrator: User, user_with_roles: UserFactory
) -> None:
    user = user_with_roles(Role.RESEARCHER)

    services.deactivate_user(actor=administrator, user=user)

    assert user.is_active is False
    assert User.objects.get(pk=user.pk).is_active is False
    assert selectors.roles_of(user) == {Role.RESEARCHER}, "the record is kept"
    assert selectors.permissions_of(user) == frozenset()


@pytest.mark.usefixtures("mfa_enrolled")
@pytest.mark.parametrize("roles", [(), (Role.READER,), (Role.RESEARCHER,), (Role.REVIEWER,)])
def test_only_an_administrator_may_deactivate_an_account(
    user_with_roles: UserFactory, roles: tuple[Role, ...]
) -> None:
    actor = user_with_roles(*roles)
    target = user_with_roles(Role.READER)

    with pytest.raises(PermissionDenied):
        services.deactivate_user(actor=actor, user=target)
    with pytest.raises(PermissionDenied):
        services.deactivate_user(actor=actor, user=actor)

    assert User.objects.get(pk=target.pk).is_active is True
    assert User.objects.get(pk=actor.pk).is_active is True


def test_an_administrator_without_a_second_factor_cannot_deactivate_an_account(
    user_with_roles: UserFactory,
) -> None:
    actor = user_with_roles(Role.ADMINISTRATOR)
    target = user_with_roles()

    with pytest.raises(PermissionDenied):
        services.deactivate_user(actor=actor, user=target)

    assert User.objects.get(pk=target.pk).is_active is True


def test_the_last_administrator_cannot_be_deactivated(administrator: User) -> None:
    with pytest.raises(LastAdministratorError):
        services.deactivate_user(actor=administrator, user=administrator)

    assert administrator.is_active is True
    assert User.objects.get(pk=administrator.pk).is_active is True
    assert selectors.can(administrator, Permission.ROLES_MANAGE)


def test_the_only_administrator_deactivating_themselves_changes_nothing(
    administrator: User, user_with_roles: UserFactory, caplog: pytest.LogCaptureFixture
) -> None:
    # Other accounts exist, and none of them is an Administrator.
    user_with_roles(Role.REVIEWER)
    user_with_roles(Role.READER)

    def stored_state() -> object:
        users = list(
            User.objects.order_by("id").values_list("id", "is_active", "updated_at", "last_login")
        )
        events = list(
            RoleEvent.objects.order_by("id").values_list(
                "id", "user_id", "role", "event_type", "actor_id", "reason", "created_at"
            )
        )
        return users, events

    before = stored_state()
    assert _administrators() == {administrator}

    with (
        caplog.at_level(logging.INFO, logger="caipo.accounts.services"),
        pytest.raises(LastAdministratorError),
    ):
        services.deactivate_user(actor=administrator, user=administrator)

    assert stored_state() == before
    assert administrator.is_active is True
    assert _administrators() == {administrator}
    assert selectors.permissions_of(administrator) == {
        Permission.ROLES_MANAGE,
        Permission.ACCOUNTS_DEACTIVATE,
    }
    # Nothing was reported as done.
    assert [record.__dict__.get("event") for record in caplog.records] == []


def test_an_inactive_administrator_does_not_count_as_another_administrator(
    administrator: User, user_with_roles: UserFactory
) -> None:
    user_with_roles(Role.ADMINISTRATOR, is_active=False)

    with pytest.raises(LastAdministratorError):
        services.deactivate_user(actor=administrator, user=administrator)

    assert User.objects.get(pk=administrator.pk).is_active is True


def test_one_of_two_administrators_can_be_deactivated_but_not_the_one_remaining(
    administrator: User, user_with_roles: UserFactory
) -> None:
    other = user_with_roles(Role.ADMINISTRATOR)

    services.deactivate_user(actor=administrator, user=other)

    assert User.objects.get(pk=other.pk).is_active is False
    with pytest.raises(LastAdministratorError):
        services.deactivate_user(actor=administrator, user=administrator)
    assert User.objects.get(pk=administrator.pk).is_active is True


def test_an_administrator_may_deactivate_their_own_account_when_another_remains(
    administrator: User, user_with_roles: UserFactory
) -> None:
    other = user_with_roles(Role.ADMINISTRATOR)

    services.deactivate_user(actor=administrator, user=administrator)

    assert User.objects.get(pk=administrator.pk).is_active is False
    assert selectors.permissions_of(administrator) == frozenset()
    assert selectors.can(other, Permission.ROLES_MANAGE)


def test_a_deactivated_administrator_cannot_deactivate_the_remaining_one(
    administrator: User, user_with_roles: UserFactory
) -> None:
    other = user_with_roles(Role.ADMINISTRATOR)
    services.deactivate_user(actor=administrator, user=other)

    with pytest.raises(PermissionDenied):
        services.deactivate_user(actor=other, user=administrator)

    assert User.objects.get(pk=administrator.pk).is_active is True


def test_deactivating_an_inactive_account_is_refused(
    administrator: User, user_with_roles: UserFactory
) -> None:
    user = user_with_roles(is_active=False)

    with pytest.raises(AccountChangeError):
        services.deactivate_user(actor=administrator, user=user)


def test_deactivation_decides_on_the_stored_account_not_the_object_passed_in(
    administrator: User, user_with_roles: UserFactory
) -> None:
    other = user_with_roles(Role.ADMINISTRATOR)
    stale = User.objects.get(pk=other.pk)
    services.deactivate_user(actor=administrator, user=other)
    assert stale.is_active is True, "the object in memory is stale on purpose"

    with pytest.raises(AccountChangeError):
        services.deactivate_user(actor=administrator, user=stale)


def test_a_deactivation_is_logged_by_identifier(
    administrator: User, user_with_roles: UserFactory, caplog: pytest.LogCaptureFixture
) -> None:
    user = user_with_roles()

    with caplog.at_level(logging.INFO, logger="caipo.accounts.services"):
        services.deactivate_user(actor=administrator, user=user)

    (record,) = caplog.records
    assert record.__dict__["event"] == "accounts.deactivated"
    assert record.__dict__["user_id"] == user.pk
    assert record.__dict__["actor_id"] == administrator.pk
    assert user.email not in str(record.__dict__)


# --- Each operation is all or nothing -----------------------------------------


def test_a_role_change_is_undone_with_the_transaction_around_it(
    administrator: User, user_with_roles: UserFactory
) -> None:
    user = user_with_roles()

    with pytest.raises(RuntimeError), transaction.atomic():
        services.grant_role(actor=administrator, user=user, role=Role.READER, reason=REASON)
        assert selectors.roles_of(user) == {Role.READER}
        raise RuntimeError("TEST failure after the change")

    assert selectors.roles_of(user) == frozenset()
    assert _events(user) == []


def test_a_deactivation_is_undone_with_the_transaction_around_it(
    administrator: User, user_with_roles: UserFactory
) -> None:
    user = user_with_roles(Role.READER)

    with pytest.raises(RuntimeError), transaction.atomic():
        services.deactivate_user(actor=administrator, user=user)
        raise RuntimeError("TEST failure after the change")

    assert User.objects.get(pk=user.pk).is_active is True


def test_a_refused_operation_writes_nothing(
    administrator: User, user_with_roles: UserFactory
) -> None:
    user = user_with_roles(Role.READER)
    events_before = RoleEvent.objects.count()

    with pytest.raises(RoleChangeError):
        services.grant_role(actor=administrator, user=user, role=Role.READER, reason=REASON)
    with pytest.raises(ValueError, match="reason"):
        services.grant_role(actor=administrator, user=user, role=Role.RESEARCHER, reason=" ")
    with pytest.raises(PermissionDenied):
        services.grant_role(actor=user, user=administrator, role=Role.READER, reason=REASON)

    assert RoleEvent.objects.count() == events_before
