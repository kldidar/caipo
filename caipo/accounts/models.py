"""Users and their lifecycle, the record of their roles, the record of sign-ins,
second factors, account activation, password reset, and requests to recover a
lost second factor (ADR-0007, ADR-0014, ADR-0015, ADR-0016, ADR-0017), and
the general audit record (ADR-0018).

Redaction records are not here yet.
"""

import functools
import operator
import unicodedata
from collections.abc import Iterator, Mapping
from types import MappingProxyType
from typing import Any, ClassVar, NoReturn

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.utils.translation import gettext_lazy as _

from caipo.accounts.authorization import Role
from caipo.core.append_only import AppendOnlyModel, AppendOnlyQuerySet


class AccountStatus(models.TextChoices):
    """Where an account stands in its lifecycle (ADR-0015). There are no other states."""

    # The account exists and nobody has yet shown that its email address is
    # theirs. It has no password anybody knows and cannot be signed in to.
    PENDING_VERIFICATION = "pending_verification", _("Awaiting verification")
    # The account can be signed in to, according to its roles and the
    # second-factor policy.
    ACTIVE = "active", _("Active")
    # An Administrator disabled the account. It cannot be signed in to and
    # holds no permission. Its roles stay on record.
    DISABLED = "disabled", _("Disabled")


# Not Django's salt: a session value of an epoch above 0 must never equal the
# value Django computes for the same password.
_EPOCH_SESSION_SALT = "caipo.accounts.models.User.session_auth_hash"


class UserManager(BaseUserManager["User"]):
    @classmethod
    def normalize_email(cls, email: str | None) -> str:
        """Return the form in which an email address identifies an account.

        The whole address is lower-cased, not only the domain, and brought to
        Unicode compatibility form (NFKC), as Django does for usernames: two
        accounts whose addresses differ only by case or by look-alike
        compatibility characters would be indistinguishable to the people
        using them.
        """
        return unicodedata.normalize("NFKC", email or "").strip().lower()

    def get_by_natural_key(self, username: str | None) -> User:
        return self.get(email=self.normalize_email(username))

    def create_user(self, email: str, password: str | None = None) -> User:
        """Create and save an active user.

        This is not how an Administrator creates an account: that is
        `caipo.accounts.services.create_user`, which creates it awaiting
        verification. This makes the account active at once and says nothing
        about its email address. The first-Administrator bootstrap uses it.

        With no password the account gets an unusable one and cannot sign in
        until a password is set. Raises ValueError if the email is empty, and
        IntegrityError if an account with that email already exists.
        """
        email = self.normalize_email(email)
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=email, status=AccountStatus.ACTIVE, activated_at=timezone.now())
        user.set_password(password)
        user.save(using=self._db)
        return user


