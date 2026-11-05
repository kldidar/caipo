"""Changing an account named by its number, and reading accounts for that.

The operations by number are what the administration pages call. Each one
checks its permission before it looks the number up, then does exactly what
the operation on an account object does, with the same refusals.
"""

from collections.abc import Callable

import pytest
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test.utils import CaptureQueriesContext

from caipo.accounts import selectors, services
from caipo.accounts.models import AccountEvent, AccountStatus, RoleEvent, RoleEventType, User
from caipo.accounts.selectors import AuthenticationContext, MfaState, Role
from caipo.accounts.services import (
    AccountChangeError,
    LastAdministratorError,
    NoSuchAccountError,
    RoleChangeError,
)
from caipo.accounts.tests.fixtures import UserFactory, enrolled_device, signed_in, verified

pytestmark = [pytest.mark.services, pytest.mark.django_db]

REASON = "TEST reason for the change"
REGISTERED_EMAIL = "test.registered@caipo.test"
UNKNOWN = 999_999

type Operation = Callable[[AuthenticationContext, int], object]

OPERATIONS: dict[str, Operation] = {
    "grant": lambda actor, user_id: services.grant_role_to_account(
        actor=actor, user_id=user_id, role=Role.RESEARCHER, reason=REASON
    ),
    "revoke": lambda actor, user_id: services.revoke_role_from_account(
        actor=actor, user_id=user_id, role=Role.READER, reason=REASON
    ),
    "disable": lambda actor, user_id: services.disable_account(actor=actor, user_id=user_id),
    "enable": lambda actor, user_id: services.enable_account(actor=actor, user_id=user_id),
}


@pytest.fixture
def administrator(user_with_roles: UserFactory) -> AuthenticationContext:
    return verified(user_with_roles(Role.ADMINISTRATOR))


def _record() -> tuple[int, int, list[str]]:
    return (
        RoleEvent.objects.count(),
        AccountEvent.objects.count(),
        list(User.objects.order_by("pk").values_list("status", flat=True)),
    )


# --- The operations by number -------------------------------------------------------------


def test_a_role_is_granted_and_revoked_by_the_number_of_the_account(
    administrator: AuthenticationContext, user_with_roles: UserFactory
) -> None:
    user = user_with_roles(Role.READER)

    granted = services.grant_role_to_account(
        actor=administrator, user_id=user.pk, role=Role.RESEARCHER, reason=f" {REASON} "
    )
    revoked = services.revoke_role_from_account(
        actor=administrator, user_id=user.pk, role=Role.READER, reason=REASON
    )

    assert selectors.roles_of(user) == {Role.RESEARCHER}
    assert (granted.user, granted.actor, granted.event_type) == (
        user,
        administrator.user,
        RoleEventType.GRANTED,
    )
    assert (revoked.role, revoked.event_type, revoked.reason) == (
        Role.READER,
        RoleEventType.REVOKED,
        REASON,
    )


def test_an_account_is_disabled_and_enabled_by_its_number(
    administrator: AuthenticationContext, user_with_roles: UserFactory
) -> None:
    user = user_with_roles(Role.RESEARCHER)

    services.disable_account(actor=administrator, user_id=user.pk)
    user.refresh_from_db()
    assert user.status == AccountStatus.DISABLED

    assert services.enable_account(actor=administrator, user_id=user.pk) == AccountStatus.ACTIVE
    user.refresh_from_db()
    assert user.status == AccountStatus.ACTIVE
    assert selectors.roles_of(user) == {Role.RESEARCHER}


@pytest.mark.parametrize("operation", OPERATIONS)
def test_a_number_that_names_no_account_is_refused_and_changes_nothing(
    administrator: AuthenticationContext, operation: str
) -> None:
    before = _record()

    with pytest.raises(NoSuchAccountError):
        OPERATIONS[operation](administrator, UNKNOWN)

    assert _record() == before


