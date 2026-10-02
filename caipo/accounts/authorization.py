"""Roles, permissions, and the policy that connects them (ADR-0007).

This module is the whole authorization policy and nothing else: it touches no
database and knows nothing of HTTP, so every decision it makes can be tested as
a plain function. Other apps reach it through `caipo.accounts.selectors`.

A permission is what code asks for. A role is what an account is given. Code
never asks "is this an Administrator?"; it asks whether a permission is held,
and only this module knows which roles hold it.
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


class Permission(StrEnum):
    """What the system can ask about an account.

    Kept as small as the system is. ROLES_MANAGE and ACCOUNTS_DEACTIVATE are
    checked by services today. The other three exist so that the four roles
    are distinguishable and views can declare the access they require; no
    operation consumes them yet. They are deliberately coarse and are to be
    split only when a feature needs a finer distinction.

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
    # Deactivate an account.
    ACCOUNTS_DEACTIVATE = "accounts.deactivate"


# Each role's permissions, written out in full (PROJECT_SPECIFICATION.md §3).
# A role absent from this table, or a permission absent from a role's set,
# means no. Administrator is not a superset of the research roles: operating
# the system gives no say over the evidence base. A person who needs both is
# granted both roles.
ROLE_PERMISSIONS: Mapping[Role, frozenset[Permission]] = MappingProxyType(
    {
        Role.READER: frozenset({Permission.WORKSPACE_READ}),
        Role.RESEARCHER: frozenset({Permission.WORKSPACE_READ, Permission.RESEARCH_CONTRIBUTE}),
        Role.REVIEWER: frozenset(
            {
                Permission.WORKSPACE_READ,
                Permission.RESEARCH_CONTRIBUTE,
                Permission.RESEARCH_REVIEW,
            }
        ),
        Role.ADMINISTRATOR: frozenset({Permission.ROLES_MANAGE, Permission.ACCOUNTS_DEACTIVATE}),
    }
)

# ADR-0007 rule 4: such an account cannot use its privileges until TOTP is
# enrolled.
MFA_REQUIRED_ROLES: frozenset[Role] = frozenset({Role.REVIEWER, Role.ADMINISTRATOR})


def permissions_for(roles: Iterable[Role], *, mfa_enrolled: bool) -> frozenset[Permission]:
    """Return the permissions that a set of granted roles confers.

    A role that requires multi-factor authentication confers nothing, not even
    what a lesser role would, unless the account is enrolled. An account that
    should work without it in the meantime is granted another role as well.
    Anything that is not one of the four roles confers nothing.
    """
    permissions: set[Permission] = set()
    for role in roles:
        if role in MFA_REQUIRED_ROLES and not mfa_enrolled:
            continue
        permissions |= ROLE_PERMISSIONS.get(role, frozenset())
    return frozenset(permissions)