class User(AbstractBaseUser):
    """An authenticated account, identified by its email address.

    There is deliberately no is_staff or is_superuser flag, and no role field.
    Access follows from the roles recorded in RoleEvent, and a superuser flag
    would bypass the deny-by-default permission checks they require.

    `status` is the lifecycle state, and the only place it is stored. Two
    times keep what the state alone would lose: `email_verified_at`, when the
    holder of the email address proved it was theirs, and `activated_at`, when
    the account first became active. A disabled account keeps both, so
    enabling it returns it to where it was.

    `session_epoch` counts how many times the account's sessions were ended
    without its password changing (ADR-0017 point 46). It starts at 0, and at
    0 a session is bound to the account exactly as Django binds it, so a
    session established before this field existed is still recognised.
    """

    email = models.EmailField(_("email address"), unique=True)
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=AccountStatus,
        default=AccountStatus.PENDING_VERIFICATION,
    )
    # Empty for the first Administrator, whose account is created at the
    # server: nobody verified that address by email.
    email_verified_at = models.DateTimeField(_("email verified at"), null=True, blank=True)
    activated_at = models.DateTimeField(_("activated at"), null=True, blank=True)
    session_epoch = models.PositiveIntegerField(_("session epoch"), default=0)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    objects: ClassVar[UserManager] = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        constraints = [
            # The manager stores addresses lower-cased. This holds the rule for
            # any row written without it.
            models.UniqueConstraint(Lower("email"), name="accounts_user_email_case_insensitive"),
            models.CheckConstraint(
                condition=models.Q(status__in=AccountStatus.values),
                name="accounts_user_status_known",
            ),
            # An account that awaits verification has never been verified or
            # active, and an active one records when it became so.
            models.CheckConstraint(
                condition=models.Q(
                    status=AccountStatus.PENDING_VERIFICATION,
                    email_verified_at__isnull=True,
                    activated_at__isnull=True,
                )
                | models.Q(status=AccountStatus.ACTIVE, activated_at__isnull=False)
                | models.Q(status=AccountStatus.DISABLED),
                name="accounts_user_status_matches_history",
            ),
        ]

    def __str__(self) -> str:
        return self.email

    @property
    def is_active(self) -> bool:  # type: ignore[override]  # Django declares a class attribute; here it is derived from the one stored state
        """Whether the account can be signed in to. What Django's authentication asks."""
        return self.status == AccountStatus.ACTIVE

    def get_session_auth_hash(self) -> str:
        """Return what a session of this account must hold to be recognised.

        At epoch 0 this is Django's own value, unchanged. Above 0 the epoch
        is part of it, under a salt of its own, so no value from one epoch
        equals a value from another. The password is part of it throughout:
        changing the password ends the account's sessions at every epoch.
        """
        if self.session_epoch == 0:
            return super().get_session_auth_hash()
        return self._epoch_session_auth_hash(secret=None)

    def get_session_auth_fallback_hash(self) -> Iterator[str]:
        """Yield the same value under each retired secret key, as Django does."""
        if self.session_epoch == 0:
            yield from super().get_session_auth_fallback_hash()
            return
        for secret in settings.SECRET_KEY_FALLBACKS:
            yield self._epoch_session_auth_hash(secret=secret)

    def _epoch_session_auth_hash(self, *, secret: str | bytes | None) -> str:
        # The epoch is decimal digits and is followed by a colon, so where it
        # ends and the password hash begins cannot be read two ways.
        return salted_hmac(
            _EPOCH_SESSION_SALT,
            f"{self.session_epoch}:{self.password}",
            secret=secret,
            algorithm="sha256",
        ).hexdigest()


class RoleEventType(models.TextChoices):
    GRANTED = "granted", _("Granted")
    REVOKED = "revoked", _("Revoked")


class RoleEvent(AppendOnlyModel):
    """One change to the roles of one user: a role granted, or a role revoked.

    Append-only. This table is both where roles are stored and the record of
    how they came to be: a user holds a role when the latest event for that
    user and role is a grant (docs/DATA_MODEL.md, modelling principle 5). There
    is no current-role row that could be overwritten, so a role cannot change
    without a new event naming who changed it, when, and why.

    Every event names the user who made the change, with one exception. The
    grant that creates the first Administrator is made by an operator at the
    server, before any account exists that could be its actor. It has no
    actor, says so in its reason, and can exist at most once.
    """

    # PROTECT: an event must never disappear because an account did. Accounts
    # are deactivated or anonymised, not deleted (ADR-0007 rule 10).
    user = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="role_events", verbose_name=_("user")
    )
    role = models.CharField(_("role"), max_length=20, choices=Role)
    event_type = models.CharField(_("event type"), max_length=10, choices=RoleEventType)
    actor = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("actor"),
        null=True,
        blank=True,
    )
    reason = models.TextField(_("reason"))
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    objects = AppendOnlyQuerySet["RoleEvent"].as_manager()

    class Meta:
        verbose_name = _("role event")
        verbose_name_plural = _("role events")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=Role.values), name="accounts_roleevent_role_known"
            ),
            models.CheckConstraint(
                condition=models.Q(event_type__in=RoleEventType.values),
                name="accounts_roleevent_event_type_known",
            ),
            models.CheckConstraint(
                condition=~models.Q(reason=""), name="accounts_roleevent_reason_given"
            ),
            # Separation of duties: nobody changes their own roles.
            models.CheckConstraint(
                condition=~models.Q(actor=models.F("user")),
                name="accounts_roleevent_actor_is_not_user",
            ),
            # An event without an actor can only be the grant that creates the
            # first Administrator...
            models.CheckConstraint(
                condition=models.Q(actor__isnull=False)
                | models.Q(role=Role.ADMINISTRATOR, event_type=RoleEventType.GRANTED),
                name="accounts_roleevent_no_actor_only_for_bootstrap",
            ),
            # ...and there can be only one such event, ever. Every event
            # without an actor has the same event type, so uniqueness of the
            # event type among them allows a single row.
            models.UniqueConstraint(
                fields=["event_type"],
                condition=models.Q(actor__isnull=True),
                name="accounts_roleevent_single_bootstrap",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.role} {self.event_type}"