def test_no_such_account_is_a_refused_account_change() -> None:
    assert issubclass(NoSuchAccountError, AccountChangeError)


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("caller", ["reader", "researcher", "reviewer", "unverified administrator"])
def test_the_permission_is_checked_before_the_number_is_looked_up(
    user_with_roles: UserFactory, operation: str, caller: str
) -> None:
    """A caller without the permission gets the same answer for a real and an unknown number."""
    if caller == "unverified administrator":
        actor = signed_in(user_with_roles(Role.ADMINISTRATOR))
    else:
        actor = verified(user_with_roles(Role(caller)))
    target = user_with_roles(Role.READER)
    if operation == "enable":
        User.objects.filter(pk=target.pk).update(status=AccountStatus.DISABLED)
    before = _record()

    for user_id in (target.pk, UNKNOWN):
        with pytest.raises(PermissionDenied):
            OPERATIONS[operation](actor, user_id)

    assert _record() == before


def test_an_administrator_changes_none_of_their_own_roles_by_number(
    administrator: AuthenticationContext,
) -> None:
    before = _record()

    with pytest.raises(PermissionDenied):
        services.grant_role_to_account(
            actor=administrator, user_id=administrator.user.pk, role=Role.READER, reason=REASON
        )
    with pytest.raises(PermissionDenied):
        services.revoke_role_from_account(
            actor=administrator,
            user_id=administrator.user.pk,
            role=Role.ADMINISTRATOR,
            reason=REASON,
        )

    assert _record() == before


def test_the_refusals_of_a_role_change_are_those_of_the_operation(
    administrator: AuthenticationContext, user_with_roles: UserFactory
) -> None:
    user = user_with_roles(Role.READER)
    before = _record()

    with pytest.raises(RoleChangeError):
        services.grant_role_to_account(
            actor=administrator, user_id=user.pk, role=Role.READER, reason=REASON
        )
    with pytest.raises(RoleChangeError):
        services.revoke_role_from_account(
            actor=administrator, user_id=user.pk, role=Role.REVIEWER, reason=REASON
        )
    with pytest.raises(ValueError, match="reason"):
        services.grant_role_to_account(
            actor=administrator, user_id=user.pk, role=Role.REVIEWER, reason="   "
        )

    assert _record() == before


def test_the_refusals_of_disabling_and_enabling_are_those_of_the_operations(
    administrator: AuthenticationContext, user_with_roles: UserFactory
) -> None:
    active = user_with_roles(Role.READER)
    disabled = user_with_roles(Role.READER, is_active=False)
    before = _record()

    with pytest.raises(AccountChangeError, match="already disabled"):
        services.disable_account(actor=administrator, user_id=disabled.pk)
    with pytest.raises(AccountChangeError, match="not disabled"):
        services.enable_account(actor=administrator, user_id=active.pk)
    with pytest.raises(LastAdministratorError):
        services.disable_account(actor=administrator, user_id=administrator.user.pk)

    assert _record() == before


# --- Reading accounts ---------------------------------------------------------------------


def test_every_account_is_listed_newest_first_with_its_state(
    administrator: AuthenticationContext, user_with_roles: UserFactory
) -> None:
    services.register_account(
        email=REGISTERED_EMAIL, source="192.0.2.1", activation_url=lambda token: f"/#{token}"
    )
    researcher = user_with_roles(Role.READER, Role.RESEARCHER)
    enrolled_device(researcher)
    disabled = user_with_roles(Role.REVIEWER, is_active=False)

    listed = {
        summary.email: summary for summary in selectors.accounts_for_administration(administrator)
    }
    order = [summary.user_id for summary in selectors.accounts_for_administration(administrator)]

    assert order == list(User.objects.order_by("-created_at", "-pk").values_list("pk", flat=True))
    registered = listed[REGISTERED_EMAIL]
    assert (registered.status, registered.roles, registered.registered) == (
        AccountStatus.PENDING_VERIFICATION,
        (Role.READER,),
        True,
    )
    assert registered.mfa_state == MfaState.NOT_ENROLLED
    mine = listed[researcher.email]
    assert (mine.status, mine.roles, mine.mfa_state, mine.registered) == (
        AccountStatus.ACTIVE,
        (Role.READER, Role.RESEARCHER),
        MfaState.ACTIVE,
        False,
    )
    assert mine.role_labels == ("Reader", "Researcher")
    assert (listed[disabled.email].status, listed[disabled.email].status_label) == (
        AccountStatus.DISABLED,
        "Disabled",
    )
    assert listed[disabled.email].roles == (Role.REVIEWER,)


