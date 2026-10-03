"""Write interface of the accounts app: signing in and out, the second factor
and its approval, changing roles, creating, activating, disabling, and enabling
accounts, resetting a forgotten password, and creating the first Administrator.

Every account change here runs as one transaction and holds a lock that lets
only one of them proceed at a time, so each decides on what the previous one
left and none can see a half-made change. The actor's permission is checked
inside that lock, not before it.

Nothing here takes a request. A sign-in is given an email address, a password,
and the address it came from, and answers with an outcome; establishing the
session is the caller's business. An operation that needs a permission is
given the authentication context of whoever is acting, never a bare account:
without a context there is no assurance to decide on, and the answer is no.
"""

import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
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
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.debug import sensitive_variables

from caipo.accounts import selectors, totp
from caipo.accounts.authentication import AuthenticationContext
from caipo.accounts.authorization import (
    Assurance,
    Permission,
    Role,
    enrollment_requires_approval,
)
from caipo.accounts.models import (
    AccountActivation,
    AccountEvent,
    AccountEventType,
    AccountStatus,
    AuthenticationEvent,
    AuthenticationEventType,
    MfaChallenge,
    PasswordReset,
    RoleEvent,
    RoleEventType,
    TotpDevice,
    TotpDeviceState,
    User,
)
from caipo.core import mail
from caipo.core.correlation import get_correlation_id

logger = logging.getLogger(__name__)

# Advisory lock classes: one sign-in attempt at a time for a source, and for
# an email address, and one second-factor operation at a time for an account.
# Always taken in this order.
_SOURCE_LOCK = 1
_IDENTIFIER_LOCK = 2
_SECOND_FACTOR_LOCK = 3
# One activation attempt at a time for a source.
_ACTIVATION_LOCK = 4
# One submission of a reset token at a time for a source. Taken before the
# email address lock and the second-factor lock of the token's account, and
# never after them.
_PASSWORD_RESET_LOCK = 5

# What stands for the network address in the one event that no request causes.
BOOTSTRAP_SOURCE = "create_first_administrator command"


class AccountChangeError(Exception):
    """The requested change to an account cannot be made."""


class RoleChangeError(AccountChangeError):
    """The requested role change would not change anything."""


class LastAdministratorError(AccountChangeError):
    """The change would leave the system with no Administrator."""


class FirstAdministratorExistsError(AccountChangeError):
    """An Administrator has already been created; the bootstrap is closed."""


class SecondFactorCodeError(AccountChangeError):
    """The code given for the first Administrator's second factor is not right for it."""


class ActivationOutcome(StrEnum):
    ACTIVATED = "activated"
    # An unknown, used, replaced, or lapsed token, and a token of an account
    # that is disabled or already active, are one outcome on purpose: a caller
    # cannot tell them apart, so neither can whoever is asking.
    REFUSED = "refused"
    THROTTLED = "throttled"
    # The token is good and the password chosen is not acceptable. Nothing
    # was changed, and the token can be used again with another password.
    PASSWORD_REFUSED = "password_refused"  # noqa: S105 - names an outcome; it is not a credential


@dataclass(frozen=True)
class ActivationResult:
    outcome: ActivationOutcome
    # Set only when the outcome is PASSWORD_REFUSED: what the password
    # validators said. They describe rules and never repeat the password.
    password_errors: tuple[str, ...] = ()


class PasswordResetOutcome(StrEnum):
    RESET = "reset"
    # An unknown, malformed, used, replaced, or lapsed token, and a token of
    # an account that is not active, are one outcome on purpose: a caller
    # cannot tell them apart, so neither can whoever is asking.
    REFUSED = "refused"
    THROTTLED = "throttled"
    # The token is good and the password chosen is not acceptable. Nothing
    # was changed, and the token can be used again with another password.
    PASSWORD_REFUSED = "password_refused"  # noqa: S105 - names an outcome; it is not a credential


@dataclass(frozen=True)
class PasswordResetResult:
    outcome: PasswordResetOutcome
    # Set only when the outcome is PASSWORD_REFUSED: what the password
    # validators said. They describe rules and never repeat the password.
    password_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class CreatedAccount:
    user: User
    # Whether the verification message was handed on for delivery. If not,
    # the account exists and awaits verification, and the message must be
    # sent again with `send_account_verification`.
    verification_sent: bool


class SignInOutcome(StrEnum):
    SIGNED_IN = "signed_in"
    # The password was right and the account has a second factor. Nobody is
    # signed in until `verify_second_factor` accepts a code.
    SECOND_FACTOR_REQUIRED = "second_factor_required"
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
    # Set only when the outcome is SECOND_FACTOR_REQUIRED: the token that
    # `verify_second_factor` takes. The caller keeps it on the server.
    challenge: str | None = field(default=None, repr=False)


class MfaOutcome(StrEnum):
    ACCEPTED = "accepted"
    # A wrong password and a wrong, expired, or already used code are one
    # outcome on purpose, as are a challenge that is unknown and one that has
    # lapsed.
    REFUSED = "refused"
    THROTTLED = "throttled"
    # The second factor is not in a state that allows the operation: enrolling
    # when enrolled, confirming when nothing awaits a code, disabling or
    # replacing when not enrolled, deciding on a request that does not await a
    # decision.
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class Provisioning:
    """What an authenticator application needs, shown to the account once."""

    secret: str = field(repr=False)
    uri: str = field(repr=False)


@dataclass(frozen=True)
class MfaResult:
    outcome: MfaOutcome
    # Set only when a code was accepted by `verify_second_factor` or
    # `confirm_mfa_enrollment`: the context the account now acts in.
    context: AuthenticationContext | None = None
    # Set only when `start_mfa_enrollment` or `replace_mfa_device` is accepted.
    provisioning: Provisioning | None = field(default=None, repr=False)


@dataclass(frozen=True)
class FirstAdministratorEnrollment:
    """The second factor issued for a first Administrator that does not exist yet.

    Held in memory by the bootstrap command between showing the secret and
    reading the first code. Nothing of it is stored until the code is right.
    """

    secret: bytes = field(repr=False)
    provisioning: Provisioning = field(repr=False)


