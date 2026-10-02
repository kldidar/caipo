"""Users and the record of their roles (ADR-0007).

TOTP, audit events, and redaction records are not here yet.
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


class RoleEventQuerySet(models.QuerySet["RoleEvent"]):
    """Refuses the bulk operations that would rewrite history."""

    def update(self, **kwargs: Any) -> NoReturn:
        raise AppendOnlyError("Role events are never updated.")

    def bulk_update(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise AppendOnlyError("Role events are never updated.")

    def delete(self) -> NoReturn:
        raise AppendOnlyError("Role events are never deleted.")


class RoleEvent(models.Model):
    """One change to the roles of one user: a role granted, or a role revoked.

    Append-only. This table is both where roles are stored and the record of
    how they came to be: a user holds a role when the latest event for that
    user and role is a grant (docs/DATA_MODEL.md, modelling principle 5). There
    is no current-role row that could be overwritten, so a role cannot change
    without a new event naming who changed it, when, and why.

    Two layers keep it append-only. The guards in this module stop application
    code from rewriting an event and say why. A PostgreSQL trigger, created by
    the migration that creates the table, refuses UPDATE and DELETE whatever
    sent them; it is the boundary that counts.
    """

    # PROTECT: an event must never disappear because an account did. Accounts
    # are deactivated or anonymised, not deleted (ADR-0007 rule 10).
    user = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="role_events", verbose_name=_("user")
    )
    role = models.CharField(_("role"), max_length=20, choices=Role)
    event_type = models.CharField(_("event type"), max_length=10, choices=RoleEventType)
    actor = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="+", verbose_name=_("actor")
    )
    reason = models.TextField(_("reason"))
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    objects = RoleEventQuerySet.as_manager()

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
        ]

    def __str__(self) -> str:
        return f"{self.role} {self.event_type}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise AppendOnlyError("Role events are never updated.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise AppendOnlyError("Role events are never deleted.")
