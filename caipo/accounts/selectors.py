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
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import OuterRef, Q, QuerySet, Subquery
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from caipo.accounts.authentication import AuthenticationContext
from caipo.accounts.authorization import Assurance, Permission, Role, permissions_for
from caipo.accounts.models import (
    AccountActivation,
    AccountStatus,
    AuditAction,
    AuditField,
    AuditTargetType,
    AuthenticationEvent,
    AuthenticationEventType,
    BreakGlassAction,
    MfaRecoveryRequest,
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
    "AuditAction",
    "AuditField",
    "AuditTargetType",
    "AuthenticationContext",
    "EnrollmentRequest",
    "MfaState",
    "OpenRecovery",
    "Permission",
    "RecoveryHistoryEntry",
    "RecoveryHistoryPage",
    "RecoveryRequest",
    "Role",
    "accounts_awaiting_verification",
    "administrators_able_to_act",
    "administrators_on_record",
    "an_administrator_is_able_to_act",
    "an_administrator_was_ever_created",
    "authentication_context",
    "can",
    "enrollment_request_number_of",
    "enrollment_requests_awaiting_approval",
    "has_open_recovery",
    "last_recovery_of",
    "mfa_state_of",
    "open_recovery_authorizer_id",
    "open_recovery_of",
    "pending_enrollment_follows",
    "permissions_of",
    "recoveries_on_record",
    "recovery_history_of",
    "recovery_request_expires_at",
    "recovery_requests_awaiting_decision",
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


@dataclass(frozen=True)
class RecoveryRequest:
    """A request to recover a lost second factor that waits for an Administrator's decision.

    `number` is what the person who made the request was shown, so that the
    Administrator can ask them for it before authorising.
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


def recovery_request_expires_at(request: MfaRecoveryRequest) -> datetime:
    """Return when a recovery request lapses and can no longer be decided on."""
    return request.created_at + settings.MFA_RECOVERY_REQUEST_LIFETIME


def recovery_requests_awaiting_decision(
    context: AuthenticationContext,
) -> list[RecoveryRequest]:
    """Return the recovery requests the context may decide on, oldest first.

    Never the context's own, and none that has lapsed. Whether a request
    would be authorised is not decided here and is not shown: that is
    answered only by the service, and only as done or unavailable. Raises
    PermissionDenied if the context may not authorise recoveries.
    """
    require_permission(context, Permission.MFA_RECOVERY_AUTHORIZE)
    now = timezone.now()
    requests = (
        MfaRecoveryRequest.objects.exclude(user_id=context.user.pk)
        .select_related("user")
        .order_by("created_at", "id")
    )
    return [
        RecoveryRequest(
            number=request.pk, email=request.user.email, requested_at=request.created_at
        )
        for request in requests
        if now < recovery_request_expires_at(request)
    ]


def administrators_on_record(*, besides: Collection[int] = ()) -> list[int]:
    """Return the active accounts that hold the Administrator role on record, in ascending order.

    The count behind the last-Administrator rule: it asks for no second
    factor. `besides` holds account identifiers that are left out.
    """
    latest = (
        RoleEvent.objects.filter(role=Role.ADMINISTRATOR, user__status=AccountStatus.ACTIVE)
        .exclude(user_id__in=besides)
        .order_by("user_id", "-id")
        .distinct("user_id")
        .values_list("user_id", "event_type")
    )
    return [user_id for user_id, event_type in latest if event_type == RoleEventType.GRANTED]


def administrators_able_to_act(*, besides: Collection[int]) -> frozenset[int]:
    """Return the Administrators who are able to act, other than these accounts.

    Able to act (ADR-0017 point 39): the account is active, holds the
    Administrator role on record, and has an active, trusted second factor.
    This is narrower than `administrators_on_record`. `besides` holds account
    identifiers.
    """
    return frozenset(
        TotpDevice.objects.filter(
            user_id__in=administrators_on_record(besides=besides),
            state=TotpDeviceState.ACTIVE,
            approved_at__isnull=False,
        ).values_list("user_id", flat=True)
    )


def an_administrator_is_able_to_act(*, besides: Collection[int]) -> bool:
    """Return whether an Administrator who is able to act exists, other than these accounts.

    See `administrators_able_to_act`. `besides` holds account identifiers.
    """
    return bool(administrators_able_to_act(besides=besides))


# What opens a recovery: an Administrator's authorisation, or the revocation
# by the break-glass command. The one statement of it, for whether a recovery
# is open and for what the history of recoveries shows.
_RECOVERY_OPENER = Q(event_type=AuthenticationEventType.MFA_RECOVERY_AUTHORIZED) | Q(
    event_type=AuthenticationEventType.MFA_RECOVERY_BREAK_GLASS,
    break_glass_action=BreakGlassAction.REVOKE_DEVICE,
)


@dataclass(frozen=True)
class OpenRecovery:
    """A recovery of an account that was opened and is not complete.

    `opener_event_id` is the identifier of the event that opened it.
    `authorizer_id` is the Administrator who authorised it, and None if the
    break-glass command revoked the device: then nobody authorised, and the
    recovery is open all the same.
    """

    opener_event_id: int
    authorizer_id: int | None


def open_recovery_of(user_id: int) -> OpenRecovery | None:
    """Return the account's open recovery, or None if it has none.

    This is the one place that says whether an account has an open recovery.
    A recovery is opened by the most recent of two kinds of event of the
    account: an `mfa_recovery_authorized` event, which names the
    Administrator who authorised, or an `mfa_recovery_break_glass` event
    whose action is `revoke_device`, which names nobody (ADR-0017 points 45
    and 63). It is closed by an `mfa_recovery_completed` event recorded after
    that one, and by nothing else (point 49). A break-glass event whose
    action is `approve_enrollment` opens nothing and closes nothing.

    `services.confirm_mfa_enrollment` records the completion when an approved
    device of the account accepts its first code. The events decide and the
    state of the device does not: a recovery that was completed stays closed
    if that device is later disabled or replaced, and nothing is inferred
    here from the enrolment events in between. Which opening is the most
    recent, and whether a completion is after it, is read from the
    identifiers of the events, which the database issues in sequence, and
    never from their times.

    No second record of recovery state is kept anywhere else.
    `has_open_recovery` and `open_recovery_authorizer_id` are two questions
    asked of this one answer, and they are different questions: a recovery
    that the break-glass command opened is open and has no authoriser.
    """
    opener = (
        AuthenticationEvent.objects.filter(user_id=user_id)
        .filter(_RECOVERY_OPENER)
        .order_by("-id")
        .values_list("id", "actor_id")
        .first()
    )
    if opener is None:
        return None
    event_id, authorizer_id = opener
    completed = AuthenticationEvent.objects.filter(
        user_id=user_id,
        id__gt=event_id,
        event_type=AuthenticationEventType.MFA_RECOVERY_COMPLETED,
    ).exists()
    return None if completed else OpenRecovery(event_id, authorizer_id)


def has_open_recovery(user_id: int) -> bool:
    """Return whether the account has an open recovery, whoever or whatever opened it.

    What decides that a first code completes a recovery (ADR-0017 point 49).
    See `open_recovery_of`.
    """
    return open_recovery_of(user_id) is not None


def open_recovery_authorizer_id(user_id: int) -> int | None:
    """Return the Administrator who authorised the account's open recovery, or None.

    What decides who does not approve the account's enrolment (ADR-0017
    point 37). None does not mean that no recovery is open: it is also the
    answer for a recovery that the break-glass command opened, which nobody
    authorised and which therefore bars nobody. Whether a recovery is open is
    `has_open_recovery`. See `open_recovery_of`.
    """
    recovery = open_recovery_of(user_id)
    return None if recovery is None else recovery.authorizer_id


# The events that begin, decide, end, or give up an enrolment. A break-glass
# event is among them for its `approve_enrollment` action; its `revoke_device`
# action opens the recovery and so is never after it.
_ENROLLMENT_EVENT_TYPES = (
    AuthenticationEventType.MFA_ENROLLMENT_STARTED,
    AuthenticationEventType.MFA_ENROLLMENT_APPROVED,
    AuthenticationEventType.MFA_ENROLLMENT_REJECTED,
    AuthenticationEventType.MFA_ENROLLMENT_SUCCEEDED,
    AuthenticationEventType.MFA_DEVICE_REPLACED,
    AuthenticationEventType.MFA_DISABLED,
    AuthenticationEventType.MFA_RECOVERY_BREAK_GLASS,
)


def pending_enrollment_follows(user_id: int, recovery: OpenRecovery) -> bool:
    """Return whether the account's current enrolment request was made in this open recovery.

    It was if the account's latest enrolment event is an
    `mfa_enrollment_started` event recorded after the event that opened the
    recovery: the request that event records is then the one that stands, and
    nothing has decided, completed, or given it up since. An enrolment that
    succeeded earlier in the same recovery and was replaced afterwards does
    not count against the request that replaced it. Read from the identifiers
    of the events, never from their times. The caller holds the account's
    second-factor lock and has read the pending device under it.
    """
    latest = (
        AuthenticationEvent.objects.filter(
            user_id=user_id,
            id__gt=recovery.opener_event_id,
            event_type__in=_ENROLLMENT_EVENT_TYPES,
        )
        .order_by("-id")
        .values_list("event_type", flat=True)
        .first()
    )
    return latest == AuthenticationEventType.MFA_ENROLLMENT_STARTED


# How many steps one page of a history of recoveries shows. The record has no
# end: whoever knows an eligible account's password can add five requests to
# it every hour.
RECOVERY_HISTORY_PAGE_SIZE = 50

# The steps of a recovery that are shown whenever they were recorded. The
# approval of an enrolment is shown too, but only inside a recovery: see
# `_recovery_history`. A refused submission (`mfa_recovery_failed`) is not a
# step of any recovery and is never shown.
_RECOVERY_HISTORY_EVENT_TYPES = (
    AuthenticationEventType.MFA_RECOVERY_REQUESTED,
    AuthenticationEventType.MFA_RECOVERY_REJECTED,
    AuthenticationEventType.MFA_RECOVERY_AUTHORIZED,
    AuthenticationEventType.MFA_RECOVERY_COMPLETED,
    AuthenticationEventType.MFA_RECOVERY_BREAK_GLASS,
)

# What a person reads for each step. The names of the event types are for the
# record and are never shown.
_RECOVERY_HISTORY_LABELS = {
    AuthenticationEventType.MFA_RECOVERY_REQUESTED: _("Recovery requested"),
    AuthenticationEventType.MFA_RECOVERY_REJECTED: _(
        "Recovery request rejected by an Administrator"
    ),
    AuthenticationEventType.MFA_RECOVERY_AUTHORIZED: _(
        "Recovery authorised by an Administrator: the second factor was revoked"
    ),
    AuthenticationEventType.MFA_ENROLLMENT_APPROVED: _(
        "Enrolment of the new second factor approved by an Administrator"
    ),
    AuthenticationEventType.MFA_RECOVERY_COMPLETED: _(
        "Recovery completed: the new second factor accepted its first code"
    ),
}
_RECOVERY_HISTORY_SERVER_LABELS = {
    BreakGlassAction.REVOKE_DEVICE: _("Second factor revoked by the emergency procedure"),
    BreakGlassAction.APPROVE_ENROLLMENT: _(
        "Enrolment of the new second factor approved by the emergency procedure"
    ),
}


@dataclass(frozen=True)
class RecoveryHistoryEntry:
    """One step of a recovery, as a person is shown it (ADR-0017 point 78).

    Everything a page may show of the event, and nothing else of it: not its
    identifier, its type, its correlation ID, or either keyed hash. `label`
    says what happened, in words. `actor_email` is the Administrator who
    decided, and None where no account of the application did.
    `performed_at_server` says that the break-glass command performed the
    step: then nobody is named, because whoever ran the command is not an
    account, and the application does not know who it was.
    """

    occurred_at: datetime
    label: str
    account_email: str
    actor_email: str | None
    performed_at_server: bool


@dataclass(frozen=True)
class RecoveryHistoryPage:
    """One page of a history of recoveries, latest step first."""

    entries: tuple[RecoveryHistoryEntry, ...]
    number: int
    has_previous: bool
    has_next: bool


def _recovery_history() -> QuerySet[AuthenticationEvent]:
    """Return the events that a history of recoveries shows, latest first.

    The six steps of ADR-0017 point 78 and security property 6: a request, a
    rejection, an authorisation, a completion, each action of the break-glass
    command, and the approval of an enrolment inside a recovery. An approval
    is inside a recovery if, of the account's events that open or complete
    one, the latest before it is an opening (`_RECOVERY_OPENER`): the
    derivation of `open_recovery_of`, asked of the moment of the approval. The
    approval of an enrolment that follows no recovery is not shown.

    Every such event names its account. Ordered by the identifiers of the
    events, which the database issues in sequence, and never by their times;
    what is inside a recovery is read from the identifiers too.
    """
    boundary = (
        AuthenticationEvent.objects.filter(user_id=OuterRef("user_id"), id__lt=OuterRef("id"))
        .filter(_RECOVERY_OPENER | Q(event_type=AuthenticationEventType.MFA_RECOVERY_COMPLETED))
        .order_by("-id")
        .values("event_type")[:1]
    )
    return (
        AuthenticationEvent.objects.annotate(previous_boundary=Subquery(boundary))
        .filter(
            Q(event_type__in=_RECOVERY_HISTORY_EVENT_TYPES)
            | Q(
                event_type=AuthenticationEventType.MFA_ENROLLMENT_APPROVED,
                previous_boundary__in=(
                    AuthenticationEventType.MFA_RECOVERY_AUTHORIZED,
                    AuthenticationEventType.MFA_RECOVERY_BREAK_GLASS,
                ),
            )
        )
        .order_by("-id")
    )


def _recovery_history_page(events: QuerySet[AuthenticationEvent], page: int) -> RecoveryHistoryPage:
    """Return one page of the events as what a person is shown of them.

    An event's type and its break-glass action are read as stored, to map
    them to the fixed labels a person reads, and the two values as stored do
    not leave this module. No identifier of an event is exposed, and never
    its correlation ID or either keyed hash. A page number that is not a page
    gets the nearest one: the first for anything below it, the last for
    anything above.
    """
    rows = events.values_list(
        "created_at", "event_type", "break_glass_action", "user__email", "actor__email"
    )
    shown = Paginator(rows, RECOVERY_HISTORY_PAGE_SIZE).get_page(page)
    return RecoveryHistoryPage(
        entries=tuple(
            _recovery_history_entry(occurred_at, event_type, action, account_email, actor_email)
            for occurred_at, event_type, action, account_email, actor_email in shown.object_list
        ),
        number=shown.number,
        has_previous=shown.has_previous(),
        has_next=shown.has_next(),
    )


def _recovery_history_entry(
    occurred_at: datetime,
    event_type: str,
    action: str,
    account_email: str,
    actor_email: str | None,
) -> RecoveryHistoryEntry:
    at_server = event_type == AuthenticationEventType.MFA_RECOVERY_BREAK_GLASS
    label = (
        _RECOVERY_HISTORY_SERVER_LABELS[BreakGlassAction(action)]
        if at_server
        else _RECOVERY_HISTORY_LABELS[AuthenticationEventType(event_type)]
    )
    return RecoveryHistoryEntry(
        occurred_at=occurred_at,
        label=str(label),
        account_email=account_email,
        actor_email=actor_email,
        performed_at_server=at_server,
    )


def recovery_history_of(context: AuthenticationContext, *, page: int = 1) -> RecoveryHistoryPage:
    """Return the history of the recoveries of the context's own account, latest step first.

    There is no parameter that could name another account: the account is the
    one the context acts as. It needs only the permission every role holds on
    its password, because an account whose second factor was just revoked has
    no second factor to verify (ADR-0017 point 78). What is shown is said by
    `_recovery_history` and `RecoveryHistoryEntry`.

    Reads only. Raises PermissionDenied if the context may not manage its own
    second factor.
    """
    require_permission(context, Permission.MFA_MANAGE_OWN)
    return _recovery_history_page(_recovery_history().filter(user_id=context.user.pk), page)


def recoveries_on_record(context: AuthenticationContext, *, page: int = 1) -> RecoveryHistoryPage:
    """Return the history of the recoveries of every account, latest step first.

    What the Administrators see (ADR-0017 point 78): every request,
    rejection, authorisation, and use of the break-glass command, with the
    approvals and completions that follow, of every account including the
    context's own. What is shown of each is said by `_recovery_history` and
    `RecoveryHistoryEntry`.

    Reads only. Raises PermissionDenied if the context may not authorise
    recoveries, a permission that exists only for an Administrator verified
    against a trusted second factor.
    """
    require_permission(context, Permission.MFA_RECOVERY_AUTHORIZE)
    return _recovery_history_page(_recovery_history(), page)


def last_recovery_of(context: AuthenticationContext) -> datetime | None:
    """Return when the second factor of the context's own account was last revoked by a recovery.

    None if it never was. The time is that of the account's most recent
    opening event (`_RECOVERY_OPENER`), which is the most recent by its
    identifier. Nothing records whether the account has seen it: the answer
    is the same every time it is asked.

    Raises PermissionDenied if the context may not manage its own second
    factor.
    """
    require_permission(context, Permission.MFA_MANAGE_OWN)
    return (
        AuthenticationEvent.objects.filter(user_id=context.user.pk)
        .filter(_RECOVERY_OPENER)
        .order_by("-id")
        .values_list("created_at", flat=True)
        .first()
    )


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