class AuthenticationEventType(models.TextChoices):
    LOGIN_SUCCESS = "login_success", _("Signed in")
    LOGIN_FAILURE = "login_failure", _("Sign-in failed")
    LOGOUT = "logout", _("Signed out")
    # A signed-in account was asked for its password again and gave a wrong one.
    PASSWORD_CONFIRMATION_FAILED = "password_confirmation_failed", _("Password not confirmed")
    # The password was accepted and a second-factor code is now awaited.
    MFA_CHALLENGE_ISSUED = "mfa_challenge_issued", _("Second factor requested")
    MFA_ENROLLMENT_STARTED = "mfa_enrollment_started", _("Second-factor enrolment started")
    MFA_ENROLLMENT_SUCCEEDED = "mfa_enrollment_succeeded", _("Second factor enrolled")
    MFA_VERIFICATION_FAILED = "mfa_verification_failed", _("Second-factor code refused")
    MFA_VERIFICATION_SUCCEEDED = "mfa_verification_succeeded", _("Second-factor code accepted")
    MFA_DISABLED = "mfa_disabled", _("Second factor disabled")
    # An Administrator approved, or rejected, another account's enrolment
    # request. The event names the account and, as its actor, the Administrator.
    MFA_ENROLLMENT_APPROVED = "mfa_enrollment_approved", _("Second-factor enrolment approved")
    MFA_ENROLLMENT_REJECTED = "mfa_enrollment_rejected", _("Second-factor enrolment rejected")
    # An active second factor was given up, on both proofs, for a new enrolment.
    MFA_DEVICE_REPLACED = "mfa_device_replaced", _("Second factor replaced")
    # Somebody who is not signed in asked for a reset message, used a reset
    # token to set a new password, or presented a token that was refused
    # (ADR-0016).
    PASSWORD_RESET_REQUESTED = "password_reset_requested", _("Password reset requested")
    PASSWORD_RESET_SUCCEEDED = "password_reset_succeeded", _("Password reset")
    PASSWORD_RESET_FAILED = "password_reset_failed", _("Password reset refused")
    # Recovery of a lost second factor (ADR-0017). The names are fixed: the
    # table is append-only and its rows cannot be renamed.
    MFA_RECOVERY_REQUESTED = "mfa_recovery_requested", _("Second-factor recovery requested")
    MFA_RECOVERY_FAILED = "mfa_recovery_failed", _("Second-factor recovery request refused")
    # An Administrator rejected, or authorised, another account's recovery
    # request. The event names the account and, as its actor, the Administrator.
    MFA_RECOVERY_REJECTED = "mfa_recovery_rejected", _("Second-factor recovery rejected")
    MFA_RECOVERY_AUTHORIZED = "mfa_recovery_authorized", _("Second-factor recovery authorised")
    MFA_RECOVERY_COMPLETED = "mfa_recovery_completed", _("Second-factor recovery completed")
    # An emergency action of the command at the server's terminal. It names
    # the account and no actor: whoever ran it is not an account.
    MFA_RECOVERY_BREAK_GLASS = (
        "mfa_recovery_break_glass",
        _("Second-factor recovery by break-glass"),
    )


class BreakGlassAction(models.TextChoices):
    """What one `mfa_recovery_break_glass` event records. There are no others."""

    REVOKE_DEVICE = "revoke_device", _("Lost device revoked")
    APPROVE_ENROLLMENT = "approve_enrollment", _("Enrolment approved")


# The events that one account causes for another. Only these name an actor.
DECISION_EVENT_TYPES = (
    AuthenticationEventType.MFA_ENROLLMENT_APPROVED,
    AuthenticationEventType.MFA_ENROLLMENT_REJECTED,
    AuthenticationEventType.MFA_RECOVERY_REJECTED,
    AuthenticationEventType.MFA_RECOVERY_AUTHORIZED,
)

# The events that can name nobody: what was submitted, an email address, a
# reset token, or a second-factor challenge, may belong to no account.
USERLESS_EVENT_TYPES = (
    AuthenticationEventType.LOGIN_FAILURE,
    AuthenticationEventType.PASSWORD_RESET_REQUESTED,
    AuthenticationEventType.PASSWORD_RESET_FAILED,
    AuthenticationEventType.MFA_RECOVERY_FAILED,
)