def test_a_revoked_role_is_not_listed(
    administrator: AuthenticationContext, user_with_roles: UserFactory
) -> None:
    user = user_with_roles(Role.READER, Role.RESEARCHER)
    services.revoke_role(actor=administrator, user=user, role=Role.RESEARCHER, reason=REASON)

    (summary,) = [
        summary
        for summary in selectors.accounts_for_administration(administrator)
        if summary.user_id == user.pk
    ]

    assert summary.roles == (Role.READER,)


def test_the_list_takes_as_many_queries_for_many_accounts_as_for_few(
    administrator: AuthenticationContext, user_with_roles: UserFactory
) -> None:
    def queries() -> int:
        with CaptureQueriesContext(connection) as captured:
            selectors.accounts_for_administration(administrator)
        return len(captured)

    few = queries()
    for _ in range(5):
        enrolled_device(user_with_roles(Role.READER, Role.RESEARCHER))

    assert queries() == few


def test_one_account_is_read_with_its_role_history_newest_first(
    administrator: AuthenticationContext, user_with_roles: UserFactory
) -> None:
    services.register_account(
        email=REGISTERED_EMAIL, source="192.0.2.1", activation_url=lambda token: f"/#{token}"
    )
    user = User.objects.get(email=REGISTERED_EMAIL)
    services.grant_role(actor=administrator, user=user, role=Role.RESEARCHER, reason=REASON)
    services.revoke_role(actor=administrator, user=user, role=Role.READER, reason="TEST second")

    account = selectors.account_for_administration(administrator, user.pk)

    assert account is not None
    assert account.summary.email == REGISTERED_EMAIL
    assert account.summary.roles == (Role.RESEARCHER,)
    assert [
        (change.role, change.granted, change.actor_email, change.reason)
        for change in account.role_history
    ] == [
        (Role.READER, False, administrator.user.email, "TEST second"),
        (Role.RESEARCHER, True, administrator.user.email, REASON),
        (Role.READER, True, None, services.REGISTRATION_ROLE_REASON),
    ]
    assert account.role_history[0].role_label == "Reader"
    assert account.is_actor is False
    assert account.grantable == (Role.READER, Role.REVIEWER, Role.ADMINISTRATOR)


def test_the_account_of_the_caller_is_marked_as_theirs(
    administrator: AuthenticationContext,
) -> None:
    account = selectors.account_for_administration(administrator, administrator.user.pk)

    assert account is not None
    assert account.is_actor is True
    assert Role.ADMINISTRATOR not in account.grantable


def test_an_unknown_number_reads_as_no_account(administrator: AuthenticationContext) -> None:
    assert selectors.account_for_administration(administrator, UNKNOWN) is None


@pytest.mark.parametrize("caller", ["reader", "researcher", "reviewer", "unverified administrator"])
def test_only_a_verified_administrator_reads_accounts(
    user_with_roles: UserFactory, caller: str
) -> None:
    if caller == "unverified administrator":
        actor = signed_in(user_with_roles(Role.ADMINISTRATOR))
    else:
        actor = verified(user_with_roles(Role(caller)))
    target = user_with_roles(Role.READER)

    with pytest.raises(PermissionDenied):
        selectors.accounts_for_administration(actor)
    for user_id in (target.pk, UNKNOWN):
        with pytest.raises(PermissionDenied):
            selectors.account_for_administration(actor, user_id)
