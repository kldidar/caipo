"""Read interface of the accounts app: who holds which role, and who may do what.

This is where every authorization question is answered, for views and for
services alike. The question is always asked about an authentication context:
an account and the assurance it is acting at. The answers come from the
database and from nothing a caller or a browser supplies: a role is held only
if a RoleEvent says so, and a second factor counts as verified only if the
device the context names is that account's active, trusted one.

`can` answers yes or no and never raises. `require_permission` is the same
decision for code that must stop when the answer is no.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from caipo.accounts.authentication import AuthenticationContext
from caipo.accounts.authorization import Assurance, Permission, Role, permissions_for
from caipo.accounts.models import (
    AccountActivation,
    AccountStatus,
    RoleEvent,
    RoleEventType,
    TotpDevice,
    TotpDeviceState,
    User,
)

__all__ = [
    "AccountAwaitingVerification",
    "AccountStatus",
    "Assurance",
    "AuthenticationContext",
    "EnrollmentRequest",
    "MfaState",
    "Permission",
    "Role",
    "accounts_awaiting_verification",
    "an_administrator_was_ever_created",
    "authentication_context",
    "can",
    "enrollment_request_number_of",
    "enrollment_requests_awaiting_approval",
    "mfa_state_of",
    "permissions_of",
    "require_permission",
    "roles_of",
]

logger = logging.getLogger(__name__)


class MfaState(StrEnum):
    """Where an account stands with its second factor."""

    NOT_ENROLLED = "not_enrolled"
    # A secret was issued and an Administrator has yet to approve the request.
    # No code is accepted for it. Grants nothing.
    PENDING_APPROVAL = "pending_approval"
    # A secret was issued and is waiting for its first code. Grants nothing.
    PENDING_VERIFICATION = "pending_verification"
    ACTIVE = "active"


@dataclass(frozen=True)
class EnrollmentRequest:
    """An enrolment that waits for an Administrator's decision.

    `number` is what the person who made the request was shown, so that the
    Administrator can ask them for it before approving.
    """

    number: int
    email: str
    requested_at: datetime


def _granted_roles(user_id: int, *, active_accounts_only: bool) -> frozenset[Role]:
    events = RoleEvent.objects.filter(user_id=user_id)
    if active_accounts_only:
        events = events.filter(user__status=AccountStatus.ACTIVE)
    # The latest event for each role decides. Ordered by identifier, which the
    # database issues in sequence, not by timestamp, which can tie.
    latest = events.order_by("role", "-id").distinct("role").values_list("role", "event_type")
    return frozenset(
        Role(role) for role, event_type in latest if event_type == RoleEventType.GRANTED
    )


def an_administrator_was_ever_created() -> bool:
    """Return whether any Administrator role event exists.

    Once one does, the first-Administrator bootstrap is closed for good,
    whatever has happened to that account since.
    """
    return RoleEvent.objects.filter(role=Role.ADMINISTRATOR).exists()


def roles_of(user: User) -> frozenset[Role]:
    """Return the roles the account has been granted and not had revoked.

    This is the record, not an authorization decision: it includes roles that
    confer nothing at present, because the account is deactivated or no
    second-factor code has been verified. Use `can` to decide access.
    """
    if user.pk is None:
        return frozenset()
    return _granted_roles(user.pk, active_accounts_only=False)


def enrollment_expires_at(device: TotpDevice) -> datetime:
    """Return when a pending enrolment becomes void.

    An enrolment that needs no approval is confirmed at once or not at all.
    One that needs approval waits for a person: MFA_APPROVAL_LIFETIME from the
    request for the decision, and as long again from the approval for the
    first code.
    """
    if device.approved_at is not None:
        return device.approved_at + settings.MFA_APPROVAL_LIFETIME
    if device.state == TotpDeviceState.PENDING_APPROVAL:
        return device.created_at + settings.MFA_APPROVAL_LIFETIME
    return device.created_at + settings.MFA_ENROLLMENT_LIFETIME


def mfa_state_of(user: User) -> MfaState:
    """Return where the account stands with its second factor.

    This is the record, not an authorization decision, and it says nothing
    about whether anyone has verified a code or whether the second factor is
    trusted. A pending enrolment that was not approved or confirmed in time
    counts as not enrolled.
    """
    device = TotpDevice.objects.filter(user_id=user.pk).first()
    if device is None:
        return MfaState.NOT_ENROLLED
    if device.state == TotpDeviceState.ACTIVE:
        return MfaState.ACTIVE
    if timezone.now() >= enrollment_expires_at(device):
        return MfaState.NOT_ENROLLED
    if device.state == TotpDeviceState.PENDING_APPROVAL:
        return MfaState.PENDING_APPROVAL
    return MfaState.PENDING_VERIFICATION


def enrollment_request_number_of(user: User) -> int | None:
    """Return the number of the account's own request that awaits approval, if any.

    The number identifies one issued secret. A request that replaced it has
    another number, so an Administrator who asks the person for theirs cannot
    be led to approve somebody else's.
    """
    device = TotpDevice.objects.filter(
        user_id=user.pk, state=TotpDeviceState.PENDING_APPROVAL
    ).first()
    if device is None or timezone.now() >= enrollment_expires_at(device):
        return None
    return device.pk


def enrollment_requests_awaiting_approval(
    context: AuthenticationContext,
) -> list[EnrollmentRequest]:
    """Return the enrolment requests the context may decide on, oldest first.

    Never the context's own, and none that has lapsed. Raises PermissionDenied
    if the context may not approve enrolments.
    """
    require_permission(context, Permission.MFA_ENROLLMENT_APPROVE)
    now = timezone.now()
    devices = (
        TotpDevice.objects.filter(state=TotpDeviceState.PENDING_APPROVAL)
        .exclude(user_id=context.user.pk)
        .select_related("user")
        .order_by("created_at", "id")
    )
    return [
        EnrollmentRequest(number=device.pk, email=device.user.email, requested_at=device.created_at)
        for device in devices
        if now < enrollment_expires_at(device)
    ]


def authentication_context(
    user: User | AnonymousUser | None, *, verified_device_id: object = None
) -> AuthenticationContext | None:
    """Return the context an established sign-in acts in, or None for an anonymous visitor.

    `verified_device_id` is what the caller's own server-side record of the
    sign-in says a code was verified against, if anything. It is a claim: the
    context is MFA_VERIFIED only in name until `can` has checked the device.
    Anything that is not an integer is no claim at all.
    """
    if not isinstance(user, User):
        return None
    if isinstance(verified_device_id, int) and not isinstance(verified_device_id, bool):
        return AuthenticationContext(user, Assurance.MFA_VERIFIED, verified_device_id)
    return AuthenticationContext(user, Assurance.PASSWORD_AUTHENTICATED)


@dataclass(frozen=True)
class AccountAwaitingVerification:
    """An account that was created and has not been activated.

    `verification_expires_at` is when the message last sent stops working, or
    None if no usable message is outstanding and one must be sent again.
    """

    user_id: int
    email: str
    created_at: datetime
    verification_expires_at: datetime | None


def activation_expires_at(activation: AccountActivation) -> datetime:
    """Return when an activation token stops working."""
    return activation.created_at + settings.ACCOUNT_ACTIVATION_LIFETIME


def accounts_awaiting_verification(
    context: AuthenticationContext,
) -> list[AccountAwaitingVerification]:
    """Return the accounts that await verification, oldest first.

    Raises PermissionDenied if the context may not create accounts.
    """
    require_permission(context, Permission.ACCOUNTS_CREATE)
    now = timezone.now()
    expiries = {
        activation.user_id: activation_expires_at(activation)
        for activation in AccountActivation.objects.all()
    }
    return [
        AccountAwaitingVerification(
            user_id=user.pk,
            email=user.email,
            created_at=user.created_at,
            verification_expires_at=(
                expiries[user.pk] if user.pk in expiries and now < expiries[user.pk] else None
            ),
        )
        for user in User.objects.filter(status=AccountStatus.PENDING_VERIFICATION).order_by(
            "created_at", "id"
        )
    ]


def _proven_assurance(context: AuthenticationContext) -> Assurance:
    """Return the assurance the context can be shown to have.

    MFA_VERIFIED needs both halves: the context says a code was verified, and
    the device it names is this account's active, trusted second factor now.
    Neither the claim alone nor the database row alone is enough. A device
    that no Administrator approved was enrolled on the password alone, so a
    code from it adds nothing to the password.
    """
    if (
        context.assurance is Assurance.MFA_VERIFIED
        and context.mfa_device_id is not None
        and TotpDevice.objects.filter(
            pk=context.mfa_device_id,
            user_id=context.user.pk,
            state=TotpDeviceState.ACTIVE,
            approved_at__isnull=False,
        ).exists()
    ):
        return Assurance.MFA_VERIFIED
    return Assurance.PASSWORD_AUTHENTICATED


def permissions_of(context: AuthenticationContext | None) -> frozenset[Permission]:
    """Return the permissions the context holds now.

    Empty for an anonymous visitor, for anything that is not a context around
    a saved User, and for a deactivated account. Whether the account is active
    is read from the database, not from the object passed in, which may be
    stale. An account passed without a context holds nothing: there is no
    assurance to decide on.
    """
    if not isinstance(context, AuthenticationContext):
        return frozenset()
    user = context.user
    if not isinstance(user, User) or user.pk is None or not user.is_active:
        return frozenset()
    roles = _granted_roles(user.pk, active_accounts_only=True)
    if not roles:
        return frozenset()
    return permissions_for(roles, assurance=_proven_assurance(context))


def can(context: AuthenticationContext | None, permission: Permission) -> bool:
    """Return whether the context holds the permission now. Never raises."""
    return permission in permissions_of(context)


def require_permission(context: AuthenticationContext | None, permission: Permission) -> None:
    """Stop unless the context holds the permission.

    Services call this themselves, whatever the view that called them has
    already checked. Raises PermissionDenied, and logs the refusal, if the
    permission is not held.
    """
    if not can(context, permission):
        logger.warning(
            "Permission denied",
            extra={
                "event": "authorization.denied",
                "permission": permission.value,
                "user_id": _user_id(context),
            },
        )
        raise PermissionDenied


def _user_id(context: object) -> int | None:
    user = getattr(context, "user", None)
    return user.pk if isinstance(user, User) else None
