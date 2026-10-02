"""The User foundation (ADR-0007).

Roles, permissions, TOTP, audit events, and redaction records are not here yet.
"""

import unicodedata
from typing import ClassVar

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _


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

    There is deliberately no is_staff or is_superuser flag. Access follows from
    the four roles of ADR-0007, which are not implemented yet, and a superuser
    flag would bypass the deny-by-default permission checks they require.
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