@sensitive_variables("password", "challenge")
def sign_in(*, email: str, password: str, source: str) -> SignInResult:
    """Check an email address and password, and record the attempt.

    `source` is the network address the attempt came from, as the caller
    established it. It is used to count attempts and is stored only as a keyed
    hash.

    Side effects: an AuthenticationEvent is appended for a success or a
    refusal, and the attempt is logged without the email address or password.
    A throttled attempt is logged and appends nothing, so that refused
    requests cannot be used to fill the table. No session is created.

    For an account with an active second factor the right password is not a
    sign-in. The outcome is SECOND_FACTOR_REQUIRED with a challenge token, the
    account's pending challenge is replaced by this one, and
    `mfa_challenge_issued` is recorded instead of `login_success`.

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

        if TotpDevice.objects.filter(user=user, state=TotpDeviceState.ACTIVE).exists():
            challenge = secrets.token_urlsafe(32)
            MfaChallenge.objects.update_or_create(
                user=user,
                defaults={"token_key": _key("challenge", challenge), "created_at": timezone.now()},
            )
            _record(AuthenticationEventType.MFA_CHALLENGE_ISSUED, user, identifier_key, source_key)
        else:
            challenge = None
            _record(AuthenticationEventType.LOGIN_SUCCESS, user, identifier_key, source_key)

    if challenge is not None:
        logger.info(
            "Password accepted, second factor required",
            extra={"event": "authentication.second_factor_required", "user_id": user.pk},
        )
        return SignInResult(SignInOutcome.SECOND_FACTOR_REQUIRED, challenge=challenge)
    logger.info("Signed in", extra={"event": "authentication.signed_in", "user_id": user.pk})
    return SignInResult(SignInOutcome.SIGNED_IN, user)


@sensitive_variables("challenge", "code", "secret")
def verify_second_factor(*, challenge: str, code: str, source: str) -> MfaResult:
    """Complete a sign-in by checking a second-factor code against its challenge.

    `challenge` is the token `sign_in` returned. It decides which account the
    code is checked for; nothing else does, so a challenge cannot complete a
    sign-in for any other account.

    Preconditions for ACCEPTED: the challenge exists and is younger than
    MFA_CHALLENGE_LIFETIME, its account is active with an active second
    factor, the account is not throttled, and the code is right for a time
    step later than the last one accepted. Side effects when accepted, in one
    transaction: the challenge is removed, so it cannot be used again, the
    time step is remembered, and `mfa_verification_succeeded` and
    `login_success` are recorded. The result carries the context the account
    now acts in. It claims MFA_VERIFIED, and the authorization decision
    upholds the claim only for a trusted second factor. No session is created.

    Never raises for a wrong code. Returns REFUSED for an unknown or lapsed
    challenge, which records nothing, and for a wrong code, which records
    `mfa_verification_failed`. Returns THROTTLED, without examining the code
    and without recording, once MFA_THROTTLE_FAILURES codes were refused for
    the account within MFA_THROTTLE_WINDOW.
    """
    with transaction.atomic():
        pending = _pending_challenge(_key("challenge", challenge))
        if pending is None:
            logger.warning(
                "Second-factor challenge refused", extra={"event": "mfa.challenge_refused"}
            )
            return MfaResult(MfaOutcome.REFUSED)

        user = User.objects.get(pk=pending.user_id)
        keys = (_key("identifier", user.email), _key("source", source))
        if _second_factor_throttled(user, keys[0]):
            return MfaResult(MfaOutcome.THROTTLED)
        device = _accept_code(user, code, TotpDeviceState.ACTIVE) if user.is_active else None
        if device is None:
            _record(AuthenticationEventType.MFA_VERIFICATION_FAILED, user, *keys)
            logger.warning(
                "Second-factor code refused",
                extra={"event": "mfa.verification_failed", "user_id": user.pk},
            )
            return MfaResult(MfaOutcome.REFUSED)

        pending.delete()
        _record(AuthenticationEventType.MFA_VERIFICATION_SUCCEEDED, user, *keys)
        _record(AuthenticationEventType.LOGIN_SUCCESS, user, *keys)

    logger.info(
        "Signed in with a second factor",
        extra={"event": "authentication.signed_in", "user_id": user.pk, "mfa": True},
    )
    return MfaResult(
        MfaOutcome.ACCEPTED, AuthenticationContext(user, Assurance.MFA_VERIFIED, device.pk)
    )


@sensitive_variables("challenge")
def cancel_second_factor_challenge(*, challenge: str) -> None:
    """Remove a pending challenge, so that it can no longer complete a sign-in.

    Called when the pending sign-in is abandoned. Harmless if the challenge is
    unknown or already gone. Records nothing.
    """
    MfaChallenge.objects.filter(token_key=_key("challenge", challenge)).delete()


@sensitive_variables("password", "secret")
def start_mfa_enrollment(*, actor: AuthenticationContext, password: str, source: str) -> MfaResult:
    """Issue a new TOTP secret to the acting account, as a pending enrolment.

    Preconditions: the actor may manage their own second factor, gives their
    current password again, and has no active second factor. Side effects when
    ACCEPTED, in one transaction: any earlier pending enrolment is discarded,
    together with any approval it had, a secret is generated here and stored
    encrypted in a pending device, and `mfa_enrollment_started` is recorded.
    The result carries the secret and its provisioning URI, which exist in
    clear nowhere else and cannot be asked for again.

    Nothing is enabled. For an account that holds a role requiring a second
    factor the device awaits approval: no code is accepted for it until an
    Administrator has approved the request with `approve_mfa_enrollment`, so
    the password given here cannot by itself establish a second factor. For
    any other account the device awaits its first code at once, and lapses
    after MFA_ENROLLMENT_LIFETIME.

    Raises PermissionDenied if the actor may not manage their second factor.
    Returns REFUSED for a wrong password, which records
    `password_confirmation_failed`; THROTTLED when password attempts for the
    account or from the source are throttled; and UNAVAILABLE if the account
    already has an active second factor: that one is replaced only with
    `replace_mfa_device`.
    """
    with transaction.atomic():
        refusal = _confirm_password(actor, password, source)
        if refusal is not None:
            return MfaResult(refusal)
        user = actor.user
        _lock_second_factor(user.pk)
        if TotpDevice.objects.filter(user=user, state=TotpDeviceState.ACTIVE).exists():
            return MfaResult(MfaOutcome.UNAVAILABLE)
        provisioning = _issue_pending_device(user, source)

    return MfaResult(MfaOutcome.ACCEPTED, provisioning=provisioning)


@sensitive_variables("code", "secret")
def confirm_mfa_enrollment(*, actor: AuthenticationContext, code: str, source: str) -> MfaResult:
    """Activate the acting account's pending second factor by proving possession of it.

    Preconditions: the actor may manage their own second factor, has an
    enrolment that awaits its first code and has not lapsed, is not throttled,
    and gives a code that is right for the pending secret. An enrolment that
    still awaits approval does not qualify, whatever code is given. Side
    effects when ACCEPTED, in one transaction: the device becomes active and
    remembers the code's time step, and `mfa_enrollment_succeeded` is
    recorded. The result carries the context the actor now acts in. It claims
    MFA_VERIFIED, and the claim holds only if the enrolment was approved: a
    device enrolled without approval confers nothing that the password does
    not, whatever roles the account holds or is given later.

    Raises PermissionDenied if the actor may not manage their second factor.
    Returns UNAVAILABLE if nothing awaits a code or it has lapsed; REFUSED for a
    wrong code, which records `mfa_verification_failed` and leaves the
    enrolment pending; and THROTTLED, without examining the code, when too
    many codes were refused for the account.
    """
    with transaction.atomic():
        selectors.require_permission(actor, Permission.MFA_MANAGE_OWN)
        user = actor.user
        _lock_second_factor(user.pk)
        keys = (_key("identifier", user.email), _key("source", source))
        if selectors.mfa_state_of(user) != selectors.MfaState.PENDING_VERIFICATION:
            return MfaResult(MfaOutcome.UNAVAILABLE)
        if _second_factor_throttled(user, keys[0]):
            return MfaResult(MfaOutcome.THROTTLED)
        device = _accept_code(user, code, TotpDeviceState.PENDING_VERIFICATION)
        if device is None:
            _record(AuthenticationEventType.MFA_VERIFICATION_FAILED, user, *keys)
            logger.warning(
                "Second-factor code refused",
                extra={"event": "mfa.verification_failed", "user_id": user.pk},
            )
            return MfaResult(MfaOutcome.REFUSED)
        _record(AuthenticationEventType.MFA_ENROLLMENT_SUCCEEDED, user, *keys)

    logger.info(
        "Second factor enrolled", extra={"event": "mfa.enrollment_succeeded", "user_id": user.pk}
    )
    return MfaResult(
        MfaOutcome.ACCEPTED, AuthenticationContext(user, Assurance.MFA_VERIFIED, device.pk)
    )


@sensitive_variables("password", "code", "secret")
def disable_mfa(
    *, actor: AuthenticationContext, password: str, code: str, source: str
) -> MfaResult:
    """Remove the acting account's own active second factor.

    Both proofs are required again, in the same call: the current password and
    a current code from the second factor being removed. Being signed in,
    at any assurance, is not enough. There is no way here to remove another
    account's second factor, and none to remove one's own without the device.

    Side effects when ACCEPTED, in one transaction: the device and its secret
    are deleted, with any approval it had, any pending challenge for the
    account is removed, and `mfa_disabled` is recorded. Roles that require a
    second factor confer nothing again until the account enrols anew, which
    for such an account needs an Administrator's approval.

    Raises PermissionDenied if the actor may not manage their second factor.
    Returns REFUSED for a wrong password or a wrong code, each recorded as for
    the other operations; THROTTLED when either kind of attempt is throttled;
    and UNAVAILABLE if the account has no active second factor.
    """
    with transaction.atomic():
        refusal = _remove_active_device(actor, password, code, source)
        if refusal is not None:
            return MfaResult(refusal)
        user = actor.user
        _record(
            AuthenticationEventType.MFA_DISABLED,
            user,
            _key("identifier", user.email),
            _key("source", source),
        )

    logger.info("Second factor disabled", extra={"event": "mfa.disabled", "user_id": user.pk})
    return MfaResult(MfaOutcome.ACCEPTED)


@sensitive_variables("password", "code", "secret")
def replace_mfa_device(
    *, actor: AuthenticationContext, password: str, code: str, source: str
) -> MfaResult:
    """Give up the acting account's active second factor and start a new enrolment.

    The only way to exchange an active second factor. It requires what
    `disable_mfa` requires, the current password and a current code from the
    device being given up, so a password alone replaces nothing. The trust in
    the old device does not pass to the new one: the new enrolment is a
    request like any other and, for an account that holds a role requiring a
    second factor, awaits an Administrator's approval.

    Side effects when ACCEPTED, in one transaction: the active device and its
    secret are deleted, any pending challenge for the account is removed,
    `mfa_device_replaced` is recorded, and a new pending enrolment is issued
    as by `start_mfa_enrollment`, which records `mfa_enrollment_started`. The
    result carries the new secret and its provisioning URI, once. Until the
    new enrolment is active, and approved where that is required, roles that
    require a second factor confer nothing.

    Raises PermissionDenied if the actor may not manage their second factor.
    Returns REFUSED, THROTTLED, and UNAVAILABLE as `disable_mfa` does, and
    then nothing is changed.
    """
    with transaction.atomic():
        refusal = _remove_active_device(actor, password, code, source)
        if refusal is not None:
            return MfaResult(refusal)
        user = actor.user
        _record(
            AuthenticationEventType.MFA_DEVICE_REPLACED,
            user,
            _key("identifier", user.email),
            _key("source", source),
        )
        provisioning = _issue_pending_device(user, source)

    logger.info(
        "Second factor given up for a new enrolment",
        extra={"event": "mfa.device_replaced", "user_id": user.pk},
    )
    return MfaResult(MfaOutcome.ACCEPTED, provisioning=provisioning)


def approve_mfa_enrollment(
    *, actor: AuthenticationContext, request_number: int, source: str
) -> MfaResult:
    """Approve another account's enrolment request, so that its first code is accepted.

    `request_number` is the number the person who made the request was shown.
    The approving Administrator is expected to have asked them for it by a
    means other than this system: it names one issued secret, and a request
    made later for the same account, by anyone who knows its password, has
    another number.

    Preconditions: the actor holds the permission to approve enrolments, which
    the policy gives only to a context verified against a trusted second
    factor; the request exists, still awaits approval, and has not lapsed; and
    it is not the actor's own. Side effects when ACCEPTED, in one transaction:
    the device awaits its first code and records the actor and the time of the
    approval, and `mfa_enrollment_approved` is recorded for the account,
    naming the actor. Nothing is enabled: the account holds no further
    permission until `confirm_mfa_enrollment` accepts a code and a sign-in is
    verified against the device.

    Raises PermissionDenied if the actor may not approve enrolments or the
    request is their own. Returns UNAVAILABLE if no such request awaits
    approval: it is unknown, was replaced or already decided, or has lapsed.
    """
    return _decide_enrollment(actor, request_number, source, approve=True)


def reject_mfa_enrollment(
    *, actor: AuthenticationContext, request_number: int, source: str
) -> MfaResult:
    """Reject another account's enrolment request, discarding its secret.

    Preconditions and errors are those of `approve_mfa_enrollment`. Side
    effects when ACCEPTED, in one transaction: the pending device and its
    secret are deleted, and `mfa_enrollment_rejected` is recorded for the
    account, naming the actor. The account may make a new request.
    """
    return _decide_enrollment(actor, request_number, source, approve=False)


def record_sign_out(*, user: User, source: str) -> None:
    """Record that an account signed out.

    Side effects: one AuthenticationEvent is appended and the sign-out is
    logged. Ending the session is the caller's business.
    """
    _record(
        AuthenticationEventType.LOGOUT, user, _key("identifier", user.email), _key("source", source)
    )
    logger.info("Signed out", extra={"event": "authentication.signed_out", "user_id": user.pk})


@sensitive_variables("password", "secret")
def prepare_first_administrator(*, email: str, password: str) -> FirstAdministratorEnrollment:
    """Issue the second factor for the first Administrator, before the account exists.

    The first step of the bootstrap. It checks everything that
    `create_first_administrator` checks about the email address and password,
    so that nobody sets up an authenticator for an account that would be
    refused, and returns a new secret with what an authenticator application
    needs. Nothing is written and nothing is logged: the secret exists only in
    the result, for the bootstrap command to show at the terminal and hand
    back.

    Raises FirstAdministratorExistsError and ValidationError as
    `create_first_administrator` does.
    """
    email = _first_administrator_email(email, password)
    secret = totp.generate_secret()
    return FirstAdministratorEnrollment(
        secret=secret,
        provisioning=Provisioning(
            secret=totp.manual_entry_key(secret),
            uri=totp.provisioning_uri(secret, account=email),
        ),
    )


@sensitive_variables("password", "enrollment", "code")
def create_first_administrator(
    *,
    email: str,
    password: str,
    operator: str,
    enrollment: FirstAdministratorEnrollment,
    code: str,
) -> User:
    """Create the first Administrator account with its second factor. Works once.

    This is the one role grant with no acting user, and the one second factor
    that is trusted without an Administrator's approval: it is made by an
    operator at the server before any account exists that could grant or
    approve. `operator` names that person's operating-system account and is
    written into the reason of the RoleEvent. `enrollment` is what
    `prepare_first_administrator` returned to the same command, and `code` is
    a current code from the authenticator that was given its secret.

    Preconditions: no Administrator role event exists, and the code is right
    for the enrolment's secret. Side effects, in one transaction and only if
    every precondition holds: an active account is created, one RoleEvent
    grants it the Administrator role, its second factor is stored encrypted,
    active and trusted, with the code's time step remembered, and
    `mfa_enrollment_succeeded` is recorded. The creation is logged without the
    email address, password, secret, or code. An Administrator therefore never
    exists without a verified second factor.

    Raises FirstAdministratorExistsError if an Administrator has ever been
    created, ValidationError if the email address is not valid or already
    belongs to an account, or the password fails the password validators, and
    SecondFactorCodeError if the code is not right. Whatever is raised,
    nothing was created.
    """
    with transaction.atomic():
        _serialize_account_changes()
        email = _first_administrator_email(email, password)
        now = timezone.now()
        step = totp.matching_step(enrollment.secret, code, at=now)
        if step is None:
            raise SecondFactorCodeError("The code is not right for the second factor.")

        user = User.objects.create_user(email, password)
        event = RoleEvent.objects.create(
            user=user,
            role=Role.ADMINISTRATOR,
            event_type=RoleEventType.GRANTED,
            actor=None,
            reason=(
                "First Administrator, created by the create_first_administrator command"
                f" run by the operating-system account {operator!r}. No acting user exists"
                " for this event. The account's second factor was enrolled and verified"
                " at the terminal by the same command."
            ),
        )
        ciphertext, key_id = totp.encrypt_secret(enrollment.secret, user_id=user.pk)
        TotpDevice.objects.create(
            user=user,
            state=TotpDeviceState.ACTIVE,
            secret_ciphertext=ciphertext,
            key_id=key_id,
            last_used_step=step,
            confirmed_at=now,
            approved_at=now,
        )
        _record(
            AuthenticationEventType.MFA_ENROLLMENT_SUCCEEDED,
            user,
            _key("identifier", user.email),
            _key("source", BOOTSTRAP_SOURCE),
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


def grant_role(*, actor: AuthenticationContext, user: User, role: Role, reason: str) -> RoleEvent:
    """Grant a role to another user and record who did it and why.

    Preconditions: the actor holds the permission to manage roles, the user is
    not the actor, and the reason is not blank. Side effects: one RoleEvent is
    appended and the change is logged. Nothing existing is modified.

    Raises PermissionDenied if the actor may not manage roles or is the user,
    ValueError if the role is not one of the four roles or the reason is
    blank, and RoleChangeError if the user already holds the role.
    """
    return _change_role(actor, user, role, reason, RoleEventType.GRANTED)


def revoke_role(*, actor: AuthenticationContext, user: User, role: Role, reason: str) -> RoleEvent:
    """Revoke a role from another user and record who did it and why.

    Preconditions, side effects, and errors are those of `grant_role`, except
    that RoleChangeError is raised if the user does not hold the role, and
    LastAdministratorError if the change would leave no Administrator. The
    grant being revoked stays on record.
    """
    return _change_role(actor, user, role, reason, RoleEventType.REVOKED)


@sensitive_variables("token", "password")
def create_user(
    *,
    actor: AuthenticationContext,
    email: str,
    role: Role,
    source: str,
    activation_url: Callable[[str], str],
) -> CreatedAccount:
    """Create an account that awaits verification, with one role, and invite its owner.

    The only way an account other than the first Administrator's comes to
    exist. The acting Administrator names an email address and one role, and
    never a password: the account is created with a password nobody knows,
    and its owner chooses one with `activate_account`, using the token sent
    to that address. `activation_url` turns that token into the address the
    message carries; the caller supplies it, because only the caller knows
    the site's pages.

    Preconditions: the actor holds the permission to create accounts and the
    permission to manage roles, the role is one of the four roles, and the
    email address is valid and belongs to no account. Side effects, in one
    transaction: the account is created in PENDING_VERIFICATION, one RoleEvent
    grants it the role, made by `grant_role` under its own rules, an
    activation token is stored as a keyed hash, and `account_created` is
    recorded naming the actor. Then, outside that transaction, the
    verification message is sent, and `verification_sent` is recorded if it
    was handed on. Whatever the role, the account can do nothing until it is
    activated, and a Reviewer or Administrator role confers nothing until
    the account has enrolled a second factor with an Administrator's approval
    and signed in with it (ADR-0014).

    The creation is logged without the email address. The token is not
    logged, recorded, or returned.

    Raises PermissionDenied if the actor may not create accounts or manage
    roles, ValueError if the role is not one of the four roles, and
    ValidationError if the email address is not valid or already belongs to
    an account. Then nothing was created. A message that could not be sent is
    not an error: the result says so, and the account awaits another message.
    """
    source_key = _key("source", source)
    with transaction.atomic():
        _serialize_account_changes()
        # Permission first, so that a caller without it learns nothing about
        # which email addresses have accounts or which inputs are valid.
        selectors.require_permission(actor, Permission.ACCOUNTS_CREATE)
        role = Role(role)
        email = User.objects.normalize_email(email)
        validate_email(email)
        if User.objects.filter(email=email).exists():
            raise ValidationError(_("An account with this email address already exists."))

        user = User(email=email, status=AccountStatus.PENDING_VERIFICATION)
        # A password nobody knows, and not an unusable one: a sign-in attempt
        # for this account then costs what it costs for any other, so the
        # time taken does not tell an account that awaits verification from
        # one that does not exist. The value is discarded here.
        user.set_password(secrets.token_urlsafe(32))
        user.save()
        _change_role(
            actor,
            user,
            role,
            "Initial role, given when the account was created.",
            RoleEventType.GRANTED,
        )
        _record_account(AccountEventType.ACCOUNT_CREATED, user, source_key, actor=actor.user)
        token = _issue_activation(user)

    logger.info(
        "Account created",
        extra={
            "event": "accounts.created",
            "user_id": user.pk,
            "actor_id": actor.user.pk,
            "role": role.value,
        },
    )
    sent = _send_verification(user, activation_url(token), source_key, actor.user)
    return CreatedAccount(user=user, verification_sent=sent)


@sensitive_variables("token")
def send_account_verification(
    *,
    actor: AuthenticationContext,
    user_id: int,
    source: str,
    activation_url: Callable[[str], str],
) -> bool:
    """Send the verification message of an account that awaits verification again.

    Preconditions: the actor holds the permission to create accounts, and the
    account exists and is in PENDING_VERIFICATION. Side effects: a new token
    replaces the earlier one, which stops working at once, and the message is
    sent; `verification_sent` is recorded, naming the actor, if it was handed
    on. Returns whether it was.

    Raises PermissionDenied if the actor may not create accounts, and
    AccountChangeError if there is no such account awaiting verification.
    """
    source_key = _key("source", source)
    with transaction.atomic():
        selectors.require_permission(actor, Permission.ACCOUNTS_CREATE)
        user = (
            User.objects.select_for_update()
            .filter(pk=user_id, status=AccountStatus.PENDING_VERIFICATION)
            .first()
        )
        if user is None:
            raise AccountChangeError("No such account awaits verification.")
        token = _issue_activation(user)

    return _send_verification(user, activation_url(token), source_key, actor.user)


@sensitive_variables("token", "password")
def activate_account(*, token: str, password: str, source: str) -> ActivationResult:
    """Verify an email address and activate its account, with the password its owner chose.

    `token` is what was sent to the account's email address. It decides which
    account is activated; nothing else does. Presenting it shows that the
    person can read that address, which is the verification.

    Preconditions for ACTIVATED: attempts from the source are not throttled,
    the token is the account's current one and younger than
    ACCOUNT_ACTIVATION_LIFETIME, the account is in PENDING_VERIFICATION, and
    the password passes the password validators. Side effects when ACTIVATED,
    in one transaction: the password is set, the account becomes ACTIVE and
    records when its email address was verified and when it was activated,
    the token is removed, so it cannot be used again, and
    `verification_succeeded` is recorded. Nobody is signed in.

    Never raises for a bad token or password. Returns REFUSED for a token
    that is unknown, used, replaced, or lapsed, or whose account is not
    awaiting verification, and records `verification_failed`, naming the
    account only if the token is that account's current one. Returns
    THROTTLED, without examining the token and without recording, once
    ACCOUNT_ACTIVATION_THROTTLE_FAILURES attempts from the source were
    refused within ACCOUNT_ACTIVATION_THROTTLE_WINDOW. Returns
    PASSWORD_REFUSED, with the validators' messages, if the token is good and
    the password is not: then nothing is changed or recorded.
    """
    source_key = _key("source", source)
    token_key = _key("activation", token)
    with transaction.atomic():
        _lock_attempts(_ACTIVATION_LOCK, source_key)
        refused = AccountEvent.objects.filter(
            event_type=AccountEventType.VERIFICATION_FAILED,
            source_key=source_key,
            created_at__gte=timezone.now() - settings.ACCOUNT_ACTIVATION_THROTTLE_WINDOW,
        ).count()
        if refused >= settings.ACCOUNT_ACTIVATION_THROTTLE_FAILURES:
            logger.warning("Account activation throttled", extra={"event": "activation.throttled"})
            return ActivationResult(ActivationOutcome.THROTTLED)

        user, activation = _pending_activation(token_key)
        if (
            user is None
            or activation is None
            or user.status != AccountStatus.PENDING_VERIFICATION
            or timezone.now() >= selectors.activation_expires_at(activation)
        ):
            _record_account(AccountEventType.VERIFICATION_FAILED, user, source_key)
            logger.warning(
                "Account activation refused",
                extra={"event": "activation.refused", "user_id": user.pk if user else None},
            )
            return ActivationResult(ActivationOutcome.REFUSED)

        try:
            validate_password(password, user=user)
        except ValidationError as error:
            return ActivationResult(ActivationOutcome.PASSWORD_REFUSED, tuple(error.messages))

        now = timezone.now()
        user.set_password(password)
        user.status = AccountStatus.ACTIVE
        user.email_verified_at = now
        user.activated_at = now
        user.save(
            update_fields=["password", "status", "email_verified_at", "activated_at", "updated_at"]
        )
        activation.delete()
        _record_account(AccountEventType.VERIFICATION_SUCCEEDED, user, source_key)

    logger.info("Account activated", extra={"event": "accounts.activated", "user_id": user.pk})
    return ActivationResult(ActivationOutcome.ACTIVATED)


@sensitive_variables("email", "token")
def request_password_reset(*, email: str, source: str, reset_url: Callable[[str], str]) -> None:
    """Take a request to reset the password of whichever account has this email address.

    Needs no actor: whoever asks is not signed in. `source` is the network
    address the request came from, as the caller established it. `reset_url`
    turns a token into the address the message carries; the caller supplies
    it, because only the caller knows the site's pages.

    Returns nothing, whatever happened, so that a caller cannot tell an
    address that has an account from one that has none, and so cannot whoever
    is asking. Every request goes through the same steps: the locks, the two
    counts, and one `password_reset_requested` event, which names the account
    if the address belongs to one and holds the address and the source only
    as keyed hashes.

    Only for an account that is ACTIVE, verified email address or not, two
    more things happen. In the same transaction, holding the account's row
    lock, a new token replaces any earlier one, which stops working at once,
    and is stored as a keyed hash with the time it lapses,
    PASSWORD_RESET_LIFETIME from now. Then, outside that transaction, the
    message is handed to the email boundary. An address with no account, an
    account that awaits verification, and a disabled account get no token and
    no message.

    A request is throttled once PASSWORD_RESET_REQUEST_EMAIL_LIMIT requests
    were made for the email address within PASSWORD_RESET_REQUEST_EMAIL_WINDOW
    or PASSWORD_RESET_REQUEST_SOURCE_LIMIT from the source within
    PASSWORD_RESET_REQUEST_SOURCE_WINDOW, whether or not the address has an
    account. A throttled request is logged, stores nothing, and sends nothing.

    Never raises for any email address. A message that could not be sent is
    logged as an error, without the address, the token, or the link; the
    token stays stored and nobody holds it, until the next request replaces
    it or it lapses.
    """
    identifier = User.objects.normalize_email(email)
    identifier_key = _key("identifier", identifier)
    source_key = _key("source", source)
    eligible: User | None = None
    token = None

    with transaction.atomic():
        # One request at a time per source and per email address, as for
        # sign-in and in the same order, so that requests sent together
        # cannot all be counted as the first.
        _lock_attempts(_SOURCE_LOCK, source_key)
        _lock_attempts(_IDENTIFIER_LOCK, identifier_key)

        throttled_by = _reset_request_throttled_by(identifier_key, source_key)
        if throttled_by is not None:
            logger.warning(
                "Password reset request throttled",
                extra={"event": "password_reset.request_throttled", "scope": throttled_by},
            )
            return

        # Locked, as disabling locks it: the status decides, and a disabling
        # of the same account must not run alongside.
        known = User.objects.select_for_update().filter(email=identifier).first()
        _record(AuthenticationEventType.PASSWORD_RESET_REQUESTED, known, identifier_key, source_key)
        if known is not None and known.status == AccountStatus.ACTIVE:
            eligible = known
            token = _issue_password_reset(known)

    # The same line for every request: what is logged does not tell an
    # address with an account from one without.
    logger.info("Password reset requested", extra={"event": "password_reset.requested"})
    if eligible is not None and token is not None:
        _send_password_reset(eligible, reset_url(token))


@sensitive_variables("token", "password")
def reset_password(*, token: str, password: str, source: str) -> PasswordResetResult:
    """Replace the password of the account a reset token was sent to.

    `token` is what was sent to the account's email address. It decides which
    account's password is set; nothing else does. `source` is the network
    address the submission came from, as the caller established it.

    Preconditions for RESET: submissions from the source are not throttled,
    the token is the account's current one and has not lapsed, the account is
    ACTIVE, and the password passes the password validators. Side effects
    when RESET, in one transaction that holds the lock on the account's email
    address that a sign-in holds, the account's second-factor lock, and the
    account's row lock: the password is set, the token is removed, so it
    cannot be used again, every pending second-factor challenge of the
    account is removed, and `password_reset_succeeded` is recorded. A sign-in
    for the account therefore runs wholly before the reset, and loses its
    challenge, or wholly after it, and needs the new password.

    Nothing else is touched: not the account's status, email verification,
    roles, second factor or its approval, nor the counts that throttle
    sign-in and second-factor codes. Nobody is signed in and no session is
    created; sessions established under the old password stop being
    recognised because the password they were bound to has changed.

    Never raises for a bad token or password. Returns REFUSED for a token
    that is unknown, malformed, used, replaced, or lapsed, or whose account
    is not active, and records `password_reset_failed`, naming the account
    only if the token is that account's current one. Returns THROTTLED,
    without looking the token up and without recording, once
    PASSWORD_RESET_THROTTLE_FAILURES submissions from the source were refused
    within PASSWORD_RESET_THROTTLE_WINDOW. Returns PASSWORD_REFUSED, with the
    validators' messages, if the token is good and the password is not: then
    nothing is changed or recorded, and the token can be used again.
    """
    source_key = _key("source", source)
    token_key = _key("password_reset", token)
    with transaction.atomic():
        _lock_attempts(_PASSWORD_RESET_LOCK, source_key)
        refused = AuthenticationEvent.objects.filter(
            event_type=AuthenticationEventType.PASSWORD_RESET_FAILED,
            source_key=source_key,
            created_at__gte=timezone.now() - settings.PASSWORD_RESET_THROTTLE_WINDOW,
        ).count()
        if refused >= settings.PASSWORD_RESET_THROTTLE_FAILURES:
            logger.warning("Password reset throttled", extra={"event": "password_reset.throttled"})
            return PasswordResetResult(PasswordResetOutcome.THROTTLED)

        user, reset = _pending_password_reset(token_key)
        if (
            user is None
            or reset is None
            or user.status != AccountStatus.ACTIVE
            or timezone.now() >= reset.expires_at
        ):
            _record(
                AuthenticationEventType.PASSWORD_RESET_FAILED,
                user,
                _key("identifier", user.email) if user is not None else "",
                source_key,
            )
            logger.warning(
                "Password reset refused",
                extra={"event": "password_reset.refused", "user_id": user.pk if user else None},
            )
            return PasswordResetResult(PasswordResetOutcome.REFUSED)

        try:
            validate_password(password, user=user)
        except ValidationError as error:
            return PasswordResetResult(PasswordResetOutcome.PASSWORD_REFUSED, tuple(error.messages))

        user.set_password(password)
        user.save(update_fields=["password", "updated_at"])
        reset.delete()
        # A sign-in that passed the old password and awaits its code must not
        # outlive that password. The device it would be answered with is not
        # touched.
        MfaChallenge.objects.filter(user=user).delete()
        _record(
            AuthenticationEventType.PASSWORD_RESET_SUCCEEDED,
            user,
            _key("identifier", user.email),
            source_key,
        )

    logger.info("Password reset", extra={"event": "password_reset.succeeded", "user_id": user.pk})
    return PasswordResetResult(PasswordResetOutcome.RESET)


def disable_user(*, actor: AuthenticationContext, user: User) -> None:
    """Disable an account, which then holds no permission and cannot be signed in to.

    Preconditions: the actor holds the permission to disable accounts. An
    actor may disable their own account: that gives up power and gains none.
    Side effects, in one transaction: the account becomes DISABLED, in the
    database and on the object passed in, any activation token and any
    password-reset token it had are removed, and `account_disabled` is
    recorded naming the actor. Its role record and its history are kept. It
    takes effect on the account's next request: its sessions stop being
    recognised and its password signs nobody in. The change is logged.

    Raises PermissionDenied if the actor may not disable accounts,
    AccountChangeError if the account is already disabled, and
    LastAdministratorError if it is the only active Administrator.
    """
    with transaction.atomic():
        _serialize_account_changes()
        selectors.require_permission(actor, Permission.ACCOUNTS_DEACTIVATE)
        # Read again, and locked: the object passed in may be out of date,
        # and an activation or a password reset of the same account must not
        # run alongside.
        target = User.objects.select_for_update().get(pk=user.pk)
        if target.status == AccountStatus.DISABLED:
            raise AccountChangeError("The account is already disabled.")
        if Role.ADMINISTRATOR in selectors.roles_of(target):
            _require_another_administrator(besides=target)
        target.status = AccountStatus.DISABLED
        target.save(update_fields=["status", "updated_at"])
        AccountActivation.objects.filter(user=target).delete()
        PasswordReset.objects.filter(user=target).delete()
        _record_account(AccountEventType.ACCOUNT_DISABLED, target, actor=actor.user)

    user.status = AccountStatus.DISABLED
    logger.info(
        "Account disabled",
        extra={"event": "accounts.disabled", "user_id": user.pk, "actor_id": actor.user.pk},
    )


def enable_user(*, actor: AuthenticationContext, user: User) -> AccountStatus:
    """Enable a disabled account, returning it to the state it was disabled in.

    Preconditions: the actor holds the permission to enable accounts, and the
    account is another account and is DISABLED. Side effects, in one
    transaction: an account that had been activated becomes ACTIVE again,
    with the password, roles, and second factor it had; one that had never
    been activated becomes PENDING_VERIFICATION, with no token, so that its
    verification message must be sent again. Enabling never verifies an email
    address or activates an account by itself. `account_enabled` is recorded
    naming the actor, and the change is logged. Returns the new state, which
    is also set on the object passed in.

    Raises PermissionDenied if the actor may not enable accounts or the
    account is their own, and AccountChangeError if the account is not
    disabled.
    """
    with transaction.atomic():
        _serialize_account_changes()
        selectors.require_permission(actor, Permission.ACCOUNTS_ENABLE)
        if actor.user.pk == user.pk:
            # A disabled account holds no permission, so this cannot happen
            # today. It is checked all the same, so that the rule holds here
            # by itself and not as a consequence of another rule.
            logger.warning(
                "Refused enabling the actor's own account",
                extra={"event": "accounts.own_enabling_refused", "user_id": actor.user.pk},
            )
            raise PermissionDenied
        target = User.objects.select_for_update().get(pk=user.pk)
        if target.status != AccountStatus.DISABLED:
            raise AccountChangeError("The account is not disabled.")
        target.status = (
            AccountStatus.ACTIVE
            if target.activated_at is not None
            else AccountStatus.PENDING_VERIFICATION
        )
        target.save(update_fields=["status", "updated_at"])
        _record_account(AccountEventType.ACCOUNT_ENABLED, target, actor=actor.user)

    user.status = target.status
    logger.info(
        "Account enabled",
        extra={
            "event": "accounts.enabled",
            "user_id": user.pk,
            "actor_id": actor.user.pk,
            "status": target.status,
        },
    )
    return AccountStatus(target.status)


def _change_role(
    actor: AuthenticationContext, user: User, role: Role, reason: str, event_type: RoleEventType
) -> RoleEvent:
    with transaction.atomic():
        _serialize_account_changes()
        # Permission first, so that a caller without it learns nothing about
        # the user or about which inputs are valid.
        selectors.require_permission(actor, Permission.ROLES_MANAGE)
        if actor.user.pk == user.pk:
            logger.warning(
                "Refused a change to the actor's own roles",
                extra={"event": "accounts.own_role_change_refused", "user_id": actor.user.pk},
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
            user=user, role=role, event_type=event_type, actor=actor.user, reason=reason
        )

    logger.info(
        "Role %s",
        event_type.value,
        extra={
            "event": f"accounts.role_{event_type.value}",
            "role": role.value,
            "user_id": user.pk,
            "actor_id": actor.user.pk,
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
    not they have a second factor.
    """
    latest = (
        RoleEvent.objects.filter(role=Role.ADMINISTRATOR, user__status=AccountStatus.ACTIVE)
        .exclude(user=besides)
        .order_by("user_id", "-id")
        .distinct("user_id")
        .values_list("event_type", flat=True)
    )
    if RoleEventType.GRANTED not in set(latest):
        raise LastAdministratorError("This would leave the system with no Administrator.")


