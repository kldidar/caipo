"""Multi-factor authentication. Not implemented.

TOTP enrolment and verification are a later increment. This module exists so
that the rule depending on them is already enforced: until an account can
enrol, no account is enrolled, and the roles that require enrolment confer
nothing (ADR-0007 rule 4).
"""

from caipo.accounts.models import User


def is_enrolled(user: User) -> bool:
    """Return whether the account has enrolled a second factor.

    Always False: no enrolment mechanism exists. The TOTP increment replaces
    this body with a lookup of the account's confirmed device.
    """
    return False
