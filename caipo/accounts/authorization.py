"""Roles, permissions, assurance, and the policy that connects them (ADR-0007, ADR-0014).

This module is the whole authorization policy and nothing else: it touches no
database and knows nothing of HTTP, so every decision it makes can be tested as
a plain function. Other apps reach it through `caipo.accounts.selectors`.

A permission is what code asks for. A role is what an account is given. An
assurance is how strongly the person acting has proved who they are. Code never
asks "is this an Administrator?" or "has this account a second factor?"; it
asks whether a permission is held, and only this module knows which roles hold
it and at which assurance.
"""

from collections.abc import Iterable, Mapping
from enum import StrEnum
from types import MappingProxyType

from django.db import models
from django.utils.translation import gettext_lazy as _


class Role(models.TextChoices):
    """The four roles of ADR-0007. There are no others.

    The values are stored in the database and must never change. An account
    may hold several roles; there is no hierarchy between them. What each role
    can do is stated in full in ROLE_PERMISSIONS.
    """

    READER = "reader", _("Reader")
    RESEARCHER = "researcher", _("Researcher")
    REVIEWER = "reviewer", _("Reviewer")
    ADMINISTRATOR = "administrator", _("Administrator")


class Assurance(StrEnum):
    """How strongly the person acting has proved who they are.

    There are two levels and no others. Anything that is not MFA_VERIFIED is
    treated as the weaker one.
    """

    # The account's password was checked. The noqa below: this names an
    # assurance level; it is not a credential.
    PASSWORD_AUTHENTICATED = "password_authenticated"  # noqa: S105
    # The password was checked, and so was a code from the account's active,
    # trusted second factor: one an Administrator approved, or the one the
    # first-Administrator bootstrap established. A code from a second factor
    # that was enrolled on a password alone proves no more than that password.
    MFA_VERIFIED = "mfa_verified"


class Permission(StrEnum):
    """What the system can ask about an account.

    Kept as small as the system is. ROLES_MANAGE, the three ACCOUNTS
    permissions, MFA_MANAGE_OWN, and MFA_ENROLLMENT_APPROVE are checked by
    services and selectors today. The other three exist so
    that the four roles are distinguishable and views can declare the access
    they require; no operation consumes them yet. They are deliberately coarse
    and are to be split only when a feature needs a finer distinction.

    Reading the public research site needs no permission: it is open to
    anonymous visitors, who hold none.
    """

    # Browse approved content in the research workspace.
    WORKSPACE_READ = "workspace.read"
    # Add to the evidence base: register sources, submit documents and
    # datasets, code policies, record searches, draft claims.
    RESEARCH_CONTRIBUTE = "research.contribute"
    # Decide on it: approve documents, set rights, change a source's allowed
    # hosts, approve or return claims.
    RESEARCH_REVIEW = "research.review"
    # Grant and revoke roles.
    ROLES_MANAGE = "accounts.roles.manage"
    # Create an account, and send its verification message again.
    ACCOUNTS_CREATE = "accounts.create"
    # Disable an account.
    ACCOUNTS_DEACTIVATE = "accounts.deactivate"
    # Enable a disabled account.
    ACCOUNTS_ENABLE = "accounts.enable"
    # Enrol, confirm, and disable the account's own second factor.
    MFA_MANAGE_OWN = "accounts.mfa.manage_own"
    # Approve or reject another account's request to enrol a second factor.
    MFA_ENROLLMENT_APPROVE = "accounts.mfa.approve_enrollment"


# Each role's permissions, written out in full (PROJECT_SPECIFICATION.md §3).
# A role absent from this table, or a permission absent from a role's set,
# means no. Administrator is not a superset of the research roles: operating
# the system gives no say over the evidence base. A person who needs both is
# granted both roles.
ROLE_PERMISSIONS: Mapping[Role, frozenset[Permission]] = MappingProxyType(
    {
        Role.READER: frozenset({Permission.WORKSPACE_READ, Permission.MFA_MANAGE_OWN}),
        Role.RESEARCHER: frozenset(
            {
                Permission.WORKSPACE_READ,
                Permission.RESEARCH_CONTRIBUTE,
                Permission.MFA_MANAGE_OWN,
            }
        ),
        Role.REVIEWER: frozenset(
            {
                Permission.WORKSPACE_READ,
                Permission.RESEARCH_CONTRIBUTE,
                Permission.RESEARCH_REVIEW,
                Permission.MFA_MANAGE_OWN,
            }
        ),
        Role.ADMINISTRATOR: frozenset(
            {
                Permission.ROLES_MANAGE,
                Permission.ACCOUNTS_CREATE,
                Permission.ACCOUNTS_DEACTIVATE,
                Permission.ACCOUNTS_ENABLE,
                Permission.MFA_MANAGE_OWN,
                Permission.MFA_ENROLLMENT_APPROVE,
            }
        ),
    }
)

# ADR-0007 rule 4: such an account cannot use its privileges until a code from
# its enrolled second factor has been verified.
MFA_REQUIRED_ROLES: frozenset[Role] = frozenset({Role.REVIEWER, Role.ADMINISTRATOR})

# The whole of what such a role confers on a password alone. Without it an
# account holding only these roles could never enrol the second factor that
# the rest of its permissions wait for.
PERMISSIONS_BEFORE_MFA: frozenset[Permission] = frozenset({Permission.MFA_MANAGE_OWN})


def permissions_for(roles: Iterable[Role], *, assurance: Assurance) -> frozenset[Permission]:
    """Return the permissions that a set of granted roles confers at an assurance.

    A role that requires multi-factor authentication confers only
    PERMISSIONS_BEFORE_MFA, and nothing that a lesser role would, unless the
    assurance is MFA_VERIFIED. An account that should work on a password in
    the meantime is granted another role as well. Anything that is not one of
    the four roles confers nothing, and anything that is not MFA_VERIFIED
    counts as the weaker assurance.
    """
    permissions: set[Permission] = set()
    for role in roles:
        conferred = ROLE_PERMISSIONS.get(role, frozenset())
        if role in MFA_REQUIRED_ROLES and assurance is not Assurance.MFA_VERIFIED:
            conferred &= PERMISSIONS_BEFORE_MFA
        permissions |= conferred
    return frozenset(permissions)


def enrollment_requires_approval(roles: Iterable[Role]) -> bool:
    """Return whether an account holding these roles needs approval to enrol a second factor.

    It does if any of its roles requires a second factor. For such an account
    the second factor is what its privileges rest on, so the password that
    would otherwise be enough to enrol one must not be: an Administrator
    approves the request first (ADR-0014).
    """
    return any(role in MFA_REQUIRED_ROLES for role in roles)