@sensitive_variables("password")
def _first_administrator_email(email: str, password: str) -> str:
    """Return the normalised email address if the first Administrator may be created with it.

    Raises FirstAdministratorExistsError if an Administrator has ever been
    created, and ValidationError if the email address is not valid or already
    belongs to an account, or the password fails the password validators.
    """
    if selectors.an_administrator_was_ever_created():
        raise FirstAdministratorExistsError("An Administrator has already been created.")
    email = User.objects.normalize_email(email)
    validate_email(email)
    if User.objects.filter(email=email).exists():
        raise ValidationError("An account with this email address already exists.")
    validate_password(password, user=User(email=email))
    return email


@sensitive_variables("secret")
def _issue_pending_device(user: User, source: str) -> Provisioning:
    """Replace whatever second factor the account has with a newly issued, pending one.

    The caller has established that the account may have a new one: it has no
    active second factor, or has just given it up on both proofs. Whether the
    new device awaits approval is decided here, from the roles the account
    holds now. Records `mfa_enrollment_started`. Must be called inside a
    transaction, holding the account's second-factor lock.
    """
    needs_approval = enrollment_requires_approval(selectors.roles_of(user))
    secret = totp.generate_secret()
    ciphertext, key_id = totp.encrypt_secret(secret, user_id=user.pk)
    TotpDevice.objects.filter(user=user).delete()
    TotpDevice.objects.create(
        user=user,
        state=(
            TotpDeviceState.PENDING_APPROVAL
            if needs_approval
            else TotpDeviceState.PENDING_VERIFICATION
        ),
        secret_ciphertext=ciphertext,
        key_id=key_id,
    )
    _record(
        AuthenticationEventType.MFA_ENROLLMENT_STARTED,
        user,
        _key("identifier", user.email),
        _key("source", source),
    )
    logger.info(
        "Second-factor enrolment started",
        extra={
            "event": "mfa.enrollment_started",
            "user_id": user.pk,
            "approval_required": needs_approval,
        },
    )
    return Provisioning(
        secret=totp.manual_entry_key(secret),
        uri=totp.provisioning_uri(secret, account=user.email),
    )