class AuthenticationEvent(AppendOnlyModel):
    """One sign-in, failed sign-in, sign-out, change to a second factor, step
    of a password reset, or step of the recovery of a lost second factor.

    Append-only, and deliberately small. It records that something happened,
    when, to which account if that is known, and under which request. It is
    also what sign-in, second-factor, and password-reset throttling count. It
    is not the general audit record.

    It never holds a password, a password hash, a second-factor code or
    secret, a reset token or its hash, a session identifier, or anything else
    from the request. What was typed as the email address and where the
    request came from are kept only as keyed hashes: enough to count attempts
    that belong together, not enough to read back what was submitted. People
    do type passwords into the email field.
    """

    event_type = models.CharField(_("event type"), max_length=32, choices=AuthenticationEventType)
    # Empty for a failed sign-in or a reset request with an email address
    # that belongs to no account, and for a refused reset token or a refused
    # recovery submission that belongs to none: there is nobody to name, and
    # naming somebody would be wrong.
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("user"),
        null=True,
        blank=True,
    )
    # Set only for a decision on another account's enrolment request or
    # recovery request: the Administrator who made it. Every other event is
    # caused by the account it names, or by nobody known.
    actor = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("actor"),
        null=True,
        blank=True,
    )
    # Empty for a refused reset token that belongs to no account: no email
    # address was submitted, and nothing derived from the token is kept.
    identifier_key = models.CharField(_("identifier key"), max_length=64)
    # Empty on a break-glass event, and the database requires it there: the
    # command at the server's terminal is not a request and has no address.
    source_key = models.CharField(_("source key"), max_length=64)
    correlation_id = models.CharField(_("correlation ID"), max_length=32, blank=True)
    # Which of its two actions a break-glass event records. Empty, and never
    # null, on every other event: a null would pass a check it should fail.
    break_glass_action = models.CharField(
        _("break-glass action"), max_length=20, choices=BreakGlassAction, blank=True, default=""
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    objects = AppendOnlyQuerySet["AuthenticationEvent"].as_manager()

    class Meta:
        verbose_name = _("authentication event")
        verbose_name_plural = _("authentication events")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(event_type__in=AuthenticationEventType.values),
                name="accounts_authenticationevent_event_type_known",
            ),
            # Only a failed sign-in, a reset request, a refused reset, and a
            # refused recovery submission can be without a user.
            models.CheckConstraint(
                condition=models.Q(user__isnull=False)
                | models.Q(event_type__in=USERLESS_EVENT_TYPES),
                name="accounts_authenticationevent_user_known_unless_failure",
            ),
            # A decision names who made it, and nothing else names an actor.
            models.CheckConstraint(
                condition=models.Q(actor__isnull=False, event_type__in=DECISION_EVENT_TYPES)
                | (models.Q(actor__isnull=True) & ~models.Q(event_type__in=DECISION_EVENT_TYPES)),
                name="accounts_authenticationevent_actor_iff_decision",
            ),
            # Nobody decides on their own enrolment or their own recovery.
            models.CheckConstraint(
                condition=~models.Q(actor=models.F("user")),
                name="accounts_authenticationevent_actor_is_not_user",
            ),
            # A break-glass event states which of its two actions it records,
            # and no other event states one.
            models.CheckConstraint(
                condition=models.Q(
                    event_type=AuthenticationEventType.MFA_RECOVERY_BREAK_GLASS,
                    break_glass_action__in=BreakGlassAction.values,
                )
                | (
                    ~models.Q(event_type=AuthenticationEventType.MFA_RECOVERY_BREAK_GLASS)
                    & models.Q(break_glass_action="")
                ),
                name="accounts_authenticationevent_action_iff_break_glass",
            ),
            # A break-glass event records no network address. What any other
            # event holds here is not decided by this constraint.
            models.CheckConstraint(
                condition=~models.Q(event_type=AuthenticationEventType.MFA_RECOVERY_BREAK_GLASS)
                | models.Q(source_key=""),
                name="accounts_authenticationevent_break_glass_has_no_source",
            ),
        ]
        indexes = [
            # Every sign-in attempt and every reset request counts recent
            # events by each of these.
            models.Index(
                fields=["identifier_key", "created_at"], name="accounts_authevent_identifier"
            ),
            models.Index(fields=["source_key", "created_at"], name="accounts_authevent_source"),
        ]

    def __str__(self) -> str:
        return self.event_type


class TotpDeviceState(models.TextChoices):
    # A secret has been issued to an account whose roles require a second
    # factor, and no Administrator has approved the request yet. No code is
    # accepted for it.
    PENDING_APPROVAL = "pending_approval", _("Awaiting approval")
    # A secret has been issued, any approval it needed has been given, and no
    # code from it has been accepted yet.
    PENDING_VERIFICATION = "pending_verification", _("Awaiting verification")
    # The account proved possession of the secret. This is the second factor.
    ACTIVE = "active", _("Active")


