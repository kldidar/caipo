"""The authorization policy as plain functions: no database, no HTTP."""

from itertools import chain, combinations

import pytest

from caipo.accounts.authorization import (
    MFA_REQUIRED_ROLES,
    ROLE_PERMISSIONS,
    Permission,
    Role,
    permissions_for,
)

READ = Permission.WORKSPACE_READ
CONTRIBUTE = Permission.RESEARCH_CONTRIBUTE
REVIEW = Permission.RESEARCH_REVIEW
MANAGE_ROLES = Permission.ROLES_MANAGE
DEACTIVATE = Permission.ACCOUNTS_DEACTIVATE


def test_the_roles_are_exactly_the_four_of_adr_0007() -> None:
    assert [role.value for role in Role] == ["reader", "researcher", "reviewer", "administrator"]


def test_the_permission_vocabulary_is_exactly_this() -> None:
    assert {permission.value for permission in Permission} == {
        "workspace.read",
        "research.contribute",
        "research.review",
        "accounts.roles.manage",
        "accounts.deactivate",
    }


def test_no_permission_can_be_mistaken_for_the_public_declaration() -> None:
    assert "public" not in {permission.value for permission in Permission}


def test_every_role_has_an_explicit_entry_in_the_policy() -> None:
    assert set(ROLE_PERMISSIONS) == set(Role)


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (Role.READER, {READ}),
        (Role.RESEARCHER, {READ, CONTRIBUTE}),
        (Role.REVIEWER, {READ, CONTRIBUTE, REVIEW}),
        (Role.ADMINISTRATOR, {MANAGE_ROLES, DEACTIVATE}),
    ],
)
def test_each_role_confers_exactly_its_permissions_when_enrolled(
    role: Role, expected: set[Permission]
) -> None:
    assert permissions_for([role], mfa_enrolled=True) == expected


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (Role.READER, {READ}),
        (Role.RESEARCHER, {READ, CONTRIBUTE}),
        (Role.REVIEWER, set()),
        (Role.ADMINISTRATOR, set()),
    ],
)
def test_roles_requiring_a_second_factor_confer_nothing_without_it(
    role: Role, expected: set[Permission]
) -> None:
    assert permissions_for([role], mfa_enrolled=False) == expected


def test_reviewer_and_administrator_are_the_roles_requiring_a_second_factor() -> None:
    assert MFA_REQUIRED_ROLES == {Role.REVIEWER, Role.ADMINISTRATOR}


def test_no_roles_confer_no_permissions() -> None:
    assert permissions_for([], mfa_enrolled=True) == frozenset()


def test_administrator_holds_no_research_permission() -> None:
    administrator = permissions_for([Role.ADMINISTRATOR], mfa_enrolled=True)

    assert administrator.isdisjoint({READ, CONTRIBUTE, REVIEW})


@pytest.mark.parametrize("permission", [MANAGE_ROLES, DEACTIVATE])
def test_only_administrator_holds_the_administrative_permissions(permission: Permission) -> None:
    holders = {role for role in Role if permission in ROLE_PERMISSIONS[role]}

    assert holders == {Role.ADMINISTRATOR}


@pytest.mark.parametrize("role", [Role.READER, Role.RESEARCHER, Role.REVIEWER])
def test_research_roles_hold_no_administrative_permission(role: Role) -> None:
    assert ROLE_PERMISSIONS[role].isdisjoint({MANAGE_ROLES, DEACTIVATE})


def test_only_reviewer_can_review() -> None:
    holders = {role for role in Role if REVIEW in ROLE_PERMISSIONS[role]}

    assert holders == {Role.REVIEWER}


def test_several_roles_confer_the_union_of_their_permissions() -> None:
    held = permissions_for([Role.RESEARCHER, Role.ADMINISTRATOR], mfa_enrolled=True)

    assert held == {READ, CONTRIBUTE, MANAGE_ROLES, DEACTIVATE}


def test_an_unenrolled_account_keeps_the_roles_that_need_no_second_factor() -> None:
    held = permissions_for([Role.READER, Role.REVIEWER, Role.ADMINISTRATOR], mfa_enrolled=False)

    assert held == {READ}


def test_no_combination_of_roles_confers_more_than_the_roles_do_separately() -> None:
    subsets = chain.from_iterable(combinations(Role, size) for size in range(len(Role) + 1))

    for roles in subsets:
        separately = frozenset().union(*(ROLE_PERMISSIONS[role] for role in roles))
        assert permissions_for(roles, mfa_enrolled=True) == separately


@pytest.mark.parametrize("unknown", ["administrator ", "ADMINISTRATOR", "superuser", "", None, 1])
def test_something_that_is_not_a_role_confers_nothing(unknown: object) -> None:
    # The ignore below: the argument is deliberately not a Role; that is the case under test.
    assert permissions_for([unknown], mfa_enrolled=True) == frozenset()  # type: ignore[list-item]


def test_the_policy_table_cannot_be_modified_at_run_time() -> None:
    with pytest.raises(TypeError):
        # The ignore below: assigning to the read-only mapping is the case under test.
        ROLE_PERMISSIONS[Role.READER] = frozenset(Permission)  # type: ignore[index]


def test_the_decision_is_deterministic() -> None:
    roles = [Role.REVIEWER, Role.READER]

    assert permissions_for(roles, mfa_enrolled=True) == permissions_for(
        reversed(roles), mfa_enrolled=True
    )