@sensitive_variables("password", "code")
def _remove_active_device(
    actor: AuthenticationContext, password: str, code: str, source: str
) -> MfaOutcome | None:
    """Delete the acting account's active second factor, given both proofs again.

    Returns None if it was deleted, with any pending challenge for the
    account, and otherwise the outcome to give back, having changed nothing.
    A wrong password and a wrong code are each recorded. Must be called inside
    a transaction. Raises PermissionDenied if the actor may not manage their
    second factor.
    """
    refusal = _confirm_password(actor, password, source)
    if refusal is not None:
        return refusal
    user = actor.user
    _lock_second_factor(user.pk)
    keys = (_key("identifier", user.email), _key("source", source))
    if selectors.mfa_state_of(user) != selectors.MfaState.ACTIVE:
        return MfaOutcome.UNAVAILABLE
    if _second_factor_throttled(user, keys[0]):
        return MfaOutcome.THROTTLED
    device = _accept_code(user, code, TotpDeviceState.ACTIVE)
    if device is None:
        _record(AuthenticationEventType.MFA_VERIFICATION_FAILED, user, *keys)
        logger.warning(
            "Second-factor code refused",
            extra={"event": "mfa.verification_failed", "user_id": user.pk},
        )
        return MfaOutcome.REFUSED
    device.delete()
    MfaChallenge.objects.filter(user=user).delete()
    return None