class TotpDevice(models.Model):
    """The TOTP second factor of one account, pending or active (ADR-0014).

    An account with no row is not enrolled. There is at most one row for an
    account, so an account cannot have two second factors, or one pending
    beside one active. A pending row grants nothing. Disabling removes the
    row, and with it the secret; what happened is kept in AuthenticationEvent.

    A device is trusted when `approved_at` is set: an Administrator, named in
    `approved_by`, approved the enrolment, or one of two things that name
    nobody did: the first-Administrator bootstrap established it, or the
    break-glass command approved the enrolment that followed the recovery of
    an Administrator (ADR-0017 point 69). Only a trusted
    device counts towards MFA_VERIFIED. A device enrolled on a password alone
    is asked for at sign-in and proves nothing more than the password.

    The secret is never stored as it is used. `secret_ciphertext` is the
    secret under authenticated encryption with a key that is not in the
    database, bound to the account it was issued to, and `key_id` names the
    key without revealing it. See `caipo.accounts.totp`.
    """

    user = models.OneToOneField(
        User, on_delete=models.PROTECT, related_name="+", verbose_name=_("user")
    )
    state = models.CharField(_("state"), max_length=20, choices=TotpDeviceState)
    secret_ciphertext = models.BinaryField(_("encrypted secret"))
    key_id = models.CharField(_("encryption key identifier"), max_length=16)
    # The time step of the last code accepted. A code is accepted only for a
    # later step, so a code that was seen in use cannot be used again.
    last_used_step = models.BigIntegerField(_("last used time step"), null=True, blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    confirmed_at = models.DateTimeField(_("confirmed at"), null=True, blank=True)
    approved_at = models.DateTimeField(_("approved at"), null=True, blank=True)
    approved_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("approved by"),
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = _("TOTP device")
        verbose_name_plural = _("TOTP devices")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(state__in=TotpDeviceState.values),
                name="accounts_totpdevice_state_known",
            ),
            # Active means confirmed, and only active does: a row cannot claim
            # to be the second factor without recording that a code proved it.
            models.CheckConstraint(
                condition=models.Q(
                    state__in=[
                        TotpDeviceState.PENDING_APPROVAL,
                        TotpDeviceState.PENDING_VERIFICATION,
                    ],
                    confirmed_at__isnull=True,
                    last_used_step__isnull=True,
                )
                | models.Q(
                    state=TotpDeviceState.ACTIVE,
                    confirmed_at__isnull=False,
                    last_used_step__isnull=False,
                ),
                name="accounts_totpdevice_active_iff_confirmed",
            ),
            # A request that still awaits approval has not been approved.
            models.CheckConstraint(
                condition=~models.Q(state=TotpDeviceState.PENDING_APPROVAL)
                | models.Q(approved_at__isnull=True),
                name="accounts_totpdevice_awaiting_approval_is_unapproved",
            ),
            # Whoever is named as approving did approve, and nobody approves
            # their own second factor.
            models.CheckConstraint(
                condition=models.Q(approved_by__isnull=True)
                | (models.Q(approved_at__isnull=False) & ~models.Q(approved_by=models.F("user"))),
                name="accounts_totpdevice_approver_is_not_user",
            ),
        ]

    def __str__(self) -> str:
        return self.state


class MfaChallenge(models.Model):
    """A sign-in whose password was accepted and whose second factor is awaited.

    The pending authentication state, held on the server. It is created only
    by the sign-in service, names the one account it can complete a sign-in
    for, and is removed when it is used, cancelled, or replaced. There is at
    most one for an account. It grants nothing by itself.

    `token_key` is a keyed hash of the token that the pending session holds.
    """

    user = models.OneToOneField(
        User, on_delete=models.PROTECT, related_name="+", verbose_name=_("user")
    )
    token_key = models.CharField(_("token key"), max_length=64, unique=True)
    created_at = models.DateTimeField(_("created at"))

    class Meta:
        verbose_name = _("second-factor challenge")
        verbose_name_plural = _("second-factor challenges")

    def __str__(self) -> str:
        return f"challenge for user {self.user_id}"


