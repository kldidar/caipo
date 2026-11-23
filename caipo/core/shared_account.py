"""The shared account of the public demonstration instance (ADR-0024 point 5).

Its address and password are published on the instance's sign-in page, so it
may change nothing about itself and submit nothing in its own name. The
settings name it on the instance alone; elsewhere there is none. This is not
part of the authorization policy, which reads no setting: the services that
change an account's own second factor, and the submission of an article,
refuse it themselves, and the web layer neither offers nor opens their pages.
"""

from django.conf import settings


def is_shared_account(user: object) -> bool:
    """Whether the user is the instance's shared account, by its email address. Never raises."""
    shared = str(settings.SHARED_ACCOUNT_EMAIL)
    email = getattr(user, "email", "")
    return bool(shared) and isinstance(email, str) and email.casefold() == shared.casefold()