def _decide_enrollment(
    actor: AuthenticationContext, request_number: int, source: str, *, approve: bool
) -> MfaResult:
    awaiting = TotpDevice.objects.filter(pk=request_number, state=TotpDeviceState.PENDING_APPROVAL)
    with transaction.atomic():
        # Permission first, so that a caller without it learns nothing about
        # which requests exist.
        selectors.require_permission(actor, Permission.MFA_ENROLLMENT_APPROVE)
        user_id = awaiting.values_list("user_id", flat=True).first()
        if user_id is None:
            return MfaResult(MfaOutcome.UNAVAILABLE)
        _lock_second_factor(user_id)
        # Read again under the lock: the request may have been replaced or
        # decided meanwhile.
        device = awaiting.select_for_update().first()
        now = timezone.now()
        if device is None or now >= selectors.enrollment_expires_at(device):
            return MfaResult(MfaOutcome.UNAVAILABLE)
        if device.user_id == actor.user.pk:
            # The actor's own second factor is active, so this cannot happen
            # today. It is checked all the same, so that the rule holds here
            # by itself and not as a consequence of another rule.
            logger.warning(
                "Refused a decision on the actor's own enrolment",
                extra={"event": "mfa.own_enrollment_decision_refused", "user_id": actor.user.pk},
            )
            raise PermissionDenied

        user = User.objects.get(pk=device.user_id)
        if approve:
            device.state = TotpDeviceState.PENDING_VERIFICATION
            device.approved_at = now
            device.approved_by = actor.user
            device.save(update_fields=["state", "approved_at", "approved_by"])
            event_type = AuthenticationEventType.MFA_ENROLLMENT_APPROVED
        else:
            device.delete()
            event_type = AuthenticationEventType.MFA_ENROLLMENT_REJECTED
        _record(
            event_type,
            user,
            _key("identifier", user.email),
            _key("source", source),
            actor=actor.user,
        )

    logger.info(
        "Second-factor enrolment %s",
        "approved" if approve else "rejected",
        extra={
            "event": "mfa.enrollment_approved" if approve else "mfa.enrollment_rejected",
            "user_id": user.pk,
            "actor_id": actor.user.pk,
        },
    )
    return MfaResult(MfaOutcome.ACCEPTED)


