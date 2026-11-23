"""What every page needs to know about the public demonstration instance (ADR-0024).

A context processor: whether the page carries the instance's notice, and
whether registration and password reset are open, so that no page offers
what the instance has closed. Elsewhere the notice is absent and both are
open.
"""

from typing import Any

from django.conf import settings
from django.http import HttpRequest

from caipo.accounts import selectors
from caipo.accounts.selectors import AuthenticationContext, Permission
from caipo.core.shared_account import is_shared_account

# What the pages neither offer nor open to the shared account: the same
# changes its services refuse (ADR-0024 point 5).
SHARED_WITHHELD = frozenset({Permission.MFA_MANAGE_OWN, Permission.ARTICLES_SUBMIT})


def instance(request: HttpRequest) -> dict[str, Any]:
    """Return the instance's switches under `instance`, for the templates."""
    return {
        "instance": {
            "demonstration": settings.DEMONSTRATION_INSTANCE,
            "registration_open": settings.REGISTRATION_OPEN,
            "password_reset_open": settings.PASSWORD_RESET_OPEN,
        }
    }


def permissions_shown(context: AuthenticationContext | None) -> frozenset[Permission]:
    """The permissions the pages act on: the account's, less what the shared account is not given.

    The authorization policy itself reads no setting; this narrows only what
    the web layer opens and offers. The services refuse the same changes.
    """
    held = selectors.permissions_of(context)
    if context is not None and is_shared_account(context.user):
        return held - SHARED_WITHHELD
    return held


def may(context: AuthenticationContext | None, permission: Permission) -> bool:
    """Whether a page may open or offer what needs this permission, for this context."""
    return permission in permissions_shown(context)
