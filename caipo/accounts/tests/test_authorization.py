"""The authorization policy as plain functions: no database, no HTTP."""

from itertools import chain, combinations

import pytest

from caipo.accounts.authorization import (
    MFA_REQUIRED_ROLES,
    PERMISSIONS_BEFORE_MFA,
    ROLE_PERMISSIONS,
    Assurance,
    Permission,
    Role,
    enrollment_requires_approval,
    permissions_for,
)

READ = Permission.WORKSPACE_READ
CONTRIBUTE = Permission.RESEARCH_CONTRIBUTE
REVIEW = Permission.RESEARCH_REVIEW
MANAGE_ROLES = Permission.ROLES_MANAGE
DEACTIVATE = Permission.ACCOUNTS_DEACTIVATE
OWN_MFA = Permission.MFA_MANAGE_OWN
APPROVE = Permission.MFA_ENROLLMENT_APPROVE

PASSWORD = Assurance.PASSWORD_AUTHENTICATED
MFA = Assurance.MFA_VERIFIED


def test_the_roles_are_exactly_the_four_of_adr_0007() -> None:
    assert [role.value for role in Role] == ["reader", "researcher", "reviewer", "administrator"]


def test_the_permission_vocabulary_is_exactly_this() -> None:
    assert {permission.value for permission in Permission} == {
        "workspace.read",
        "research.contribute",
        "research.review",
        "accounts.roles.manage",
        "accounts.deactivate",
        "accounts.mfa.manage_own",
        "accounts.mfa.approve_enrollment",
    }


def test_the_assurance_levels_are_exactly_these_two() -> None:
    assert [assurance.value for assurance in Assurance] == [
        "password_authenticated",
        "mfa_verified",
    ]


def test_no_permission_can_be_mistaken_for_the_public_declaration() -> None:
    assert "public" not in {permission.value for permission in Permission}


def test_every_role_has_an_explicit_entry_in_the_policy() -> None:
    assert set(ROLE_PERMISSIONS) == set(Role)


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (Role.READER, {READ, OWN_MFA}),
        (Role.RESEARCHER, {READ, CONTRIBUTE, OWN_MFA}),
        (Role.REVIEWER, {READ, CONTRIBUTE, REVIEW, OWN_MFA}),
        (Role.ADMINISTRATOR, {MANAGE_ROLES, DEACTIVATE, OWN_MFA, APPROVE}),
    ],
)
def test_each_role_confers_exactly_its_permissions_with_a_verified_second_factor(
    role: Role, expected: set[Permission]
) -> None:
    assert permissions_for([role], assurance=MFA) == expected


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (Role.READER, {READ, OWN_MFA}),
        (Role.RESEARCHER, {READ, CONTRIBUTE, OWN_MFA}),
        (Role.REVIEWER, {OWN_MFA}),
        (Role.ADMINISTRATOR, {OWN_MFA}),
    ],
)
def test_roles_requiring_a_second_factor_confer_only_enrolment_on_a_password(
    role: Role, expected: set[Permission]
) -> None:
    assert permissions_for([role], assurance=PASSWORD) == expected


def test_enrolment_is_the_only_permission_available_before_a_second_factor() -> None:
    assert PERMISSIONS_BEFORE_MFA == {OWN_MFA}


@pytest.mark.parametrize("role", [Role.READER, Role.RESEARCHER])
def test_roles_that_need_no_second_factor_confer_the_same_at_either_assurance(role: Role) -> None:
    assert permissions_for([role], assurance=PASSWORD) == permissions_for([role], assurance=MFA)


@pytest.mark.parametrize(
    "not_an_assurance", ["mfa_verified", "MFA_VERIFIED", True, 1, None, "password_authenticated"]
)
def test_anything_that_is_not_the_verified_assurance_counts_as_the_weaker_one(
    not_an_assurance: object,
) -> None:
    # The ignore below: an assurance that is not an Assurance is the case under test.
    held = permissions_for(
        [Role.REVIEWER, Role.ADMINISTRATOR],
        assurance=not_an_assurance,  # type: ignore[arg-type]
    )

    assert held == {OWN_MFA}


def test_every_role_can_manage_its_own_second_factor() -> None:
    assert all(OWN_MFA in permissions for permissions in ROLE_PERMISSIONS.values())