class AccountActivation(models.Model):
    """An account that awaits verification, and the token that can activate it (ADR-0015).

    Created with the account and replaced when the verification message is
    sent again, so there is at most one for an account and an earlier token
    stops working. Removed when it is used and when the account is disabled.
    It grants nothing by itself. Operational state, like MfaChallenge.

    `token_key` is a keyed hash of the token that was sent to the account's
    email address. The token itself is stored nowhere.
    """

    user = models.OneToOneField(
        User, on_delete=models.PROTECT, related_name="+", verbose_name=_("user")
    )
    token_key = models.CharField(_("token key"), max_length=64, unique=True)
    created_at = models.DateTimeField(_("created at"))

    class Meta:
        verbose_name = _("account activation")
        verbose_name_plural = _("account activations")

    def __str__(self) -> str:
        return f"activation for user {self.user_id}"


class PasswordReset(models.Model):
    """An active account whose owner asked to replace a forgotten password, and
    the token that can do it (ADR-0016).

    Created when a reset is asked for and replaced when it is asked for again,
    so there is at most one for an account and an earlier token stops working.
    Removed when it is used and when the account is disabled. It grants
    nothing by itself. Operational state, like AccountActivation, and
    separate from it: neither token is accepted where the other is expected.

    `token_key` is a keyed hash of the token that was sent to the account's
    email address. The token itself is stored nowhere. `expires_at` is when
    the token stops working, fixed when it was issued.
    """

    user = models.OneToOneField(
        User, on_delete=models.PROTECT, related_name="+", verbose_name=_("user")
    )
    token_key = models.CharField(_("token key"), max_length=64, unique=True)
    created_at = models.DateTimeField(_("created at"))
    expires_at = models.DateTimeField(_("expires at"))

    class Meta:
        verbose_name = _("password reset")
        verbose_name_plural = _("password resets")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(expires_at__gt=models.F("created_at")),
                name="accounts_passwordreset_expires_after_created",
            ),
        ]

    def __str__(self) -> str:
        return f"password reset for user {self.user_id}"


class RecoveryRequestChangeError(Exception):
    """An attempt was made to change a recovery request where it stands."""


