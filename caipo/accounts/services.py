"""Write interface of the accounts app: changing roles and deactivating accounts.

Every operation here runs as one transaction and holds a lock that lets only
one of them proceed at a time, so each decides on what the previous one left
and none can see a half-made change. The actor's permission is checked inside
that lock, not before it.
"""

import logging

from django.core.exceptions import PermissionDenied
from django.db import connection, transaction

from caipo.accounts import selectors
from caipo.accounts.authorization import Permission, Role
from caipo.accounts.models import RoleEvent, RoleEventType, User

logger = logging.getLogger(__name__)


class AccountChangeError(Exception):
    """The requested change to an account cannot be made."""


class RoleChangeError(AccountChangeError):
    """The requested role change would not change anything."""


class LastAdministratorError(AccountChangeError):
    """The change would leave the system with no Administrator."""


def grant_role(*, actor: User, user: User, role: Role, reason: str) -> RoleEvent:
    """Grant a role to another user and record who did it and why.

    Preconditions: the actor holds the permission to manage roles, the user is
    not the actor, and the reason is not blank. Side effects: one RoleEvent is
    appended and the change is logged. Nothing existing is modified.

    Raises PermissionDenied if the actor may not manage roles or is the user,
    ValueError if the role is not one of the four roles or the reason is
    blank, and RoleChangeError if the user already holds the role.
    """
    return _change_role(actor, user, role, reason, RoleEventType.GRANTED)


def revoke_role(*, actor: User, user: User, role: Role, reason: str) -> RoleEvent:
    """Revoke a role from another user and record who did it and why.

    Preconditions, side effects, and errors are those of `grant_role`, except
    that RoleChangeError is raised if the user does not hold the role, and
    LastAdministratorError if the change would leave no Administrator. The
    grant being revoked stays on record.
    """
    return _change_role(actor, user, role, reason, RoleEventType.REVOKED)


def deactivate_user(*, actor: User, user: User) -> None:
    """Deactivate an account, which then holds no permission and cannot be used.

    Preconditions: the actor holds the permission to deactivate accounts. An
    actor may deactivate their own account: that gives up power and gains
    none. Side effects: the account is marked inactive, in the database and on
    the object passed in, and the change is logged. Its role record is kept.

    Raises PermissionDenied if the actor may not deactivate accounts,
    AccountChangeError if the account is already inactive, and
    LastAdministratorError if it is the only active Administrator.
    """
    with transaction.atomic():
        _serialize_account_changes()
        selectors.require_permission(actor, Permission.ACCOUNTS_DEACTIVATE)
        # Read again: the object passed in may be out of date.
        target = User.objects.get(pk=user.pk)
        if not target.is_active:
            raise AccountChangeError("The account is already inactive.")
        if Role.ADMINISTRATOR in selectors.roles_of(target):
            _require_another_administrator(besides=target)
        target.is_active = False
        target.save(update_fields=["is_active", "updated_at"])

    user.is_active = False
    logger.info(
        "Account deactivated",
        extra={"event": "accounts.deactivated", "user_id": user.pk, "actor_id": actor.pk},
    )


def _change_role(
    actor: User, user: User, role: Role, reason: str, event_type: RoleEventType
) -> RoleEvent:
    with transaction.atomic():
        _serialize_account_changes()
        # Permission first, so that a caller without it learns nothing about
        # the user or about which inputs are valid.
        selectors.require_permission(actor, Permission.ROLES_MANAGE)
        if actor.pk == user.pk:
            logger.warning(
                "Refused a change to the actor's own roles",
                extra={"event": "accounts.own_role_change_refused", "user_id": actor.pk},
            )
            raise PermissionDenied
        role = Role(role)
        reason = reason.strip()
        if not reason:
            raise ValueError("A reason is required.")

        holds_role = role in selectors.roles_of(user)
        if event_type == RoleEventType.GRANTED and holds_role:
            raise RoleChangeError("The user already holds this role.")
        if event_type == RoleEventType.REVOKED and not holds_role:
            raise RoleChangeError("The user does not hold this role.")
        if event_type == RoleEventType.REVOKED and role == Role.ADMINISTRATOR:
            # The actor is a different, active Administrator, so this cannot
            # fail today. It is checked all the same, so that the rule holds
            # here by itself and not as a consequence of another rule.
            _require_another_administrator(besides=user)
        event = RoleEvent.objects.create(
            user=user, role=role, event_type=event_type, actor=actor, reason=reason
        )

    logger.info(
        "Role %s",
        event_type.value,
        extra={
            "event": f"accounts.role_{event_type.value}",
            "role": role.value,
            "user_id": user.pk,
            "actor_id": actor.pk,
            "role_event_id": event.pk,
        },
    )
    return event


def _serialize_account_changes() -> None:
    """Let one account change proceed at a time, until its transaction ends.

    A lock on the role event table that conflicts with itself and with
    inserts, and with nothing that only reads. Locking the affected user rows
    would not be enough: whether an Administrator remains depends on every
    account at once, and two changes to different accounts could each see the
    other's Administrator still in place.
    """
    with connection.cursor() as cursor:
        cursor.execute("LOCK TABLE accounts_roleevent IN SHARE ROW EXCLUSIVE MODE")


def _require_another_administrator(*, besides: User) -> None:
    """Raise LastAdministratorError unless an active Administrator other than this one exists.

    Counts accounts that are active and hold the role on record, whether or
    not they have enrolled a second factor.
    """
    latest = (
        RoleEvent.objects.filter(role=Role.ADMINISTRATOR, user__is_active=True)
        .exclude(user=besides)
        .order_by("user_id", "-id")
        .distinct("user_id")
        .values_list("event_type", flat=True)
    )
    if RoleEventType.GRANTED not in set(latest):
        raise LastAdministratorError("This would leave the system with no Administrator.")