def test_reviewer_and_administrator_are_the_roles_requiring_a_second_factor() -> None:
    assert MFA_REQUIRED_ROLES == {Role.REVIEWER, Role.ADMINISTRATOR}


def test_no_roles_confer_no_permissions() -> None:
    assert permissions_for([], assurance=MFA) == frozenset()


def test_administrator_holds_no_research_permission() -> None:
    administrator = permissions_for([Role.ADMINISTRATOR], assurance=MFA)

    assert administrator.isdisjoint({READ, CONTRIBUTE, REVIEW})


@pytest.mark.parametrize("permission", [MANAGE_ROLES, DEACTIVATE])
def test_only_administrator_holds_the_administrative_permissions(permission: Permission) -> None:
    holders = {role for role in Role if permission in ROLE_PERMISSIONS[role]}

    assert holders == {Role.ADMINISTRATOR}


@pytest.mark.parametrize("role", [Role.READER, Role.RESEARCHER, Role.REVIEWER])
def test_research_roles_hold_no_administrative_permission(role: Role) -> None:
    assert ROLE_PERMISSIONS[role].isdisjoint({MANAGE_ROLES, DEACTIVATE, APPROVE})


def test_only_administrator_can_approve_an_enrolment_and_never_on_a_password() -> None:
    holders = {role for role in Role if APPROVE in ROLE_PERMISSIONS[role]}

    assert holders == {Role.ADMINISTRATOR}
    assert APPROVE not in permissions_for(list(Role), assurance=PASSWORD)
    assert APPROVE in permissions_for([Role.ADMINISTRATOR], assurance=MFA)


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        ([], False),
        ([Role.READER], False),
        ([Role.RESEARCHER], False),
        ([Role.READER, Role.RESEARCHER], False),
        ([Role.REVIEWER], True),
        ([Role.ADMINISTRATOR], True),
        ([Role.READER, Role.REVIEWER], True),
        ([Role.RESEARCHER, Role.ADMINISTRATOR], True),
        (list(Role), True),
    ],
)
def test_enrolment_needs_approval_exactly_when_a_role_requires_a_second_factor(
    roles: list[Role], expected: bool
) -> None:
    assert enrollment_requires_approval(roles) is expected
    # The same roles, and no others, that confer less on a password.
    assert expected is any(role in MFA_REQUIRED_ROLES for role in roles)


def test_only_reviewer_can_review() -> None:
    holders = {role for role in Role if REVIEW in ROLE_PERMISSIONS[role]}

    assert holders == {Role.REVIEWER}


def test_several_roles_confer_the_union_of_their_permissions() -> None:
    held = permissions_for([Role.RESEARCHER, Role.ADMINISTRATOR], assurance=MFA)

    assert held == {READ, CONTRIBUTE, MANAGE_ROLES, DEACTIVATE, OWN_MFA, APPROVE}


def test_on_a_password_an_account_keeps_the_roles_that_need_no_second_factor() -> None:
    held = permissions_for([Role.READER, Role.REVIEWER, Role.ADMINISTRATOR], assurance=PASSWORD)

    assert held == {READ, OWN_MFA}


def test_no_combination_of_roles_confers_more_than_the_roles_do_separately() -> None:
    subsets = chain.from_iterable(combinations(Role, size) for size in range(len(Role) + 1))

    for roles in subsets:
        separately = frozenset().union(*(ROLE_PERMISSIONS[role] for role in roles))
        assert permissions_for(roles, assurance=MFA) == separately


@pytest.mark.parametrize("unknown", ["administrator ", "ADMINISTRATOR", "superuser", "", None, 1])
def test_something_that_is_not_a_role_confers_nothing(unknown: object) -> None:
    # The ignore below: the argument is deliberately not a Role; that is the case under test.
    assert permissions_for([unknown], assurance=MFA) == frozenset()  # type: ignore[list-item]


def test_the_policy_table_cannot_be_modified_at_run_time() -> None:
    with pytest.raises(TypeError):
        # The ignore below: assigning to the read-only mapping is the case under test.
        ROLE_PERMISSIONS[Role.READER] = frozenset(Permission)  # type: ignore[index]


def test_the_decision_is_deterministic() -> None:
    roles = [Role.REVIEWER, Role.READER]

    assert permissions_for(roles, assurance=MFA) == permissions_for(reversed(roles), assurance=MFA)
