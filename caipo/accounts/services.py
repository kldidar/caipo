"""Write interface of the accounts app: signing in and out, changing roles,
deactivating accounts, and creating the first Administrator.

Every account change here runs as one transaction and holds a lock that lets
only one of them proceed at a time, so each decides on what the previous one
left and none can see a half-made change. The actor's permission is checked
inside that lock, not before it.

Nothing here takes a request. A sign-in is given an email address, a password,
and the address it came from, and answers with an outcome; establishing the
session is the caller's business.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db import connection, transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.debug import sensitive_variables

from caipo.accounts import selectors
from caipo.accounts.authorization import Permission, Role
from caipo.accounts.models import (
    AuthenticationEvent,
    AuthenticationEventType,
    RoleEvent,
    RoleEventType,
    User,
)
from caipo.core.correlation import get_correlation_id

logger = logging.getLogger(__name__)

# Advisory lock classes: one sign-in attempt at a time for a source, and for
# an email address.
_SOURCE_LOCK = 1
_IDENTIFIER_LOCK = 2


class AccountChangeError(Exception):
    """The requested change to an account cannot be made."""


class RoleChangeError(AccountChangeError):
    """The requested role change would not change anything."""


class LastAdministratorError(AccountChangeError):
    """The change would leave the system with no Administrator."""


class FirstAdministratorExistsError(AccountChangeError):
    """An Administrator has already been created; the bootstrap is closed."""


class SignInOutcome(StrEnum):
    SIGNED_IN = "signed_in"
    # Wrong password, unknown email address, and deactivated account are one
    # outcome on purpose: a caller cannot tell them apart, so neither can
    # whoever is asking.
    REFUSED = "refused"
    THROTTLED = "throttled"


@dataclass(frozen=True)
class SignInResult:
    outcome: SignInOutcome
    # Set only when the outcome is SIGNED_IN.
    user: User | None = None


@sensitive_variables("password")
def sign_in(*, email: str, password: str, source: str) -> SignInResult:
    """Check an email address and password, and record the attempt.

    `source` is the network address the attempt came from, as the caller
    established it. It is used to count attempts and is stored only as a keyed
    hash.

    Side effects: an AuthenticationEvent is appended for a success or a
    refusal, and the attempt is logged without the email address or password.
    A throttled attempt is logged and appends nothing, so that refused
    requests cannot be used to fill the table. No session is created.

    Never raises for bad credentials. Returns THROTTLED, without checking the
    password, when too many recent attempts failed for this email address or
    from this source; this is the same whether or not an account exists.
    """
    identifier = User.objects.normalize_email(email)
    identifier_key = _key("identifier", identifier)
    source_key = _key("source", source)

    with transaction.atomic():
        # One attempt at a time per source and per email address, so that
        # attempts sent together cannot all be counted as the first. Always
        # taken in this order.
        _lock_attempts(_SOURCE_LOCK, source_key)
        _lock_attempts(_IDENTIFIER_LOCK, identifier_key)

        throttled_by = _throttled_by(identifier_key, source_key)
        if throttled_by is not None:
            logger.warning(
                "Sign-in throttled",
                extra={"event": "authentication.throttled", "scope": throttled_by},
            )
            return SignInResult(SignInOutcome.THROTTLED)

        user = authenticate(email=identifier, password=password)
        if not isinstance(user, User):
            # Named in the record only if the address belongs to an account.
            known = User.objects.filter(email=identifier).first()
            _record(AuthenticationEventType.LOGIN_FAILURE, known, identifier_key, source_key)
            logger.warning("Sign-in refused", extra={"event": "authentication.refused"})
            return SignInResult(SignInOutcome.REFUSED)

        _record(AuthenticationEventType.LOGIN_SUCCESS, user, identifier_key, source_key)

    logger.info("Signed in", extra={"event": "authentication.signed_in", "user_id": user.pk})
    return SignInResult(SignInOutcome.SIGNED_IN, user)


def record_sign_out(*, user: User, source: str) -> None:
    """Record that an account signed out.

    Side effects: one AuthenticationEvent is appended and the sign-out is
    logged. Ending the session is the caller's business.
    """
    _record(
        AuthenticationEventType.LOGOUT, user, _key("identifier", user.email), _key("source", source)
    )
    logger.info("Signed out", extra={"event": "authentication.signed_out", "user_id": user.pk})


@sensitive_variables("password")
def create_first_administrator(*, email: str, password: str, operator: str) -> User:
    """Create the first Administrator account. Works once.

    This is the one role grant with no acting user: it is made by an operator
    at the server before any account exists. `operator` names that person's
    operating-system account and is written into the reason of the RoleEvent.

    Preconditions: no Administrator role event exists. Side effects, in one
    transaction: an active account is created and one RoleEvent grants it the
    Administrator role. The creation is logged without the email address or
    password.

    Raises FirstAdministratorExistsError if an Administrator has ever been
    created, and ValidationError if the email address is not valid or already
    belongs to an account, or the password fails the password validators.
    """
    with transaction.atomic():
        _serialize_account_changes()
        if selectors.an_administrator_was_ever_created():
            raise FirstAdministratorExistsError("An Administrator has already been created.")

        email = User.objects.normalize_email(email)
        validate_email(email)
        if User.objects.filter(email=email).exists():
            raise ValidationError("An account with this email address already exists.")
        validate_password(password, user=User(email=email))

        user = User.objects.create_user(email, password)
        event = RoleEvent.objects.create(
            user=user,
            role=Role.ADMINISTRATOR,
            event_type=RoleEventType.GRANTED,
            actor=None,
            reason=(
                "First Administrator, created by the create_first_administrator command"
                f" run by the operating-system account {operator!r}. No acting user exists"
                " for this event."
            ),
        )

    logger.info(
        "First Administrator created",
        extra={
            "event": "accounts.first_administrator_created",
            "user_id": user.pk,
            "role_event_id": event.pk,
        },
    )
    return user


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


def _key(purpose: str, value: str) -> str:
    """Return a keyed hash that identifies a value without revealing it."""
    return salted_hmac(
        f"caipo.accounts.authentication.{purpose}", value, algorithm="sha256"
    ).hexdigest()


def _lock_attempts(lock_class: int, key: str) -> None:
    """Hold, until the transaction ends, the lock for attempts sharing this key.

    Two different keys can share a lock, because only 31 bits of the key are
    used. That makes unrelated attempts wait for each other occasionally and
    changes no decision.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [lock_class, int(key[:8], 16) >> 1])