class MfaRecoveryRequestQuerySet(models.QuerySet["MfaRecoveryRequest"]):
    """Refuses the bulk operations that would change a request where it stands.

    Removing requests is not refused: that is how one is used up, rejected,
    or replaced.
    """

    def update(self, **kwargs: Any) -> NoReturn:
        raise RecoveryRequestChangeError("A recovery request is replaced, never updated.")

    def bulk_update(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise RecoveryRequestChangeError("A recovery request is replaced, never updated.")

    def bulk_create(self, *args: Any, **kwargs: Any) -> NoReturn:
        # It can be told to overwrite the row it conflicts with, which is an
        # update. Requests are made one at a time.
        raise RecoveryRequestChangeError("Recovery requests are created one at a time.")


class MfaRecoveryRequest(models.Model):
    """An account whose owner asked for a lost second factor to be revoked (ADR-0017).

    The identifier of the row is the number of the request: what its owner is
    shown and gives to an Administrator, who authorises or rejects that number
    and no other. There is at most one for an account. It grants nothing by
    itself. Operational state, like MfaChallenge.

    Unlike the other operational records, a request is never changed where it
    stands. Which account it is for and when it was made decide whether it
    may be authorised, and the number names exactly that. A new request
    therefore removes this row and creates another, which has another number,
    and the earlier number names nothing. The guards here and in
    MfaRecoveryRequestQuerySet refuse an update made through the model or its
    manager, which is every way the application writes this table. Unlike an
    append-only record, no database trigger stands behind them: SQL sent
    past the model is not refused.

    It holds no token, no secret, and nothing about how the person was
    identified.
    """

    user = models.OneToOneField(
        User, on_delete=models.PROTECT, related_name="+", verbose_name=_("user")
    )
    created_at = models.DateTimeField(_("created at"))

    objects = MfaRecoveryRequestQuerySet.as_manager()

    class Meta:
        verbose_name = _("second-factor recovery request")
        verbose_name_plural = _("second-factor recovery requests")

    def __str__(self) -> str:
        return f"recovery request for user {self.user_id}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise RecoveryRequestChangeError("A recovery request is replaced, never updated.")
        super().save(*args, **kwargs)


class AccountEventType(models.TextChoices):
    ACCOUNT_CREATED = "account_created", _("Account created")
    VERIFICATION_SENT = "verification_sent", _("Verification message sent")
    VERIFICATION_SUCCEEDED = "verification_succeeded", _("Email address verified")
    VERIFICATION_FAILED = "verification_failed", _("Verification refused")
    ACCOUNT_DISABLED = "account_disabled", _("Account disabled")
    ACCOUNT_ENABLED = "account_enabled", _("Account enabled")


# What an Administrator does to an account. Only these name an actor.
ADMINISTRATIVE_ACCOUNT_EVENT_TYPES = (
    AccountEventType.ACCOUNT_CREATED,
    AccountEventType.VERIFICATION_SENT,
    AccountEventType.ACCOUNT_DISABLED,
    AccountEventType.ACCOUNT_ENABLED,
)


class AccountEvent(AppendOnlyModel):
    """One step in the lifecycle of an account (ADR-0015).

    Append-only. It records that an account was created, sent its verification
    message, verified, disabled, or enabled, and each refused attempt to
    verify: what happened, when, to which account if that is known, who did
    it if an Administrator did, and under which request. It is also what the
    throttling of verification attempts counts. It is not the general audit
    record.

    It never holds a verification token or its hash, a password, a
    second-factor secret, or an email address. Where a verification attempt
    came from is kept only as a keyed hash.
    """

    event_type = models.CharField(_("event type"), max_length=32, choices=AccountEventType)
    # Empty for a refused verification whose token belongs to no account.
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("user"),
        null=True,
        blank=True,
    )
    actor = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("actor"),
        null=True,
        blank=True,
    )
    # Empty for a change made by a service that no request reaches.
    source_key = models.CharField(_("source key"), max_length=64, blank=True)
    correlation_id = models.CharField(_("correlation ID"), max_length=32, blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    objects = AppendOnlyQuerySet["AccountEvent"].as_manager()

    class Meta:
        verbose_name = _("account event")
        verbose_name_plural = _("account events")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(event_type__in=AccountEventType.values),
                name="accounts_accountevent_event_type_known",
            ),
            # Only a refused verification can be without a user.
            models.CheckConstraint(
                condition=models.Q(user__isnull=False)
                | models.Q(event_type=AccountEventType.VERIFICATION_FAILED),
                name="accounts_accountevent_user_known_unless_failure",
            ),
            # What an Administrator does names the Administrator, and nothing
            # else names an actor.
            models.CheckConstraint(
                condition=models.Q(
                    actor__isnull=False, event_type__in=ADMINISTRATIVE_ACCOUNT_EVENT_TYPES
                )
                | (
                    models.Q(actor__isnull=True)
                    & ~models.Q(event_type__in=ADMINISTRATIVE_ACCOUNT_EVENT_TYPES)
                ),
                name="accounts_accountevent_actor_iff_administrative",
            ),
            # Nobody creates, invites, or enables their own account. Disabling
            # one's own is allowed while another Administrator remains
            # (ADR-0012).
            models.CheckConstraint(
                condition=~models.Q(actor=models.F("user"))
                | models.Q(event_type=AccountEventType.ACCOUNT_DISABLED),
                name="accounts_accountevent_actor_is_not_user_unless_disabling",
            ),
        ]
        indexes = [
            # Every verification attempt counts recent refusals from its source.
            models.Index(fields=["source_key", "created_at"], name="accounts_acctevent_source"),
        ]

    def __str__(self) -> str:
        return self.event_type


class AuditAction(models.TextChoices):
    """What an audit event says was done (ADR-0018 point 31). There are no others."""

    CREATED = "created", _("Created")
    UPDATED = "updated", _("Updated")
    DEACTIVATED = "deactivated", _("Deactivated")
    REACTIVATED = "reactivated", _("Reactivated")
    MARKED_ENTERED_IN_ERROR = "marked_entered_in_error", _("Marked as entered in error")


class AuditTargetType(models.TextChoices):
    """The kinds of record an audit event can name (ADR-0018 point 31).

    Known here as text: the records live in a higher layer, and nothing is
    imported for them. A later domain adds its kinds here, with a migration
    that widens the check.
    """

    COUNTRY = "registry.country", _("Country")
    LANGUAGE = "registry.language", _("Language")
    INSTITUTION = "registry.institution", _("Institution")
    INSTITUTION_NAME = "registry.institution_name", _("Institution name")


class AuditField(models.TextChoices):
    """The attributes whose change an audit event can record (ADR-0018 point 35).

    An attribute is on this list only if it can hold no secret and no personal
    data.
    """

    NAME_EN = "name_en", _("English name")
    KIND = "kind", _("Kind")
    COUNTRY = "country", _("Country")
    PARENT = "parent", _("Parent")
    SUCCESSOR = "successor", _("Successor")
    VALID_FROM = "valid_from", _("Valid from")
    VALID_TO = "valid_to", _("Valid to")


