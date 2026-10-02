"""Users, the record of their roles, and the record of sign-ins (ADR-0007).

TOTP, the general audit record, and redaction records are not here yet.
"""

import unicodedata
from typing import Any, ClassVar, NoReturn

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from caipo.accounts.authorization import Role


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

        With no password the account gets an unusable one and cannot sign in
        until a password is set. Raises ValueError if the email is empty, and
        IntegrityError if an account with that email already exists.
        """
        email = self.normalize_email(email)
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=email)
        user.set_password(password)
        user.save(using=self._db)
        return user


class User(AbstractBaseUser):
    """An authenticated account, identified by its email address.

    There is deliberately no is_staff or is_superuser flag, and no role field.
    Access follows from the roles recorded in RoleEvent, and a superuser flag
    would bypass the deny-by-default permission checks they require.
    """

    email = models.EmailField(_("email address"), unique=True)
    is_active = models.BooleanField(_("active"), default=True)
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
        ]

    def __str__(self) -> str:
        return self.email


class AppendOnlyError(Exception):
    """An attempt was made to change or delete a record that is append-only."""


class RoleEventType(models.TextChoices):
    GRANTED = "granted", _("Granted")
    REVOKED = "revoked", _("Revoked")


class AppendOnlyQuerySet[M: models.Model](models.QuerySet[M]):
    """Refuses the bulk operations that would rewrite history."""

    def update(self, **kwargs: Any) -> NoReturn:
        raise AppendOnlyError("Append-only records are never updated.")

    def bulk_update(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise AppendOnlyError("Append-only records are never updated.")

    def delete(self) -> NoReturn:
        raise AppendOnlyError("Append-only records are never deleted.")


class AppendOnlyModel(models.Model):
    """A record that is written once and never changed or removed.

    Two layers keep it so. The guards here and in AppendOnlyQuerySet stop
    application code from rewriting a record and say why. A PostgreSQL trigger,
    created by the migration that creates each table, refuses UPDATE and
    DELETE whatever sent them; it is the boundary that counts (ADR-0012).
    """

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise AppendOnlyError("Append-only records are never updated.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise AppendOnlyError("Append-only records are never deleted.")


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


class AuthenticationEvent(AppendOnlyModel):
    """One sign-in, failed sign-in, or sign-out.

    Append-only, and deliberately small. It records that something happened,
    when, to which account if that is known, and under which request. It is
    also what sign-in throttling counts. It is not the general audit record.

    It never holds a password, a password hash, a session identifier, or
    anything else from the request. What was typed as the email address and
    where the request came from are kept only as keyed hashes: enough to count
    attempts that belong together, not enough to read back what was submitted.
    People do type passwords into the email field.
    """

    event_type = models.CharField(_("event type"), max_length=20, choices=AuthenticationEventType)
    # Empty for a failed sign-in with an email address that belongs to no
    # account: there is nobody to name, and naming somebody would be wrong.
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("user"),
        null=True,
        blank=True,
    )
    identifier_key = models.CharField(_("identifier key"), max_length=64)
    source_key = models.CharField(_("source key"), max_length=64)
    correlation_id = models.CharField(_("correlation ID"), max_length=32, blank=True)
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
            # Only a failure can be without a user.
            models.CheckConstraint(
                condition=models.Q(user__isnull=False)
                | models.Q(event_type=AuthenticationEventType.LOGIN_FAILURE),
                name="accounts_authenticationevent_user_known_unless_failure",
            ),
        ]
        indexes = [
            # Every sign-in attempt counts recent events by each of these.
            models.Index(
                fields=["identifier_key", "created_at"], name="accounts_authevent_identifier"
            ),
            models.Index(fields=["source_key", "created_at"], name="accounts_authevent_source"),
        ]

    def __str__(self) -> str:
        return self.event_type