def _throttled_by(identifier_key: str, source_key: str) -> str | None:
    """Return which limit refuses a new attempt now, "account" or "source", or None."""
    window_start = timezone.now() - settings.LOGIN_THROTTLE_WINDOW
    failures = AuthenticationEvent.objects.filter(event_type=AuthenticationEventType.LOGIN_FAILURE)

    # A successful sign-in clears the count for that email address. It does
    # not clear the count for the source: one valid account must not buy a
    # source fresh attempts at every other account.
    counted_from: datetime = window_start
    last_success = (
        AuthenticationEvent.objects.filter(
            event_type=AuthenticationEventType.LOGIN_SUCCESS,
            identifier_key=identifier_key,
            created_at__gte=window_start,
        )
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    if last_success is not None:
        counted_from = last_success
    account_failures = failures.filter(
        identifier_key=identifier_key, created_at__gt=counted_from
    ).count()
    if account_failures >= settings.LOGIN_THROTTLE_ACCOUNT_FAILURES:
        return "account"

    source_failures = failures.filter(source_key=source_key, created_at__gte=window_start).count()
    if source_failures >= settings.LOGIN_THROTTLE_SOURCE_FAILURES:
        return "source"
    return None


def _record(
    event_type: AuthenticationEventType, user: User | None, identifier_key: str, source_key: str
) -> None:
    AuthenticationEvent.objects.create(
        event_type=event_type,
        user=user,
        identifier_key=identifier_key,
        source_key=source_key,
        correlation_id=get_correlation_id() or "",
    )