# The kinds of record each action applies to. Only a country or a language is
# deactivated and reactivated, and only an institution name is marked as
# entered in error. The database check and the writer both read this.
AUDIT_ACTION_TARGET_TYPES: Mapping[AuditAction, tuple[AuditTargetType, ...]] = MappingProxyType(
    {
        AuditAction.CREATED: tuple(AuditTargetType),
        AuditAction.UPDATED: tuple(AuditTargetType),
        AuditAction.DEACTIVATED: (AuditTargetType.COUNTRY, AuditTargetType.LANGUAGE),
        AuditAction.REACTIVATED: (AuditTargetType.COUNTRY, AuditTargetType.LANGUAGE),
        AuditAction.MARKED_ENTERED_IN_ERROR: (AuditTargetType.INSTITUTION_NAME,),
    }
)

# The longest rendered value a change record holds (owner decision of
# 2026-10-09 on ADR-0018 point 35). No attribute on the AuditField list may be
# given a longer limit than this without a review of this schema.
AUDIT_VALUE_MAX_LENGTH = 200


class AuditEvent(AppendOnlyModel):
    """One successful change that a signed-in account made to a registry record (ADR-0018).

    Append-only. It names what was done, to which record, by whom, when, and
    under which request. The record is named by its type and public
    identifier and never by a foreign key, so this app depends on nothing
    above it. The values a change replaced are in AuditEventChange.

    Every event has an actor, and the actor is an account: there is no
    anonymous, system, or bootstrap event. It holds no free text, and no
    password, secret, token, session identifier, source address, or personal
    data beyond the reference to the actor.

    It is not RoleEvent, AuthenticationEvent, or AccountEvent, and nothing is
    recorded both here and there. Only `caipo.accounts.services.record_audit_event`
    creates one.
    """

    action = models.CharField(_("action"), max_length=32, choices=AuditAction)
    target_type = models.CharField(_("target type"), max_length=32, choices=AuditTargetType)
    target_public_id = models.UUIDField(_("target public identifier"))
    # PROTECT: an event must never disappear because an account did.
    actor = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="+", verbose_name=_("actor")
    )
    correlation_id = models.CharField(_("correlation ID"), max_length=32, blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    objects = AppendOnlyQuerySet["AuditEvent"].as_manager()

    class Meta:
        verbose_name = _("audit event")
        verbose_name_plural = _("audit events")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(action__in=AuditAction.values),
                name="accounts_auditevent_action_known",
            ),
            models.CheckConstraint(
                condition=models.Q(target_type__in=AuditTargetType.values),
                name="accounts_auditevent_target_type_known",
            ),
            models.CheckConstraint(
                condition=functools.reduce(
                    operator.or_,
                    (
                        models.Q(action=action, target_type__in=target_types)
                        for action, target_types in AUDIT_ACTION_TARGET_TYPES.items()
                    ),
                ),
                name="accounts_auditevent_action_fits_target_type",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.target_type} {self.action}"


class AuditEventChange(AppendOnlyModel):
    """One attribute that an `updated` audit event changed: what it was, and what it became.

    Append-only. A registry record is overwritten in place, so without this
    the earlier value would be gone. A value is the attribute's own value in
    one fixed rendering: text as stored, a date in ISO 8601, a reference as
    the public identifier of the record referred to, and nothing as the empty
    string.

    The database cannot tell that the event of a change is an `updated` one;
    the service that writes both keeps that rule.
    """

    event = models.ForeignKey(
        AuditEvent, on_delete=models.PROTECT, related_name="changes", verbose_name=_("event")
    )
    field = models.CharField(_("field"), max_length=32, choices=AuditField)
    old_value = models.CharField(_("old value"), max_length=AUDIT_VALUE_MAX_LENGTH, blank=True)
    new_value = models.CharField(_("new value"), max_length=AUDIT_VALUE_MAX_LENGTH, blank=True)

    objects = AppendOnlyQuerySet["AuditEventChange"].as_manager()

    class Meta:
        verbose_name = _("audit event change")
        verbose_name_plural = _("audit event changes")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(field__in=AuditField.values),
                name="accounts_auditeventchange_field_known",
            ),
            models.CheckConstraint(
                condition=~models.Q(old_value=models.F("new_value")),
                name="accounts_auditeventchange_values_differ",
            ),
            models.UniqueConstraint(
                fields=["event", "field"], name="accounts_auditeventchange_field_once_per_event"
            ),
        ]

    def __str__(self) -> str:
        return self.field