@sensitive_variables("token")
def _issue_activation(user: User) -> str:
    """Give the account a new activation token, replacing any earlier one, and return it.

    The token is 256 random bits. Only its keyed hash is stored. Must be
    called inside a transaction.
    """
    token = secrets.token_urlsafe(32)
    AccountActivation.objects.update_or_create(
        user=user,
        defaults={"token_key": _key("activation", token), "created_at": timezone.now()},
    )
    return token


def _pending_activation(token_key: str) -> tuple[User | None, AccountActivation | None]:
    """Return the account and activation with this token key, both locked, or neither.

    The account row is locked before the activation row, as disabling locks
    them, and the activation is read again under the lock: another request
    may have used or replaced it meanwhile. Must be called inside a
    transaction.
    """
    user_id = (
        AccountActivation.objects.filter(token_key=token_key)
        .values_list("user_id", flat=True)
        .first()
    )
    if user_id is None:
        return None, None
    user = User.objects.select_for_update().get(pk=user_id)
    activation = (
        AccountActivation.objects.select_for_update()
        .filter(token_key=token_key, user_id=user_id)
        .first()
    )
    if activation is None:
        return None, None
    return user, activation


@sensitive_variables("url")
def _send_verification(user: User, url: str, source_key: str, actor: User) -> bool:
    """Send the account its verification message, and record that if it was handed on.

    Returns whether it was. A message that could not be sent is logged as an
    error, without its content, and recorded nowhere: the account still
    awaits a message.
    """
    lifetime_hours = int(settings.ACCOUNT_ACTIVATION_LIFETIME.total_seconds() // 3600)
    try:
        mail.deliver(
            to=user.email,
            subject=verification_subject(),
            body=verification_body(url=url, lifetime_hours=lifetime_hours),
        )
    except mail.DeliveryError as error:
        # No traceback: what a mail service says when it refuses a message
        # can repeat the recipient's address.
        logger.error(  # noqa: TRY400 - deliberately without the traceback, see above
            "The verification message could not be sent",
            extra={
                "event": "accounts.verification_not_sent",
                "user_id": user.pk,
                "cause": type(error.__cause__).__name__,
            },
        )
        return False
    _record_account(AccountEventType.VERIFICATION_SENT, user, source_key, actor=actor)
    logger.info(
        "Verification message sent",
        extra={"event": "accounts.verification_sent", "user_id": user.pk, "actor_id": actor.pk},
    )
    return True


def verification_subject() -> str:
    """Return the subject of the verification message."""
    return _("Activate your CAIPO account")


def verification_body(*, url: str, lifetime_hours: int) -> str:
    """Return the text of the verification message.

    The same for every recipient apart from the link: it names no person, no
    email address, and no role, and holds no password, secret, or anything
    about what the account can reach.
    """
    return _(
        "An account has been created for this email address on CAIPO, the Central Asia"
        " AI Policy Observatory.\n"
        "\n"
        "To confirm that this address is yours and choose your password, open this"
        " link:\n"
        "\n"
        "%(url)s\n"
        "\n"
        "The link works once and stops working %(hours)d hours after this message was"
        " sent. Do not pass it on: whoever opens it first sets the password of the"
        " account.\n"
        "\n"
        "If you were not expecting this message, ignore it. Nothing happens unless the"
        " link is used.\n"
    ) % {"url": url, "hours": lifetime_hours}


@sensitive_variables("token")
def _issue_password_reset(user: User) -> str:
    """Give the account a new reset token, replacing any earlier one, and return it.

    The token is 256 random bits. Only its keyed hash is stored, with the
    time it lapses. Must be called inside a transaction, holding the
    account's row lock.
    """
    token = secrets.token_urlsafe(32)
    now = timezone.now()
    PasswordReset.objects.update_or_create(
        user=user,
        defaults={
            "token_key": _key("password_reset", token),
            "created_at": now,
            "expires_at": now + settings.PASSWORD_RESET_LIFETIME,
        },
    )
    return token


def _pending_password_reset(token_key: str) -> tuple[User | None, PasswordReset | None]:
    """Return the account and reset with this token key, both locked, or neither.

    Four locks, in the order every other operation takes them. First the
    lock on the account's email address that a sign-in holds from before it
    checks the password until it has stored its challenge: a sign-in for this
    account cannot then run alongside. Then the account's second-factor lock,
    which whoever examines a code for a pending challenge holds: without it,
    that operation would hold the challenge and wait for the account row
    while this one held the account row and waited for the challenge. Then
    the account row, as disabling locks it, and then the reset row, which is
    read again under the locks: another request may have used or replaced it
    meanwhile. Must be called inside a transaction.
    """
    found = (
        PasswordReset.objects.filter(token_key=token_key)
        .values_list("user_id", "user__email")
        .first()
    )
    if found is None:
        return None, None
    user_id, email = found
    _lock_attempts(_IDENTIFIER_LOCK, _key("identifier", email))
    _lock_second_factor(user_id)
    user = User.objects.select_for_update().get(pk=user_id)
    reset = (
        PasswordReset.objects.select_for_update()
        .filter(token_key=token_key, user_id=user_id)
        .first()
    )
    if reset is None:
        return None, None
    return user, reset


def _reset_request_throttled_by(identifier_key: str, source_key: str) -> str | None:
    """Return which limit refuses a new reset request now, "email" or "source", or None.

    Every request that was recorded counts, whether or not its email address
    had an account, and nothing clears either count early.
    """
    now = timezone.now()
    requests = AuthenticationEvent.objects.filter(
        event_type=AuthenticationEventType.PASSWORD_RESET_REQUESTED
    )
    for_email = requests.filter(
        identifier_key=identifier_key,
        created_at__gte=now - settings.PASSWORD_RESET_REQUEST_EMAIL_WINDOW,
    ).count()
    if for_email >= settings.PASSWORD_RESET_REQUEST_EMAIL_LIMIT:
        return "email"
    from_source = requests.filter(
        source_key=source_key,
        created_at__gte=now - settings.PASSWORD_RESET_REQUEST_SOURCE_WINDOW,
    ).count()
    if from_source >= settings.PASSWORD_RESET_REQUEST_SOURCE_LIMIT:
        return "source"
    return None


@sensitive_variables("url")
def _send_password_reset(user: User, url: str) -> None:
    """Send the account its reset message.

    A message that could not be sent is logged as an error, without its
    content, and changes nothing else: the caller's answer is the same.
    """
    lifetime_hours = int(settings.PASSWORD_RESET_LIFETIME.total_seconds() // 3600)
    try:
        mail.deliver(
            to=user.email,
            subject=password_reset_subject(),
            body=password_reset_body(url=url, lifetime_hours=lifetime_hours),
        )
    except mail.DeliveryError as error:
        # No traceback: what a mail service says when it refuses a message
        # can repeat the recipient's address.
        logger.error(  # noqa: TRY400 - deliberately without the traceback, see above
            "The password reset message could not be sent",
            extra={
                "event": "password_reset.message_not_sent",
                "user_id": user.pk,
                "cause": type(error.__cause__).__name__,
            },
        )
        return
    logger.info(
        "Password reset message sent",
        extra={"event": "password_reset.message_sent", "user_id": user.pk},
    )


def password_reset_subject() -> str:
    """Return the subject of the password reset message."""
    return _("Reset your CAIPO password")


def password_reset_body(*, url: str, lifetime_hours: int) -> str:
    """Return the text of the password reset message.

    The same for every recipient apart from the link: it names no person, no
    email address, and no role, and holds no password, secret, or anything
    about what the account can reach.
    """
    lapses = ngettext(
        "The link works once and stops working %(hours)d hour after this message was sent.",
        "The link works once and stops working %(hours)d hours after this message was sent.",
        lifetime_hours,
    ) % {"hours": lifetime_hours}
    return _(
        "A password reset was requested for the account with this email address on"
        " CAIPO, the Central Asia AI Policy Observatory.\n"
        "\n"
        "To choose a new password, open this link:\n"
        "\n"
        "%(url)s\n"
        "\n"
        "%(lapses)s Do not pass it on: whoever opens it first sets the password of the"
        " account.\n"
        "\n"
        "If you were not expecting this message, ignore it. Nothing happens unless the"
        " link is used.\n"
    ) % {"url": url, "lapses": lapses}


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


def _confirm_password(
    actor: AuthenticationContext, password: str, source: str
) -> MfaOutcome | None:
    """Check the acting account's password again, before its second factor is changed.

    Returns None if the password is right, and otherwise the outcome to give
    back. A wrong password is recorded and counts towards the same limits as
    a refused sign-in, for the account and for the source, so being signed in
    buys no extra guesses at the password. Must be called inside a
    transaction. Raises PermissionDenied if the actor may not manage their
    second factor.
    """
    selectors.require_permission(actor, Permission.MFA_MANAGE_OWN)
    user = actor.user
    identifier_key = _key("identifier", user.email)
    source_key = _key("source", source)
    _lock_attempts(_SOURCE_LOCK, source_key)
    _lock_attempts(_IDENTIFIER_LOCK, identifier_key)

    throttled_by = _throttled_by(identifier_key, source_key)
    if throttled_by is not None:
        logger.warning(
            "Password confirmation throttled",
            extra={"event": "authentication.throttled", "scope": throttled_by},
        )
        return MfaOutcome.THROTTLED
    # Read again: the object in the context may be out of date.
    if not User.objects.get(pk=user.pk).check_password(password):
        _record(
            AuthenticationEventType.PASSWORD_CONFIRMATION_FAILED, user, identifier_key, source_key
        )
        logger.warning(
            "Password confirmation refused",
            extra={"event": "authentication.password_confirmation_refused", "user_id": user.pk},
        )
        return MfaOutcome.REFUSED
    return None


def _pending_challenge(token_key: str) -> MfaChallenge | None:
    """Return the challenge with this token key if it can still be used, locked.

    Takes the second-factor lock of the challenge's account, and reads the
    challenge again under it: another request may have used it meanwhile.
    Must be called inside a transaction.
    """
    user_id = (
        MfaChallenge.objects.filter(token_key=token_key).values_list("user_id", flat=True).first()
    )
    if user_id is None:
        return None
    _lock_second_factor(user_id)
    pending = (
        MfaChallenge.objects.select_for_update()
        .filter(token_key=token_key, user_id=user_id)
        .first()
    )
    if pending is None or timezone.now() >= pending.created_at + settings.MFA_CHALLENGE_LIFETIME:
        return None
    return pending


def _lock_second_factor(user_id: int) -> None:
    """Hold, until the transaction ends, the lock for one account's second factor.

    One code is examined at a time for an account, so codes sent together
    cannot each be counted as the first failure or each be accepted.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)", [_SECOND_FACTOR_LOCK, user_id % 2**31]
        )


def _second_factor_throttled(user: User, identifier_key: str) -> bool:
    """Return whether too many codes were refused for the account recently.

    Counted over the whole window, whatever succeeded in between: an accepted
    code from the real device must not buy fresh guesses for someone else.
    """
    refused = AuthenticationEvent.objects.filter(
        event_type=AuthenticationEventType.MFA_VERIFICATION_FAILED,
        identifier_key=identifier_key,
        created_at__gte=timezone.now() - settings.MFA_THROTTLE_WINDOW,
    ).count()
    if refused < settings.MFA_THROTTLE_FAILURES:
        return False
    logger.warning("Second-factor code throttled", extra={"event": "mfa.throttled"})
    return True


@sensitive_variables("code", "secret")
def _accept_code(user: User, code: str, state: TotpDeviceState) -> TotpDevice | None:
    """Return the account's device if the code is right for it now, and None otherwise.

    The device must be in the given state. A right code is accepted once: its
    time step is stored, and only a later step is accepted afterwards. A
    device awaiting its first code becomes active when it receives a right
    one, and keeps whatever approval it had. Must be called
    inside a transaction, holding the account's second-factor lock.

    A secret that cannot be decrypted is logged as an error and refuses the
    code like a wrong one: nothing is accepted that could not be checked.
    """
    device = TotpDevice.objects.select_for_update().filter(user=user, state=state).first()
    if device is None:
        return None
    try:
        secret = totp.decrypt_secret(
            bytes(device.secret_ciphertext), device.key_id, user_id=user.pk
        )
    except totp.SecretUnavailableError:
        logger.error(
            "A second-factor secret cannot be decrypted with the configured key",
            extra={"event": "mfa.secret_unavailable", "user_id": user.pk},
        )
        return None
    now = timezone.now()
    step = totp.matching_step(secret, code, at=now)
    if step is None or (device.last_used_step is not None and step <= device.last_used_step):
        return None
    device.last_used_step = step
    if device.state == TotpDeviceState.PENDING_VERIFICATION:
        device.state = TotpDeviceState.ACTIVE
        device.confirmed_at = now
    device.save(update_fields=["last_used_step", "state", "confirmed_at"])
    return device


def _throttled_by(identifier_key: str, source_key: str) -> str | None:
    """Return which limit refuses a new attempt now, "account" or "source", or None.

    A wrong password counts the same whether it was given at sign-in or when a
    signed-in account was asked for it again.
    """
    window_start = timezone.now() - settings.LOGIN_THROTTLE_WINDOW
    failures = AuthenticationEvent.objects.filter(
        event_type__in=[
            AuthenticationEventType.LOGIN_FAILURE,
            AuthenticationEventType.PASSWORD_CONFIRMATION_FAILED,
        ]
    )

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
    event_type: AuthenticationEventType,
    user: User | None,
    identifier_key: str,
    source_key: str,
    *,
    actor: User | None = None,
) -> None:
    AuthenticationEvent.objects.create(
        event_type=event_type,
        user=user,
        actor=actor,
        identifier_key=identifier_key,
        source_key=source_key,
        correlation_id=get_correlation_id() or "",
    )


def _record_account(
    event_type: AccountEventType,
    user: User | None,
    source_key: str = "",
    *,
    actor: User | None = None,
) -> None:
    """Append an account event. `source_key` is empty for a change made by a
    service that no request reaches yet, and so has no source."""
    AccountEvent.objects.create(
        event_type=event_type,
        user=user,
        actor=actor,
        source_key=source_key,
        correlation_id=get_correlation_id() or "",
    )
