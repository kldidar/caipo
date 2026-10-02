"""Read interface of the accounts app: who holds which role, and who may do what.

This is where every authorization question is answered, for views and for
services alike. The answers come from the database and from nothing a caller
or a browser supplies: a role is held only if a RoleEvent says so.

`can` answers yes or no and never raises. `require_permission` is the same
decision for code that must stop when the answer is no.
"""

import logging

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied

from caipo.accounts import mfa
from caipo.accounts.authorization import Permission, Role, permissions_for
from caipo.accounts.models import RoleEvent, RoleEventType, User

__all__ = ["Permission", "Role", "can", "permissions_of", "require_permission", "roles_of"]

logger = logging.getLogger(__name__)


def _granted_roles(user_id: int, *, active_accounts_only: bool) -> frozenset[Role]:
    events = RoleEvent.objects.filter(user_id=user_id)
    if active_accounts_only:
        events = events.filter(user__is_active=True)
    # The latest event for each role decides. Ordered by identifier, which the
    # database issues in sequence, not by timestamp, which can tie.
    latest = events.order_by("role", "-id").distinct("role").values_list("role", "event_type")
    return frozenset(
        Role(role) for role, event_type in latest if event_type == RoleEventType.GRANTED
    )


def roles_of(user: User) -> frozenset[Role]:
    """Return the roles the account has been granted and not had revoked.

    This is the record, not an authorization decision: it includes roles that
    confer nothing at present, because the account is deactivated or has not
    enrolled a second factor. Use `can` to decide access.
    """
    if user.pk is None:
        return frozenset()
    return _granted_roles(user.pk, active_accounts_only=False)


def permissions_of(user: User | AnonymousUser | None) -> frozenset[Permission]:
    """Return the permissions the account holds now.

    Empty for an anonymous visitor, for anything that is not a saved User, and
    for a deactivated account. Whether the account is active is read from the
    database, not from the object passed in, which may be stale.
    """
    if not isinstance(user, User) or user.pk is None or not user.is_active:
        return frozenset()
    roles = _granted_roles(user.pk, active_accounts_only=True)
    return permissions_for(roles, mfa_enrolled=mfa.is_enrolled(user))


def can(user: User | AnonymousUser | None, permission: Permission) -> bool:
    """Return whether the account holds the permission now. Never raises."""
    return permission in permissions_of(user)


def require_permission(user: User | AnonymousUser | None, permission: Permission) -> None:
    """Stop unless the account holds the permission.

    Services call this themselves, whatever the view that called them has
    already checked. Raises PermissionDenied, and logs the refusal, if the
    permission is not held.
    """
    if not can(user, permission):
        logger.warning(
            "Permission denied",
            extra={
                "event": "authorization.denied",
                "permission": permission.value,
                "user_id": user.pk if isinstance(user, User) else None,
            },
        )
        raise PermissionDenied
